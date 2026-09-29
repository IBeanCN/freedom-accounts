"""Response-side JSON normalization."""

import json
from datetime import datetime

from fastapi.responses import JSONResponse, Response


# SQLite columns use local naive strings; upstream expiry can be RFC3339 or
# epoch-like values. The API contract emits Unix milliseconds for all of them.
TEMPORAL_FIELD_NAMES = {
    "at",
    "t",
    "time",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "expires_at",
    "expiresAt",
    "token_refresh_at",
    "last_run_at",
    "fp_check_at",
    "check_at",
}

# Detail endpoints deliberately keep these fields as JSON strings. Normalize
# their inner timestamps without changing the outer wire contract.
JSON_STRING_FIELDS = {"steps", "result_json", "fingerprint_json"}


def timestamp_millis(value):
    """Convert supported wire values to Unix milliseconds; invalid values pass through."""
    if isinstance(value, bool) or value in (None, ""):
        return value
    if isinstance(value, (int, float)):
        # Epoch seconds stay below 1e11 until 5138; milliseconds are above it.
        return int(value if abs(value) >= 100_000_000_000 else value * 1000)
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value
    if text.lstrip("+-").isdigit():
        number = int(text)
        return int(number if abs(number) >= 100_000_000_000 else number * 1000)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return value
    return int(parsed.timestamp() * 1000)


def normalize_temporal_fields(value):
    """Recursively convert fields whose names carry timestamps in API responses."""
    if isinstance(value, list):
        return [normalize_temporal_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in JSON_STRING_FIELDS and isinstance(item, str):
            try:
                parsed = json.loads(item or "null")
            except json.JSONDecodeError:
                result[key] = item
                continue
            result[key] = json.dumps(
                normalize_temporal_fields(parsed), ensure_ascii=False)
        elif key in TEMPORAL_FIELD_NAMES or key.endswith("_at"):
            result[key] = timestamp_millis(item)
        else:
            result[key] = normalize_temporal_fields(item)
    return result


async def normalize_json_response(response):
    """Replace JSON response bodies after routes, preserving headers and status."""
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.headers.get("content-type"),
        )

    headers = dict(response.headers)
    headers.pop("content-length", None)
    return JSONResponse(
        content=normalize_temporal_fields(data),
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
    )
