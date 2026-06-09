from __future__ import annotations

import base64
import json
import re
import ssl
from copy import deepcopy
from urllib import error, parse, request

from store import InMemoryStore, make_id, today


def _split_text_list(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if not value:
        return []
    return [x.strip() for x in re.split(r"[,，、\n]", str(value)) if x.strip()]


def _first_value(data, *keys, default=""):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _normalize_variants(data):
    variants = data.get("variants") or []
    normalized = []
    for index, variant in enumerate(variants):
        image_url = _first_value(variant, "image_url", "imageUrl")
        if not image_url:
            continue
        normalized.append(
            {
                "id": variant.get("id") or f"v_{index}",
                "name": variant.get("name") or f"款式 {index + 1}",
                "image_url": image_url,
                "notes": variant.get("notes", ""),
            }
        )
    return normalized


def normalize_product(data):
    variants = _normalize_variants(data)
    selected_variant_id = _first_value(data, "selected_variant_id", "selectedVariantId")
    return {
        "id": data.get("id") or make_id("prod"),
        "name": data.get("name") or "未命名产品",
        "category": data.get("category") or "其他",
        "price": data.get("price") or "",
        "audience": data.get("audience") or "",
        "selling_points": _split_text_list(_first_value(data, "selling_points", "sellingPoints", default=[])),
        "scene": data.get("scene") or "",
        "tone": data.get("tone") or "真实种草",
        "spec": data.get("spec") or "",
        "forbidden_words": _split_text_list(_first_value(data, "forbidden_words", "forbiddenWords", default=[])),
        "product_url": _first_value(data, "product_url", "productUrl"),
        "image_url": _first_value(data, "image_url", "imageUrl"),
        "variants": variants,
        "selected_variant_id": selected_variant_id or (variants[0]["id"] if variants else ""),
        "created_at": data.get("created_at") or data.get("created") or today(),
        "updated_at": today(),
    }


def _safe_filename(filename, fallback="asset"):
    name = (filename or fallback).strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name or fallback


def _extension_for_content_type(content_type):
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type.lower(), ".bin")


def _decode_data_url(data_url, fallback_content_type="application/octet-stream"):
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", data_url, re.S)
    if not match:
        return None
    content_type = match.group(1) or fallback_content_type
    is_base64 = bool(match.group(2))
    payload = match.group(3)
    if is_base64:
        raw = base64.b64decode(payload)
    else:
        raw = parse.unquote_to_bytes(payload)
    return content_type, raw


class SupabaseStore:
    """Supabase-backed repository using REST and Storage APIs.

    The project stays dependency-free: no supabase-py package is required.
    Service role credentials must stay on the backend.
    """

    def __init__(self, settings):
        self.settings = settings
        self.url = settings.supabase_url.rstrip("/")
        self.key = settings.supabase_service_role_key
        self.bucket = settings.supabase_storage_bucket
        self.ssl_verify = settings.supabase_ssl_verify
        if not self.url or not self.key:
            raise RuntimeError("Supabase is selected but XHS_SUPABASE_URL or XHS_SUPABASE_SERVICE_ROLE_KEY is missing")
        if settings.supabase_seed_sample and not self.list_products():
            self.seed()

    def _clone(self, value):
        return deepcopy(value)

    def _context(self):
        return None if self.ssl_verify else ssl._create_unverified_context()

    def _headers(self, content_type="application/json", prefer=""):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _rest_url(self, table, query=None):
        url = f"{self.url}/rest/v1/{table}"
        if query:
            url += "?" + parse.urlencode(query, doseq=True)
        return url

    def _request_json(self, method, table, payload=None, query=None, prefer=""):
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self._rest_url(table, query=query),
            data=data,
            headers=self._headers(prefer=prefer),
            method=method,
        )
        try:
            with request.urlopen(req, timeout=30, context=self._context()) as response:
                text = response.read().decode("utf-8", errors="replace")
                if not text:
                    return None
                return json.loads(text)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase {method} {table} failed: HTTP {exc.code} {body[:500]}") from exc

    def _upsert(self, table, item):
        rows = self._request_json(
            "POST",
            table,
            payload=item,
            query={"on_conflict": "id"},
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self._clone(rows[0] if rows else item)

    def _patch(self, table, row_id, data):
        rows = self._request_json(
            "PATCH",
            table,
            payload=data,
            query={"id": f"eq.{row_id}"},
            prefer="return=representation",
        )
        return self._clone(rows[0]) if rows else None

    def _delete(self, table, row_id):
        rows = self._request_json(
            "DELETE",
            table,
            query={"id": f"eq.{row_id}"},
            prefer="return=representation",
        )
        return self._clone(rows[0]) if rows else None

    def _list(self, table, query=None):
        rows = self._request_json("GET", table, query=query or {})
        return self._clone(rows or [])

    def _get(self, table, row_id):
        rows = self._list(table, {"id": f"eq.{row_id}", "select": "*", "limit": "1"})
        return rows[0] if rows else None

    def _upload_binary(self, path, content_type, data):
        quoted_path = "/".join(parse.quote(part, safe="") for part in path.split("/"))
        url = f"{self.url}/storage/v1/object/{parse.quote(self.bucket, safe='')}/{quoted_path}"
        req = request.Request(
            url,
            data=data,
            headers={**self._headers(content_type=content_type), "x-upsert": "true"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60, context=self._context()) as response:
                response.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase storage upload failed: HTTP {exc.code} {body[:500]}") from exc
        return f"{self.url}/storage/v1/object/public/{parse.quote(self.bucket, safe='')}/{quoted_path}"

    def _store_data_url_if_needed(self, value, folder, filename_hint="asset"):
        decoded = _decode_data_url(value)
        if not decoded:
            return value or ""
        content_type, raw = decoded
        filename = _safe_filename(filename_hint, "asset")
        if "." not in filename:
            filename += _extension_for_content_type(content_type)
        path = f"{folder}/{today()}/{make_id('file')}-{filename}"
        return self._upload_binary(path, content_type, raw)

    def _store_product_images(self, item):
        item["image_url"] = self._store_data_url_if_needed(item.get("image_url", ""), "products", f"{item['id']}-main")
        for variant in item.get("variants", []):
            variant["image_url"] = self._store_data_url_if_needed(
                variant.get("image_url", ""),
                "variants",
                f"{item['id']}-{variant.get('id') or 'variant'}",
            )
        return item

    def seed(self):
        sample = InMemoryStore()
        for product in sample.list_products():
            self.create_product(product)
        for asset in sample.list_assets():
            self.create_asset(asset)
        for note in sample.list_note_packages():
            self.create_note_package(note)

    def status(self):
        self._list("products", {"select": "id", "limit": "1"})
        return {
            "backend": "supabase",
            "configured": True,
            "url": self.url,
            "bucket": self.bucket,
        }

    def create_product(self, data):
        item = self._store_product_images(normalize_product(data))
        return self._upsert("products", item)

    def update_product(self, product_id, data):
        current = self.get_product(product_id)
        if not current:
            return None
        merged = {**current, **data, "id": product_id}
        item = self._store_product_images(normalize_product(merged))
        return self._upsert("products", item)

    def get_product(self, product_id):
        return self._get("products", product_id)

    def list_products(self):
        return self._list("products", {"select": "*", "order": "updated_at.desc"})

    def create_asset(self, data):
        product = self.get_product(data.get("product_id", "")) if data.get("product_id") else None
        item = {
            "id": data.get("id") or make_id("asset"),
            "product_id": data.get("product_id", ""),
            "product_name": product["name"] if product else data.get("product_name", ""),
            "type": data.get("type", "copy"),
            "title": data.get("title", ""),
            "status": data.get("status", "review"),
            "style": data.get("style", ""),
            "content": data.get("content", ""),
            "url": self._store_data_url_if_needed(data.get("url", ""), "assets", data.get("title") or "asset"),
            "provider_task": data.get("provider_task", {}),
            "provider_status": data.get("provider_status", ""),
            "variant_id": data.get("variant_id", ""),
            "variant_name": data.get("variant_name", ""),
            "source_image_url": data.get("source_image_url", ""),
            "generation_plan": data.get("generation_plan", {}),
            "created_at": data.get("created_at", today()),
        }
        return self._upsert("assets", item)

    def list_assets(self, product_id=None, asset_type=None, status=None):
        query = {"select": "*", "order": "created_at.desc"}
        if product_id:
            query["product_id"] = f"eq.{product_id}"
        if asset_type:
            query["type"] = f"eq.{asset_type}"
        if status:
            query["status"] = f"eq.{status}"
        return self._list("assets", query)

    def update_asset_status(self, asset_id, status):
        return self.update_asset(asset_id, {"status": status})

    def update_asset(self, asset_id, data):
        allowed = {
            "title",
            "status",
            "style",
            "content",
            "url",
            "provider_task",
            "provider_status",
            "variant_id",
            "variant_name",
            "source_image_url",
            "generation_plan",
        }
        patch = {key: value for key, value in data.items() if key in allowed}
        if "url" in patch:
            patch["url"] = self._store_data_url_if_needed(patch["url"], "assets", asset_id)
        return self._patch("assets", asset_id, patch)

    def delete_asset(self, asset_id):
        item = self._delete("assets", asset_id)
        if not item:
            return None
        for note in self.list_note_packages():
            patch = {}
            if note.get("copy_asset_id") == asset_id:
                patch["copy_asset_id"] = ""
            if note.get("cover_asset_id") == asset_id:
                patch["cover_asset_id"] = ""
            if note.get("video_asset_id") == asset_id:
                patch["video_asset_id"] = ""
            detail_ids = [x for x in note.get("detail_asset_ids", []) if x != asset_id]
            if detail_ids != note.get("detail_asset_ids", []):
                patch["detail_asset_ids"] = detail_ids
            if patch:
                self._patch("note_packages", note["id"], patch)
        return item

    def create_note_package(self, data):
        product = self.get_product(data.get("product_id", "")) if data.get("product_id") else None
        item = {
            "id": data.get("id") or make_id("note"),
            "product_id": data.get("product_id", ""),
            "product_name": product["name"] if product else data.get("product_name", ""),
            "title": data.get("title", ""),
            "angle": data.get("angle", ""),
            "persona": data.get("persona", ""),
            "status": data.get("status", "review"),
            "score": data.get("score", 80),
            "copy_asset_id": data.get("copy_asset_id", ""),
            "cover_asset_id": data.get("cover_asset_id", ""),
            "detail_asset_ids": data.get("detail_asset_ids", []),
            "video_asset_id": data.get("video_asset_id", ""),
            "summary": data.get("summary", ""),
            "hashtags": data.get("hashtags", []),
            "publish_plan": data.get("publish_plan", "待排期"),
            "goal": data.get("goal", "引流成交"),
            "created_at": data.get("created_at", today()),
        }
        return self._upsert("note_packages", item)

    def list_note_packages(self, product_id=None, status=None):
        query = {"select": "*", "order": "created_at.desc"}
        if product_id:
            query["product_id"] = f"eq.{product_id}"
        if status:
            query["status"] = f"eq.{status}"
        return self._list("note_packages", query)

    def update_note_status(self, note_id, status):
        patch = {"status": status}
        if status == "published":
            patch["publish_plan"] = "已发布"
        return self._patch("note_packages", note_id, patch)

    def create_job(self, data):
        item = {
            "id": data.get("id") or make_id("job"),
            "product_id": data.get("product_id", ""),
            "product_name": data.get("product_name", ""),
            "type": data.get("type", "note_package"),
            "title": data.get("title", "生成任务"),
            "status": data.get("status", "running"),
            "progress": data.get("progress", 0),
            "detail": data.get("detail", "任务已创建"),
            "config": data.get("config", {}),
            "created_at": data.get("created_at", today()),
            "result": data.get("result", {}),
        }
        return self._upsert("generation_jobs", item)

    def update_job(self, job_id, **data):
        return self._patch("generation_jobs", job_id, data)

    def get_job(self, job_id):
        return self._get("generation_jobs", job_id)

    def list_jobs(self, status=None):
        query = {"select": "*", "order": "created_at.desc"}
        if status:
            query["status"] = f"eq.{status}"
        return self._list("generation_jobs", query)

    def create_upload(self, data):
        upload_id = make_id("upload")
        filename = data.get("filename") or f"{upload_id}.bin"
        content_type = data.get("content_type") or "application/octet-stream"
        url = data.get("url") or ""
        if data.get("data_url"):
            decoded = _decode_data_url(data["data_url"], content_type)
            if decoded:
                content_type, raw = decoded
                safe_name = _safe_filename(filename, f"{upload_id}{_extension_for_content_type(content_type)}")
                url = self._upload_binary(f"uploads/{today()}/{upload_id}-{safe_name}", content_type, raw)
            else:
                url = data["data_url"]
        item = {
            "id": upload_id,
            "filename": filename,
            "content_type": content_type,
            "url": url,
            "created_at": today(),
        }
        return self._upsert("uploads", item)
