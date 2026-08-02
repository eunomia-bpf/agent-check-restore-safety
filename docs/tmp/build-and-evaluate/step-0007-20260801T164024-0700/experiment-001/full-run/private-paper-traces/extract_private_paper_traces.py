#!/usr/bin/env python3
"""Privacy-preserving, read-only audit of one paper-formation trace lineage.

The program reads Codex's local SQLite index and rollout JSONL files, but emits
only aggregate counts.  It never emits prompts, messages, tool arguments,
commands, tool results, session/thread IDs, rollout paths, working directories,
or file names from a patch.  Claude recovery is exact-ID based; fuzzy content
matches are deliberately excluded.

Important source-fidelity rule: full-history Codex child rollouts contain a
local ``session_meta`` header, then a copied parent-history prefix, then the
child's native turn.  For a child, this program retains its matching local
header and starts action counting at the last ``task_started`` before the first
``inter_agent_communication_metadata`` trigger. Counting whole files, or merely
starting at the first local header, would multiply parent history across
children.

The script does not mutate the DB, traces, repository, or Claude stores.  It
prints deterministic JSON to stdout.  The root thread ID is required at runtime
so the private identifier is not embedded in this artifact or its output.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Any, Iterable


UTC = dt.timezone.utc
SCHEMA_VERSION = "private-paper-trace-summary-v1"

# Only stable enum-like values are emitted. Unknown names are folded into
# ``other`` rather than copied from a private trace.
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

# These categories are intentionally lexical and overlapping.  They describe
# executable wrapper source, not proved effects or successful operations.
LEXICAL_ACTION_PATTERNS = {
    "nested_exec_command_call_site": re.compile(r"\btools\.exec_command\s*\("),
    "nested_apply_patch_call_site": re.compile(r"\btools\.apply_patch\s*\("),
    "nested_web_call_site": re.compile(r"\btools\.web__run\s*\("),
    "git_inspection_wrapper": re.compile(
        r"\bgit\s+(?:status|diff|log|show|rev-parse|ls-files|branch|remote)\b",
        re.IGNORECASE,
    ),
    "git_commit_wrapper": re.compile(r"\bgit\s+commit\b", re.IGNORECASE),
    "git_push_wrapper": re.compile(r"\bgit\s+push\b", re.IGNORECASE),
    "git_network_wrapper": re.compile(
        r"\bgit\s+(?:clone|fetch|pull|push)\b", re.IGNORECASE
    ),
    "build_or_test_wrapper": re.compile(
        r"\b(?:lake\s+build|pytest|cargo\s+(?:test|build|check)|npm\s+test|"
        r"pnpm\s+test|go\s+test|make(?:\s|$)|lean\b|mvn\s+test|gradle\s+test)",
        re.IGNORECASE,
    ),
    "network_or_download_wrapper": re.compile(
        r"\b(?:curl|wget|git\s+(?:clone|fetch|pull|push))\b|tools\.web__run",
        re.IGNORECASE,
    ),
    "process_or_service_wrapper": re.compile(
        r"\b(?:kill|pkill|systemctl|service|nohup|docker|podman|kubectl)\b",
        re.IGNORECASE,
    ),
    "database_wrapper": re.compile(
        r"\b(?:sqlite3|psql|mysql|mongosh|redis-cli)\b", re.IGNORECASE
    ),
    "shell_mutation_wrapper": re.compile(
        r"\b(?:mkdir|touch|cp|mv|rm|install)\b|(?:^|[^>])>{1,2}(?!=)",
        re.IGNORECASE,
    ),
}

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def iso_utc(value: int | float | dt.datetime) -> str:
    if not isinstance(value, dt.datetime):
        value = dt.datetime.fromtimestamp(value, UTC)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def json_command(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


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
    """Classify wrapper-level evidence without returning any result content."""
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


def git_cutoff(repo: Path, commit: str) -> tuple[str, str, int]:
    full = json_command(["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], repo)
    committed = json_command(["git", "show", "-s", "--format=%cI", full], repo)
    cutoff = parse_iso(committed)
    return full[:7], iso_utc(cutoff), int(cutoff.timestamp())


def read_lineage(
    db_path: Path, root_id: str, cutoff_epoch: int
) -> tuple[list[dict[str, Any]], int]:
    # mode=ro is the SQLite enforcement boundary for the trace index.
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            WITH RECURSIVE lineage(id, depth, parent_id) AS (
              SELECT id, 0, NULL FROM threads WHERE id = ?
              UNION ALL
              SELECT edge.child_thread_id, lineage.depth + 1, edge.parent_thread_id
              FROM thread_spawn_edges AS edge
              JOIN lineage ON edge.parent_thread_id = lineage.id
            )
            SELECT lineage.id, lineage.depth, lineage.parent_id,
                   threads.rollout_path, threads.created_at,
                   threads.model, threads.reasoning_effort
            FROM lineage JOIN threads ON threads.id = lineage.id
            WHERE threads.created_at <= ?
            ORDER BY threads.created_at, lineage.id
            """,
            (root_id, cutoff_epoch),
        ).fetchall()
    finally:
        connection.close()
    if not rows or rows[0]["id"] != root_id:
        raise RuntimeError("root thread was not found in the read-only index")
    records = [dict(row) for row in rows]
    selected = {row["id"] for row in records}
    edge_count = sum(
        1
        for row in records
        if row["parent_id"] is not None and row["parent_id"] in selected
    )
    return records, edge_count


def process_codex_rollout(
    record: dict[str, Any], cutoff: dt.datetime
) -> dict[str, Any]:
    thread_id = record["id"]
    path = Path(record["rollout_path"])
    depth = int(record["depth"])
    role = "interactive_parent" if depth == 0 else "delegated_child"

    result: dict[str, Any] = {
        "depth": depth,
        "role": role,
        "header_found": False,
        "native_boundary_found": False,
        "prefix_rows": 0,
        "selected_rows": 0,
        "selected_invalid_rows": 0,
        "selected_invalid_error_kinds": collections.Counter(),
        "selected_missing_timestamp_rows": 0,
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
        "calls": {},
        "results": [],
        "exec_inputs": {},
        "exec_result_status": collections.Counter(),
    }

    # Locate the child-local header and the structural end of the inherited
    # snapshot.  The copied events have their timestamps rewritten near fork
    # time, so timestamp filtering cannot identify the boundary.
    header_line: int | None = None
    native_boundary_line: int | None = None
    last_task_started_line: int | None = None
    with path.open("rb") as source:
        for line_number, raw in enumerate(source, 1):
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            if (
                event.get("type") == "session_meta"
                and payload.get("id") == thread_id
                and header_line is None
            ):
                header_line = line_number
            if depth == 0:
                continue
            if (
                event.get("type") == "event_msg"
                and payload.get("type") == "task_started"
            ):
                last_task_started_line = line_number
            if event.get("type") == "inter_agent_communication_metadata":
                native_boundary_line = last_task_started_line
                break

    if header_line is None:
        raise RuntimeError("a selected rollout has no matching local session header")
    if depth == 0:
        native_boundary_line = header_line
    if native_boundary_line is None:
        raise RuntimeError("a delegated rollout has no structural native-turn boundary")
    result["header_found"] = True
    result["native_boundary_found"] = True

    # Invalid rows have no timestamp. They are selected only before the first
    # valid row known to be after the cutoff; this makes an append-only live
    # source deterministic at the declared prefix.
    past_cutoff = False
    with path.open("rb") as source:
        for line_number, raw in enumerate(source, 1):
            selected_region = line_number == header_line or line_number >= native_boundary_line
            if not selected_region:
                result["prefix_rows"] += 1
                continue
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                if not past_cutoff:
                    result["selected_invalid_rows"] += 1
                    result["selected_invalid_error_kinds"][
                        "unicode_decode" if isinstance(error, UnicodeDecodeError) else "json_decode"
                    ] += 1
                    result["selected_digest"].update(raw)
                continue

            payload = event.get("payload")
            if not isinstance(payload, dict):
                payload = {}

            timestamp = event.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    event_time = parse_iso(timestamp)
                except ValueError:
                    event_time = None
                if event_time is not None and event_time > cutoff:
                    past_cutoff = True
                    continue
            else:
                event_time = None

            # Valid rows at or before the cutoff remain selected even if a
            # source contains an out-of-order future row.
            if event_time is not None and event_time <= cutoff:
                past_cutoff = False
            elif event_time is None:
                result["selected_missing_timestamp_rows"] += 1

            result["selected_rows"] += 1
            result["selected_digest"].update(raw)

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
            if payload_type in {"function_call", "custom_tool_call"}:
                call_id = payload.get("call_id")
                tool = normalized_name(payload.get("name"), KNOWN_TOOL_NAMES)
                result["call_kinds"][payload_type] += 1
                result["call_tools"][tool] += 1
                if payload_type == "custom_tool_call":
                    status = payload.get("status")
                    result["call_statuses"][
                        status if status in {"completed", "in_progress", "failed"} else "other"
                    ] += 1
                if isinstance(call_id, str):
                    if call_id in result["calls"]:
                        result["call_kinds"]["duplicate_call_id"] += 1
                    result["calls"][call_id] = (tool, payload_type)
                    if tool == "exec" and isinstance(payload.get("input"), str):
                        executable = payload["input"]
                        result["exec_inputs"][call_id] = executable
                        for label, pattern in LEXICAL_ACTION_PATTERNS.items():
                            matches = list(pattern.finditer(executable))
                            if label.endswith("call_site"):
                                result["lexical"][label] += len(matches)
                            elif matches:
                                result["lexical"][label] += 1
                continue

            if payload_type in {"function_call_output", "custom_tool_call_output"}:
                result["result_kinds"][payload_type] += 1
                result["results"].append(
                    (payload.get("call_id"), payload_type, payload.get("output"))
                )

    return result


def collect_codex(
    db_path: Path, root_id: str, cutoff_iso: str, cutoff_epoch: int
) -> dict[str, Any]:
    records, edge_count = read_lineage(db_path, root_id, cutoff_epoch)
    cutoff = parse_iso(cutoff_iso)
    parts = [process_codex_rollout(record, cutoff) for record in records]

    depth_counts: collections.Counter[str] = collections.Counter()
    role_counts: collections.Counter[str] = collections.Counter()
    model_counts: collections.Counter[str] = collections.Counter()
    effort_counts: collections.Counter[str] = collections.Counter()
    totals: dict[str, collections.Counter[str]] = {
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
            "exec_result_status",
        )
    }
    selected_rows = prefix_rows = invalid_rows = missing_timestamp = 0
    prefix_files = invalid_files = patch_entries = 0
    calls_total = results_total = matched_results = unmatched_results = 0
    missing_results = duplicate_results = 0
    missing_results_by_tool: collections.Counter[str] = collections.Counter()
    result_tools: collections.Counter[str] = collections.Counter()
    role_tool_calls: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    role_lifecycle: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    lexical_result_markers: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    invalid_error_kinds: collections.Counter[str] = collections.Counter()
    digests: list[str] = []

    for record, part in zip(records, parts):
        depth_counts[str(part["depth"])] += 1
        role_counts[part["role"]] += 1
        model = record.get("model")
        effort = record.get("reasoning_effort")
        model_counts[model if isinstance(model, str) and len(model) < 40 else "other"] += 1
        effort_counts[
            effort if effort in {"low", "medium", "high", "xhigh", "max", "ultra"} else "other"
        ] += 1
        for key in totals:
            totals[key].update(part[key])
        role_tool_calls[part["role"]].update(part["call_tools"])
        role_lifecycle[part["role"]].update(part["lifecycle"])
        selected_rows += part["selected_rows"]
        prefix_rows += part["prefix_rows"]
        invalid_rows += part["selected_invalid_rows"]
        invalid_error_kinds.update(part["selected_invalid_error_kinds"])
        missing_timestamp += part["selected_missing_timestamp_rows"]
        prefix_files += int(part["prefix_rows"] > 0)
        invalid_files += int(part["selected_invalid_rows"] > 0)
        patch_entries += part["patch_changed_entries"]
        calls_total += len(part["calls"])
        results_total += len(part["results"])

        seen_result_ids: collections.Counter[str] = collections.Counter()
        for call_id, _kind, output in part["results"]:
            if isinstance(call_id, str) and call_id in part["calls"]:
                matched_results += 1
                seen_result_ids[call_id] += 1
                tool = part["calls"][call_id][0]
                result_tools[tool] += 1
                if tool == "exec":
                    marker = exec_result_status(output)
                    part["exec_result_status"][marker] += 1
                    totals["exec_result_status"][marker] += 1
                    executable = part["exec_inputs"].get(call_id)
                    if isinstance(executable, str):
                        for label, pattern in LEXICAL_ACTION_PATTERNS.items():
                            if not label.endswith("call_site") and pattern.search(executable):
                                lexical_result_markers[label][marker] += 1
            else:
                unmatched_results += 1
        duplicate_results += sum(max(0, count - 1) for count in seen_result_ids.values())
        for call_id, (tool, _kind) in part["calls"].items():
            if seen_result_ids[call_id] == 0:
                missing_results += 1
                missing_results_by_tool[tool] += 1
        digests.append(part["selected_digest"].hexdigest())

    combined_digest = hashlib.sha256("\n".join(sorted(digests)).encode()).hexdigest()
    created_values = [int(record["created_at"]) for record in records]
    return {
        "lineage": {
            "threads": len(records),
            "spawn_edges": edge_count,
            "depth_counts": sorted_counts(depth_counts),
            "role_counts": sorted_counts(role_counts),
            "created_at_min_utc": iso_utc(min(created_values)),
            "created_at_max_utc": iso_utc(max(created_values)),
            "db_max_created_at_at_cutoff_epoch": max(created_values),
            "db_max_created_at_at_cutoff_utc": iso_utc(max(created_values)),
            "model_counts": sorted_counts(model_counts),
            "reasoning_effort_counts": sorted_counts(effort_counts),
        },
        "source_fidelity": {
            "rollout_files": len(parts),
            "matching_local_headers": sum(part["header_found"] for part in parts),
            "matching_structural_native_boundaries": sum(
                part["native_boundary_found"] for part in parts
            ),
            "files_with_inherited_prefix": prefix_files,
            "inherited_prefix_rows_excluded": prefix_rows,
            "selected_native_valid_rows": selected_rows,
            "selected_native_invalid_rows": invalid_rows,
            "selected_invalid_row_error_counts": sorted_counts(invalid_error_kinds),
            "files_with_selected_invalid_rows": invalid_files,
            "selected_valid_rows_without_parseable_timestamp": missing_timestamp,
            "selected_prefix_content_sha256": combined_digest,
        },
        "event_shapes": {
            "top_level_type_counts": sorted_counts(totals["top_types"]),
            "payload_type_counts": sorted_counts(totals["payload_types"]),
        },
        "tool_protocol": {
            "call_events": calls_total,
            "result_events": results_total,
            "matched_result_events": matched_results,
            "unmatched_result_events": unmatched_results,
            "calls_without_result": missing_results,
            "duplicate_call_ids_within_thread": totals["call_kinds"].get(
                "duplicate_call_id", 0
            ),
            "duplicate_results_for_same_call_within_thread": duplicate_results,
            "call_kind_counts": sorted_counts(totals["call_kinds"]),
            "result_kind_counts": sorted_counts(totals["result_kinds"]),
            "call_tool_counts": sorted_counts(totals["call_tools"]),
            "matched_result_tool_counts": sorted_counts(result_tools),
            "calls_without_result_by_tool": sorted_counts(missing_results_by_tool),
            "custom_call_status_counts": sorted_counts(totals["call_statuses"]),
            "exec_result_marker_counts": sorted_counts(totals["exec_result_status"]),
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
        "lexical_wrapper_result_markers": {
            label: sorted_counts(counter)
            for label, counter in sorted(lexical_result_markers.items())
        },
    }


def exact_id_filename_scan(home: Path, ids: set[str]) -> dict[str, int]:
    matched_ids: set[str] = set()
    matched_nodes = 0
    errors = [0]

    def record_walk_error(_error: OSError) -> None:
        errors[0] += 1

    for root, directories, files in os.walk(
        home, followlinks=False, onerror=record_walk_error
    ):
        # Do not prune: this is the documented exhaustive filename/component
        # recovery pass. It reads directory entries, not file contents.
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


def rg_reference_file_count(paths: Iterable[Path], ids: set[str]) -> int:
    existing = [str(path) for path in paths if path.exists()]
    if not existing:
        return 0
    command = ["rg", "-l", "--hidden", "--no-messages", "-F"]
    for session_id in sorted(ids):
        command.extend(["-e", session_id])
    command.extend(existing)
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError("exact-ID reference scan failed")
    return sum(1 for line in completed.stdout.splitlines() if line)


def file_distinct_id_count(path: Path, ids: set[str]) -> int:
    if not path.exists():
        return 0
    data = path.read_bytes()
    return sum(session_id.encode() in data for session_id in ids)


def collect_claude(index_path: Path, home: Path) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index.get("entries", [])
    ids = {
        entry.get("sessionId")
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("sessionId"), str)
    }
    created = [
        parse_iso(entry["created"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("created"), str)
    ]
    modified = [
        parse_iso(entry["modified"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("modified"), str)
    ]
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
    all_indexes = list(projects.glob("*/sessions-index.json"))
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
    project_reference_files = rg_reference_file_count([projects], ids)
    backup_reference_files = rg_reference_file_count([claude / "backups"], ids)
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
    auxiliary_reference_files = rg_reference_file_count(auxiliary_dirs, ids)
    file_history_reference_files = rg_reference_file_count(
        [claude / "file-history"], ids
    )
    history_ids = file_distinct_id_count(claude / "history.jsonl", ids)

    return {
        "evidence_role": "lifecycle_metadata_only",
        "indexed_entries": len(entries),
        "unique_session_ids": len(ids),
        "sidechain_entries": sidechains,
        "entries_with_message_count": len(message_counts),
        "index_message_count_sum": sum(message_counts),
        "created_at_min_utc": iso_utc(min(created)) if created else None,
        "created_at_max_utc": iso_utc(max(created)) if created else None,
        "modified_at_max_utc": iso_utc(max(modified)) if modified else None,
        "declared_raw_paths_existing": declared_existing,
        "project_indexes_scanned": len(all_indexes),
        "project_index_parse_errors": index_parse_errors,
        "exact_ids_referenced_by_other_project_indexes": len(other_index_refs),
        "global_exact_filename_scan": filename_scan,
        "exact_id_reference_files": {
            # The sole project hit is expected to be the target index itself;
            # a nonzero raw-session interpretation is expressly forbidden.
            "all_project_files_including_target_index": project_reference_files,
            "backups": backup_reference_files,
            "file_history": file_history_reference_files,
            "auxiliary_stores": auxiliary_reference_files,
            "history_jsonl_distinct_session_ids": history_ids,
        },
        "raw_action_corpus_available": False,
        "blocked_metrics": [
            "tool_calls_and_results",
            "file_writes",
            "failures_and_retries",
            "fork_or_sidechain_actions",
            "external_effect_attempts",
        ],
    }


def collect_git(repo: Path, cutoff_iso: str, root_created_iso: str, commit: str) -> dict[str, Any]:
    all_count = int(json_command(["git", "rev-list", "--all", "--count"], repo))
    window_lines = json_command(
        [
            "git",
            "log",
            "--all",
            "--format=%H",
            f"--since={root_created_iso}",
            f"--until={cutoff_iso}",
        ],
        repo,
    ).splitlines()
    return {
        "cutoff_commit_verified": True,
        "cutoff_commit_short": commit,
        "currently_reachable_commits_all_refs": all_count,
        "currently_reachable_commits_in_case_window": len(set(window_lines)),
        "interpretation": "repository outcome evidence; not a remote durability receipt",
    }


def privacy_assertions(document: dict[str, Any], private_root_id: str) -> None:
    # Inspect values, not schema keys: names such as ``command_call_site`` are
    # intentional aggregate labels, whereas a command string or private path
    # would occur as a value.
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
    leaks: list[str] = []
    for value in strings:
        if private_root_id in value or str(Path.home()) in value:
            leaks.append("private identifier or home path")
        if UUID_RE.search(value):
            leaks.append("uuid-shaped value")
    if leaks:
        raise RuntimeError("privacy assertion failed for redacted output schema")


def parse_args() -> argparse.Namespace:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-thread-id", required=True)
    parser.add_argument(
        "--codex-db", type=Path, default=home / ".codex" / "state_5.sqlite"
    )
    parser.add_argument(
        "--claude-index",
        type=Path,
        default=home
        / ".claude"
        / "projects"
        / "-home-yunwei37-workspace-agent-check-restore-safety"
        / "sessions-index.json",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--cutoff-commit", default="5efc4ea")
    parser.add_argument(
        "--skip-global-claude-recovery",
        action="store_true",
        help="Skip expensive exact-ID recovery; intended only for unit debugging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commit, cutoff_iso, cutoff_epoch = git_cutoff(args.repo, args.cutoff_commit)
    codex = collect_codex(args.codex_db, args.root_thread_id, cutoff_iso, cutoff_epoch)
    if args.skip_global_claude_recovery:
        claude: dict[str, Any] = {"recovery_skipped": True}
    else:
        claude = collect_claude(args.claude_index, Path.home())
    git = collect_git(
        args.repo,
        cutoff_iso,
        codex["lineage"]["created_at_min_utc"],
        commit,
    )
    document = {
        "schema_version": SCHEMA_VERSION,
        "selection": {
            "case": "single_private_paper_formation_lineage",
            "cutoff_basis": "repository_commit_timestamp_pre_pilot",
            "cutoff_commit_short": commit,
            "cutoff_utc": cutoff_iso,
            "codex_selector": "recursive_spawn_descendants_created_by_cutoff",
            "rollout_selector": "local_matching_session_header_plus_structural_native_turn_suffix_then_event_time_at_or_before_cutoff",
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
    privacy_assertions(document, args.root_thread_id)
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
