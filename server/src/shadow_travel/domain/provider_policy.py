"""Single boundary for durable user-owned projections; never export live Google responses."""

import hashlib
import json


def persisted_place(payload):
    result = dict(payload)
    if result.get("provider") == "google":
        # Name/city are explicitly user-authored aliases in our reference endpoint.
        result.update(address="", district="", coordinate=None, contentPolicy="reference_only")
        for field in ("attributions", "liveDetails", "routeGeometry", "weather"):
            result.pop(field, None)
    return result


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def pack_digest(payload):
    # Transport integrity only, not a signature or proof of authorization.
    data = {key: payload[key] for key in ("trip", "document", "places", "visits", "run")}
    return hashlib.sha256(
        json.dumps(
            canonical(data), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
