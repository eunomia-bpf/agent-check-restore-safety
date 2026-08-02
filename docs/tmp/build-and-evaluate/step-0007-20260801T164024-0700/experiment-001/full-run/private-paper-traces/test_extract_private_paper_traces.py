"""Synthetic regression tests for the private trace extractor.

The fixtures contain no real IDs, prompts, commands, paths, or results.  They
exercise the source-format and aggregation mistakes that matter to the paper.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("extract_private_paper_traces.py")
SPEC = importlib.util.spec_from_file_location("private_trace_extractor", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 8, 2, 3, 11, 1, tzinfo=UTC)
BEFORE = "2026-08-02T03:00:00Z"
AFTER = "2026-08-02T03:20:00Z"


def event(kind: str, payload: dict, timestamp: str = BEFORE) -> bytes:
    return (
        json.dumps(
            {"timestamp": timestamp, "type": kind, "payload": payload},
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def header(thread_id: str) -> bytes:
    return event("session_meta", {"id": thread_id})


def task_started() -> bytes:
    return event("event_msg", {"type": "task_started"})


def trigger() -> bytes:
    return event("inter_agent_communication_metadata", {})


def call(call_id: str) -> bytes:
    return event(
        "response_item",
        {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": call_id,
            "status": "completed",
            "input": "synthetic_wrapper()",
        },
    )


def result(call_id: str) -> bytes:
    return event(
        "response_item",
        {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": [],
        },
    )


def write_rollout(path: Path, rows: list[bytes]) -> None:
    with path.open("wb") as stream:
        stream.writelines(rows)


class StructuralBoundaryTests(unittest.TestCase):
    def test_child_header_does_not_make_copied_history_native(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "child.jsonl"
            write_rollout(
                path,
                [
                    header("child"),
                    task_started(),  # copied parent turn
                    call("copied-call"),
                    result("copied-call"),
                    task_started(),  # child-native turn
                    trigger(),
                    call("native-call"),
                    result("native-call"),
                ],
            )
            part = extractor.process_codex_rollout(
                {
                    "id": "child",
                    "depth": 1,
                    "rollout_path": str(path),
                },
                CUTOFF,
            )

        self.assertEqual(3, part["prefix_rows"])
        self.assertEqual(5, part["selected_rows"])
        self.assertEqual({"native-call"}, set(part["calls"]))
        self.assertEqual(1, len(part["results"]))
        self.assertNotIn("copied-call", part["calls"])

    def test_no_history_child_and_invalid_cutoff_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "child.jsonl"
            write_rollout(
                path,
                [
                    header("child"),
                    task_started(),
                    trigger(),
                    b"\xff\xfe\n",
                    event("event_msg", {"type": "task_complete"}, AFTER),
                    b"not-json-after-cutoff\n",
                ],
            )
            part = extractor.process_codex_rollout(
                {
                    "id": "child",
                    "depth": 2,
                    "rollout_path": str(path),
                },
                CUTOFF,
            )

        self.assertEqual(0, part["prefix_rows"])
        self.assertEqual(1, part["selected_invalid_rows"])
        self.assertEqual(1, part["selected_invalid_error_kinds"]["unicode_decode"])
        self.assertEqual(3, part["selected_rows"])


class AggregateCorrelationTests(unittest.TestCase):
    def test_equal_totals_can_hide_one_missing_and_one_duplicate_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            root_rollout = root_dir / "root.jsonl"
            child_rollout = root_dir / "child.jsonl"
            write_rollout(
                root_rollout,
                [header("root"), call("root-call"), result("root-call"), result("root-call")],
            )
            write_rollout(
                child_rollout,
                [
                    header("child"),
                    call("copied-root-call"),
                    result("copied-root-call"),
                    task_started(),
                    trigger(),
                    call("child-call"),
                ],
            )

            db_path = root_dir / "index.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE threads(
                  id TEXT PRIMARY KEY,
                  created_at INTEGER NOT NULL,
                  rollout_path TEXT NOT NULL,
                  model TEXT,
                  reasoning_effort TEXT
                );
                CREATE TABLE thread_spawn_edges(
                  parent_thread_id TEXT NOT NULL,
                  child_thread_id TEXT NOT NULL
                );
                """
            )
            before_epoch = int(dt.datetime(2026, 8, 2, 3, 0, tzinfo=UTC).timestamp())
            connection.executemany(
                "INSERT INTO threads VALUES(?,?,?,?,?)",
                [
                    ("root", before_epoch - 1, str(root_rollout), "synthetic", "high"),
                    ("child", before_epoch, str(child_rollout), "synthetic", "high"),
                ],
            )
            connection.execute("INSERT INTO thread_spawn_edges VALUES(?,?)", ("root", "child"))
            connection.commit()
            connection.close()

            aggregate = extractor.collect_codex(
                db_path,
                "root",
                extractor.iso_utc(CUTOFF),
                int(CUTOFF.timestamp()),
            )

        lineage = aggregate["lineage"]
        protocol = aggregate["tool_protocol"]
        fidelity = aggregate["source_fidelity"]
        self.assertEqual(2, lineage["threads"])
        self.assertEqual(1, lineage["spawn_edges"])
        self.assertEqual({"0": 1, "1": 1}, lineage["depth_counts"])
        self.assertEqual(2, protocol["call_events"])
        self.assertEqual(2, protocol["result_events"])
        self.assertEqual(1, protocol["calls_without_result"])
        self.assertEqual(1, protocol["duplicate_results_for_same_call_within_thread"])
        self.assertEqual(2, fidelity["inherited_prefix_rows_excluded"])


if __name__ == "__main__":
    unittest.main()
