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
- `GET/POST /api/providers/vision/model`
- `GET/POST /api/providers/image/model`
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
- `POST /api/dance/workflows`
- `GET /api/dance/workflows/{id}`
- `GET /api/dance/tasks/{task_id}`
- `POST /api/commerce-learning/analyze`
- `POST /api/commerce-learning/normalize-samples`
- `POST /api/commerce-learning/market-opportunities`
- `POST /api/commerce-learning/run-cycle`
- `POST /api/commerce-learning/video-workflow`
- `POST /api/commerce-learning/feedback`
- `POST /api/commerce-learning/clipforge-export`
- `POST /api/commerce-learning/clipforge-project`
- `GET /api/commerce-learning/clipforge-status`
- `GET /api/role-wallpaper/roles`
- `GET /api/role-wallpaper/templates`
- `GET /api/role-wallpaper/references?role_id=&usage=&template_id=`
- `GET /api/role-wallpaper/references/{reference_id}/file`
- `POST /api/role-wallpaper/plans`
- `POST /api/role-wallpaper/reference-prompt` (`action=analyze|expand`)
- `POST /api/role-wallpaper/images`
- `GET /api/role-wallpaper/assets`

## 恋与深空角色壁纸工作台（MVP）

这一版先提供后端能力，供前端新增“角色壁纸工作台”页面调用。

### 参考图放哪里

把你提供的角色图放到项目内：

```text
reference_library/role_wallpapers/
  roles/
    xavier/                # 沈星回：完整参考图可直接放这里
      01.png
      02.jpg
      complete/            # 或者统一放 complete/，效果一样
    xavier/identity/       # 可选增强：脸、发型、五官、体态
    xavier/outfit/         # 可选增强：服装、材质、配色
    xavier/expression/     # 可选增强：表情、眼神
    xavier/pose/           # 可选增强：姿态、构图、身体比例
    xavier/mood/           # 可选增强：光影、氛围
    rafayel/...            # 祁煜
    zayne/...              # 黎深
    sylus/...              # 秦彻
    caleb/...              # 夏以昼
```

支持 `.png`、`.jpg`、`.jpeg`、`.webp`、`.gif`、`.bmp`。真实图片已被 `.gitignore` 忽略，避免误提交官方图或二创参考图。

你不需要手工拆分 `identity/outfit/expression/pose/mood`。这些目录只是高级可选项。直接放在 `roles/{role_id}/` 或 `roles/{role_id}/complete/` 的图片会被识别为 `complete` 综合参考图，正式出图时会自动作为脸、发型、体态、服装和整体气质参考。

如果某个角色（比如秦彻 `sylus`）放了十几张 `complete` 图，系统不会把所有图片一次性塞给生图模型，也不会固定只用第一张。默认策略是：

- 每张成图最多携带 5 张参考图；
- 其中 `complete` 综合参考默认抽 3 张；
- 当同一角色一次生成多张时，会按第 1/2/3/4 张成图自动轮换参考图组合，让十几张素材逐步被覆盖；
- 如果 Grsai 首次未返回图片，系统会自动减少到 2 张核心参考图再重试一次；
- 如果后续补了 `identity/outfit/expression/pose/mood`，这些分类参考会在剩余名额里自动追加。

前端也支持“手动选择参考图”：切到单角色生成后，展开参考图选择器，从该角色本地资料库里点选图片即可。手选最多使用 6 张，顺序会保留；后端同样会做 6 张上限保护。五角色批量生成时默认使用自动轮换。

参考图反推 Prompt 时，前端可以勾选是否从参考图人物里提取“人物身份/角色感、脸型五官、发型发色、原服装细节”。场景、构图、镜头、光影、配色和氛围会默认提取；人物维度默认全选，适合原角色图，但也可以关闭以只借用场景氛围。

五角色模式可追加一张 `16:9` 或 `16:10` 五人合照，形成“5 张同风格单人图 + 1 张宽幅群像”。五张单人图共享同一视觉锚点；合照按角色固定左右顺序，并为每个角色各取一张 complete 身份参考。若任一角色没有本地参考图，合照方案默认不勾选并显示缺失角色，避免误耗生图积分。

五角色批量模式支持“逐角色手选”：每个角色最多手选 3 张，单人图只使用该角色所选参考图；合照不会再直接混用五组原始资料图，而是在同一生成任务中等待五张单人图完成，再将这五张本批次新图按角色顺序作为合照参考。任何一张单人图失败时，合照会暂停并提示缺失角色，避免生成串脸的低质量群像。

参考图完成多模态拆解后，可在前端选择“其他四人”或任意目标角色，把该图的场景、构图、镜头、光影、色板、材质与氛围跨角色套用。来源人物的脸、发型、身材和服装不会迁移；每个目标角色仍使用自己的本地参考图库锁定身份。

已生成角色壁纸支持多选，并通过 `GET /api/assets/archive?ids=<asset_id,...>` 打包下载 ZIP。服务端会优先读取本地缓存或持久化素材；个别图片失效时，其余可用图片仍会写入压缩包，并附带 `download-errors.txt`。

画幅支持手机、平板、电脑壁纸常用比例，也支持自定义 `宽:高` 字符串，例如 `2:3`、`16:10`、`1920:1080`。

### 查看五个角色卡

```bash
curl http://127.0.0.1:8787/api/role-wallpaper/roles
```

内置角色：

- `xavier`：沈星回
- `rafayel`：祁煜
- `zayne`：黎深
- `sylus`：秦彻
- `caleb`：夏以昼

每个角色卡包含：

- `visual_identity`：脸、发型、眼睛、体态、服装等识别点
- `personality_hooks`：角色背景与情绪钩子
- `fan_preference_angles`：玩家喜爱点与内容投放角度
- `preferred_template_tags`：适配通用模板的标签
- `role_specific_template_ideas`：后续可扩展的角色专属场景模板方向
- `avoid_prompt_notes`：避免跑偏的负向约束
- `risk_profile`：粉丝向 / IP 风险标记

后续如果要把“专属模板”做成正式可选模板，可以把 `role_specific_template_ideas` 里的方向迁移到 `templates`，并增加 `role_ids` 字段限定角色。

### 查看 22 个通用场景模板

```bash
curl http://127.0.0.1:8787/api/role-wallpaper/templates
```

内置模板：

- `bedroom_morning`：卧室晨光
- `rain_window`：雨夜落地窗
- `sofa_companion`：沙发陪伴
- `kitchen_turnback`：厨房回眸
- `late_study`：深夜书房
- `floral_wedding_window`：花窗婚礼
- `starry_wedding_window`：星穹花窗礼堂
- `glasshouse_wedding`：玻璃温室婚礼
- `moon_crystal_chapel`：月下水晶圣堂
- `deepsea_wedding_window`：海底花窗誓约厅
- `snow_rose_chapel`：雪夜玫瑰教堂
- `mist_forest_chapel`：晨雾森林礼堂
- `rose_library_vow`：玫瑰图书馆誓约
- `mirror_lake_window`：镜湖花窗仪式台
- `sky_bell_tower_garden`：空中钟楼花园
- `white_gold_wing_chapel`：白金圣翼礼堂
- `bath_mist`：浴室水雾
- `balcony_breeze`：阳台微风
- `entrance_homecoming`：玄关等你回家
- `car_night`：车内夜景
- `cafe_afternoon`：咖啡馆午后
- `clean_lock_screen`：干净锁屏留白

### 扫描参考图

```bash
curl 'http://127.0.0.1:8787/api/role-wallpaper/references?role_id=xavier'
curl 'http://127.0.0.1:8787/api/role-wallpaper/references?role_id=xavier&usage=complete'
```

### 一键为五个角色生成同一模板方案

此步骤只生成可审核 prompt，不调用图片接口，不消耗生图额度。

```bash
curl -X POST http://127.0.0.1:8787/api/role-wallpaper/plans \
  -H "Content-Type: application/json" \
  -d '{
    "role_ids": "all",
    "template_id": "bedroom_morning",
    "count_per_role": 1,
    "aspect_ratio": "9:16"
  }'
```

### 单角色、多模板生成方案

```bash
curl -X POST http://127.0.0.1:8787/api/role-wallpaper/plans \
  -H "Content-Type: application/json" \
  -d '{
    "role_ids": ["sylus"],
    "template_ids": ["rain_window", "car_night", "entrance_homecoming"],
    "aspect_ratio": "9:16",
    "user_notes": "黑红氛围强一点，但不要血腥暴力"
  }'
```

### 正式出图

把 `/plans` 返回的 `plans` 审核/编辑后传入：

```bash
curl -X POST http://127.0.0.1:8787/api/role-wallpaper/images \
  -H "Content-Type: application/json" \
  -d '{
    "plans": [替换为审核后的 plan 对象],
    "reference_limit_per_usage": 2,
    "complete_reference_limit": 3,
    "reference_limit": 5,
    "auto_retry_with_fewer_references": true,
    "reference_ids": ["可选：手动选中的参考图 id，最多 6 张"],
    "ip_risk_acknowledged": true
  }'
```

后台会启动异步任务，生成结果会进入 `GET /api/role-wallpaper/assets` 和通用素材库。每个生成素材都会保留 prompt、使用过的参考图列表、风险标记和 provider 原始返回。

> 风险提示：角色、名称、官方美术和相关素材属于权利方。系统默认把原角色相关输出标记为 `high_ip_risk` / `粉丝向二创展示`，不建议公开售卖高度贴脸角色图。

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
    "provider": "yunwu",
    "api_base": "https://yunwu.ai/v1",
    "yunwu_api_key": "填云雾 API 令牌",
    "mimo_api_key": "可选：MiMo API Key",
    "deepseek_api_key": "可选：DeepSeek API Key",
    "api_key": "",
    "model": "claude-sonnet-4-6",
    "vision_model": "gemini-3.5-flash",
    "api_key_header": "Authorization",
    "api_key_prefix": "Bearer "
  },
  "image": {
    "provider": "grsai_gpt_image",
    "api_base": "https://grsai.dakka.com.cn",
    "api_key": "填 Grsai API Key",
    "model": "gpt-image-2",
    "models": [
      {
        "id": "gpt-image-2",
        "label": "Grsai · GPT Image 2",
        "credits_per_image": 600,
        "note": "如 Grsai 控制台价格变化，请以控制台为准"
      }
    ],
    "create_path": "/v1/draw/completions",
    "result_path": "/v1/draw/result",
    "api_key_header": "Authorization",
    "api_key_prefix": "Bearer "
  },
  "video": {
    "provider": "aliyun_dashscope_animate_anyone",
    "api_base": "https://dashscope.aliyuncs.com/api/v1",
    "api_key": "填华北 2（北京）地域的百炼 API Key",
    "model": "animate-anyone-gen2",
    "detect_model": "animate-anyone-detect-gen2",
    "template_model": "animate-anyone-template-gen2",
    "motion_model": "wan2.2-animate-move",
    "ssl_verify": true
  }
}
```

`provider_config.local.json` 已加入 `.gitignore`，不要提交真实 key。

修改 `provider_config.local.json` 后需要重启后端服务，配置才会重新读取。

### 环境变量配置

也可以用环境变量覆盖本地 JSON：

```bash
export XHS_TEXT_PROVIDER="yunwu"
export XHS_TEXT_API_BASE="https://yunwu.ai/v1"
export XHS_TEXT_API_KEY=""
export XHS_TEXT_MODEL="claude-sonnet-4-6"
export XHS_VISION_MODEL="gemini-3.5-flash"
export XHS_TEXT_API_KEY_HEADER="Authorization"
export XHS_TEXT_API_KEY_PREFIX="Bearer "

export XHS_IMAGE_API_BASE="https://grsai.dakka.com.cn"
export XHS_IMAGE_API_KEY=""
export XHS_IMAGE_MODEL="gpt-image-2"
export XHS_IMAGE_CREATE_PATH="/v1/draw/completions"
export XHS_IMAGE_RESULT_PATH="/v1/draw/result"

export XHS_VIDEO_API_BASE="https://dashscope.aliyuncs.com/api/v1"
export XHS_VIDEO_API_KEY=""
export XHS_VIDEO_MODEL="animate-anyone-gen2"
export XHS_VIDEO_DETECT_MODEL="animate-anyone-detect-gen2"
export XHS_VIDEO_TEMPLATE_MODEL="animate-anyone-template-gen2"
export XHS_VIDEO_MOTION_MODEL="wan2.2-animate-move"
```

### 测试 provider

查看配置状态，不会返回 API Key：

```bash
curl http://127.0.0.1:8787/api/provider-status
```

测试云雾文案生成：

```bash
curl -X POST http://127.0.0.1:8787/api/providers/text/test \
  -H "Content-Type: application/json" \
  -d '{"angle":"生活化种草","persona":"真实自用"}'
```

文案模型默认使用云雾中转的 `claude-sonnet-4-6`。页面同时提供 GPT-5.5、GPT-5.4 Mini、Claude Opus 4.8、Gemini 3.1 Pro、Gemini 3.5 Flash、Qwen 3.6 Plus、豆包 Seed 2.1 与 Kimi K2.5；AI 家居户型方案、家居小红书文案和角色壁纸 Prompt 都会使用顶部当前选择。云雾使用 OpenAI 兼容的 `/chat/completions` 接口，请求头为 `Authorization: Bearer <token>`。MiMo 和 DeepSeek 直连保留为备用选项；图片生成仍由独立的 Grsai 接口负责。

`text.vision_model` 单独控制“参考图反推场景 Prompt”的多模态模型，默认使用 `gemini-3.5-flash`。它与普通文案模型分离：即使日常文案切换到便宜的纯文本模型，参考图分析仍会使用支持图文输入的模型。
角色壁纸工作台内置 17 个从当前云雾 `/v1/models` 筛选出的新版视觉模型，包括 GPT-5.5/5.4、Claude 4.8/4.6、Gemini 3.1/3.5、Qwen 3.6、豆包 Seed 2.1、Kimi K2.5、Grok 4 和 QVQ Max；旧版 GPT-4o、Gemini 2.5、Qwen3-VL 等默认值会迁移到 Gemini 3.5 Flash。也可在高级输入框填写云雾返回的其他精确模型 ID。视觉请求始终走云雾连接，不会因普通文案切换到 MiMo/DeepSeek 直连而改变。

`image.model` 控制 Grsai 生图模型；角色壁纸工作台会显示 [Grsai 官方模型目录](https://grsai.com/dashboard/models) 中的完整生图模型与 `credits_per_image`。当前内置积分为：`gpt-image-2` 600、`nano-banana-2-lite` 440、`nano-banana-fast` 440、`nano-banana-2` 1200、`nano-banana-pro` / `nano-banana-pro-vt` 1800、CL/VIP 高稳定渠道 6000–18000；`gpt-image-2-vip` 因官方维护中会展示但禁选。GPT Image 自动走 `/v1/draw/completions`，Nano Banana 系列自动走 `/v1/draw/nano-banana`，并附带对应 `imageSize` 与异步轮询参数。正式生图任务会把当时选择的模型写入 job config 和生成素材记录；官方价格变化时可在 `provider_config.local.json` 的 `image.models` 覆盖。

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

确认 `text.configured` 为 `true`、`text.provider` 为 `yunwu`、`text.model` 为 `claude-sonnet-4-6`（或你在页面选择的其他云雾模型）。

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

### AI 人物舞蹈视频（AnimateAnyone）

侧边栏“AI 人物舞蹈”支持两条生成链路：

- AnimateAnyone Gen2：人物图检测 → 参考视频动作模板 → 舞蹈视频生成。
- 万相图生动作 `wan2.2-animate-move`：人物图片 + 参考视频直接迁移动作与表情，支持标准模式 `wan-std` 和专业模式 `wan-pro`。

API Key 必须属于阿里云百炼华北 2（北京）地域。

浏览器上传的本地图片和视频由后端写入百炼的模型绑定临时存储（48 小时），Key 不会发送到前端。最终 `video_url` 的有效期为任务完成后 24 小时。

完整工作流接口：

```bash
curl -X POST http://127.0.0.1:8787/api/dance/workflows \
  -F 'image=@/path/person.png' \
  -F 'video=@/path/dance.mp4' \
  -F 'use_ref_img_bg=false' \
  -F 'video_ratio=9:16'

curl http://127.0.0.1:8787/api/dance/workflows/替换为工作流ID
```

底层接口也可独立调用：

- `POST /api/dance/image-check`：检测人物图片
- `POST /api/dance/templates`：提交动作模板任务
- `POST /api/dance/videos`：提交舞蹈视频任务
- `POST /api/dance/wan-move`：提交万相图生动作任务
- `GET /api/dance/tasks/{task_id}`：查询百炼异步任务
- `GET /api/dance/workflows`：查询当前后端进程内的工作流

服务层入口：

- 文案适配器：`backend/services/text_provider.py`
- 生图适配器：`backend/services/image_provider.py`
- 生成任务编排：`backend/services/mock_generation.py`

服务层入口：`backend/services/animate_anyone.py`。

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
