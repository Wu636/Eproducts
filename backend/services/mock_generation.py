from __future__ import annotations

from copy import deepcopy
from time import sleep

from services.image_provider import ProviderNotConfigured as ImageProviderNotConfigured
from services.image_provider import create_image_task
from services.image_provider import wait_for_image_result
from services.text_provider import ProviderNotConfigured, generate_copywriting


NOTE_ANGLES = ["生活化种草", "痛点解决", "真实测评", "开箱体验", "竞品对比", "优惠转化"]
COVER_STYLES = ["clean", "aesthetic", "compare", "collage", "list_c"]
DETAIL_STYLES = ["feature", "spec", "scene", "compare_d"]


def _points(product):
    points = product.get("selling_points") or []
    if isinstance(points, str):
        points = [x.strip() for x in points.replace("；", "\n").splitlines() if x.strip()]
    return points or ["高颜值", "好上手", "性价比友好"]


def _selected_variant(product, variant_id=""):
    variants = product.get("variants") or []
    if not variants:
        return {
            "id": "",
            "name": "",
            "image_url": product.get("image_url") or product.get("imageUrl") or "",
            "notes": "",
        }
    selected_id = variant_id or product.get("selected_variant_id") or product.get("selectedVariantId") or ""
    return next((v for v in variants if v.get("id") == selected_id), variants[0])


def _product_for_variant(product, variant_id=""):
    item = deepcopy(product)
    variant = _selected_variant(item, variant_id)
    if variant.get("id"):
        item["selected_variant_id"] = variant["id"]
        item["image_url"] = variant.get("image_url") or item.get("image_url", "")
    return item


def _copy(product, angle, persona, word_range="", rewrite_suggestion="", template_prompt=""):
    points = "\n".join(f"• {x}" for x in _points(product)[:4])
    rewrite_line = f"\n重写建议：{rewrite_suggestion}\n" if rewrite_suggestion else ""
    template_line = f"\n模板提示词：{template_prompt}\n" if template_prompt else ""
    return (
        f"{product['name']}这次按「{persona}」角度来写。\n\n"
        f"内容方向：{angle}\n"
        f"字数范围：{word_range or '200-300字'}\n"
        f"适合人群：{product.get('audience') or '日常自用人群'}\n"
        f"使用场景：{product.get('scene') or '日常使用'}\n"
        f"价格/利益点：{product.get('price') or '按实际活动填写'}\n\n"
        f"核心卖点：\n{points}\n\n"
        f"{template_line}"
        f"{rewrite_line}"
        f"真实分享建议：少夸张，多讲细节和使用感。"
    )


def _provider_copy(product, angle, persona, goal, word_range="", rewrite_suggestion="", template_prompt=""):
    try:
        return generate_copywriting(product, angle, persona, goal=goal, word_range=word_range, rewrite_suggestion=rewrite_suggestion, template_prompt=template_prompt), "real"
    except ProviderNotConfigured:
        return _copy(product, angle, persona, word_range=word_range, rewrite_suggestion=rewrite_suggestion, template_prompt=template_prompt), "mock"
    except Exception as exc:
        status = f"fallback_error:{type(exc).__name__}"
        return _copy(product, angle, persona, word_range=word_range, rewrite_suggestion=rewrite_suggestion, template_prompt=template_prompt), status


def _title(product, angle, index):
    options = [
        f"{product['name']}真的值得买吗？我替你试了",
        f"{product.get('audience') or '新手'}闭眼入的{product.get('category') or '好物'}",
        f"不夸张分享：{product['name']}适合这些场景",
        f"用了才懂，{product['name']}这个细节很加分",
    ]
    return f"{options[index % len(options)]}｜{angle}"


def _ratio_text(aspect_ratio, asset_type):
    mapping = {
        "3:4": "3:4 小红书竖版封面",
        "1:1": "1:1 小红书正方形封面",
        "9:16": "9:16 小红书全屏竖版封面",
        "1024x1024": "1:1 小红书正方形封面",
        "1024x1536": "3:4 小红书竖版封面",
        "1536x2048": "3:4 小红书竖版封面",
    }
    if aspect_ratio in mapping:
        return mapping[aspect_ratio]
    if aspect_ratio:
        return str(aspect_ratio)
    return "3:4 小红书竖版封面" if asset_type == "cover" else "小红书产品细节图"


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_image_url(value):
    if not isinstance(value, str):
        return False
    if value.startswith("data:image/"):
        return True
    return value.startswith(("http://", "https://")) or value.startswith("/")


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
    for key in ("url", "image_url", "imageUrl", "output_url", "outputUrl"):
        if _looks_like_image_url(value.get(key)):
            return value[key]
    for key in ("provider_task", "providerTask", "raw", "results", "result", "data", "images", "outputs"):
        found = _first_image_url(value.get(key), depth + 1)
        if found:
            return found
    return ""


def _asset_image_url(asset):
    if not asset:
        return ""
    return asset.get("url") or _first_image_url(asset.get("provider_task")) or _first_image_url(asset.get("providerTask"))


def _source_asset_url(store, asset_id, product_id=""):
    if not asset_id:
        return ""
    candidates = []
    try:
        candidates.extend(store.list_assets(product_id=product_id) if product_id else [])
    except Exception:
        pass
    try:
        candidates.extend(store.list_assets())
    except Exception:
        pass
    seen = set()
    for asset in candidates:
        if not asset or asset.get("id") in seen:
            continue
        seen.add(asset.get("id"))
        if asset.get("id") == asset_id:
            return _asset_image_url(asset)
    return ""


def _image_prompt(product, asset_type, angle, index, aspect_ratio="", rewrite_suggestion="", template_prompt="", image_advice="", plan_item=None):
    ratio = _ratio_text(aspect_ratio, asset_type)
    plan_item = plan_item or {}
    variant = _selected_variant(product, plan_item.get("variantId") or plan_item.get("variant_id") or "")
    subject_rule = (
        f"必须严格参考输入产品图（当前款式：{variant.get('name') or '默认款'}）：保持产品主体形态、轮廓、颜色、材质、装饰细节、比例关系一致，"
        "不要改成其他动物/其他商品/其他颜色，不要凭空新增会改变商品识别度的结构或配饰。"
        "只允许优化光线、背景、构图、留白和小红书电商氛围。"
    )
    plan_text = plan_item.get("prompt") or ""
    reference_edit_rule = ""
    if _truthy(plan_item.get("referenceEditMode") or plan_item.get("reference_edit_mode")):
        reference_edit_rule = (
            "第一张参考图是上一版已生成图，本次任务是基于这张图做局部重生。"
            "优先保留上一版图里的商品主体、比例、材质、包装文字/服饰细节、构图关系和可用部分，"
            "只根据用户修改建议调整背景、光线、道具、留白、姿势或局部瑕疵；不要无关大改。"
        )
    return (
        f"{ratio}，产品：{product.get('name')}，类目：{product.get('category')}，"
        f"内容角度：{angle}，核心卖点：{'、'.join(_points(product)[:4])}。"
        f"{subject_rule}"
        f"{reference_edit_rule}"
        f"{'模板提示词：' + template_prompt + '。' if template_prompt else ''}"
        f"{'用户生图建议：' + image_advice + '。' if image_advice else ''}"
        f"{'本张审核通过的生图方案：' + plan_text + '。' if plan_text else ''}"
        f"{'重写/修改建议：' + rewrite_suggestion + '。' if rewrite_suggestion else ''}"
        "风格真实清新，适合小红书电商种草，商品主体清晰，文字区域留白，商业摄影质感。"
    )


def _reference_images(product, variant_id="", source_reference_url=""):
    variant = _selected_variant(product, variant_id)
    image_url = variant.get("image_url") or variant.get("imageUrl") or product.get("image_url") or product.get("imageUrl") or ""
    refs = []
    for url in (source_reference_url, image_url):
        if url and url not in refs:
            refs.append(url)
    return refs or None


def _provider_image_task(product, asset_type, angle, index, size="auto", aspect_ratio="", rewrite_suggestion="", template_prompt="", image_advice="", plan_item=None, image_model=""):
    plan_item = plan_item or {}
    variant_id = plan_item.get("variantId") or plan_item.get("variant_id") or product.get("selected_variant_id", "")
    source_reference_url = plan_item.get("sourceImageUrl") or plan_item.get("source_image_url") or plan_item.get("source_reference_url") or ""
    prompt = _image_prompt(product, asset_type, angle, index, aspect_ratio=aspect_ratio, rewrite_suggestion=rewrite_suggestion, template_prompt=template_prompt, image_advice=image_advice, plan_item=plan_item)
    try:
        result = create_image_task(
            prompt=prompt,
            size=size or "auto",
            aspect_ratio=aspect_ratio or size or "auto",
            images=_reference_images(product, variant_id, source_reference_url=source_reference_url),
            model=image_model or None,
        )
        result = wait_for_image_result(result, max_wait=300)
        status = result.get("status") or ("succeeded" if result.get("url") else "submitted")
        if not result.get("url") and str(status).lower() in {"completed", "succeeded", "success"}:
            status = "failed"
        return {
            "url": result.get("url") or "",
            "provider_task": result,
            "provider_status": status,
            "content": prompt,
        }
    except ImageProviderNotConfigured:
        return {
            "url": "",
            "provider_task": {},
            "provider_status": "mock",
            "content": prompt,
        }
    except Exception as exc:
        return {
            "url": "",
            "provider_task": {"error": str(exc)},
            "provider_status": "failed",
            "content": prompt,
        }


def run_generation_job(store, job_id):
    try:
        _run_generation_job(store, job_id)
    except Exception as exc:
        try:
            store.update_job(job_id, status="failed", progress=100, detail=f"真实接口调用失败：{exc}")
        except Exception:
            pass


def _run_generation_job(store, job_id):
    job = store.get_job(job_id)
    if not job:
        return

    product = store.get_product(job["product_id"])
    if not product:
        store.update_job(job_id, status="failed", progress=100, detail="产品不存在")
        return

    config = job.get("config") or {}
    mode = config.get("mode", "all")
    count = int(config.get("note_count") or config.get("count") or 10)
    count = max(1, min(count, 30))
    persona = config.get("persona", "真实自用")
    goal = config.get("goal", "引流成交")
    angles = config.get("angles") or NOTE_ANGLES[:4]
    asset_types = config.get("asset_types") or ["copy", "cover", "detailimg", "video"]
    image_size = config.get("size") or "auto"
    aspect_ratio = config.get("aspect_ratio") or ""
    word_range = config.get("word_range") or ""
    rewrite_suggestion = config.get("rewrite_suggestion") or ""
    template_prompt = config.get("template_prompt") or ""
    image_advice = config.get("image_advice") or ""
    plan_items = config.get("plan_items") or []
    image_model = config.get("image_model") or config.get("imageModel") or ""
    image_model_profile = config.get("image_model_profile") or config.get("imageModelProfile") or {}
    source_asset_id = config.get("source_asset_id") or config.get("sourceAssetId") or ""
    source_image_url = config.get("source_image_url") or config.get("sourceImageUrl") or ""
    use_source_image_reference = _truthy(config.get("use_source_image_reference") or config.get("useSourceImageReference") or config.get("reference_edit_mode") or config.get("referenceEditMode"))
    variant_id = config.get("variant_id") or product.get("selected_variant_id", "")
    variant = _selected_variant(product, variant_id)
    product_for_text = _product_for_variant(product, variant.get("id", ""))
    if use_source_image_reference and not source_image_url:
        source_image_url = _source_asset_url(store, source_asset_id, product.get("id", ""))

    steps = [
        "分析产品资料",
        "生成标题与正文",
        "生成封面和详情图占位",
        "生成视频脚本",
        "整理笔记包",
    ]
    for index, step in enumerate(steps, start=1):
        sleep(0.15)
        store.update_job(job_id, progress=int(index / len(steps) * 80), detail=step)

    created_assets = []
    created_notes = []
    copy_ids = []
    cover_ids = []
    detail_ids = []
    video_ids = []
    needs_copy_content = "copy" in asset_types or mode == "all"

    for i in range(count):
        angle = angles[i % len(angles)]
        copy_content = ""
        copy_provider_status = ""
        if needs_copy_content:
            copy_content, copy_provider_status = _provider_copy(
                product_for_text,
                angle,
                persona,
                goal,
                word_range=word_range,
                rewrite_suggestion=rewrite_suggestion,
                template_prompt=template_prompt,
            )
        if "copy" in asset_types:
            asset = store.create_asset(
                {
                    "product_id": product["id"],
                    "type": "copy",
                    "title": f"{product['name']} · {angle}文案",
                    "status": "review",
                    "content": copy_content,
                    "provider_status": copy_provider_status,
                    "variant_id": variant.get("id", ""),
                    "variant_name": variant.get("name", ""),
                    "source_image_url": variant.get("image_url", ""),
                }
            )
            copy_ids.append(asset["id"])
            created_assets.append(asset)

        if "cover" in asset_types:
            plan_item = plan_items[i % len(plan_items)] if plan_items else {}
            plan_variant = _selected_variant(product, plan_item.get("variantId") or plan_item.get("variant_id") or variant.get("id", ""))
            image_product = _product_for_variant(product, plan_variant.get("id", ""))
            plan_source_url = plan_item.get("sourceImageUrl") or plan_item.get("source_image_url") or source_image_url
            plan_reference_edit = _truthy(plan_item.get("referenceEditMode") or plan_item.get("reference_edit_mode")) or bool(plan_source_url and use_source_image_reference)
            plan_with_model = {
                **plan_item,
                "image_model": image_model,
                "image_model_profile": image_model_profile,
                "source_asset_id": plan_item.get("sourceAssetId") or plan_item.get("source_asset_id") or source_asset_id,
                "source_image_url": plan_source_url,
                "source_reference_url": plan_source_url,
                "reference_edit_mode": plan_reference_edit,
            }
            image_task = _provider_image_task(image_product, "cover", angle, i, size=image_size, aspect_ratio=aspect_ratio, rewrite_suggestion=rewrite_suggestion, template_prompt=template_prompt, image_advice=image_advice, plan_item=plan_with_model, image_model=image_model)
            asset = store.create_asset(
                {
                    "product_id": product["id"],
                    "type": "cover",
                    "title": f"{product['name']} · 封面图 {i + 1}",
                    "status": "review",
                    "style": COVER_STYLES[i % len(COVER_STYLES)],
                    "variant_id": plan_variant.get("id", ""),
                    "variant_name": plan_variant.get("name", ""),
                    "source_image_url": plan_variant.get("image_url", ""),
                    "generation_plan": plan_with_model,
                    **image_task,
                }
            )
            cover_ids.append(asset["id"])
            created_assets.append(asset)

        if "detailimg" in asset_types:
            plan_item = plan_items[i % len(plan_items)] if plan_items else {}
            plan_variant = _selected_variant(product, plan_item.get("variantId") or plan_item.get("variant_id") or variant.get("id", ""))
            image_product = _product_for_variant(product, plan_variant.get("id", ""))
            plan_source_url = plan_item.get("sourceImageUrl") or plan_item.get("source_image_url") or source_image_url
            plan_reference_edit = _truthy(plan_item.get("referenceEditMode") or plan_item.get("reference_edit_mode")) or bool(plan_source_url and use_source_image_reference)
            plan_with_model = {
                **plan_item,
                "image_model": image_model,
                "image_model_profile": image_model_profile,
                "source_asset_id": plan_item.get("sourceAssetId") or plan_item.get("source_asset_id") or source_asset_id,
                "source_image_url": plan_source_url,
                "source_reference_url": plan_source_url,
                "reference_edit_mode": plan_reference_edit,
            }
            image_task = _provider_image_task(image_product, "detailimg", angle, i, size=image_size, aspect_ratio=aspect_ratio, rewrite_suggestion=rewrite_suggestion, template_prompt=template_prompt, image_advice=image_advice, plan_item=plan_with_model, image_model=image_model)
            asset = store.create_asset(
                {
                    "product_id": product["id"],
                    "type": "detailimg",
                    "title": f"{product['name']} · 详情图 {i + 1}",
                    "status": "review",
                    "style": DETAIL_STYLES[i % len(DETAIL_STYLES)],
                    "variant_id": plan_variant.get("id", ""),
                    "variant_name": plan_variant.get("name", ""),
                    "source_image_url": plan_variant.get("image_url", ""),
                    "generation_plan": plan_with_model,
                    **image_task,
                }
            )
            detail_ids.append(asset["id"])
            created_assets.append(asset)

        if "video" in asset_types:
            asset = store.create_asset(
                {
                    "product_id": product["id"],
                    "type": "video",
                    "title": f"{product['name']} · 口播脚本 {i + 1}",
                    "status": "review",
                    "content": (
                        f"[0-3s] 开场 hook：{_title(product, angle, i)}\n"
                        f"[3-20s] 展示使用场景：{product.get('scene') or '日常使用'}\n"
                        f"[20-45s] 展示卖点：{' / '.join(_points(product)[:3])}\n"
                        "[45-60s] 引导评论和领取链接。"
                        f"{chr(10) + '模板提示词：' + template_prompt if template_prompt else ''}"
                        f"{chr(10) + '重写建议：' + rewrite_suggestion if rewrite_suggestion else ''}"
                    ),
                    "variant_id": variant.get("id", ""),
                    "variant_name": variant.get("name", ""),
                    "source_image_url": variant.get("image_url", ""),
                }
            )
            video_ids.append(asset["id"])
            created_assets.append(asset)

        if mode == "all":
            note = store.create_note_package(
                {
                    "product_id": product["id"],
                    "title": _title(product, angle, i),
                    "angle": angle,
                    "persona": persona,
                    "status": "review",
                    "score": max(72, 96 - i * 2),
                    "copy_asset_id": copy_ids[-1] if copy_ids else "",
                    "cover_asset_id": cover_ids[-1] if cover_ids else "",
                    "detail_asset_ids": detail_ids[-1:] if detail_ids else [],
                    "video_asset_id": video_ids[-1] if video_ids else "",
                    "summary": (copy_content or f"{product['name']} · {angle}素材包")[:160],
                    "hashtags": [f"#{product.get('category') or '好物'}", f"#{product['name']}", "#小红书种草"],
                    "publish_plan": "待排期",
                    "goal": goal,
                }
            )
            created_notes.append(note)

    store.update_job(
        job_id,
        status="completed",
        progress=100,
        detail="生成完成，等待审核",
        result={
            "asset_ids": [x["id"] for x in created_assets],
            "note_package_ids": [x["id"] for x in created_notes],
        },
    )
