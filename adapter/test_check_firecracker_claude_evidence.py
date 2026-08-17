from __future__ import annotations

import unittest

from . import check_firecracker_claude_evidence as checker


class FirecrackerClaudeEvidenceCheckerTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_fields(self) -> None:
        for value in (
            b'{"valid":true,"valid":false}',
            b'{"outer":{"pid":1,"pid":2}}',
        ):
            with self.assertRaises(checker.EvidenceError):
                checker._loads(value, "test evidence")

    def test_strict_json_preserves_normal_object(self) -> None:
        self.assertEqual(
            checker._loads(b'{"valid":true,"items":[1,2]}', "test evidence"),
            {"valid": True, "items": [1, 2]},
        )


if __name__ == "__main__":
    unittest.main()
