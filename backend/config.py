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

    def __init__(self):
        local_config = _load_local_provider_config()
        self.host = os.getenv("XHS_API_HOST", "127.0.0.1")
        self.port = int(os.getenv("XHS_API_PORT", "8787"))
        self.cors_origin = os.getenv("XHS_CORS_ORIGIN", "*")

        # Text copywriting: Xiaomi MiMo OpenAI-compatible protocol.
        self.text_provider = _provider_value(local_config, "text", "provider", "XHS_TEXT_PROVIDER", "xiaomi_mimo")
        self.text_api_base = _provider_value(
            local_config,
            "text",
            "api_base",
            "XHS_TEXT_API_BASE",
            "https://token-plan-cn.xiaomimimo.com/v1",
        )
        self.text_api_key = _provider_value(local_config, "text", "api_key", "XHS_TEXT_API_KEY", "")
        self.text_model = _provider_value(local_config, "text", "model", "XHS_TEXT_MODEL", "mimo-v2.5")
        self.text_api_key_header = _provider_value(
            local_config,
            "text",
            "api_key_header",
            "XHS_TEXT_API_KEY_HEADER",
            "Authorization",
        )
        self.text_api_key_prefix = _provider_value(
            local_config,
            "text",
            "api_key_prefix",
            "XHS_TEXT_API_KEY_PREFIX",
            "Bearer ",
        )
        self.text_ssl_verify = _provider_bool(local_config, "text", "ssl_verify", "XHS_TEXT_SSL_VERIFY", True)

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

        # Video generation is intentionally left blank until the provider is chosen.
        self.video_provider = _provider_value(local_config, "video", "provider", "XHS_VIDEO_PROVIDER", "")
        self.video_api_base = _provider_value(local_config, "video", "api_base", "XHS_VIDEO_API_BASE", "")
        self.video_api_key = _provider_value(local_config, "video", "api_key", "XHS_VIDEO_API_KEY", "")
        self.video_model = _provider_value(local_config, "video", "model", "XHS_VIDEO_MODEL", "")

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

    def provider_status(self):
        return {
            "text": {
                "configured": bool(self.text_api_base and self.text_api_key),
                "provider": self.text_provider,
                "api_base": self.text_api_base,
                "model": self.text_model,
                "api_key_header": self.text_api_key_header,
                "ssl_verify": self.text_ssl_verify,
            },
            "image": {
                "configured": bool(self.image_api_base and self.image_api_key),
                "provider": self.image_provider,
                "api_base": self.image_api_base,
                "model": self.image_model,
                "create_path": self.image_create_path,
                "result_path": self.image_result_path,
                "ssl_verify": self.image_ssl_verify,
            },
            "video": {
                "configured": bool(self.video_api_base and self.video_api_key),
                "provider": self.video_provider,
                "api_base": self.video_api_base,
                "model": self.video_model,
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
