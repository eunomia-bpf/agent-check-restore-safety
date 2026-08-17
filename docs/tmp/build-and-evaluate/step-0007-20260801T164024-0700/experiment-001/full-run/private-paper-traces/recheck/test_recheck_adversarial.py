"""Independent synthetic attacks against the repaired private-trace method.

This file deliberately encodes the *claimed* fail-closed contract.  Failures
therefore identify places where the current extractor accepts an input that
the report says should be rejected.  It imports no private trace and uses only
temporary synthetic files and databases.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


BASE = Path(__file__).resolve().parent.parent
MODULE_PATH = BASE / "extract_private_paper_traces.py"
SPEC = importlib.util.spec_from_file_location("rechecked_extractor", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 8, 2, 3, 11, 1, tzinfo=UTC)
CUTOFF_EPOCH = int(CUTOFF.timestamp())
CUTOFF_ISO = extractor.iso_utc(CUTOFF)
BEFORE = "2026-08-02T03:00:00Z"
AFTER = "2026-08-02T03:20:00Z"
KEY = b"independent-synthetic-review-key-32-bytes"


def event(kind: str, payload: dict, timestamp: str | None = BEFORE) -> bytes:
    value = {"type": kind, "payload": payload}
    if timestamp is not None:
        value["timestamp"] = timestamp
    return json.dumps(value, sort_keys=True).encode("utf-8") + b"\n"


def user_header(thread_id: str, timestamp: str | None = BEFORE) -> bytes:
    return event(
        "session_meta",
        {
            "id": thread_id,
            "cli_version": "0.145.0",
            "history_mode": "legacy",
            "source": "vscode",
            "thread_source": "user",
        },
        timestamp,
    )


def subagent_header(
    thread_id: str, parent_id: str, timestamp: str | None = BEFORE
) -> bytes:
    return event(
        "session_meta",
        {
            "id": thread_id,
            "cli_version": "0.145.0",
            "history_mode": "legacy",
            "multi_agent_version": "v2",
            "parent_thread_id": parent_id,
            "thread_source": "subagent",
            "source": {
                "subagent": {"thread_spawn": {"parent_thread_id": parent_id}}
            },
        },
        timestamp,
    )


def task_started(timestamp: str | None = BEFORE) -> bytes:
    return event("event_msg", {"type": "task_started"}, timestamp)


def marker(
    timestamp: str | None = BEFORE, *, trigger_turn: bool = True
) -> bytes:
    return event(
        "inter_agent_communication_metadata",
        {"trigger_turn": trigger_turn},
        timestamp,
    )


def call(
    call_id: object,
    *,
    kind: str = "custom_tool_call",
    timestamp: str | None = BEFORE,
    input_text: str = "synthetic command body",
) -> bytes:
    payload = {
        "type": kind,
        "name": "exec" if kind == "custom_tool_call" else "spawn_agent",
        "call_id": call_id,
    }
    if kind == "custom_tool_call":
        payload.update(status="completed", input=input_text)
    return event("response_item", payload, timestamp)


def result(
    call_id: object,
    *,
    kind: str = "custom_tool_call_output",
    timestamp: str | None = BEFORE,
) -> bytes:
    return event(
        "response_item",
        {
            "type": kind,
            "call_id": call_id,
            "output": [
                {"type": "input_text", "text": "synthetic private result body"}
            ],
        },
        timestamp,
    )


def write_rollout(path: Path, rows: list[bytes]) -> None:
    with path.open("wb") as stream:
        stream.writelines(rows)


def record(
    thread_id: str,
    path: Path,
    *,
    depth: int = 0,
    parent: str | None = None,
) -> dict:
    return {
        "id": thread_id,
        "depth": depth,
        "expected_parent_id": parent,
        "rollout_path": str(path),
        "cli_version": "0.145.0",
        "history_mode": "legacy",
    }


def make_db(
    path: Path,
    threads: list[tuple[str, int, Path, str]],
    edges: list[tuple[str, str, str]],
) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE threads(
          id TEXT PRIMARY KEY,
          created_at INTEGER NOT NULL,
          rollout_path TEXT NOT NULL,
          model TEXT,
          reasoning_effort TEXT,
          cli_version TEXT,
          history_mode TEXT,
          source TEXT,
          thread_source TEXT
        );
        CREATE TABLE thread_spawn_edges(
          parent_thread_id TEXT NOT NULL,
          child_thread_id TEXT NOT NULL,
          status TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?)",
        [
            (
                thread_id,
                created_at,
                str(rollout),
                "synthetic-model",
                "high",
                "0.145.0",
                "legacy",
                "synthetic-source",
                provenance,
            )
            for thread_id, created_at, rollout, provenance in threads
        ],
    )
    connection.executemany("INSERT INTO thread_spawn_edges VALUES(?,?,?)", edges)
    connection.commit()
    connection.close()


class TimestampedBoundaryContractTests(unittest.TestCase):
    def test_matching_header_without_timestamp_must_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(rollout, [user_header("synthetic-root", None), call("c")])
            with self.assertRaisesRegex(RuntimeError, "timestamp|header"):
                extractor.process_codex_rollout(
                    record("synthetic-root", rollout), CUTOFF
                )

    def test_native_task_start_without_timestamp_must_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    subagent_header("synthetic-child", "synthetic-parent"),
                    task_started(None),
                    marker(),
                    call("native"),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "timestamp|task start"):
                extractor.process_codex_rollout(
                    record(
                        "synthetic-child",
                        rollout,
                        depth=1,
                        parent="synthetic-parent",
                    ),
                    CUTOFF,
                )

    def test_native_marker_without_timestamp_must_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    subagent_header("synthetic-child", "synthetic-parent"),
                    task_started(),
                    marker(None),
                    call("native"),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "timestamp|marker"):
                extractor.process_codex_rollout(
                    record(
                        "synthetic-child",
                        rollout,
                        depth=1,
                        parent="synthetic-parent",
                    ),
                    CUTOFF,
                )

    def test_first_spawn_marker_must_trigger_a_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    subagent_header("synthetic-child", "synthetic-parent"),
                    task_started(),
                    marker(trigger_turn=False),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "trigger"):
                extractor.process_codex_rollout(
                    record(
                        "synthetic-child",
                        rollout,
                        depth=1,
                        parent="synthetic-parent",
                    ),
                    CUTOFF,
                )


class PhysicalCutoffAndSnapshotTests(unittest.TestCase):
    def test_future_row_physically_hides_older_and_malformed_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    user_header("synthetic-root"),
                    call("before"),
                    event("event_msg", {"type": "task_complete"}, AFTER),
                    call("backdated-after-stop"),
                    call("missing-after-stop", timestamp=None),
                    user_header("synthetic-root"),
                ],
            )
            part = extractor.process_codex_rollout(
                record("synthetic-root", rollout), CUTOFF
            )
        self.assertTrue(part["future_stop_found"])
        self.assertEqual(["before"], [item[0] for item in part["calls"]])
        self.assertEqual(1, part["matching_header_count"])

    def test_two_pass_file_change_must_fail_closed(self) -> None:
        """Append a second local header between the discovery and count pass."""
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(rollout, [user_header("synthetic-root"), call("before")])
            original_open = Path.open
            read_count = 0

            class MutatingContext:
                def __init__(self, handle):
                    self.handle = handle

                def __enter__(self):
                    return self.handle.__enter__()

                def __exit__(self, exc_type, exc, traceback):
                    nonlocal read_count
                    outcome = self.handle.__exit__(exc_type, exc, traceback)
                    with original_open(rollout, "ab") as sink:
                        sink.write(user_header("synthetic-root"))
                    read_count += 1
                    return outcome

            def opened(path_self, mode="r", *args, **kwargs):
                handle = original_open(path_self, mode, *args, **kwargs)
                if path_self == rollout and mode == "rb" and read_count == 0:
                    return MutatingContext(handle)
                return handle

            with mock.patch.object(Path, "open", new=opened):
                with self.assertRaisesRegex(RuntimeError, "changed|snapshot|header"):
                    extractor.process_codex_rollout(
                        record("synthetic-root", rollout), CUTOFF
                    )


class LineageIntegrityRecheckTests(unittest.TestCase):
    def _files(self, directory: Path) -> tuple[Path, Path, Path]:
        root = directory / "root.jsonl"
        child = directory / "child.jsonl"
        other = directory / "other.jsonl"
        write_rollout(root, [user_header("r")])
        write_rollout(child, [subagent_header("c", "r"), task_started(), marker()])
        write_rollout(other, [user_header("o")])
        return root, child, other

    def test_duplicate_edge_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, child, _ = self._files(base)
            db = base / "db.sqlite3"
            make_db(
                db,
                [
                    ("r", CUTOFF_EPOCH - 2, root, "user"),
                    ("c", CUTOFF_EPOCH - 1, child, "subagent"),
                ],
                [("r", "c", "open"), ("r", "c", "open")],
            )
            with self.assertRaisesRegex(RuntimeError, "duplicate"):
                extractor.read_lineage(db, "r", CUTOFF_EPOCH, KEY)

    def test_multi_parent_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, child, other = self._files(base)
            db = base / "db.sqlite3"
            make_db(
                db,
                [
                    ("r", CUTOFF_EPOCH - 2, root, "user"),
                    ("c", CUTOFF_EPOCH - 1, child, "subagent"),
                    ("o", CUTOFF_EPOCH - 3, other, "user"),
                ],
                [("r", "c", "open"), ("o", "c", "closed")],
            )
            with self.assertRaisesRegex(RuntimeError, "one selected parent"):
                extractor.read_lineage(db, "r", CUTOFF_EPOCH, KEY)

    def test_cycle_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, child, _ = self._files(base)
            db = base / "db.sqlite3"
            make_db(
                db,
                [
                    ("r", CUTOFF_EPOCH - 2, root, "user"),
                    ("c", CUTOFF_EPOCH - 1, child, "subagent"),
                ],
                [("r", "c", "open"), ("c", "r", "closed")],
            )
            with self.assertRaisesRegex(RuntimeError, "tree|cycle"):
                extractor.read_lineage(db, "r", CUTOFF_EPOCH, KEY)

    def test_external_root_edge_is_committed_and_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            external, selected, _ = self._files(base)
            db = base / "db.sqlite3"
            make_db(
                db,
                [
                    ("external", CUTOFF_EPOCH - 2, external, "user"),
                    ("selected", CUTOFF_EPOCH - 1, selected, "subagent"),
                ],
                [("external", "selected", "closed")],
            )
            records, metadata = extractor.read_lineage(
                db, "selected", CUTOFF_EPOCH, KEY
            )
        self.assertEqual(1, len(records))
        self.assertEqual("external", records[0]["expected_parent_id"])
        self.assertTrue(metadata["root_has_external_parent"])
        self.assertRegex(metadata["edge_snapshot_hmac_sha256"], r"^[0-9a-f]{64}$")


class ProtocolAccountingRecheckTests(unittest.TestCase):
    def test_duplicate_and_kind_mismatch_never_form_strict_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    user_header("synthetic-root"),
                    call("duplicate"),
                    call("duplicate"),
                    result("duplicate"),
                    call("mismatch", kind="function_call"),
                    result("mismatch", kind="custom_tool_call_output"),
                    call("paired", kind="function_call"),
                    result("paired", kind="function_call_output"),
                ],
            )
            counts = extractor._correlate_part(
                extractor.process_codex_rollout(
                    record("synthetic-root", rollout), CUTOFF
                )
            )
        self.assertEqual(4, counts["raw_call_events"])
        self.assertEqual(1, counts["duplicate_call_id_events_within_thread"])
        self.assertEqual(1, counts["kind_mismatched_singleton_ids_within_thread"])
        self.assertEqual(1, counts["kind_compatible_one_to_one_pairs_within_thread"])
        self.assertEqual(3, counts["call_events_without_one_to_one_pair"])
        self.assertEqual(2, counts["result_events_without_one_to_one_pair"])


class PublishedAggregateArithmeticTests(unittest.TestCase):
    def test_published_summary_satisfies_all_independent_identities(self) -> None:
        document = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))
        codex = document["codex"]
        lineage = codex["lineage"]
        fidelity = codex["source_fidelity"]
        protocol = codex["tool_protocol"]
        checks = [
            lineage["spawn_edges"] == lineage["threads"] - 1,
            *(
                sum(lineage[name].values()) == lineage["threads"]
                for name in (
                    "depth_counts",
                    "role_counts",
                    "model_category_counts",
                    "reasoning_effort_counts",
                )
            ),
            *(
                sum(fidelity[name].values()) == fidelity["rollout_files"]
                for name in (
                    "header_provenance_counts",
                    "supported_cli_version_counts",
                )
            ),
            fidelity["matching_local_headers"]
            == fidelity["matching_native_boundaries"]
            == fidelity["rollout_files"],
            fidelity["files_stopped_at_first_future_timestamp"]
            + fidelity["files_committed_at_snapshot_eof"]
            == fidelity["rollout_files"],
            sum(codex["event_shapes"]["top_level_type_counts"].values())
            == fidelity["selected_exact_timestamped_rows"],
            sum(protocol["call_kind_counts"].values())
            == protocol["raw_call_events"],
            sum(protocol["call_tool_counts"].values())
            == protocol["raw_call_events"],
            protocol["calls_with_string_id"]
            + protocol["calls_without_string_id"]
            == protocol["raw_call_events"],
            protocol["unique_call_ids_within_thread_sum"]
            + protocol["duplicate_call_id_events_within_thread"]
            == protocol["calls_with_string_id"],
            sum(protocol["result_kind_counts"].values())
            == protocol["raw_result_events"],
            protocol["results_with_string_id"]
            + protocol["results_without_string_id"]
            == protocol["raw_result_events"],
            protocol["unique_result_ids_within_thread_sum"]
            + protocol["duplicate_result_id_events_within_thread"]
            == protocol["results_with_string_id"],
            protocol["kind_compatible_one_to_one_pairs_within_thread"]
            + protocol["call_events_without_one_to_one_pair"]
            == protocol["raw_call_events"],
            protocol["kind_compatible_one_to_one_pairs_within_thread"]
            + protocol["result_events_without_one_to_one_pair"]
            == protocol["raw_result_events"],
            sum(protocol["one_to_one_pair_tool_counts"].values())
            == protocol["kind_compatible_one_to_one_pairs_within_thread"],
            sum(protocol["call_events_without_one_to_one_pair_by_tool"].values())
            == protocol["call_events_without_one_to_one_pair"],
            sum(protocol["one_to_one_exec_result_marker_counts"].values())
            == protocol["one_to_one_pair_tool_counts"]["exec"],
            sum(
                sum(role_counts.values())
                for role_counts in protocol["tool_calls_by_role"].values()
            )
            == protocol["raw_call_events"],
            all(
                sum(
                    role.get(name, 0)
                    for role in codex["lifecycle_observations"][
                        "counts_by_role"
                    ].values()
                )
                == count
                for name, count in codex["lifecycle_observations"]["counts"].items()
            ),
        ]
        self.assertEqual(24, len(checks))
        self.assertTrue(all(checks))


class PrivacyAndClaudeRecheckTests(unittest.TestCase):
    def test_output_dictionary_keys_must_be_allowlisted(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "allowlist|privacy"):
            extractor.privacy_assertions({"synthetic-secret-key": 1}, [])

    def test_digest_shaped_arbitrary_value_must_not_bypass_field_policy(self) -> None:
        token = "a" * 40
        with self.assertRaisesRegex(RuntimeError, "allowlist|privacy"):
            extractor.privacy_assertions({"value": token}, [])

    def test_empty_claude_session_id_must_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            index = home / "sessions-index.json"
            index.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "sessionId": "",
                                "fullPath": str(home / "absent.jsonl"),
                                "messageCount": 1,
                                "isSidechain": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "session ID|schema"):
                extractor.collect_claude(index, home)

    def test_filename_walk_preserves_four_errors_as_uncertainty(self) -> None:
        error = OSError("synthetic walk failure")

        def fake_walk(_home, *, followlinks, onerror):
            self.assertFalse(followlinks)
            for _ in range(4):
                onerror(error)
            return iter(())

        with mock.patch.object(extractor.os, "walk", new=fake_walk):
            result_value = extractor.exact_id_filename_scan(
                Path("/synthetic"), {"synthetic-id"}
            )
        self.assertEqual(4, result_value["walk_errors_observed"])
        self.assertEqual(0, result_value["matching_nodes"])


if __name__ == "__main__":
    unittest.main()
