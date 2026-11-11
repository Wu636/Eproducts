from __future__ import annotations

import json
import os
import re
import struct
import time
import zlib
from datetime import datetime
from urllib import parse, request
from urllib.error import HTTPError, URLError


DEFAULT_CLIPFORGE_BASE_URL = os.getenv("XHS_CLIPFORGE_BASE_URL", "http://127.0.0.1:3010").rstrip("/")


SCRIPT_STYLES = [
    {
        "id": "pain_seed",
        "name": "痛点种草",
        "best_for": "即时痛点、夏季/通勤/宿舍好物",
        "opening": "先把用户正在难受的瞬间说出来，再让产品自然出现。",
    },
    {
        "id": "scene_case",
        "name": "场景安利",
        "best_for": "日用品、服饰、低客单泛人群商品",
        "opening": "用一个具体场景承接需求：包里、桌面、宿舍、办公室、通勤路上。",
    },
    {
        "id": "avoid_mistake",
        "name": "避坑指南",
        "best_for": "同质化严重、用户怕踩坑的类目",
        "opening": "先讲别乱买，再给选择标准，最后承接到当前商品。",
    },
    {
        "id": "compare_review",
        "name": "对比测评",
        "best_for": "数码、家居日用、服饰版型、规格差异明显的商品",
        "opening": "用对比降低决策成本，但不虚构竞品数据。",
    },
    {
        "id": "deal_direct",
        "name": "商品卡强钩子",
        "best_for": "价格/规格/组合装利益点真实清楚的商品",
        "opening": "开头直接说适合谁、为什么现在值得看。",
    },
]

PAIN_SEEDS = {
    "小风扇": [
        "刚化完妆出门 5 分钟刘海就塌",
        "地铁口等车热到烦躁",
        "办公室开大风扇怕吹到别人",
        "宿舍桌面空间小，大风扇太占地方",
        "便宜小风扇声音大，图书馆/办公室尴尬",
    ],
    "防晒衣": [
        "骑车通勤手臂晒得发烫",
        "旅游暴晒但又不想穿得闷",
        "普通外套不透气，防晒又显土",
        "防晒衣太薄没型，穿上像雨衣",
    ],
    "短袖": [
        "短袖显不显胖主要看肩线",
        "软塌面料穿上没精神",
        "白 T 很容易透，领口洗几次就变形",
        "普通女生想通勤不费脑搭配",
    ],
    "通勤": [
        "早八/上班路上最怕热、乱、累",
        "包里东西太多但关键时候找不到",
        "办公室桌面小物要实用不能浮夸",
        "夏天通勤想体面但不要太贵",
    ],
    "护肤": [
        "一上妆毛孔和卡粉反而更明显",
        "清洁类产品怕刺激，也怕用完拔干",
        "瓶瓶罐罐很多，但真正能坚持用的不多",
        "质地看着高级，实际上推开黏腻不好洗",
    ],
    "毛孔": [
        "鼻翼和脸颊毛孔一到下午就更明显",
        "底妆卡在纹理里，看起来不干净",
        "想清洁但不想把皮肤折腾得很干",
        "产品说得很猛，但不知道具体怎么用",
    ],
    "素颜": [
        "想看起来干净一点，但不想妆感很重",
        "赶时间出门，底妆越叠越容易卡",
        "皮肤状态一般时，最怕近距离看显脏",
    ],
}

COMPLIANCE_RULES = [
    "价格、优惠券、组合装必须以商品页真实信息为准。",
    "不伪造销量、订单截图、平台活动、库存倒计时或检测报告。",
    "护肤、食品、健康类不写治疗、根治、永久、第一、最强等高风险表达。",
    "AI 模特/AI 场景按平台要求标识，不冒充真实本人试穿或实拍。",
    "商品主体颜色、包装、版型、材质、文字信息不得被 AI 改坏。",
]

AESTHETIC_FORBIDDEN_PATTERNS = [
    "红色大字",
    "白色文字飞入",
    "闪烁文字",
    "限时优惠大字",
    "点击下方链接闪烁",
    "5万+收藏",
    "回购率92%",
    "销量第一",
    "全网爆款",
    "夸张前后对比",
    "廉价促销海报",
    "直播间风贴片",
]

AESTHETIC_DIRECTOR_RULES = [
    "画面像真人创作者拍摄：真实光线、真实材质、真实使用动作，不做廉价广告模板。",
    "字幕只承担理解，不承担吆喝；每屏 6-12 个字，放底部安全区，米白/浅灰小字即可。",
    "不要在生成画面里生成中文大字、价格标签、飞入特效、闪烁 CTA；文字后期由剪辑层统一加。",
    "证据优先级：手部动作、质地近景、尺寸/容量/步骤、使用前后的体感描述；不虚构销量、收藏、回购率。",
    "商品必须保持真实包装、颜色、材质和文字；AI 只补场景、光线、镜头运动。",
]

VISUAL_STYLE_PRESETS = [
    {
        "id": "clean_beauty_editorial",
        "match": ["护肤", "美妆", "素颜", "清洁", "面霜", "精华", "毛孔"],
        "name": "干净护肤编辑感",
        "palette": "暖白、蜂蜜金、浅米色、低饱和木色",
        "lighting": "浴室窗边自然光或柔和棚拍光，反光克制，保留膏体通透质感",
        "camera": "微距质地、手部开盖、轻慢推近、俯拍桌面，不拍夸张皮肤恐怖图",
        "texture": "膏体拉丝、玻璃罐反光、指腹涂抹、湿润但不油腻的表面",
    },
    {
        "id": "daily_utility_realshot",
        "match": ["日用", "收纳", "杯", "风扇", "通勤", "宿舍", "办公室", "桌面"],
        "name": "日常实拍清爽感",
        "palette": "自然白、浅灰、植物绿、少量商品主色",
        "lighting": "白天室内自然光，桌面/包内/手持场景，避免影棚塑料感",
        "camera": "手持近景、功能步骤、尺寸对比、轻微生活化晃动",
        "texture": "真实材质、使用痕迹、手和环境比例，不做过度精修",
    },
    {
        "id": "quiet_product_proof",
        "match": [],
        "name": "克制商品证据感",
        "palette": "低饱和中性色 + 商品主色点缀",
        "lighting": "柔和侧光，主体清楚，背景有生活层次但不抢戏",
        "camera": "产品近景、手部使用、场景转场、细节证据",
        "texture": "材质、尺度、使用路径清楚，少用抽象概念画面",
    },
]

MARKET_PRODUCT_SEEDS = [
    {
        "id": "portable_fan",
        "name": "便携小风扇/挂脖风扇",
        "category": "夏季通勤小电器",
        "keywords": ["热", "通勤", "出汗", "小风扇", "宿舍", "排队", "地铁"],
        "price_band": "39-129 元",
        "why": "痛点即时、低客单、演示镜头直观，适合短视频挂车。",
        "risks": ["噪音、续航、风量必须实测", "避免虚标降温效果"],
    },
    {
        "id": "sun_protection",
        "name": "防晒衣/冰袖/遮阳帽",
        "category": "夏季服饰配件",
        "keywords": ["晒", "防晒", "骑车", "旅游", "通勤", "闷", "显瘦"],
        "price_band": "29-199 元",
        "why": "季节性强，图文和短视频都能用对比/避坑讲清楚。",
        "risks": ["防晒指数、材质、尺码要真实", "不夸大医学/护肤效果"],
    },
    {
        "id": "desk_storage",
        "name": "桌面收纳/包中包/通勤整理小物",
        "category": "收纳日用",
        "keywords": ["乱", "桌面", "包里", "找不到", "收纳", "办公室", "宿舍"],
        "price_band": "9.9-69 元",
        "why": "前后对比强，容易用评论问题持续复刻。",
        "risks": ["尺寸容量要拍清楚", "不要用虚假前后对比"],
    },
    {
        "id": "commute_cup",
        "name": "保温杯/吨吨杯/随行杯",
        "category": "通勤水具",
        "keywords": ["通勤", "办公室", "宿舍", "自习", "喝水", "杯", "保温"],
        "price_band": "39-159 元",
        "why": "使用场景稳定，适合真实细节证据和商品卡承接。",
        "risks": ["材质、容量、保温时长需以实测或商品页为准"],
    },
    {
        "id": "basic_tee",
        "name": "显瘦短袖/通勤基础款",
        "category": "服饰基础款",
        "keywords": ["短袖", "显胖", "肩线", "白T", "通勤", "搭配", "面料"],
        "price_band": "39-129 元",
        "why": "小红书图文强，适合版型证据、避坑清单和多款矩阵。",
        "risks": ["尺码、色差、上身效果不要过度承诺"],
    },
]

SALES_MODE_SEEDS = [
    {
        "id": "short_video_cart",
        "name": "痛点短视频挂车",
        "best_for": "即时痛点、低客单、演示强的商品",
        "reason": "3 秒痛点开头 + 真实细节证据 + 商品卡，转化链路最短。",
    },
    {
        "id": "xhs_carousel",
        "name": "小红书图文避坑/清单",
        "best_for": "服饰、收纳、对比标准多的商品",
        "reason": "用户愿意停留看选择标准，适合种草和评论收集。",
    },
    {
        "id": "comment_reply_video",
        "name": "评论答疑二创",
        "best_for": "评论里集中问价格、尺寸、噪音、效果的商品",
        "reason": "直接回应疑虑，适合把互动转成下一条挂车内容。",
    },
    {
        "id": "deal_card_direct",
        "name": "商品卡强钩子图文",
        "best_for": "价格利益点明确、规格组合清楚的商品",
        "reason": "低制作成本，适合一天多条测封面和人群。",
    },
    {
        "id": "comparison_review",
        "name": "对比测评短视频",
        "best_for": "用户怕踩坑、同质化严重的品类",
        "reason": "用标准降低决策成本，但必须避免伪造竞品数据。",
    },
]


def _split_list(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if not value:
        return []
    return [x.strip() for x in re.split(r"[,，、\n]", str(value)) if x.strip()]


def _first_value(data, keys, default=""):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _metric_value(data, keys):
    value = _first_value(data, keys, 0)
    if isinstance(value, str):
        value = value.replace(",", "").replace("万", "0000").strip()
    return _safe_int(value, 0)


def _normalize_sample_item(item, index=0):
    if not isinstance(item, dict):
        return {"id": f"sample_{index + 1}", "title": str(item).strip(), "comments": [], "metrics": {}}
    title = str(_first_value(item, ["title", "desc", "description", "content", "note_desc", "aweme_desc", "text"], "")).strip()
    comments = _first_value(item, ["comments", "comment_list", "top_comments", "comment"], [])
    if isinstance(comments, str):
        comments = _split_list(comments)
    elif isinstance(comments, list):
        comments = [
            str(_first_value(x, ["content", "text", "comment", "desc"], x)).strip() if isinstance(x, dict) else str(x).strip()
            for x in comments
        ]
    else:
        comments = []
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    merged = {**item, **metrics}
    return {
        "id": str(item.get("id") or item.get("note_id") or item.get("aweme_id") or f"sample_{index + 1}"),
        "title": title or f"样本 {index + 1}",
        "comments": [x for x in comments if x][:8],
        "metrics": {
            "likes": _metric_value(merged, ["likes", "liked_count", "digg_count", "like_count"]),
            "comments": _metric_value(merged, ["comments", "comment_count", "comments_count"]),
            "shares": _metric_value(merged, ["shares", "share_count", "forward_count"]),
            "collects": _metric_value(merged, ["collects", "collected_count", "collect_count"]),
        },
        "source_url": _first_value(item, ["url", "share_url", "note_url", "video_url"], ""),
        "author": _first_value(item, ["author", "nickname", "user_name"], ""),
    }


def normalize_market_samples(body):
    raw = body.get("raw") or body.get("raw_text") or body.get("text") or ""
    items = body.get("items") or body.get("samples") or []
    if raw and not items:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                items = parsed.get("items") or parsed.get("data") or parsed.get("samples") or [parsed]
            elif isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            items = []
    if raw and not items:
        rows = [line.strip() for line in str(raw).splitlines() if line.strip()]
        items = []
        for index, row in enumerate(rows):
            parts = [part.strip() for part in re.split(r"\||\t", row) if part.strip()]
            title = parts[0] if parts else row
            metrics = {}
            for part in parts[1:]:
                if any(key in part for key in ["赞", "like"]):
                    metrics["likes"] = _metric_value({"v": re.sub(r"\D", "", part)}, ["v"])
                if any(key in part for key in ["评", "comment"]):
                    metrics["comments"] = _metric_value({"v": re.sub(r"\D", "", part)}, ["v"])
            items.append({"id": f"raw_{index + 1}", "title": title, "metrics": metrics})
    normalized = [_normalize_sample_item(item, index) for index, item in enumerate(items)]
    normalized = [item for item in normalized if item.get("title")][:80]
    keyword_pool = []
    for sample in normalized[:20]:
        keyword_pool.extend(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", sample.get("title", ""))[:6])
    keyword_pool = list(dict.fromkeys(keyword_pool))[:20]
    return {
        "platform": body.get("platform") or "external",
        "source": body.get("source") or "manual_import",
        "count": len(normalized),
        "samples": normalized,
        "keywords": keyword_pool,
        "note": "已归一化为学习台 samples；如来自抓取工具，请确认账号授权、平台规则和数据使用边界。",
    }


def _sample_text(sample):
    comments = sample.get("comments") or []
    return " ".join([str(sample.get("title") or ""), " ".join(str(x) for x in comments)])


def _keyword_hits(text, keywords):
    return sum(1 for word in keywords if word and word.lower() in text.lower())


def _engagement(sample):
    metrics = sample.get("metrics") or {}
    return _safe_int(metrics.get("likes")) * 0.08 + _safe_int(metrics.get("comments")) * 0.45 + _safe_int(metrics.get("shares")) * 0.25 + _safe_int(metrics.get("collects")) * 0.18


def _hot_terms(samples, extra_keywords=""):
    counts = {}
    for token in _split_list(extra_keywords):
        counts[token] = counts.get(token, 0) + 3
    for sample in samples:
        weight = 1 + min(8, int(_engagement(sample) / 80))
        for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", _sample_text(sample)):
            if token in {"这个", "真的", "可以", "一下", "一个", "怎么", "什么"}:
                continue
            counts[token] = counts.get(token, 0) + weight
    return [{"term": key, "score": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:24]]


def _pain_clusters(samples):
    clusters = []
    seen = set()
    for sample in samples[:20]:
        title = sample.get("title") or ""
        comments = sample.get("comments") or []
        candidates = [title, *comments[:3]]
        for text in candidates:
            text = str(text).strip()
            if len(text) < 4:
                continue
            key = re.sub(r"\s+", "", text)[:24]
            if key in seen:
                continue
            seen.add(key)
            clusters.append(
                {
                    "pain": text,
                    "evidence": title,
                    "intent": "强" if any(word in text for word in ["求链接", "怎么买", "多少钱", "别乱买", "想看", "能不能"]) else "中",
                    "score": min(98, 62 + len(clusters) * 2 + int(_engagement(sample)) % 18),
                }
            )
            if len(clusters) >= 8:
                return clusters
    return clusters


def analyze_market_opportunities(body):
    normalized = normalize_market_samples(body)
    samples = normalized.get("samples") or []
    text = " ".join(_sample_text(sample) for sample in samples) + " " + str(body.get("keywords") or "")
    terms = _hot_terms(samples, body.get("keywords") or "")
    pains = _pain_clusters(samples)
    feedback = body.get("feedback") or body.get("feedback_history") or []
    feedback_power = _feedback_score(feedback)

    product_picks = []
    for seed in MARKET_PRODUCT_SEEDS:
        hits = _keyword_hits(text, seed["keywords"])
        pain_boost = sum(1 for pain in pains if _keyword_hits(pain.get("pain", ""), seed["keywords"]))
        score = 52 + hits * 9 + pain_boost * 5 + min(14, int(feedback_power / 12))
        if hits == 0 and pain_boost == 0:
            score -= 10
        product_picks.append(
            {
                **seed,
                "score": max(35, min(98, score)),
                "demand_evidence": [item["pain"] for item in pains if _keyword_hits(item.get("pain", ""), seed["keywords"])][:3],
                "recommended_content": _content_modes_for_product(seed["id"]),
                "starter_assets": _starter_assets_for_product(seed["id"]),
            }
        )
    product_picks.sort(key=lambda item: item["score"], reverse=True)

    sales_modes = []
    for mode in SALES_MODE_SEEDS:
        mode_text = mode["best_for"] + " " + mode["reason"]
        score = 58
        if any(word in text for word in ["求链接", "多少钱", "买", "挂车"]):
            score += 10 if mode["id"] in {"short_video_cart", "comment_reply_video", "deal_card_direct"} else 3
        if any(word in text for word in ["别乱买", "怎么选", "对比", "显胖", "尺寸"]):
            score += 10 if mode["id"] in {"xhs_carousel", "comparison_review"} else 4
        score += _keyword_hits(text, re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", mode_text)) * 2
        sales_modes.append({**mode, "score": min(98, score), "first_test": _first_test_for_mode(mode["id"], product_picks[0] if product_picks else {})})
    sales_modes.sort(key=lambda item: item["score"], reverse=True)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform": body.get("platform") or normalized.get("platform"),
        "source": normalized.get("source"),
        "sample_count": normalized.get("count"),
        "hot_terms": terms,
        "pain_clusters": pains,
        "product_picks": product_picks[:6],
        "sales_modes": sales_modes,
        "crawler_adapters": [
            {"name": "MediaCrawler 导出", "status": "import_ready", "fields": ["title/content", "comments", "liked_count", "comment_count", "share_url"]},
            {"name": "TikHub/Just One API", "status": "api_ready", "fields": ["desc", "statistics", "comments", "share_url"], "note": "需按服务商授权和付费规则配置"},
            {"name": "手动观察/CSV 粘贴", "status": "ready", "fields": ["标题 | 赞:1200 | 评:88"]},
        ],
        "action_plan": [
            "先用排名第一的商品方向做 6 条低成本内容测试，不急着备大货。",
            "同一个痛点做 1 条不挂车图文、1 条挂车短视频、1 条评论答疑，比较点击和成交。",
            "表现最好的痛点进入第二天扩量；低播放但高评论的内容只改封面和前 3 秒。",
        ],
        "compliance_rules": [
            "只导入你有权限获取和使用的数据；登录态抓取、批量采集需遵守平台规则。",
            "选品分数是内容测试优先级，不等于销量承诺；备货前必须看真实成交和退货风险。",
        ],
    }


def _content_modes_for_product(product_id):
    return {
        "portable_fan": ["痛点短视频挂车", "噪音/风量实测", "评论答疑"],
        "sun_protection": ["小红书避坑图文", "骑车/旅游场景短视频", "版型对比"],
        "desk_storage": ["前后对比图文", "桌面整理短视频", "包内翻找痛点"],
        "commute_cup": ["细节证据短视频", "办公室场景图文", "价格规格商品卡"],
        "basic_tee": ["版型避坑图文", "上身/平铺矩阵", "肩线面料对比"],
    }.get(product_id, ["痛点种草", "真实测评", "评论答疑"])


def _starter_assets_for_product(product_id):
    return {
        "portable_fan": ["手持大小对比", "风量吹纸巾", "分贝/噪音近景", "放包里"],
        "sun_protection": ["面料近景", "透光对比", "骑车场景", "上身版型"],
        "desk_storage": ["乱桌面 before", "整理 after", "容量装载", "尺寸对比"],
        "commute_cup": ["开盖/防漏", "内胆近景", "包里侧袋", "办公室桌面"],
        "basic_tee": ["肩线", "领口", "面料透光", "平铺+上身"],
    }.get(product_id, ["商品近景", "使用场景", "细节证据"])


def _first_test_for_mode(mode_id, product_pick):
    name = product_pick.get("name") or "当前高潜商品"
    return {
        "short_video_cart": f"用“现在最难受的瞬间”开头，30 秒挂车测 {name}",
        "xhs_carousel": f"做一篇“{name} 别乱买”避坑清单，收集评论问题",
        "comment_reply_video": "挑 1 条高频评论做答疑视频，结尾引导看商品细节",
        "deal_card_direct": f"用价格/规格/适合人群做 3 张商品卡测封面",
        "comparison_review": f"列 3 个选择标准，对比说明为什么选 {name}",
    }.get(mode_id, f"围绕 {name} 做一条真实场景内容")


def _product_points(product):
    points = product.get("selling_points") or product.get("sellingPoints") or []
    return _split_list(points) or ["真实可见细节", "日常使用方便", "价格利益点清楚"]


def _product_text(product, *extra):
    chunks = [
        product.get("name", ""),
        product.get("category", ""),
        product.get("audience", ""),
        product.get("scene", ""),
        " ".join(_product_points(product)),
        *extra,
    ]
    return " ".join(str(x) for x in chunks if x)


def _aesthetic_profile(product, body=None):
    body = body or {}
    text = _product_text(product, body.get("keywords", ""), body.get("visual_style", ""), body.get("style_hint", "")).lower()
    preset = next(
        (
            item
            for item in VISUAL_STYLE_PRESETS
            if item["match"] and any(word.lower() in text for word in item["match"])
        ),
        VISUAL_STYLE_PRESETS[-1],
    )
    return {
        **preset,
        "subtitle_policy": "仅保留克制字幕：底部安全区、每屏 6-12 字、无飞入、无闪烁、无红色促销字。",
        "overlay_policy": "画面生成阶段不生成中文文字；价格/规格/CTA 只在剪辑层用小号标签处理。",
        "forbidden": AESTHETIC_FORBIDDEN_PATTERNS,
        "negative_prompt": (
            "no Chinese text in image, no red sale banners, no flashing typography, no fake review numbers, "
            "no exaggerated before-after, no cheap ecommerce poster, no distorted product packaging, "
            "no malformed logo, no watermark, no cluttered layout"
        ),
    }


def _creative_strategy(product, selected, style, points):
    pain = selected.get("pain") or "用户已经感受到的小困扰"
    return {
        "positioning": "先做真实内容，再承接商品；像创作者分享使用细节，不像广告片喊卖点。",
        "viewer_question": pain,
        "story_arc": [
            "把痛点放进一个真实瞬间",
            "用手部/质地/场景让商品自然出现",
            "给出 2-3 个可验证细节",
            "说清适合谁，不虚构社会证明",
            "用温和 CTA 承接商品页",
        ],
        "proof_points": points[:3],
        "style_id": style.get("id"),
        "style_name": style.get("name"),
    }


def _clean_marketing_text(text):
    clean = str(text or "")
    replacements = {
        "红色大字": "小号重点标签",
        "白色文字飞入": "底部克制字幕",
        "闪烁文字": "静态字幕",
        "限时优惠": "当前活动信息",
        "点击下方链接": "看商品页详情",
        "5万+收藏": "很多人关心",
        "回购率92%": "复购信息以商品页为准",
    }
    for old, new in replacements.items():
        clean = clean.replace(old, new)
    clean = re.sub(r"\d+\s*万\+?\s*(收藏|销量|下单)", "用户反馈", clean)
    clean = re.sub(r"回购率\s*\d+%?", "复购反馈", clean)
    return clean.strip()


def _short_subtitle(text, fallback=""):
    text = _clean_marketing_text(text or fallback)
    text = re.sub(r"[，。；：,.!！?？].*$", "", text).strip()
    return text[:14] if text else fallback[:14]


def _scene_prompt(product, profile, visual, camera="", role=""):
    product_name = product.get("name") or "product"
    return (
        f"{product_name} commerce video shot, {profile['name']}, {visual}, {camera or profile['camera']}, "
        f"palette: {profile['palette']}, lighting: {profile['lighting']}, texture focus: {profile['texture']}, "
        "realistic creator-style vertical video frame, natural composition, premium but understated, "
        "keep product package shape, color, material and label accurate. "
        f"Role in story: {role}. Negative: {profile['negative_prompt']}"
    )


def _soft_cta(product, price):
    audience = product.get("audience") or "这个场景里经常用得上的人"
    if price and "发布前" not in str(price):
        return f"适合{audience}，价格和规格我会放商品页，你先按自己需求看。"
    return f"适合{audience}，先看规格、成分和使用场景，别只看包装。"


def _keyword_text(product, body):
    chunks = [
        product.get("name", ""),
        product.get("category", ""),
        product.get("audience", ""),
        product.get("scene", ""),
        " ".join(_product_points(product)),
        body.get("keywords", ""),
        body.get("category_hint", ""),
    ]
    return " ".join(str(x) for x in chunks if x).lower()


def _seed_pains(product, body):
    text = _keyword_text(product, body)
    seed_pains = []
    for key, values in PAIN_SEEDS.items():
        if key.lower() in text:
            seed_pains.extend(values)
    sample_pains = []
    samples = body.get("samples") or []
    for sample in samples:
        title = sample.get("title") or ""
        comments = sample.get("comments") or []
        if title:
            sample_pains.append(title)
        sample_pains.extend([str(x) for x in comments[:4]])
    pains = seed_pains + sample_pains
    if not pains:
        pains.extend(PAIN_SEEDS["通勤"])
    return list(dict.fromkeys([x for x in pains if x]))[:12]


def _feedback_score(feedback):
    score = 0.0
    for item in feedback or []:
        try:
            views = float(item.get("views") or 0)
            likes = float(item.get("likes") or 0)
            comments = float(item.get("comments") or 0)
            orders = float(item.get("orders") or 0)
        except (TypeError, ValueError):
            continue
        score += views * 0.001 + likes * 0.08 + comments * 0.2 + orders * 4
    return round(score, 2)


def _style_scores(feedback):
    scores = {style["id"]: 50 for style in SCRIPT_STYLES}
    for item in feedback or []:
        style = item.get("style_id") or item.get("styleId") or ""
        if style not in scores:
            continue
        try:
            views = float(item.get("views") or 0)
            likes = float(item.get("likes") or 0)
            comments = float(item.get("comments") or 0)
            orders = float(item.get("orders") or 0)
        except (TypeError, ValueError):
            continue
        scores[style] += min(35, views / 1500) + min(18, likes / 30) + min(15, comments / 8) + min(40, orders * 5)
    return {key: round(min(100, value), 1) for key, value in scores.items()}


def _ranked_styles(product, body):
    text = _keyword_text(product, body)
    scores = _style_scores(body.get("feedback") or body.get("feedback_history") or [])
    if any(word in text for word in ["小风扇", "防晒", "冰袖", "通勤", "宿舍"]):
        scores["pain_seed"] += 12
        scores["scene_case"] += 8
        scores["avoid_mistake"] += 8
    if any(word in text for word in ["短袖", "防晒衣", "短裤", "服饰", "鞋包"]):
        scores["avoid_mistake"] += 12
        scores["compare_review"] += 8
        scores["scene_case"] += 7
    if product.get("price"):
        scores["deal_direct"] += 7
    by_id = {style["id"]: style for style in SCRIPT_STYLES}
    ranked = []
    for style_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        style = by_id.get(style_id)
        if style:
            ranked.append({**style, "score": round(min(100, score), 1)})
    return ranked


def analyze_commerce_opportunities(product, body):
    platform = body.get("platform") or "抖音图文 / 小红书"
    pains = _seed_pains(product, body)
    ranked_styles = _ranked_styles(product, body)
    points = _product_points(product)
    feedback = body.get("feedback") or body.get("feedback_history") or []
    feedback_power = _feedback_score(feedback)
    product_name = product.get("name") or "当前商品"
    category = product.get("category") or "带货商品"
    opportunities = []
    for index, pain in enumerate(pains[:6]):
        style = ranked_styles[index % max(1, len(ranked_styles))]
        demand_score = min(98, 68 + index * 3 + int(feedback_power) % 12 + int(style["score"] / 8))
        opportunities.append(
            {
                "id": f"opp_{index + 1}",
                "pain": pain,
                "buyer_intent": "强" if any(token in pain for token in ["买", "别乱买", "怎么选", "热", "显胖", "声音"]) else "中",
                "recommended_style_id": style["id"],
                "recommended_style": style["name"],
                "content_angle": _angle_for_style(style["id"]),
                "hook": _hook_for(product_name, pain, style["id"]),
                "evidence_shot": _evidence_for(category, points, style["id"]),
                "demand_score": demand_score,
                "risk": _risk_for(product, pain),
            }
        )
    best = opportunities[0] if opportunities else {}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform": platform,
        "product": {
            "id": product.get("id", ""),
            "name": product_name,
            "category": category,
            "price": product.get("price", ""),
            "audience": product.get("audience", ""),
        },
        "signals": {
            "sample_count": len(body.get("samples") or []),
            "feedback_count": len(feedback),
            "feedback_power": feedback_power,
            "top_pain_count": len(pains),
        },
        "style_rank": ranked_styles,
        "opportunities": opportunities,
        "product_score": {
            "overall": min(96, 66 + len(pains) * 2 + int(feedback_power) % 16),
            "demand": min(98, 70 + len(pains) * 2),
            "execution_ease": _execution_ease(product),
            "trust_need": _trust_need(product),
            "compliance_risk": _compliance_risk(product),
        },
        "daily_loop": [
            {"slot": "上午", "type": "不挂车痛点", "action": best.get("hook") or "先测痛点内容"},
            {"slot": "中午", "type": "挂车实况", "action": "用同一痛点承接商品，主图/手持/桌面证据要清楚"},
            {"slot": "下午", "type": "不挂车避坑", "action": "做选择标准或对比清单，评论区收集需求"},
            {"slot": "晚上", "type": "挂车成交", "action": "套用白天表现最好的开头，补价格/规格/适合人群"},
        ],
        "capture_shot_list": build_capture_shot_list(product, body),
        "compliance_rules": COMPLIANCE_RULES,
        "learning_rules": [
            "每条发布后回填播放、点赞、评论、成交；系统会把高表现脚本风格上调。",
            "不挂车内容只负责测痛点和养标签，表现好的痛点第二天改挂车版。",
            "挂车内容优先用真实产品图和实拍证据，AI 场景只做封面氛围和补充 B-roll。",
        ],
    }


def _angle_for_style(style_id):
    return {
        "pain_seed": "痛点共鸣 → 产品解决",
        "scene_case": "真实场景 → 短案例安利",
        "avoid_mistake": "避坑标准 → 当前商品承接",
        "compare_review": "对比选择 → 细节证据",
        "deal_direct": "适合人群 → 价格利益点",
    }.get(style_id, "真实种草")


def _hook_for(product_name, pain, style_id):
    if any(word in pain for word in ["毛孔", "卡粉", "上妆", "底妆", "素颜"]):
        if style_id == "avoid_mistake":
            return f"{product_name}别急着买，先看你是不是这个肤感：{pain}"
        return f"{pain}，先别急着换底妆"
    if style_id == "avoid_mistake":
        return f"{product_name}别乱买，先看这个细节：{pain}"
    if style_id == "compare_review":
        return f"同类看了一圈，最后我会重点看：{pain}"
    if style_id == "deal_direct":
        return f"{pain}，先看{product_name}能不能解决这个点"
    return f"{pain}，我会先看这个细节"


def _evidence_for(category, points, style_id):
    if "服饰" in category or style_id == "compare_review":
        return ["整体上身/平铺", "肩线/领口/面料近景", "长度/垂坠/搭配对比"]
    if "数码" in category:
        return ["开关/档位演示", "声音/续航/接口近景", "与手机/手掌大小对比"]
    return ["手持产品近景", "放包里/桌面/使用场景", "细节证明：" + " / ".join(points[:2])]


def _risk_for(product, pain):
    category = product.get("category", "")
    risks = []
    if any(word in category for word in ["食品", "护肤", "健康", "母婴"]):
        risks.append("功效表达需克制")
    if any(word in pain for word in ["最", "第一", "永久", "根治"]):
        risks.append("开头含高风险绝对化表达")
    if not risks:
        risks.append("低风险：注意价格与素材授权")
    return risks


def _execution_ease(product):
    category = product.get("category", "")
    if any(word in category for word in ["家居", "日用", "数码"]):
        return 88
    if "服饰" in category:
        return 76
    return 80


def _trust_need(product):
    category = product.get("category", "")
    if any(word in category for word in ["护肤", "食品", "母婴", "数码"]):
        return 86
    return 68


def _compliance_risk(product):
    category = product.get("category", "")
    if any(word in category for word in ["护肤", "食品", "健康", "母婴"]):
        return "中高"
    return "中"


def build_capture_shot_list(product, body=None):
    body = body or {}
    text = _keyword_text(product, body)
    if "小风扇" in text or "风扇" in text:
        return [
            {"group": "真实证据", "shots": ["手持吹刘海/纸巾", "桌面立放", "放包里看大小", "一二三档风量", "靠近手机录声音"]},
            {"group": "场景库存", "shots": ["地铁口/太阳下", "办公室电脑旁", "宿舍桌面", "化妆前后", "户外排队"]},
        ]
    if any(word in text for word in ["短袖", "防晒衣", "短裤", "服饰"]):
        return [
            {"group": "版型证据", "shots": ["衣架挂拍", "床上平铺", "肩线位置", "领口袖口", "面料近景"]},
            {"group": "搭配库存", "shots": ["镜子局部试穿不露脸", "裤子/包包平铺搭配", "下摆长度", "不同光线颜色"]},
        ]
    return [
        {"group": "产品证据", "shots": ["手持主图", "桌面摆拍", "包里/收纳对比", "细节近景", "使用步骤"]},
        {"group": "内容库存", "shots": ["痛点场景", "清单合集", "对比选择", "价格规格卡", "评论答疑图"]},
    ]


def generate_video_workflows(product, body):
    analysis = body.get("analysis") or analyze_commerce_opportunities(product, body)
    opportunities = analysis.get("opportunities") or []
    selected = body.get("opportunity") or (opportunities[0] if opportunities else {})
    styles = analysis.get("style_rank") or _ranked_styles(product, body)
    style = next((item for item in styles if item["id"] == selected.get("recommended_style_id")), styles[0])
    product_name = product.get("name") or "当前商品"
    points = _product_points(product)
    price = product.get("price") or "发布前补真实价格"
    aesthetic = _aesthetic_profile(product, body)
    creative_strategy = _creative_strategy(product, selected, style, points)
    scenes = _script_scenes(product, selected, style, points, price, aesthetic)
    title = selected.get("hook") or _hook_for(product_name, selected.get("pain") or "这个场景很常见", style["id"])
    quality_gate = [
        "每个分镜必须能用真实镜头拍出来；如果像 PPT 广告，就重写。",
        "任何销量、收藏、回购、排名类数字，没有真实来源一律删除。",
        "生成画面不承担文字排版；字幕、价格和 CTA 后期统一加，且只用克制小字。",
        "护肤/食品/健康类只说感受和使用场景，不暗示治疗、根治、永久改善。",
    ]
    return {
        "title": title,
        "style": style,
        "creative_strategy": creative_strategy,
        "aesthetic_layer": aesthetic,
        "quality_gate": quality_gate,
        "duration": body.get("duration") or "30-45 秒",
        "platform": body.get("platform") or analysis.get("platform") or "抖音 / 小红书",
        "cover_text": _cover_text(selected, product_name),
        "voiceover": "\n".join(scene["voiceover"] for scene in scenes),
        "scenes": scenes,
        "shot_list": build_capture_shot_list(product, body),
        "clipforge": build_clipforge_payload(product, scenes, title, body, aesthetic, creative_strategy, quality_gate),
        "publish_copy": {
            "title": title,
            "hashtags": [f"#{product.get('category') or '好物'}", f"#{product_name}", "#真实种草", "#好物分享"],
            "description": f"{title}\n价格和规格以商品页为准。AI/素材辅助仅用于内容展示，具体以实物为准。",
            "comment_pin": "你更想看实拍细节还是对比测评？我下一条补。",
        },
        "compliance_rules": COMPLIANCE_RULES,
        "feedback_schema": {
            "views": "播放量",
            "likes": "点赞",
            "comments": "评论",
            "orders": "成交/加购",
            "style_id": style["id"],
        },
    }


def _script_scenes(product, selected, style, points, price, aesthetic=None):
    aesthetic = aesthetic or _aesthetic_profile(product)
    pain = selected.get("pain") or "这个场景很常见"
    product_name = product.get("name") or "这个小东西"
    scene = product.get("scene") or "日常使用场景"
    audience = product.get("audience") or "经常遇到这个场景的人"
    category = product.get("category") or ""
    is_beauty = any(word in _product_text(product, pain) for word in ["护肤", "美妆", "素颜", "毛孔", "面霜", "精华", "清洁"])
    detail_a = points[0] if points else "真实质感"
    detail_b = points[1] if len(points) > 1 else "使用步骤"
    detail_c = points[2] if len(points) > 2 else "适合场景"

    if is_beauty:
        raw_scenes = [
            {
                "time": "0-3s",
                "purpose": "真实痛点开头",
                "role": "让用户在一个生活瞬间里认出问题，不恐吓皮肤",
                "visual": "洗漱台自然光下的局部肤感与底妆卡纹细节，镜头很近但不过度恐怖，旁边有纸巾和镜子边缘",
                "camera": "微距轻推近，手持但稳定，景深浅，保留真实皮肤纹理",
                "voiceover": f"{pain}，这种时候别先堆遮瑕，先看清洁和质地。",
                "subtitle": _short_subtitle(pain, "一上妆就卡"),
                "stock_query": "clean bathroom skincare routine macro natural light",
            },
            {
                "time": "3-9s",
                "purpose": "产品自然进入",
                "role": "不要硬卖，用质地把商品带出来",
                "visual": f"{product_name} 罐子放在干净台面，手打开盖子，膏体有真实光泽和厚度，背景只留毛巾/镜子虚化",
                "camera": "45 度近景，慢慢推向膏体，再切手指轻取质地",
                "voiceover": f"我会先看质地和用起来麻不麻烦，这款重点看{detail_a}。",
                "subtitle": _short_subtitle(detail_a, "先看质地"),
                "stock_query": "skincare jar texture close up hand opening product",
            },
            {
                "time": "9-18s",
                "purpose": "使用证据",
                "role": "把卖点变成可见动作，不喊概念",
                "visual": f"指腹在手背或小面积肌肤上推开膏体，质地从厚到薄，旁边只放产品罐和湿润棉片",
                "camera": "手部微距，横向慢移，重点拍质地变化和涂抹边界",
                "voiceover": f"{detail_b}要拍清楚，别只看包装好不好看。",
                "subtitle": _short_subtitle(detail_b, "步骤拍清楚"),
                "stock_query": "hand applying skincare cream texture macro close up",
            },
            {
                "time": "18-30s",
                "purpose": "适合人群",
                "role": "说清楚谁适合，避免所有人都适合的空话",
                "visual": f"早上化妆前的台面小场景，产品、粉扑、镜子和自然光，手把产品放回常用位置",
                "camera": "俯拍转近景，轻微生活化动作，画面干净有呼吸感",
                "voiceover": f"如果你是{audience}，这种放在{scene}里会更容易坚持用。",
                "subtitle": _short_subtitle(audience, "适合这个场景"),
                "stock_query": "morning makeup desk skincare product natural light",
            },
            {
                "time": "30-40s",
                "purpose": "温和成交承接",
                "role": "只提醒去看真实规格，不做夸张逼单",
                "visual": f"{product_name} 罐子和质地收尾特写，背景留干净台面和柔和暖光，不出现红色价格牌",
                "camera": "静物近景，轻慢推进，最后停在产品正面但不夸张发光",
                "voiceover": _soft_cta(product, price),
                "subtitle": "先看规格和场景",
                "stock_query": "premium skincare product close up warm bathroom counter",
            },
        ]
    else:
        raw_scenes = [
            {
                "time": "0-3s",
                "purpose": "真实痛点开头",
                "role": "先让用户看到熟悉场景，不急着露完整商品",
                "visual": f"{scene}里的真实小麻烦：手、桌面或包内局部细节，画面干净但有生活痕迹",
                "camera": "手持近景，轻微推进，节奏快但不乱",
                "voiceover": f"{pain}，其实很多时候差的就是一个顺手的东西。",
                "subtitle": _short_subtitle(pain, "这个场景太常见"),
                "stock_query": "real life problem close up vertical creator video",
            },
            {
                "time": "3-9s",
                "purpose": "产品自然出现",
                "role": "产品作为解决动作出现，不做海报展示",
                "visual": f"手把 {product_name} 放进真实场景，先看比例、材质和拿取动作",
                "camera": "手部跟拍，切一个产品近景，再回到使用场景",
                "voiceover": f"我会先看它是不是顺手，尤其是{detail_a}。",
                "subtitle": _short_subtitle(detail_a, "先看是否顺手"),
                "stock_query": "handheld product demonstration natural light vertical",
            },
            {
                "time": "9-20s",
                "purpose": "细节证据",
                "role": "用 2-3 个具体镜头替代形容词",
                "visual": f"连续细节：{detail_a}、{detail_b}、{detail_c}，每个点只拍一个清楚动作",
                "camera": "三段近景切换，动作干净，背景不抢戏",
                "voiceover": f"重点看这三个细节：{detail_a}、{detail_b}，还有{detail_c}。",
                "subtitle": "只看三个细节",
                "stock_query": "product detail close up demonstration vertical",
            },
            {
                "time": "20-32s",
                "purpose": "适合人群",
                "role": "让用户判断自己是不是目标人群",
                "visual": f"{audience}的日常使用场景，产品处在真实位置，不摆拍过度",
                "camera": "中近景转细节，留一点环境信息",
                "voiceover": f"如果你是{audience}，这个会比单纯好看更重要。",
                "subtitle": _short_subtitle(audience, "适合这类人"),
                "stock_query": "daily lifestyle product use vertical video",
            },
            {
                "time": "32-42s",
                "purpose": "温和成交承接",
                "role": "承接商品页，不假装全网都在买",
                "visual": f"{product_name} 回到干净主画面，旁边只保留一个真实规格/使用提醒的小标签",
                "camera": "稳定近景，轻微推近，结尾停 0.5 秒",
                "voiceover": _soft_cta(product, price),
                "subtitle": "按需求看规格",
                "stock_query": "clean product detail card natural ecommerce vertical",
            },
        ]

    scenes = []
    for item in raw_scenes:
        clean_visual = _clean_marketing_text(item["visual"])
        clean_voiceover = _clean_marketing_text(item["voiceover"])
        scene_item = {
            **item,
            "visual": clean_visual,
            "voiceover": clean_voiceover,
            "subtitle": _clean_marketing_text(item.get("subtitle") or ""),
            "on_screen_text": _clean_marketing_text(item.get("subtitle") or ""),
            "overlay_policy": aesthetic["subtitle_policy"],
            "prompt": _scene_prompt(product, aesthetic, clean_visual, item.get("camera", ""), item.get("role", "")),
            "negative_prompt": aesthetic["negative_prompt"],
            "visual_source_preference": "product_image" if item["purpose"] in {"产品自然进入", "温和成交承接"} else "ai_or_real_broll",
        }
        scenes.append(scene_item)
    return scenes


def _cover_text(selected, product_name):
    pain = selected.get("pain") or "这个场景很多人忽略"
    return f"{product_name}别乱买\n先看这个场景"


def build_clipforge_payload(product, scenes, title, body, aesthetic=None, creative_strategy=None, quality_gate=None):
    product_image = body.get("product_image") or product.get("image_url") or product.get("imageUrl") or ""
    script = "\n".join(scene["voiceover"] for scene in scenes)
    aesthetic = aesthetic or _aesthetic_profile(product, body)
    return {
        "mode": "script_to_video",
        "base_url": body.get("clipforge_base_url") or DEFAULT_CLIPFORGE_BASE_URL,
        "product": {
            "name": product.get("name") or "",
            "price": product.get("price") or "",
            "image_url": product_image,
            "category": product.get("category") or "",
        },
        "title": title,
        "script": script,
        "aspectRatio": "9:16",
        "quality": body.get("quality") or "standard",
        "bgm": True,
        "productCard": True,
        "aiDisclosure": True,
        "creative_strategy": creative_strategy or {},
        "aesthetic_layer": aesthetic,
        "director_rules": AESTHETIC_DIRECTOR_RULES,
        "quality_gate": quality_gate or [],
        "asset_policy": {
            "product_fidelity": "商品主体优先使用真实商品图；AI 补图只能补环境、光线和 B-roll。",
            "text_policy": "不要让生图模型生成中文文案、价格标签、销量数字和闪烁 CTA。",
            "review_policy": "评论、收藏、复购、销量等社会证明必须来自真实数据，否则不出现在画面或口播里。",
        },
        "scenes": scenes,
        "note": "可传给 ClipForge 的自带脚本成片/compose 链路；商品图需用你有权使用的真实图片。审美层会约束外部工具不要生成廉价促销模板。",
    }


def _clipforge_json(base_url, path, payload=None, method=None, timeout=30):
    base = (base_url or DEFAULT_CLIPFORGE_BASE_URL).rstrip("/")
    data = None
    headers = {"User-Agent": "XHS-Commerce-Workstation/0.1"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(base + path, data=data, headers=headers, method=method or ("POST" if payload is not None else "GET"))
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(text)
        except json.JSONDecodeError:
            detail = {"error": text}
        raise RuntimeError(detail.get("error") or detail.get("message") or f"ClipForge HTTP {exc.code}") from exc


def _png_chunk(kind, data):
    import binascii

    raw = kind + data
    return struct.pack(">I", len(data)) + raw + struct.pack(">I", binascii.crc32(raw) & 0xFFFFFFFF)


def build_storyboard_png(product, workflow, width=720, height=1280):
    """Generate a lightweight vertical PNG so ClipForge can compose without external stock."""
    name = product.get("name") or "Product"
    score = sum(ord(ch) for ch in name) % 160
    bg_a = (24 + score // 4, 42 + score // 5, 54 + score // 6)
    bg_b = (232, 246 - score // 8, 238 - score // 10)
    raw = bytearray()
    for y in range(height):
        t = y / max(1, height - 1)
        row = bytearray([0])
        for x in range(width):
            cx = abs(x - width / 2) / (width / 2)
            band = 1 if (y // 110) % 2 == 0 else 0
            card = 0.0
            if width * 0.12 < x < width * 0.88 and height * 0.22 < y < height * 0.70:
                card = 0.55
            r = int(bg_a[0] * (1 - t) + bg_b[0] * t + card * 80 + band * 8 - cx * 18)
            g = int(bg_a[1] * (1 - t) + bg_b[1] * t + card * 72 + band * 6 - cx * 10)
            b = int(bg_a[2] * (1 - t) + bg_b[2] * t + card * 64 + band * 4)
            row.extend([max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))])
        raw.extend(row)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _png_chunk(b"IEND", b"")


def _clipforge_multipart_file(base_url, path, field_name, file_name, content_type, content, timeout=60):
    boundary = f"----xhs-commerce-{int(time.time() * 1000)}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{file_name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + content + tail
    req = request.Request(
        (base_url or DEFAULT_CLIPFORGE_BASE_URL).rstrip("/") + path,
        data=body,
        headers={
            "User-Agent": "XHS-Commerce-Workstation/0.1",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(text)
        except json.JSONDecodeError:
            detail = {"error": text}
        raise RuntimeError(detail.get("error") or detail.get("message") or f"ClipForge upload HTTP {exc.code}") from exc


def push_workflow_to_clipforge(product, workflow, body):
    base_url = (body.get("clipforge_base_url") or body.get("clipforgeBaseUrl") or workflow.get("clipforge", {}).get("base_url") or DEFAULT_CLIPFORGE_BASE_URL).rstrip("/")
    title = workflow.get("title") or f"{product.get('name') or '商品'} 带货视频"
    script = workflow.get("voiceover") or "\n".join(scene.get("voiceover", "") for scene in workflow.get("scenes", []))
    if not script.strip():
        raise RuntimeError("workflow 缺少可导入 ClipForge 的脚本")

    project = _clipforge_json(
        base_url,
        "/api/project",
        {
            "name": title[:80],
            "productName": product.get("name") or "",
            "productCategory": product.get("category") or "",
            "productDescription": "；".join(_product_points(product)),
            "productImages": [],
            "videoMode": "graphic_montage",
        },
        timeout=30,
    )
    project_id = project.get("id")
    if not project_id:
        raise RuntimeError("ClipForge 未返回 project id")

    imported = _clipforge_json(base_url, f"/api/project/{project_id}/import-script", {"script": script, "title": title[:80]}, timeout=30)
    material = None
    fill = None
    if body.get("upload_storyboard", True):
        png = build_storyboard_png(product, workflow)
        material = _clipforge_multipart_file(base_url, f"/api/project/{project_id}/materials", "files", "xhs-commerce-storyboard.png", "image/png", png)
        fill = _clipforge_json(base_url, f"/api/project/{project_id}/stock-fill", {"source": "local", "mediaType": "image", "force": True}, timeout=60)

    composition = None
    video_url = None
    if body.get("compose", False):
        started = _clipforge_json(
            base_url,
            f"/api/project/{project_id}/compose",
            {
                "aspectRatio": body.get("aspectRatio") or "9:16",
                "renderPreset": body.get("renderPreset") or "fast",
                "aiDisclosure": True,
                "productCard": False,
            },
            timeout=30,
        )
        comp_id = started.get("compositionId")
        deadline = time.time() + max(30, min(240, _safe_int(body.get("compose_timeout"), 120)))
        while time.time() < deadline:
            query = f"?compositionId={parse.quote(comp_id)}" if comp_id else ""
            latest = _clipforge_json(base_url, f"/api/project/{project_id}/compose{query}", timeout=15)
            composition = latest.get("composition")
            status = (composition or {}).get("status")
            if status == "done":
                video_url = base_url + (composition.get("url") or "")
                break
            if status == "failed":
                break
            time.sleep(2)
    return {
        "base_url": base_url,
        "project": project,
        "project_id": project_id,
        "project_url": f"{base_url}/project/{project_id}/video",
        "import": imported,
        "materials": material,
        "stock_fill": fill,
        "composition": composition,
        "video_url": video_url,
        "compose_command": f"CLIPFORGE_BASE_URL={base_url} node .external/clipforge/bin/clipforge.mjs compose --project {project_id} --no-fill --quality fast --json",
        "open_command": f"open {base_url}/project/{project_id}/video",
    }


def _safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _queue_slot(index):
    slots = [
        ("上午", "不挂车痛点", "先测痛点强度，评论区收集真实问题"),
        ("中午", "挂车实况", "承接上午痛点，用实拍证据推动点击商品"),
        ("下午", "不挂车避坑", "用选择标准养标签，筛出高意图人群"),
        ("晚上", "挂车成交", "复用白天强钩子，补价格/规格/适合人群"),
        ("加更", "评论答疑", "把评论里的疑虑做成下一条素材"),
        ("加更", "对比测评", "用细节对比降低下单犹豫"),
    ]
    return slots[index % len(slots)]


def _kpi_target(task_type, demand_score):
    base_views = 800 if "不挂车" in task_type else 500
    multiplier = max(1, demand_score / 70)
    return {
        "views": int(base_views * multiplier),
        "like_rate": "3%-6%",
        "comment_goal": "收集 5 条以上真实疑问",
        "order_goal": "挂车内容目标 1-3 单/加购" if "挂车" in task_type else "不考核成交，优先看痛点互动",
    }


def _feedback_memory(feedback):
    rows = feedback or []
    style_stats = {}
    for item in rows:
        style_id = item.get("style_id") or item.get("styleId") or "unknown"
        bucket = style_stats.setdefault(style_id, {"views": 0, "likes": 0, "comments": 0, "orders": 0, "count": 0})
        bucket["views"] += _safe_int(item.get("views"))
        bucket["likes"] += _safe_int(item.get("likes"))
        bucket["comments"] += _safe_int(item.get("comments"))
        bucket["orders"] += _safe_int(item.get("orders"))
        bucket["count"] += 1
    ranked = []
    for style_id, stats in style_stats.items():
        views = max(1, stats["views"])
        ranked.append(
            {
                "style_id": style_id,
                "count": stats["count"],
                "views": stats["views"],
                "engagement_rate": round((stats["likes"] + stats["comments"] * 2) / views, 4),
                "order_rate": round(stats["orders"] / views, 4),
                "score": round(stats["views"] * 0.001 + stats["likes"] * 0.08 + stats["comments"] * 0.2 + stats["orders"] * 4, 2),
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return {
        "sample_size": len(rows),
        "best_style": ranked[0] if ranked else None,
        "style_rank": ranked,
        "last_notes": [str(item.get("notes") or "") for item in rows[-5:] if item.get("notes")],
    }


def _next_iteration_rules(analysis, memory):
    score = analysis.get("product_score", {}).get("overall") or 0
    best_style = (memory.get("best_style") or {}).get("style_id")
    rules = []
    if best_style:
        rules.append(f"下一轮优先复用 {best_style} 的开头结构，但换痛点和封面字，避免素材疲劳。")
    if score >= 85:
        rules.append("爆品潜力较高：今天至少做 2 条挂车版，晚上复用互动最强的痛点扩量。")
    else:
        rules.append("先不要重投放：用不挂车内容验证痛点，评论里出现明确购买问题后再挂车。")
    rules.extend(
        [
            "播放低但评论高：封面/前 3 秒不够直给，保留痛点，重写开头。",
            "播放高但成交低：补价格、规格、适合人群和真实细节，减少空泛种草。",
            "成交高但播放低：保留商品卡承接，换 3 个更宽的人群场景测试。",
        ]
    )
    return rules


def _data_source_health(body):
    samples = body.get("samples") or []
    feedback = body.get("feedback") or body.get("feedback_history") or []
    sources = []
    if samples:
        sources.append({"name": "手动/外部热点样本", "status": "ready", "count": len(samples), "note": "已参与痛点和标题提炼"})
    else:
        sources.append({"name": "手动/外部热点样本", "status": "empty", "count": 0, "note": "建议粘贴 MediaCrawler/TikHub/人工观察到的标题和评论"})
    if feedback:
        sources.append({"name": "发布表现回填", "status": "learning", "count": len(feedback), "note": "已用于调整打法权重"})
    else:
        sources.append({"name": "发布表现回填", "status": "waiting", "count": 0, "note": "发布后填播放、互动、成交，下一轮会自动偏向高表现打法"})
    sources.append(
        {
            "name": "平台抓取适配器",
            "status": "adapter_ready",
            "count": 0,
            "note": "建议先接合规导出的标题/评论/指标；跑通 ROI 后再接 MediaCrawler 或付费 API 做定时批量采样",
        }
    )
    return sources


def _data_strategy_plan(body):
    sample_count = len(body.get("samples") or [])
    feedback_count = len(body.get("feedback") or body.get("feedback_history") or [])
    phase = "cold_start" if sample_count < 20 else "calibration" if feedback_count < 10 else "scaling"
    return {
        "phase": phase,
        "recommendation": {
            "cold_start": "先用人工精选/外部导出 30-80 条高热视频样本，不急着上重抓取；把字段、评分和回填跑准。",
            "calibration": "开始做轻量定时采样：每天按关键词抓标题、互动、评论高频问题，和发布表现一起训练排序。",
            "scaling": "当单品/类目验证能稳定出单，再接付费 API 或自建采集队列扩量，重点买稳定性和节省人力。",
        }[phase],
        "manual_upload_role": "人工上传/粘贴适合做高质量标注和审美样本库，能自迭代，但市场发现速度慢。",
        "auto_fetch_role": "自动抓取适合做趋势发现、痛点聚类和选品雷达，但要单独处理授权、限频、字段清洗和成本。",
        "best_value_path": [
            "人工精选 30-80 条样本 + 发布表现回填，先验证脚本和审美判断。",
            "接 MediaCrawler/导出文件做每日批量候选池，只入库标题、互动、评论和链接。",
            "出现稳定 ROI 后，再接 TikHub/第三方 API 或平台授权接口，减少维护成本。",
        ],
    }


def build_learning_cycle(product, body):
    daily_target = max(4, min(12, _safe_int(body.get("daily_target") or body.get("dailyTarget"), 8)))
    analysis = body.get("analysis") or analyze_commerce_opportunities(product, body)
    opportunities = analysis.get("opportunities") or []
    feedback = body.get("feedback") or body.get("feedback_history") or []
    memory = _feedback_memory(feedback)
    test_queue = []
    workflows = []
    for index in range(daily_target):
        opportunity = opportunities[index % max(1, len(opportunities))] if opportunities else {}
        slot, task_type, objective = _queue_slot(index)
        task_body = {**body, "analysis": analysis, "opportunity": opportunity, "save_asset": False}
        workflow = generate_video_workflows(product, task_body)
        workflows.append(workflow)
        test_queue.append(
            {
                "id": f"task_{index + 1}",
                "slot": slot,
                "type": task_type,
                "objective": objective,
                "hook": opportunity.get("hook") or workflow.get("title"),
                "style_id": workflow.get("style", {}).get("id"),
                "style_name": workflow.get("style", {}).get("name"),
                "asset_type": "video" if "挂车" in task_type or index % 3 == 1 else "copy",
                "production": "ClipForge 成片 + 真实产品镜头" if "挂车" in task_type else "短图文/口播素材",
                "evidence_shots": opportunity.get("evidence_shot") or [],
                "kpi": _kpi_target(task_type, opportunity.get("demand_score") or 70),
                "clipforge": workflow.get("clipforge") if "挂车" in task_type else None,
                "status": "draft",
            }
        )
    cycle_id = f"cycle_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return {
        "id": cycle_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "product": analysis.get("product") or {},
        "platform": body.get("platform") or analysis.get("platform"),
        "daily_target": daily_target,
        "mode": body.get("mode") or "cold_start_learning",
        "analysis": analysis,
        "test_queue": test_queue,
        "workflows": workflows[: min(4, len(workflows))],
        "learning_memory": memory,
        "next_iteration": _next_iteration_rules(analysis, memory),
        "data_sources": _data_source_health(body),
        "data_strategy": _data_strategy_plan(body),
        "operating_rules": [
            "先测痛点，再挂车承接；不挂车内容负责找需求，挂车内容负责成交。",
            "每条内容只验证一个变量：开头、封面、场景、商品证据或价格承接。",
            "当天表现最好的痛点进入次日扩量，表现差的只保留评论问题，不复制脚本。",
        ],
    }


def clipforge_status(base_url=None):
    base = (base_url or DEFAULT_CLIPFORGE_BASE_URL).rstrip("/")
    parsed = parse.urlparse(base)
    host_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    result = {
        "base_url": base,
        "reachable": False,
        "status": "not_started",
        "message": "ClipForge 未启动；可先运行 .external/clipforge 或 Docker 服务。",
        "docker_command": f"docker run -d -p {host_port}:3000 -v clipforge-data:/data ghcr.io/xixihhhh/clipforge",
        "local_command": f"cd .external/clipforge && pnpm exec next dev --webpack -p {host_port}",
        "local_path": ".external/clipforge",
    }
    try:
        req = request.Request(base + "/", headers={"User-Agent": "Mozilla/5.0"})
        opener = request.build_opener(request.ProxyHandler({}))
        with opener.open(req, timeout=3) as response:
            text = response.read(300).decode("utf-8", errors="replace")
        result.update(
            {
                "reachable": True,
                "status": "running",
                "message": "ClipForge 服务可访问，可把视频工作流 payload 交给它成片。",
                "probe": text[:180],
            }
        )
    except (URLError, TimeoutError, OSError) as exc:
        result["error"] = str(exc)
    return result


def format_cycle_report(cycle):
    lines = [
        f"自循环爆款学习周期｜{cycle.get('product', {}).get('name')}",
        f"平台：{cycle.get('platform')}｜今日目标：{cycle.get('daily_target')} 条｜周期：{cycle.get('id')}",
        "",
        "今日测试队列：",
    ]
    for item in cycle.get("test_queue", []):
        kpi = item.get("kpi") or {}
        lines.append(
            f"- {item['slot']}｜{item['type']}｜{item['hook']}｜打法：{item.get('style_name')}｜目标播放：{kpi.get('views')}"
        )
    lines.append("")
    lines.append("下一轮优化规则：")
    for item in cycle.get("next_iteration", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("数据源健康：")
    for item in cycle.get("data_sources", []):
        lines.append(f"- {item['name']}：{item['status']}｜{item['note']}")
    strategy = cycle.get("data_strategy") or {}
    if strategy:
        lines.append("")
        lines.append("数据策略：")
        lines.append(f"- 阶段：{strategy.get('phase')}")
        lines.append(f"- 建议：{strategy.get('recommendation')}")
    return "\n".join(lines)


def format_market_report(market):
    lines = [
        "热点选品雷达",
        f"平台：{market.get('platform')}｜样本数：{market.get('sample_count')}｜来源：{market.get('source')}",
        "",
        "高频需求词：",
        "、".join(item["term"] for item in market.get("hot_terms", [])[:12]),
        "",
        "推荐选品：",
    ]
    for item in market.get("product_picks", [])[:6]:
        lines.append(f"- {item['name']}｜{item['score']} 分｜{item['price_band']}｜{item['why']}")
    lines.append("")
    lines.append("容易出货的带货方式：")
    for item in market.get("sales_modes", [])[:5]:
        lines.append(f"- {item['name']}｜{item['score']} 分｜{item['first_test']}")
    lines.append("")
    lines.append("行动计划：")
    for item in market.get("action_plan", []):
        lines.append(f"- {item}")
    return "\n".join(lines)


def format_learning_report(analysis):
    lines = [
        f"爆款学习台分析｜{analysis['product']['name']}",
        "",
        f"平台：{analysis.get('platform')}",
        f"样本数：{analysis['signals']['sample_count']}；回填数据：{analysis['signals']['feedback_count']}；反馈强度：{analysis['signals']['feedback_power']}",
        "",
        "推荐打法排行：",
    ]
    for item in analysis.get("style_rank", [])[:5]:
        lines.append(f"- {item['name']}：{item['score']} 分｜{item['opening']}")
    lines.append("")
    lines.append("高意图痛点：")
    for item in analysis.get("opportunities", [])[:6]:
        lines.append(f"- {item['hook']}｜打法：{item['recommended_style']}｜需求分：{item['demand_score']}")
    lines.append("")
    lines.append("今日循环：")
    for item in analysis.get("daily_loop", []):
        lines.append(f"- {item['slot']}｜{item['type']}｜{item['action']}")
    lines.append("")
    lines.append("实拍素材清单：")
    for group in analysis.get("capture_shot_list", []):
        lines.append(f"- {group['group']}：" + "、".join(group.get("shots") or []))
    return "\n".join(lines)


def format_video_workflow(workflow):
    aesthetic = workflow.get("aesthetic_layer") or {}
    strategy = workflow.get("creative_strategy") or {}
    lines = [
        f"带货视频工作流｜{workflow.get('title')}",
        f"平台：{workflow.get('platform')}｜时长：{workflow.get('duration')}｜打法：{workflow.get('style', {}).get('name')}",
        "",
        f"封面字：{workflow.get('cover_text')}",
        "",
        "创作策略：",
        f"- 定位：{strategy.get('positioning', '')}",
        f"- 用户问题：{strategy.get('viewer_question', '')}",
        f"- 审美预设：{aesthetic.get('name', '')}｜{aesthetic.get('palette', '')}",
        f"- 字幕规则：{aesthetic.get('subtitle_policy', '')}",
        "",
        "质量闸门：",
    ]
    for item in workflow.get("quality_gate", []):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "分镜脚本：",
        ]
    )
    for scene in workflow.get("scenes", []):
        lines.append(f"[{scene['time']}] {scene['purpose']}")
        lines.append(f"画面：{scene['visual']}")
        if scene.get("camera"):
            lines.append(f"镜头：{scene['camera']}")
        lines.append(f"口播：{scene['voiceover']}")
        lines.append(f"字幕：{scene['subtitle']}")
        if scene.get("prompt"):
            lines.append(f"生图/视频提示词：{scene['prompt']}")
        if scene.get("negative_prompt"):
            lines.append(f"负面词：{scene['negative_prompt']}")
        lines.append("")
    lines.append("发布文案：")
    publish = workflow.get("publish_copy") or {}
    lines.append(publish.get("description", ""))
    lines.append(" ".join(publish.get("hashtags") or []))
    lines.append("")
    lines.append("ClipForge Payload:")
    lines.append(json.dumps(workflow.get("clipforge") or {}, ensure_ascii=False, indent=2))
    return "\n".join(lines)
