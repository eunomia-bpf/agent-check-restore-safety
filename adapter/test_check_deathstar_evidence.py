from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from adapter.check_codex_isolated_evidence import EvidenceError
from adapter.check_deathstar_evidence import (
    _fact_hash,
    _gateway_request_hash,
    _operation_id,
    check_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/tmp/bootstrap/step-0015-20260815T141250Z"


class DeathStarDerivationTests(unittest.TestCase):
    def test_operation_identity_binds_domain_and_call(self) -> None:
        first = _operation_id("deathstar-hotel", "reservation/A-17")
        self.assertRegex(first, r"^op-[0-9a-f]{64}$")
        self.assertNotEqual(first, _operation_id("another-domain", "reservation/A-17"))
        self.assertNotEqual(first, _operation_id("deathstar-hotel", "reservation/B-18"))

    def test_gateway_request_hash_binds_owned_headers_and_exact_body(self) -> None:
        operation_id = _operation_id("deathstar-hotel", "reservation/A-17")
        body = b'{"hotel_id":"1","rooms":1}'
        first = _gateway_request_hash("http://effect-v1:8090/v1/reserve", body, operation_id)
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            first,
            _gateway_request_hash("http://effect-v2:8090/v1/reserve", body, operation_id),
        )
        self.assertNotEqual(
            first,
            _gateway_request_hash(
                "http://effect-v1:8090/v1/reserve", body + b"\n", operation_id
            ),
        )

    def test_fact_hash_binds_every_business_field(self) -> None:
        fact = {
            "customer_name": "safe-op-a",
            "hotel_id": "1",
            "in_date": "2015-04-09",
            "out_date": "2015-04-10",
            "rooms": 1,
        }
        first = _fact_hash([fact])
        changed = dict(fact)
        changed["rooms"] = 2
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first, _fact_hash([changed]))


@unittest.skipUnless(
    (EVIDENCE / "result.json").exists(), "retained DeathStar evidence is absent"
)
class DeathStarEvidenceMutationTests(unittest.TestCase):
    def copy_evidence(self, temporary: str) -> Path:
        destination = Path(temporary) / "evidence"
        shutil.copytree(EVIDENCE, destination)
        return destination

    @staticmethod
    def rewrite(path: Path, mutate) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )

    def assert_mutation_fails(self, relative: str, mutate) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            self.rewrite(evidence / relative, mutate)
            with self.assertRaises(EvidenceError):
                check_evidence(evidence)

    def test_retained_real_run_passes_independent_check(self) -> None:
        verdict = check_evidence(EVIDENCE)
        self.assertTrue(verdict["valid"])
        self.assertTrue(verdict["history_chain_replayed"])
        self.assertEqual(verdict["raw_retry_mongo_rows"], 2)
        self.assertEqual(verdict["old_mongo_rows"], 1)
        self.assertTrue(verdict["recovered_by_query"])

    def test_binary_history_byte_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "state/runtime.history"
            contents = bytearray(path.read_bytes())
            contents[-2] ^= 1
            path.write_bytes(contents)
            with self.assertRaisesRegex(EvidenceError, "History"):
                check_evidence(evidence)

    def test_mongo_count_mutation_fails_closed(self) -> None:
        self.assert_mutation_fails(
            "proposed/mongo-old.json", lambda value: value.__setitem__("count", 2)
        )

    def test_mongo_fact_mutation_fails_closed(self) -> None:
        self.assert_mutation_fails(
            "proposed/mongo-old.json",
            lambda value: value["facts"][0].__setitem__("hotel_id", "forged"),
        )

    def test_observer_fact_hash_mutation_fails_closed(self) -> None:
        def mutate(value) -> None:
            succeeded = next(item for item in value["facts"] if item["outcome"] == "succeeded")
            succeeded["fact_hash"] = "f" * 64

        self.assert_mutation_fails("adapter/observer-facts.json", mutate)

    def test_observer_identity_mutation_fails_closed(self) -> None:
        def mutate(value) -> None:
            succeeded = next(item for item in value["facts"] if item["outcome"] == "succeeded")
            succeeded["operation_id"] = "op-" + "e" * 64

        self.assert_mutation_fails("adapter/observer-facts.json", mutate)

    def test_upstream_commit_mutation_fails_closed(self) -> None:
        self.assert_mutation_fails(
            "upstream.json",
            lambda value: value["releases"]["v1"].__setitem__("commit", "0" * 40),
        )

    def test_removal_probe_mutation_fails_closed(self) -> None:
        self.assert_mutation_fails(
            "docker/removal-probes.json",
            lambda value: value["frontend_v1"].__setitem__("exit_code", 0),
        )

    def test_network_topology_mutation_fails_closed(self) -> None:
        def mutate(value) -> None:
            frontend = next(
                member
                for member in value["members"]["frontdoor"]
                if "frontend" in member.lower()
            )
            value["members"]["control"].append(frontend)

        self.assert_mutation_fails("docker/network-proof.json", mutate)

    def test_raw_retry_rows_mutation_fails_closed(self) -> None:
        def mutate(value) -> None:
            value["count"] = 1
            del value["facts"][1]

        self.assert_mutation_fails("baselines/raw-retry/mongo.json", mutate)

    def test_official_service_graph_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "docker/official-services.txt"
            services = path.read_text(encoding="utf-8").splitlines()
            services.remove("reservation")
            path.write_text("\n".join(services) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "official service"):
                check_evidence(evidence)

    def test_condition_body_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.copy_evidence(temporary)
            path = evidence / "baselines/raw-retry/request-body.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(EvidenceError, "bodies"):
                check_evidence(evidence)

    def test_final_rule_allow_mutation_fails_closed(self) -> None:
        self.assert_mutation_fails(
            "state/final-state.json",
            lambda value: value["rule"].__setitem__("allow", ["reserve-v2"]),
        )


if __name__ == "__main__":
    unittest.main()
