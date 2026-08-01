"""Authenticated, idempotent SQLite sink used by the runtime litmus tests.

The sink is deliberately a different durability domain from the authority
controller.  Its only mutating operation is ``attempt``.  Calls are
authenticated, a stable idempotency key names one aggregate outcome, and both
positive receipts and linearizable absence observations are HMAC signed.

This is a local test sink, not a claim that HMAC makes an untrusted remote
service truthful.  It models the explicit queryable/idempotent sink premise in
the paper and gives the controller evidence it can authenticate after a crash.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


class SinkError(RuntimeError):
    """Base class for sink protocol failures."""


class AuthenticationError(SinkError):
    """Raised when a request or evidence MAC is invalid."""


class StableKeyConflict(SinkError):
    """Raised when a stable key is reused for different logical work."""


def canonical_json(value: Any) -> str:
    """Serialize the small JSON protocol deterministically."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _mac(secret: bytes, domain: str, value: Mapping[str, Any]) -> str:
    if not isinstance(secret, bytes) or not secret:
        raise ValueError("the sink HMAC secret must be nonempty bytes")
    material = domain.encode("utf-8") + b"\x00" + canonical_json(value).encode("utf-8")
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def request_auth(secret: bytes, method: str, payload: Mapping[str, Any]) -> str:
    """Create a request MAC for one exact sink method and payload."""

    if method not in {"attempt", "query"}:
        raise ValueError(f"unknown sink method: {method}")
    return _mac(secret, f"authority-sink/request/{method}/v1", payload)


def sign_evidence(secret: bytes, body: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached-HMAC evidence envelope."""

    canonical_body = dict(body)
    return {
        "body": canonical_body,
        "signature": _mac(secret, "authority-sink/evidence/v1", canonical_body),
    }


def verify_evidence(secret: bytes, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Authenticate an evidence envelope and return a copy of its body."""

    body = evidence.get("body")
    signature = evidence.get("signature")
    if not isinstance(body, Mapping) or not isinstance(signature, str):
        raise AuthenticationError("malformed sink evidence")
    expected = _mac(secret, "authority-sink/evidence/v1", body)
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationError("invalid sink evidence signature")
    return dict(body)


class AuthenticatedSink:
    """A synchronous, durable, idempotent test sink.

    ``stable_key`` is the physical idempotency key.  ``effect_id`` is the
    controller's stable logical operation name.  Both mappings are injective:
    neither name can be silently rebound to another request.
    """

    def __init__(self, path: os.PathLike[str] | str, secret: bytes) -> None:
        self.path = str(Path(path).resolve())
        self._secret = secret
        if not isinstance(secret, bytes) or not secret:
            raise ValueError("the sink HMAC secret must be nonempty bytes")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA wal_autocheckpoint = 1")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                revision INTEGER NOT NULL CHECK (revision >= 0)
            );
            INSERT OR IGNORE INTO metadata(singleton, revision) VALUES (1, 0);

            CREATE TABLE IF NOT EXISTS outcomes (
                stable_key TEXT PRIMARY KEY,
                effect_id TEXT NOT NULL UNIQUE,
                request_hash TEXT NOT NULL,
                outcome_json TEXT NOT NULL,
                revision INTEGER NOT NULL UNIQUE,
                evidence_json TEXT NOT NULL,
                evidence_signature TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attempts (
                attempt_no INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_key TEXT NOT NULL,
                effect_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                reused INTEGER NOT NULL CHECK (reused IN (0, 1)),
                observed_revision INTEGER NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS outcomes_no_update
            BEFORE UPDATE ON outcomes BEGIN
                SELECT RAISE(ABORT, 'sink outcomes are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS outcomes_no_delete
            BEFORE DELETE ON outcomes BEGIN
                SELECT RAISE(ABORT, 'sink outcomes are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS attempts_no_update
            BEFORE UPDATE ON attempts BEGIN
                SELECT RAISE(ABORT, 'sink attempts are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS attempts_no_delete
            BEFORE DELETE ON attempts BEGIN
                SELECT RAISE(ABORT, 'sink attempts are append-only');
            END;
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "AuthenticatedSink":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    @staticmethod
    def attempt_payload(
        effect_id: str,
        stable_key: str,
        request_hash: str,
        outcome: Any,
    ) -> dict[str, Any]:
        return {
            "effect_id": effect_id,
            "stable_key": stable_key,
            "request_hash": request_hash,
            "outcome": outcome,
        }

    @staticmethod
    def query_payload(stable_key: str) -> dict[str, str]:
        return {"stable_key": stable_key}

    def authorize_attempt(
        self,
        effect_id: str,
        stable_key: str,
        request_hash: str,
        outcome: Any,
    ) -> str:
        return request_auth(
            self._secret,
            "attempt",
            self.attempt_payload(effect_id, stable_key, request_hash, outcome),
        )

    def authorize_query(self, stable_key: str) -> str:
        return request_auth(self._secret, "query", self.query_payload(stable_key))

    def _check_request(
        self,
        method: str,
        payload: Mapping[str, Any],
        authorization: str | None,
    ) -> None:
        if not isinstance(authorization, str):
            raise AuthenticationError("missing sink request authentication")
        expected = request_auth(self._secret, method, payload)
        if not hmac.compare_digest(authorization, expected):
            raise AuthenticationError("invalid sink request authentication")

    def attempt(
        self,
        *,
        effect_id: str,
        stable_key: str,
        request_hash: str,
        outcome: Any,
        authorization: str | None,
    ) -> dict[str, Any]:
        """Commit or retrieve the one aggregate outcome for ``stable_key``."""

        if not all(isinstance(value, str) and value for value in (effect_id, stable_key, request_hash)):
            raise ValueError("effect_id, stable_key, and request_hash must be nonempty strings")
        payload = self.attempt_payload(effect_id, stable_key, request_hash, outcome)
        self._check_request("attempt", payload, authorization)
        requested_outcome_json = canonical_json(outcome)

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outcomes WHERE stable_key = ? OR effect_id = ?",
                (stable_key, effect_id),
            ).fetchone()
            if row is not None:
                if (
                    row["stable_key"] != stable_key
                    or row["effect_id"] != effect_id
                    or row["request_hash"] != request_hash
                    or row["outcome_json"] != requested_outcome_json
                ):
                    raise StableKeyConflict(
                        "effect/stable key was already bound to different logical work"
                    )
                revision = int(row["revision"])
                connection.execute(
                    """
                    INSERT INTO attempts(
                        stable_key, effect_id, request_hash, reused, observed_revision
                    ) VALUES (?, ?, ?, 1, ?)
                    """,
                    (stable_key, effect_id, request_hash, revision),
                )
                return {
                    "body": json.loads(row["evidence_json"]),
                    "signature": row["evidence_signature"],
                }

            current = connection.execute(
                "SELECT revision FROM metadata WHERE singleton = 1"
            ).fetchone()
            assert current is not None
            revision = int(current["revision"]) + 1
            body = {
                "kind": "receipt",
                "sink_revision": revision,
                "effect_id": effect_id,
                "stable_key": stable_key,
                "request_hash": request_hash,
                "outcome": outcome,
            }
            evidence = sign_evidence(self._secret, body)
            connection.execute(
                "UPDATE metadata SET revision = ? WHERE singleton = 1",
                (revision,),
            )
            connection.execute(
                """
                INSERT INTO outcomes(
                    stable_key, effect_id, request_hash, outcome_json, revision,
                    evidence_json, evidence_signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_key,
                    effect_id,
                    request_hash,
                    requested_outcome_json,
                    revision,
                    canonical_json(body),
                    evidence["signature"],
                ),
            )
            connection.execute(
                """
                INSERT INTO attempts(
                    stable_key, effect_id, request_hash, reused, observed_revision
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (stable_key, effect_id, request_hash, revision),
            )
            return evidence

    def query(
        self,
        stable_key: str,
        *,
        authorization: str | None,
    ) -> dict[str, Any]:
        """Return signed receipt or signed linearizable absence evidence."""

        if not isinstance(stable_key, str) or not stable_key:
            raise ValueError("stable_key must be a nonempty string")
        self._check_request("query", self.query_payload(stable_key), authorization)
        # BEGIN (rather than an unlocked pair of reads) makes the row/revision
        # observation one SQLite snapshot.  No write is performed.
        self._connection.execute("BEGIN")
        try:
            row = self._connection.execute(
                "SELECT evidence_json, evidence_signature FROM outcomes WHERE stable_key = ?",
                (stable_key,),
            ).fetchone()
            revision_row = self._connection.execute(
                "SELECT revision FROM metadata WHERE singleton = 1"
            ).fetchone()
            assert revision_row is not None
            revision = int(revision_row["revision"])
            if row is not None:
                evidence = {
                    "body": json.loads(row["evidence_json"]),
                    "signature": row["evidence_signature"],
                }
            else:
                evidence = sign_evidence(
                    self._secret,
                    {
                        "kind": "absence",
                        "sink_revision": revision,
                        "stable_key": stable_key,
                    },
                )
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
            return evidence

    def snapshot(self) -> dict[str, Any]:
        """Return deterministic audit data; this is not used for admission."""

        revision_row = self._connection.execute(
            "SELECT revision FROM metadata WHERE singleton = 1"
        ).fetchone()
        assert revision_row is not None
        outcomes = [
            {
                "stable_key": row["stable_key"],
                "effect_id": row["effect_id"],
                "request_hash": row["request_hash"],
                "outcome": json.loads(row["outcome_json"]),
                "revision": int(row["revision"]),
                "evidence": {
                    "body": json.loads(row["evidence_json"]),
                    "signature": row["evidence_signature"],
                },
            }
            for row in self._connection.execute(
                "SELECT * FROM outcomes ORDER BY stable_key"
            )
        ]
        attempts = [
            {
                "attempt_no": int(row["attempt_no"]),
                "stable_key": row["stable_key"],
                "effect_id": row["effect_id"],
                "request_hash": row["request_hash"],
                "reused": bool(row["reused"]),
                "observed_revision": int(row["observed_revision"]),
            }
            for row in self._connection.execute(
                "SELECT * FROM attempts ORDER BY attempt_no"
            )
        ]
        return {
            "revision": int(revision_row["revision"]),
            "outcomes": outcomes,
            "attempts": attempts,
        }


# Short alias used by callers that do not need the authentication adjective.
DurableSink = AuthenticatedSink
