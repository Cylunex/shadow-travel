from __future__ import annotations

import base64
import binascii
import json
from typing import Any


def encode_cursor(kind: str, **values: str) -> str:
    payload = {"v": 1, "kind": kind, "values": values}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, kind: str) -> dict[str, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload: Any = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != kind
            or not isinstance(payload.get("values"), dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in payload["values"].items()
            )
        ):
            raise ValueError
        return payload["values"]
    except (
        ValueError,
        TypeError,
        binascii.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise ValueError("invalid cursor") from exc
