#!/usr/bin/env python3
"""Unit and ordering tests for the Temporal main runner's deployment gate."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import textwrap
import unittest


RUNNER = Path(__file__).with_name("run-case.sh")
COMPATIBLE_RUNNER = Path(__file__).with_name("run-compatible.sh")
OLD_DRAIN_RUNNER = Path(__file__).with_name("run-old-drain-case.sh")
UNSAFE_RUNNER = RUNNER.parent.parent / "temporal-unsafe" / "run-unsafe-case.sh"
OLD_DRAIN_CHECKER = Path(__file__).with_name("check-old-drain.py")
FUNCTION_NAME = "wait_deployment_version_task_queues"
DEPLOYMENT = "safe-change-food-order-worker"
BUILD = "food-order-v2"
QUEUE = "safe-change-food-orders"


def version_snapshot(queues: list[dict[str, str]]) -> dict[str, object]:
    return {
        "deploymentName": DEPLOYMENT,
        "BuildID": BUILD,
        "taskQueuesInfos": queues,
    }


WORKFLOW_ONLY = version_snapshot([{"name": QUEUE, "type": "workflow"}])
EXPECTED = version_snapshot([
    {"name": QUEUE, "type": "activity"},
    {"name": QUEUE, "type": "workflow"},
])


def function_source(runner: Path = RUNNER) -> str:
    source = runner.read_text()
    match = re.search(
        rf"^{FUNCTION_NAME}\(\) \{{\n.*?^\}}\n",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"{FUNCTION_NAME} is absent from {runner}")
    return match.group(0)


class DeploymentVersionGateTest(unittest.TestCase):
    def invoke(
        self, snapshots: list[dict[str, object]], *, attempts: int | None = None,
        deployment: str = DEPLOYMENT, build: str = BUILD, queue: str = QUEUE,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object], int, list[str]]:
        self.assertTrue(snapshots)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, snapshot in enumerate(snapshots, 1):
                (root / f"{index}.json").write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
            output = root / "observed.json"
            call_count = root / "calls"
            call_count.write_text("0\n")
            call_args = root / "call-args"
            call_args.write_text("")
            limit = attempts if attempts is not None else len(snapshots)
            harness = textwrap.dedent(f"""\
                set -euo pipefail
                {function_source()}
                temporal_json() {{
                  local output=$1
                  shift
                  printf '%s\\n' "$*" >>"$CALL_ARGS"
                  local count
                  count=$(<"$CALL_COUNT")
                  count=$((count + 1))
                  printf '%s\\n' "$count" >"$CALL_COUNT"
                  local source="$SNAPSHOT_ROOT/$count.json"
                  if [[ ! -f "$source" ]]; then
                    source="$SNAPSHOT_ROOT/{len(snapshots)}.json"
                  fi
                  cp "$source" "$output"
                }}
                export DEPLOYMENT_VERSION_WAIT_ATTEMPTS={limit}
                export DEPLOYMENT_VERSION_WAIT_INTERVAL_SECONDS=0
                {FUNCTION_NAME} {shlex.quote(deployment)} {shlex.quote(build)} \
                  {shlex.quote(queue)} "$OUTPUT"
            """)
            completed = subprocess.run(
                ["bash", "-c", harness],
                env={
                    "PATH": "/usr/bin:/bin",
                    "SNAPSHOT_ROOT": str(root),
                    "CALL_COUNT": str(call_count),
                    "CALL_ARGS": str(call_args),
                    "OUTPUT": str(output),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            observed = json.loads(output.read_text())
            calls = int(call_count.read_text())
            arguments = call_args.read_text().splitlines()
        return completed, observed, calls, arguments

    def test_waits_until_both_task_queue_types_are_visible(self) -> None:
        completed, observed, calls, arguments = self.invoke([WORKFLOW_ONLY, EXPECTED])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(calls, 2)
        self.assertEqual(observed, EXPECTED)
        self.assertEqual(arguments, [
            "worker deployment describe-version --deployment-name "
            "safe-change-food-order-worker --build-id food-order-v2",
        ] * 2)

    def test_rejects_duplicate_wrong_queue_and_unknown_type(self) -> None:
        invalid = [
            version_snapshot([
                {"name": QUEUE, "type": "activity"},
                {"name": QUEUE, "type": "activity"},
            ]),
            version_snapshot([
                {"name": "wrong-queue", "type": "activity"},
                {"name": QUEUE, "type": "workflow"},
            ]),
            version_snapshot([
                {"name": QUEUE, "type": "activity"},
                {"name": QUEUE, "type": "workflow"},
                {"name": QUEUE, "type": "nexus"},
            ]),
        ]
        completed, observed, calls, _ = self.invoke([*invalid, EXPECTED])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(calls, 4)
        self.assertEqual(observed, EXPECTED)

    def test_timeout_keeps_the_last_snapshot(self) -> None:
        last = version_snapshot([{"name": QUEUE, "type": "activity"}])
        completed, observed, calls, _ = self.invoke([WORKFLOW_ONLY, last])
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "timed out waiting for deployment version food-order-v2 task queues",
            completed.stderr,
        )
        self.assertEqual(calls, 2)
        self.assertEqual(observed, last)

    def test_deployment_and_build_parameters_are_enforced(self) -> None:
        for label, arguments in (
            ("deployment", {"deployment": "wrong-deployment"}),
            ("build", {"build": "wrong-build"}),
        ):
            with self.subTest(label=label):
                completed, observed, calls, _ = self.invoke(
                    [EXPECTED], attempts=1, **arguments,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(calls, 1)
                self.assertEqual(observed, EXPECTED)


class RunnerOrderingTest(unittest.TestCase):
    def assert_gated_transition(
        self, runner: Path, workflow_poller: str, activity_poller: str,
        build: str, snapshot: str, set_current: str,
    ) -> None:
        source = runner.read_text()
        workflow = source.index(workflow_poller)
        activity = source.index(activity_poller, workflow)
        gate = source.index(FUNCTION_NAME, activity)
        version = source.index(f'"$results_dir/{snapshot}"', gate)
        current = source.index(set_current, version)
        self.assertLess(workflow, activity)
        self.assertLess(activity, gate)
        self.assertLess(gate, version)
        self.assertLess(version, current)
        region = source[gate:current]
        self.assertIn(f"{DEPLOYMENT} {build} {QUEUE}", region)

    def test_all_gate_implementations_are_identical(self) -> None:
        expected = function_source(RUNNER)
        self.assertEqual(function_source(COMPATIBLE_RUNNER), expected)
        self.assertEqual(function_source(UNSAFE_RUNNER), expected)

    def test_main_v1_and_v2_transitions_are_gated(self) -> None:
        for label, workflow, activity, build, snapshot, current in (
            (
                "v1",
                'wait_poller workflow food-order-v1 "$results_dir/v1-workflow-pollers.json"',
                'wait_poller activity food-order-v1 "$results_dir/v1-activity-pollers.json"',
                "food-order-v1", "version-v1.json",
                'temporal_json "$results_dir/set-current-v1.json" worker deployment set-current-version',
            ),
            (
                "v2",
                'wait_poller workflow food-order-v2 "$results_dir/v2-workflow-pollers.json"',
                'wait_poller activity food-order-v2 "$results_dir/v2-activity-pollers.json"',
                "food-order-v2", "version-v2-before-current.json",
                'temporal_json "$results_dir/set-current-v2.json" worker deployment set-current-version',
            ),
        ):
            with self.subTest(label=label):
                self.assert_gated_transition(
                    RUNNER, workflow, activity, build, snapshot, current,
                )

    def test_compatible_v1_and_target_transitions_are_gated(self) -> None:
        for label, workflow, activity, build, snapshot, current in (
            (
                "v1",
                'wait_poller workflow food-order-v1 "$results_dir/v1-workflow-pollers.json"',
                'wait_poller activity food-order-v1 "$results_dir/v1-activity-pollers.json"',
                "food-order-v1", "version-v1.json",
                'temporal_json "$results_dir/set-current-v1.json" worker deployment set-current-version',
            ),
            (
                "compatible",
                'wait_poller workflow food-order-compatible-v2 "$results_dir/compatible-workflow-pollers.json"',
                'wait_poller activity food-order-compatible-v2 "$results_dir/compatible-activity-pollers.json"',
                "food-order-compatible-v2", "version-compatible-before-current.json",
                'temporal_json "$results_dir/set-current-compatible.json" worker deployment set-current-version',
            ),
        ):
            with self.subTest(label=label):
                self.assert_gated_transition(
                    COMPATIBLE_RUNNER, workflow, activity, build, snapshot, current,
                )

    def test_unsafe_clean_source_and_native_target_transitions_are_gated(self) -> None:
        for label, workflow, activity, build, identity, snapshot, current in (
            (
                "clean-target", "clean-target-workflow-pollers.json",
                "clean-target-activity-pollers.json", "food-order-unsafe-v2",
                "safe-change-food-order-unsafe-v2-worker",
                "clean-target-version-before-current.json", "clean-set-current-target.json",
            ),
            (
                "main-source", "main-source-workflow-pollers.json",
                "main-source-activity-pollers.json", "food-order-v1",
                "safe-change-food-order-v1-worker",
                "main-source-version-before-current.json", "main-set-current-source.json",
            ),
            (
                "main-native-target", "main-target-workflow-pollers.json",
                "main-target-activity-pollers.json", "food-order-unsafe-v2",
                "safe-change-food-order-unsafe-v2-worker",
                "main-target-version-before-current.json", "main-set-current-target.json",
            ),
        ):
            with self.subTest(label=label):
                self.assert_gated_transition(
                    UNSAFE_RUNNER,
                    f"wait_poller workflow {build} {identity}",
                    f"wait_poller activity {build} {identity}",
                    build, snapshot,
                    f'temporal_json "$results_dir/{current}" worker deployment set-current-version',
                )
                source = UNSAFE_RUNNER.read_text()
                self.assertIn(f'"$results_dir/{workflow}"', source)
                self.assertIn(f'"$results_dir/{activity}"', source)

    def test_old_drain_has_no_exact_task_queue_version_oracle(self) -> None:
        self.assertNotIn(FUNCTION_NAME, OLD_DRAIN_RUNNER.read_text())
        self.assertNotIn("taskQueuesInfos", OLD_DRAIN_CHECKER.read_text())


if __name__ == "__main__":
    unittest.main()
