"""Fetch and apply 3GPP agenda-item descriptions."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import httpx
import pandas as pd
from bs4 import BeautifulSoup


TDOC_LIST_URL = "https://www.3gpp.org/ftp/Meetings_3GPP_SYNC/RAN1/Inbox/Tdoc_list"
DEFAULT_JSON_PATH = Path("docs/agenda_item_description.json")
DEFAULT_DOWNLOAD_DIR = Path("downloads/Tdoc_list")

AGENDA_ITEM_COLUMN = "Agenda item"
AGENDA_DESCRIPTION_COLUMN = "Agenda item description"

_DERIVED_SESSION_FIELDS = {
    "description",
    "agenda_descriptions",
    "agenda_description",
}


@dataclass(frozen=True)
class TdocXlsx:
    """One XLSX file advertised in the TDoc_list directory."""

    name: str
    url: str


def find_tdoc_xlsx_files(listing_url: str = TDOC_LIST_URL) -> list[TdocXlsx]:
    """Return XLSX links from a 3GPP TDoc_list directory listing."""
    resp = httpx.get(listing_url, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    files: list[TdocXlsx] = []
    for link in soup.find_all("a"):
        href = link.get("href") or ""
        text = link.get_text(" ", strip=True)
        if not href.lower().endswith(".xlsx"):
            continue
        name = unquote(text or href.rsplit("/", 1)[-1])
        files.append(TdocXlsx(name=name, url=href))
    return files


def _natural_sort_key(value: str) -> list[int | str]:
    parts = re.split(r"(\d+)", value)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def pick_tdoc_xlsx(files: list[TdocXlsx]) -> TdocXlsx:
    """Pick one XLSX file from the listing.

    The current policy picks the naturally-last filename. The caller does not
    depend on this being the newest file; it just provides a deterministic
    useful default.
    """
    if not files:
        raise ValueError("No .xlsx files found in TDoc_list listing")
    return sorted(files, key=lambda f: _natural_sort_key(f.name))[-1]


def download_tdoc_xlsx(
    xlsx: TdocXlsx,
    download_dir: Path = DEFAULT_DOWNLOAD_DIR,
) -> Path:
    """Download a TDoc-list XLSX file and return its local path."""
    download_dir.mkdir(parents=True, exist_ok=True)
    path = download_dir / xlsx.name
    resp = httpx.get(xlsx.url, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return path


def load_agenda_description_dataframe(xlsx_path: Path) -> pd.DataFrame:
    """Load the agenda-item columns from a TDoc-list XLSX file."""
    df = pd.read_excel(xlsx_path, sheet_name=0, dtype=str)
    missing = {
        col
        for col in (AGENDA_ITEM_COLUMN, AGENDA_DESCRIPTION_COLUMN)
        if col not in df.columns
    }
    if missing:
        raise ValueError(
            f"Missing required column(s) in {xlsx_path}: {', '.join(sorted(missing))}"
        )
    return df[[AGENDA_ITEM_COLUMN, AGENDA_DESCRIPTION_COLUMN]]


def _normalize_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def build_agenda_description_pairs(df: pd.DataFrame) -> list[dict[str, str]]:
    """Build unique agenda-item/description pairs from a dataframe."""
    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for _, row in df.iterrows():
        agenda_item = _normalize_cell(row.get(AGENDA_ITEM_COLUMN))
        description = _normalize_cell(row.get(AGENDA_DESCRIPTION_COLUMN))
        if not agenda_item or not description:
            continue
        key = (agenda_item, description)
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"agenda_item": agenda_item, "description": description})

    pairs.sort(key=lambda p: _natural_sort_key(p["agenda_item"]))
    return pairs


def save_agenda_description_json(
    pairs: list[dict[str, str]],
    output_path: Path = DEFAULT_JSON_PATH,
    *,
    source_file: str | None = None,
    source_url: str | None = None,
) -> None:
    """Save agenda descriptions in both list and lookup-map form."""
    descriptions: dict[str, str] = {}
    conflicts: dict[str, list[str]] = {}

    for pair in pairs:
        agenda_item = pair["agenda_item"]
        description = pair["description"]
        if agenda_item in descriptions and descriptions[agenda_item] != description:
            conflicts.setdefault(agenda_item, [descriptions[agenda_item]])
            if description not in conflicts[agenda_item]:
                conflicts[agenda_item].append(description)
            continue
        descriptions[agenda_item] = description

    payload: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": source_file,
        "source_url": source_url,
        "agenda_items": pairs,
        "descriptions": descriptions,
    }
    if conflicts:
        payload["conflicts"] = conflicts

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def update_agenda_description_json(
    listing_url: str = TDOC_LIST_URL,
    output_path: Path = DEFAULT_JSON_PATH,
    download_dir: Path = DEFAULT_DOWNLOAD_DIR,
) -> Path:
    """Fetch one TDoc-list XLSX and write agenda_item_description.json."""
    xlsx = pick_tdoc_xlsx(find_tdoc_xlsx_files(listing_url))
    xlsx_path = download_tdoc_xlsx(xlsx, download_dir)
    df = load_agenda_description_dataframe(xlsx_path)
    pairs = build_agenda_description_pairs(df)
    save_agenda_description_json(
        pairs,
        output_path,
        source_file=xlsx.name,
        source_url=xlsx.url,
    )
    return output_path


def load_agenda_description_map(
    path: Path = DEFAULT_JSON_PATH,
) -> dict[str, str]:
    """Load agenda item descriptions from JSON."""
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    descriptions = data.get("descriptions")
    if isinstance(descriptions, dict):
        return {str(k): str(v) for k, v in descriptions.items() if v is not None}

    items = data.get("agenda_items", [])
    result: dict[str, str] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            agenda_item = item.get("agenda_item")
            description = item.get("description")
            if agenda_item and description:
                result[str(agenda_item)] = str(description)
    return result


def strip_derived_description_fields(sessions: list[dict]) -> list[dict]:
    """Remove generated description fields before LLM merge comparison."""
    stripped: list[dict] = []
    for session in sessions:
        stripped.append(
            {k: v for k, v in session.items() if k not in _DERIVED_SESSION_FIELDS}
        )
    return stripped


def _split_agenda_item_field(value: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"\s*(?:,|;|\bor\b)\s*", value)
        if part.strip()
    ]


def _expand_slash_shorthand(token: str) -> list[str]:
    if "/" not in token:
        return [token]

    head, tail = token.split("/", 1)
    tail = tail.strip()
    if not tail:
        return [head]

    if "." in tail:
        return [head, tail]

    prefix = head.rsplit(".", 1)[0] if "." in head else ""
    expanded_tail = f"{prefix}.{tail}" if prefix else tail
    return [head, expanded_tail]


def _extract_agenda_tokens_from_field(value: str | None) -> list[str]:
    if not value:
        return []
    tokens: list[str] = []
    for part in _split_agenda_item_field(value):
        for match in re.finditer(
            r"\b\d+(?:\.(?:\d+|[xX]))*(?:/\d+(?:\.\d+)*)?\b",
            part,
        ):
            tokens.extend(_expand_slash_shorthand(match.group(0)))
    return tokens


def _extract_agenda_tokens_from_name(value: str | None) -> list[str]:
    if not value:
        return []

    stripped = value.strip()
    leading = re.match(
        r"^(?:AI\s+)?\.?\s*(\d+(?:\.(?:\d+|[xX]))*(?:/\d+(?:\.\d+)*)?)\b",
        stripped,
        re.IGNORECASE,
    )
    if leading and ("." in leading.group(1) or stripped.upper().startswith("AI ")):
        return _expand_slash_shorthand(leading.group(1))

    tokens: list[str] = []
    for match in re.finditer(r"\b\d+(?:\.(?:\d+|[xX]))+(?:/\d+)?\b", stripped):
        tokens.extend(_expand_slash_shorthand(match.group(0)))
    return tokens


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().strip(".")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_session_agenda_items(session: dict) -> list[str]:
    """Extract agenda item candidates from a merged session dict."""
    agenda_item = session.get("agenda_item")
    name = session.get("name")

    tokens = _extract_agenda_tokens_from_field(agenda_item)
    if not tokens:
        tokens = _extract_agenda_tokens_from_name(name)
    return _ordered_unique(tokens)


def _parent_candidates(agenda_item: str) -> list[str]:
    candidates = [agenda_item]
    if agenda_item.lower().endswith(".x"):
        candidates.append(agenda_item[:-2])

    base = candidates[-1]
    while "." in base:
        base = base.rsplit(".", 1)[0]
        candidates.append(base)
    return _ordered_unique(candidates)


def _description_hierarchy(
    agenda_item: str,
    descriptions: dict[str, str],
) -> dict[str, object] | None:
    matched = None
    for candidate in _parent_candidates(agenda_item):
        if candidate in descriptions:
            matched = candidate
            break

    if matched is None:
        return None

    hierarchy: list[dict[str, object]] = []
    parts = matched.split(".")
    prefixes = [".".join(parts[: i + 1]) for i in range(len(parts))]
    for prefix in prefixes:
        description = descriptions.get(prefix)
        hierarchy.append(
            {
                "agenda_item": prefix,
                "description": description,
                "has_description": description is not None,
            }
        )

    return {
        "agenda_item": agenda_item,
        "matched_agenda_item": matched,
        "description": descriptions[matched],
        "hierarchy": hierarchy,
    }


def annotate_sessions_with_agenda_descriptions(
    sessions: list[dict],
    descriptions: dict[str, str] | None = None,
) -> list[dict]:
    """Add generated agenda description fields to merged session dicts."""
    descriptions = descriptions if descriptions is not None else load_agenda_description_map()
    stripped = strip_derived_description_fields(sessions)
    if not descriptions:
        return stripped

    annotated: list[dict] = []
    for session in stripped:
        items = []
        for agenda_item in extract_session_agenda_items(session):
            item = _description_hierarchy(agenda_item, descriptions)
            if item:
                items.append(item)

        if items:
            session = dict(session)
            session["description"] = items[0]["description"]
            session["agenda_descriptions"] = items
        annotated.append(session)

    return annotated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a 3GPP RAN1 TDoc-list XLSX and build agenda descriptions JSON."
    )
    parser.add_argument("--listing-url", default=TDOC_LIST_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    args = parser.parse_args()

    output = update_agenda_description_json(
        listing_url=args.listing_url,
        output_path=args.output,
        download_dir=args.download_dir,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
