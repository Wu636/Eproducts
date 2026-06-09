from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import RLock
from uuid import uuid4


def today():
    return datetime.now().date().isoformat()


def make_id(prefix):
    return f"{prefix}_{uuid4().hex[:12]}"


class InMemoryStore:
    """Small in-memory store for the prototype API.

    Replace this with a database repository later without changing the route
    shapes. The frontend can already code against these response contracts.
    """

    def __init__(self):
        self._lock = RLock()
        self.products = {}
        self.assets = {}
        self.note_packages = {}
        self.jobs = {}
        self.uploads = {}
        self.seed()

    def seed(self):
        product = self.create_product(
            {
                "name": "316不锈钢保温杯",
                "category": "家居日用",
                "price": "券后 89 元",
                "audience": "通勤上班族、学生党",
                "selling_points": [
                    "316 不锈钢内胆",
                    "12 小时长效保温",
                    "单手开盖不漏水",
                    "奶油白磨砂高颜值",
                ],
                "scene": "办公室、通勤、宿舍、自习室",
                "tone": "真实种草",
                "spec": "500ml / 奶油白 / 硅胶防滑底 / 赠杯刷",
                "forbidden_words": ["最", "第一", "永久"],
            }
        )
        copy = self.create_asset(
            {
                "product_id": product["id"],
                "type": "copy",
                "title": "保温杯种草文案 · 温暖治愈风",
                "status": "approved",
                "content": "冬天的仪式感，从一杯热饮开始。这个保温杯适合通勤、办公室和宿舍使用。",
            }
        )
        cover = self.create_asset(
            {
                "product_id": product["id"],
                "type": "cover",
                "title": "保温杯清新简约封面",
                "status": "approved",
                "style": "clean",
            }
        )
        self.create_note_package(
            {
                "product_id": product["id"],
                "title": "316不锈钢保温杯真的值得买吗？",
                "angle": "生活化种草",
                "persona": "真实自用",
                "status": "approved",
                "score": 92,
                "copy_asset_id": copy["id"],
                "cover_asset_id": cover["id"],
                "detail_asset_ids": [],
                "video_asset_id": "",
                "summary": "适合通勤上班族和学生党的保温杯种草笔记。",
                "hashtags": ["#家居日用好物", "#保温杯", "#小红书种草"],
                "publish_plan": "待排期",
            }
        )

    def _clone(self, value):
        return deepcopy(value)

    def create_product(self, data):
        with self._lock:
            variants = data.get("variants") or []
            normalized_variants = []
            for index, variant in enumerate(variants):
                image_url = variant.get("image_url") or variant.get("imageUrl") or ""
                if not image_url:
                    continue
                normalized_variants.append(
                    {
                        "id": variant.get("id") or f"v_{index}",
                        "name": variant.get("name") or f"款式 {index + 1}",
                        "image_url": image_url,
                        "notes": variant.get("notes", ""),
                    }
                )
            item = {
                "id": data.get("id") or make_id("prod"),
                "name": data.get("name", "未命名产品"),
                "category": data.get("category", "其他"),
                "price": data.get("price", ""),
                "audience": data.get("audience", ""),
                "selling_points": data.get("selling_points", []),
                "scene": data.get("scene", ""),
                "tone": data.get("tone", "真实种草"),
                "spec": data.get("spec", ""),
                "forbidden_words": data.get("forbidden_words", []),
                "product_url": data.get("product_url", ""),
                "image_url": data.get("image_url", ""),
                "variants": normalized_variants,
                "selected_variant_id": data.get("selected_variant_id") or (normalized_variants[0]["id"] if normalized_variants else ""),
                "created_at": data.get("created_at", today()),
                "updated_at": today(),
            }
            self.products[item["id"]] = item
            return self._clone(item)

    def update_product(self, product_id, data):
        with self._lock:
            if product_id not in self.products:
                return None
            self.products[product_id].update(data)
            self.products[product_id]["updated_at"] = today()
            return self._clone(self.products[product_id])

    def get_product(self, product_id):
        with self._lock:
            item = self.products.get(product_id)
            return self._clone(item) if item else None

    def list_products(self):
        with self._lock:
            return self._clone(list(self.products.values()))

    def create_asset(self, data):
        with self._lock:
            item = {
                "id": data.get("id") or make_id("asset"),
                "product_id": data.get("product_id", ""),
                "type": data.get("type", "copy"),
                "title": data.get("title", ""),
                "status": data.get("status", "review"),
                "style": data.get("style", ""),
                "content": data.get("content", ""),
                "url": data.get("url", ""),
                "provider_task": data.get("provider_task", {}),
                "provider_status": data.get("provider_status", ""),
                "variant_id": data.get("variant_id", ""),
                "variant_name": data.get("variant_name", ""),
                "source_image_url": data.get("source_image_url", ""),
                "generation_plan": data.get("generation_plan", {}),
                "created_at": data.get("created_at", today()),
            }
            product = self.products.get(item["product_id"])
            item["product_name"] = product["name"] if product else data.get("product_name", "")
            self.assets[item["id"]] = item
            return self._clone(item)

    def list_assets(self, product_id=None, asset_type=None, status=None):
        with self._lock:
            items = list(self.assets.values())
            if product_id:
                items = [x for x in items if x["product_id"] == product_id]
            if asset_type:
                items = [x for x in items if x["type"] == asset_type]
            if status:
                items = [x for x in items if x["status"] == status]
            return self._clone(items)

    def update_asset_status(self, asset_id, status):
        with self._lock:
            if asset_id not in self.assets:
                return None
            self.assets[asset_id]["status"] = status
            return self._clone(self.assets[asset_id])

    def update_asset(self, asset_id, data):
        with self._lock:
            if asset_id not in self.assets:
                return None
            allowed = {"title", "status", "style", "content", "url", "provider_task", "provider_status", "variant_id", "variant_name", "source_image_url", "generation_plan"}
            for key, value in data.items():
                if key in allowed:
                    self.assets[asset_id][key] = value
            return self._clone(self.assets[asset_id])

    def delete_asset(self, asset_id):
        with self._lock:
            item = self.assets.pop(asset_id, None)
            if not item:
                return None
            for note in self.note_packages.values():
                if note.get("copy_asset_id") == asset_id:
                    note["copy_asset_id"] = ""
                if note.get("cover_asset_id") == asset_id:
                    note["cover_asset_id"] = ""
                if note.get("video_asset_id") == asset_id:
                    note["video_asset_id"] = ""
                note["detail_asset_ids"] = [x for x in note.get("detail_asset_ids", []) if x != asset_id]
            return self._clone(item)

    def create_note_package(self, data):
        with self._lock:
            product = self.products.get(data.get("product_id", ""))
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
            self.note_packages[item["id"]] = item
            return self._clone(item)

    def list_note_packages(self, product_id=None, status=None):
        with self._lock:
            items = list(self.note_packages.values())
            if product_id:
                items = [x for x in items if x["product_id"] == product_id]
            if status:
                items = [x for x in items if x["status"] == status]
            return self._clone(items)

    def update_note_status(self, note_id, status):
        with self._lock:
            if note_id not in self.note_packages:
                return None
            self.note_packages[note_id]["status"] = status
            if status == "published":
                self.note_packages[note_id]["publish_plan"] = "已发布"
            return self._clone(self.note_packages[note_id])

    def create_job(self, data):
        with self._lock:
            item = {
                "id": data.get("id") or make_id("job"),
                "product_id": data.get("product_id", ""),
                "product_name": data.get("product_name", ""),
                "type": data.get("type", "note_package"),
                "title": data.get("title", "生成任务"),
                "status": "running",
                "progress": 0,
                "detail": "任务已创建",
                "config": data.get("config", {}),
                "created_at": today(),
                "result": {},
            }
            self.jobs[item["id"]] = item
            return self._clone(item)

    def update_job(self, job_id, **data):
        with self._lock:
            if job_id not in self.jobs:
                return None
            self.jobs[job_id].update(data)
            return self._clone(self.jobs[job_id])

    def get_job(self, job_id):
        with self._lock:
            item = self.jobs.get(job_id)
            return self._clone(item) if item else None

    def list_jobs(self, status=None):
        with self._lock:
            items = list(self.jobs.values())
            if status:
                items = [x for x in items if x["status"] == status]
            return self._clone(items)

    def create_upload(self, data):
        with self._lock:
            item = {
                "id": make_id("upload"),
                "filename": data.get("filename", ""),
                "content_type": data.get("content_type", ""),
                "url": data.get("data_url") or data.get("url", ""),
                "created_at": today(),
            }
            self.uploads[item["id"]] = item
            return self._clone(item)
