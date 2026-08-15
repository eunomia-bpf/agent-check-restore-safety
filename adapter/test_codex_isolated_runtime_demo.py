from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from adapter.codex_isolated_runtime_demo import (
    ComposeDeployment,
    DemoError,
    _find_vendor_bundle,
    _prepare_account_home,
    _safe_project_name,
    _validate_network_cut,
)


class IsolatedCodexDemoTests(unittest.TestCase):
    def test_explicit_vendor_bundle_requires_native_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(DemoError):
                _find_vendor_bundle(root)
            (root / "bin").mkdir()
            (root / "bin/codex").write_bytes(b"native")
            (root / "codex-resources").mkdir()
            self.assertEqual(_find_vendor_bundle(root), root.resolve())

    def test_account_home_copies_only_private_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "auth.json"
            source.write_text('{"credential":"fixture"}\n', encoding="utf-8")
            source.chmod(0o600)
            destination = root / "isolated"
            _prepare_account_home(source, destination)
            self.assertEqual(
                sorted(path.name for path in destination.iterdir()), ["auth.json"]
            )
            self.assertEqual((destination / "auth.json").stat().st_mode & 0o777, 0o600)

    def test_account_home_rejects_group_readable_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "auth.json"
            source.write_text("{}\n", encoding="utf-8")
            source.chmod(0o640)
            with self.assertRaisesRegex(DemoError, "not private"):
                _prepare_account_home(source, root / "isolated")

    def test_project_name_is_compose_safe_and_unique(self) -> None:
        left = _safe_project_name()
        right = _safe_project_name()
        self.assertRegex(left, r"^[a-z0-9][a-z0-9-]+$")
        self.assertNotEqual(left, right)

    def test_network_cut_requires_exact_three_party_topology(self) -> None:
        deployment = mock.Mock(spec=ComposeDeployment)
        deployment.agent_network = "project_agent"
        deployment.effects_network = "project_effects"
        deployment.service_container.side_effect = lambda service: service
        observed = {
            "codex": ["project_agent"],
            "control": ["project_agent", "project_effects"],
            "payment": ["project_effects"],
        }
        with (
            mock.patch(
                "adapter.codex_isolated_runtime_demo._container_networks",
                side_effect=lambda container: observed[container],
            ),
            mock.patch(
                "adapter.codex_isolated_runtime_demo._network_ip",
                return_value="172.30.0.2",
            ),
            mock.patch(
                "adapter.codex_isolated_runtime_demo._require_payment_blocked"
            ) as blocked,
        ):
            summary, observations = _validate_network_cut(deployment, "codex")
        blocked.assert_called_once_with("codex", "172.30.0.2")
        self.assertTrue(summary["control_is_only_bridge"])
        self.assertEqual(summary["control_health_from_codex"], "reachable")
        self.assertEqual(observations, blocked.return_value)

    def test_project_name_pattern_does_not_admit_underscores(self) -> None:
        self.assertIsNone(re.fullmatch(r"[a-z0-9][a-z0-9-]+", "bad_name"))


if __name__ == "__main__":
    unittest.main()
