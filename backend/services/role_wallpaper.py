from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import mimetypes
import re
import ssl
from pathlib import Path
from threading import RLock
from time import sleep
from urllib import request

from config import settings
from services.http_client import post_json
from services.image_provider import ProviderNotConfigured as ImageProviderNotConfigured
from services.image_provider import create_image_task, wait_for_image_result
from services.text_provider import (
    ProviderNotConfigured as TextProviderNotConfigured,
    is_text_provider_configured,
    prepare_text_payload,
)


ROLE_WALLPAPER_ACCOUNT_ID = "account_role_wallpaper"
ROLE_WALLPAPER_ACCOUNT_NAME = "恋与深空角色壁纸号"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = BACKEND_ROOT / "data" / "role_wallpaper_catalog.json"
REFERENCE_ROOT = WORKSPACE_ROOT / "reference_library" / "role_wallpapers"
GENERATED_OUTPUT_ROOT = REFERENCE_ROOT / "outputs"
PERSISTED_ASSET_INDEX = GENERATED_OUTPUT_ROOT / "assets.json"
PERSISTED_ASSET_LOCK = RLock()

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
ROLE_REFERENCE_USAGES = ("complete", "identity", "outfit", "expression", "pose", "mood")
COMPLETE_REFERENCE_ALIASES = {"complete", "raw", "general", "full", "all", "综合", "完整", "原图"}
SCENE_REFERENCE_ROOT = "scenes"
DEFAULT_REFERENCE_LIMIT = 5
DEFAULT_COMPLETE_REFERENCE_LIMIT = 3
DEFAULT_REFERENCE_LIMIT_PER_USAGE = 2
MAX_MANUAL_REFERENCE_LIMIT = 6
REFERENCE_EXTRACTION_LABELS = {
    "character_identity": "人物身份/角色感",
    "face_shape": "脸型与五官比例",
    "hairstyle": "发型与发色",
    "outfit": "原服装细节、材质与配色",
}
DEFAULT_REFERENCE_EXTRACTION_OPTIONS = tuple(REFERENCE_EXTRACTION_LABELS.keys())


def ensure_role_wallpaper_account(store):
    account = store.get_product(ROLE_WALLPAPER_ACCOUNT_ID)
    if account:
        return account
    return store.create_product(
        {
            "id": ROLE_WALLPAPER_ACCOUNT_ID,
            "name": ROLE_WALLPAPER_ACCOUNT_NAME,
            "category": "AI 角色壁纸",
            "tone": "乙游角色氛围图 + 家居壁纸 + 小红书引流素材",
            "audience": "恋与深空玩家、乙游玩家、梦女向壁纸用户",
            "selling_points": ["五角色批量出图", "本地参考图资料库", "多套通用场景模板", "粉丝向风险标记"],
            "scene": "手机锁屏、小红书图文、社群限免、壁纸图包预览",
        }
    )


def _load_catalog():
    with CATALOG_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    data["roles"] = data.get("roles") or []
    data["templates"] = data.get("templates") or []
    return data


def _slug(value):
    return re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")


def _bounded_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _duration_label(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, remainder = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{remainder}秒"
    return f"{remainder}秒"


def _wallpaper_format_hint(aspect_ratio):
    raw = str(aspect_ratio or "9:16").strip()
    try:
        width_text, height_text = raw.split(":", 1)
        width = float(width_text)
        height = float(height_text)
        ratio = width / height if height else 0
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0
    if ratio > 1.08:
        return "横版平板或电脑桌面壁纸，主体与环境层次适配宽屏，保留图标区域"
    if 0.92 <= ratio <= 1.08:
        return "方形壁纸或社交平台配图，主体居中并保留呼吸感"
    return "竖版手机或平板壁纸，主体清晰，顶部保留锁屏留白"


def _rotated(items, offset):
    if not items:
        return []
    offset = offset % len(items)
    return [*items[offset:], *items[:offset]]


def _chat_url():
    return settings.text_api_base.rstrip("/") + "/chat/completions"


def _text_headers():
    return {
        settings.text_api_key_header: settings.text_api_key_prefix + settings.text_api_key,
        "Content-Type": "application/json",
    }


def _vision_chat_url():
    return settings.vision_api_base.rstrip("/") + "/chat/completions"


def _vision_headers():
    return {
        settings.vision_api_key_header: settings.vision_api_key_prefix + settings.vision_api_key,
        "Content-Type": "application/json",
    }


def _extract_json(text):
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.M).strip()
    for candidate in (
        raw,
        re.sub(r",\s*([}\]])", r"\1", raw),
    ):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw[start : end + 1]))
    raise ValueError("AI 返回的内容不是有效 JSON")


def _string_list(value, fallback=None, limit=4):
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif value:
        items = [part.strip() for part in re.split(r"[,，、\n]", str(value)) if part.strip()]
    else:
        items = []
    if not items and fallback:
        items = [str(item).strip() for item in fallback if str(item).strip()]
    return items[:limit]


def _reference_extraction_options(data):
    raw = (data or {}).get("extraction_options")
    if raw is None:
        raw = (data or {}).get("extractionOptions")
    if raw is None:
        return list(DEFAULT_REFERENCE_EXTRACTION_OPTIONS)
    if isinstance(raw, dict):
        selected = [key for key, enabled in raw.items() if enabled]
    elif isinstance(raw, str):
        selected = [part.strip() for part in re.split(r"[,，、\s]+", raw) if part.strip()]
    elif isinstance(raw, list):
        selected = [str(item).strip() for item in raw if str(item).strip()]
    else:
        selected = []
    return [item for item in selected if item in REFERENCE_EXTRACTION_LABELS]


def _extraction_label_text(options):
    return "、".join(REFERENCE_EXTRACTION_LABELS[item] for item in options if item in REFERENCE_EXTRACTION_LABELS)


def _ai_prompt_for(role, template, data, base_prompt, variant_index=1):
    if not is_text_provider_configured():
        raise TextProviderNotConfigured("Text provider is not configured")

    aspect_ratio = (data or {}).get("aspect_ratio") or (data or {}).get("aspectRatio") or "9:16"
    user_notes = (data or {}).get("user_notes") or (data or {}).get("userNotes") or ""
    series_style_anchor = str((data or {}).get("_series_style_anchor") or "").strip()
    series_inspiration = _series_inspiration_prompt(data or {})
    source_role = _inspiration_source_role(data or {})
    reference_scene_guard = _reference_scene_identity_guard(data or {}, role)
    plan_revision = _role_wallpaper_plan_revision(data)
    previous_prompts = _previous_prompts_for(
        data,
        role_id=role.get("id") or "",
        template_id=template.get("id") or "",
        is_group_photo=False,
    )
    reference_counts = _count_references_for_role(role["id"])
    reference_note = (
        f"本地会随正式出图附带角色参考图：complete {reference_counts.get('complete', 0)} 张，"
        f"总计 {reference_counts.get('total', 0)} 张；如果 complete 很多，系统默认稳定模式轮换抽 3 张。"
    )
    instruction = {
        "任务": "生成乙游角色壁纸的高质量 AI 生图 Prompt",
        "角色标识": {
            "id": role.get("id"),
            "cn_name": role.get("cn_name"),
            "en_name": role.get("en_name"),
        },
        "场景模板": template,
        "参考图统一场景 Prompt": series_inspiration,
        "参考图来源角色": (
            {"id": source_role.get("id"), "cn_name": source_role.get("cn_name"), "en_name": source_role.get("en_name")}
            if source_role
            else None
        ),
        "参考图人物净化规则": reference_scene_guard,
        "场景来源规则": (
            "本次必须以参考图统一场景 Prompt 为唯一场景来源，但只能抽取场景、构图、镜头、光影、色彩、环境材质、道具运动和氛围；不要套用通用场景模板，也不要继承来源人物身份"
            if series_inspiration
            else "使用所选通用场景模板"
        ),
        "画幅": aspect_ratio,
        "用户补充要求": user_notes,
        "用户重生成建议": plan_revision,
        "上一轮同角色同模板 Prompt": previous_prompts,
        "整组统一视觉锚点": series_style_anchor,
        "第几张变体": variant_index,
        "参考图策略": reference_note,
        "基础安全提示词": base_prompt,
        "输出要求": [
            "只输出 JSON，不要 Markdown，不要解释",
            "JSON 字段必须包含 title、hook、prompt、negative_prompt、xhs_hooks",
            "prompt 用中文，适合直接交给图像模型，画面描述要有镜头、构图、光影、材质、情绪和参考图约束",
            "必须强调：严格参考随任务附带的本地角色参考图；脸部、发型、眼睛、服装和身材比例跟随本次参考图变化，不要套用固定服装或固定眼神",
            "不要生成官方卡面复刻、游戏 logo、UI、卡面文字、水印",
            "不要过度裸露、色情化、血腥暴力；危险感用光影、姿态、距离感表达",
            "如果角色和模板气质冲突，可以让模板服务于角色，不要牺牲角色辨识度",
            "同一批次的所有角色必须共享整组统一视觉锚点，保持场景世界观、色板、光线方向、镜头语言和材质一致",
            "角色参考图只用于锁定脸、发型、体态与必要服装识别点；忽略参考图原本的背景、构图、动作、光线和色调，统一风格必须覆盖它们",
            "如果提供了参考图统一场景 Prompt，必须完全以它作为场景、构图、镜头、光影、色彩和道具来源，不要混入通用模板场景",
            "如果参考图统一场景 Prompt 中出现来源人物的脸、发型发色、瞳色、服装剪裁、胸肩装饰、身材、表情、姿态、角色姓名或角色气质，必须当作误提取删除，不能写入最终 prompt",
            "非来源角色尤其不能沿用来源角色外貌和服装；每个角色的服装识别点也以该角色本地参考图为准，只允许共享环境色板和氛围",
            "如果提供了上一轮 Prompt 或用户重生成建议，新 prompt 必须明显改变镜头、动作、空间层次、道具关系或光影方向，不能只是复述上一轮内容",
            "prompt 控制在 450-900 个中文字符，negative_prompt 控制在 80-180 个中文字符",
        ],
    }
    system_prompt = (
        "你是乙游角色壁纸与小红书 AI 视觉内容的生图提示词导演，"
        "擅长把角色资料、玩家情绪点、场景模板转成稳定可出图的 Prompt。"
        "你必须尊重参考图一致性，避免官方卡面复刻和平台敏感表达。"
    )
    payload = prepare_text_payload(
        {
            "model": settings.text_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)},
            ],
            "temperature": 0.75,
        },
        json_output=True,
    )
    response = post_json(
        _chat_url(),
        payload,
        _text_headers(),
        timeout=300,
        ssl_verify=settings.text_ssl_verify,
    )
    content = response["choices"][0]["message"]["content"].strip()
    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("AI 返回的 Prompt JSON 格式不正确")
    prompt = str(parsed.get("prompt") or parsed.get("生图提示词") or "").strip()
    negative = str(parsed.get("negative_prompt") or parsed.get("负向提示词") or "").strip()
    if not prompt:
        raise ValueError("AI 没有返回 prompt 字段")
    if negative and "负向" not in prompt and "不要" not in prompt[-120:]:
        prompt = f"{prompt}\n负向约束：{negative}"
    if reference_scene_guard and "参考图人物净化" not in prompt:
        prompt = f"{reference_scene_guard}\n{prompt}"
    return {
        "title": str(parsed.get("title") or parsed.get("标题") or "").strip(),
        "hook": str(parsed.get("hook") or parsed.get("summary") or parsed.get("卖点") or "").strip(),
        "prompt": prompt,
        "negative_prompt": negative,
        "xhs_hooks": _string_list(parsed.get("xhs_hooks") or parsed.get("小红书钩子"), template.get("xhs_hooks") or [], 4),
    }


def analyze_role_wallpaper_reference(data):
    """Turn one local inspiration image into an editable scene/style prompt.

    Scene/style are always extracted. Character identity, face, hair and outfit
    are extracted only when the user enables the corresponding options.
    """

    if not (settings.vision_api_base and settings.vision_api_key and settings.text_vision_model):
        raise TextProviderNotConfigured("云雾 API 令牌尚未配置")
    role = get_role_profile((data or {}).get("role_id") or (data or {}).get("roleId"))
    if not role:
        raise ValueError("请先选择角色")
    reference_id = str((data or {}).get("reference_id") or (data or {}).get("referenceId") or "").strip()
    if not reference_id:
        raise ValueError("请先选择一张场景灵感图")
    path = _path_from_reference_id(reference_id)
    reference = _reference_item(path)
    aspect_ratio = (data or {}).get("aspect_ratio") or (data or {}).get("aspectRatio") or "9:16"
    user_notes = str((data or {}).get("user_notes") or (data or {}).get("userNotes") or "").strip()
    extraction_options = _reference_extraction_options(data or {})
    scene_only = bool((data or {}).get("scene_only") or (data or {}).get("sceneOnly"))
    if scene_only:
        extraction_options = []
    extraction_text = _extraction_label_text(extraction_options) or "不提取参考图人物特征"
    instruction = {
        "任务": "解析参考图的可复用视觉语言，并改写成乙游角色壁纸生图 Prompt",
        "目标角色": {
            "id": role.get("id"),
            "cn_name": role.get("cn_name"),
            "en_name": role.get("en_name"),
        },
        "目标画幅": aspect_ratio,
        "用户补充": user_notes,
        "用户选择从参考图人物中提取": extraction_text,
        "分析原则": [
            "场景、构图、镜头、光影、色彩、材质、道具和情绪必须提取",
            "人物身份、脸型、发型、原服装细节只在用户选择的范围内提取",
            "不要套用固定角色描述；最终人物呈现应跟随本次选中的参考图和正式生图附带的本地角色参考图",
            "抽取风格 DNA，不要要求逐像素复刻原图",
        ],
        "输出要求": [
            "只输出 JSON，不要 Markdown 和解释",
            "JSON 必须包含 style_summary、style_dna、character_dna、reconstruction_prompt、negative_prompt、variation_axes",
            "style_dna 必须包含 scene、composition、camera、lighting、palette、materials、mood、props",
            "character_dna 只填写用户选择提取的人物特征；未选择的维度留空或省略",
            "reconstruction_prompt 用中文，450-900 个中文字符，可直接给生图模型",
            "variation_axes 给出 4-6 个后续可换场景或微动作方向",
        ],
    }
    payload = prepare_text_payload(
        {
            "model": settings.text_vision_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是乙游角色壁纸的视觉导演和多模态 Prompt 分析师。"
                        "你要把参考图拆成可复用的场景风格 DNA，同时严格隔离参考图人物身份。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(instruction, ensure_ascii=False)},
                        {"type": "image_url", "image_url": {"url": _file_to_data_url(path)}},
                    ],
                },
            ],
            "temperature": 0.55,
        },
        json_output=True,
    )
    response = post_json(
        _vision_chat_url(),
        payload,
        _vision_headers(),
        timeout=300,
        ssl_verify=settings.vision_ssl_verify,
    )
    parsed = _extract_json(response["choices"][0]["message"]["content"].strip())
    if not isinstance(parsed, dict):
        raise ValueError("多模态模型返回的分析格式不正确")
    reconstruction = str(parsed.get("reconstruction_prompt") or parsed.get("prompt") or "").strip()
    if not reconstruction:
        raise ValueError("多模态模型没有返回可编辑 Prompt")
    negative = str(parsed.get("negative_prompt") or "").strip()
    character_dna = parsed.get("character_dna") if isinstance(parsed.get("character_dna"), dict) else {}
    extraction_line = (
        f"本次允许从所选参考图提取人物维度：{extraction_text}；这些维度应随参考图变化，不要套用固定服装、固定眼神或固定姿态。"
        if extraction_options
        else "本次不从灵感图提取人物身份、脸型、发型或原服装，只复用场景、构图、光影和氛围。"
    )
    if scene_only:
        editable_prompt = (
            "五角色系列壁纸的统一场景风格；只提取参考图的场景、构图、镜头、光影、色板、材质、道具与氛围，"
            "完全忽略参考图人物的身份、脸、发型发色、瞳色、身材体态、服装剪裁、胸肩装饰、动作、表情、眼神和角色气质；"
            "如果下面的模型还写出了人物外貌或服装，请在生成系列时把它们视为误提取并忽略。\n"
            f"参考图场景与风格还原：{reconstruction}\n"
            f"单人图画幅：{aspect_ratio}，{_wallpaper_format_hint(aspect_ratio)}；同系列五人合照将横向重构为宽幅群像。"
        )
    else:
        editable_prompt = (
            f"粉丝向乙游角色壁纸，当前角色：{role['cn_name']} / {role['en_name']}。"
            "人物身份与细节以本次选择的本地参考图为准，避免固定模板化复刻。\n"
            f"{extraction_line}\n"
            f"参考图场景与风格还原：{reconstruction}\n"
            f"画幅：{aspect_ratio}，{_wallpaper_format_hint(aspect_ratio)}。"
        )
    if user_notes:
        editable_prompt += f"\n用户补充要求：{user_notes}"
    if negative:
        editable_prompt += f"\n负向约束：{negative}"
    style_dna = parsed.get("style_dna") if isinstance(parsed.get("style_dna"), dict) else {}
    return {
        "reference": reference,
        "role": role,
        "vision_model": settings.text_vision_model,
        "style_summary": str(parsed.get("style_summary") or "").strip(),
        "style_dna": style_dna,
        "character_dna": character_dna,
        "extraction_options": extraction_options,
        "extraction_labels": [REFERENCE_EXTRACTION_LABELS[item] for item in extraction_options],
        "variation_axes": _string_list(parsed.get("variation_axes"), [], 6),
        "negative_prompt": negative,
        "prompt": editable_prompt,
    }


def expand_role_wallpaper_reference_plans(data):
    """Expand an edited inspiration prompt into several reviewable plans."""

    if not is_text_provider_configured():
        raise TextProviderNotConfigured("云雾 API 令牌尚未配置")
    role = get_role_profile((data or {}).get("role_id") or (data or {}).get("roleId"))
    if not role:
        raise ValueError("请先选择角色")
    base_prompt = str((data or {}).get("prompt") or (data or {}).get("base_prompt") or "").strip()
    if not base_prompt:
        raise ValueError("请先解析参考图，并保留一版可编辑 Prompt")
    count = _bounded_int((data or {}).get("count"), 4, 1, 6)
    aspect_ratio = (data or {}).get("aspect_ratio") or (data or {}).get("aspectRatio") or "9:16"
    reference_id = str((data or {}).get("reference_id") or (data or {}).get("referenceId") or "").strip()
    extraction_options = _reference_extraction_options(data or {})
    image_model = (data or {}).get("image_model") or (data or {}).get("imageModel") or settings.image_model
    style_dna = (data or {}).get("style_dna") or (data or {}).get("styleDna") or {}
    variation_axes = _string_list((data or {}).get("variation_axes") or (data or {}).get("variationAxes"), [], 8)
    plan_revision = _role_wallpaper_plan_revision(data)
    previous_prompts = _previous_prompts_for(
        data,
        role_id=role.get("id") or "",
        template_id="reference_inspiration",
        is_group_photo=False,
    )
    selected_reference_ids = (data or {}).get("reference_ids") or (data or {}).get("referenceIds") or []
    if isinstance(selected_reference_ids, str):
        selected_reference_ids = [selected_reference_ids]
    selected_reference_ids = [str(item) for item in selected_reference_ids[:MAX_MANUAL_REFERENCE_LIMIT] if item]
    reference_counts = _count_references_for_role(role["id"])
    planned_reference_count = (
        len(selected_reference_ids)
        if selected_reference_ids
        else min(DEFAULT_COMPLETE_REFERENCE_LIMIT, reference_counts.get("complete", 0))
    )
    instruction = {
        "任务": f"基于用户已编辑的参考图风格 Prompt，生成 {count} 组同风格但不重复的角色壁纸方案",
        "目标角色": {
            "id": role.get("id"),
            "cn_name": role.get("cn_name"),
            "en_name": role.get("en_name"),
        },
        "用户编辑后的核心 Prompt": base_prompt,
        "用户重生成建议": plan_revision,
        "上一轮参考图扩展 Prompt": previous_prompts,
        "画幅": aspect_ratio,
        "变体数量": count,
        "已解析风格 DNA": style_dna if isinstance(style_dna, dict) else {},
        "可用变化方向": variation_axes,
        "人物提取选项": _extraction_label_text(extraction_options) or "不提取人物特征",
        "要求": [
            "保留核心构图、光影、配色、材质和情绪 DNA",
            "每组只改变一到两个维度：微动作、镜头距离、时间、天气、道具或空间层次",
            "不得把角色写成固定服装、固定眼神或固定姿态；人物细节应跟随本次选择的参考图",
            "每组 Prompt 都必须能看出明显差异，不能只是标题不同",
            "如果提供了上一轮 Prompt 或用户重生成建议，新方案必须避开上一轮镜头、动作、道具关系和空间层次",
            "只输出 JSON：{\"plans\":[{\"title\":\"\",\"hook\":\"\",\"variant_axis\":\"\",\"prompt\":\"\",\"negative_prompt\":\"\",\"xhs_hooks\":[\"\"]}]} ",
            f"plans 必须恰好 {count} 组",
        ],
    }
    payload = prepare_text_payload(
        {
            "model": settings.text_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是乙游角色壁纸的系列化视觉导演，擅长从一张风格参考扩展稳定且有区分度的组图。",
                },
                {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)},
            ],
            "temperature": 0.78,
        },
        json_output=True,
    )
    response = post_json(
        _chat_url(),
        payload,
        _text_headers(),
        timeout=300,
        ssl_verify=settings.text_ssl_verify,
    )
    parsed = _extract_json(response["choices"][0]["message"]["content"].strip())
    raw_plans = parsed.get("plans") if isinstance(parsed, dict) else None
    if not isinstance(raw_plans, list) or not raw_plans:
        raise ValueError("AI 没有返回可用的系列方案")
    seed = hashlib.sha1(f"{reference_id}:{role['id']}:{base_prompt}".encode("utf-8")).hexdigest()[:10]
    fallback_axes = variation_axes or [
        "近景半身，眼神与道具互动",
        "中景留白，窗光与环境层次增强",
        "低机位仰视，压迫感和空间纵深增强",
        "侧脸回眸，背景虚化与轮廓光增强",
        "坐姿/倚靠，手部动作和服装材质特写",
        "远景构图，人物与场景比例更像壁纸",
    ]
    prompt_keys = set()
    plans = []
    for index, raw_plan in enumerate(raw_plans[:count], start=1):
        if not isinstance(raw_plan, dict):
            continue
        prompt = str(raw_plan.get("prompt") or "").strip()
        if not prompt:
            continue
        negative = str(raw_plan.get("negative_prompt") or "").strip()
        variant_axis = str(raw_plan.get("variant_axis") or raw_plan.get("axis") or "").strip()
        if not variant_axis:
            variant_axis = fallback_axes[(index - 1) % len(fallback_axes)]
        prompt_key = re.sub(r"\s+", "", prompt)[:180]
        if prompt_key in prompt_keys or variant_axis not in prompt:
            prompt += f"\n本组差异化方向：{variant_axis}。请确保这张与同系列其他图在动作、镜头或空间层次上明显不同。"
            prompt_key = re.sub(r"\s+", "", prompt)[:180]
        regeneration_direction = _regeneration_direction(
            data,
            role,
            {"id": "reference_inspiration", "name": "参考图风格扩展"},
            variant_index=index,
        )
        if regeneration_direction and "重新生成变化指令" not in prompt:
            prompt += f"\n{regeneration_direction}"
        prompt_keys.add(prompt_key)
        if negative and "负向" not in prompt and "不要" not in prompt[-160:]:
            prompt += f"\n负向约束：{negative}"
        plan = {
            "id": f"role_inspiration_{_slug(role['id'])}_{seed}_{index}",
            "index": index,
            "approved": True,
            "role_id": role["id"],
            "role_name": role["cn_name"],
            "role_en_name": role["en_name"],
            "template_id": "reference_inspiration",
            "template_name": "参考图风格扩展",
            "variant_index": index,
            "aspect_ratio": aspect_ratio,
            "image_model": image_model,
            "image_model_profile": settings.image_model_profile(image_model),
            "reference_types": ["complete", "identity", "outfit", "expression", "pose"],
            "reference_strategy": {
                "mode": "manual" if selected_reference_ids else "complete_pool_rotation",
                "selected_count": len(selected_reference_ids),
                "planned_reference_count": planned_reference_count,
                "reference_limit": len(selected_reference_ids) if selected_reference_ids else DEFAULT_REFERENCE_LIMIT,
                "complete_reference_limit": (
                    len(selected_reference_ids) if selected_reference_ids else DEFAULT_COMPLETE_REFERENCE_LIMIT
                ),
                "reference_limit_per_usage": DEFAULT_REFERENCE_LIMIT_PER_USAGE,
                "note": "场景灵感图只用于 Prompt 分析；正式出图使用独立角色参考图锁定身份。",
            },
            "reference_counts": reference_counts,
            "reference_ids": selected_reference_ids,
            "inspiration_reference_id": reference_id,
            "risk_level": role.get("risk_profile", {}).get("default") or "high_ip_risk",
            "recommended_public_label": role.get("risk_profile", {}).get("recommended_public_label") or "粉丝向二创展示",
            "commercial_note": role.get("risk_profile", {}).get("commercial_note") or "",
            "title": str(raw_plan.get("title") or f"{role['cn_name']} · 参考风格 {index}").strip(),
            "hook": str(raw_plan.get("hook") or "").strip(),
            "variant_axis": variant_axis,
            "prompt": prompt,
            "negative_prompt": negative,
            "xhs_hooks": _string_list(raw_plan.get("xhs_hooks"), [], 4),
            "prompt_source": "ai_reference_expansion",
            "source": "ai_vision",
            "extraction_options": extraction_options,
        }
        plans.append(plan)
    if not plans:
        raise ValueError("AI 返回的方案缺少 Prompt")
    return {"plans": plans, "source": "ai_vision", "vision_model": settings.text_vision_model}


def apply_role_wallpaper_reference_style_to_roles(data):
    """Reuse one analyzed scene/style DNA while locking every target to its own role references."""

    catalog = _load_catalog()
    source_role = get_role_profile((data or {}).get("role_id") or (data or {}).get("roleId"))
    if not source_role:
        raise ValueError("请先选择提供场景灵感图的角色")
    raw_target_ids = (data or {}).get("target_role_ids") or (data or {}).get("targetRoleIds") or []
    if isinstance(raw_target_ids, str):
        raw_target_ids = [raw_target_ids]
    lookup = _role_lookup(catalog)
    targets = []
    for role_id in raw_target_ids:
        role = lookup.get(str(role_id or "").strip().lower())
        if role and role not in targets:
            targets.append(role)
    if not targets:
        targets = list(catalog["roles"])
    targets = targets[:5]
    base_prompt = str((data or {}).get("prompt") or (data or {}).get("base_prompt") or "").strip()
    if not base_prompt:
        raise ValueError("请先用多模态模型拆解参考图")
    aspect_ratio = (data or {}).get("aspect_ratio") or (data or {}).get("aspectRatio") or "9:16"
    reference_id = str((data or {}).get("reference_id") or (data or {}).get("referenceId") or "").strip()
    style_dna = (data or {}).get("style_dna") or (data or {}).get("styleDna") or {}
    scene_style_text = "；".join(
        f"{key}：{'、'.join(str(item) for item in value) if isinstance(value, list) else value}"
        for key, value in (style_dna.items() if isinstance(style_dna, dict) else [])
        if value
    ) or base_prompt
    image_model = (data or {}).get("image_model") or (data or {}).get("imageModel") or settings.image_model
    plan_revision = _role_wallpaper_plan_revision(data)
    previous_prompts = _previous_prompts_for(
        data,
        role_id="",
        template_id="cross_role_reference_style",
        is_group_photo=False,
        limit=5,
    )
    source_reference_ids = (data or {}).get("reference_ids") or (data or {}).get("referenceIds") or []
    if isinstance(source_reference_ids, str):
        source_reference_ids = [source_reference_ids]
    source_reference_ids = [str(item) for item in source_reference_ids[:MAX_MANUAL_REFERENCE_LIMIT] if item]
    instruction = {
        "任务": "把一张参考图中已提取的场景与视觉风格分别套用到多个目标乙游角色",
        "风格来源角色": {"id": source_role["id"], "name": source_role["cn_name"]},
        "目标角色": [
            {"id": role["id"], "cn_name": role["cn_name"], "en_name": role["en_name"]} for role in targets
        ],
        "参考图反推的可编辑 Prompt": base_prompt,
        "用户重生成建议": plan_revision,
        "上一轮跨角色 Prompt": previous_prompts,
        "场景风格 DNA": style_dna if isinstance(style_dna, dict) else {},
        "画幅": aspect_ratio,
        "身份隔离规则": [
            "只迁移场景、构图、镜头、光影、色板、材质、道具与氛围，不迁移来源人物的脸、发型、身材、服装或身份",
            "每个目标角色的脸、发型、眼睛、体态、气质和服装只读取正式出图时附带的该角色本地参考图",
            "不得沿用来源角色姓名或来源人物外貌；不得角色串脸、串发色",
            "所有图共享同一风格 DNA，但允许按角色气质微调姿态和局部色彩权重",
        ],
        "输出要求": [
            "只输出 JSON，根字段 plans；每项包含 role_id、title、hook、prompt、negative_prompt、variant_axis、xhs_hooks",
            f"plans 必须恰好 {len(targets)} 组，每个目标角色一组",
            "每组 Prompt 用中文，明确目标角色与身份参考隔离要求，可直接交给图像模型",
            "如果提供了上一轮 Prompt 或用户重生成建议，新方案必须明显改变镜头、姿态、空间层次、道具关系或光影方向",
        ],
    }
    raw_by_role = {}
    ai_error = ""
    try:
        if (data or {}).get("use_ai_prompt") is False or (data or {}).get("useAiPrompt") is False:
            raise TextProviderNotConfigured("AI Prompt generation disabled for this request")
        if not is_text_provider_configured():
            raise TextProviderNotConfigured("云雾 API 令牌尚未配置")
        payload = prepare_text_payload(
            {
                "model": settings.text_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是系列角色视觉导演，擅长只迁移场景风格，同时严格隔离不同人物身份。",
                    },
                    {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)},
                ],
                "temperature": 0.62,
            },
            json_output=True,
        )
        response = post_json(_chat_url(), payload, _text_headers(), timeout=300, ssl_verify=settings.text_ssl_verify)
        parsed = _extract_json(response["choices"][0]["message"]["content"].strip())
        for raw_plan in (parsed.get("plans") if isinstance(parsed, dict) else []) or []:
            if isinstance(raw_plan, dict):
                role_id = str(raw_plan.get("role_id") or raw_plan.get("roleId") or "").strip().lower()
                if role_id:
                    raw_by_role[role_id] = raw_plan
    except Exception as exc:
        ai_error = str(exc)

    seed = hashlib.sha1(f"cross:{reference_id}:{base_prompt}".encode("utf-8")).hexdigest()[:10]
    plans = []
    for index, role in enumerate(targets, start=1):
        raw_plan = raw_by_role.get(role["id"], {})
        prompt = str(raw_plan.get("prompt") or "").strip()
        if role["id"] != source_role["id"] and prompt:
            prompt = prompt.replace(source_role["cn_name"], "来源人物").replace(source_role["en_name"], "来源人物")
        if not prompt:
            prompt = (
                f"粉丝向乙游角色壁纸，目标角色：{role['cn_name']} / {role['en_name']}。"
                "人物身份、脸型五官、发型发色、眼睛、体态比例、气质与服装只以正式出图时附带的该角色本地参考图为准；"
                "不要继承场景来源人物的任何外貌。\n"
                f"仅复用以下参考图场景视觉语言：{scene_style_text}\n"
                f"目标画幅：{aspect_ratio}，{_wallpaper_format_hint(aspect_ratio)}。"
                "保持同系列场景、构图、镜头、光影、色板、材质、道具和氛围一致；严禁串脸、串发色、复制来源人物。"
            )
        regeneration_direction = _regeneration_direction(
            data,
            role,
            {"id": "cross_role_reference_style", "name": "参考图场景跨角色套用"},
            variant_index=index,
        )
        if regeneration_direction and "重新生成变化指令" not in prompt:
            prompt += f"\n{regeneration_direction}"
        negative = str(raw_plan.get("negative_prompt") or "").strip()
        if negative and "负向" not in prompt and "不要" not in prompt[-180:]:
            prompt += f"\n负向约束：{negative}"
        reference_counts = _count_references_for_role(role["id"])
        explicit_ids = source_reference_ids if role["id"] == source_role["id"] else []
        planned_count = len(explicit_ids) or min(DEFAULT_COMPLETE_REFERENCE_LIMIT, reference_counts.get("complete", 0))
        plans.append(
            {
                "id": f"role_cross_style_{_slug(role['id'])}_{seed}_{index}",
                "index": index,
                "approved": True,
                "role_id": role["id"],
                "role_name": role["cn_name"],
                "role_en_name": role["en_name"],
                "template_id": "cross_role_reference_style",
                "template_name": "参考图场景跨角色套用",
                "variant_index": index,
                "aspect_ratio": aspect_ratio,
                "image_model": image_model,
                "image_model_profile": settings.image_model_profile(image_model),
                "reference_types": ["complete", "identity", "outfit", "expression", "pose"],
                "reference_ids": explicit_ids,
                "reference_strategy": {
                    "mode": "manual" if explicit_ids else "complete_pool_rotation",
                    "selected_count": len(explicit_ids),
                    "planned_reference_count": planned_count,
                    "reference_limit": len(explicit_ids) or DEFAULT_REFERENCE_LIMIT,
                    "complete_reference_limit": len(explicit_ids) or DEFAULT_COMPLETE_REFERENCE_LIMIT,
                    "reference_limit_per_usage": DEFAULT_REFERENCE_LIMIT_PER_USAGE,
                    "note": "灵感图只迁移场景风格；正式出图改用目标角色自己的本地参考图锁定身份。",
                },
                "reference_counts": reference_counts,
                "inspiration_reference_id": reference_id,
                "style_source_role_id": source_role["id"],
                "cross_role_style": True,
                "risk_level": role.get("risk_profile", {}).get("default") or "high_ip_risk",
                "recommended_public_label": role.get("risk_profile", {}).get("recommended_public_label") or "粉丝向二创展示",
                "commercial_note": role.get("risk_profile", {}).get("commercial_note") or "",
                "title": str(raw_plan.get("title") or f"{role['cn_name']} · 同场景风格").strip(),
                "hook": str(raw_plan.get("hook") or "").strip(),
                "variant_axis": str(raw_plan.get("variant_axis") or "角色气质适配，场景风格保持不变").strip(),
                "prompt": prompt,
                "negative_prompt": negative,
                "xhs_hooks": _string_list(raw_plan.get("xhs_hooks"), [], 4),
                "prompt_source": "ai_cross_role_style" if raw_plan else "cross_role_fallback",
                "ai_prompt_error": ai_error if not raw_plan else "",
                "source": "ai" if raw_plan else "catalog",
            }
        )
    return {"plans": plans, "source": "ai" if raw_by_role else "fallback", "warning": ai_error}


def _safe_output_filename(label, fallback="role-wallpaper"):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label or fallback)).strip(".-")
    return name or fallback


def _cache_generated_image_url(url, label):
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return "", {}
    context = None
    if not settings.image_ssl_verify:
        context = ssl._create_unverified_context()
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=120, context=context) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";")[0]
        raw = response.read()
    if not content_type.startswith("image/"):
        raise ValueError(f"生成结果不是图片：{content_type}")
    extension = mimetypes.guess_extension(content_type) or Path(url).suffix or ".png"
    if extension == ".jpe":
        extension = ".jpg"
    output_dir = GENERATED_OUTPUT_ROOT / "cached"
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    filename = f"{_safe_output_filename(label)}-{digest}{extension}"
    path = output_dir / filename
    path.write_bytes(raw)
    relative = str(path.relative_to(WORKSPACE_ROOT))
    return relative, {
        "original_url": url,
        "cached_url": relative,
        "content_type": content_type,
        "bytes": len(raw),
    }


def _load_persisted_assets():
    if not PERSISTED_ASSET_INDEX.exists():
        return []
    try:
        data = json.loads(PERSISTED_ASSET_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("id")]


def _write_persisted_assets(items):
    PERSISTED_ASSET_INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PERSISTED_ASSET_INDEX.with_suffix(PERSISTED_ASSET_INDEX.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(PERSISTED_ASSET_INDEX)


def _persist_role_wallpaper_asset(asset):
    if not asset or not asset.get("id"):
        return
    with PERSISTED_ASSET_LOCK:
        items = [item for item in _load_persisted_assets() if item.get("id") != asset.get("id")]
        items.insert(0, asset)
        _write_persisted_assets(items[:500])


def _delete_persisted_role_wallpaper_asset(asset_id):
    with PERSISTED_ASSET_LOCK:
        items = _load_persisted_assets()
        deleted = next((item for item in items if item.get("id") == asset_id), None)
        if not deleted:
            return None
        _write_persisted_assets([item for item in items if item.get("id") != asset_id])
        return deleted


def _merge_asset_lists(*asset_lists):
    merged = []
    for assets in asset_lists:
        for asset in assets or []:
            if not asset or not asset.get("id"):
                continue
            index = next((i for i, item in enumerate(merged) if item.get("id") == asset.get("id")), -1)
            if index >= 0:
                merged[index] = {**merged[index], **asset}
            else:
                merged.append(asset)
    return sorted(merged, key=lambda item: item.get("created_at") or "", reverse=True)


def _role_lookup(catalog):
    lookup = {}
    for role in catalog["roles"]:
        keys = [role.get("id"), role.get("cn_name"), role.get("en_name"), *(role.get("aliases") or [])]
        for key in keys:
            if key:
                lookup[str(key).strip().lower()] = role
    return lookup


def _template_lookup(catalog):
    lookup = {}
    for template in catalog["templates"]:
        keys = [template.get("id"), template.get("name"), *(template.get("tags") or [])]
        for key in keys:
            if key:
                lookup[str(key).strip().lower()] = template
    return lookup


def list_role_profiles():
    catalog = _load_catalog()
    return {
        "items": catalog["roles"],
        "version": catalog.get("version", ""),
        "ip_notice": catalog.get("ip_notice", ""),
        "reference_root": str(REFERENCE_ROOT.relative_to(WORKSPACE_ROOT)),
    }


def list_wallpaper_templates():
    catalog = _load_catalog()
    return {"items": catalog["templates"], "version": catalog.get("version", "")}


def get_role_profile(role_id):
    catalog = _load_catalog()
    return _role_lookup(catalog).get(str(role_id or "").strip().lower())


def get_wallpaper_template(template_id):
    catalog = _load_catalog()
    return _template_lookup(catalog).get(str(template_id or "").strip().lower())


def _safe_reference_id(path):
    rel = path.resolve().relative_to(REFERENCE_ROOT.resolve())
    encoded = base64.urlsafe_b64encode(str(rel).encode("utf-8")).decode("ascii").rstrip("=")
    return encoded


def _path_from_reference_id(reference_id):
    padding = "=" * (-len(reference_id) % 4)
    try:
        rel = base64.urlsafe_b64decode((reference_id + padding).encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Invalid reference id") from exc
    path = (REFERENCE_ROOT / rel).resolve()
    root = REFERENCE_ROOT.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Reference path is outside library") from exc
    if not path.exists() or not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise FileNotFoundError("Reference image not found")
    return path


def _reference_item(path):
    rel = path.resolve().relative_to(REFERENCE_ROOT.resolve())
    parts = rel.parts
    item = {
        "id": _safe_reference_id(path),
        "filename": path.name,
        "relative_path": str(rel),
        "file_url": f"/api/role-wallpaper/references/{_safe_reference_id(path)}/file",
        "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "size": path.stat().st_size,
        "risk_level": "high_ip_risk",
    }
    if len(parts) >= 3 and parts[0] == "roles":
        usage = "complete"
        bucket = ""
        if len(parts) >= 4:
            bucket = str(parts[2])
            usage = "complete" if bucket in COMPLETE_REFERENCE_ALIASES or bucket not in ROLE_REFERENCE_USAGES else bucket
        item.update({"scope": "role", "role_id": parts[1], "usage": usage, "bucket": bucket})
    elif len(parts) >= 3 and parts[0] == SCENE_REFERENCE_ROOT:
        item.update({"scope": "scene", "template_id": parts[1], "usage": "scene"})
    else:
        item.update({"scope": "misc", "usage": "misc"})
    return item


def list_reference_images(role_id="", usage="", template_id=""):
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(REFERENCE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        rel_parts = path.resolve().relative_to(REFERENCE_ROOT.resolve()).parts
        if rel_parts and rel_parts[0] == "outputs":
            continue
        item = _reference_item(path)
        if role_id and item.get("role_id") != role_id:
            continue
        if usage and item.get("usage") != usage:
            continue
        if template_id and item.get("template_id") != template_id:
            continue
        files.append(item)
    return {
        "items": files,
        "reference_root": str(REFERENCE_ROOT.relative_to(WORKSPACE_ROOT)),
        "accepted_extensions": sorted(IMAGE_EXTENSIONS),
        "role_reference_usages": list(ROLE_REFERENCE_USAGES),
    }


def get_reference_file(reference_id):
    path = _path_from_reference_id(reference_id)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.read_bytes(), content_type, path.name


def _file_to_data_url(path, max_bytes=8 * 1024 * 1024):
    if path.stat().st_size > max_bytes:
        raise ValueError(f"参考图超过 {max_bytes // 1024 // 1024}MB：{path.name}")
    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _selected_roles(data, catalog):
    raw = data.get("role_ids") or data.get("roles") or data.get("role_id") or data.get("role")
    if raw in (None, "", "all", ["all"]):
        return catalog["roles"]
    if isinstance(raw, str):
        raw = [raw]
    lookup = _role_lookup(catalog)
    roles = []
    for item in raw or []:
        role = lookup.get(str(item).strip().lower())
        if role and role not in roles:
            roles.append(role)
    return roles or catalog["roles"]


def _series_inspiration_prompt(data):
    return str(
        (data or {}).get("series_inspiration_prompt")
        or (data or {}).get("seriesInspirationPrompt")
        or ""
    ).strip()


SCENE_STYLE_DNA_KEYS = ("scene", "composition", "camera", "lighting", "palette", "materials", "mood", "props")
SOURCE_IDENTITY_PROMPT_TERMS = (
    "人物",
    "角色",
    "身份",
    "脸",
    "五官",
    "眉",
    "眼",
    "瞳",
    "发型",
    "发色",
    "头发",
    "白发",
    "银发",
    "红眼",
    "红瞳",
    "身材",
    "体态",
    "肩",
    "胸",
    "服装",
    "衣服",
    "礼服",
    "西装",
    "外套",
    "制服",
    "领口",
    "表情",
    "眼神",
    "姿态",
    "气质",
)


def _inspiration_source_role(data):
    role_id = str(
        (data or {}).get("inspiration_source_role_id")
        or (data or {}).get("inspirationSourceRoleId")
        or (data or {}).get("style_source_role_id")
        or (data or {}).get("styleSourceRoleId")
        or ""
    ).strip()
    reference_id = str(
        (data or {}).get("inspiration_reference_id")
        or (data or {}).get("inspirationReferenceId")
        or ""
    ).strip()
    if not role_id and reference_id:
        try:
            reference = _reference_item(_path_from_reference_id(reference_id))
            role_id = str(reference.get("role_id") or "").strip()
        except Exception:
            role_id = ""
    return get_role_profile(role_id) if role_id else None


def _scene_style_dna_text(data):
    style_dna = (data or {}).get("style_dna") or (data or {}).get("styleDna") or {}
    if not isinstance(style_dna, dict):
        return ""
    source_role = _inspiration_source_role(data or {})
    source_names = {
        str(source_role.get("cn_name") or "").strip().lower() if source_role else "",
        str(source_role.get("en_name") or "").strip().lower() if source_role else "",
        str(source_role.get("id") or "").strip().lower() if source_role else "",
    }
    source_names.discard("")

    def clean_piece(piece):
        text = str(piece or "").strip()
        lower = text.lower()
        if not text:
            return ""
        if any(name and name in lower for name in source_names):
            return ""
        if any(term in text for term in SOURCE_IDENTITY_PROMPT_TERMS):
            return ""
        return text

    parts = []
    for key in SCENE_STYLE_DNA_KEYS:
        value = style_dna.get(key)
        if not value:
            continue
        text = "、".join(item for item in (clean_piece(item) for item in value) if item) if isinstance(value, list) else clean_piece(value)
        if text.strip():
            parts.append(f"{key}：{text.strip()}")
    return "；".join(parts)


def _compact_scene_only_prompt_text(prompt, source_role=None, max_chars=420):
    """Keep only scene-like clauses from a user-edited inspiration prompt.

    The source image can contain a character. For five-role transfer this text
    must not be passed verbatim to image generation, otherwise the image model
    tends to copy the source character's face/clothes into every target role.
    """

    raw = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if not raw:
        return ""
    source_names = {
        str(source_role.get("cn_name") or "").strip().lower() if source_role else "",
        str(source_role.get("en_name") or "").strip().lower() if source_role else "",
        str(source_role.get("id") or "").strip().lower() if source_role else "",
    }
    source_names.discard("")
    candidates = [part.strip() for part in re.split(r"[。；;!\n]", raw) if part.strip()]
    kept = []
    for part in candidates:
        lower = part.lower()
        if any(name and name in lower for name in source_names):
            continue
        if any(term in part for term in SOURCE_IDENTITY_PROMPT_TERMS):
            continue
        kept.append(part)
        if len("；".join(kept)) >= max_chars:
            break
    compact = "；".join(kept).strip("； ")
    if not compact:
        compact = "用户审核原文包含人物/服装信息，最终生图阶段已省略原文；只按场景、构图、镜头、光影、色彩、环境材质、道具运动和氛围理解。"
    return compact[:max_chars]


def _reference_scene_identity_guard(data, target_role=None, group=False):
    if not _series_inspiration_prompt(data or {}):
        return ""
    source_role = _inspiration_source_role(data or {})
    source_label = ""
    if source_role:
        source_label = f"场景灵感图来源角色：{source_role.get('cn_name')} / {source_role.get('en_name')}。"
    target_label = ""
    if target_role and not group:
        target_label = f"本张目标角色：{target_role.get('cn_name')} / {target_role.get('en_name')}。"
    target_rule = (
        "五位角色的脸部辨识点、发型发色、瞳色、体态比例、服装识别点与角色气质，必须分别只读取各自对应的角色参考图。"
        if group
        else "目标角色的脸部辨识点、发型发色、瞳色、体态比例、服装识别点与角色气质，必须只读取目标角色本地参考图。"
    )
    return (
        f"【参考图人物净化】{source_label}{target_label}"
        "参考图统一场景 Prompt 只允许提供场景、构图、镜头、光影方向、色板、环境材质、空间层次、道具运动与整体氛围；"
        "严禁继承灵感图中来源人物的脸、五官、发型发色、瞳色、身材体态、表情眼神、姿态、服装剪裁、胸肩装饰、角色姓名或角色气质。"
        f"{target_rule}"
        "如果统一场景 Prompt 中出现任何人物外貌或服装描述，把它们视为误提取并忽略；只保留环境与视觉语言。"
    )


def _reference_unified_scene_template(data=None):
    return {
        "id": "reference_unified_scene",
        "name": "参考图统一场景",
        "scene": "完全以用户审核后的参考图反推 Prompt 为准，不套用通用场景模板",
        "composition": "只沿用参考图 Prompt 的构图、镜头距离、前后景层次与留白方式，不沿用来源人物身份",
        "lighting": "只沿用参考图 Prompt 的光影方向、色彩关系、环境材质质感与时间氛围",
        "mood": "沿用参考图 Prompt 的整体情绪和视觉风格",
        "props": ["参考图 Prompt 中已出现的核心场景元素，不包含来源人物服装装饰"],
        "negative": ["不要套用通用场景模板", "不要继承灵感图来源人物的脸、发型、服装或气质", "不要混入与参考图 Prompt 冲突的背景、道具或光影"],
        "xhs_hooks": ["同一张参考图风格统一", "角色参考图只锁身份", "不套用通用场景模板"],
    }


def _selected_templates(data, catalog):
    if _series_inspiration_prompt(data or {}):
        return [_reference_unified_scene_template(data)]
    raw = data.get("template_ids") or data.get("templates") or data.get("template_id") or data.get("template")
    if raw in (None, "", "all", ["all"]):
        default_id = data.get("default_template_id") or "bedroom_morning"
        raw = [default_id]
    if isinstance(raw, str):
        raw = [raw]
    lookup = _template_lookup(catalog)
    templates = []
    for item in raw or []:
        template = lookup.get(str(item).strip().lower())
        if template and template not in templates:
            templates.append(template)
    return templates or catalog["templates"][:1]


def _count_references_for_role(role_id):
    counts = {}
    for usage in ROLE_REFERENCE_USAGES:
        counts[usage] = len(list_reference_images(role_id=role_id, usage=usage)["items"])
    counts["total"] = len(list_reference_images(role_id=role_id)["items"])
    return counts


def _role_wallpaper_plan_revision(data):
    return str(
        (data or {}).get("plan_revision")
        or (data or {}).get("planRevision")
        or (data or {}).get("regenerate_notes")
        or (data or {}).get("regenerateNotes")
        or ""
    ).strip()


def _compact_previous_prompt(prompt, limit=260):
    text = re.sub(r"\s+", " ", str(prompt or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _previous_role_wallpaper_plans(data):
    raw = (data or {}).get("previous_plans") or (data or {}).get("previousPlans") or []
    if not isinstance(raw, list):
        return []
    plans = []
    for item in raw[:80]:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or item.get("content") or "").strip()
        if not prompt:
            continue
        plans.append(
            {
                "role_id": str(item.get("role_id") or item.get("roleId") or ""),
                "template_id": str(item.get("template_id") or item.get("templateId") or ""),
                "variant_index": item.get("variant_index") or item.get("variantIndex") or item.get("index") or "",
                "is_group_photo": bool(item.get("is_group_photo") or item.get("isGroupPhoto")),
                "prompt": prompt,
            }
        )
    return plans


def _previous_prompts_for(data, role_id="", template_id="", is_group_photo=False, limit=3):
    plans = _previous_role_wallpaper_plans(data)
    if not plans:
        return []
    filtered = []
    for plan in plans:
        same_group = is_group_photo and (plan.get("is_group_photo") or plan.get("role_id") == "group_all")
        same_role = not is_group_photo and (not role_id or plan.get("role_id") == role_id)
        same_template = not template_id or plan.get("template_id") == template_id
        if (same_group or same_role) and same_template:
            filtered.append(plan)
    if not filtered and template_id:
        filtered = [plan for plan in plans if plan.get("template_id") == template_id]
    return [_compact_previous_prompt(plan.get("prompt")) for plan in filtered[:limit]]


def _regeneration_direction(data, role, template, variant_index=1, is_group_photo=False):
    previous_prompts = _previous_prompts_for(
        data,
        role_id=role.get("id") or role.get("role_id") or "",
        template_id=template.get("id") or "",
        is_group_photo=is_group_photo,
    )
    plan_revision = _role_wallpaper_plan_revision(data)
    if not previous_prompts and not plan_revision:
        return ""
    seed_source = ":".join(
        [
            str((data or {}).get("regeneration_seed") or (data or {}).get("regenerationSeed") or ""),
            str(role.get("id") or role.get("role_id") or ""),
            str(template.get("id") or ""),
            str(variant_index),
            str(len(_previous_role_wallpaper_plans(data))),
        ]
    )
    seed = int(hashlib.sha1(seed_source.encode("utf-8")).hexdigest()[:8], 16)
    if is_group_photo:
        cameras = ["低机位横向电影群像", "远景空间纵深群像", "窗边逆光错落站位", "桌边围合式互动构图", "前后景分层海报构图"]
        actions = ["五人之间有克制视线交流", "中心人物稍退、两侧形成守护式包围", "每个人有不同手部动作但都不遮脸", "同一光源下形成安静等待的瞬间"]
        spaces = ["更强调室内纵深与同一空间关系", "加入前景虚化道具增强层次", "减少竖版留白，改成宽幅横向呼吸感", "把背景统一成同一时间段的完整环境"]
    else:
        cameras = ["近景半身、轻微仰角", "远景全身、前景虚化遮挡", "侧逆光三分构图", "俯视窗边留白构图", "镜面反射双层构图", "低机位桌边电影镜头"]
        actions = ["改变微表情和视线方向", "改成回眸或停步瞬间", "让手部与道具产生自然互动", "姿态更放松、距离感更强", "动作更静态克制但情绪更明确"]
        spaces = ["把背景层次拉深", "调整道具摆位和桌面关系", "强化窗光与阴影方向", "增加前景虚化材质", "减少与上一轮相同的主体站位"]
    direction = (
        "重新生成变化指令：这版必须明显区别于上一轮 Prompt，不要只改标题或少量形容词；"
        f"优先改为「{cameras[seed % len(cameras)]}」，并「{actions[(seed // 7) % len(actions)]}」，"
        f"同时「{spaces[(seed // 13) % len(spaces)]}」。"
    )
    if plan_revision:
        direction += f" 用户重生成建议：{plan_revision}。"
    if previous_prompts:
        direction += " 请避开上一轮核心画面：" + " / ".join(previous_prompts)
    return direction


def _prompt_for(role, template, data, variant_index=1):
    aspect_ratio = data.get("aspect_ratio") or data.get("aspectRatio") or "9:16"
    user_notes = (data.get("user_notes") or data.get("notes") or "").strip()
    scene_extra = (data.get("scene_extra") or data.get("sceneExtra") or "").strip()
    template_negative = "，".join(template.get("negative") or [])
    role_avoid = "，".join(role.get("avoid_prompt_notes") or [])
    props = "、".join(template.get("props") or [])
    series_style_anchor = str(data.get("_series_style_anchor") or "").strip()
    variation = ""
    if variant_index > 1:
        variation = f"这是同一角色同一模板的第 {variant_index} 个变体，请改变微表情、镜头距离和道具摆位，但不要改变角色识别点。"
    prompt = (
        f"粉丝向乙游角色壁纸，角色目标：{role['cn_name']} / {role['en_name']}。"
        "请严格参考随任务提供的本地角色参考图，脸部辨识点、发型、眼睛、服装、体态比例与气质跟随本次参考图变化；"
        "不要把角色做成固定服装、固定眼神或固定姿态；"
        "不要直接复刻官方卡面构图，不要加入游戏 logo、UI、卡面文字或水印。\n"
        "人物表情、眼神和服装不要从固定角色模板补写，应读取本次附带参考图。\n"
        f"场景模板：{template['name']}。场景：{template['scene']}。构图：{template['composition']}。"
        f"光影：{template['lighting']}。情绪：{template['mood']}。道具：{props}。\n"
        f"画幅：{aspect_ratio}，{_wallpaper_format_hint(aspect_ratio)}，高质量商业插画质感，真实皮肤和头发细节，电影感光影，背景干净，主体清晰。"
        f"{variation}"
    )
    regeneration_direction = _regeneration_direction(data, role, template, variant_index=variant_index)
    if regeneration_direction:
        prompt += f"\n{regeneration_direction}"
    if series_style_anchor:
        prompt += (
            f"\n整组统一视觉锚点：{series_style_anchor}。本图必须与同组其他角色保持相同世界观、色板、光线方向、镜头语言与材质。"
            "角色参考图只负责锁定脸、发型、体态和必要服装识别点；忽略参考图自身背景、构图、动作、光影和色调，不能让随机参考图破坏整组统一风格。"
        )
    if scene_extra:
        prompt += f"\n额外场景要求：{scene_extra}"
    if user_notes:
        prompt += f"\n用户补充要求：{user_notes}"
    prompt += (
        f"\n负向约束：{template_negative}，{role_avoid}，不要多人抢主体，不要低清晰度，不要脸崩，不要错手错眼，"
        "不要畸形身体，不要 AI 乱码，不要过度裸露，不要色情化，不要血腥暴力。"
    )
    return prompt


def _series_style_anchor(template, data):
    inspiration_prompt = _series_inspiration_prompt(data or {})
    if inspiration_prompt:
        source_role = _inspiration_source_role(data or {})
        dna_text = _scene_style_dna_text(data or {})
        compact_prompt = "" if dna_text else _compact_scene_only_prompt_text(inspiration_prompt, source_role)
        scene_source = f"风格 DNA：{dna_text}" if dna_text else f"场景摘要：{compact_prompt}"
        return (
            "参考图反推的整组统一场景风格（已隔离来源人物身份，只保留场景维度）。"
            f"{scene_source}。"
        )
    props = "、".join(template.get("props") or [])
    user_notes = str((data or {}).get("user_notes") or (data or {}).get("userNotes") or "").strip()
    anchor = (
        f"{template.get('name', '')}；场景：{template.get('scene', '')}；"
        f"光影：{template.get('lighting', '')}；情绪：{template.get('mood', '')}；"
        f"构图语言：{template.get('composition', '')}；核心道具：{props}"
    )
    if user_notes:
        anchor += f"；用户统一要求：{user_notes}"
    return anchor


def _manual_reference_ids_by_role(data, roles):
    raw = (data or {}).get("reference_ids_by_role") or (data or {}).get("referenceIdsByRole") or {}
    if not isinstance(raw, dict):
        raw = {}
    role_ids = {role["id"] for role in roles}
    result = {role_id: [] for role_id in role_ids}
    for role_id, values in raw.items():
        if role_id not in role_ids:
            continue
        if isinstance(values, str):
            values = [values]
        for reference_id in (values or [])[:MAX_MANUAL_REFERENCE_LIMIT]:
            try:
                item = _reference_item(_path_from_reference_id(str(reference_id)))
            except Exception:
                continue
            if item.get("role_id") == role_id and item["id"] not in result[role_id]:
                result[role_id].append(item["id"])
    return result


def _group_reference_ids(roles, manual_by_role=None):
    """Use one identity anchor per role so five people fit within the six-image API limit."""
    selected = []
    for role in roles:
        if manual_by_role is not None:
            manual = manual_by_role.get(role["id"]) or []
            if manual:
                selected.append(manual[0])
            continue
        complete = list_reference_images(role_id=role["id"], usage="complete")["items"]
        pool = complete or list_reference_images(role_id=role["id"])["items"]
        if pool:
            selected.append(pool[0]["id"])
    return selected[:MAX_MANUAL_REFERENCE_LIMIT]


def _group_prompt_for(roles, template, data, aspect_ratio, style_anchor):
    order = "、".join(f"{index + 1}号位 {role['cn_name']} / {role['en_name']}" for index, role in enumerate(roles))
    role_avoids = "，".join(
        note for role in roles for note in (role.get("avoid_prompt_notes") or []) if note
    )
    using_reference_scene = bool(_series_inspiration_prompt(data or {}) or template.get("id") == "reference_unified_scene")
    scene_source_line = (
        f"整组统一视觉锚点：{style_anchor}。场景来源：参考图统一场景 Prompt；本张必须把这份竖版/单人场景风格横向重构为宽幅群像，不套用通用场景模板。"
        if using_reference_scene
        else (
            f"整组统一视觉锚点：{style_anchor}。场景模板：{template.get('name', '')}。"
            "模板中的竖版构图只作为单人图语言参考；本张必须重新组织成宽幅群像，不能照搬竖版留白或单人站位。"
        )
    )
    regeneration_direction = _regeneration_direction(
        data,
        {"id": "group_all", "role_id": "group_all", "cn_name": "五人合照"},
        template,
        variant_index=1,
        is_group_photo=True,
    )
    return (
        "粉丝向乙游五人同框宽幅壁纸，必须同时出现五位独立成年男性角色，人数恰好五人。\n"
        f"从画面左到右固定站位：{order}。每一位人物分别对应随任务附带的同序号角色参考图；"
        "逐人锁定各自脸部辨识点、发型发色、眼睛、体态比例与气质，严禁互换五官、串发色、融合脸、复制同一张脸或遗漏角色。\n"
        "五张人物参考图只用于身份锁定，必须忽略各参考图原有背景、动作、构图、光影与色调；整张合照完全服从统一场景风格。\n"
        f"{scene_source_line}"
        "五人处于同一空间、同一时间、同一光源下，服装材质与色板属于同一系列，但保留每个角色独立辨识度。"
        "采用有主次但不遮脸的横向群像构图，前后层次自然，人物之间有克制互动，头部不切边，手部尽量完整，背景留出桌面图标区域。\n"
        f"{regeneration_direction + chr(10) if regeneration_direction else ''}"
        f"画幅：{aspect_ratio}，{_wallpaper_format_hint(aspect_ratio)}，电影海报级群像，清晰面部，高质量商业插画与真实材质。\n"
        f"负向约束：人数不足或超过五人，重复人物，融合脸，角色特征串位，遮挡面部，比例失衡，{role_avoids}，"
        "游戏 logo、UI、卡面文字、水印、乱码、低清晰度、错手错眼、畸形身体、过度裸露、色情化、血腥暴力。"
    )


def _ai_group_prompt_for(roles, template, data, fallback_prompt, aspect_ratio, style_anchor):
    if not is_text_provider_configured():
        raise TextProviderNotConfigured("Text provider is not configured")
    series_inspiration = _series_inspiration_prompt(data or {})
    source_role = _inspiration_source_role(data or {})
    reference_scene_guard = _reference_scene_identity_guard(data or {}, group=True)
    plan_revision = _role_wallpaper_plan_revision(data)
    previous_prompts = _previous_prompts_for(
        data,
        role_id="group_all",
        template_id=template.get("id") or "",
        is_group_photo=True,
    )
    instruction = {
        "任务": "为五个乙游角色生成一张同框宽幅群像壁纸 Prompt",
        "五人固定左到右顺序": [
            {"position": index + 1, "id": role["id"], "name": role["cn_name"], "en_name": role["en_name"]}
            for index, role in enumerate(roles)
        ],
        "整组统一视觉锚点": style_anchor,
        "场景模板": template,
        "参考图统一场景 Prompt": series_inspiration,
        "参考图来源角色": (
            {"id": source_role.get("id"), "cn_name": source_role.get("cn_name"), "en_name": source_role.get("en_name")}
            if source_role
            else None
        ),
        "参考图人物净化规则": reference_scene_guard,
        "场景来源规则": (
            "本次必须以参考图统一场景 Prompt 为唯一场景来源，但只能抽取场景、构图、镜头、光影、色彩、环境材质、道具运动和氛围；不要套用通用场景模板，也不要继承来源人物身份"
            if series_inspiration
            else "使用所选通用场景模板"
        ),
        "画幅": aspect_ratio,
        "用户重生成建议": plan_revision,
        "上一轮五人合照 Prompt": previous_prompts,
        "基础 Prompt": fallback_prompt,
        "要求": [
            "人物人数恰好五人；每个人分别绑定同序号参考图，不能融合脸、串发色、重复或漏人",
            "和同批五张单人图保持同一场景世界观、色板、光线方向、镜头语言和材质",
            "宽幅群像要有清晰站位、前后层次和克制互动，但不能遮挡脸",
            "如果提供了参考图统一场景 Prompt，必须完全以它作为场景、构图、镜头、光影、色彩和道具来源，不要混入通用模板场景",
            "如果参考图统一场景 Prompt 中出现来源人物的脸、发型发色、瞳色、服装剪裁、胸肩装饰、身材、表情、姿态、角色姓名或角色气质，必须当作误提取删除，不能写入最终 prompt",
            "五个人的脸、发型、发色、瞳色、服装识别点和气质分别以对应角色/单人图参考为准，严禁把来源角色复制成五个人",
            "如果提供了上一轮 Prompt 或用户重生成建议，新 prompt 必须明显改变群像站位、镜头距离、空间层次、互动方式或光影方向",
            "只输出 JSON，字段为 title、hook、prompt、negative_prompt、xhs_hooks",
            "prompt 用中文，450-1000 字，可直接交给图像模型",
        ],
    }
    payload = prepare_text_payload(
        {
            "model": settings.text_model,
            "messages": [
                {"role": "system", "content": "你是擅长多角色身份隔离与系列化视觉统一的群像海报导演。"},
                {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)},
            ],
            "temperature": 0.62,
        },
        json_output=True,
    )
    response = post_json(_chat_url(), payload, _text_headers(), timeout=300, ssl_verify=settings.text_ssl_verify)
    parsed = _extract_json(response["choices"][0]["message"]["content"].strip())
    prompt = str((parsed or {}).get("prompt") or "").strip()
    if not prompt:
        raise ValueError("AI 没有返回五人合照 prompt")
    negative = str((parsed or {}).get("negative_prompt") or "").strip()
    if negative and "负向" not in prompt and "不要" not in prompt[-180:]:
        prompt += f"\n负向约束：{negative}"
    if reference_scene_guard and "参考图人物净化" not in prompt:
        prompt = f"{reference_scene_guard}\n{prompt}"
    return {
        "title": str((parsed or {}).get("title") or "五人同风格合照").strip(),
        "hook": str((parsed or {}).get("hook") or "").strip(),
        "prompt": prompt,
        "negative_prompt": negative,
        "xhs_hooks": _string_list((parsed or {}).get("xhs_hooks"), template.get("xhs_hooks") or [], 4),
    }


def generate_role_wallpaper_plans(data):
    catalog = _load_catalog()
    roles = _selected_roles(data or {}, catalog)
    templates = _selected_templates(data or {}, catalog)
    series_inspiration = _series_inspiration_prompt(data or {})
    using_reference_scene = bool(series_inspiration)
    count_per_role = max(1, min(int((data or {}).get("count_per_role") or (data or {}).get("countPerRole") or 1), 4))
    max_plans = max(1, min(int((data or {}).get("max_plans") or (data or {}).get("maxPlans") or 40), 80))
    reference_types = (data or {}).get("reference_types") or (data or {}).get("referenceTypes") or ["complete", "identity", "outfit", "expression", "pose"]
    reference_types = [x for x in reference_types if x in ROLE_REFERENCE_USAGES] or ["complete"]
    image_model = (data or {}).get("image_model") or (data or {}).get("imageModel") or settings.image_model
    reference_mode = str((data or {}).get("reference_mode") or (data or {}).get("referenceMode") or "auto")
    manual_all = reference_mode == "manual_all"
    manual_by_role = _manual_reference_ids_by_role(data or {}, roles)
    if len(roles) == 1 and reference_mode == "manual":
        single_ids = (data or {}).get("reference_ids") or (data or {}).get("referenceIds") or []
        if isinstance(single_ids, str):
            single_ids = [single_ids]
        manual_by_role[roles[0]["id"]] = [str(item) for item in single_ids[:MAX_MANUAL_REFERENCE_LIMIT] if item]
    include_group_photo = (data or {}).get("include_group_photo")
    if include_group_photo is None:
        include_group_photo = (data or {}).get("includeGroupPhoto", False)
    group_aspect_ratio = str(
        (data or {}).get("group_aspect_ratio") or (data or {}).get("groupAspectRatio") or "16:9"
    ).strip()
    if group_aspect_ratio not in {"16:9", "16:10"}:
        group_aspect_ratio = "16:9"
    plans = []
    for template in templates:
        style_anchor = _series_style_anchor(template, data or {})
        plan_data = {**(data or {}), "_series_style_anchor": style_anchor}
        for role in roles:
            reference_counts = _count_references_for_role(role["id"])
            role_reference_ids = manual_by_role.get(role["id"]) or []
            role_reference_ready = bool(role_reference_ids) if manual_all else True
            for variant_index in range(1, count_per_role + 1):
                if len(plans) >= max_plans:
                    break
                plan_id = f"role_plan_{_slug(role['id'])}_{_slug(template['id'])}_{variant_index}"
                fallback_prompt = _prompt_for(role, template, plan_data, variant_index=variant_index)
                ai_prompt = None
                ai_prompt_error = ""
                if (data or {}).get("use_ai_prompt") is not False and (data or {}).get("useAiPrompt") is not False:
                    try:
                        ai_prompt = _ai_prompt_for(role, template, plan_data, fallback_prompt, variant_index=variant_index)
                    except Exception as exc:
                        ai_prompt_error = str(exc)
                prompt = (ai_prompt or {}).get("prompt") or fallback_prompt
                identity_guard = _reference_scene_identity_guard(plan_data, role)
                prompt += (
                    f"\n【整组强制统一】本张必须严格服从同系列视觉锚点：{style_anchor}。"
                    "本张只共享场景、镜头、光影、配色、环境材质、道具运动和氛围；"
                    "角色参考图仅用于人物身份，不得继承其背景、构图、动作、光影或色调。"
                )
                if identity_guard and "参考图人物净化" not in prompt:
                    prompt = f"{identity_guard}\n{prompt}"
                xhs_hooks = (ai_prompt or {}).get("xhs_hooks") or template.get("xhs_hooks") or []
                plans.append(
                    {
                        "id": plan_id,
                        "index": len(plans) + 1,
                        "approved": role_reference_ready,
                        "role_id": role["id"],
                        "role_name": role["cn_name"],
                        "role_en_name": role["en_name"],
                        "template_id": template["id"],
                        "template_name": template["name"],
                        "variant_index": variant_index,
                        "aspect_ratio": (data or {}).get("aspect_ratio") or (data or {}).get("aspectRatio") or "9:16",
                        "image_model": image_model,
                        "image_model_profile": settings.image_model_profile(image_model),
                        "reference_types": reference_types,
                        "reference_ids": role_reference_ids,
                        "reference_strategy": {
                            "mode": "manual" if role_reference_ids else "complete_pool_rotation",
                            "selected_count": len(role_reference_ids),
                            "planned_reference_count": len(role_reference_ids) or min(DEFAULT_COMPLETE_REFERENCE_LIMIT, reference_counts.get("complete", 0)),
                            "reference_limit": len(role_reference_ids) or DEFAULT_REFERENCE_LIMIT,
                            "complete_reference_limit": len(role_reference_ids) or DEFAULT_COMPLETE_REFERENCE_LIMIT,
                            "reference_limit_per_usage": DEFAULT_REFERENCE_LIMIT_PER_USAGE,
                            "note": "完整角色图会作为 complete 综合参考；正式出图时不会全量塞入，而是按生成序号轮换挑选一组稳定参考图。",
                        },
                        "reference_counts": reference_counts,
                        "risk_level": role.get("risk_profile", {}).get("default") or "high_ip_risk",
                        "recommended_public_label": role.get("risk_profile", {}).get("recommended_public_label") or "粉丝向二创展示",
                        "commercial_note": role.get("risk_profile", {}).get("commercial_note") or "",
                        "title": (ai_prompt or {}).get("title") or f"{role['cn_name']} · {template['name']}",
                        "hook": (ai_prompt or {}).get("hook") or "",
                        "prompt": prompt,
                        "negative_prompt": (ai_prompt or {}).get("negative_prompt") or "",
                        "xhs_hooks": xhs_hooks,
                        "prompt_source": "ai_text_provider" if ai_prompt else "catalog_fallback",
                        "ai_prompt_error": ai_prompt_error,
                        "source": "ai" if ai_prompt else "catalog",
                        "series_style_anchor": style_anchor,
                        "uses_series_inspiration": using_reference_scene,
                        "series_inspiration_prompt": series_inspiration if using_reference_scene else "",
                        "style_source": "reference_unified_scene" if using_reference_scene else "common_template",
                        "reference_warning": (
                            f"五角色手选模式下尚未为 {role['cn_name']} 选择参考图"
                            if manual_all and not role_reference_ids
                            else ""
                        ),
                    }
                )
        if include_group_photo and len(roles) == 5 and len(plans) < max_plans:
            reference_ids = _group_reference_ids(roles, manual_by_role if manual_all else None)
            missing_role_names = []
            for role in roles:
                if manual_all:
                    ready = bool(manual_by_role.get(role["id"]))
                else:
                    ready = bool(
                        list_reference_images(role_id=role["id"], usage="complete")["items"]
                        or list_reference_images(role_id=role["id"])["items"]
                    )
                if not ready:
                    missing_role_names.append(role["cn_name"])
            group_reference_ready = not missing_role_names and len(reference_ids) == 5
            fallback_prompt = _group_prompt_for(roles, template, data or {}, group_aspect_ratio, style_anchor)
            ai_prompt = None
            ai_prompt_error = ""
            if group_reference_ready and (data or {}).get("use_ai_prompt") is not False and (data or {}).get("useAiPrompt") is not False:
                try:
                    ai_prompt = _ai_group_prompt_for(
                        roles, template, data or {}, fallback_prompt, group_aspect_ratio, style_anchor
                    )
                except Exception as exc:
                    ai_prompt_error = str(exc)
            prompt = (ai_prompt or {}).get("prompt") or fallback_prompt
            group_identity_guard = _reference_scene_identity_guard(data or {}, group=True)
            prompt += (
                f"\n【整组强制统一】五人合照必须严格服从与五张单人图相同的视觉锚点：{style_anchor}。"
                "合照只共享场景、镜头、光影、配色、环境材质、道具运动和氛围；"
                "五张角色参考图仅用于各自身份锁定，不得把任何参考图原背景、动作、光影或色调带入合照。"
            )
            if group_identity_guard and "参考图人物净化" not in prompt:
                prompt = f"{group_identity_guard}\n{prompt}"
            plans.append(
                {
                    "id": f"role_plan_group_all_{_slug(template['id'])}_1",
                    "index": len(plans) + 1,
                    "approved": group_reference_ready,
                    "role_id": "group_all",
                    "role_ids": [role["id"] for role in roles],
                    "role_name": "五人合照",
                    "role_en_name": "Five-character group",
                    "template_id": template["id"],
                    "template_name": f"{template['name']} · 五人合照",
                    "variant_index": 1,
                    "aspect_ratio": group_aspect_ratio,
                    "image_model": image_model,
                    "image_model_profile": settings.image_model_profile(image_model),
                    "reference_types": ["complete"],
                    "reference_ids": reference_ids,
                    "reference_strategy": {
                        "mode": "one_identity_reference_per_role",
                        "selected_count": len(reference_ids),
                        "planned_reference_count": len(reference_ids),
                        "reference_limit": MAX_MANUAL_REFERENCE_LIMIT,
                        "complete_reference_limit": MAX_MANUAL_REFERENCE_LIMIT,
                        "note": "五人合照每个角色各取 1 张身份参考图，顺序与 Prompt 中五人站位一致。",
                    },
                    "reference_counts": {"total": len(reference_ids), "complete": len(reference_ids)},
                    "risk_level": "high_ip_risk",
                    "recommended_public_label": "粉丝向二创展示",
                    "commercial_note": "五个原角色同框，公开商用前需单独评估授权与平台规则。",
                    "title": (ai_prompt or {}).get("title") or f"五人合照 · {template['name']}",
                    "hook": (ai_prompt or {}).get("hook") or "",
                    "prompt": prompt,
                    "negative_prompt": (ai_prompt or {}).get("negative_prompt") or "",
                    "xhs_hooks": (ai_prompt or {}).get("xhs_hooks") or template.get("xhs_hooks") or [],
                    "prompt_source": "ai_text_provider" if ai_prompt else "catalog_fallback",
                    "ai_prompt_error": ai_prompt_error,
                    "source": "ai" if ai_prompt else "catalog",
                    "is_group_photo": True,
                    "group_reference_source": "current_batch_solo_images",
                    "group_reference_ready": group_reference_ready,
                    "group_reference_warning": (
                        "五人合照暂不可生成，缺少角色参考图：" + "、".join(missing_role_names)
                        if missing_role_names
                        else ""
                    ),
                    "series_style_anchor": style_anchor,
                    "uses_series_inspiration": using_reference_scene,
                    "series_inspiration_prompt": series_inspiration if using_reference_scene else "",
                    "style_source": "reference_unified_scene" if using_reference_scene else "common_template",
                }
            )
    return {
        "plans": plans,
        "roles": roles,
        "templates": templates,
        "reference_root": str(REFERENCE_ROOT.relative_to(WORKSPACE_ROOT)),
        "ip_notice": catalog.get("ip_notice", ""),
        "source": "ai" if any(plan.get("prompt_source") == "ai_text_provider" for plan in plans) else "catalog",
    }


def _selected_reference_items(plan, config):
    explicit_ids = plan.get("reference_ids") or plan.get("referenceIds") or config.get("reference_ids") or config.get("referenceIds") or []
    if isinstance(explicit_ids, str):
        explicit_ids = [explicit_ids]

    items = []
    warnings = []
    if explicit_ids:
        explicit_limit = _bounded_int(
            config.get("manual_reference_limit") or config.get("manualReferenceLimit") or config.get("reference_limit") or config.get("referenceLimit"),
            MAX_MANUAL_REFERENCE_LIMIT,
            1,
            MAX_MANUAL_REFERENCE_LIMIT,
        )
        if len(explicit_ids) > explicit_limit:
            warnings.append(f"手动参考图最多使用 {explicit_limit} 张，已自动截断")
        for reference_id in explicit_ids[:explicit_limit]:
            try:
                path = _path_from_reference_id(reference_id)
                items.append(_reference_item(path))
            except Exception as exc:
                warnings.append(str(exc))
        return items, warnings

    role_id = plan.get("role_id") or config.get("role_id") or ""
    template_id = plan.get("template_id") or config.get("template_id") or ""
    reference_types = plan.get("reference_types") or config.get("reference_types") or ["complete", "identity", "outfit", "expression", "pose"]
    reference_types = [x for x in reference_types if x in ROLE_REFERENCE_USAGES] or ["complete"]
    if "complete" not in reference_types:
        reference_types = ["complete", *reference_types]

    seen_ids = set()
    total_limit = _bounded_int(
        config.get("reference_limit") or config.get("referenceLimit"),
        DEFAULT_REFERENCE_LIMIT,
        1,
        12,
    )
    per_usage = _bounded_int(
        config.get("reference_limit_per_usage") or config.get("referenceLimitPerUsage"),
        DEFAULT_REFERENCE_LIMIT_PER_USAGE,
        1,
        4,
    )
    complete_limit = _bounded_int(
        config.get("complete_reference_limit") or config.get("completeReferenceLimit"),
        min(DEFAULT_COMPLETE_REFERENCE_LIMIT, total_limit),
        1,
        total_limit,
    )
    rotation_offset = _bounded_int(
        plan.get("variant_index") or plan.get("variantIndex") or plan.get("index"),
        1,
        1,
        9999,
    ) - 1

    complete_items = []
    if "complete" in reference_types:
        complete_items = _rotated(list_reference_images(role_id=role_id, usage="complete")["items"], rotation_offset)
        for item in complete_items[:complete_limit]:
            if item["id"] not in seen_ids:
                items.append(item)
                seen_ids.add(item["id"])

    for usage in reference_types:
        if usage == "complete":
            continue
        if len(items) >= total_limit:
            break
        for item in list_reference_images(role_id=role_id, usage=usage)["items"][:per_usage]:
            if len(items) >= total_limit:
                break
            if item["id"] not in seen_ids:
                items.append(item)
                seen_ids.add(item["id"])

    if config.get("include_scene_references") or config.get("includeSceneReferences"):
        for item in list_reference_images(template_id=template_id)["items"][:2]:
            if len(items) >= total_limit:
                break
            if item["id"] not in seen_ids:
                items.append(item)
                seen_ids.add(item["id"])

    return items[:total_limit], warnings


def _reference_data_urls(items):
    images = []
    used = []
    warnings = []
    for item in items:
        try:
            path = _path_from_reference_id(item["id"])
            images.append(_file_to_data_url(path))
            used.append(item)
        except Exception as exc:
            warnings.append(str(exc))
    return images, used, warnings


def _generated_image_reference_value(url):
    value = str(url or "").strip()
    if value.startswith(("data:image/", "http://", "https://")):
        return value
    path = (WORKSPACE_ROOT / value.lstrip("/")).resolve()
    try:
        path.relative_to(WORKSPACE_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("Generated solo image path is outside workspace") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Generated solo image cache is missing")
    return _file_to_data_url(path)


def _submit_and_wait_image(prompt, aspect_ratio, images, model=None, on_poll=None):
    result = create_image_task(
        prompt=prompt,
        size="auto",
        aspect_ratio=aspect_ratio,
        images=images,
        model=model,
    )
    return wait_for_image_result(
        result,
        poll_interval=settings.image_poll_interval,
        max_wait=settings.image_max_wait,
        on_poll=on_poll,
    )


def _result_has_url(result):
    return bool((result or {}).get("url"))


def list_role_wallpaper_assets(store):
    ensure_role_wallpaper_account(store)
    store_items = [
        item
        for item in store.list_assets(product_id=ROLE_WALLPAPER_ACCOUNT_ID)
        if (item.get("generation_plan") or {}).get("kind") == "role_wallpaper"
    ]
    return {
        "items": _merge_asset_lists(store_items, _load_persisted_assets())
    }


def delete_role_wallpaper_asset(store, asset_id):
    ensure_role_wallpaper_account(store)
    store_item = next(
        (
            item
            for item in store.list_assets(product_id=ROLE_WALLPAPER_ACCOUNT_ID)
            if item.get("id") == asset_id and (item.get("generation_plan") or {}).get("kind") == "role_wallpaper"
        ),
        None,
    )
    deleted = store.delete_asset(asset_id) if store_item else None
    persisted = _delete_persisted_role_wallpaper_asset(asset_id)
    return deleted or persisted


def run_role_wallpaper_image_job(store, job_id):
    job = store.get_job(job_id)
    if not job:
        return
    ensure_role_wallpaper_account(store)
    config = job.get("config") or {}
    plans = [plan for plan in config.get("plans") or [] if plan.get("approved") is not False]
    if not plans:
        store.update_job(job_id, status="failed", progress=100, detail="没有可生成的角色壁纸方案")
        return

    store.update_job(job_id, progress=5, detail="整理角色壁纸 prompt 与本地参考图")
    created_assets_by_index = {}
    generated_solo_images = {}
    state_lock = RLock()
    active_labels = {}
    completed_count = 0
    total = len(plans)
    missing_reference_count = 0
    concurrency = _bounded_int(
        config.get("image_concurrency") or config.get("imageConcurrency") or settings.image_concurrency,
        settings.image_concurrency,
        1,
        8,
    )
    indexed_plans = list(enumerate(plans, start=1))

    def _is_group_plan(plan):
        return bool(plan.get("is_group_photo") or plan.get("isGroupPhoto"))

    def _active_summary():
        labels = list(active_labels.values())
        if not labels:
            return "等待图片接口返回"
        return "、".join(labels[:4]) + ("…" if len(labels) > 4 else "")

    def _job_progress():
        return min(96, max(8, int((completed_count / max(total, 1)) * 88) + 8))

    def _publish_progress(detail=None):
        with state_lock:
            progress = _job_progress()
            message = detail or f"并发生成中：已完成 {completed_count}/{total}；当前：{_active_summary()}"
        store.update_job(job_id, progress=progress, detail=message)

    def _process_plan(index, plan):
        prompt = str(plan.get("prompt") or "").strip()
        if not prompt:
            role = get_role_profile(plan.get("role_id"))
            template = get_wallpaper_template(plan.get("template_id"))
            if role and template:
                prompt = _prompt_for(role, template, config, variant_index=index)
        is_group_photo = _is_group_plan(plan)
        role_label = plan.get("role_name") or plan.get("role_id") or "角色"
        with state_lock:
            active_labels[index] = role_label
        _publish_progress(
            f"正在{'生成合照' if is_group_photo else '并发生成单人图'}：{role_label} · {index}/{total}；"
            f"当前并发：{_active_summary()}"
        )

        ref_warnings = []
        data_url_warnings = []
        used_refs = []
        result = {}
        provider_status = "failed"
        missing_reference = False
        if is_group_photo:
            role_ids = plan.get("role_ids") or plan.get("roleIds") or []
            template_id = plan.get("template_id") or ""
            generated_reference_assets = plan.get("generated_reference_assets") or plan.get("generatedReferenceAssets") or []
            reference_image_urls = plan.get("reference_image_urls") or plan.get("referenceImageUrls") or []
            if isinstance(reference_image_urls, str):
                reference_image_urls = [reference_image_urls]
            images = []
            used_refs = []
            missing_generated_roles = []
            if generated_reference_assets or reference_image_urls:
                normalized_refs = []
                if isinstance(generated_reference_assets, list):
                    for item in generated_reference_assets[:MAX_MANUAL_REFERENCE_LIMIT]:
                        if isinstance(item, dict):
                            normalized_refs.append(item)
                for url in reference_image_urls[:MAX_MANUAL_REFERENCE_LIMIT]:
                    normalized_refs.append({"url": url, "title": "selected-generated-image"})
                for ref_index, ref in enumerate(normalized_refs[:MAX_MANUAL_REFERENCE_LIMIT], start=1):
                    ref_url = ref.get("url") or ref.get("image_url") or ref.get("imageUrl") or ""
                    try:
                        images.append(_generated_image_reference_value(ref_url))
                        used_refs.append(
                            {
                                "id": ref.get("id") or ref.get("asset_id") or "",
                                "role_id": ref.get("role_id") or ref.get("roleId") or "",
                                "filename": ref.get("title") or ref.get("filename") or f"selected-generated-image-{ref_index}",
                                "usage": "selected_generated_image",
                                "source": "selected_generated_assets",
                                "position": ref_index,
                            }
                        )
                    except Exception:
                        missing_generated_roles.append(str(ref.get("title") or ref.get("id") or ref_index))
            else:
                for role_id in role_ids:
                    with state_lock:
                        generated = generated_solo_images.get((template_id, role_id))
                    if generated and generated.get("url"):
                        try:
                            images.append(_generated_image_reference_value(generated["url"]))
                            used_refs.append(
                                {
                                    "id": generated.get("asset_id") or "",
                                    "role_id": role_id,
                                    "filename": generated.get("title") or f"{role_id}-current-batch-solo",
                                    "usage": "current_batch_solo_image",
                                    "source": "generated_in_current_job",
                                }
                            )
                        except Exception:
                            missing_generated_roles.append(role_id)
                    else:
                        missing_generated_roles.append(role_id)
            if missing_generated_roles:
                ref_warnings.append("合照暂停：缺少可用生成图 " + "、".join(missing_generated_roles))
        else:
            generated_reference_assets = plan.get("generated_reference_assets") or plan.get("generatedReferenceAssets") or []
            reference_image_urls = plan.get("reference_image_urls") or plan.get("referenceImageUrls") or []
            if isinstance(reference_image_urls, str):
                reference_image_urls = [reference_image_urls]
            if generated_reference_assets or reference_image_urls:
                images = []
                used_refs = []
                data_url_warnings = []
                ref_warnings = []
                normalized_refs = []
                if isinstance(generated_reference_assets, list):
                    for item in generated_reference_assets[:MAX_MANUAL_REFERENCE_LIMIT]:
                        if isinstance(item, dict):
                            normalized_refs.append(item)
                for url in reference_image_urls[:MAX_MANUAL_REFERENCE_LIMIT]:
                    normalized_refs.append({"url": url, "title": "selected-generated-image"})
                for ref_index, ref in enumerate(normalized_refs[:MAX_MANUAL_REFERENCE_LIMIT], start=1):
                    ref_url = ref.get("url") or ref.get("image_url") or ref.get("imageUrl") or ""
                    try:
                        images.append(_generated_image_reference_value(ref_url))
                        used_refs.append(
                            {
                                "id": ref.get("id") or ref.get("asset_id") or "",
                                "role_id": ref.get("role_id") or ref.get("roleId") or plan.get("role_id") or "",
                                "filename": ref.get("title") or ref.get("filename") or f"selected-generated-image-{ref_index}",
                                "usage": "selected_generated_image",
                                "source": "generated_image_edit_reference",
                                "position": ref_index,
                            }
                        )
                    except Exception as exc:
                        ref_warnings.append(f"生成图参考不可用：{exc}")
            else:
                refs, ref_warnings = _selected_reference_items(plan, config)
                images, used_refs, data_url_warnings = _reference_data_urls(refs)
            missing_generated_roles = []
        if not images:
            missing_reference = True
        image_model = plan.get("image_model") or plan.get("imageModel") or config.get("image_model") or config.get("imageModel")
        try:
            if is_group_photo and missing_generated_roles:
                raise ValueError(f"{len(images) + len(missing_generated_roles)}人合照需要所选生成图全部可用；缺少：" + "、".join(missing_generated_roles))

            def _image_poll_update(poll_result):
                elapsed = _duration_label((poll_result or {}).get("elapsed_seconds") or 0)
                provider_status_text = str((poll_result or {}).get("status") or "处理中")
                with state_lock:
                    active_labels[index] = f"{role_label}({elapsed})"
                    progress = _job_progress()
                    active = _active_summary()
                detail = (
                    f"并发生成中：已完成 {completed_count}/{total}；当前：{active}。"
                    f"{role_label} · {index}/{total} 已等待 {elapsed}，图片接口仍在处理（状态：{provider_status_text}）"
                )
                if (poll_result or {}).get("last_poll_error"):
                    detail += "；最近一次查询接口状态失败，已自动继续重试"
                store.update_job(job_id, progress=progress, detail=detail)

            store.update_job(
                job_id,
                progress=_job_progress(),
                detail=(
                    f"{'合照等待单人图完成后生成' if is_group_photo else '单人图并发生成'}：{role_label} · {index}/{total}，"
                    f"并发数 {concurrency}，单张最长等待 {_duration_label(settings.image_max_wait)}"
                ),
            )
            aspect_ratio = plan.get("aspect_ratio") or config.get("aspect_ratio") or config.get("aspectRatio") or "9:16"
            result = _submit_and_wait_image(
                prompt,
                aspect_ratio,
                images,
                model=image_model,
                on_poll=_image_poll_update,
            )
            if (
                not _result_has_url(result)
                and len(images) > 2
                and not is_group_photo
                and str(result.get("status") or "").lower() != "timeout"
                and (config.get("auto_retry_with_fewer_references") is not False)
                and (config.get("autoRetryWithFewerReferences") is not False)
            ):
                previous_attempt = result
                retry_images = images[:2]
                store.update_job(
                    job_id,
                    progress=max(10, int((index - 0.5) / total * 88)),
                    detail=f"{plan.get('role_name') or plan.get('role_id') or '角色'} 首次未出图，正在用 2 张核心参考图重试",
                )
                result = _submit_and_wait_image(
                    prompt,
                    aspect_ratio,
                    retry_images,
                    model=image_model,
                    on_poll=_image_poll_update,
                )
                result["retry_strategy"] = "reduced_reference_images"
                result["retry_reference_count"] = len(retry_images)
                result["previous_attempt"] = previous_attempt
            provider_status = result.get("status") or ("succeeded" if result.get("url") else "failed")
            if not result.get("url") and str(provider_status).lower() in {"completed", "succeeded", "success"}:
                provider_status = "failed"
            if result.get("url"):
                try:
                    cached_url, cache_info = _cache_generated_image_url(
                        result["url"],
                        f"{plan.get('role_name') or plan.get('role_id') or 'role'}-{plan.get('template_name') or plan.get('template_id') or 'wallpaper'}-{index}",
                    )
                    if cached_url:
                        result["original_url"] = result.get("url")
                        result["url"] = cached_url
                        result["cached_url"] = cached_url
                        result["cache"] = cache_info
                except Exception as exc:
                    result["cache_warning"] = f"生成图缓存失败：{exc}"
        except ImageProviderNotConfigured as exc:
            result = {"error": str(exc)}
            provider_status = "failed"
        except Exception as exc:
            result = {"error": str(exc)}
            provider_status = "failed"

        all_warnings = [*ref_warnings, *data_url_warnings]
        if str(provider_status).lower() == "timeout":
            all_warnings.append(
                f"图片接口超过 {_duration_label(settings.image_max_wait)} 仍未返回图片；供应商任务可能仍在后台处理，可用 provider_task.task_id 排查。"
            )
        asset = store.create_asset(
            {
                "product_id": ROLE_WALLPAPER_ACCOUNT_ID,
                "product_name": ROLE_WALLPAPER_ACCOUNT_NAME,
                "type": "wallpaper",
                "title": f"{plan.get('role_name') or '角色'} · {plan.get('template_name') or '壁纸'} {index}",
                "status": "review",
                "style": "role_wallpaper",
                "content": prompt,
                "url": result.get("url") or "",
                "provider_task": result,
                "provider_status": provider_status,
                "variant_id": plan.get("template_id") or "",
                "variant_name": plan.get("template_name") or "",
                "generation_plan": {
                    "kind": "role_wallpaper",
                    **plan,
                    "prompt": prompt,
                    "image_model": image_model or settings.image_model,
                    "image_model_profile": settings.image_model_profile(image_model or settings.image_model),
                    "used_references": used_refs,
                    "reference_warnings": all_warnings,
                    "ip_risk_acknowledged": bool(config.get("ip_risk_acknowledged") or config.get("ipRiskAcknowledged")),
                },
            }
        )
        _persist_role_wallpaper_asset(asset)
        if not is_group_photo and asset.get("url"):
            key = (plan.get("template_id") or "", plan.get("role_id") or "")
            with state_lock:
                if key not in generated_solo_images:
                    generated_solo_images[key] = {
                        "url": asset.get("url"),
                        "asset_id": asset.get("id"),
                        "title": asset.get("title"),
                    }
        nonlocal_update = None
        with state_lock:
            created_assets_by_index[index] = asset
            active_labels.pop(index, None)
            nonlocal_update = missing_reference
        return asset, nonlocal_update

    def _record_completed(result_tuple=None, failed_index=None, failed_error=None):
        nonlocal completed_count, missing_reference_count
        with state_lock:
            completed_count += 1
            if result_tuple and result_tuple[1]:
                missing_reference_count += 1
            if failed_index is not None:
                active_labels.pop(failed_index, None)
            progress = _job_progress()
            detail = (
                f"并发生成中：已完成 {completed_count}/{total}；当前：{_active_summary()}"
                if completed_count < total
                else f"角色壁纸生成收尾中：已完成 {completed_count}/{total}"
            )
        if failed_error:
            detail += f"；有任务异常：{failed_error}"
        store.update_job(job_id, progress=progress, detail=detail)

    def _run_batch(batch, label, workers):
        if not batch:
            return
        if workers <= 1 or len(batch) == 1:
            for index, plan in batch:
                try:
                    _record_completed(_process_plan(index, plan))
                except Exception as exc:
                    _record_completed(failed_index=index, failed_error=str(exc))
            return
        store.update_job(
            job_id,
            progress=_job_progress(),
            detail=f"{label}：{len(batch)} 张任务并发生成中，并发数 {workers}",
        )
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_plan, index, plan): index
                for index, plan in batch
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    _record_completed(future.result())
                except Exception as exc:
                    _record_completed(failed_index=index, failed_error=str(exc))

    solo_plans = [(index, plan) for index, plan in indexed_plans if not _is_group_plan(plan)]
    group_plans = [(index, plan) for index, plan in indexed_plans if _is_group_plan(plan)]
    if solo_plans:
        _run_batch(solo_plans, "单人图", min(concurrency, len(solo_plans)))
    if group_plans:
        store.update_job(
            job_id,
            progress=_job_progress(),
            detail="单人图阶段已完成，正在生成依赖单人图的合照",
        )
        _run_batch(group_plans, "合照", 1)

    created_assets = [
        created_assets_by_index[index]
        for index, _plan in indexed_plans
        if index in created_assets_by_index
    ]
    succeeded = [asset for asset in created_assets if asset.get("url")]
    detail = f"已生成 {len(succeeded)}/{total} 张角色壁纸"
    if missing_reference_count:
        detail += f"，其中 {missing_reference_count} 张没有可用本地参考图"
    if not succeeded:
        detail += "，图片接口没有返回可用图片"
    store.update_job(
        job_id,
        status="completed" if succeeded else "failed",
        progress=100,
        detail=detail,
        result={"asset_ids": [asset["id"] for asset in created_assets]},
    )
