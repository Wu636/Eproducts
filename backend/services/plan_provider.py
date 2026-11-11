from __future__ import annotations

import json
import re

from config import settings
from services.http_client import post_json
from services.text_provider import (
    is_text_provider_configured,
    prepare_text_payload,
    text_provider_supports_images,
)


def _chat_url():
    return settings.text_api_base.rstrip("/") + "/chat/completions"


def _selected_variant(product, variant_id=""):
    variants = product.get("variants") or []
    selected_id = variant_id or product.get("selected_variant_id") or product.get("selectedVariantId") or ""
    if variants:
        return next((v for v in variants if v.get("id") == selected_id), variants[0])
    return {
        "id": "",
        "name": "默认款",
        "image_url": product.get("image_url") or product.get("imageUrl") or "",
        "notes": "",
    }


def _points(product):
    points = product.get("selling_points") or product.get("sellingPoints") or []
    if isinstance(points, str):
        points = [x.strip() for x in re.split(r"[\n;；、]", points) if x.strip()]
    return points


def _extract_json_object(text):
    raw = (text or "").strip()
    if not raw:
        raise ValueError("AI 没有返回方案内容")
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError("AI 返回的方案不是有效 JSON")


def _normalize_plan(item, index, variant, group_mood):
    if not isinstance(item, dict):
        item = {}
    prompt = item.get("prompt") or item.get("方案提示词") or ""
    scene = item.get("scene") or item.get("场景") or "生活化商品摆拍"
    light = item.get("light") or item.get("lighting") or item.get("光线") or "柔和自然光"
    composition = item.get("composition") or item.get("构图") or "主体清晰，留出标题区域"
    props = item.get("props") or item.get("道具") or "少量低成本生活道具"
    mood = item.get("mood") or item.get("氛围") or group_mood or "同组统一清透生活感"
    palette = item.get("palette") or item.get("色调") or "同组低饱和浅色调"
    if not prompt:
        prompt = (
            f"同组统一氛围：{mood}；统一色调：{palette}。\n"
            f"本张图方案：{scene}，{composition}，{light}，道具为{props}。\n"
            f"必须严格参考「{variant.get('name') or '默认款'}」产品图，保持产品颜色、形态、材质、装饰细节、比例一致，只变化背景、构图、光线和道具。"
        )
    return {
        "id": f"ai_plan_{index}",
        "index": index,
        "approved": True,
        "variantId": variant.get("id", ""),
        "variantName": variant.get("name") or "默认款",
        "mood": str(mood),
        "palette": str(palette),
        "scene": str(scene),
        "light": str(light),
        "composition": str(composition),
        "props": str(props),
        "prompt": str(prompt),
        "source": "ai",
    }


def _fallback_plans(product, config, count, variant, reason=""):
    scenes = [
        "手持实拍安利",
        "桌面生活化摆拍",
        "开箱细节展示",
        "使用场景近景",
        "礼物/囤货场景",
        "通勤包内/随身携带",
    ]
    points = "、".join(_points(product)[:3]) or product.get("category") or "核心卖点"
    mood = config.get("plan_brief") or config.get("planBrief") or "真实生活化带货感"
    palette = "自然光、低饱和、不过度精修"
    plans = []
    for index in range(count):
        scene = scenes[index % len(scenes)]
        item = {
            "scene": scene,
            "light": "柔和自然光，保留手机实拍质感",
            "composition": "商品主体清晰，占画面 55%-70%，侧边或顶部留短句区域",
            "props": "少量真实生活道具，不遮挡商品识别信息",
            "mood": mood,
            "palette": palette,
            "prompt": (
                f"小红书/抖音带货图，{scene}。严格参考「{variant.get('name') or '默认款'}」产品图，"
                "保持商品形态、颜色、材质、包装文字、比例和关键设计一致，不换品类不换款。"
                f"突出卖点：{points}。自然光，真实用户随手拍质感，背景生活化但干净，"
                "预留 2-3 行短句留白，商业信息清楚但不伪造平台截图、销量或订单。"
            ),
        }
        plan = _normalize_plan(item, index + 1, variant, mood)
        plan["source"] = "fallback"
        plans.append(plan)
    return {"plans": plans, "raw": {"source": "fallback", "warning": reason}}


def generate_image_plans(product, config):
    """Create preflight image-generation plans with the text model.

    This endpoint only designs prompts. It does not call the image provider or
    spend image credits. Image generation happens after the user approves plans.
    """

    count = max(1, min(int(config.get("count") or config.get("note_count") or 4), 12))
    variant = _selected_variant(product, config.get("variant_id") or config.get("variantId"))
    if not is_text_provider_configured():
        return _fallback_plans(product, config, count, variant, "Text provider is not configured")

    image_url = variant.get("image_url") or variant.get("imageUrl") or product.get("image_url") or product.get("imageUrl") or ""
    asset_type = config.get("type") or "cover"
    asset_label = "封面图" if asset_type == "cover" else "详情图"
    user_payload = {
        "任务": f"为小红书电商{asset_label}生成 {count} 张生图前的审核方案",
        "重要边界": [
            "只生成方案，不要生成图片，不要输出解释文字",
            "必须基于产品资料和当前款式产品图理解商品",
            "每张图都必须保持商品主体形态、颜色、材质、装饰细节、比例与参考图一致",
            "同一组图片要色调和氛围统一，但场景、构图、光线、道具要有差异，不能四张几乎一样",
            "不同款式由用户选择参考图，不能自行改变颜色深浅或款式细节",
        ],
        "输出格式": {
            "plans": [
                {
                    "scene": "场景",
                    "light": "光线",
                    "composition": "构图",
                    "props": "道具",
                    "mood": "同组氛围",
                    "palette": "同组色调",
                    "prompt": "完整生图提示词",
                }
            ]
        },
        "产品名称": product.get("name"),
        "类目": product.get("category"),
        "价格利益点": product.get("price"),
        "目标人群": product.get("audience"),
        "核心卖点": _points(product),
        "使用场景": product.get("scene"),
        "规格参数": product.get("spec"),
        "当前款式": variant.get("name") or "默认款",
        "款式备注": variant.get("notes") or "",
        "素材类型": asset_type,
        "尺寸": config.get("aspect_ratio") or config.get("aspectRatio") or "3:4",
        "选中的模板": config.get("template"),
        "模板提示词": config.get("template_prompt") or config.get("templatePrompt") or "",
        "用户生图建议": config.get("image_advice") or config.get("imageAdvice") or "",
        "方案偏好": config.get("plan_brief") or config.get("planBrief") or "",
        "重生成建议": config.get("plan_revision") or config.get("planRevision") or "",
        "上一组方案": config.get("previous_plans") or config.get("previousPlans") or [],
    }
    text_content = json.dumps(user_payload, ensure_ascii=False)
    content = text_content
    if text_provider_supports_images() and isinstance(image_url, str) and image_url.startswith(("data:image/", "http://", "https://")):
        content = [
            {"type": "text", "text": text_content},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

    payload = prepare_text_payload({
        "model": settings.text_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是电商视觉策划和小红书内容美术指导。"
                    "输出必须是一个 JSON 对象，且只输出 JSON。"
                    "不要让商品变形、换色、换品类或新增改变商品识别度的结构。"
                ),
            },
            {"role": "user", "content": content},
        ],
        "temperature": 0.95,
    }, json_output=True)
    headers = {
        settings.text_api_key_header: settings.text_api_key_prefix + settings.text_api_key,
        "Content-Type": "application/json",
    }
    try:
        data = post_json(_chat_url(), payload, headers, timeout=300, ssl_verify=settings.text_ssl_verify)
        text = data["choices"][0]["message"]["content"]
        parsed = _extract_json_object(text)
        plans = parsed.get("plans") or []
        if not isinstance(plans, list) or not plans:
            raise ValueError("AI 没有返回可用方案")
        group_mood = parsed.get("group_mood") or parsed.get("groupMood") or ""
        normalized = [_normalize_plan(item, index + 1, variant, group_mood) for index, item in enumerate(plans[:count])]
        while len(normalized) < count:
            normalized.append(_normalize_plan({}, len(normalized) + 1, variant, group_mood))
        return {"plans": normalized, "raw": parsed}
    except Exception as exc:
        return _fallback_plans(product, config, count, variant, str(exc))
