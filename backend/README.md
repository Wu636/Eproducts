# 小红书素材生成库后端接口

这是第一版后端接口骨架，暂时不依赖 FastAPI 等第三方库，直接用 Python 标准库运行。

## 启动

```bash
python3 backend/server.py --host 127.0.0.1 --port 8787
```

健康检查：

```bash
curl http://127.0.0.1:8787/api/health
```

## 已有接口

- `GET /api/health`
- `GET /api/provider-status`
- `GET /api/database-status`
- `GET /api/products`
- `POST /api/products`
- `GET /api/products/{id}`
- `PATCH /api/products/{id}`
- `POST /api/uploads`
- `GET /api/assets?product_id=&type=&status=`
- `PATCH /api/assets/{id}/status`
- `GET /api/note-packages?product_id=&status=`
- `PATCH /api/note-packages/{id}/status`
- `GET /api/generation/jobs?status=`
- `GET /api/generation/jobs/{id}`
- `POST /api/generation/jobs`

## 模型接口预留

### 本地填写 API Key

复制模板：

```bash
cp backend/provider_config.local.json.template backend/provider_config.local.json
```

然后在 `backend/provider_config.local.json` 里填写：

```json
{
  "text": {
    "provider": "xiaomi_mimo",
    "api_base": "https://token-plan-cn.xiaomimimo.com/v1",
    "api_key": "填小米 MiMo API Key",
    "model": "mimo-v2.5",
    "api_key_header": "Authorization",
    "api_key_prefix": "Bearer "
  },
  "image": {
    "provider": "grsai_gpt_image",
    "api_base": "https://grsai.dakka.com.cn",
    "api_key": "填 Grsai API Key",
    "model": "gpt-image-2",
    "create_path": "/v1/draw/completions",
    "result_path": "/v1/draw/result",
    "api_key_header": "Authorization",
    "api_key_prefix": "Bearer "
  }
}
```

`provider_config.local.json` 已加入 `.gitignore`，不要提交真实 key。

修改 `provider_config.local.json` 后需要重启后端服务，配置才会重新读取。

### 环境变量配置

也可以用环境变量覆盖本地 JSON：

```bash
export XHS_TEXT_API_BASE="https://token-plan-cn.xiaomimimo.com/v1"
export XHS_TEXT_API_KEY=""
export XHS_TEXT_MODEL="mimo-v2.5"
export XHS_TEXT_API_KEY_HEADER="Authorization"
export XHS_TEXT_API_KEY_PREFIX="Bearer "

export XHS_IMAGE_API_BASE="https://grsai.dakka.com.cn"
export XHS_IMAGE_API_KEY=""
export XHS_IMAGE_MODEL="gpt-image-2"
export XHS_IMAGE_CREATE_PATH="/v1/draw/completions"
export XHS_IMAGE_RESULT_PATH="/v1/draw/result"

export XHS_VIDEO_API_BASE=""
export XHS_VIDEO_API_KEY=""
```

### 测试 provider

查看配置状态，不会返回 API Key：

```bash
curl http://127.0.0.1:8787/api/provider-status
```

测试小米 MiMo 文案生成：

```bash
curl -X POST http://127.0.0.1:8787/api/providers/text/test \
  -H "Content-Type: application/json" \
  -d '{"angle":"生活化种草","persona":"真实自用"}'
```

文案模型默认使用 `mimo-v2.5`，因为该模型支持图像理解。前端上传产品图时会把图片转为 data URL，同步到后端后随 `messages[].content` 的 `image_url` 一起传给 MiMo。

如果你使用的是官方 OpenAI API 文档里的普通 API Key，可以把 `api_base` 改成：

```json
"api_base": "https://api.xiaomimimo.com/v1"
```

如果你使用 Token Plan 专属 key，则保留控制台显示的 Token Plan Base URL。

### macOS Python 证书问题

如果真实接口失败并出现类似：

```text
CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate
```

说明 Python 本地 CA 证书链不可用。开发阶段可以在 `backend/provider_config.local.json` 里临时设置：

```json
"ssl_verify": false
```

已经给本地配置加了这个字段。正式部署建议安装 CA/certifi 后改回 `true`。

### 快速定位真实失败原因

后端启动后运行：

```bash
curl -s http://127.0.0.1:8787/api/provider-status
```

确认 `text.configured` 为 `true`、`text.model` 为 `mimo-v2.5`。

再运行：

```bash
curl -s -X POST http://127.0.0.1:8787/api/providers/text/test \
  -H "Content-Type: application/json" \
  -d '{"angle":"生活化种草","persona":"真实自用"}'
```

如果这里返回 `error`，前端生成一定会 fallback 到 Mock；先按这个 error 修。

测试 Grsai 生图任务提交：

```bash
curl -X POST http://127.0.0.1:8787/api/providers/image/create \
  -H "Content-Type: application/json" \
  -d '{"prompt":"小红书电商保温杯封面图，3:4，清新真实商品摄影","size":"auto"}'
```

查询 Grsai 生图结果：

```bash
curl -X POST http://127.0.0.1:8787/api/providers/image/result \
  -H "Content-Type: application/json" \
  -d '{"task_id":"替换为创建接口返回的任务 id"}'
```

服务层入口：

- 文案适配器：`backend/services/text_provider.py`
- 生图适配器：`backend/services/image_provider.py`
- 生成任务编排：`backend/services/mock_generation.py`

生视频接口暂时留空，等 provider/API key 确定后再加。

## Supabase 数据库 / Storage

这一版支持两种存储模式：

- `memory`：默认模式，数据存在本地后端内存里，重启后丢失。
- `supabase`：产品、款式、素材、任务、笔记包写入 Supabase；上传的 data URL 图片会自动上传到 Supabase Storage。

### 1. 建表

在 Supabase 控制台打开 SQL Editor，执行：

```sql
-- 文件位置：backend/supabase_schema.sql
```

这份 SQL 会创建：

- `products`
- `assets`
- `note_packages`
- `generation_jobs`
- `uploads`
- `template_prompts`
- `xhs-assets` Storage bucket

### 2. 配置本地环境变量

复制模板：

```bash
cp .env.example .env.local
```

然后填写：

```bash
XHS_STORAGE_BACKEND=supabase
XHS_SUPABASE_URL=https://你的项目.supabase.co
XHS_SUPABASE_SERVICE_ROLE_KEY=你的 service_role key
XHS_SUPABASE_STORAGE_BUCKET=xhs-assets
```

`service_role key` 只能放在后端本地或部署环境变量里，不能写进前端 HTML，也不能提交到 GitHub。

### 3. 重启后端

```bash
python3 backend/server.py --host 127.0.0.1 --port 8787
```

检查数据库状态：

```bash
curl http://127.0.0.1:8787/api/database-status
```

如果返回 `backend: "supabase"`，说明后端已经切到 Supabase。

## 前端生成链路

前端点击“开始生成”时会优先调用：

1. `POST /api/products` 同步当前产品资料
2. `POST /api/generation/jobs` 创建后端生成任务
3. `GET /api/generation/jobs/{id}` 轮询任务状态
4. `GET /api/assets?product_id=...` 和 `GET /api/note-packages?product_id=...` 拉取结果

如果后端没启动或接口报错，前端才会 fallback 到本地 Mock。
