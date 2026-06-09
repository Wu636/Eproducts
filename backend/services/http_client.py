from __future__ import annotations

import json
import ssl
from urllib import request


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


def post_json(url, payload, headers, timeout=300, ssl_verify=True):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    context = None
    if not ssl_verify:
        context = ssl._create_unverified_context()
    with request.urlopen(req, timeout=timeout, context=context) as response:
        content_type = response.headers.get("Content-Type", "")
        text = response.read().decode("utf-8", errors="replace")
        return _parse_response_text(text, status=response.status, content_type=content_type)
