from __future__ import annotations

import re
from time import monotonic, sleep

from config import settings
from services.http_client import post_json


class ProviderNotConfigured(RuntimeError):
    pass


def is_image_provider_configured():
    return bool(settings.image_api_base and settings.image_api_key and settings.image_model)


def _url(path):
    return settings.image_api_base.rstrip("/") + "/" + path.lstrip("/")


def _headers():
    key_value = settings.image_api_key_prefix + settings.image_api_key
    return {
        settings.image_api_key_header: key_value,
        "Content-Type": "application/json",
    }


def _normalize_reference_images(images):
    if isinstance(images, str):
        return [images] if images else []
    return [url for url in (images or []) if url]


def _reference_debug(reference_images):
    return {
        "reference_count": len(reference_images),
        "reference_types": [
            "data_url" if str(url).startswith("data:") else "http_url" if str(url).startswith(("http://", "https://")) else "other"
            for url in reference_images
        ],
    }


def _build_image_payload(prompt, aspect_ratio="auto", images=None, extra=None):
    reference_images = _normalize_reference_images(images)
    aspect_ratio = aspect_ratio or "auto"

    if "/v1/images/generations" in settings.image_create_path:
        payload = {
            "model": settings.image_model,
            "prompt": prompt,
            "size": aspect_ratio,
            "response_format": "url",
        }
        if reference_images:
            payload["image"] = reference_images
    elif "/v1/api/generate" in settings.image_create_path:
        payload = {
            "model": settings.image_model,
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "replyType": "json",
        }
        if reference_images:
            payload["images"] = reference_images
    else:
        payload = {
            "model": settings.image_model,
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "shutProgress": False,
        }
        if reference_images:
            # The legacy GPT Image page uses `urls` for reference images.
            payload["urls"] = reference_images

    if extra:
        payload.update(extra)
    return payload


def build_image_request_debug(prompt, size="auto", images=None, extra=None, aspect_ratio=None):
    reference_images = _normalize_reference_images(images)
    payload = _build_image_payload(prompt, aspect_ratio=aspect_ratio or size or "auto", images=images, extra=extra)
    redacted = {
        key: ("[reference images omitted]" if key in {"urls", "images", "image"} else value)
        for key, value in payload.items()
    }
    return {
        "endpoint": _url(settings.image_create_path),
        "payload": redacted,
        **_reference_debug(reference_images),
    }


def create_image_task(prompt, size="auto", images=None, extra=None, aspect_ratio=None):
    """Submit a Grsai GPT Image generation request.

    The current Grsai page shows:
    - Host: https://grsai.dakka.com.cn
    - Create: POST /v1/draw/completions
    - Result: POST /v1/draw/result

    The exact provider response is preserved in `raw` so we can adapt fields
    after you confirm the final API docs/key format.
    """

    if not is_image_provider_configured():
        raise ProviderNotConfigured("Image provider is not configured")

    payload = _build_image_payload(prompt, aspect_ratio=aspect_ratio or size or "auto", images=images, extra=extra)
    request_debug = build_image_request_debug(prompt, size=size, images=images, extra=extra, aspect_ratio=aspect_ratio)

    data = post_json(
        _url(settings.image_create_path),
        payload,
        _headers(),
        timeout=300,
        ssl_verify=settings.image_ssl_verify,
    )
    result = normalize_image_response(data)
    result["request_debug"] = request_debug
    return result


def get_image_result(task_id, extra=None):
    if not is_image_provider_configured():
        raise ProviderNotConfigured("Image provider is not configured")

    payload = {"id": task_id}
    if extra:
        payload.update(extra)

    data = post_json(
        _url(settings.image_result_path),
        payload,
        _headers(),
        timeout=300,
        ssl_verify=settings.image_ssl_verify,
    )
    return normalize_image_response(data)


def wait_for_image_result(initial_result, poll_interval=4, max_wait=180):
    """Poll Grsai result API until a generated image URL is available."""

    result = dict(initial_result or {})
    if result.get("url"):
        return result

    task_id = result.get("task_id")
    if not task_id:
        return result

    deadline = monotonic() + max_wait
    last_error = ""
    while monotonic() < deadline:
        sleep(poll_interval)
        try:
            latest = get_image_result(task_id)
        except Exception as exc:
            last_error = str(exc)
            result["last_poll_error"] = last_error
            continue
        latest["task_id"] = latest.get("task_id") or task_id
        result = {**result, **latest}
        if result.get("url"):
            return result
        status = (result.get("status") or "").lower()
        if status in {"failed", "error", "canceled", "cancelled"}:
            return result

    if not result.get("url") and (result.get("status") or "").lower() not in {"failed", "error", "canceled", "cancelled"}:
        result["status"] = "timeout"
        if last_error:
            result["last_poll_error"] = last_error
    return result


def _first_url_from_list(items):
    if isinstance(items, dict):
        return items.get("url") or items.get("image_url") or items.get("output_url")
    for item in items or []:
        if isinstance(item, str) and item:
            return item
        if isinstance(item, dict):
            url = item.get("url") or item.get("image_url") or item.get("output_url")
            if url:
                return url
    return None


def _first_image_url_from_text(text):
    if not text:
        return None
    match = re.search(r"https?://[^\s\"'<>]+?\.(?:png|jpe?g|webp|gif)(?:\?[^\s\"'<>]*)?", str(text), re.IGNORECASE)
    return match.group(0) if match else None


def _flatten_response_candidates(data):
    candidates = [data]
    if isinstance(data, dict):
        for key in ("data", "result", "results", "output", "response"):
            value = data.get(key)
            if value is not None:
                candidates.append(value)
        for event in data.get("_events") or []:
            candidates.extend(_flatten_response_candidates(event))
    elif isinstance(data, list):
        for item in data:
            candidates.extend(_flatten_response_candidates(item))
    return candidates


def normalize_image_response(data):
    """Keep raw response and extract common task/url fields when present."""

    task_id = None
    url = None
    status = None

    for candidate in _flatten_response_candidates(data):
        if isinstance(candidate, dict):
            task_id = task_id or candidate.get("task_id") or candidate.get("taskId") or candidate.get("id") or candidate.get("request_id")
            status = status or candidate.get("status") or candidate.get("state") or candidate.get("result_type")
            url = url or candidate.get("url") or candidate.get("image_url") or candidate.get("output_url")
            url = url or _first_url_from_list(candidate.get("results") or candidate.get("result") or candidate.get("data"))
            url = url or _first_image_url_from_text(candidate.get("_raw_text"))
        elif isinstance(candidate, list):
            url = url or _first_url_from_list(candidate)
        elif isinstance(candidate, str):
            url = url or _first_image_url_from_text(candidate)
        if url and task_id and status:
            break

    return {
        "task_id": task_id,
        "url": url,
        "status": status,
        "raw": data,
    }
