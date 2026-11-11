from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import ssl
import sys
import zipfile
from io import BytesIO
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import URLError
from urllib import request
from urllib.parse import parse_qs, quote, unquote_to_bytes, urlparse

sys.path.append(str(Path(__file__).resolve().parent))
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

from config import settings
from services.home_layout import (
    HOME_LAYOUT_ACCOUNT_ID,
    HOME_LAYOUT_ACCOUNT_NAME,
    ensure_home_layout_account,
    generate_home_layout_copy,
    generate_home_layout_plans,
    run_home_layout_image_job,
)
from services.role_wallpaper import (
    ROLE_WALLPAPER_ACCOUNT_ID,
    ROLE_WALLPAPER_ACCOUNT_NAME,
    analyze_role_wallpaper_reference,
    apply_role_wallpaper_reference_style_to_roles,
    delete_role_wallpaper_asset,
    ensure_role_wallpaper_account,
    expand_role_wallpaper_reference_plans,
    generate_role_wallpaper_plans,
    get_reference_file,
    list_reference_images,
    list_role_profiles,
    list_role_wallpaper_assets,
    list_wallpaper_templates,
    run_role_wallpaper_image_job,
)
from services.animate_anyone import (
    AnimateAnyoneError,
    create_workflow as create_dance_workflow,
    detect_person_image,
    get_provider_task as get_dance_provider_task,
    get_workflow as get_dance_workflow,
    list_workflows as list_dance_workflows,
    submit_action_template,
    submit_dance_video,
    submit_wan_motion_video,
)
from services.commerce_learning import (
    analyze_commerce_opportunities,
    build_learning_cycle,
    clipforge_status,
    format_cycle_report,
    format_learning_report,
    format_market_report,
    format_video_workflow,
    analyze_market_opportunities,
    generate_video_workflows,
    normalize_market_samples,
    push_workflow_to_clipforge,
)
from services.image_provider import build_image_request_debug, create_image_task, get_image_result
from services.mock_generation import run_generation_job
from services.plan_provider import generate_image_plans
from services.text_provider import generate_copywriting
from store import InMemoryStore, today
from supabase_store import SupabaseStore


_TRANSIENT_STORAGE_ERROR_TOKENS = (
    "ssl",
    "tls",
    "unexpected_eof",
    "eof occurred",
    "eof while reading",
    "urlopen error",
    "connection reset",
    "remote end closed",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "network is unreachable",
    "nodename nor servname",
)


def _is_transient_storage_error(exc):
    if isinstance(exc, (URLError, ssl.SSLError, TimeoutError, ConnectionResetError)):
        return True
    reason = getattr(exc, "reason", None)
    if reason is not None and reason is not exc and _is_transient_storage_error(reason):
        return True
    text = str(exc).lower()
    return any(token in text for token in _TRANSIENT_STORAGE_ERROR_TOKENS)


def create_store():
    if settings.storage_backend == "supabase":
        return SupabaseStore(settings)
    return InMemoryStore()


main_local_store = InMemoryStore()
main_storage_mode = ""
main_storage_warning = ""
try:
    store = create_store()
except Exception as exc:
    if settings.storage_backend != "supabase" or not _is_transient_storage_error(exc):
        raise
    store = main_local_store
    main_storage_mode = "local_fallback"
    main_storage_warning = str(exc)
home_layout_local_store = InMemoryStore()
home_layout_storage_mode = ""
role_wallpaper_local_store = InMemoryStore()
role_wallpaper_storage_mode = ""


def activate_main_store_fallback(exc):
    global main_storage_mode, main_storage_warning
    if settings.storage_backend != "supabase" or not _is_transient_storage_error(exc):
        return False
    main_storage_mode = "local_fallback"
    main_storage_warning = str(exc)
    return True


def get_main_store():
    if settings.storage_backend != "supabase":
        return store, "memory"
    if main_storage_mode == "local_fallback":
        return main_local_store, main_storage_mode
    return store, "supabase"


def _with_storage_meta(payload, storage_mode):
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    result.setdefault("storage", storage_mode)
    if storage_mode == "local_fallback" and main_storage_warning:
        result.setdefault("warning", f"Supabase 暂时不可用，已切换到本地暂存：{main_storage_warning}")
    return result


def get_home_layout_store():
    """Return a usable store for the independent home-layout workflow.

    Planning and image generation should not be unavailable simply because the
    optional Supabase connection is having a transient TLS/network failure.
    The fallback is deliberately limited to this workflow so the rest of the
    application keeps its configured persistence behaviour.
    """

    global home_layout_storage_mode
    if settings.storage_backend != "supabase":
        ensure_home_layout_account(store)
        return store, "memory"

    if home_layout_storage_mode == "local_fallback":
        ensure_home_layout_account(home_layout_local_store)
        return home_layout_local_store, home_layout_storage_mode

    try:
        ensure_home_layout_account(store)
        return store, "supabase"
    except Exception as exc:
        if not _is_transient_storage_error(exc):
            raise
        home_layout_storage_mode = "local_fallback"
        ensure_home_layout_account(home_layout_local_store)
        return home_layout_local_store, home_layout_storage_mode


def get_role_wallpaper_store():
    """Return a usable store for the role-wallpaper workflow.

    The role catalog and local reference library should stay usable even when
    optional Supabase persistence has a transient TLS/network failure.
    """

    global role_wallpaper_storage_mode
    if settings.storage_backend != "supabase":
        ensure_role_wallpaper_account(store)
        return store, "memory"

    if role_wallpaper_storage_mode == "local_fallback":
        ensure_role_wallpaper_account(role_wallpaper_local_store)
        return role_wallpaper_local_store, role_wallpaper_storage_mode

    try:
        ensure_role_wallpaper_account(store)
        return store, "supabase"
    except Exception as exc:
        if not _is_transient_storage_error(exc):
            raise
        role_wallpaper_storage_mode = "local_fallback"
        ensure_role_wallpaper_account(role_wallpaper_local_store)
        return role_wallpaper_local_store, role_wallpaper_storage_mode


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "XHSAssetAPI/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            if method == "GET" and self._maybe_send_asset_archive(path, query):
                return
            if method == "GET" and self._maybe_send_asset_download(path, query):
                return
            if method == "GET" and self._maybe_send_role_reference_file(path):
                return
            body = self._read_body() if method in {"POST", "PATCH", "DELETE"} else {}
            result = self._route(method, path, query, body)
            self._send_json(result)
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # Keep prototype API debuggable.
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _route(self, method, path, query, body):
        parts = [x for x in path.split("/") if x]
        if not parts or parts[0] != "api":
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

        resource = parts[1] if len(parts) > 1 else ""

        if method == "GET" and path == "/api/health":
            return {"status": "ok", "version": "0.1.0"}

        if method == "GET" and path == "/api/provider-status":
            return {"providers": settings.provider_status()}

        if method == "GET" and path == "/api/database-status":
            return self._database_status()

        if resource == "providers":
            return self._providers(method, parts, body)

        if resource == "products":
            return self._products(method, parts, body)

        if resource == "uploads":
            return self._uploads(method, body)

        if resource == "assets":
            return self._assets(method, parts, query, body)

        if resource == "note-packages":
            return self._note_packages(method, parts, query, body)

        if resource == "home-layout":
            return self._home_layout(method, parts, query, body)

        if resource == "role-wallpaper":
            return self._role_wallpaper(method, parts, query, body)

        if resource == "dance":
            return self._dance(method, parts, query, body)

        if resource == "commerce-learning":
            return self._commerce_learning(method, parts, query, body)

        if resource == "generation":
            if len(parts) >= 3 and parts[2] == "image-plans":
                return self._image_plans(method, parts, body)
            if len(parts) >= 3 and parts[2] == "jobs":
                return self._jobs(method, parts, query, body)

        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def _with_main_store(self, action):
        app_store, storage_mode = get_main_store()
        try:
            return _with_storage_meta(action(app_store), storage_mode)
        except Exception as exc:
            if not activate_main_store_fallback(exc):
                raise
            app_store, storage_mode = get_main_store()
            return _with_storage_meta(action(app_store), storage_mode)

    def _database_status(self):
        app_store, storage_mode = get_main_store()
        try:
            status = app_store.status()
        except Exception as exc:
            if not activate_main_store_fallback(exc):
                raise
            app_store, storage_mode = get_main_store()
            status = app_store.status()
        if storage_mode == "local_fallback":
            status = {
                **status,
                "backend": "local_fallback",
                "configured": False,
                "fallback_from": "supabase",
                "warning": main_storage_warning,
            }
        return {"database": status, "storage": storage_mode}

    def _providers(self, method, parts, body):
        if len(parts) == 4 and parts[1:] == ["providers", "vision", "model"]:
            if method == "GET":
                return {
                    "model": settings.text_vision_model,
                    "models": settings.vision_model_list(),
                    "provider": settings.text_provider,
                }
            if method == "POST":
                try:
                    model = settings.set_vision_model(body.get("model"))
                except ValueError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
                return {"model": model, "models": settings.vision_model_list()}
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        if len(parts) == 4 and parts[1:] == ["providers", "image", "model"]:
            if method == "GET":
                return {
                    "model": settings.image_model,
                    "models": settings.image_model_list(),
                    "provider": settings.image_provider,
                    "profile": settings.image_model_profile(),
                }
            if method == "POST":
                try:
                    model = settings.set_image_model(body.get("model"))
                except ValueError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
                return {
                    "model": model,
                    "models": settings.image_model_list(),
                    "provider": settings.image_provider,
                    "profile": settings.image_model_profile(model),
                }
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        if len(parts) == 4 and parts[1:] == ["providers", "text", "model"]:
            if method == "GET":
                return {
                    "model": settings.text_model,
                    "models": settings.text_model_list(),
                    "provider": settings.text_provider,
                }
            if method == "POST":
                try:
                    model = settings.set_text_model(body.get("model"))
                except ValueError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
                return {"model": model}
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        if method == "POST" and len(parts) == 4 and parts[1:] == ["providers", "text", "test"]:
            product = body.get("product") or {
                "name": "测试产品",
                "category": "家居日用",
                "price": "券后 99 元",
                "audience": "通勤上班族",
                "selling_points": ["高颜值", "使用方便", "性价比友好"],
                "scene": "办公室、宿舍",
                "spec": "",
                "forbidden_words": [],
            }
            content = generate_copywriting(
                product,
                body.get("angle", "生活化种草"),
                body.get("persona", "真实自用"),
                goal=body.get("goal", "引流成交"),
            )
            return {"content": content}

        if method == "POST" and len(parts) == 4 and parts[1:] == ["providers", "image", "create"]:
            prompt = body.get("prompt")
            if not prompt:
                raise ApiError(HTTPStatus.BAD_REQUEST, "prompt is required")
            references = body.get("urls") or body.get("images")
            aspect_ratio = body.get("aspectRatio") or body.get("aspect_ratio") or body.get("size") or "auto"
            return create_image_task(
                prompt=prompt,
                size=body.get("size", "auto"),
                aspect_ratio=aspect_ratio,
                images=references,
                model=body.get("model") or body.get("image_model") or body.get("imageModel"),
                extra=body.get("extra"),
            )

        if method == "POST" and len(parts) == 4 and parts[1:] == ["providers", "image", "payload-preview"]:
            prompt = body.get("prompt") or "测试提示词"
            references = body.get("urls") or body.get("images")
            aspect_ratio = body.get("aspectRatio") or body.get("aspect_ratio") or body.get("size") or "auto"
            return build_image_request_debug(
                prompt=prompt,
                size=body.get("size", "auto"),
                aspect_ratio=aspect_ratio,
                images=references,
                model=body.get("model") or body.get("image_model") or body.get("imageModel"),
                extra=body.get("extra"),
            )

        if method == "POST" and len(parts) == 4 and parts[1:] == ["providers", "image", "result"]:
            task_id = body.get("task_id") or body.get("id")
            if not task_id:
                raise ApiError(HTTPStatus.BAD_REQUEST, "task_id or id is required")
            return get_image_result(task_id=task_id, extra=body.get("extra"))

        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def _products(self, method, parts, body):
        def action(app_store):
            if method == "GET" and len(parts) == 2:
                return {"items": app_store.list_products()}
            if method == "POST" and len(parts) == 2:
                if not body.get("name"):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "name is required")
                return {"item": app_store.create_product(body)}
            if len(parts) == 3:
                product_id = parts[2]
                if method == "GET":
                    item = app_store.get_product(product_id)
                    if not item:
                        raise ApiError(HTTPStatus.NOT_FOUND, "Product not found")
                    return {"item": item}
                if method == "PATCH":
                    item = app_store.update_product(product_id, body)
                    if not item:
                        raise ApiError(HTTPStatus.NOT_FOUND, "Product not found")
                    return {"item": item}
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        return self._with_main_store(action)

    def _uploads(self, method, body):
        if method != "POST":
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
        return self._with_main_store(lambda app_store: {"item": app_store.create_upload(body)})

    def _assets(self, method, parts, query, body):
        def action(app_store):
            if method == "GET" and len(parts) == 2:
                return {
                    "items": app_store.list_assets(
                        product_id=query.get("product_id"),
                        asset_type=query.get("type"),
                        status=query.get("status"),
                    )
                }
            if method == "POST" and len(parts) == 2:
                return {"item": app_store.create_asset(body)}
            if method == "PATCH" and len(parts) == 3:
                item = app_store.update_asset(parts[2], body)
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
                return {"item": item}
            if method == "PATCH" and len(parts) == 4 and parts[3] == "status":
                item = app_store.update_asset_status(parts[2], body.get("status", "review"))
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
                return {"item": item}
            if method == "DELETE" and len(parts) == 3:
                item = app_store.delete_asset(parts[2])
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
                return {"item": item}
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        return self._with_main_store(action)

    def _note_packages(self, method, parts, query, body):
        def action(app_store):
            if method == "GET" and len(parts) == 2:
                return {
                    "items": app_store.list_note_packages(
                        product_id=query.get("product_id"),
                        status=query.get("status"),
                    )
                }
            if method == "POST" and len(parts) == 2:
                return {"item": app_store.create_note_package(body)}
            if method == "PATCH" and len(parts) == 4 and parts[3] == "status":
                item = app_store.update_note_status(parts[2], body.get("status", "review"))
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Note package not found")
                return {"item": item}
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        return self._with_main_store(action)

    def _image_plans(self, method, parts, body):
        if method != "POST" or len(parts) != 3:
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
        product_id = body.get("product_id")

        def action(app_store):
            product = app_store.get_product(product_id)
            if not product:
                raise ApiError(HTTPStatus.BAD_REQUEST, "product_id is invalid")
            config = body.get("config") or {}
            return generate_image_plans(product, config)

        return self._with_main_store(action)

    def _home_layout(self, method, parts, query, body):
        if method == "POST" and len(parts) == 3 and parts[2] == "plans":
            # Planning is text-only and does not need the asset database.  Keeping
            # it independent lets users still draft prompts when cloud storage is
            # temporarily unavailable.
            return generate_home_layout_plans(body or {})

        if method == "GET" and len(parts) == 3 and parts[2] == "assets":
            home_layout_store, storage_mode = get_home_layout_store()
            items = home_layout_store.list_assets(product_id=HOME_LAYOUT_ACCOUNT_ID)
            return {
                "items": [
                    item
                    for item in items
                    if (item.get("generation_plan") or {}).get("kind") in {"home_layout", "home_layout_copy"}
                ],
                "storage": storage_mode,
            }

        if method == "DELETE" and len(parts) == 4 and parts[2] == "assets":
            home_layout_store, storage_mode = get_home_layout_store()
            asset_id = parts[3]
            asset = next((item for item in home_layout_store.list_assets(product_id=HOME_LAYOUT_ACCOUNT_ID) if item.get("id") == asset_id), None)
            if not asset or (asset.get("generation_plan") or {}).get("kind") not in {"home_layout", "home_layout_copy"}:
                raise ApiError(HTTPStatus.NOT_FOUND, "Home layout asset not found")
            return {"item": home_layout_store.delete_asset(asset_id), "storage": storage_mode}

        if method == "POST" and len(parts) == 3 and parts[2] == "images":
            plans = body.get("plans") or []
            if not isinstance(plans, list) or not plans:
                raise ApiError(HTTPStatus.BAD_REQUEST, "at least one approved plan is required")
            home_layout_store, storage_mode = get_home_layout_store()
            job = home_layout_store.create_job(
                {
                    "product_id": HOME_LAYOUT_ACCOUNT_ID,
                    "product_name": HOME_LAYOUT_ACCOUNT_NAME,
                    "type": "home_layout_image",
                    "title": body.get("title") or f"生成 {len(plans)} 张 AI 家居户型图",
                    "config": {**body, "plans": plans},
                }
            )
            Thread(target=run_home_layout_image_job, args=(home_layout_store, job["id"]), daemon=True).start()
            return {"item": job, "storage": storage_mode}

        if method == "POST" and len(parts) == 3 and parts[2] == "copy":
            home_layout_store, storage_mode = get_home_layout_store()
            asset_id = body.get("asset_id")
            asset = next((item for item in home_layout_store.list_assets(product_id=HOME_LAYOUT_ACCOUNT_ID) if item.get("id") == asset_id), None)
            if not asset:
                raise ApiError(HTTPStatus.BAD_REQUEST, "asset_id is invalid")
            plan = asset.get("generation_plan") or {}
            context = {
                "image_url": asset.get("url") or "",
                "image_prompt": asset.get("content") or plan.get("prompt") or "",
                "style": plan.get("style") or body.get("style") or "AI 家居灵感风",
                "layout_type": body.get("layout_type") or body.get("layoutType") or "户型图",
                "area": body.get("area") or "",
                "household": body.get("household") or "",
                "mood": plan.get("mood") or body.get("mood") or "",
                "scene": plan.get("scene") or body.get("scene") or "",
                "palette": plan.get("palette") or body.get("palette") or "",
                "layout_highlights": plan.get("layout_highlights") or body.get("layout_highlights") or "",
                "user_description": body.get("description") or "",
            }
            hooks = body.get("hooks") or []
            generated = generate_home_layout_copy(context, hooks, body.get("goal") or "引导收藏")
            created = []
            for index, item in enumerate(generated.get("items") or [], start=1):
                content = (
                    f"【爆款标题】\n{item.get('title', '')}\n\n"
                    f"【正文文案】\n{item.get('content', '')}\n\n"
                    f"【封面短句】\n" + "\n".join(item.get("cover_phrases") or []) + "\n\n"
                    f"【评论区引导】\n" + "\n".join(item.get("comment_ctas") or []) + "\n\n"
                    f"【标签】\n" + " ".join(item.get("hashtags") or []) + "\n\n"
                    f"【同款软装关键词】\n" + "、".join(item.get("soft_furnishing_keywords") or [])
                )
                created.append(
                    home_layout_store.create_asset(
                        {
                            "product_id": HOME_LAYOUT_ACCOUNT_ID,
                            "product_name": HOME_LAYOUT_ACCOUNT_NAME,
                            "type": "copy",
                            "title": f"{asset.get('title') or '户型图'} · {item.get('hook') or '爆款'}文案 {index}",
                            "status": "review",
                            "style": "home_layout_copy",
                            "content": content,
                            "provider_status": generated.get("source") or "ai",
                            "source_image_url": asset.get("url") or "",
                            "generation_plan": {
                                "kind": "home_layout_copy",
                                "image_asset_id": asset.get("id"),
                                "hook": item.get("hook") or "",
                                "context": context,
                            },
                        }
                    )
                )
            return {
                "items": created,
                "source": generated.get("source"),
                "warning": generated.get("warning"),
                "storage": storage_mode,
            }

        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _commerce_learning(self, method, parts, query, body):
        if method == "GET" and len(parts) == 3 and parts[2] == "clipforge-status":
            return {"item": clipforge_status(query.get("base_url") or query.get("baseUrl"))}

        if method != "POST" or len(parts) != 3:
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

        action = parts[2]
        if action == "normalize-samples":
            return {"item": normalize_market_samples(body)}

        if action == "market-opportunities":
            market = analyze_market_opportunities(body)

            def with_market_store(app_store):
                created = None
                if body.get("save_asset", True):
                    created = app_store.create_asset(
                        {
                            "product_id": body.get("product_id") or body.get("productId") or "",
                            "product_name": "热点选品雷达",
                            "type": "copy",
                            "title": "热点选品雷达 · 爆品方向与带货方式",
                            "status": "review",
                            "style": "commerce_market_radar",
                            "content": format_market_report(market),
                            "provider_status": "market_radar",
                            "generation_plan": {
                                "kind": "commerce_market_radar",
                                "market": market,
                            },
                        }
                    )
                return {"item": market, "asset": created}

            return self._with_main_store(with_market_store)

        product_id = body.get("product_id") or body.get("productId")

        def with_product(app_store):
            product = app_store.get_product(product_id) if product_id else (body.get("product") or {})
            if not product:
                raise ApiError(HTTPStatus.BAD_REQUEST, "product_id is invalid")
            if action == "analyze":
                analysis = analyze_commerce_opportunities(product, body)
                created = None
                if body.get("save_asset", True):
                    created = app_store.create_asset(
                        {
                            "product_id": product.get("id", ""),
                            "product_name": product.get("name", ""),
                            "type": "copy",
                            "title": f"{product.get('name') or '商品'} · 爆款学习台分析",
                            "status": "review",
                            "style": "commerce_learning",
                            "content": format_learning_report(analysis),
                            "provider_status": "learning",
                            "generation_plan": {
                                "kind": "commerce_learning_analysis",
                                "analysis": analysis,
                            },
                        }
                    )
                return {"item": analysis, "asset": created}

            if action == "video-workflow":
                workflow = generate_video_workflows(product, body)
                created = None
                if body.get("save_asset", True):
                    created = app_store.create_asset(
                        {
                            "product_id": product.get("id", ""),
                            "product_name": product.get("name", ""),
                            "type": "video",
                            "title": workflow.get("title") or f"{product.get('name') or '商品'} · 带货视频工作流",
                            "status": "review",
                            "style": workflow.get("style", {}).get("id", "learning_video"),
                            "content": format_video_workflow(workflow),
                            "provider_status": "learning",
                            "generation_plan": {
                                "kind": "commerce_video_workflow",
                                "workflow": workflow,
                            },
                        }
                    )
                return {"item": workflow, "asset": created, "clipforge": workflow.get("clipforge") or {}}

            if action == "run-cycle":
                cycle = build_learning_cycle(product, body)
                created = []
                if body.get("save_asset", True):
                    created.append(
                        app_store.create_asset(
                            {
                                "product_id": product.get("id", ""),
                                "product_name": product.get("name", ""),
                                "type": "copy",
                                "title": f"{product.get('name') or '商品'} · 自循环爆款学习周期",
                                "status": "review",
                                "style": "commerce_learning_cycle",
                                "content": format_cycle_report(cycle),
                                "provider_status": "learning_cycle",
                                "generation_plan": {
                                    "kind": "commerce_learning_cycle",
                                    "cycle": cycle,
                                },
                            }
                        )
                    )
                    for workflow in cycle.get("workflows", [])[:4]:
                        created.append(
                            app_store.create_asset(
                                {
                                    "product_id": product.get("id", ""),
                                    "product_name": product.get("name", ""),
                                    "type": "video",
                                    "title": workflow.get("title") or f"{product.get('name') or '商品'} · 周期视频工作流",
                                    "status": "review",
                                    "style": workflow.get("style", {}).get("id", "learning_video"),
                                    "content": format_video_workflow(workflow),
                                    "provider_status": "learning_cycle",
                                    "generation_plan": {
                                        "kind": "commerce_video_workflow",
                                        "cycle_id": cycle.get("id"),
                                        "workflow": workflow,
                                    },
                                }
                            )
                        )
                return {
                    "item": cycle,
                    "assets": created,
                    "analysis": cycle.get("analysis"),
                    "workflows": cycle.get("workflows") or [],
                    "clipforge_status": clipforge_status(body.get("clipforge_base_url") or body.get("clipforgeBaseUrl")),
                }

            if action == "feedback":
                asset_id = body.get("asset_id") or body.get("assetId")
                if not asset_id:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "asset_id is required")
                feedback = {
                    "views": body.get("views") or 0,
                    "likes": body.get("likes") or 0,
                    "comments": body.get("comments") or 0,
                    "orders": body.get("orders") or 0,
                    "style_id": body.get("style_id") or body.get("styleId") or "",
                    "notes": body.get("notes") or "",
                    "updated_at": today(),
                }
                asset = next((item for item in app_store.list_assets(product_id=product.get("id")) if item.get("id") == asset_id), None)
                if not asset:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
                plan = asset.get("generation_plan") or {}
                history = plan.get("feedback_history") or []
                history.append(feedback)
                asset = app_store.update_asset(
                    asset_id,
                    {
                        "provider_status": "learning_feedback",
                        "generation_plan": {**plan, "feedback_history": history[-30:]},
                    },
                )
                return {"item": asset, "feedback": feedback}

            if action == "clipforge-export":
                workflow = body.get("workflow") or generate_video_workflows(product, body)
                status = clipforge_status(body.get("clipforge_base_url") or body.get("clipforgeBaseUrl"))
                return {
                    "item": workflow.get("clipforge") or {},
                    "status": status,
                    "curl_hint": "ClipForge 已作为外部服务处理；可先启动 .external/clipforge，再用它的 MCP/CLI 或自带脚本成片入口导入 payload。",
                }

            if action == "clipforge-project":
                workflow = body.get("workflow") or generate_video_workflows(product, body)
                handoff = push_workflow_to_clipforge(product, workflow, body)
                return {"item": handoff, "workflow": workflow}

            raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

        return self._with_main_store(with_product)

    def _role_wallpaper(self, method, parts, query, body):
        if method == "GET" and len(parts) == 3 and parts[2] == "roles":
            return list_role_profiles()

        if method == "GET" and len(parts) == 3 and parts[2] == "templates":
            return list_wallpaper_templates()

        if method == "GET" and len(parts) == 3 and parts[2] == "references":
            return list_reference_images(
                role_id=query.get("role_id") or query.get("roleId") or "",
                usage=query.get("usage") or "",
                template_id=query.get("template_id") or query.get("templateId") or "",
            )

        if method == "GET" and len(parts) == 3 and parts[2] == "assets":
            role_store, storage_mode = get_role_wallpaper_store()
            return {**list_role_wallpaper_assets(role_store), "storage": storage_mode}

        if method == "DELETE" and len(parts) == 4 and parts[2] == "assets":
            role_store, storage_mode = get_role_wallpaper_store()
            deleted = delete_role_wallpaper_asset(role_store, parts[3])
            if not deleted:
                raise ApiError(HTTPStatus.NOT_FOUND, "Role wallpaper asset not found")
            return {"item": deleted, "storage": storage_mode}

        if method == "POST" and len(parts) == 3 and parts[2] == "plans":
            return generate_role_wallpaper_plans(body or {})

        if method == "POST" and len(parts) == 3 and parts[2] == "reference-prompt":
            action = str((body or {}).get("action") or "analyze").strip().lower()
            if action == "analyze":
                return analyze_role_wallpaper_reference(body or {})
            if action == "expand":
                return expand_role_wallpaper_reference_plans(body or {})
            if action == "apply_to_roles":
                return apply_role_wallpaper_reference_style_to_roles(body or {})
            raise ApiError(HTTPStatus.BAD_REQUEST, "reference-prompt action must be analyze, expand or apply_to_roles")

        if method == "POST" and len(parts) == 3 and parts[2] == "images":
            plans = body.get("plans") or []
            if not isinstance(plans, list) or not plans:
                raise ApiError(HTTPStatus.BAD_REQUEST, "at least one approved role wallpaper plan is required")
            role_store, storage_mode = get_role_wallpaper_store()
            job = role_store.create_job(
                {
                    "product_id": ROLE_WALLPAPER_ACCOUNT_ID,
                    "product_name": ROLE_WALLPAPER_ACCOUNT_NAME,
                    "type": "role_wallpaper_image",
                    "title": body.get("title") or f"生成 {len(plans)} 张角色壁纸",
                    "config": {**body, "plans": plans},
                }
            )
            Thread(target=run_role_wallpaper_image_job, args=(role_store, job["id"]), daemon=True).start()
            return {"item": job, "storage": storage_mode}

        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _dance(self, method, parts, query, body):
        files = body.get("_files") or {}
        try:
            if method == "GET" and len(parts) == 3 and parts[2] == "workflows":
                return {"items": list_dance_workflows()}

            if method == "POST" and len(parts) == 3 and parts[2] == "workflows":
                item = create_dance_workflow(
                    image_file=files.get("image"),
                    video_file=files.get("video"),
                    image_url=body.get("image_url") or "",
                    video_url=body.get("video_url") or "",
                    engine=body.get("engine") or "animate-anyone",
                    use_ref_img_bg=_as_bool(body.get("use_ref_img_bg")),
                    video_ratio=body.get("video_ratio") or "9:16",
                    mode=body.get("mode") or "wan-std",
                    watermark=_as_bool(body.get("watermark")),
                )
                return {"item": item}

            if method == "GET" and len(parts) == 4 and parts[2] == "workflows":
                item = get_dance_workflow(parts[3])
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Dance workflow not found")
                return {"item": item}

            if method == "POST" and len(parts) == 3 and parts[2] == "image-check":
                return detect_person_image(image_file=files.get("image"), image_url=body.get("image_url") or "")

            if method == "POST" and len(parts) == 3 and parts[2] == "templates":
                return submit_action_template(video_file=files.get("video"), video_url=body.get("video_url") or "")

            if method == "POST" and len(parts) == 3 and parts[2] == "videos":
                return submit_dance_video(
                    template_id=body.get("template_id") or "",
                    image_file=files.get("image"),
                    image_url=body.get("image_url") or "",
                    use_ref_img_bg=_as_bool(body.get("use_ref_img_bg")),
                    video_ratio=body.get("video_ratio") or "9:16",
                )

            if method == "POST" and len(parts) == 3 and parts[2] == "wan-move":
                return submit_wan_motion_video(
                    image_file=files.get("image"),
                    video_file=files.get("video"),
                    image_url=body.get("image_url") or "",
                    video_url=body.get("video_url") or "",
                    mode=body.get("mode") or "wan-std",
                    watermark=_as_bool(body.get("watermark")),
                    check_image=_as_bool(body.get("check_image", True)),
                )

            if method == "GET" and len(parts) == 4 and parts[2] == "tasks":
                return get_dance_provider_task(parts[3])
        except AnimateAnyoneError as exc:
            message = str(exc)
            status = HTTPStatus.BAD_REQUEST if any(
                token in message for token in ("尚未配置", "请上传", "不能为空", "只能为")
            ) else HTTPStatus.BAD_GATEWAY
            raise ApiError(status, message) from exc

        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _jobs(self, method, parts, query, body):
        if method == "GET" and len(parts) == 3:
            if role_wallpaper_storage_mode == "local_fallback":
                return {"items": role_wallpaper_local_store.list_jobs(status=query.get("status")), "storage": role_wallpaper_storage_mode}
            if home_layout_storage_mode == "local_fallback":
                return {"items": home_layout_local_store.list_jobs(status=query.get("status")), "storage": home_layout_storage_mode}
            return self._with_main_store(lambda app_store: {"items": app_store.list_jobs(status=query.get("status"))})

        if method == "GET" and len(parts) == 4:
            if role_wallpaper_storage_mode == "local_fallback":
                item = role_wallpaper_local_store.get_job(parts[3])
                if item:
                    return {"item": item, "storage": role_wallpaper_storage_mode}
            if home_layout_storage_mode == "local_fallback":
                item = home_layout_local_store.get_job(parts[3])
                if item:
                    return {"item": item, "storage": home_layout_storage_mode}

            def action(app_store):
                item = app_store.get_job(parts[3])
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Job not found")
                return {"item": item}

            return self._with_main_store(action)

        if method == "POST" and len(parts) == 3:
            def action(app_store):
                product_id = body.get("product_id")
                product = app_store.get_product(product_id)
                if not product:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "product_id is invalid")

                config = body.get("config") or {}
                job = app_store.create_job(
                    {
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "type": config.get("type", "note_package"),
                        "title": body.get("title") or f"生成 {config.get('note_count', 10)} 条笔记包",
                        "config": config,
                    }
                )
                Thread(target=run_generation_job, args=(app_store, job["id"]), daemon=True).start()
                return {"item": job}

            return self._with_main_store(action)

        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > 230 * 1024 * 1024:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "上传内容不能超过 230MB")
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.lower().startswith("multipart/form-data"):
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw
            )
            body = {"_files": {}}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                if filename is not None:
                    body["_files"][name] = {
                        "filename": filename,
                        "content_type": part.get_content_type(),
                        "content": payload,
                    }
                else:
                    charset = part.get_content_charset() or "utf-8"
                    body[name] = payload.decode(charset, errors="replace")
            return body
        text = raw.decode("utf-8")
        return json.loads(text) if text else {}

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", settings.cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization,api-key")
        self.end_headers()
        self.wfile.write(body)

    def _maybe_send_asset_download(self, path, query):
        match = re.fullmatch(r"/api/assets/([^/]+)/download", path)
        if not match:
            return False
        asset_id = match.group(1)
        item = None
        if home_layout_storage_mode == "local_fallback":
            item = next((asset for asset in home_layout_local_store.list_assets() if asset.get("id") == asset_id), None)
        if not item and role_wallpaper_storage_mode == "local_fallback":
            item = next((asset for asset in role_wallpaper_local_store.list_assets() if asset.get("id") == asset_id), None)
        if not item and main_storage_mode == "local_fallback":
            item = next((asset for asset in main_local_store.list_assets() if asset.get("id") == asset_id), None)
        if not item:
            try:
                item = next((asset for asset in store.list_assets() if asset.get("id") == asset_id), None)
            except Exception as exc:
                if not activate_main_store_fallback(exc):
                    raise
                item = next((asset for asset in main_local_store.list_assets() if asset.get("id") == asset_id), None)
        if not item:
            raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")

        filename = _download_filename(item)
        content_type = "text/plain; charset=utf-8"
        data = b""

        source_url = _asset_download_url(item)
        if source_url:
            data, content_type = _read_download_url(source_url)
            filename = _with_extension(filename, content_type, source_url)
        else:
            data = (item.get("content") or item.get("title") or "").encode("utf-8")
            filename = _with_extension(filename, content_type, "")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        disposition = "inline" if query.get("view") else "attachment"
        self.send_header("Content-Disposition", _content_disposition(disposition, filename))
        self.send_header("Access-Control-Allow-Origin", settings.cors_origin)
        self.send_header("Access-Control-Expose-Headers", "Content-Disposition,Content-Type")
        self.end_headers()
        self.wfile.write(data)
        return True

    def _maybe_send_asset_archive(self, path, query):
        if path != "/api/assets/archive":
            return False
        asset_ids = [item.strip() for item in str(query.get("ids") or "").split(",") if item.strip()]
        asset_ids = list(dict.fromkeys(asset_ids))[:50]
        if not asset_ids:
            raise ApiError(HTTPStatus.BAD_REQUEST, "至少选择一张图片")

        candidates = []
        for source_store in (home_layout_local_store, role_wallpaper_local_store, main_local_store, store):
            try:
                candidates.extend(source_store.list_assets())
            except Exception:
                pass
        try:
            role_store, _ = get_role_wallpaper_store()
            candidates.extend(list_role_wallpaper_assets(role_store).get("items") or [])
        except Exception:
            pass
        by_id = {item.get("id"): item for item in candidates if item and item.get("id")}

        buffer = BytesIO()
        errors = []
        used_names = set()
        added = 0
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, asset_id in enumerate(asset_ids, start=1):
                item = by_id.get(asset_id)
                if not item:
                    errors.append(f"{asset_id}: 素材不存在")
                    continue
                source_url = _asset_download_url(item)
                if not source_url:
                    errors.append(f"{item.get('title') or asset_id}: 缺少图片地址")
                    continue
                try:
                    data, content_type = _read_download_url(source_url)
                    filename = _with_extension(_download_filename(item), content_type, source_url)
                    stem, suffix = Path(filename).stem, Path(filename).suffix
                    candidate = filename
                    serial = 2
                    while candidate in used_names:
                        candidate = f"{stem}-{serial}{suffix}"
                        serial += 1
                    used_names.add(candidate)
                    archive.writestr(candidate, data)
                    added += 1
                except Exception as exc:
                    errors.append(f"{item.get('title') or asset_id}: {exc}")
            if errors:
                archive.writestr("download-errors.txt", "\n".join(errors).encode("utf-8"))
        if not added:
            raise ApiError(HTTPStatus.BAD_GATEWAY, "选中的图片均无法下载：" + "；".join(errors[:3]))

        data = buffer.getvalue()
        filename = f"role-wallpapers-{added}-images.zip"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", _content_disposition("attachment", filename))
        self.send_header("Access-Control-Allow-Origin", settings.cors_origin)
        self.send_header("Access-Control-Expose-Headers", "Content-Disposition,Content-Type")
        self.end_headers()
        self.wfile.write(data)
        return True

    def _maybe_send_role_reference_file(self, path):
        match = re.fullmatch(r"/api/role-wallpaper/references/([^/]+)/file", path)
        if not match:
            return False
        try:
            data, content_type, filename = get_reference_file(match.group(1))
        except FileNotFoundError:
            raise ApiError(HTTPStatus.NOT_FOUND, "Reference image not found")
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", _content_disposition("inline", filename))
        self.send_header("Access-Control-Allow-Origin", settings.cors_origin)
        self.end_headers()
        self.wfile.write(data)
        return True


def _content_disposition(disposition, filename):
    raw_name = str(filename or "download").replace("\r", "").replace("\n", "")
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip(".-") or "download"
    encoded = quote(raw_name, safe="")
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def _download_filename(item):
    label = {
        "copy": "copy",
        "cover": "cover",
        "detailimg": "detail",
        "video": "video",
    }.get(item.get("type"), "asset")
    asset_id = re.sub(r"[^A-Za-z0-9_-]+", "-", item.get("id") or "asset").strip("-")
    return f"xhs-{label}-{asset_id or 'asset'}"


def _looks_like_image_url(value):
    if not isinstance(value, str):
        return False
    if value.startswith("data:image/"):
        return True
    return bool(re.search(r"^https?://.+\.(png|jpe?g|webp)(\?|#|$)", value, re.I))


def _first_image_url(value, depth=0):
    if not value or depth > 5:
        return ""
    if isinstance(value, str):
        return value if _looks_like_image_url(value) else ""
    if isinstance(value, list):
        for item in value:
            found = _first_image_url(item, depth + 1)
            if found:
                return found
        return ""
    if not isinstance(value, dict):
        return ""
    for key in ("url", "image_url", "output_url"):
        if _looks_like_image_url(value.get(key)):
            return value[key]
    for key in ("results", "result", "data", "raw", "images", "outputs"):
        found = _first_image_url(value.get(key), depth + 1)
        if found:
            return found
    return ""


def _asset_download_url(item):
    return item.get("url") or _first_image_url(item.get("provider_task")) or ""


def _read_download_url(url):
    if url.startswith("data:"):
        header, _, payload = url.partition(",")
        content_type = header[5:].split(";")[0] or "application/octet-stream"
        if ";base64" in header:
            return base64.b64decode(payload), content_type
        return unquote_to_bytes(payload), content_type

    if not url.startswith(("http://", "https://")):
        raw_path = urlparse(url).path if url.startswith("/") else url
        path = Path(raw_path)
        if not path.is_absolute():
            path = WORKSPACE_ROOT / raw_path.lstrip("/")
        path = path.resolve()
        try:
            path.relative_to(WORKSPACE_ROOT.resolve())
        except ValueError as exc:
            raise FileNotFoundError("Local asset path is outside workspace") from exc
        if not path.exists() or not path.is_file():
            raise FileNotFoundError("Local asset file not found")
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return path.read_bytes(), content_type

    context = None
    if not settings.image_ssl_verify:
        context = ssl._create_unverified_context()
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=90, context=context) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";")[0]
        return response.read(), content_type or "application/octet-stream"


def _with_extension(filename, content_type, source_url=""):
    if "." in Path(filename).name:
        return filename
    ext = mimetypes.guess_extension((content_type or "").split(";")[0]) or ""
    if ext == ".jpe":
        ext = ".jpg"
    if not ext and source_url:
        ext = Path(urlparse(source_url).path).suffix
    if not ext:
        ext = ".txt" if (content_type or "").startswith("text/") else ".bin"
    return filename + ext


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main():
    parser = argparse.ArgumentParser(description="XHS asset generator backend API")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    print(f"XHS Asset API running at http://{args.host}:{args.port}/api/health")
    server.serve_forever()


if __name__ == "__main__":
    main()
