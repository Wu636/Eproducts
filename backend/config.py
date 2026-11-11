import json
import os
from pathlib import Path


CONFIG_DIR = Path(__file__).resolve().parent
LOCAL_PROVIDER_CONFIG = CONFIG_DIR / "provider_config.local.json"


def _load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


for env_path in (
    CONFIG_DIR.parent / ".env",
    CONFIG_DIR.parent / ".env.local",
    CONFIG_DIR / ".env",
    CONFIG_DIR / ".env.local",
):
    _load_env_file(env_path)


def _load_local_provider_config():
    if not LOCAL_PROVIDER_CONFIG.exists():
        return {}
    with LOCAL_PROVIDER_CONFIG.open("r", encoding="utf-8") as file:
        return json.load(file)


def _provider_value(local_config, provider, key, env_name, default=""):
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value
    return local_config.get(provider, {}).get(key, default)


def _provider_bool(local_config, provider, key, env_name, default=True):
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value.lower() not in {"0", "false", "no", "off"}
    value = local_config.get(provider, {}).get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "no", "off"}
    return bool(value)


class Settings:
    """Runtime settings and future model-provider placeholders."""

    TEXT_MODEL_OPTIONS = [
        {
            "id": "claude-sonnet-4-6",
            "label": "Yunwu · Claude Sonnet 4.6（文案推荐）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "gpt-5.5",
            "label": "Yunwu · GPT-5.5（综合旗舰）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "gpt-5.4-mini",
            "label": "Yunwu · GPT-5.4 Mini（质量/速度均衡）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "claude-opus-4-8",
            "label": "Yunwu · Claude Opus 4.8（旗舰创意）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "gemini-3.1-pro-preview",
            "label": "Yunwu · Gemini 3.1 Pro（复杂方案）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "gemini-3.5-flash",
            "label": "Yunwu · Gemini 3.5 Flash（快速稳定）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "qwen3.6-plus",
            "label": "Yunwu · Qwen 3.6 Plus（中文性价比）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "doubao-seed-2-1-pro-260628",
            "label": "Yunwu · 豆包 Seed 2.1 Pro（中文旗舰）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "doubao-seed-2-1-turbo-260628",
            "label": "Yunwu · 豆包 Seed 2.1 Turbo（快速）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "kimi-k2.5",
            "label": "Yunwu · Kimi K2.5（长文策划）",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "mimo-v2.5-pro",
            "label": "MiMo V2.5 Pro",
            "provider": "mimo",
            "api_base": "https://api.xiaomimimo.com/v1",
            "api_key_header": "api-key",
            "api_key_prefix": "",
        },
        {
            "id": "mimo-v2.5-pro-ultraspeed",
            "label": "MiMo V2.5 Pro UltraSpeed",
            "provider": "mimo",
            "api_base": "https://api.xiaomimimo.com/v1",
            "api_key_header": "api-key",
            "api_key_prefix": "",
        },
        {
            "id": "mimo-v2.5",
            "label": "MiMo V2.5 全模态",
            "provider": "mimo",
            "api_base": "https://api.xiaomimimo.com/v1",
            "api_key_header": "api-key",
            "api_key_prefix": "",
        },
        {
            "id": "deepseek-v4-flash",
            "label": "DeepSeek Flash",
            "provider": "deepseek",
            "api_base": "https://api.deepseek.com",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
        {
            "id": "deepseek-v4-pro",
            "label": "DeepSeek Pro",
            "provider": "deepseek",
            "api_base": "https://api.deepseek.com",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        },
    ]
    TEXT_MODELS = {item["id"] for item in TEXT_MODEL_OPTIONS}
    YUNWU_MODELS = {item["id"] for item in TEXT_MODEL_OPTIONS if item["provider"] == "yunwu"}
    MIMO_MODELS = {item["id"] for item in TEXT_MODEL_OPTIONS if item["provider"] == "mimo"}
    DEEPSEEK_MODELS = {item["id"] for item in TEXT_MODEL_OPTIONS if item["provider"] == "deepseek"}
    LEGACY_TEXT_MODELS = {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "claude-3-5-sonnet-20241022",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "deepseek-chat",
        "deepseek-reasoner",
        "ERNIE-4.0-8K",
    }
    VISION_MODEL_OPTIONS = [
        {"id": "gpt-5.5", "label": "GPT-5.5（综合旗舰）", "tier": "quality"},
        {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini（质量/速度均衡）", "tier": "balanced"},
        {"id": "gpt-5.4-nano", "label": "GPT-5.4 Nano（低成本快速）", "tier": "fast"},
        {"id": "claude-opus-4-8", "label": "Claude Opus 4.8（旗舰理解）", "tier": "quality"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6（氛围 Prompt 推荐）", "tier": "recommended"},
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5（快速）", "tier": "fast"},
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro（复杂视觉推荐）", "tier": "recommended"},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash（稳定速度推荐）", "tier": "recommended"},
        {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite（高性价比）", "tier": "fast"},
        {"id": "qwen3.6-plus", "label": "Qwen 3.6 Plus（中文视觉/OCR）", "tier": "recommended"},
        {"id": "qwen3.6-27b", "label": "Qwen 3.6 27B（快速视觉）", "tier": "balanced"},
        {"id": "doubao-seed-2-1-pro-260628", "label": "豆包 Seed 2.1 Pro（多模态旗舰）", "tier": "quality"},
        {"id": "doubao-seed-2-1-turbo-260628", "label": "豆包 Seed 2.1 Turbo（快速）", "tier": "fast"},
        {"id": "kimi-k2.5", "label": "Kimi K2.5（原生多模态）", "tier": "balanced"},
        {"id": "grok-4", "label": "Grok 4（高级视觉推理）", "tier": "quality"},
        {"id": "grok-4-fast-non-reasoning", "label": "Grok 4 Fast（快速识图）", "tier": "fast"},
        {"id": "qvq-max-latest", "label": "QVQ Max Latest（视觉推理）", "tier": "balanced"},
    ]
    LEGACY_VISION_MODELS = {
        "gpt-4o",
        "gpt-4.1",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "qwen3-vl-plus",
        "qwen3-vl-flash",
        "qwen-vl-max",
        "qwen3-vl-235b-a22b-instruct",
        "doubao-seed-1-6-vision-250815",
        "mimo-v2.5",
    }
    IMAGE_MODEL_OPTIONS = [
        {
            "id": "gpt-image-2-vip",
            "label": "Grsai · GPT Image 2 VIP（维护中）",
            "credits_per_image": 1300,
            "note": "官方目录标记为维护中，暂不可选",
            "available": False,
            "create_path": "/v1/draw/completions",
            "image_size": "1K",
        },
        {
            "id": "gpt-image-2",
            "label": "Grsai · GPT Image 2",
            "credits_per_image": 600,
            "note": "1K，文生图/图生图，参考图一致性优先",
            "available": True,
            "create_path": "/v1/draw/completions",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-pro",
            "label": "Grsai · Nano Banana Pro",
            "credits_per_image": 1800,
            "note": "1K/2K/4K，综合稳定",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-2-lite",
            "label": "Grsai · Nano Banana 2 Lite",
            "credits_per_image": 440,
            "note": "轻量低价版",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-pro-vt",
            "label": "Grsai · Nano Banana Pro VT",
            "credits_per_image": 1800,
            "note": "1K/2K/4K，4K 质量好，高峰期可能不稳定",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-fast",
            "label": "Grsai · Nano Banana Fast",
            "credits_per_image": 440,
            "note": "特价快速版，图像编辑能力强",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-2",
            "label": "Grsai · Nano Banana 2",
            "credits_per_image": 1200,
            "note": "1K/2K/4K，综合稳定",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-pro-cl",
            "label": "Grsai · Nano Banana Pro CL",
            "credits_per_image": 10000,
            "note": "1K 稳定渠道",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-2-cl",
            "label": "Grsai · Nano Banana 2 CL",
            "credits_per_image": 6000,
            "note": "1K 稳定渠道",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
        {
            "id": "nano-banana-2-2k-cl",
            "label": "Grsai · Nano Banana 2 2K CL",
            "credits_per_image": 9000,
            "note": "2K 稳定渠道",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "2K",
        },
        {
            "id": "nano-banana-2-4k-cl",
            "label": "Grsai · Nano Banana 2 4K CL",
            "credits_per_image": 13000,
            "note": "4K 稳定渠道",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "4K",
        },
        {
            "id": "nano-banana-pro-4k-vip",
            "label": "Grsai · Nano Banana Pro 4K VIP",
            "credits_per_image": 18000,
            "note": "4K 高成本稳定渠道",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "4K",
        },
        {
            "id": "nano-banana-pro-vip",
            "label": "Grsai · Nano Banana Pro VIP",
            "credits_per_image": 10000,
            "note": "1K/2K 高成本稳定渠道",
            "available": True,
            "create_path": "/v1/draw/nano-banana",
            "image_size": "1K",
        },
    ]

    @classmethod
    def text_model_profile(cls, model):
        for item in cls.TEXT_MODEL_OPTIONS:
            if item["id"] == model:
                return item
        return {
            "id": model or "claude-sonnet-4-6",
            "label": f"Yunwu · {model or 'claude-sonnet-4-6'}",
            "provider": "yunwu",
            "api_base": "https://yunwu.ai/v1",
            "api_key_header": "Authorization",
            "api_key_prefix": "Bearer ",
        }

    @classmethod
    def text_model_list(cls):
        return [{"id": item["id"], "label": item["label"], "provider": item["provider"]} for item in cls.TEXT_MODEL_OPTIONS]

    @classmethod
    def vision_model_list(cls):
        return [dict(item) for item in cls.VISION_MODEL_OPTIONS]

    @classmethod
    def _normalise_image_model_options(cls, configured):
        merged = []

        def push(item):
            if not isinstance(item, dict):
                return
            model_id = str(item.get("id") or item.get("model") or "").strip()
            if not model_id:
                return
            existing = next((index for index, model in enumerate(merged) if model["id"] == model_id), -1)
            credits = item.get("credits_per_image", item.get("creditsPerImage", item.get("credits")))
            if credits in ("", "unknown", "未知"):
                credits = None
            try:
                credits = None if credits is None else int(credits)
            except (TypeError, ValueError):
                credits = None
            if existing >= 0:
                updated = dict(merged[existing])
                if item.get("label") or item.get("name"):
                    updated["label"] = str(item.get("label") or item.get("name")).strip()
                if any(key in item for key in ("credits_per_image", "creditsPerImage", "credits")):
                    updated["credits_per_image"] = credits
                if item.get("note") is not None or item.get("description") is not None:
                    updated["note"] = str(item.get("note") or item.get("description") or "").strip()
                if "available" in item:
                    updated["available"] = item.get("available") is not False
                if item.get("create_path") or item.get("createPath"):
                    updated["create_path"] = str(item.get("create_path") or item.get("createPath")).strip()
                if item.get("image_size") or item.get("imageSize"):
                    updated["image_size"] = str(item.get("image_size") or item.get("imageSize")).strip()
                merged[existing] = updated
                return
            normalised = {
                "id": model_id,
                "label": str(item.get("label") or item.get("name") or model_id).strip(),
                "credits_per_image": credits,
                "note": str(item.get("note") or item.get("description") or "").strip(),
                "available": item.get("available") is not False,
                "create_path": str(item.get("create_path") or item.get("createPath") or "").strip(),
                "image_size": str(item.get("image_size") or item.get("imageSize") or "").strip(),
            }
            merged.append(normalised)

        for item in cls.IMAGE_MODEL_OPTIONS:
            push(item)
        if isinstance(configured, list):
            for item in configured:
                push(item)
        return merged

    def __init__(self):
        local_config = _load_local_provider_config()
        self._local_text_config = local_config.get("text", {})
        self._local_image_config = local_config.get("image", {})
        self.host = os.getenv("XHS_API_HOST", "127.0.0.1")
        self.port = int(os.getenv("XHS_API_PORT", "8787"))
        self.cors_origin = os.getenv("XHS_CORS_ORIGIN", "*")

        # Text copywriting: Yunwu relay first; MiMo / DeepSeek remain fallback options.
        self.text_provider = _provider_value(local_config, "text", "provider", "XHS_TEXT_PROVIDER", "yunwu")
        self.text_model = _provider_value(local_config, "text", "model", "XHS_TEXT_MODEL", "claude-sonnet-4-6")
        # Reference-image analysis stays on a vision-capable model even when
        # routine copywriting is switched to a cheaper text-only model.
        self.text_vision_model = _provider_value(
            local_config,
            "text",
            "vision_model",
            "XHS_VISION_MODEL",
            "gemini-3.5-flash",
        ) or "gemini-3.5-flash"
        if self.text_vision_model in self.LEGACY_VISION_MODELS:
            self.text_vision_model = "gemini-3.5-flash"
        provider_name = self.text_provider.strip().lower()
        if not self.text_model:
            self.text_model = "claude-sonnet-4-6"
        elif provider_name == "yunwu" and self.text_model in self.LEGACY_TEXT_MODELS:
            self.text_model = "claude-sonnet-4-6"
        elif self.text_model not in self.TEXT_MODELS and provider_name != "yunwu":
            self.text_model = "deepseek-v4-flash" if provider_name == "deepseek" else "mimo-v2.5-pro"
        profile = self.text_model_profile(self.text_model)
        if not self.text_provider:
            self.text_provider = profile["provider"]
        self.text_api_base = _provider_value(
            local_config,
            "text",
            "api_base",
            "XHS_TEXT_API_BASE",
            profile["api_base"],
        )
        self.text_api_key_header = _provider_value(
            local_config,
            "text",
            "api_key_header",
            "XHS_TEXT_API_KEY_HEADER",
            profile["api_key_header"],
        )
        self.text_api_key_prefix = _provider_value(
            local_config,
            "text",
            "api_key_prefix",
            "XHS_TEXT_API_KEY_PREFIX",
            profile["api_key_prefix"],
        )
        self.text_api_key = self._text_key_for_provider(self.text_provider)
        self.text_ssl_verify = _provider_bool(local_config, "text", "ssl_verify", "XHS_TEXT_SSL_VERIFY", True)
        # Vision analysis always uses the Yunwu connection. It must not follow
        # runtime switches to the optional direct MiMo/DeepSeek text providers.
        self.vision_provider = "yunwu"
        self.vision_api_base = _provider_value(
            local_config,
            "text",
            "vision_api_base",
            "XHS_VISION_API_BASE",
            "https://yunwu.ai/v1",
        ) or "https://yunwu.ai/v1"
        self.vision_api_key = self._text_key_for_provider("yunwu")
        self.vision_api_key_header = "Authorization"
        self.vision_api_key_prefix = "Bearer "
        self.vision_ssl_verify = self.text_ssl_verify

        # Image generation: Grsai GPT Image API.
        self.image_provider = _provider_value(local_config, "image", "provider", "XHS_IMAGE_PROVIDER", "grsai_gpt_image")
        self.image_api_base = _provider_value(
            local_config,
            "image",
            "api_base",
            "XHS_IMAGE_API_BASE",
            "https://grsai.dakka.com.cn",
        )
        self.image_api_key = _provider_value(local_config, "image", "api_key", "XHS_IMAGE_API_KEY", "")
        self.image_model = _provider_value(local_config, "image", "model", "XHS_IMAGE_MODEL", "gpt-image-2")
        self.image_create_path = _provider_value(
            local_config,
            "image",
            "create_path",
            "XHS_IMAGE_CREATE_PATH",
            "/v1/draw/completions",
        )
        self.image_model_options = self._normalise_image_model_options(
            self._local_image_config.get("models") or self._local_image_config.get("model_options")
        )
        configured_image_profile = next(
            (item for item in self.image_model_options if item["id"] == self.image_model),
            None,
        )
        if configured_image_profile and configured_image_profile.get("available") is False:
            self.image_model = "gpt-image-2"
        if self.image_model and not any(item["id"] == self.image_model for item in self.image_model_options):
            self.image_model_options.insert(
                0,
                {
                    "id": self.image_model,
                    "label": f"Grsai · {self.image_model}",
                    "credits_per_image": None,
                    "note": "本地配置中的自定义模型",
                    "available": True,
                    "create_path": self.image_create_path,
                    "image_size": "1K",
                },
            )
        self.image_result_path = _provider_value(
            local_config,
            "image",
            "result_path",
            "XHS_IMAGE_RESULT_PATH",
            "/v1/draw/result",
        )
        self.image_api_key_header = _provider_value(
            local_config,
            "image",
            "api_key_header",
            "XHS_IMAGE_API_KEY_HEADER",
            "Authorization",
        )
        self.image_api_key_prefix = _provider_value(
            local_config,
            "image",
            "api_key_prefix",
            "XHS_IMAGE_API_KEY_PREFIX",
            "Bearer ",
        )
        self.image_ssl_verify = _provider_bool(local_config, "image", "ssl_verify", "XHS_IMAGE_SSL_VERIFY", True)
        self.image_poll_interval = max(2, int(os.getenv("XHS_IMAGE_POLL_INTERVAL", "5")))
        self.image_max_wait = max(300, int(os.getenv("XHS_IMAGE_MAX_WAIT", "2400")))
        self.image_concurrency = max(1, min(8, int(os.getenv("XHS_IMAGE_CONCURRENCY", "3"))))

        # Dance video generation: Alibaba Cloud Model Studio AnimateAnyone (Beijing region).
        self.video_provider = _provider_value(
            local_config, "video", "provider", "XHS_VIDEO_PROVIDER", "aliyun_dashscope_animate_anyone"
        ) or "aliyun_dashscope_animate_anyone"
        self.video_api_base = _provider_value(
            local_config, "video", "api_base", "XHS_VIDEO_API_BASE", "https://dashscope.aliyuncs.com/api/v1"
        ) or "https://dashscope.aliyuncs.com/api/v1"
        self.video_api_key = _provider_value(local_config, "video", "api_key", "XHS_VIDEO_API_KEY", "")
        if not self.video_api_key:
            self.video_api_key = os.getenv("DASHSCOPE_API_KEY", "")
        self.video_model = _provider_value(
            local_config, "video", "model", "XHS_VIDEO_MODEL", "animate-anyone-gen2"
        ) or "animate-anyone-gen2"
        self.video_detect_model = _provider_value(
            local_config,
            "video",
            "detect_model",
            "XHS_VIDEO_DETECT_MODEL",
            "animate-anyone-detect-gen2",
        ) or "animate-anyone-detect-gen2"
        self.video_template_model = _provider_value(
            local_config,
            "video",
            "template_model",
            "XHS_VIDEO_TEMPLATE_MODEL",
            "animate-anyone-template-gen2",
        ) or "animate-anyone-template-gen2"
        self.video_motion_model = _provider_value(
            local_config,
            "video",
            "motion_model",
            "XHS_VIDEO_MOTION_MODEL",
            "wan2.2-animate-move",
        ) or "wan2.2-animate-move"
        self.video_ssl_verify = _provider_bool(local_config, "video", "ssl_verify", "XHS_VIDEO_SSL_VERIFY", True)
        self.video_poll_interval = max(2, int(os.getenv("XHS_VIDEO_POLL_INTERVAL", "5")))
        self.video_max_wait = max(60, int(os.getenv("XHS_VIDEO_MAX_WAIT", "1800")))

        # Database/storage backend. Keep service role keys on the backend only.
        self.storage_backend = os.getenv("XHS_STORAGE_BACKEND", "memory").strip().lower()
        self.supabase_url = os.getenv("XHS_SUPABASE_URL", "").rstrip("/")
        self.supabase_service_role_key = os.getenv("XHS_SUPABASE_SERVICE_ROLE_KEY", "")
        self.supabase_storage_bucket = os.getenv("XHS_SUPABASE_STORAGE_BUCKET", "xhs-assets")
        self.supabase_ssl_verify = os.getenv("XHS_SUPABASE_SSL_VERIFY", "true").lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        self.supabase_seed_sample = os.getenv("XHS_SUPABASE_SEED_SAMPLE", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def set_text_model(self, model):
        model = str(model or "").strip()
        if not model:
            raise ValueError("不支持的文字模型")
        profile = self.text_model_profile(model)
        self.text_model = model
        self.text_provider = profile["provider"]
        self.text_api_base = profile["api_base"]
        self.text_api_key_header = profile["api_key_header"]
        self.text_api_key_prefix = profile["api_key_prefix"]
        self.text_api_key = self._text_key_for_provider(self.text_provider)
        return self.text_model

    def set_vision_model(self, model):
        model = str(model or "").strip()
        if not model or len(model) > 160 or not all(char.isalnum() or char in "._-*" for char in model):
            raise ValueError("视觉模型 ID 不正确")
        self.text_vision_model = model
        return self.text_vision_model

    def image_model_list(self):
        return [dict(item) for item in self.image_model_options]

    def image_model_profile(self, model=None):
        model = str(model or self.image_model or "").strip()
        for item in self.image_model_options:
            if item["id"] == model:
                return dict(item)
        return {
            "id": model or "gpt-image-2",
            "label": f"Grsai · {model or 'gpt-image-2'}",
            "credits_per_image": None,
            "note": "自定义模型，积分以 Grsai 控制台为准",
            "available": True,
            "create_path": self.image_create_path,
            "image_size": "1K",
        }

    def image_create_path_for(self, model=None):
        profile = self.image_model_profile(model)
        return profile.get("create_path") or self.image_create_path

    def set_image_model(self, model):
        model = str(model or "").strip()
        if not model or len(model) > 160 or not all(char.isalnum() or char in "._:-*" for char in model):
            raise ValueError("生图模型 ID 不正确")
        profile = self.image_model_profile(model)
        if profile.get("available") is False:
            raise ValueError(f"{profile.get('label') or model} 当前维护中，暂不可用")
        self.image_model = model
        if not any(item["id"] == model for item in self.image_model_options):
            self.image_model_options.insert(0, self.image_model_profile(model))
        return self.image_model

    def _text_key_for_provider(self, provider):
        provider = (provider or "").strip().lower()
        text_config = self._local_text_config
        if provider == "deepseek":
            return (
                os.getenv("XHS_TEXT_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY")
                or text_config.get("deepseek_api_key", "")
                or text_config.get("api_key", "")
            )
        if provider == "mimo":
            return (
                os.getenv("XHS_TEXT_API_KEY")
                or os.getenv("MIMO_API_KEY")
                or os.getenv("XHS_MIMO_API_KEY")
                or text_config.get("mimo_api_key", "")
                or text_config.get("api_key", "")
            )
        if provider == "yunwu":
            return (
                os.getenv("XHS_TEXT_API_KEY")
                or os.getenv("YUNWU_API_KEY")
                or os.getenv("XHS_YUNWU_API_KEY")
                or text_config.get("yunwu_api_key", "")
            )
        return os.getenv("XHS_TEXT_API_KEY") or text_config.get("api_key", "")

    def provider_status(self):
        return {
            "text": {
                "configured": bool(self.text_api_base and self.text_api_key),
                "provider": self.text_provider,
                "api_base": self.text_api_base,
                "model": self.text_model,
                "vision_model": self.text_vision_model,
                "vision_models": self.vision_model_list(),
                "models": self.text_model_list(),
                "api_key_header": self.text_api_key_header,
                "ssl_verify": self.text_ssl_verify,
            },
            "image": {
                "configured": bool(self.image_api_base and self.image_api_key),
                "provider": self.image_provider,
                "api_base": self.image_api_base,
                "model": self.image_model,
                "models": self.image_model_list(),
                "model_profile": self.image_model_profile(),
                "create_path": self.image_create_path,
                "result_path": self.image_result_path,
                "ssl_verify": self.image_ssl_verify,
            },
            "vision": {
                "configured": bool(self.vision_api_base and self.vision_api_key and self.text_vision_model),
                "provider": self.vision_provider,
                "api_base": self.vision_api_base,
                "model": self.text_vision_model,
                "models": self.vision_model_list(),
                "api_key_header": self.vision_api_key_header,
                "ssl_verify": self.vision_ssl_verify,
            },
            "video": {
                "configured": bool(
                    self.video_api_base
                    and self.video_api_key
                    and self.video_model
                    and self.video_detect_model
                    and self.video_template_model
                    and self.video_motion_model
                ),
                "provider": self.video_provider,
                "api_base": self.video_api_base,
                "model": self.video_model,
                "detect_model": self.video_detect_model,
                "template_model": self.video_template_model,
                "motion_model": self.video_motion_model,
                "ssl_verify": self.video_ssl_verify,
            },
            "database": {
                "configured": self.storage_backend == "supabase"
                and bool(self.supabase_url and self.supabase_service_role_key),
                "provider": self.storage_backend,
                "supabase_url": self.supabase_url,
                "storage_bucket": self.supabase_storage_bucket,
                "ssl_verify": self.supabase_ssl_verify,
            },
        }


settings = Settings()
