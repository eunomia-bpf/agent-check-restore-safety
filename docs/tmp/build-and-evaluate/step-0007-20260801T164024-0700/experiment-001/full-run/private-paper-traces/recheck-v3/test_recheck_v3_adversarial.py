"""Fresh, private-data-free adversarial review of the v3 trace extractor.

The fixtures in this file are synthetic.  They do not locate, open, or name
any private Codex/Claude trace, rollout root, commitment key, or raw path.
Tests encode the acceptance gate stated by the preceding independent review;
an assertion failure is therefore evidence that the gate is not yet closed.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


BASE = Path(__file__).resolve().parent.parent
MODULE_PATH = BASE / "extract_private_paper_traces.py"
SUMMARY_PATH = BASE / "summary.json"
REPLAY_PATH = BASE / "replay-evidence-v3.json"
SPEC = importlib.util.spec_from_file_location("v3_rechecked_extractor", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)

UTC = dt.timezone.utc
CUTOFF = dt.datetime(2026, 8, 2, 3, 11, 1, tzinfo=UTC)
CUTOFF_ISO = extractor.iso_utc(CUTOFF)
CUTOFF_EPOCH = int(CUTOFF.timestamp())
BEFORE = "2026-08-02T03:00:00Z"
AFTER = "2026-08-02T03:20:00Z"
KEY = b"fresh-independent-v3-review-key-material"
CANONICAL_ID = "01234567-89ab-cdef-0123-456789abcdef"


def event(kind: str, payload: dict, timestamp: str | None = BEFORE) -> bytes:
    value = {"type": kind, "payload": payload}
    if timestamp is not None:
        value["timestamp"] = timestamp
    return json.dumps(value, sort_keys=True).encode("utf-8") + b"\n"


def user_header(thread_id: str, *, version: str = "0.145.0") -> bytes:
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


def subagent_header(thread_id: str, parent_id: str) -> bytes:
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
    )


def task_started(timestamp: str | None = BEFORE) -> bytes:
    return event("event_msg", {"type": "task_started"}, timestamp)


def marker(trigger_turn: object = True, timestamp: str | None = BEFORE) -> bytes:
    return event(
        "inter_agent_communication_metadata",
        {"trigger_turn": trigger_turn},
        timestamp,
    )


def call(call_id: str, timestamp: str | None = BEFORE) -> bytes:
    return event(
        "response_item",
        {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": call_id,
            "status": "completed",
            "input": "synthetic operation",
        },
        timestamp,
    )


def result(call_id: str, timestamp: str | None = BEFORE) -> bytes:
    return event(
        "response_item",
        {"type": "custom_tool_call_output", "call_id": call_id, "output": []},
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
        "INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?)",
        [
            (
                thread_id,
                created_at,
                str(rollout),
                model,
                effort,
                "0.145.0",
                "legacy",
                source,
                provenance,
            )
            for (
                thread_id,
                created_at,
                rollout,
                model,
                effort,
                source,
                provenance,
            ) in threads
        ],
    )
    connection.executemany("INSERT INTO thread_spawn_edges VALUES(?,?,?)", edges)
    connection.commit()
    connection.close()


class SnapshotIdentityTests(unittest.TestCase):
    def _run_with_read_hook(self, mutation) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(rollout, [user_header("synthetic-root"), call("one")])
            original_open = Path.open
            did_mutate = False

            class ReadProxy:
                def __init__(self, handle):
                    self.handle = handle

                def __enter__(self):
                    self.handle.__enter__()
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return self.handle.__exit__(exc_type, exc, traceback)

                def fileno(self):
                    return self.handle.fileno()

                def read(self, size=-1):
                    nonlocal did_mutate
                    data = self.handle.read(size)
                    if not did_mutate:
                        mutation(rollout, original_open, data)
                        did_mutate = True
                    return data

            def opened(path_self, mode="r", *args, **kwargs):
                handle = original_open(path_self, mode, *args, **kwargs)
                if path_self == rollout and mode == "rb":
                    return ReadProxy(handle)
                return handle

            with mock.patch.object(Path, "open", new=opened):
                with self.assertRaisesRegex(RuntimeError, "changed|snapshot"):
                    extractor.process_codex_rollout(
                        record("synthetic-root", rollout), CUTOFF
                    )
            self.assertTrue(did_mutate)

    def test_same_size_in_place_byte_tamper_is_detected(self) -> None:
        def mutate(path: Path, original_open, data: bytes) -> None:
            replacement = b"[" if data[:1] != b"[" else b"{"
            with original_open(path, "r+b") as stream:
                stream.seek(0)
                stream.write(replacement)
                stream.flush()
                os.fsync(stream.fileno())
            self.assertEqual(len(data), path.stat().st_size)

        self._run_with_read_hook(mutate)

    def test_identical_bytes_same_size_path_replacement_is_detected(self) -> None:
        def mutate(path: Path, original_open, data: bytes) -> None:
            replacement = path.with_name("replacement.jsonl")
            with original_open(replacement, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(replacement, path)
            self.assertEqual(len(data), path.stat().st_size)

        self._run_with_read_hook(mutate)


class BoundaryContractTests(unittest.TestCase):
    def test_task_start_must_physically_follow_local_header_and_precede_marker(self) -> None:
        fixtures = {
            "start-before-header": [
                task_started(),
                subagent_header("synthetic-child", "synthetic-parent"),
                marker(),
            ],
            "start-after-marker": [
                subagent_header("synthetic-child", "synthetic-parent"),
                marker(),
                task_started(),
            ],
        }
        for label, rows in fixtures.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                rollout = Path(directory) / "rollout.jsonl"
                write_rollout(rollout, rows)
                with self.assertRaisesRegex(RuntimeError, "task start|preceding"):
                    extractor.process_codex_rollout(
                        record(
                            "synthetic-child",
                            rollout,
                            depth=1,
                            parent="synthetic-parent",
                        ),
                        CUTOFF,
                    )

    def test_header_id_comparison_is_exact_and_duplicates_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    user_header("synthetic-root-suffix"),
                    user_header("synthetic-root"),
                    call("local"),
                ],
            )
            part = extractor.process_codex_rollout(
                record("synthetic-root", rollout), CUTOFF
            )
            self.assertEqual(1, part["matching_header_count"])
            self.assertEqual(["local"], [entry[0] for entry in part["calls"]])

            write_rollout(
                rollout,
                [user_header("synthetic-root"), user_header("synthetic-root")],
            )
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                extractor.process_codex_rollout(
                    record("synthetic-root", rollout), CUTOFF
                )

    def test_trigger_turn_requires_the_boolean_true_value(self) -> None:
        for bad_value in (False, 1, "true", None):
            with self.subTest(value=bad_value), tempfile.TemporaryDirectory() as directory:
                rollout = Path(directory) / "rollout.jsonl"
                write_rollout(
                    rollout,
                    [
                        subagent_header("synthetic-child", "synthetic-parent"),
                        task_started(),
                        marker(bad_value),
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

    def test_future_stop_is_physical_not_timestamp_resorting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            write_rollout(
                rollout,
                [
                    user_header("synthetic-root"),
                    call("before"),
                    event("event_msg", {"type": "task_complete"}, AFTER),
                    call("backdated"),
                    user_header("synthetic-root"),
                ],
            )
            part = extractor.process_codex_rollout(
                record("synthetic-root", rollout), CUTOFF
            )
        self.assertTrue(part["future_stop_found"])
        self.assertEqual(["before"], [entry[0] for entry in part["calls"]])
        self.assertEqual(1, part["matching_header_count"])


class ManifestCoverageTests(unittest.TestCase):
    def test_selected_db_fields_that_can_change_output_or_provenance_are_committed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            rollout = base / "root.jsonl"
            identical = base / "identical.jsonl"
            rows = [user_header("synthetic-root"), call("one"), result("one")]
            write_rollout(rollout, rows)
            write_rollout(identical, rows)
            db = base / "state.sqlite3"
            make_db(
                db,
                [
                    (
                        "synthetic-root",
                        CUTOFF_EPOCH - 10,
                        rollout,
                        "unknown-model-a",
                        "high",
                        "synthetic-source-a",
                        "synthetic-thread-source-a",
                    )
                ],
                [],
            )

            def collect() -> dict:
                return extractor.collect_codex(
                    db, "synthetic-root", CUTOFF_ISO, CUTOFF_EPOCH, KEY
                )

            def update(field: str, value: object) -> None:
                connection = sqlite3.connect(db)
                connection.execute(
                    f"UPDATE threads SET {field} = ? WHERE id = ?",
                    (value, "synthetic-root"),
                )
                connection.commit()
                connection.close()

            baseline = collect()["source_fidelity"]["source_manifest_hmac_sha256"]
            mutations = {
                "created_at": CUTOFF_EPOCH - 9,
                "rollout_path": str(identical),
                "model": "unknown-model-b",
                "reasoning_effort": "xhigh",
                "source": "synthetic-source-b",
                "thread_source": "synthetic-thread-source-b",
            }
            original = {
                "created_at": CUTOFF_EPOCH - 10,
                "rollout_path": str(rollout),
                "model": "unknown-model-a",
                "reasoning_effort": "high",
                "source": "synthetic-source-a",
                "thread_source": "synthetic-thread-source-a",
            }
            for field, value in mutations.items():
                with self.subTest(field=field):
                    update(field, value)
                    changed = collect()["source_fidelity"][
                        "source_manifest_hmac_sha256"
                    ]
                    self.assertNotEqual(baseline, changed)
                    update(field, original[field])

    def test_edge_status_is_covered_by_edge_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "root.jsonl"
            child = base / "child.jsonl"
            write_rollout(root, [user_header("synthetic-root")])
            write_rollout(
                child,
                [
                    subagent_header("synthetic-child", "synthetic-root"),
                    task_started(),
                    marker(),
                ],
            )
            db = base / "state.sqlite3"
            make_db(
                db,
                [
                    (
                        "synthetic-root",
                        CUTOFF_EPOCH - 2,
                        root,
                        "model",
                        "high",
                        "source",
                        "user",
                    ),
                    (
                        "synthetic-child",
                        CUTOFF_EPOCH - 1,
                        child,
                        "model",
                        "high",
                        "source",
                        "subagent",
                    ),
                ],
                [("synthetic-root", "synthetic-child", "open")],
            )
            first = extractor.collect_codex(
                db, "synthetic-root", CUTOFF_ISO, CUTOFF_EPOCH, KEY
            )["lineage"]["edge_snapshot_hmac_sha256"]
            connection = sqlite3.connect(db)
            connection.execute("UPDATE thread_spawn_edges SET status = 'closed'")
            connection.commit()
            connection.close()
            second = extractor.collect_codex(
                db, "synthetic-root", CUTOFF_ISO, CUTOFF_EPOCH, KEY
            )["lineage"]["edge_snapshot_hmac_sha256"]
        self.assertNotEqual(first, second)

    def test_external_root_parent_endpoint_must_exist(self) -> None:
        """The report says every missing spawn-edge endpoint fails closed."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            selected = base / "selected.jsonl"
            write_rollout(
                selected,
                [
                    subagent_header("synthetic-selected", "synthetic-missing-parent"),
                    task_started(),
                    marker(),
                ],
            )
            db = base / "state.sqlite3"
            make_db(
                db,
                [
                    (
                        "synthetic-selected",
                        CUTOFF_EPOCH - 1,
                        selected,
                        "model",
                        "high",
                        "source",
                        "subagent",
                    )
                ],
                [("synthetic-missing-parent", "synthetic-selected", "closed")],
            )
            with self.assertRaisesRegex(RuntimeError, "missing|endpoint|parent"):
                extractor.collect_codex(
                    db, "synthetic-selected", CUTOFF_ISO, CUTOFF_EPOCH, KEY
                )


class ClaudeSelectionAndScanTests(unittest.TestCase):
    def _index(self, home: Path, session_id: str) -> Path:
        project = home / ".claude" / "projects" / "synthetic-project"
        project.mkdir(parents=True)
        index = project / "sessions-index.json"
        index.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "sessionId": session_id,
                            "fullPath": str(home / "absent-rollout.jsonl"),
                            "messageCount": 2,
                            "isSidechain": False,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return index

    def test_empty_and_noncanonical_ids_fail_while_canonical_id_is_accepted(self) -> None:
        for bad_id in ("", "not-a-session-id", CANONICAL_ID.upper()):
            with self.subTest(session_id=bad_id), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                index = self._index(home, bad_id)
                with self.assertRaisesRegex(RuntimeError, "schema"):
                    extractor.collect_claude(index, home)

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            index = self._index(home, CANONICAL_ID)
            observed = extractor.collect_claude(index, home)
        self.assertEqual(1, observed["indexed_entries"])
        self.assertEqual(1, observed["unique_session_ids"])
        self.assertFalse(observed["raw_action_corpus_available"])

    def test_walk_parse_and_content_read_errors_remain_explicit(self) -> None:
        def failing_walk(_home, *, followlinks, onerror):
            self.assertFalse(followlinks)
            onerror(OSError("synthetic walk error one"))
            onerror(OSError("synthetic walk error two"))
            return iter(())

        with mock.patch.object(extractor.os, "walk", new=failing_walk):
            walked = extractor.exact_id_filename_scan(
                Path("/synthetic-not-read"), {CANONICAL_ID}
            )
        self.assertEqual(2, walked["walk_errors_observed"])

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            readable = base / "readable.bin"
            unreadable = base / "unreadable.bin"
            readable.write_bytes(CANONICAL_ID.encode("ascii"))
            unreadable.write_bytes(b"synthetic")
            original_open = Path.open

            def opened(path_self, mode="r", *args, **kwargs):
                if path_self == unreadable and mode == "rb":
                    raise OSError("synthetic content read error")
                return original_open(path_self, mode, *args, **kwargs)

            with mock.patch.object(Path, "open", new=opened):
                matches, errors = extractor.exact_id_reference_file_count(
                    [readable, unreadable], {CANONICAL_ID}
                )
        self.assertEqual(1, matches)
        self.assertEqual(1, errors)

    def test_directory_traversal_error_is_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)

            def inaccessible_walk(_path, *, followlinks, onerror=None):
                self.assertFalse(followlinks)
                if onerror is not None:
                    onerror(OSError("synthetic traversal error"))
                return iter(())

            with mock.patch.object(extractor.os, "walk", new=inaccessible_walk):
                _matches, errors = extractor.exact_id_reference_file_count(
                    [base], {CANONICAL_ID}
                )
        self.assertEqual(1, errors)

    def test_malformed_neighbor_index_is_counted_without_guessing_a_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = self._index(home, CANONICAL_ID)
            neighbor = home / ".claude" / "projects" / "neighbor"
            neighbor.mkdir(parents=True)
            (neighbor / "sessions-index.json").write_text("not-json", encoding="utf-8")
            observed = extractor.collect_claude(target, home)
        self.assertEqual(1, observed["project_index_parse_errors"])
        self.assertFalse(observed["raw_action_corpus_available"])


class PrivacySchemaTests(unittest.TestCase):
    def test_known_keys_are_bound_to_their_schema_paths(self) -> None:
        # ``threads`` is valid only under codex.lineage, never at the root.
        with self.assertRaisesRegex(RuntimeError, "privacy|allowlist|schema"):
            extractor.privacy_assertions({"threads": 1}, [])

    def test_fixed_allowlisted_values_are_bound_to_their_fields(self) -> None:
        # Both strings are public constants, but this pairing is not schema-valid.
        with self.assertRaisesRegex(RuntimeError, "privacy|allowlist|schema"):
            extractor.privacy_assertions(
                {"schema_version": "user_provenance"}, []
            )

    def test_digest_is_bound_to_its_complete_schema_path(self) -> None:
        digest = "a" * 64
        with self.assertRaisesRegex(RuntimeError, "privacy|allowlist|schema"):
            extractor.privacy_assertions(
                {"claude": {"root_hmac_sha256": digest}}, []
            )
        extractor.privacy_assertions(
            {
                "codex": {
                    "lineage": {"root_hmac_sha256": digest},
                }
            },
            [],
        )


class CliPrivacyTests(unittest.TestCase):
    def test_direct_root_id_option_is_absent_from_argument_parser(self) -> None:
        syntax = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        flags: set[str] = set()
        for node in ast.walk(syntax):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr != "add_argument":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    flags.add(argument.value)
        self.assertIn("--root-thread-id-file", flags)
        self.assertNotIn("--root-thread-id", flags)


class PublishedEvidenceTests(unittest.TestCase):
    def test_summary_arithmetic_is_self_consistent(self) -> None:
        document = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual("private-paper-trace-summary-v3", document["schema_version"])
        codex = document["codex"]
        lineage = codex["lineage"]
        fidelity = codex["source_fidelity"]
        protocol = codex["tool_protocol"]
        identities = [
            lineage["spawn_edges"] == lineage["threads"] - 1,
            sum(lineage["depth_counts"].values()) == lineage["threads"],
            sum(lineage["role_counts"].values()) == lineage["threads"],
            sum(lineage["model_category_counts"].values()) == lineage["threads"],
            sum(lineage["reasoning_effort_counts"].values()) == lineage["threads"],
            sum(fidelity["header_provenance_counts"].values())
            == fidelity["rollout_files"],
            sum(fidelity["supported_cli_version_counts"].values())
            == fidelity["rollout_files"],
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
            sum(protocol["result_kind_counts"].values())
            == protocol["raw_result_events"],
            sum(protocol["call_tool_counts"].values())
            == protocol["raw_call_events"],
            protocol["calls_with_string_id"] + protocol["calls_without_string_id"]
            == protocol["raw_call_events"],
            protocol["results_with_string_id"]
            + protocol["results_without_string_id"]
            == protocol["raw_result_events"],
            protocol["unique_call_ids_within_thread_sum"]
            + protocol["duplicate_call_id_events_within_thread"]
            == protocol["calls_with_string_id"],
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
                sum(counts.values())
                for counts in protocol["tool_calls_by_role"].values()
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
        self.assertEqual(24, len(identities))
        self.assertTrue(all(identities))
        extractor.privacy_assertions(document, [])

    def test_summary_is_the_byte_identical_replay_output_and_flags_agree(self) -> None:
        evidence = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
        summary_digest = hashlib.sha256(SUMMARY_PATH.read_bytes()).hexdigest()
        self.assertTrue(evidence["byte_identical"])
        self.assertEqual([0, 0], evidence["return_codes"])
        self.assertEqual([summary_digest, summary_digest], evidence["output_sha256"])
        self.assertTrue(evidence["source_manifest_hmac_identical"])
        self.assertTrue(evidence["edge_manifest_hmac_identical"])
        self.assertTrue(evidence["cutoff_commit_hmac_identical"])
        self.assertFalse(evidence["private_material_retained"])

    def test_replay_evidence_pins_the_current_extractor_bytes(self) -> None:
        evidence = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
        current = hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest()
        self.assertEqual(current, evidence["extractor_sha256"])

    def test_all_four_published_commitments_are_well_formed_and_distinct(self) -> None:
        document = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        values = [
            document["selection"]["cutoff_commit_hmac_sha256"],
            document["codex"]["lineage"]["root_hmac_sha256"],
            document["codex"]["lineage"]["edge_snapshot_hmac_sha256"],
            document["codex"]["source_fidelity"]["source_manifest_hmac_sha256"],
        ]
        self.assertTrue(all(extractor.SHA256_RE.fullmatch(value) for value in values))
        self.assertEqual(4, len(set(values)))


if __name__ == "__main__":
    unittest.main()
