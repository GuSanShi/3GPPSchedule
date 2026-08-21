"""LLM wrapper — OpenAI-compatible API for 3GPP Schedule Parser.

Supports any OpenAI-compatible endpoint (DeepSeek, Qwen, etc.).
Configure via env vars:
  LLM_API_KEY       — API key (primary)
  DEEPSEEK_API_KEY  — fallback API key
  LLM_BASE_URL      — API base URL (default: https://api.deepseek.com)
  LLM_MODEL         — Model name (default: deepseek-chat)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from openai import OpenAI


def llm_json(
    *,
    prompt: str,
    system_instruction: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    timeout_ms: int = 120_000,
    base_url: str | None = None,
    json_schema: dict | None = None,
) -> dict[str, Any] | None:
    """Call an OpenAI-compatible API and return parsed JSON.

    Args:
        prompt: User message text.
        system_instruction: Optional system prompt.
        api_key: API key. Falls back to LLM_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY.
        model: Model name. Falls back to LLM_MODEL env, then deepseek-chat.
        temperature: Sampling temperature (default: 0.0).
        timeout_ms: Request timeout in milliseconds (default: 120s).
        base_url: API base URL. Falls back to LLM_BASE_URL env, then https://api.deepseek.com.
        json_schema: If provided, instructs the model to output JSON matching
            this schema (via system prompt guidance).

    Returns:
        Parsed JSON dict, or None on failure.
    """
    resolved_key = (
        api_key
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not resolved_key:
        print("Warning: No API key set (try LLM_API_KEY or DEEPSEEK_API_KEY)")
        return None

    resolved_model = model or os.environ.get("LLM_MODEL") or "deepseek-chat"
    resolved_base_url = base_url or os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com"

    client = OpenAI(
        api_key=resolved_key,
        base_url=resolved_base_url,
        timeout=timeout_ms / 1000,
        max_retries=2,
    )

    messages: list[dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    # Append schema guidance to prompt if provided
    enhanced_prompt = prompt
    if json_schema:
        schema_hint = (
            "\n\nYou MUST respond with valid JSON only, matching this schema:\n"
            f"{json.dumps(json_schema, indent=2, ensure_ascii=False)}"
        )
        enhanced_prompt = prompt + schema_hint

    messages.append({"role": "user", "content": enhanced_prompt})

    MAX_RETRIES = 3
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                lines = text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            return json.loads(text)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (attempt + 1)
                print(f"  LLM retry({attempt+1}, wait {wait}s)...", flush=True)
                time.sleep(wait)
            else:
                print(f"  LLM call failed after {MAX_RETRIES} retries: {e}")

    return None