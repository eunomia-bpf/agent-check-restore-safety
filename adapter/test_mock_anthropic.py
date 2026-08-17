from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from adapter.mock_anthropic import DeterministicAnthropicServer


def _request(server: DeterministicAnthropicServer, messages: list[dict]) -> bytes:
    body = json.dumps(
        {
            "model": "fixture-model",
            "stream": True,
            "tools": [
                {
                    "name": "mcp__continuity__commit_effect",
                    "input_schema": {"type": "object"},
                }
            ],
            "messages": messages,
        }
    ).encode()
    request = Request(
        server.base_url + "/v1/messages?beta=true",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        return response.read()


class DeterministicAnthropicServerTests(unittest.TestCase):
    def test_streams_protected_call_then_done(self) -> None:
        with DeterministicAnthropicServer(("effect-A",)) as server:
            first = _request(
                server,
                [{"role": "user", "content": [{"type": "text", "text": "run"}]}],
            )
            self.assertIn(b'effect-A', first)
            second = _request(
                server,
                [
                    {"role": "user", "content": [{"type": "text", "text": "run"}]},
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool-1",
                                "name": "mcp__continuity__commit_effect",
                                "input": {"effect_id": "effect-A"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "tool-1"}],
                    },
                ],
            )
            self.assertIn(b'"text":"DONE"', second)
            self.assertEqual([record.ordinal for record in server.requests], [1, 2])
            self.assertIsNone(server.failure)

    def test_rejects_out_of_order_effect_history(self) -> None:
        with DeterministicAnthropicServer() as server:
            with self.assertRaises(HTTPError) as raised:
                _request(
                    server,
                    [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-1",
                                    "name": "mcp__continuity__commit_effect",
                                    "input": {"effect_id": "effect-B"},
                                }
                            ],
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": "tool-1"}
                            ],
                        },
                    ],
                )
            self.assertEqual(raised.exception.code, 400)
            self.assertIsNotNone(server.failure)

    def test_bounds_response_delay(self) -> None:
        with self.assertRaises(ValueError):
            DeterministicAnthropicServer(response_delay_seconds=1.1)


if __name__ == "__main__":
    unittest.main()
