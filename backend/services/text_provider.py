from __future__ import annotations

import json

from config import settings
from services.http_client import post_json


class ProviderNotConfigured(RuntimeError):
    pass


def is_text_provider_configured():
    return bool(settings.text_api_base and settings.text_api_key and settings.text_model)


def is_deepseek_provider():
    return settings.text_provider.strip().lower() == "deepseek" or "api.deepseek.com" in settings.text_api_base.lower()


def is_mimo_provider():
    provider = settings.text_provider.strip().lower()
    api_base = settings.text_api_base.lower()
    return provider == "mimo" or "xiaomimimo.com" in api_base


def is_yunwu_provider():
    provider = settings.text_provider.strip().lower()
    api_base = settings.text_api_base.lower()
    return provider == "yunwu" or "yunwu.ai" in api_base


def text_provider_supports_images():
    # DeepSeek is text-only here. MiMo has separate text and multimodal model
    # names; only the all-modal `mimo-v2.5` should receive image_url content.
    if is_deepseek_provider():
        return False
    if is_yunwu_provider():
        return False
    if is_mimo_provider():
        return settings.text_model == "mimo-v2.5"
    return True


def prepare_text_payload(payload, *, json_output=False):
    prepared = dict(payload)
    if is_deepseek_provider():
        # Routine copy and planning do not need reasoning mode. Disabling it
        # keeps latency and token usage predictable and makes temperature work.
        prepared["thinking"] = {"type": "disabled"}
        if json_output:
            prepared["response_format"] = {"type": "json_object"}
    return prepared


def _chat_url():
    return settings.text_api_base.rstrip("/") + "/chat/completions"


def _image_url(product):
    selected_variant_id = product.get("selected_variant_id") or product.get("selectedVariantId") or ""
    variants = product.get("variants") or []
    if variants:
        selected = next((v for v in variants if v.get("id") == selected_variant_id), variants[0])
        url = selected.get("image_url") or selected.get("imageUrl") or ""
        if url.startswith("data:image/") or url.startswith("http://") or url.startswith("https://"):
            return url
    url = product.get("image_url") or product.get("imageUrl") or ""
    if url.startswith("data:image/") or url.startswith("http://") or url.startswith("https://"):
        return url
    return ""


def _variant_name(product):
    selected_variant_id = product.get("selected_variant_id") or product.get("selectedVariantId") or ""
    variants = product.get("variants") or []
    if variants:
        selected = next((v for v in variants if v.get("id") == selected_variant_id), variants[0])
        return selected.get("name", "")
    return ""


def _user_content(product, angle, persona, goal, word_range="", rewrite_suggestion="", template_prompt=""):
    has_vision = text_provider_supports_images() and bool(_image_url(product))
    user_prompt = {
        "任务": "基于产品图片和产品资料，生成一条小红书电商引流笔记文案" if has_vision else "基于产品资料，生成一条小红书电商引流笔记文案",
        "产品名称": product.get("name"),
        "类目": product.get("category"),
        "价格利益点": product.get("price"),
        "目标人群": product.get("audience"),
        "核心卖点": product.get("selling_points"),
        "使用场景": product.get("scene"),
        "规格参数": product.get("spec"),
        "禁用词": product.get("forbidden_words"),
        "当前款式": _variant_name(product),
        "内容角度": angle,
        "人设语气": persona,
        "发布目标": goal,
        "字数范围": word_range or "220-450字",
        "模板提示词": template_prompt,
        "重写建议": rewrite_suggestion,
        "事实要求": (
            [
                "先观察产品图，提取外观、颜色、材质、形态、风格、使用场景暗示",
                "只写图片中能看见或产品资料明确给出的信息",
                "如果图片和文字资料冲突，以图片可见事实优先，并避免编造",
            ]
            if has_vision
            else [
                "只使用产品资料中明确给出的信息",
                "没有提供的外观、材质、功效、规格或使用体验不得自行编造",
            ]
        ),
        "文案要求": [
            "标题感强，前 3 行有 hook",
            f"正文控制在 {word_range or '220-450字'}",
            "包含 4-6 个话题标签",
            "如果提供了重写建议，必须优先按建议调整内容方向、结构、语气或画面细节",
            "如果提供了模板提示词，必须优先按模板提示词的结构、风格和约束来写",
            "不要夸大效果，不要使用绝对化/医疗化/虚假承诺表达",
        ],
    }
    text_part = {
        "type": "text",
        "text": json.dumps(user_prompt, ensure_ascii=False),
    }
    image_url = _image_url(product)
    if not image_url or not text_provider_supports_images():
        return text_part["text"]
    return [
        text_part,
        {
            "type": "image_url",
            "image_url": {"url": image_url},
        },
    ]


def generate_copywriting(product, angle, persona, goal="引流成交", word_range="", rewrite_suggestion="", template_prompt=""):
    """Generate XHS copy through an OpenAI-compatible chat API.

    The adapter stays generic for OpenAI-compatible text providers. Providers
    without vision support receive the structured product data as plain text.
    """

    if not is_text_provider_configured():
        raise ProviderNotConfigured("Text provider is not configured")

    vision_instruction = (
        "你必须结合用户提供的产品图片进行理解，再组织文案。"
        if text_provider_supports_images()
        else "请严格根据用户提供的产品资料组织文案，不要假装看到了产品图片。"
    )
    system_prompt = (
        "你是小红书电商内容策划，擅长生成真实、克制、有转化力的种草笔记。"
        f"{vision_instruction}"
        "不要使用绝对化、医疗化、虚假承诺类表达。输出只包含正文。"
    )
    payload = prepare_text_payload({
        "model": settings.text_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _user_content(product, angle, persona, goal, word_range, rewrite_suggestion, template_prompt)},
        ],
        "temperature": 0.8,
    })
    key_header = settings.text_api_key_header
    key_value = settings.text_api_key_prefix + settings.text_api_key
    headers = {
        key_header: key_value,
        "Content-Type": "application/json",
    }
    data = post_json(
        _chat_url(),
        payload,
        headers,
        timeout=300,
        ssl_verify=settings.text_ssl_verify,
    )

    return data["choices"][0]["message"]["content"].strip()
