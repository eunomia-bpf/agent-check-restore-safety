from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import uuid

from adapter import check_claude_mcp_evidence as checker


class ClaudeEvidenceCheckerTests(unittest.TestCase):
    def test_history_hash_chain_rejects_one_byte_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            previous = checker._ZERO_HASH
            frames: list[bytes] = []
            for sequence in range(1, 8):
                operation = "event"
                data = {"value": sequence}
                digest = sha256(
                    b"history-event-v1\x00" + struct.pack(">Q", sequence)
                )
                for part in (
                    previous.encode(),
                    operation.encode(),
                    checker._canonical(data),
                ):
                    digest.update(struct.pack(">Q", len(part)))
                    digest.update(part)
                current = digest.hexdigest()
                event = {
                    "version": 1,
                    "sequence": sequence,
                    "operation": operation,
                    "data": data,
                    "previous_hash": previous,
                    "hash": current,
                }
                encoded = checker._canonical(event)
                frames.append(b"HST1" + struct.pack(">Q", len(encoded)) + encoded)
                previous = current
            history = root / "control.history"
            history.write_bytes(b"".join(frames))
            os.chmod(history, 0o600)
            self.assertEqual(len(checker._history(root)), 7)
            mutated = bytearray(history.read_bytes())
            mutated[-2] = ord("0") if mutated[-2] != ord("0") else ord("1")
            history.write_bytes(mutated)
            with self.assertRaises(checker.EvidenceError):
                checker._history(root)

    def test_conversation_reconstructs_ordered_effects(self) -> None:
        messages = [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "a",
                        "name": checker._TOOL,
                        "input": {"effect_id": "effect-A"},
                    }
                ]
            },
            {"content": [{"type": "tool_result", "tool_use_id": "a"}]},
        ]
        self.assertEqual(
            checker._conversation_effects(messages), (["effect-A"], ["effect-A"])
        )

    def test_conversation_rejects_unknown_effect(self) -> None:
        messages = [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "x",
                        "name": checker._TOOL,
                        "input": {"effect_id": "effect-X"},
                    }
                ]
            }
        ]
        with self.assertRaises(checker.EvidenceError):
            checker._conversation_effects(messages)

    def test_command_requires_bare_strict_mcp_mode(self) -> None:
        binary = Path("/tmp/claude")
        config = Path("/tmp/mcp.json")
        command = [
            os.fspath(binary),
            "--print",
            checker._PROMPT,
        ]
        with self.assertRaises(checker.EvidenceError):
            checker._check_command(command, binary, config, str(uuid.uuid4()))


if __name__ == "__main__":
    unittest.main()
