import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import _agenda_state_for_save, _extract_meeting_name, main


class ExtractMeetingNameTests(unittest.TestCase):
    def test_extracts_basic_ran_meeting_name(self):
        self.assertEqual(
            _extract_meeting_name(Path("RAN1#124 online and offline schedules - v00.docx")),
            "RAN1#124",
        )

    def test_preserves_meeting_suffixes(self):
        self.assertEqual(
            _extract_meeting_name(Path("RAN1#124bis online and offline schedules - v00.docx")),
            "RAN1#124bis",
        )

    def test_falls_back_to_file_stem_when_no_meeting_name_is_found(self):
        self.assertEqual(
            _extract_meeting_name(Path("custom schedule name.docx")),
            "custom schedule name",
        )


class AgendaStateForSaveTests(unittest.TestCase):
    def test_uses_description_json_when_remote_agenda_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "agenda_item_description.json"
            json_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-19T23:24:55+00:00",
                        "source_type": "agenda_docx",
                        "source_file": "R1-2601750_Draft agenda.docx",
                        "source_url": "https://example.com/Agenda/R1-2601750.zip",
                        "source_uploaded_at": "2026-05-18T08:30:00",
                        "source_agenda_file": "R1-2601750.zip",
                    }
                )
            )

            state = _agenda_state_for_save(None, None, json_path)

        self.assertEqual(state["name"], "R1-2601750.zip")
        self.assertEqual(state["document_file"], "R1-2601750_Draft agenda.docx")
        self.assertEqual(state["description_json"], str(json_path))
        self.assertEqual(state["description_source_agenda_file"], "R1-2601750.zip")


class MainChairNotesLookupTests(unittest.TestCase):
    @patch("main.save_html", return_value="docs/index.html")
    @patch("main.fill_missing_groups", side_effect=lambda sessions: sessions)
    @patch("main.normalize_group_headers", side_effect=lambda sessions: sessions)
    @patch("main.parse_time_slots", return_value=[])
    @patch("main.collect_time_slot_data", return_value=[])
    @patch("main.build_room_list", return_value={})
    @patch("main.parse_docx", return_value=([], []))
    @patch("main.load_schedule_state", return_value={})
    @patch("main.find_chair_notes_docx", return_value=None)
    @patch("main.find_local_latest_agenda", return_value=None)
    @patch("main.download_latest_agenda", return_value=None)
    @patch("main.download_latest_chair_notes", return_value=None)
    @patch("main.load_config", return_value={
        "meeting_sync": None,
        "meeting_specific": [],
        "inbox_urls": ["https://example.com/legacy/Inbox/", "https://example.com/next/Inbox/"],
        "agenda_urls": [],
        "extra_folders": [{"url": "https://example.com/custom/Chair_notes/", "name": "Chair_notes"}],
    })
    def test_passes_configured_sources_to_chair_notes_download(
        self,
        mock_load_config,
        mock_download_latest_chair_notes,
        mock_download_latest_agenda,
        mock_find_local_latest_agenda,
        mock_find_chair_notes_docx,
        mock_load_schedule_state,
        mock_parse_docx,
        mock_build_room_list,
        mock_collect_time_slot_data,
        mock_parse_time_slots,
        mock_normalize_group_headers,
        mock_fill_missing_groups,
        mock_save_html,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "custom schedule.docx"
            docx_path.write_text("placeholder")

            args = argparse.Namespace(
                local=str(docx_path),
                no_download=False,
                output="docs/index.html",
                rebuild_slots=False,
            )

            with patch("argparse.ArgumentParser.parse_args", return_value=args):
                with patch.dict(
                    os.environ,
                    {
                        "SCHEDULE_CONTACT_NAME": "Tester",
                        "SCHEDULE_CONTACT_EMAIL": "tester@example.com",
                    },
                    clear=False,
                ):
                    main()

        mock_download_latest_chair_notes.assert_called_once_with(
            docx_path.parent,
            urls=["https://example.com/legacy/Inbox/", "https://example.com/next/Inbox/"],
            extra_folders=[{"url": "https://example.com/custom/Chair_notes/", "name": "Chair_notes"}],
        )


class MainExtraFilesWiringTests(unittest.TestCase):
    """Wiring assertions: extra_files -> download -> schedule / chair notes."""

    def _enter_common(self, extra_files: list, no_download: bool):
        """Enter the common patch stack shared by all wiring tests."""
        import contextlib

        stack = contextlib.ExitStack()
        args = argparse.Namespace(
            local=None,
            no_download=no_download,
            output="docs/index.html",
            rebuild_slots=False,
        )
        stack.enter_context(
            patch("argparse.ArgumentParser.parse_args", return_value=args)
        )
        stack.enter_context(
            patch.dict(
                os.environ,
                {"SCHEDULE_CONTACT_NAME": "Tester", "SCHEDULE_CONTACT_EMAIL": "t@e.com"},
                clear=False,
            )
        )
        stack.enter_context(
            patch(
                "main.load_config",
                return_value={
                    "meeting_sync": None,
                    "meeting_specific": [],
                    "inbox_urls": ["https://example.com/Inbox/"],
                    "agenda_urls": [],
                    "extra_folders": [],
                    "extra_files": extra_files,
                },
            )
        )
        # CRITICAL: return {} so tz detection runs instead of reusing a cached tz.
        stack.enter_context(patch("main.load_schedule_state", return_value={}))
        stack.enter_context(patch("main.parse_docx", return_value=([], [])))
        stack.enter_context(patch("main.build_room_list", return_value={}))
        stack.enter_context(patch("main.collect_time_slot_data", return_value=[]))
        stack.enter_context(patch("main.parse_time_slots", return_value=[]))
        stack.enter_context(
            patch("main.normalize_group_headers", side_effect=lambda s: s)
        )
        stack.enter_context(patch("main.fill_missing_groups", side_effect=lambda s: s))
        stack.enter_context(patch("main.save_schedule_state", return_value=None))
        stack.enter_context(patch("main.save_html", return_value="docs/index.html"))
        stack.enter_context(patch("main.find_local_latest_agenda", return_value=None))
        stack.enter_context(patch("main.find_local_vice_chair_schedules", return_value={}))
        # Defensive: keep local/FTP local-schedule fallbacks inert.
        stack.enter_context(patch("main.find_local_latest_schedule", return_value=None))
        stack.enter_context(patch("main.download_latest_schedule", return_value=None))
        return stack

    def test_download_path_schedule_entry_merged_into_local_sources(self):
        """Download path: schedule entry becomes a local ScheduleSource fed to
        discover_schedule_sources; external state is persisted."""
        from models import ScheduleSource
        from downloader import EXTRA_FILES_DIR

        url = "https://x/e.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            docx = Path(tmpdir) / "RAN1#126 online and offline schedules - v01.docx"
            docx.write_text("placeholder")
            entries = [{"url": url, "type": "schedule"}]
            entry_obj = dict(entries[0], person_name=None, is_main=True)
            # main builds the merged source with folder_name=EXTRA_FILES_DIR.name,
            # so this must match for the dataclass equality in assertIn below.
            extra_source = ScheduleSource(
                folder_name=EXTRA_FILES_DIR.name,
                person_name=None,
                is_main=True,
                file_info={"name": docx.name, "url": url, "uploaded_at": None},
                local_path=docx,
            )

            with self._enter_common(entries, no_download=False) as stack:
                stack.enter_context(
                    patch("main.find_local_schedule_sources", return_value=([], None))
                )
                stack.enter_context(patch("main.find_chair_notes_docx", return_value=None))
                stack.enter_context(
                    patch("main.download_latest_chair_notes", return_value=None)
                )
                stack.enter_context(
                    patch("main.extract_meeting_location", return_value="Malta, Malta")
                )
                stack.enter_context(
                    patch("main.get_timezone_from_location", return_value="Europe/Malta")
                )
                mock_dl = stack.enter_context(
                    patch(
                        "main.download_external_files",
                        return_value=([(entry_obj, docx)], {url: "deadbeef"}),
                    )
                )
                mock_save = stack.enter_context(patch("main.save_external_files_state"))
                mock_disc = stack.enter_context(
                    patch("main.discover_schedule_sources", return_value=[extra_source])
                )
                stack.enter_context(
                    patch("main.download_all_schedules", return_value=(docx, {}))
                )

                main()

                mock_dl.assert_called_once_with(entries)
                mock_save.assert_called_once_with({"files": {url: "deadbeef"}})
                self.assertIn(
                    extra_source,
                    mock_disc.call_args.kwargs["local_schedule_sources"],
                )

    def test_download_path_chair_notes_entry_used_in_tz_block_before_ftp(self):
        """TZ block: an extra_files chair_notes entry is used for location
        extraction, and the FTP chair-notes download is skipped."""
        from models import ScheduleSource

        url = "https://x/e.docx"
        with tempfile.TemporaryDirectory() as tmpdir:
            docx = Path(tmpdir) / "RAN1#126 online and offline schedules - v01.docx"
            docx.write_text("placeholder")
            chair_docx = Path(tmpdir) / "chair-notes.docx"
            chair_docx.write_text("placeholder")

            entries = [{"url": url, "type": "chair_notes"}]
            main_src = ScheduleSource(
                folder_name="Chair_notes",
                person_name=None,
                is_main=True,
                file_info={
                    "name": docx.name,
                    "url": "https://ftpx/m.docx",
                    "uploaded_at": None,
                },
                local_path=None,
            )

            with self._enter_common(entries, no_download=False) as stack:
                stack.enter_context(
                    patch("main.find_local_schedule_sources", return_value=([], None))
                )
                stack.enter_context(
                    patch(
                        "main.download_external_files",
                        return_value=(
                            [(dict(entries[0], is_main=None), chair_docx)],
                            {url: "abc"},
                        ),
                    )
                )
                stack.enter_context(patch("main.save_external_files_state"))
                stack.enter_context(
                    patch("main.discover_schedule_sources", return_value=[main_src])
                )
                stack.enter_context(
                    patch("main.download_all_schedules", return_value=(docx, {}))
                )
                stack.enter_context(patch("main.find_chair_notes_docx", return_value=None))
                mock_loc = stack.enter_context(
                    patch("main.extract_meeting_location", return_value="Malta, Malta")
                )
                stack.enter_context(
                    patch("main.get_timezone_from_location", return_value="Europe/Malta")
                )
                mock_ftp = stack.enter_context(patch("main.download_latest_chair_notes"))

                main()

                mock_loc.assert_called_once_with(chair_docx)
                mock_ftp.assert_not_called()

    def test_no_download_scans_extra_files_dir(self):
        """no_download: the REAL scanner runs against a temp EXTRA_FILES_DIR;
        the scan-picked schedule becomes the main doc and the chair notes in
        the same dir feed the tz block."""
        from downloader import find_local_schedule_sources as real_find

        with tempfile.TemporaryDirectory() as tmpdir:
            extra = Path(tmpdir) / "extra_files"
            extra.mkdir()
            sched = extra / "RAN1#126 online and offline schedules - v02.docx"
            chair = extra / "chair notes - v01.docx"
            sched.write_text("placeholder")
            chair.write_text("placeholder")

            with self._enter_common([], no_download=True) as stack:
                stack.enter_context(patch("main.EXTRA_FILES_DIR", extra))
                stack.enter_context(
                    patch(
                        "main.find_local_schedule_sources",
                        side_effect=lambda ref_dir=None, preferred_meeting_id=None: (
                            ([], None)
                            if ref_dir is None
                            else real_find(ref_dir, preferred_meeting_id)
                        ),
                    )
                )
                # NOTE: main.find_chair_notes_docx is NOT patched, so the REAL
                # scanner runs against docx_path.parent (== extra) and finds chair.
                mock_loc = stack.enter_context(
                    patch("main.extract_meeting_location", return_value="Malta, Malta")
                )
                stack.enter_context(
                    patch("main.get_timezone_from_location", return_value="Europe/Malta")
                )
                mock_ftp = stack.enter_context(patch("main.download_latest_chair_notes"))
                mock_parse = stack.enter_context(
                    patch("main.parse_docx", return_value=([], []))
                )

                main()

                self.assertEqual(mock_parse.call_args[0][0], sched)
                self.assertEqual(mock_loc.call_args[0][0], chair)
                mock_ftp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
