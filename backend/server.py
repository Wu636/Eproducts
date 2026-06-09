from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

sys.path.append(str(Path(__file__).resolve().parent))

from config import settings
from services.image_provider import build_image_request_debug, create_image_task, get_image_result
from services.mock_generation import run_generation_job
from services.text_provider import generate_copywriting
from store import InMemoryStore


store = InMemoryStore()


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
            body = self._read_json() if method in {"POST", "PATCH", "DELETE"} else {}
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

        if resource == "generation" and len(parts) >= 3 and parts[2] == "jobs":
            return self._jobs(method, parts, query, body)

        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def _providers(self, method, parts, body):
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
                extra=body.get("extra"),
            )

        if method == "POST" and len(parts) == 4 and parts[1:] == ["providers", "image", "result"]:
            task_id = body.get("task_id") or body.get("id")
            if not task_id:
                raise ApiError(HTTPStatus.BAD_REQUEST, "task_id or id is required")
            return get_image_result(task_id=task_id, extra=body.get("extra"))

        raise ApiError(HTTPStatus.NOT_FOUND, "Not found")

    def _products(self, method, parts, body):
        if method == "GET" and len(parts) == 2:
            return {"items": store.list_products()}
        if method == "POST" and len(parts) == 2:
            if not body.get("name"):
                raise ApiError(HTTPStatus.BAD_REQUEST, "name is required")
            return {"item": store.create_product(body)}
        if len(parts) == 3:
            product_id = parts[2]
            if method == "GET":
                item = store.get_product(product_id)
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Product not found")
                return {"item": item}
            if method == "PATCH":
                item = store.update_product(product_id, body)
                if not item:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Product not found")
                return {"item": item}
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _uploads(self, method, body):
        if method != "POST":
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
        return {"item": store.create_upload(body)}

    def _assets(self, method, parts, query, body):
        if method == "GET" and len(parts) == 2:
            return {
                "items": store.list_assets(
                    product_id=query.get("product_id"),
                    asset_type=query.get("type"),
                    status=query.get("status"),
                )
            }
        if method == "PATCH" and len(parts) == 3:
            item = store.update_asset(parts[2], body)
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
            return {"item": item}
        if method == "PATCH" and len(parts) == 4 and parts[3] == "status":
            item = store.update_asset_status(parts[2], body.get("status", "review"))
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
            return {"item": item}
        if method == "DELETE" and len(parts) == 3:
            item = store.delete_asset(parts[2])
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "Asset not found")
            return {"item": item}
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _note_packages(self, method, parts, query, body):
        if method == "GET" and len(parts) == 2:
            return {
                "items": store.list_note_packages(
                    product_id=query.get("product_id"),
                    status=query.get("status"),
                )
            }
        if method == "PATCH" and len(parts) == 4 and parts[3] == "status":
            item = store.update_note_status(parts[2], body.get("status", "review"))
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "Note package not found")
            return {"item": item}
        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _jobs(self, method, parts, query, body):
        if method == "GET" and len(parts) == 3:
            return {"items": store.list_jobs(status=query.get("status"))}

        if method == "GET" and len(parts) == 4:
            item = store.get_job(parts[3])
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "Job not found")
            return {"item": item}

        if method == "POST" and len(parts) == 3:
            product_id = body.get("product_id")
            product = store.get_product(product_id)
            if not product:
                raise ApiError(HTTPStatus.BAD_REQUEST, "product_id is invalid")

            config = body.get("config") or {}
            job = store.create_job(
                {
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "type": config.get("type", "note_package"),
                    "title": body.get("title") or f"生成 {config.get('note_count', 10)} 条笔记包",
                    "config": config,
                }
            )
            Thread(target=run_generation_job, args=(store, job["id"]), daemon=True).start()
            return {"item": job}

        raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", settings.cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.end_headers()
        self.wfile.write(body)


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
