#!/usr/bin/env python3
"""Read-only, privacy-preserving audit of one paper-formation lineage.

This extractor is deliberately fail closed.  Its child-history boundary is
supported only for Codex 0.145.0 and 0.146.0, legacy history, multi-agent v2.
For both pinned upstream revisions, ``keep_forked_rollout_item`` excludes
``InterAgentCommunication`` and ``InterAgentCommunicationMetadata`` from the
copied prefix.  Consequently the first exact, timestamped inter-agent metadata
record is a source-grounded native marker, rather than a content heuristic.
It must carry ``trigger_turn: true``.  The last physical ``task_started``
immediately preceding that marker must likewise be exact and timestamped; it
begins the native turn.

Whether a selected rollout needs that boundary is determined from its matching
local ``session_meta`` provenance, not from its depth within the selected
subtree.  Thus a selected root that is itself a subagent is normalized too.

Only timestamped events at or before the fixed cutoff are exact events.  The
physical stream stops at the first parseable future timestamp; malformed or
timestamp-less rows before that point are integrity anomalies, never events.
No prompt, message, reasoning, command, result body, ID, or path is emitted.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
from typing import Any, Iterable, Iterator


UTC = dt.timezone.utc
SCHEMA_VERSION = "private-paper-trace-summary-v3"

PINNED_CODEX_SOURCES = {
    "0.145.0": {
        "tag": "rust-v0.145.0",
        "commit": "25af12f7e61572b0bc18ddb1008be543b91519b0",
    },
    "0.146.0": {
        "tag": "rust-v0.146.0",
        "commit": "e363b08c9175ac1cbe5893615dd2cb9ddf95043b",
    },
}
PINNED_HISTORY_MODE = "legacy"
PINNED_MULTI_AGENT_VERSION = "v2"
KNOWN_EDGE_STATUSES = {"open", "closed"}

# Private strings are normalized to one of these fixed labels.  Keys are
# schema, not observations; privacy_assertions checks every emitted value.
KNOWN_TOOL_NAMES = {
    "exec",
    "wait",
    "run",
    "shell_command",
    "spawn_agent",
    "send_message",
    "followup_task",
    "interrupt_agent",
    "list_agents",
    "wait_agent",
    "request_user_input",
    "update_plan",
    "create_goal",
    "get_goal",
    "update_goal",
    "apply_patch",
    "view_image",
    "write_stdin",
    "read_thread",
    "create_thread",
    "wait_threads",
    "send_message_to_thread",
}
KNOWN_TOP_LEVEL_TYPES = {
    "session_meta",
    "event_msg",
    "response_item",
    "turn_context",
    "world_state",
    "compacted",
    "inter_agent_communication_metadata",
}
KNOWN_PAYLOAD_TYPES = {
    "task_started",
    "task_complete",
    "turn_aborted",
    "user_message",
    "agent_message",
    "reasoning",
    "agent_reasoning",
    "token_count",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
    "context_compacted",
    "thread_rolled_back",
    "thread_goal_updated",
    "sub_agent_activity",
    "patch_apply_end",
    "thread_settings_applied",
    "web_search_end",
    "message",
}
LIFECYCLE_PAYLOADS = {
    "task_started",
    "task_complete",
    "turn_aborted",
    "context_compacted",
    "thread_rolled_back",
    "thread_goal_updated",
    "sub_agent_activity",
}
KNOWN_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
KNOWN_MODEL_LABELS = {"gpt-5.6-sol": "pinned_primary", "gpt-5.6-terra": "pinned_secondary"}

CALL_TO_RESULT_KIND = {
    "function_call": "function_call_output",
    "custom_tool_call": "custom_tool_call_output",
}

# Lexical categories overlap and describe wrapper source, not proved effects.
LEXICAL_ACTION_PATTERNS = {
    "nested_exec_command_call_site": re.compile(r"\btools\.exec_command\s*\("),
    "nested_apply_patch_call_site": re.compile(r"\btools\.apply_patch\s*\("),
    "nested_web_call_site": re.compile(r"\btools\.web__run\s*\("),
    "git_inspection_wrapper": re.compile(
        r"\bgit\s+(?:status|diff|log|show|rev-parse|ls-files|branch|remote)\b", re.I
    ),
    "git_commit_wrapper": re.compile(r"\bgit\s+commit\b", re.I),
    "git_push_wrapper": re.compile(r"\bgit\s+push\b", re.I),
    "git_network_wrapper": re.compile(r"\bgit\s+(?:clone|fetch|pull|push)\b", re.I),
    "build_or_test_wrapper": re.compile(
        r"\b(?:lake\s+build|pytest|cargo\s+(?:test|build|check)|npm\s+test|"
        r"pnpm\s+test|go\s+test|make(?:\s|$)|lean\b|mvn\s+test|gradle\s+test)",
        re.I,
    ),
    "network_or_download_wrapper": re.compile(
        r"\b(?:curl|wget|git\s+(?:clone|fetch|pull|push))\b|tools\.web__run", re.I
    ),
    "process_or_service_wrapper": re.compile(
        r"\b(?:kill|pkill|systemctl|service|nohup|docker|podman|kubectl)\b", re.I
    ),
    "database_wrapper": re.compile(r"\b(?:sqlite3|psql|mysql|mongosh|redis-cli)\b", re.I),
    "shell_mutation_wrapper": re.compile(
        r"\b(?:mkdir|touch|cp|mv|rm|install)\b|(?:^|[^>])>{1,2}(?!=)", re.I
    ),
}

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)

OUTPUT_STRING_ALLOWLIST = {
    SCHEMA_VERSION,
    "single_private_paper_formation_lineage",
    "retrospective_fixed_cutoff_single_case",
    "repository_commit_timestamp_before_current_pilot",
    "recursive_spawn_descendants_created_by_cutoff",
    "single_byte_snapshot_exact_header_plus_pinned_native_suffix",
    "first_parseable_future_timestamp_stops_physical_prefix",
    "exact_old_project_index_ids_only_no_fuzzy_content_matches",
    "pinned_codex_legacy_fork_filter_drops_inter_agent_records",
    "keyed_selection_manifest_commitment",
    "selection_root",
    "selected_descendant",
    "user_provenance",
    "subagent_provenance",
    "pinned_primary",
    "pinned_secondary",
    "other",
    "lifecycle_metadata_only",
    "unavailable",
    "declared_index_unavailable_or_unsupported",
    "repository_outcome_not_remote_receipt",
    "one_parent_lineage_not_independent_tasks",
    "lexical_wrappers_are_not_proved_effects",
    "call_ids_are_not_durable_effect_tickets",
    "thread_rollback_is_not_semantic_restore",
    "context_compaction_is_not_checkpoint_restore",
    "no_unsafe_history_rate_or_causal_safety_label",
    "tool_calls_and_results",
    "file_writes",
    "failures_and_retries",
    "fork_or_sidechain_actions",
    "external_effect_attempts",
    "legacy",
    "v2",
    "rust-v0.145.0",
    "rust-v0.146.0",
    "0.145.0",
    "0.146.0",
}
OUTPUT_STRING_ALLOWLIST.update(KNOWN_REASONING_EFFORTS)
OUTPUT_STRING_ALLOWLIST.update(
    source["commit"] for source in PINNED_CODEX_SOURCES.values()
)

# Privacy validation is intentionally redundant with construction.  These are
# schema keys, including normalized counter labels.  Decimal keys are allowed
# only for depth histograms; arbitrary free-form keys are never emitted.
OUTPUT_KEY_ALLOWLIST = {
    "aggregate_committed_prefix_bytes",
    "aggregate_patch_change_entries",
    "all_project_files_including_target_index",
    "ambiguous_duplicate_or_missing_id_groups_within_thread",
    "auxiliary_stores",
    "backups",
    "blocked_metrics",
    "call_events_without_one_to_one_pair",
    "call_events_without_one_to_one_pair_by_tool",
    "call_kind_counts",
    "call_tool_counts",
    "calls_with_string_id",
    "calls_without_string_id",
    "case",
    "claude",
    "claude_selector",
    "codex",
    "codex_selector",
    "commit",
    "commitment_kind",
    "contract",
    "counts",
    "counts_by_role",
    "created_at_max_offset_from_cutoff_seconds",
    "created_at_min_offset_from_cutoff_seconds",
    "currently_reachable_commits_all_refs",
    "currently_reachable_commits_in_case_window",
    "custom_call_status_counts",
    "cutoff_basis",
    "cutoff_commit_hmac_sha256",
    "cutoff_commit_verified",
    "cutoff_utc",
    "declared_raw_paths_existing",
    "depth_counts",
    "design",
    "distinct_matching_session_ids",
    "duplicate_call_id_events_within_thread",
    "duplicate_result_id_events_within_thread",
    "edge_snapshot_hmac_sha256",
    "entries_with_message_count",
    "event_shapes",
    "evidence_role",
    "exact_id_reference_files",
    "exact_ids_referenced_by_other_project_indexes",
    "file_history",
    "files_committed_at_snapshot_eof",
    "files_stopped_at_first_future_timestamp",
    "files_with_inherited_prefix",
    "global_exact_filename_scan",
    "header_provenance_counts",
    "history_jsonl_distinct_session_ids",
    "history_jsonl_exists",
    "history_jsonl_read_errors",
    "history_mode",
    "index_message_count_sum",
    "indexed_entries",
    "inherited_prefix_rows_excluded",
    "integrity_anomaly_counts",
    "integrity_anomaly_rows_excluded",
    "interpretation",
    "interpretive_limits",
    "kind_compatible_one_to_one_pairs_within_thread",
    "kind_mismatched_singleton_ids_within_thread",
    "lexical_wrapper_observations",
    "lexical_wrapper_one_to_one_result_markers",
    "lifecycle_observations",
    "lineage",
    "matching_local_headers",
    "matching_native_boundaries",
    "matching_nodes",
    "model_category_counts",
    "one_to_one_exec_result_marker_counts",
    "one_to_one_pair_tool_counts",
    "patch_apply_end_counts",
    "payload_type_counts",
    "physical_cutoff_rule",
    "project_index_parse_errors",
    "project_index_walk_errors",
    "project_indexes_scanned",
    "raw_action_corpus_available",
    "raw_call_events",
    "raw_result_events",
    "reason",
    "reasoning_effort_counts",
    "recovery_skipped",
    "reference_scan_read_errors",
    "repository",
    "result_events_without_one_to_one_pair",
    "result_kind_counts",
    "results_with_string_id",
    "results_without_string_id",
    "role_counts",
    "rollout_files",
    "rollout_selector",
    "root_has_external_parent",
    "root_hmac_sha256",
    "schema_version",
    "selected_exact_timestamped_rows",
    "selection",
    "sidechain_entries",
    "source_contract",
    "source_fidelity",
    "source_manifest_hmac_sha256",
    "spawn_edges",
    "subagent_multi_agent_version",
    "supported_cli_version_counts",
    "tag",
    "threads",
    "tool_calls_by_role",
    "tool_protocol",
    "top_level_type_counts",
    "unique_call_ids_within_thread_sum",
    "unique_result_ids_within_thread_sum",
    "unique_session_ids",
    "upstream",
    "walk_errors_observed",
    "workspace_observations",
}
OUTPUT_KEY_ALLOWLIST.update(KNOWN_TOOL_NAMES)
OUTPUT_KEY_ALLOWLIST.update(KNOWN_TOP_LEVEL_TYPES)
OUTPUT_KEY_ALLOWLIST.update(KNOWN_PAYLOAD_TYPES)
OUTPUT_KEY_ALLOWLIST.update(KNOWN_REASONING_EFFORTS)
OUTPUT_KEY_ALLOWLIST.update(KNOWN_MODEL_LABELS.values())
OUTPUT_KEY_ALLOWLIST.update(PINNED_CODEX_SOURCES)
OUTPUT_KEY_ALLOWLIST.update(LEXICAL_ACTION_PATTERNS)
OUTPUT_KEY_ALLOWLIST.update(
    {
        "other",
        "selection_root",
        "selected_descendant",
        "user_provenance",
        "subagent_provenance",
        "compacted_record",
        "inter_agent_metadata",
        "success",
        "failure_or_unknown",
        "completed",
        "in_progress",
        "failed",
        "non_list_result",
        "yielded_running_session",
        "explicit_failure_marker",
        "completed_marker",
        "no_standard_status_marker",
        "unicode_decode",
        "json_decode",
        "non_object_json",
        "missing_timestamp",
        "unparseable_timestamp",
    }
)

DIGEST_VALUE_KEYS = {
    "cutoff_commit_hmac_sha256",
    "edge_snapshot_hmac_sha256",
    "root_hmac_sha256",
    "source_manifest_hmac_sha256",
}


def iso_utc(value: int | float | dt.datetime) -> str:
    if not isinstance(value, dt.datetime):
        value = dt.datetime.fromtimestamp(value, UTC)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def json_command(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def normalized_name(value: Any, allowed: set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "other"


def sorted_counts(counter: collections.Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def load_json_argument(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def exec_result_status(output: Any) -> str:
    if not isinstance(output, list):
        return "non_list_result"
    texts = [
        item.get("text", "")
        for item in output
        if isinstance(item, dict)
        and item.get("type") == "input_text"
        and isinstance(item.get("text"), str)
    ]
    if any(text.startswith("Script running") for text in texts):
        return "yielded_running_session"
    if any(
        text.startswith(("Script failed", "Tool error", "Error:"))
        or re.search(r"\b(?:exit|exited)[ _-]?code\D+[1-9]\d*\b", text[:800], re.I)
        for text in texts
    ):
        return "explicit_failure_marker"
    if any(text.startswith("Script completed") for text in texts):
        return "completed_marker"
    return "no_standard_status_marker"


def commitment(key: bytes, domain: str, chunks: Iterable[bytes | str]) -> str:
    if len(key) < 32:
        raise RuntimeError("commitment key must contain at least 32 bytes")
    digest = hmac.new(key, digestmod=hashlib.sha256)
    digest.update(domain.encode("utf-8"))
    digest.update(b"\0")
    for chunk in chunks:
        raw = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def git_cutoff(repo: Path, commit: str) -> tuple[str, str, int]:
    full = json_command(["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], repo)
    committed = json_command(["git", "show", "-s", "--format=%cI", full], repo)
    cutoff = parse_iso(committed)
    return full, iso_utc(cutoff), int(cutoff.timestamp())


def _thread_columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(threads)")}


def _thread_record(connection: sqlite3.Connection, thread_id: str) -> dict[str, Any] | None:
    available = _thread_columns(connection)
    required = {"id", "rollout_path", "created_at"}
    if not required.issubset(available):
        raise RuntimeError("unsupported threads schema")
    optional = [
        name
        for name in (
            "model",
            "reasoning_effort",
            "cli_version",
            "history_mode",
            "source",
            "thread_source",
        )
        if name in available
    ]
    columns = ["id", "rollout_path", "created_at", *optional]
    row = connection.execute(
        f"SELECT {','.join(columns)} FROM threads WHERE id = ?", (thread_id,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    for name in (
        "model",
        "reasoning_effort",
        "cli_version",
        "history_mode",
        "source",
        "thread_source",
    ):
        result.setdefault(name, None)
    return result


def read_lineage(
    db_path: Path, root_id: str, cutoff_epoch: int, commitment_key: bytes
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select and validate a rooted tree from a read-only DB snapshot."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        # Pin every schema, edge, and thread read below to one SQLite snapshot.
        connection.execute("BEGIN")
        edge_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(thread_spawn_edges)")
        }
        if not {"parent_thread_id", "child_thread_id"}.issubset(edge_columns):
            raise RuntimeError("unsupported spawn-edge schema")
        status_expr = "status" if "status" in edge_columns else "NULL AS status"
        edge_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT parent_thread_id, child_thread_id, " + status_expr
                + " FROM thread_spawn_edges"
            )
        ]

        adjacency: dict[str, list[tuple[str, str | None]]] = collections.defaultdict(list)
        incoming: dict[str, list[tuple[str, str | None]]] = collections.defaultdict(list)
        for edge in edge_rows:
            parent = edge["parent_thread_id"]
            child = edge["child_thread_id"]
            status = edge["status"]
            if not isinstance(parent, str) or not isinstance(child, str):
                raise RuntimeError("spawn edge contains a non-string endpoint")
            if status is not None and status not in KNOWN_EDGE_STATUSES:
                raise RuntimeError("spawn edge contains an unsupported status")
            adjacency[parent].append((child, status))
            incoming[child].append((parent, status))

        root = _thread_record(connection, root_id)
        if root is None or not isinstance(root.get("created_at"), int):
            raise RuntimeError("root thread was not found in the read-only index")
        if int(root["created_at"]) > cutoff_epoch:
            raise RuntimeError("root thread is newer than the cutoff")

        selected: dict[str, dict[str, Any]] = {root_id: root}
        depths = {root_id: 0}
        queue = collections.deque([root_id])
        while queue:
            parent = queue.popleft()
            for child, _status in sorted(adjacency.get(parent, [])):
                candidate = _thread_record(connection, child)
                if candidate is None or not isinstance(candidate.get("created_at"), int):
                    raise RuntimeError("spawn edge references a missing thread")
                if int(candidate["created_at"]) > cutoff_epoch:
                    continue
                if child not in selected:
                    selected[child] = candidate
                    depths[child] = depths[parent] + 1
                    queue.append(child)

        # Validate the selected induced graph rather than assuming nodes-1.
        selected_edges: list[tuple[str, str, str | None]] = []
        for parent in selected:
            for child, status in adjacency.get(parent, []):
                if child in selected:
                    selected_edges.append((parent, child, status))
        if len(set(selected_edges)) != len(selected_edges):
            raise RuntimeError("selected lineage contains duplicate edges")
        if len(selected_edges) != len(selected) - 1:
            raise RuntimeError("selected lineage is not a tree")
        for node in selected:
            total_incoming = incoming.get(node, [])
            if node == root_id:
                if len(total_incoming) > 1:
                    raise RuntimeError("selected root has multiple parents")
                if any(parent in selected for parent, _status in total_incoming):
                    raise RuntimeError("selected root participates in a cycle")
            else:
                if len(total_incoming) != 1 or total_incoming[0][0] not in selected:
                    raise RuntimeError("selected non-root does not have one selected parent")

        colour: dict[str, int] = {}

        def visit(node: str) -> None:
            state = colour.get(node, 0)
            if state == 1:
                raise RuntimeError("selected lineage contains a cycle")
            if state == 2:
                return
            colour[node] = 1
            for child, _status in adjacency.get(node, []):
                if child in selected:
                    visit(child)
            colour[node] = 2

        visit(root_id)
        if len(colour) != len(selected):
            raise RuntimeError("selected lineage is disconnected")

        records: list[dict[str, Any]] = []
        for node in sorted(selected, key=lambda value: (depths[value], int(selected[value]["created_at"]), value)):
            record = selected[node]
            record["depth"] = depths[node]
            parents = incoming.get(node, [])
            record["expected_parent_id"] = parents[0][0] if parents else None
            records.append(record)

        external_root_edges = [
            (parent, root_id, status)
            for parent, status in incoming.get(root_id, [])
            if parent not in selected
        ]
        for parent, _child, _status in external_root_edges:
            if _thread_record(connection, parent) is None:
                raise RuntimeError(
                    "selected root references a missing external-parent endpoint"
                )
        committed_edges = sorted(selected_edges + external_root_edges)
        lineage_meta = {
            "spawn_edges": len(selected_edges),
            "root_has_external_parent": bool(external_root_edges),
            "root_hmac_sha256": commitment(commitment_key, "root-v3", [root_id]),
            "edge_snapshot_hmac_sha256": commitment(
                commitment_key,
                "edges-v3",
                [
                    json.dumps(edge, separators=(",", ":"), ensure_ascii=True)
                    for edge in committed_edges
                ],
            ),
        }
        return records, lineage_meta
    finally:
        connection.close()


def _event_payload(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _parse_raw_event(raw: bytes) -> tuple[dict[str, Any] | None, str | None]:
    try:
        event = json.loads(raw)
    except UnicodeDecodeError:
        return None, "unicode_decode"
    except json.JSONDecodeError:
        return None, "json_decode"
    if not isinstance(event, dict):
        return None, "non_object_json"
    return event, None


def _event_time(event: dict[str, Any]) -> tuple[dt.datetime | None, str | None]:
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        return None, "missing_timestamp"
    try:
        return parse_iso(timestamp), None
    except ValueError:
        return None, "unparseable_timestamp"


def _subagent_header(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    source = payload.get("source")
    nested: dict[str, Any] = {}
    if isinstance(source, dict):
        subagent = source.get("subagent")
        if isinstance(subagent, dict) and isinstance(subagent.get("thread_spawn"), dict):
            nested = subagent["thread_spawn"]
    declared = payload.get("thread_source") == "subagent"
    structured = bool(nested)
    if declared != structured:
        raise RuntimeError("ambiguous local subagent provenance")
    return declared, nested


def _validate_header(record: dict[str, Any], payload: dict[str, Any]) -> bool:
    version = payload.get("cli_version")
    history = payload.get("history_mode")
    if version not in PINNED_CODEX_SOURCES:
        raise RuntimeError("unsupported Codex source version")
    if history != PINNED_HISTORY_MODE:
        raise RuntimeError("unsupported Codex history mode")
    if record.get("cli_version") not in {None, version}:
        raise RuntimeError("DB/header Codex version mismatch")
    if record.get("history_mode") not in {None, history}:
        raise RuntimeError("DB/header history mode mismatch")

    is_subagent, nested = _subagent_header(payload)
    expected_parent = record.get("expected_parent_id")
    if is_subagent:
        if payload.get("multi_agent_version") != PINNED_MULTI_AGENT_VERSION:
            raise RuntimeError("unsupported multi-agent source version")
        header_parent = payload.get("parent_thread_id")
        nested_parent = nested.get("parent_thread_id")
        if (
            not isinstance(expected_parent, str)
            or header_parent != expected_parent
            or nested_parent != expected_parent
        ):
            raise RuntimeError("DB/header parent provenance mismatch")
    elif expected_parent is not None:
        raise RuntimeError("DB parent edge conflicts with local user provenance")
    return is_subagent


def _new_part(depth: int) -> dict[str, Any]:
    return {
        "depth": depth,
        "role": "selection_root" if depth == 0 else "selected_descendant",
        "header_provenance": None,
        "cli_version": None,
        "matching_header_count": 0,
        "native_boundary_found": False,
        "prefix_rows": 0,
        "selected_exact_rows": 0,
        "integrity_anomalies": collections.Counter(),
        "future_stop_found": False,
        "committed_prefix_bytes": 0,
        "committed_prefix_sha256": hashlib.sha256(),
        "selected_digest": hashlib.sha256(),
        "top_types": collections.Counter(),
        "payload_types": collections.Counter(),
        "lifecycle": collections.Counter(),
        "call_kinds": collections.Counter(),
        "call_tools": collections.Counter(),
        "call_statuses": collections.Counter(),
        "result_kinds": collections.Counter(),
        "patch": collections.Counter(),
        "patch_changed_entries": 0,
        "lexical": collections.Counter(),
        "calls": [],
        "results": [],
        "exec_inputs": {},
    }


def _read_rollout_snapshot(path: Path) -> list[bytes]:
    """Capture one stable regular-file byte image for all parsing passes."""
    if path.is_symlink():
        raise RuntimeError("rollout snapshot path must not be a symlink")
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("rollout snapshot source must be a regular file")
        data = source.read(before.st_size + 1)
        after_fd = os.fstat(source.fileno())
    try:
        after_path = path.stat()
    except OSError as error:
        raise RuntimeError("rollout snapshot path changed during capture") from error

    identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    before_identity = tuple(getattr(before, field) for field in identity_fields)
    after_fd_identity = tuple(getattr(after_fd, field) for field in identity_fields)
    after_path_identity = tuple(getattr(after_path, field) for field in identity_fields)
    if (
        len(data) != before.st_size
        or before_identity != after_fd_identity
        or before_identity != after_path_identity
    ):
        raise RuntimeError("rollout changed while capturing immutable byte snapshot")
    return data.splitlines(keepends=True)


def process_codex_rollout(record: dict[str, Any], cutoff: dt.datetime) -> dict[str, Any]:
    """Normalize one rollout under the pinned upstream source contract."""
    thread_id = record.get("id")
    if not isinstance(thread_id, str):
        raise RuntimeError("selected thread has no string ID")
    path = Path(record["rollout_path"])
    result = _new_part(int(record["depth"]))
    snapshot_lines = _read_rollout_snapshot(path)

    matching_headers: list[
        tuple[int, dict[str, Any], dt.datetime | None, str | None]
    ] = []
    first_future_line: int | None = None
    first_metadata: tuple[
        int, dict[str, Any], dt.datetime | None, str | None
    ] | None = None
    last_task_started_before_metadata: tuple[
        int, dt.datetime | None, str | None
    ] | None = None

    for line_number, raw in enumerate(snapshot_lines, 1):
        event, _error = _parse_raw_event(raw)
        if event is None:
            continue
        payload = _event_payload(event)
        event_time, time_error = _event_time(event)
        if event_time is not None and event_time > cutoff:
            first_future_line = line_number
            break
        if event.get("type") == "session_meta" and payload.get("id") == thread_id:
            matching_headers.append((line_number, payload, event_time, time_error))
        if first_metadata is None:
            if (
                event.get("type") == "event_msg"
                and payload.get("type") == "task_started"
            ):
                last_task_started_before_metadata = (
                    line_number,
                    event_time,
                    time_error,
                )
            if event.get("type") == "inter_agent_communication_metadata":
                first_metadata = (line_number, payload, event_time, time_error)

    result["matching_header_count"] = len(matching_headers)
    if len(matching_headers) != 1:
        raise RuntimeError("selected rollout must have exactly one matching local header")
    header_line, header_payload, header_time, _header_time_error = matching_headers[0]
    if header_time is None:
        raise RuntimeError("matching local header must have a valid timestamp")
    is_subagent = _validate_header(record, header_payload)
    result["header_provenance"] = (
        "subagent_provenance" if is_subagent else "user_provenance"
    )
    result["cli_version"] = header_payload["cli_version"]

    if is_subagent:
        if first_metadata is None:
            raise RuntimeError("pinned subagent rollout has no valid native marker")
        first_metadata_line, first_metadata_payload, metadata_time, _metadata_error = (
            first_metadata
        )
        if metadata_time is None:
            raise RuntimeError("native marker must have a valid timestamp")
        if first_metadata_payload.get("trigger_turn") is not True:
            raise RuntimeError("initial native marker must trigger a turn")
        if (
            last_task_started_before_metadata is None
            or last_task_started_before_metadata[0] <= header_line
        ):
            raise RuntimeError("native marker has no preceding child task start")
        native_boundary_line, task_time, _task_time_error = (
            last_task_started_before_metadata
        )
        if task_time is None:
            raise RuntimeError("native child task start must have a valid timestamp")
        if first_future_line is not None and native_boundary_line >= first_future_line:
            raise RuntimeError("native boundary occurs after the fixed cutoff prefix")
    else:
        native_boundary_line = header_line
    result["native_boundary_found"] = True

    for line_number, raw in enumerate(snapshot_lines, 1):
        if first_future_line is not None and line_number >= first_future_line:
            result["future_stop_found"] = True
            break
        result["committed_prefix_bytes"] += len(raw)
        result["committed_prefix_sha256"].update(raw)

        selected_region = line_number == header_line or line_number >= native_boundary_line
        if not selected_region:
            result["prefix_rows"] += 1
            continue
        event, parse_error = _parse_raw_event(raw)
        if event is None:
            result["integrity_anomalies"][parse_error or "parse_error"] += 1
            continue
        event_time, time_error = _event_time(event)
        if event_time is None:
            result["integrity_anomalies"][time_error or "timestamp_error"] += 1
            continue
        if event_time > cutoff:
            raise RuntimeError("future-stop invariant violated")

        result["selected_exact_rows"] += 1
        result["selected_digest"].update(raw)
        payload = _event_payload(event)
        top_type = normalized_name(event.get("type"), KNOWN_TOP_LEVEL_TYPES)
        result["top_types"][top_type] += 1
        payload_type = normalized_name(payload.get("type"), KNOWN_PAYLOAD_TYPES)
        if payload.get("type") is not None:
            result["payload_types"][payload_type] += 1
        if payload_type in LIFECYCLE_PAYLOADS:
            result["lifecycle"][payload_type] += 1
        if event.get("type") == "compacted":
            result["lifecycle"]["compacted_record"] += 1
        if event.get("type") == "inter_agent_communication_metadata":
            result["lifecycle"]["inter_agent_metadata"] += 1

        if payload_type == "patch_apply_end":
            success = payload.get("success")
            result["patch"]["success" if success is True else "failure_or_unknown"] += 1
            changes = payload.get("changes")
            if isinstance(changes, (list, dict)):
                result["patch_changed_entries"] += len(changes)

        if event.get("type") != "response_item":
            continue
        if payload_type in CALL_TO_RESULT_KIND:
            call_id = payload.get("call_id")
            tool = normalized_name(payload.get("name"), KNOWN_TOOL_NAMES)
            result["call_kinds"][payload_type] += 1
            result["call_tools"][tool] += 1
            if payload_type == "custom_tool_call":
                status = payload.get("status")
                result["call_statuses"][
                    status if status in {"completed", "in_progress", "failed"} else "other"
                ] += 1
            result["calls"].append((call_id, tool, payload_type))
            if isinstance(call_id, str):
                if tool == "exec" and isinstance(payload.get("input"), str):
                    executable = payload["input"]
                    result["exec_inputs"].setdefault(call_id, []).append(executable)
                    for label, pattern in LEXICAL_ACTION_PATTERNS.items():
                        matches = list(pattern.finditer(executable))
                        if label.endswith("call_site"):
                            result["lexical"][label] += len(matches)
                        elif matches:
                            result["lexical"][label] += 1
            continue
        if payload_type in set(CALL_TO_RESULT_KIND.values()):
            result["result_kinds"][payload_type] += 1
            result["results"].append(
                (payload.get("call_id"), payload_type, payload.get("output"))
            )

    return result


def _correlate_part(part: dict[str, Any]) -> dict[str, Any]:
    calls_by_id: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    calls_with_string_id = 0
    non_string_call_tools: collections.Counter[str] = collections.Counter()
    for call_id, tool, kind in part["calls"]:
        if isinstance(call_id, str):
            calls_with_string_id += 1
            calls_by_id[call_id].append((tool, kind))
        else:
            non_string_call_tools[tool] += 1
    results_by_id: dict[str, list[tuple[str, Any]]] = collections.defaultdict(list)
    results_with_string_id = 0
    for call_id, kind, output in part["results"]:
        if isinstance(call_id, str):
            results_with_string_id += 1
            results_by_id[call_id].append((kind, output))

    pairs = 0
    kind_mismatches = 0
    ambiguous_groups = 0
    missing_by_tool: collections.Counter[str] = collections.Counter()
    pair_tools: collections.Counter[str] = collections.Counter()
    exec_markers: collections.Counter[str] = collections.Counter()
    lexical_markers: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for call_id in sorted(set(calls_by_id) | set(results_by_id)):
        calls = calls_by_id.get(call_id, [])
        results = results_by_id.get(call_id, [])
        if len(calls) == 1 and len(results) == 1:
            tool, call_kind = calls[0]
            result_kind, output = results[0]
            if CALL_TO_RESULT_KIND[call_kind] == result_kind:
                pairs += 1
                pair_tools[tool] += 1
                if tool == "exec":
                    marker = exec_result_status(output)
                    exec_markers[marker] += 1
                    executable_values = part["exec_inputs"].get(call_id, [])
                    if len(executable_values) == 1:
                        executable = executable_values[0]
                        for label, pattern in LEXICAL_ACTION_PATTERNS.items():
                            if not label.endswith("call_site") and pattern.search(executable):
                                lexical_markers[label][marker] += 1
            else:
                kind_mismatches += 1
                missing_by_tool[tool] += 1
        else:
            ambiguous_groups += 1
            for tool, _kind in calls:
                missing_by_tool[tool] += 1

    raw_call_events = sum(part["call_kinds"].values())
    raw_result_events = sum(part["result_kinds"].values())
    missing_by_tool.update(non_string_call_tools)
    return {
        "raw_call_events": raw_call_events,
        "calls_with_string_id": calls_with_string_id,
        "calls_without_string_id": raw_call_events - calls_with_string_id,
        "unique_call_ids_within_thread_sum": len(calls_by_id),
        "duplicate_call_id_events_within_thread": calls_with_string_id
        - len(calls_by_id),
        "raw_result_events": raw_result_events,
        "results_with_string_id": results_with_string_id,
        "results_without_string_id": raw_result_events - results_with_string_id,
        "unique_result_ids_within_thread_sum": len(results_by_id),
        "duplicate_result_id_events_within_thread": results_with_string_id
        - len(results_by_id),
        "kind_compatible_one_to_one_pairs_within_thread": pairs,
        "kind_mismatched_singleton_ids_within_thread": kind_mismatches,
        "ambiguous_duplicate_or_missing_id_groups_within_thread": ambiguous_groups,
        "call_events_without_one_to_one_pair": raw_call_events - pairs,
        "result_events_without_one_to_one_pair": raw_result_events - pairs,
        "missing_by_tool": missing_by_tool,
        "pair_tools": pair_tools,
        "exec_markers": exec_markers,
        "lexical_markers": lexical_markers,
    }


def collect_codex(
    db_path: Path,
    root_id: str,
    cutoff_iso: str,
    cutoff_epoch: int,
    commitment_key: bytes,
) -> dict[str, Any]:
    records, lineage_meta = read_lineage(db_path, root_id, cutoff_epoch, commitment_key)
    cutoff = parse_iso(cutoff_iso)
    parts = [process_codex_rollout(record, cutoff) for record in records]

    depth_counts: collections.Counter[str] = collections.Counter()
    role_counts: collections.Counter[str] = collections.Counter()
    provenance_counts: collections.Counter[str] = collections.Counter()
    version_counts: collections.Counter[str] = collections.Counter()
    model_counts: collections.Counter[str] = collections.Counter()
    effort_counts: collections.Counter[str] = collections.Counter()
    totals = {
        key: collections.Counter()
        for key in (
            "top_types",
            "payload_types",
            "lifecycle",
            "call_kinds",
            "call_tools",
            "call_statuses",
            "result_kinds",
            "patch",
            "lexical",
        )
    }
    role_tool_calls: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    role_lifecycle: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    anomaly_counts: collections.Counter[str] = collections.Counter()
    protocol_counts: collections.Counter[str] = collections.Counter()
    missing_by_tool: collections.Counter[str] = collections.Counter()
    pair_tools: collections.Counter[str] = collections.Counter()
    exec_markers: collections.Counter[str] = collections.Counter()
    lexical_markers: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    selected_rows = prefix_rows = prefix_files = patch_entries = 0
    future_stop_files = committed_prefix_bytes = 0
    manifest_chunks: list[str] = []

    for record, part in zip(records, parts):
        depth_counts[str(part["depth"])] += 1
        role_counts[part["role"]] += 1
        provenance_counts[part["header_provenance"]] += 1
        version_counts[part["cli_version"]] += 1
        model_counts[KNOWN_MODEL_LABELS.get(record.get("model"), "other")] += 1
        effort_counts[normalized_name(record.get("reasoning_effort"), KNOWN_REASONING_EFFORTS)] += 1
        for key in totals:
            totals[key].update(part[key])
        role_tool_calls[part["role"]].update(part["call_tools"])
        role_lifecycle[part["role"]].update(part["lifecycle"])
        anomaly_counts.update(part["integrity_anomalies"])
        selected_rows += part["selected_exact_rows"]
        prefix_rows += part["prefix_rows"]
        prefix_files += int(part["prefix_rows"] > 0)
        future_stop_files += int(part["future_stop_found"])
        committed_prefix_bytes += part["committed_prefix_bytes"]
        patch_entries += part["patch_changed_entries"]

        correlation = _correlate_part(part)
        for key in (
            "raw_call_events",
            "calls_with_string_id",
            "calls_without_string_id",
            "unique_call_ids_within_thread_sum",
            "duplicate_call_id_events_within_thread",
            "raw_result_events",
            "results_with_string_id",
            "results_without_string_id",
            "unique_result_ids_within_thread_sum",
            "duplicate_result_id_events_within_thread",
            "kind_compatible_one_to_one_pairs_within_thread",
            "kind_mismatched_singleton_ids_within_thread",
            "ambiguous_duplicate_or_missing_id_groups_within_thread",
            "call_events_without_one_to_one_pair",
            "result_events_without_one_to_one_pair",
        ):
            protocol_counts[key] += correlation[key]
        missing_by_tool.update(correlation["missing_by_tool"])
        pair_tools.update(correlation["pair_tools"])
        exec_markers.update(correlation["exec_markers"])
        for label, counter in correlation["lexical_markers"].items():
            lexical_markers[label].update(counter)

        manifest_chunks.append(
            json.dumps(
                {
                    "id": record["id"],
                    "parent": record.get("expected_parent_id"),
                    "path": record["rollout_path"],
                    "created_at": record.get("created_at"),
                    "depth": record.get("depth"),
                    "prefix_bytes": part["committed_prefix_bytes"],
                    "prefix_sha256": part["committed_prefix_sha256"].hexdigest(),
                    "selected_sha256": part["selected_digest"].hexdigest(),
                    "db_model": record.get("model"),
                    "db_reasoning_effort": record.get("reasoning_effort"),
                    "db_cli_version": record.get("cli_version"),
                    "db_history_mode": record.get("history_mode"),
                    "db_source": record.get("source"),
                    "db_thread_source": record.get("thread_source"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    if sum(totals["top_types"].values()) != selected_rows:
        raise RuntimeError("top-level event arithmetic invariant failed")
    if protocol_counts["raw_call_events"] != sum(totals["call_kinds"].values()):
        raise RuntimeError("call-event arithmetic invariant failed")
    if protocol_counts["raw_result_events"] != sum(totals["result_kinds"].values()):
        raise RuntimeError("result-event arithmetic invariant failed")

    created = [int(record["created_at"]) for record in records]
    source_fidelity = {
        "rollout_files": len(parts),
        "matching_local_headers": sum(part["matching_header_count"] for part in parts),
        "matching_native_boundaries": sum(part["native_boundary_found"] for part in parts),
        "header_provenance_counts": sorted_counts(provenance_counts),
        "supported_cli_version_counts": sorted_counts(version_counts),
        "history_mode": PINNED_HISTORY_MODE,
        "subagent_multi_agent_version": PINNED_MULTI_AGENT_VERSION,
        "files_with_inherited_prefix": prefix_files,
        "inherited_prefix_rows_excluded": prefix_rows,
        "selected_exact_timestamped_rows": selected_rows,
        "integrity_anomaly_rows_excluded": sum(anomaly_counts.values()),
        "integrity_anomaly_counts": sorted_counts(anomaly_counts),
        "files_stopped_at_first_future_timestamp": future_stop_files,
        "files_committed_at_snapshot_eof": len(parts) - future_stop_files,
        "aggregate_committed_prefix_bytes": committed_prefix_bytes,
        "source_manifest_hmac_sha256": commitment(
            commitment_key, "source-manifest-v3", sorted(manifest_chunks)
        ),
        "commitment_kind": "keyed_selection_manifest_commitment",
    }
    return {
        "lineage": {
            "threads": len(records),
            "spawn_edges": lineage_meta["spawn_edges"],
            "root_has_external_parent": lineage_meta["root_has_external_parent"],
            "depth_counts": sorted_counts(depth_counts),
            "role_counts": sorted_counts(role_counts),
            "created_at_min_offset_from_cutoff_seconds": min(created) - cutoff_epoch,
            "created_at_max_offset_from_cutoff_seconds": max(created) - cutoff_epoch,
            "model_category_counts": sorted_counts(model_counts),
            "reasoning_effort_counts": sorted_counts(effort_counts),
            "root_hmac_sha256": lineage_meta["root_hmac_sha256"],
            "edge_snapshot_hmac_sha256": lineage_meta["edge_snapshot_hmac_sha256"],
        },
        "source_contract": {
            "contract": "pinned_codex_legacy_fork_filter_drops_inter_agent_records",
            "upstream": {
                version: PINNED_CODEX_SOURCES[version]
                for version in sorted(PINNED_CODEX_SOURCES)
            },
        },
        "source_fidelity": source_fidelity,
        "event_shapes": {
            "top_level_type_counts": sorted_counts(totals["top_types"]),
            "payload_type_counts": sorted_counts(totals["payload_types"]),
        },
        "tool_protocol": {
            **{key: protocol_counts[key] for key in sorted(protocol_counts)},
            "call_kind_counts": sorted_counts(totals["call_kinds"]),
            "result_kind_counts": sorted_counts(totals["result_kinds"]),
            "call_tool_counts": sorted_counts(totals["call_tools"]),
            "one_to_one_pair_tool_counts": sorted_counts(pair_tools),
            "call_events_without_one_to_one_pair_by_tool": sorted_counts(missing_by_tool),
            "custom_call_status_counts": sorted_counts(totals["call_statuses"]),
            "one_to_one_exec_result_marker_counts": sorted_counts(exec_markers),
            "tool_calls_by_role": {
                role: sorted_counts(counter)
                for role, counter in sorted(role_tool_calls.items())
            },
        },
        "lifecycle_observations": {
            "counts": sorted_counts(totals["lifecycle"]),
            "counts_by_role": {
                role: sorted_counts(counter)
                for role, counter in sorted(role_lifecycle.items())
            },
        },
        "workspace_observations": {
            "patch_apply_end_counts": sorted_counts(totals["patch"]),
            "aggregate_patch_change_entries": patch_entries,
        },
        "lexical_wrapper_observations": sorted_counts(totals["lexical"]),
        "lexical_wrapper_one_to_one_result_markers": {
            label: sorted_counts(counter)
            for label, counter in sorted(lexical_markers.items())
        },
    }


def exact_id_filename_scan(home: Path, ids: set[str]) -> dict[str, int]:
    matched_ids: set[str] = set()
    matched_nodes = 0
    errors = [0]

    def record_error(_error: OSError) -> None:
        errors[0] += 1

    for _root, directories, files in os.walk(home, followlinks=False, onerror=record_error):
        for name in directories + files:
            for session_id in ids:
                if (
                    name == session_id
                    or name.startswith(session_id + ".")
                    or name.startswith(session_id + "-")
                ):
                    matched_ids.add(session_id)
                    matched_nodes += 1
    return {
        "matching_nodes": matched_nodes,
        "distinct_matching_session_ids": len(matched_ids),
        "walk_errors_observed": errors[0],
    }


def _iter_regular_files(
    paths: Iterable[Path], onerror: Any | None = None
) -> Iterator[Path]:
    def report(error: OSError) -> None:
        if onerror is not None:
            onerror(error)

    for path in paths:
        try:
            mode = path.lstat().st_mode
        except OSError as error:
            report(error)
            continue
        if stat.S_ISREG(mode):
            yield path
        elif stat.S_ISDIR(mode):
            for root, directories, files in os.walk(
                path, followlinks=False, onerror=report
            ):
                retained_directories: list[str] = []
                for name in directories:
                    candidate = Path(root) / name
                    try:
                        candidate_mode = candidate.lstat().st_mode
                    except OSError as error:
                        report(error)
                        continue
                    if stat.S_ISDIR(candidate_mode):
                        retained_directories.append(name)
                directories[:] = retained_directories
                for name in files:
                    candidate = Path(root) / name
                    try:
                        candidate_mode = candidate.lstat().st_mode
                    except OSError as error:
                        report(error)
                        continue
                    if stat.S_ISREG(candidate_mode):
                        yield candidate


def exact_id_reference_file_count(paths: Iterable[Path], ids: set[str]) -> tuple[int, int]:
    """Pure-Python exact byte scan; private IDs never appear in process argv."""
    needles = [value.encode("utf-8") for value in ids]
    overlap = max((len(needle) for needle in needles), default=1) - 1
    matched = 0
    errors = 0

    def record_walk_error(_error: OSError) -> None:
        nonlocal errors
        errors += 1

    for path in _iter_regular_files(paths, onerror=record_walk_error):
        try:
            found = False
            tail = b""
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    window = tail + chunk
                    if any(needle in window for needle in needles):
                        found = True
                        break
                    tail = window[-overlap:] if overlap else b""
        except OSError:
            errors += 1
            continue
        if found:
            matched += 1
    return matched, errors


def file_distinct_id_count(path: Path, ids: set[str]) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        data = path.read_bytes()
    except OSError:
        return 0, 1
    return sum(value.encode("utf-8") in data for value in ids), 0


def discover_project_indexes(projects: Path, selected_index: Path) -> tuple[list[Path], int]:
    """Enumerate one-level Claude project indexes with explicit walk errors."""
    indexes = {selected_index}
    errors = 0
    try:
        with os.scandir(projects) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    candidate = Path(entry.path) / "sessions-index.json"
                    candidate_mode = candidate.lstat().st_mode
                except FileNotFoundError:
                    continue
                except OSError:
                    errors += 1
                    continue
                if stat.S_ISREG(candidate_mode):
                    indexes.add(candidate)
    except OSError:
        errors += 1
    return sorted(indexes), errors


def collect_claude(index_path: Path, home: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or not isinstance(index.get("entries"), list):
        raise RuntimeError("unsupported declared Claude index schema")
    entries = index.get("entries", [])
    if any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("sessionId"), str)
        or CANONICAL_SESSION_ID_RE.fullmatch(entry["sessionId"]) is None
        or not isinstance(entry.get("fullPath"), str)
        or not entry["fullPath"]
        or not isinstance(entry.get("messageCount"), int)
        or not isinstance(entry.get("isSidechain"), bool)
        for entry in entries
    ):
        raise RuntimeError("unsupported declared Claude index entry schema")
    if len({entry["sessionId"] for entry in entries}) != len(entries):
        raise RuntimeError("declared Claude index repeats a session ID")
    ids = {
        entry.get("sessionId")
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("sessionId"), str)
    }
    declared_existing = sum(
        Path(entry["fullPath"]).exists()
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("fullPath"), str)
    )
    sidechains = sum(
        entry.get("isSidechain") is True for entry in entries if isinstance(entry, dict)
    )
    message_counts = [
        entry.get("messageCount")
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("messageCount"), int)
    ]

    projects = home / ".claude" / "projects"
    all_indexes, project_index_walk_errors = discover_project_indexes(
        projects, index_path
    )
    other_index_refs: set[str] = set()
    index_parse_errors = 0
    for path in all_indexes:
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            index_parse_errors += 1
            continue
        if path == index_path:
            continue
        for entry in candidate.get("entries", []):
            if isinstance(entry, dict) and entry.get("sessionId") in ids:
                other_index_refs.add(entry["sessionId"])

    filename_scan = exact_id_filename_scan(home, ids)
    claude = home / ".claude"
    project_refs, project_errors = exact_id_reference_file_count([projects], ids)
    backup_refs, backup_errors = exact_id_reference_file_count([claude / "backups"], ids)
    auxiliary_dirs = [
        claude / name
        for name in (
            "debug",
            "sessions",
            "tasks",
            "todos",
            "session-env",
            "shell-snapshots",
            "telemetry",
            "usage-data",
            "plugins",
            "statsig",
            "cache",
            "jobs",
            "daemon",
            "ide",
        )
    ]
    auxiliary_refs, auxiliary_errors = exact_id_reference_file_count(auxiliary_dirs, ids)
    file_history_refs, history_errors = exact_id_reference_file_count(
        [claude / "file-history"], ids
    )
    history_path = claude / "history.jsonl"
    history_id_count, history_read_errors = file_distinct_id_count(history_path, ids)
    return {
        "evidence_role": "lifecycle_metadata_only",
        "indexed_entries": len(entries),
        "unique_session_ids": len(ids),
        "sidechain_entries": sidechains,
        "entries_with_message_count": len(message_counts),
        "index_message_count_sum": sum(message_counts),
        "declared_raw_paths_existing": declared_existing,
        "project_indexes_scanned": len(all_indexes),
        "project_index_parse_errors": index_parse_errors,
        "project_index_walk_errors": project_index_walk_errors,
        "exact_ids_referenced_by_other_project_indexes": len(other_index_refs),
        "global_exact_filename_scan": filename_scan,
        "exact_id_reference_files": {
            "all_project_files_including_target_index": project_refs,
            "backups": backup_refs,
            "file_history": file_history_refs,
            "auxiliary_stores": auxiliary_refs,
            "history_jsonl_distinct_session_ids": history_id_count,
            "history_jsonl_exists": history_path.exists(),
            "history_jsonl_read_errors": history_read_errors,
        },
        "reference_scan_read_errors": (
            project_errors
            + backup_errors
            + auxiliary_errors
            + history_errors
            + history_read_errors
        ),
        "raw_action_corpus_available": False,
        "blocked_metrics": [
            "tool_calls_and_results",
            "file_writes",
            "failures_and_retries",
            "fork_or_sidechain_actions",
            "external_effect_attempts",
        ],
    }


def collect_declared_claude_or_unavailable(index_path: Path, home: Path) -> dict[str, Any]:
    """Never guess another Claude source when the declared index is unusable."""
    try:
        return collect_claude(index_path, home)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError):
        return {
            "evidence_role": "unavailable",
            "reason": "declared_index_unavailable_or_unsupported",
            "raw_action_corpus_available": False,
        }


def collect_git(repo: Path, cutoff_iso: str, root_created_epoch: int) -> dict[str, Any]:
    all_count = int(json_command(["git", "rev-list", "--all", "--count"], repo))
    window = json_command(
        [
            "git",
            "log",
            "--all",
            "--format=%H",
            f"--since={iso_utc(root_created_epoch)}",
            f"--until={cutoff_iso}",
        ],
        repo,
    ).splitlines()
    return {
        "cutoff_commit_verified": True,
        "currently_reachable_commits_all_refs": all_count,
        "currently_reachable_commits_in_case_window": len(set(window)),
        "interpretation": "repository_outcome_not_remote_receipt",
    }


def _privacy_output_schema() -> dict[str, Any]:
    """Return the exact public JSON shape accepted by ``privacy_assertions``.

    Ordinary dictionaries below are sparse schemas: a synthetic test may
    validate one subtree, but every present child must occur at that complete
    path.  Production calls pass the complete generated document.  Counter
    maps additionally restrict their dynamic labels and scalar ranges.
    """

    integer = ("integer",)
    nonnegative = ("nonnegative_integer",)
    boolean = ("boolean",)
    digest = ("sha256",)
    timestamp = ("utc_timestamp",)

    def enum(*values: str) -> tuple[str, frozenset[str]]:
        return ("enum", frozenset(values))

    def counter(keys: Iterable[str]) -> tuple[str, frozenset[str]]:
        return ("counter", frozenset(keys))

    def mapping(
        keys: Iterable[str], value_schema: Any
    ) -> tuple[str, frozenset[str], Any]:
        return ("mapping", frozenset(keys), value_schema)

    def sequence(value_schema: Any) -> tuple[str, Any]:
        return ("sequence", value_schema)

    tools = KNOWN_TOOL_NAMES | {"other"}
    roles = {"selection_root", "selected_descendant"}
    result_markers = {
        "non_list_result",
        "yielded_running_session",
        "explicit_failure_marker",
        "completed_marker",
        "no_standard_status_marker",
    }
    lifecycle = LIFECYCLE_PAYLOADS | {"compacted_record", "inter_agent_metadata"}
    anomalies = {
        "unicode_decode",
        "json_decode",
        "non_object_json",
        "missing_timestamp",
        "unparseable_timestamp",
    }

    return {
        "schema_version": enum(SCHEMA_VERSION),
        "selection": {
            "case": enum("single_private_paper_formation_lineage"),
            "design": enum("retrospective_fixed_cutoff_single_case"),
            "cutoff_basis": enum(
                "repository_commit_timestamp_before_current_pilot"
            ),
            "cutoff_commit_hmac_sha256": digest,
            "cutoff_utc": timestamp,
            "codex_selector": enum(
                "recursive_spawn_descendants_created_by_cutoff"
            ),
            "rollout_selector": enum(
                "single_byte_snapshot_exact_header_plus_pinned_native_suffix"
            ),
            "physical_cutoff_rule": enum(
                "first_parseable_future_timestamp_stops_physical_prefix"
            ),
            "claude_selector": enum(
                "exact_old_project_index_ids_only_no_fuzzy_content_matches"
            ),
        },
        "codex": {
            "lineage": {
                "threads": nonnegative,
                "spawn_edges": nonnegative,
                "root_has_external_parent": boolean,
                "depth_counts": ("decimal_counter",),
                "role_counts": counter(roles),
                "created_at_min_offset_from_cutoff_seconds": integer,
                "created_at_max_offset_from_cutoff_seconds": integer,
                "model_category_counts": counter(
                    set(KNOWN_MODEL_LABELS.values()) | {"other"}
                ),
                "reasoning_effort_counts": counter(
                    KNOWN_REASONING_EFFORTS | {"other"}
                ),
                "root_hmac_sha256": digest,
                "edge_snapshot_hmac_sha256": digest,
            },
            "source_contract": {
                "contract": enum(
                    "pinned_codex_legacy_fork_filter_drops_inter_agent_records"
                ),
                "upstream": {
                    version: {
                        "tag": enum(source["tag"]),
                        "commit": enum(source["commit"]),
                    }
                    for version, source in PINNED_CODEX_SOURCES.items()
                },
            },
            "source_fidelity": {
                "rollout_files": nonnegative,
                "matching_local_headers": nonnegative,
                "matching_native_boundaries": nonnegative,
                "header_provenance_counts": counter(
                    {"user_provenance", "subagent_provenance"}
                ),
                "supported_cli_version_counts": counter(PINNED_CODEX_SOURCES),
                "history_mode": enum(PINNED_HISTORY_MODE),
                "subagent_multi_agent_version": enum(PINNED_MULTI_AGENT_VERSION),
                "files_with_inherited_prefix": nonnegative,
                "inherited_prefix_rows_excluded": nonnegative,
                "selected_exact_timestamped_rows": nonnegative,
                "integrity_anomaly_rows_excluded": nonnegative,
                "integrity_anomaly_counts": counter(anomalies),
                "files_stopped_at_first_future_timestamp": nonnegative,
                "files_committed_at_snapshot_eof": nonnegative,
                "aggregate_committed_prefix_bytes": nonnegative,
                "source_manifest_hmac_sha256": digest,
                "commitment_kind": enum("keyed_selection_manifest_commitment"),
            },
            "event_shapes": {
                "top_level_type_counts": counter(
                    KNOWN_TOP_LEVEL_TYPES | {"other"}
                ),
                "payload_type_counts": counter(KNOWN_PAYLOAD_TYPES | {"other"}),
            },
            "tool_protocol": {
                "ambiguous_duplicate_or_missing_id_groups_within_thread": nonnegative,
                "call_events_without_one_to_one_pair": nonnegative,
                "call_events_without_one_to_one_pair_by_tool": counter(tools),
                "call_kind_counts": counter(CALL_TO_RESULT_KIND),
                "call_tool_counts": counter(tools),
                "calls_with_string_id": nonnegative,
                "calls_without_string_id": nonnegative,
                "custom_call_status_counts": counter(
                    {"completed", "in_progress", "failed", "other"}
                ),
                "duplicate_call_id_events_within_thread": nonnegative,
                "duplicate_result_id_events_within_thread": nonnegative,
                "kind_compatible_one_to_one_pairs_within_thread": nonnegative,
                "kind_mismatched_singleton_ids_within_thread": nonnegative,
                "one_to_one_exec_result_marker_counts": counter(result_markers),
                "one_to_one_pair_tool_counts": counter(tools),
                "raw_call_events": nonnegative,
                "raw_result_events": nonnegative,
                "result_events_without_one_to_one_pair": nonnegative,
                "result_kind_counts": counter(set(CALL_TO_RESULT_KIND.values())),
                "results_with_string_id": nonnegative,
                "results_without_string_id": nonnegative,
                "tool_calls_by_role": mapping(roles, counter(tools)),
                "unique_call_ids_within_thread_sum": nonnegative,
                "unique_result_ids_within_thread_sum": nonnegative,
            },
            "lifecycle_observations": {
                "counts": counter(lifecycle),
                "counts_by_role": mapping(roles, counter(lifecycle)),
            },
            "workspace_observations": {
                "patch_apply_end_counts": counter(
                    {"success", "failure_or_unknown"}
                ),
                "aggregate_patch_change_entries": nonnegative,
            },
            "lexical_wrapper_observations": counter(LEXICAL_ACTION_PATTERNS),
            "lexical_wrapper_one_to_one_result_markers": mapping(
                LEXICAL_ACTION_PATTERNS, counter(result_markers)
            ),
        },
        "claude": {
            "evidence_role": enum("lifecycle_metadata_only", "unavailable"),
            "reason": enum("declared_index_unavailable_or_unsupported"),
            "recovery_skipped": boolean,
            "indexed_entries": nonnegative,
            "unique_session_ids": nonnegative,
            "sidechain_entries": nonnegative,
            "entries_with_message_count": nonnegative,
            "index_message_count_sum": nonnegative,
            "declared_raw_paths_existing": nonnegative,
            "project_indexes_scanned": nonnegative,
            "project_index_parse_errors": nonnegative,
            "project_index_walk_errors": nonnegative,
            "exact_ids_referenced_by_other_project_indexes": nonnegative,
            "global_exact_filename_scan": {
                "matching_nodes": nonnegative,
                "distinct_matching_session_ids": nonnegative,
                "walk_errors_observed": nonnegative,
            },
            "exact_id_reference_files": {
                "all_project_files_including_target_index": nonnegative,
                "backups": nonnegative,
                "file_history": nonnegative,
                "auxiliary_stores": nonnegative,
                "history_jsonl_distinct_session_ids": nonnegative,
                "history_jsonl_exists": boolean,
                "history_jsonl_read_errors": nonnegative,
            },
            "reference_scan_read_errors": nonnegative,
            "raw_action_corpus_available": boolean,
            "blocked_metrics": sequence(
                enum(
                    "tool_calls_and_results",
                    "file_writes",
                    "failures_and_retries",
                    "fork_or_sidechain_actions",
                    "external_effect_attempts",
                )
            ),
        },
        "repository": {
            "cutoff_commit_verified": boolean,
            "currently_reachable_commits_all_refs": nonnegative,
            "currently_reachable_commits_in_case_window": nonnegative,
            "interpretation": enum("repository_outcome_not_remote_receipt"),
        },
        "interpretive_limits": sequence(
            enum(
                "one_parent_lineage_not_independent_tasks",
                "lexical_wrappers_are_not_proved_effects",
                "call_ids_are_not_durable_effect_tickets",
                "thread_rollback_is_not_semantic_restore",
                "context_compaction_is_not_checkpoint_restore",
                "no_unsafe_history_rate_or_causal_safety_label",
            )
        ),
    }


def privacy_assertions(document: dict[str, Any], forbidden_values: Iterable[str]) -> None:
    """Validate exact output paths, types, public labels, and secret absence."""

    forbidden = [value for value in forbidden_values if value]

    def check_secret(value: str) -> None:
        if any(secret in value for secret in forbidden):
            raise RuntimeError("privacy schema rejected a forbidden value")
        if UUID_RE.search(value):
            raise RuntimeError("privacy schema rejected a UUID-shaped value")

    def check_integer(value: Any, *, nonnegative: bool, path: tuple[str, ...]) -> None:
        if type(value) is not int or (nonnegative and value < 0):
            raise RuntimeError(
                "privacy schema rejected an invalid integer at " + ".".join(path)
            )

    def walk(value: Any, schema: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(schema, dict):
            if not isinstance(value, dict):
                raise RuntimeError(
                    "privacy schema rejected a non-object at " + ".".join(path)
                )
            for key, child in value.items():
                if not isinstance(key, str):
                    raise RuntimeError("privacy schema rejected a non-string key")
                check_secret(key)
                if key not in schema:
                    raise RuntimeError(
                        "privacy schema rejected a key at " + ".".join((*path, key))
                    )
                walk(child, schema[key], (*path, key))
            return

        kind = schema[0]
        if kind == "integer":
            check_integer(value, nonnegative=False, path=path)
        elif kind == "nonnegative_integer":
            check_integer(value, nonnegative=True, path=path)
        elif kind == "boolean":
            if type(value) is not bool:
                raise RuntimeError(
                    "privacy schema rejected a non-Boolean at " + ".".join(path)
                )
        elif kind == "enum":
            if not isinstance(value, str):
                raise RuntimeError(
                    "privacy schema rejected a non-string enum at " + ".".join(path)
                )
            check_secret(value)
            if value not in schema[1]:
                raise RuntimeError(
                    "privacy schema rejected a string value at " + ".".join(path)
                )
        elif kind == "sha256":
            if not isinstance(value, str):
                raise RuntimeError(
                    "privacy schema rejected a non-string digest at " + ".".join(path)
                )
            check_secret(value)
            if SHA256_RE.fullmatch(value) is None:
                raise RuntimeError(
                    "privacy schema rejected a digest at " + ".".join(path)
                )
        elif kind == "utc_timestamp":
            if not isinstance(value, str):
                raise RuntimeError(
                    "privacy schema rejected a non-string timestamp at "
                    + ".".join(path)
                )
            check_secret(value)
            if ISO_RE.fullmatch(value) is None:
                raise RuntimeError(
                    "privacy schema rejected a timestamp at " + ".".join(path)
                )
        elif kind in {"counter", "decimal_counter"}:
            if not isinstance(value, dict):
                raise RuntimeError(
                    "privacy schema rejected a non-counter at " + ".".join(path)
                )
            allowed = schema[1] if kind == "counter" else None
            for key, child in value.items():
                if not isinstance(key, str):
                    raise RuntimeError("privacy schema rejected a non-string key")
                check_secret(key)
                if (allowed is not None and key not in allowed) or (
                    allowed is None and not key.isdecimal()
                ):
                    raise RuntimeError(
                        "privacy schema rejected a counter key at "
                        + ".".join((*path, key))
                    )
                check_integer(child, nonnegative=True, path=(*path, key))
        elif kind == "mapping":
            if not isinstance(value, dict):
                raise RuntimeError(
                    "privacy schema rejected a non-mapping at " + ".".join(path)
                )
            for key, child in value.items():
                if not isinstance(key, str):
                    raise RuntimeError("privacy schema rejected a non-string key")
                check_secret(key)
                if key not in schema[1]:
                    raise RuntimeError(
                        "privacy schema rejected a mapping key at "
                        + ".".join((*path, key))
                    )
                walk(child, schema[2], (*path, key))
        elif kind == "sequence":
            if not isinstance(value, list):
                raise RuntimeError(
                    "privacy schema rejected a non-list at " + ".".join(path)
                )
            for index, child in enumerate(value):
                walk(child, schema[1], (*path, str(index)))
        else:
            raise RuntimeError("privacy schema contains an unknown validator")

    walk(document, _privacy_output_schema())


def read_commitment_key(path: Path) -> bytes:
    raw = path.read_bytes().strip()
    if re.fullmatch(rb"[0-9a-fA-F]{64}", raw):
        raw = bytes.fromhex(raw.decode("ascii"))
    if len(raw) < 32:
        raise RuntimeError("commitment key file must contain at least 32 bytes")
    return raw


def parse_args() -> argparse.Namespace:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root-thread-id-file",
        type=Path,
        required=True,
        help="Private local input file; keeps the root ID out of process argv.",
    )
    parser.add_argument("--codex-db", type=Path, default=home / ".codex" / "state_5.sqlite")
    parser.add_argument(
        "--claude-index",
        type=Path,
        help="Explicit private index path; required unless Claude recovery is skipped.",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--cutoff-commit", default="5efc4ea")
    parser.add_argument(
        "--commitment-key-file",
        type=Path,
        required=True,
        help="Untracked local file containing at least 32 random bytes.",
    )
    parser.add_argument("--skip-global-claude-recovery", action="store_true")
    args = parser.parse_args()
    if not args.skip_global_claude_recovery and args.claude_index is None:
        parser.error("--claude-index is required unless Claude recovery is skipped")
    args.root_thread_id = args.root_thread_id_file.read_text(encoding="utf-8").strip()
    if not args.root_thread_id:
        parser.error("--root-thread-id-file is empty")
    return args


def build_document(args: argparse.Namespace, commitment_key: bytes) -> dict[str, Any]:
    full_commit, cutoff_iso, cutoff_epoch = git_cutoff(args.repo, args.cutoff_commit)
    codex = collect_codex(
        args.codex_db,
        args.root_thread_id,
        cutoff_iso,
        cutoff_epoch,
        commitment_key,
    )
    if args.skip_global_claude_recovery:
        claude: dict[str, Any] = {"recovery_skipped": True}
    else:
        claude = collect_declared_claude_or_unavailable(args.claude_index, Path.home())
    root_created_epoch = cutoff_epoch + codex["lineage"][
        "created_at_min_offset_from_cutoff_seconds"
    ]
    git = collect_git(args.repo, cutoff_iso, root_created_epoch)
    return {
        "schema_version": SCHEMA_VERSION,
        "selection": {
            "case": "single_private_paper_formation_lineage",
            "design": "retrospective_fixed_cutoff_single_case",
            "cutoff_basis": "repository_commit_timestamp_before_current_pilot",
            "cutoff_commit_hmac_sha256": commitment(
                commitment_key, "cutoff-commit-v3", [full_commit]
            ),
            "cutoff_utc": cutoff_iso,
            "codex_selector": "recursive_spawn_descendants_created_by_cutoff",
            "rollout_selector": "single_byte_snapshot_exact_header_plus_pinned_native_suffix",
            "physical_cutoff_rule": "first_parseable_future_timestamp_stops_physical_prefix",
            "claude_selector": "exact_old_project_index_ids_only_no_fuzzy_content_matches",
        },
        "codex": codex,
        "claude": claude,
        "repository": git,
        "interpretive_limits": [
            "one_parent_lineage_not_independent_tasks",
            "lexical_wrappers_are_not_proved_effects",
            "call_ids_are_not_durable_effect_tickets",
            "thread_rollback_is_not_semantic_restore",
            "context_compaction_is_not_checkpoint_restore",
            "no_unsafe_history_rate_or_causal_safety_label",
        ],
    }


def main() -> int:
    args = parse_args()
    commitment_key = read_commitment_key(args.commitment_key_file)
    document = build_document(args, commitment_key)
    privacy_assertions(
        document,
        [args.root_thread_id, str(Path.home()), str(args.repo), str(args.claude_index or "")],
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
