"""Adversarial, private-data-free tests for the private trace extractor."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("extract_private_paper_traces.py")
SPEC = importlib.util.spec_from_file_location("private_trace_extractor", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 8, 2, 3, 11, 1, tzinfo=UTC)
CUTOFF_ISO = extractor.iso_utc(CUTOFF)
CUTOFF_EPOCH = int(CUTOFF.timestamp())
BEFORE = "2026-08-02T03:00:00Z"
AFTER = "2026-08-02T03:20:00Z"
KEY = b"synthetic-private-trace-test-key-32-bytes-plus"


def event(kind: str, payload: dict, timestamp: str | None = BEFORE) -> bytes:
    body = {"type": kind, "payload": payload}
    if timestamp is not None:
        body["timestamp"] = timestamp
    return json.dumps(body, sort_keys=True).encode("utf-8") + b"\n"


def user_header(thread_id: str, version: str = "0.145.0") -> bytes:
    return event(
        "session_meta",
        {
            "id": thread_id,
            "cli_version": version,
            "history_mode": "legacy",
            "source": "vscode",
            "thread_source": "user",
        },
    )


def subagent_header(
    thread_id: str,
    parent_id: str,
    version: str = "0.145.0",
    multi_agent_version: str = "v2",
) -> bytes:
    return event(
        "session_meta",
        {
            "id": thread_id,
            "cli_version": version,
            "history_mode": "legacy",
            "multi_agent_version": multi_agent_version,
            "parent_thread_id": parent_id,
            "forked_from_id": "synthetic-fork-point",
            "thread_source": "subagent",
            "source": {
                "subagent": {"thread_spawn": {"parent_thread_id": parent_id}}
            },
        },
    )


def task_started(timestamp: str | None = BEFORE) -> bytes:
    return event("event_msg", {"type": "task_started"}, timestamp)


def trigger(timestamp: str | None = BEFORE) -> bytes:
    return event(
        "inter_agent_communication_metadata", {"trigger_turn": True}, timestamp
    )


def call(
    call_id: object,
    *,
    kind: str = "custom_tool_call",
    timestamp: str | None = BEFORE,
) -> bytes:
    payload = {
        "type": kind,
        "name": "exec" if kind == "custom_tool_call" else "spawn_agent",
        "call_id": call_id,
    }
    if kind == "custom_tool_call":
        payload.update(status="completed", input="synthetic_wrapper()")
    return event("response_item", payload, timestamp)


def result(
    call_id: object,
    *,
    kind: str = "custom_tool_call_output",
    timestamp: str | None = BEFORE,
) -> bytes:
    return event(
        "response_item",
        {"type": kind, "call_id": call_id, "output": []},
        timestamp,
    )


def write_rollout(path: Path, rows: list[bytes]) -> None:
    with path.open("wb") as stream:
        stream.writelines(rows)


def record(
    thread_id: str,
    path: Path,
    *,
    depth: int,
    parent: str | None = None,
    version: str = "0.145.0",
) -> dict:
    return {
        "id": thread_id,
        "depth": depth,
        "expected_parent_id": parent,
        "rollout_path": str(path),
        "cli_version": version,
        "history_mode": "legacy",
    }


def make_db(
    path: Path,
    threads: list[tuple[str, int, Path, str, str, str, str]],
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
        "INSERT INTO threads(id,created_at,rollout_path,model,reasoning_effort,"
        "cli_version,history_mode,source,thread_source) VALUES(?,?,?,?,?,?,?,?,?)",
        [
            (thread_id, created, str(rollout), model, effort, version, "legacy", source, thread_source)
            for thread_id, created, rollout, model, effort, version, source, thread_source in threads
        ],
    )
    connection.executemany("INSERT INTO thread_spawn_edges VALUES(?,?,?)", edges)
    connection.commit()
    connection.close()


class PinnedSourceBoundaryTests(unittest.TestCase):
    def test_both_pinned_versions_exclude_copied_history(self) -> None:
        for version in ("0.145.0", "0.146.0"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "rollout.jsonl"
                write_rollout(
                    path,
                    [
                        subagent_header("private-child", "private-parent", version),
                        user_header("copied-parent", version),
                        task_started(),
                        call("copied-call"),
                        result("copied-call"),
                        task_started(),
                        trigger(),
                        call("native-call"),
                        result("native-call"),
                    ],
                )
                part = extractor.process_codex_rollout(
                    record(
                        "private-child",
                        path,
                        depth=1,
                        parent="private-parent",
                        version=version,
                    ),
                    CUTOFF,
                )
                self.assertEqual(4, part["prefix_rows"])
                self.assertEqual(5, part["selected_exact_rows"])
                self.assertEqual(["native-call"], [row[0] for row in part["calls"]])
                self.assertEqual("subagent_provenance", part["header_provenance"])

    def test_unsupported_source_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            write_rollout(
                path,
                [
                    subagent_header(
                        "private-child", "private-parent", version="0.144.0"
                    ),
                    task_started(),
                    trigger(),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "unsupported Codex source"):
                extractor.process_codex_rollout(
                    record(
                        "private-child",
                        path,
                        depth=1,
                        parent="private-parent",
                        version="0.144.0",
                    ),
                    CUTOFF,
                )

    def test_selected_root_with_external_parent_is_normalized_as_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            rollout = root_dir / "selected-root.jsonl"
            write_rollout(
                rollout,
                [
                    subagent_header("private-selected-root", "private-external-parent"),
                    user_header("copied-external-parent"),
                    call("copied-call"),
                    task_started(),
                    trigger(),
                    call("native-call"),
                    result("native-call"),
                ],
            )
            unused = root_dir / "unused.jsonl"
            write_rollout(unused, [user_header("private-external-parent")])
            db = root_dir / "index.sqlite3"
            make_db(
                db,
                [
                    (
                        "private-external-parent",
                        CUTOFF_EPOCH - 20,
                        unused,
                        "private-model",
                        "high",
                        "0.145.0",
                        "vscode",
                        "user",
                    ),
                    (
                        "private-selected-root",
                        CUTOFF_EPOCH - 10,
                        rollout,
                        "private-model",
                        "high",
                        "0.145.0",
                        "private-db-source",
                        "subagent",
                    ),
                ],
                [("private-external-parent", "private-selected-root", "closed")],
            )
            aggregate = extractor.collect_codex(
                db,
                "private-selected-root",
                CUTOFF_ISO,
                CUTOFF_EPOCH,
                KEY,
            )
        self.assertTrue(aggregate["lineage"]["root_has_external_parent"])
        self.assertEqual(
            {"subagent_provenance": 1},
            aggregate["source_fidelity"]["header_provenance_counts"],
        )
        self.assertEqual(1, aggregate["tool_protocol"]["raw_call_events"])

    def test_zero_or_multiple_matching_headers_fail_closed(self) -> None:
        fixtures = {
            "zero": [user_header("different-thread")],
            "multiple": [user_header("private-root"), user_header("private-root")],
        }
        for label, rows in fixtures.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "rollout.jsonl"
                write_rollout(path, rows)
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    extractor.process_codex_rollout(
                        record("private-root", path, depth=0), CUTOFF
                    )

    def test_unsupported_or_ambiguous_multi_agent_marker_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            write_rollout(
                path,
                [
                    subagent_header(
                        "private-child",
                        "private-parent",
                        multi_agent_version="v3",
                    ),
                    task_started(),
                    trigger(),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "multi-agent"):
                extractor.process_codex_rollout(
                    record(
                        "private-child", path, depth=1, parent="private-parent"
                    ),
                    CUTOFF,
                )


class CutoffIntegrityTests(unittest.TestCase):
    def test_missing_bad_and_invalid_rows_are_anomalies_and_future_stops_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            write_rollout(
                path,
                [
                    user_header("private-root"),
                    b"\xff\xfe\n",
                    call("missing-time", timestamp=None),
                    call("bad-time", timestamp="not-a-time"),
                    call("exact-call"),
                    event("event_msg", {"type": "task_complete"}, AFTER),
                    call("post-future-missing", timestamp=None),
                    result("post-future-bad", timestamp="bad"),
                    call("post-future-past", timestamp=BEFORE),
                    user_header("private-root"),
                ],
            )
            part = extractor.process_codex_rollout(
                record("private-root", path, depth=0), CUTOFF
            )
        self.assertTrue(part["future_stop_found"])
        self.assertEqual(2, part["selected_exact_rows"])
        self.assertEqual(3, sum(part["integrity_anomalies"].values()))
        self.assertEqual(1, part["integrity_anomalies"]["unicode_decode"])
        self.assertEqual(1, part["integrity_anomalies"]["missing_timestamp"])
        self.assertEqual(1, part["integrity_anomalies"]["unparseable_timestamp"])
        self.assertEqual(["exact-call"], [row[0] for row in part["calls"]])

    def test_fixed_fixture_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            write_rollout(path, [user_header("private-root"), call("exact-call")])
            first = extractor.process_codex_rollout(
                record("private-root", path, depth=0), CUTOFF
            )
            second = extractor.process_codex_rollout(
                record("private-root", path, depth=0), CUTOFF
            )
        for key in ("committed_prefix_bytes", "selected_exact_rows"):
            self.assertEqual(first[key], second[key])
        for key in ("committed_prefix_sha256", "selected_digest"):
            self.assertEqual(first[key].hexdigest(), second[key].hexdigest())


class ProtocolAccountingTests(unittest.TestCase):
    def test_raw_string_unique_duplicate_pair_and_kind_counts_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            write_rollout(
                path,
                [
                    user_header("private-root"),
                    call("duplicate"),
                    call("duplicate"),
                    result("duplicate"),
                    call("mismatch", kind="function_call"),
                    result("mismatch", kind="custom_tool_call_output"),
                    call("one-to-one", kind="function_call"),
                    result("one-to-one", kind="function_call_output"),
                    call(17),
                    result(17),
                ],
            )
            part = extractor.process_codex_rollout(
                record("private-root", path, depth=0), CUTOFF
            )
            counts = extractor._correlate_part(part)
        self.assertEqual(5, counts["raw_call_events"])
        self.assertEqual(4, counts["calls_with_string_id"])
        self.assertEqual(3, counts["unique_call_ids_within_thread_sum"])
        self.assertEqual(1, counts["duplicate_call_id_events_within_thread"])
        self.assertEqual(4, counts["raw_result_events"])
        self.assertEqual(3, counts["results_with_string_id"])
        self.assertEqual(3, counts["unique_result_ids_within_thread_sum"])
        self.assertEqual(1, counts["kind_compatible_one_to_one_pairs_within_thread"])
        self.assertEqual(1, counts["kind_mismatched_singleton_ids_within_thread"])
        self.assertEqual(
            1, counts["ambiguous_duplicate_or_missing_id_groups_within_thread"]
        )
        self.assertEqual(4, counts["call_events_without_one_to_one_pair"])
        self.assertEqual(3, counts["result_events_without_one_to_one_pair"])


class LineageIntegrityTests(unittest.TestCase):
    def _base_files(self, root_dir: Path) -> tuple[Path, Path, Path]:
        root = root_dir / "root.jsonl"
        child = root_dir / "child.jsonl"
        other = root_dir / "other.jsonl"
        write_rollout(root, [user_header("private-root")])
        write_rollout(
            child,
            [
                subagent_header("private-child", "private-root"),
                task_started(),
                trigger(),
            ],
        )
        write_rollout(other, [user_header("private-other")])
        return root, child, other

    def test_multi_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            root, child, other = self._base_files(root_dir)
            db = root_dir / "index.sqlite3"
            rows = [
                ("private-root", CUTOFF_EPOCH - 3, root, "private", "high", "0.145.0", "vscode", "user"),
                ("private-child", CUTOFF_EPOCH - 2, child, "private", "high", "0.145.0", "private", "subagent"),
                ("private-other", CUTOFF_EPOCH - 4, other, "private", "high", "0.145.0", "vscode", "user"),
            ]
            make_db(
                db,
                rows,
                [
                    ("private-root", "private-child", "open"),
                    ("private-other", "private-child", "closed"),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "one selected parent"):
                extractor.read_lineage(db, "private-root", CUTOFF_EPOCH, KEY)

    def test_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            root, child, _other = self._base_files(root_dir)
            db = root_dir / "index.sqlite3"
            rows = [
                ("private-root", CUTOFF_EPOCH - 3, root, "private", "high", "0.145.0", "vscode", "user"),
                ("private-child", CUTOFF_EPOCH - 2, child, "private", "high", "0.145.0", "private", "subagent"),
            ]
            make_db(
                db,
                rows,
                [
                    ("private-root", "private-child", "open"),
                    ("private-child", "private-root", "closed"),
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "tree|cycle"):
                extractor.read_lineage(db, "private-root", CUTOFF_EPOCH, KEY)

    def test_external_root_parent_endpoint_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            selected = root_dir / "selected.jsonl"
            write_rollout(
                selected,
                [
                    subagent_header("private-selected", "private-missing-parent"),
                    task_started(),
                    trigger(),
                ],
            )
            db = root_dir / "index.sqlite3"
            make_db(
                db,
                [
                    (
                        "private-selected",
                        CUTOFF_EPOCH - 1,
                        selected,
                        "private",
                        "high",
                        "0.145.0",
                        "private",
                        "subagent",
                    )
                ],
                [("private-missing-parent", "private-selected", "closed")],
            )
            with self.assertRaisesRegex(RuntimeError, "missing.*parent|endpoint"):
                extractor.read_lineage(db, "private-selected", CUTOFF_EPOCH, KEY)


class AggregateAndPrivacyTests(unittest.TestCase):
    def test_aggregate_arithmetic_determinism_and_privacy_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            root = root_dir / "root.jsonl"
            child = root_dir / "child.jsonl"
            write_rollout(root, [user_header("private-root-token"), call("private-call-a"), result("private-call-a")])
            write_rollout(
                child,
                [
                    subagent_header("private-child-token", "private-root-token"),
                    user_header("copied-header-token"),
                    call("copied-call-token"),
                    task_started(),
                    trigger(),
                    call("private-call-b"),
                    result("private-call-b"),
                ],
            )
            db = root_dir / "index.sqlite3"
            make_db(
                db,
                [
                    ("private-root-token", CUTOFF_EPOCH - 3, root, "private-model", "high", "0.145.0", "vscode", "user"),
                    ("private-child-token", CUTOFF_EPOCH - 2, child, "private-model", "ultra", "0.145.0", "private-source", "subagent"),
                ],
                [("private-root-token", "private-child-token", "closed")],
            )
            first = extractor.collect_codex(
                db, "private-root-token", CUTOFF_ISO, CUTOFF_EPOCH, KEY
            )
            second = extractor.collect_codex(
                db, "private-root-token", CUTOFF_ISO, CUTOFF_EPOCH, KEY
            )
            encoded = json.dumps(first, sort_keys=True)

        self.assertEqual(first, second)
        self.assertEqual(first["lineage"]["threads"] - 1, first["lineage"]["spawn_edges"])
        self.assertEqual(
            first["lineage"]["threads"],
            sum(first["lineage"]["depth_counts"].values()),
        )
        self.assertEqual(
            first["source_fidelity"]["selected_exact_timestamped_rows"],
            sum(first["event_shapes"]["top_level_type_counts"].values()),
        )
        self.assertEqual(
            first["tool_protocol"]["raw_call_events"],
            sum(first["tool_protocol"]["call_kind_counts"].values()),
        )
        self.assertEqual(
            2,
            first["tool_protocol"][
                "kind_compatible_one_to_one_pairs_within_thread"
            ],
        )
        for forbidden in (
            "private-root-token",
            "private-child-token",
            "private-call-a",
            "private-call-b",
            str(root_dir),
            "private-model",
        ):
            self.assertNotIn(forbidden, encoded)
        extractor.privacy_assertions(
            {"codex": first},
            ["private-root-token", "private-child-token", str(root_dir)],
        )

    def test_privacy_rejects_uuid_path_and_arbitrary_free_string(self) -> None:
        bad_documents = [
            {"value": "01234567-89ab-cdef-0123-456789abcdef"},
            {"value": "/private/home/author/file"},
            {"value": "raw prompt body that is not allowlisted"},
        ]
        for document in bad_documents:
            with self.subTest(document=document), self.assertRaises(RuntimeError):
                extractor.privacy_assertions(document, ["/private/home/author"])

    def test_privacy_digest_exception_is_field_specific(self) -> None:
        digest = "a" * 64
        with self.assertRaisesRegex(RuntimeError, "privacy schema"):
            extractor.privacy_assertions({"schema_version": digest}, [])
        extractor.privacy_assertions(
            {"codex": {"lineage": {"root_hmac_sha256": digest}}}, []
        )

    def test_privacy_keys_are_bound_to_complete_paths(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "privacy schema"):
            extractor.privacy_assertions({"threads": 1}, [])

    def test_privacy_fixed_values_are_bound_to_fields(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "privacy schema"):
            extractor.privacy_assertions(
                {"schema_version": "user_provenance"}, []
            )

    def test_privacy_digests_are_bound_to_complete_paths(self) -> None:
        digest = "a" * 64
        with self.assertRaisesRegex(RuntimeError, "privacy schema"):
            extractor.privacy_assertions(
                {"claude": {"root_hmac_sha256": digest}}, []
            )
        extractor.privacy_assertions(
            {"codex": {"lineage": {"root_hmac_sha256": digest}}}, []
        )

    def test_manifest_commits_normalized_away_db_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            rollout = root_dir / "root.jsonl"
            write_rollout(rollout, [user_header("private-root")])
            db = root_dir / "index.sqlite3"
            make_db(
                db,
                [
                    (
                        "private-root",
                        CUTOFF_EPOCH - 1,
                        rollout,
                        "private-model-a",
                        "high",
                        "0.145.0",
                        "vscode",
                        "user",
                    )
                ],
                [],
            )
            first = extractor.collect_codex(
                db, "private-root", CUTOFF_ISO, CUTOFF_EPOCH, KEY
            )
            connection = sqlite3.connect(db)
            connection.execute(
                "UPDATE threads SET model = ? WHERE id = ?",
                ("private-model-b", "private-root"),
            )
            connection.commit()
            connection.close()
            second = extractor.collect_codex(
                db, "private-root", CUTOFF_ISO, CUTOFF_EPOCH, KEY
            )

        self.assertEqual(
            first["lineage"]["model_category_counts"],
            second["lineage"]["model_category_counts"],
        )
        self.assertNotEqual(
            first["source_fidelity"]["source_manifest_hmac_sha256"],
            second["source_fidelity"]["source_manifest_hmac_sha256"],
        )


class ClaudeFailClosedTests(unittest.TestCase):
    def test_missing_declared_index_is_unavailable_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_value = extractor.collect_declared_claude_or_unavailable(
                root / "missing-index.json", root
            )
        self.assertEqual("unavailable", result_value["evidence_role"])
        self.assertFalse(result_value["raw_action_corpus_available"])

    def test_malformed_declared_index_is_unavailable_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "declared-index.json"
            malformed.write_text('{"entries":[{"sessionId":"private"}]}', encoding="utf-8")
            result_value = extractor.collect_declared_claude_or_unavailable(
                malformed, root
            )
        self.assertEqual(
            "declared_index_unavailable_or_unsupported", result_value["reason"]
        )

    def test_history_read_error_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text("synthetic", encoding="utf-8")
            with mock.patch.object(
                Path, "read_bytes", side_effect=OSError("synthetic read failure")
            ):
                count, errors = extractor.file_distinct_id_count(
                    path, {"01234567-89ab-cdef-0123-456789abcdef"}
                )
        self.assertEqual(0, count)
        self.assertEqual(1, errors)

    def test_targeted_directory_walk_error_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def inaccessible_walk(_path, *, followlinks, onerror=None):
                self.assertFalse(followlinks)
                self.assertIsNotNone(onerror)
                onerror(OSError("synthetic traversal failure"))
                return iter(())

            with mock.patch.object(extractor.os, "walk", new=inaccessible_walk):
                matches, errors = extractor.exact_id_reference_file_count(
                    [root], {"01234567-89ab-cdef-0123-456789abcdef"}
                )
        self.assertEqual(0, matches)
        self.assertEqual(1, errors)

    def test_project_index_enumeration_error_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected-index.json"
            with mock.patch.object(
                extractor.os,
                "scandir",
                side_effect=OSError("synthetic index enumeration failure"),
            ):
                indexes, errors = extractor.discover_project_indexes(root, selected)
        self.assertEqual([selected], indexes)
        self.assertEqual(1, errors)


if __name__ == "__main__":
    unittest.main()
