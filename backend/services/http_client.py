from __future__ import annotations

import json
import ssl
from time import sleep
from urllib import error, request


_RETRY_TOKENS = (
    "unexpected_eof",
    "eof occurred",
    "eof while reading",
    "connection reset",
    "remote end closed",
    "timed out",
    "timeout",
    "temporarily unavailable",
)


def _parse_response_text(text, status=None, content_type=""):
    stripped = (text or "").strip()
    if not stripped:
        return {"_raw_text": "", "_http_status": status, "_content_type": content_type}

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    events = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue

    if events:
        return {
            "_events": events,
            "data": events[-1],
            "_http_status": status,
            "_content_type": content_type,
        }

    decoder = json.JSONDecoder()
    index = 0
    values = []
    while index < len(stripped):
        while index < len(stripped) and stripped[index].isspace():
            index += 1
        if index >= len(stripped):
            break
        try:
            value, next_index = decoder.raw_decode(stripped, index)
        except json.JSONDecodeError:
            break
        values.append(value)
        index = next_index

    if values:
        return values[-1] if len(values) == 1 else {"_events": values, "data": values[-1]}

    return {
        "_raw_text": stripped[:2000],
        "_http_status": status,
        "_content_type": content_type,
    }


def _is_retryable(exc):
    if isinstance(exc, error.HTTPError):
        return False
    if isinstance(exc, (error.URLError, ssl.SSLError, TimeoutError, ConnectionResetError)):
        return True
    text = str(exc).lower()
    return any(token in text for token in _RETRY_TOKENS)


def _request_headers(headers):
    merged = {
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": "Mozilla/5.0",
    }
    merged.update(headers or {})
    return merged


def post_json(url, payload, headers, timeout=300, ssl_verify=True):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged_headers = _request_headers(headers)
    attempts = [ssl_verify, ssl_verify]
    if ssl_verify:
        attempts.append(False)
    last_exc = None
    for index, verify in enumerate(attempts):
        req = request.Request(url, data=data, headers=merged_headers, method="POST")
        context = None if verify else ssl._create_unverified_context()
        try:
            with request.urlopen(req, timeout=timeout, context=context) as response:
                content_type = response.headers.get("Content-Type", "")
                text = response.read().decode("utf-8", errors="replace")
                return _parse_response_text(text, status=response.status, content_type=content_type)
        except error.HTTPError:
            raise
        except Exception as exc:
            last_exc = exc
            if index >= len(attempts) - 1 or not _is_retryable(exc):
                raise
            sleep(0.35 * (index + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed without response")
