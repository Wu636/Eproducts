# 爆款学习台与带货视频工作流

本项目现在把“纯带货工作站”拆成一个可循环的内容生产闭环：

1. 输入商品、平台、关键词、竞品/热点样本。
2. 爆款学习台分析痛点、打法排行、爆品潜力、发布节奏与实拍素材清单。
3. 选择一个高意图痛点，生成 30-45 秒带货视频脚本、分镜、封面字、发布文案和 ClipForge payload。
4. 发布后回填播放、点赞、评论、成交/加购。
5. 下一轮分析会读取回填数据，把高表现脚本风格排到更前面。

## 数据源与自迭代方案

当前爆款学习台不是纯 mock，但也不是自动实时抓抖音/小红书热榜。它现在吃三类真实输入：

1. 手动粘贴/CSV/JSON 导入的热点标题、评论和互动指标。
2. MediaCrawler、TikHub/Just One API 或其他外部工具导出的样本。
3. 自己发布后的播放、点赞、评论、加购/成交回填。

性价比最高的路线是分三段走：

1. 冷启动：人工精选 30-80 条高热视频/笔记样本，重点做字段清洗、痛点聚类、脚本结构和审美判断。这一步成本最低，也最能避免把垃圾数据喂给模型。
2. 校准期：接入轻量采样适配器，每天按关键词导入标题、互动、评论高频问题和链接，不保存无授权的视频原片。学习台用这些数据做选品雷达和痛点排行。
3. 放量期：当某个品类或单品能稳定出单，再接付费 API 或更稳定的数据服务。这个阶段买的是稳定性和省人力，不是用来证明方向。

只靠用户上传也能自迭代，因为发布表现回填会改变打法权重；但它只能“越做越懂自己的账号和商品”，不能自动发现平台新趋势。要做到趋势自更新，需要增加定时采样任务、样本库、去重清洗、评论聚类和成本/合规监控。

## 脚本创作台与审美层

工作流现在分成三层输出：

1. 创作策略：明确用户问题、故事路径、证据点和适合人群，避免先写空泛广告词。
2. 审美提示词层：按品类选择视觉预设，统一光线、色彩、镜头、字幕和禁用词。
3. 分镜执行：每个分镜包含画面、镜头、口播、字幕、外部生图/视频提示词和负面词。

默认禁用这些廉价带货表达：红色大字、白色文字飞入、闪烁文字、虚构收藏/销量/复购率、夸张前后对比、直播间风贴片、强促销价格海报。

护肤/食品/健康类脚本只讲真实使用场景、质地、步骤和体感，不写治疗、根治、永久改善。商品包装、颜色、材质和文字必须以真实商品图为准，AI 只补环境、光线和 B-roll。

## 本地启动

一键启动工作站、后端和 ClipForge：

```bash
./scripts/start_commerce_workstation.sh
```

启动后访问：

```text
http://127.0.0.1:8790/xhs-asset-generator-2.html
```

也可以分别启动。后端：

```bash
python3 backend/server.py --host 127.0.0.1 --port 8789
```

前端：

直接打开 `xhs-asset-generator-2.html`，或用任意静态服务器打开。页面会优先连接 `http://127.0.0.1:8789/api`。

## ClipForge 外部生成器

ClipForge 已作为外部项目拉到 `.external/clipforge`。这个目录被 `.gitignore` 忽略，避免把 AGPL 项目代码混进主项目。

建议使用 3010 端口，避免和其他本地 Next 项目抢 3000：

```bash
docker run -d -p 3010:3000 -v clipforge-data:/data ghcr.io/xixihhhh/clipforge
```

或者本地开发：

```bash
./scripts/start_clipforge_external.sh 3010
```

也可以手动启动：

```bash
cd .external/clipforge
pnpm exec next dev --webpack -p 3010
```

工作站里的“复制 payload”会把当前视频工作流交接包复制到剪贴板。服务地址默认是 `http://127.0.0.1:3010`，也可以在页面里改成 Docker、远程机器或后续 MCP 网关的地址。ClipForge 启动后，可用它的自带脚本成片、CLI 或 MCP 链路导入脚本和商品信息继续成片。

工作站里的“创建项目/本地试渲染（0 AI）”会进一步调用 ClipForge：

1. 创建 ClipForge 项目。
2. 导入当前视频工作流脚本。
3. 生成一张本地 storyboard PNG 并上传为自有素材。
4. 用 ClipForge 的 local stock-fill 填满分镜。
5. 本地试渲染时只触发 fast MP4 合成并返回视频地址，不调用 Seedance/Kling/Veo 等付费生视频模型。

成本护栏：

- ClipForge 的 Atlas 一键接入不再自动选择默认生视频模型。
- ClipForge 素材页的“AI 动态镜头”默认关闭，开启或单镜头转动态都需要二次确认。
- `/api/ai/video` 服务端会拦截未确认的付费生视频请求，默认单次也会拦截超过 5 秒的生视频。
- 推荐先用商品图、免费素材和本地合成看完整节奏，只有少数关键镜头值得时再单独转动态。

## API

整理外部热点/竞品样本：

```bash
curl -X POST http://127.0.0.1:8789/api/commerce-learning/normalize-samples \
  -H "Content-Type: application/json" \
  -d '{"raw_text":"夏天通勤最怕出门就狼狈 | 赞:1200 | 评:88\n办公室桌面乱的人可以试试这个 | 赞:680 | 评:43","platform":"抖音短视频"}'
```

分析爆品选品方向和出货方式：

```bash
curl -X POST http://127.0.0.1:8789/api/commerce-learning/market-opportunities \
  -H "Content-Type: application/json" \
  -d '{"platform":"抖音短视频","keywords":"夏天通勤 小风扇 防晒衣 桌面收纳","raw_text":"小风扇别乱买，看这 5 点 | 赞:2400 | 评:166"}'
```

本地验证选品雷达：

```bash
./scripts/verify_market_radar.sh
```

一键跑完整学习周期：

```bash
curl -X POST http://127.0.0.1:8789/api/commerce-learning/run-cycle \
  -H "Content-Type: application/json" \
  -d '{"product_id":"你的产品ID","platform":"抖音短视频","daily_target":6,"keywords":"通勤好物 夏天怕热","clipforge_base_url":"http://127.0.0.1:3010"}'
```

本地验证闭环：

```bash
./scripts/verify_commerce_learning_cycle.sh
```

验证工作站到 ClipForge 的真实项目交接和 MP4 试渲染：

```bash
./scripts/verify_clipforge_handoff.sh
```

完整验收：

```bash
./scripts/verify_full_commerce_product.sh
```

分析热点痛点：

```bash
curl -X POST http://127.0.0.1:8789/api/commerce-learning/analyze \
  -H "Content-Type: application/json" \
  -d '{"product_id":"你的产品ID","platform":"抖音图文","keywords":"夏天通勤 小风扇","samples":[{"title":"小风扇别乱买，看这5点","comments":["求链接","声音大不大"]}]}'
```

生成视频工作流：

```bash
curl -X POST http://127.0.0.1:8789/api/commerce-learning/video-workflow \
  -H "Content-Type: application/json" \
  -d '{"product_id":"你的产品ID","platform":"抖音图文","keywords":"通勤好物"}'
```

回填表现：

```bash
curl -X POST http://127.0.0.1:8789/api/commerce-learning/feedback \
  -H "Content-Type: application/json" \
  -d '{"product_id":"你的产品ID","asset_id":"视频工作流素材ID","style_id":"scene_case","views":5200,"likes":260,"comments":41,"orders":7}'
```

检查 ClipForge：

```bash
curl "http://127.0.0.1:8789/api/commerce-learning/clipforge-status?base_url=http%3A%2F%2F127.0.0.1%3A3010"
```
