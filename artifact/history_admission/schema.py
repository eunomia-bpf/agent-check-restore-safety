"""Strict JSON and canonical-digest helpers shared by both executables.

Only serialization machinery is shared.  The verifier deliberately does not
import the compiler and independently reimplements the semantic algorithms.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any, Iterable, Mapping


REQUEST_SCHEMA = "history-admission.request.v2"
RESULT_SCHEMA = "history-admission.result.v2"
VERIFICATION_SCHEMA = "history-admission.verification.v2"

MAX_ATOMS = 16
MAX_SOURCE_CELLS = 12
MAX_TARGET_CELLS = 12
MAX_CONTROLLERS = 10
MAX_OCCURRENCES = 24
MAX_GATE_USES = 24
MAX_EXPANDED_CONFIGURATIONS = 4096
MAX_PRODUCT_STATES = 200_000
MAX_RAW_LIST_ITEMS = 4096
MAX_STRING_CODEPOINTS = 4096


class SchemaError(ValueError):
    """A fail-closed manifest or certificate parsing error."""


def _reject_float(value: str) -> None:
    raise SchemaError(f"floating-point JSON values are forbidden: {value}")


def _reject_constant(value: str) -> None:
    raise SchemaError(f"non-finite JSON value is forbidden: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _validate_json_tree(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise SchemaError(f"non-NFC string at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_tree(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaError(f"non-string object key at {path}")
            _validate_json_tree(key, f"{path}.<key>")
            _validate_json_tree(item, f"{path}.{key}")
        return
    raise SchemaError(f"unsupported JSON value at {path}: {type(value).__name__}")


def loads_json(text: str) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON: {exc}") from exc
    _validate_json_tree(value)
    return value


def load_json(path: str | Path) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot read {path}: {exc}") from exc
    return loads_json(text)


def canonical_json(value: Any) -> str:
    _validate_json_tree(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_json(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def write_json(path: str | Path, value: Any) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    )
    Path(path).write_text(payload + "\n", encoding="utf-8")


def expect_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{path} must be an object")
    return value


def expect_exact_keys(
    value: Mapping[str, Any],
    required: Iterable[str],
    optional: Iterable[str],
    path: str,
) -> None:
    required_set = set(required)
    optional_set = set(optional)
    actual = set(value)
    missing = sorted(required_set - actual)
    unknown = sorted(actual - required_set - optional_set)
    if missing:
        raise SchemaError(f"{path} is missing fields: {', '.join(missing)}")
    if unknown:
        raise SchemaError(f"{path} has unknown fields: {', '.join(unknown)}")


def expect_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise SchemaError(f"{path} must be a list")
    if len(value) > MAX_RAW_LIST_ITEMS:
        raise SchemaError(f"{path} has more than {MAX_RAW_LIST_ITEMS} items")
    return value


def expect_string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{path} must be a string")
    if not allow_empty and not value:
        raise SchemaError(f"{path} must be nonempty")
    if len(value) > MAX_STRING_CODEPOINTS:
        raise SchemaError(
            f"{path} has more than {MAX_STRING_CODEPOINTS} Unicode code points"
        )
    return value


def expect_optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return expect_string(value, path)


def expect_nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchemaError(f"{path} must be a nonnegative integer")
    return value


def expect_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaError(f"{path} must be a boolean")
    return value


def unique_strings(values: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = expect_list(values, path)
    parsed = tuple(expect_string(item, f"{path}[{index}]") for index, item in enumerate(items))
    if not allow_empty and not parsed:
        raise SchemaError(f"{path} must be nonempty")
    if len(set(parsed)) != len(parsed):
        raise SchemaError(f"{path} contains duplicates")
    return parsed
