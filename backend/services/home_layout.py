from __future__ import annotations

import json
import random
import re
from time import sleep

from config import settings
from services.http_client import post_json
from services.image_provider import ProviderNotConfigured as ImageProviderNotConfigured
from services.image_provider import create_image_task, wait_for_image_result
from services.text_provider import (
    ProviderNotConfigured,
    is_text_provider_configured,
    prepare_text_payload,
    text_provider_supports_images,
)


HOME_LAYOUT_ACCOUNT_ID = "account_ai_home_layout"
HOME_LAYOUT_ACCOUNT_NAME = "AI 家居户型图号"

HOOK_LABELS = {
    "emotion": "情绪价值种草",
    "layout": "户型拆解",
    "save": "收藏灵感",
    "prompt": "提示词引导",
    "soft": "软装清单",
    "compare": "风格对比",
}

FALLBACK_STYLES = [
    {
        "name": "北欧阳光自然风",
        "tag": "热门",
        "scene": "晨光开放客餐厨，大窗、白纱帘、木餐桌、绿植和早餐吧台形成通透生活场景",
        "palette": "白色、浅灰、浅原木、鼠尾草绿、少量阳光黄",
        "mood": "明亮、干净、松弛、自然、治愈",
        "elements": "白纱帘、原木家具、浅色地毯、绿植、开放书架、早餐餐具",
    },
    {
        "name": "奶油原木暖居",
        "tag": "热门",
        "scene": "午后客厅与卧室半开放布局，圆润沙发、软毯、落地灯和收纳柜让小家显得温暖可住",
        "palette": "奶白、米色、浅原木、杏桃色、低饱和暖黄",
        "mood": "温柔、软糯、治愈、有生活感、像被阳光包住",
        "elements": "圆润沙发、棉麻抱枕、暖光台灯、木质收纳、浅色窗帘、软毯",
    },
    {
        "name": "彩色多巴胺小家",
        "tag": "热门",
        "scene": "开放式小公寓，客厅、工作区和餐边柜用彩色模块自然分区，像阳光下的快乐小家",
        "palette": "奶白底色、柠檬黄、珊瑚粉、薄荷绿、天空蓝",
        "mood": "阳光、活泼、彩色但不杂乱、元气治愈",
        "elements": "彩色单椅、模块收纳、圆形地毯、趣味台灯、艺术挂画、透明花瓶",
    },
    {
        "name": "阳台花园治愈风",
        "tag": "热门",
        "scene": "室内客厅连着阳光阳台，藤编椅、花架、香草植物和小圆桌形成城市花园角落",
        "palette": "象牙白、浅木色、叶绿色、花朵粉、少量陶土色",
        "mood": "自然、清新、呼吸感强、像周末晒太阳",
        "elements": "阳台花架、藤编椅、白纱帘、盆栽、圆桌、浅色木地板",
    },
    {
        "name": "海盐度假公寓风",
        "tag": "热门",
        "scene": "海边度假感开放式公寓，客餐厅、卧室和阳台连成一条清爽动线，窗外是明亮天空和远景",
        "palette": "贝壳白、海盐蓝、浅沙色、漂白木、少量珊瑚色",
        "mood": "清爽、放松、度假感、明亮治愈",
        "elements": "百叶窗、亚麻沙发、浅木餐桌、条纹织物、贝壳装饰、绿植",
    },
    {
        "name": "南法花园小屋风",
        "tag": "小众",
        "scene": "拱门、花砖和开放餐厨组成南法小屋，窗边有花草、餐桌和柔和午后阳光",
        "palette": "奶油白、薰衣草紫、鼠尾草绿、陶土橙、浅木色",
        "mood": "浪漫、温馨、彩色、慢生活",
        "elements": "拱形门洞、花砖、木百叶、花草、藤编吊灯、圆形餐桌",
    },
    {
        "name": "日式暖木杂货风",
        "tag": "小众",
        "scene": "日式小户型里有榻榻米休息区、低矮书桌、餐厨和充足收纳，像安静但不冷清的杂货小家",
        "palette": "暖白、浅桦木、米黄、抹茶绿、浅焦糖",
        "mood": "安稳、温暖、整洁、有烟火气",
        "elements": "木格推拉门、低矮家具、布帘、开放格收纳、陶器、棉麻坐垫",
    },
    {
        "name": "复古彩色公寓风",
        "tag": "小众",
        "scene": "阳光照进复古公寓，客厅、餐桌和阅读角用彩色地毯、画框和中古家具串联",
        "palette": "奶油白、樱桃红、湖蓝、芥末黄、胡桃木",
        "mood": "复古、明快、有故事感、温暖不沉重",
        "elements": "中古边柜、彩色地毯、复古画框、玻璃花瓶、布艺沙发、暖色壁灯",
    },
    {
        "name": "亲子暖居收纳风",
        "tag": "热门",
        "scene": "家庭型小户型，客厅活动区、餐厨、儿童收纳墙和卧室动线清楚，空间温馨又不拥挤",
        "palette": "暖白、浅木、鹅黄、草绿、柔和蓝",
        "mood": "温暖、安全、明亮、整洁、有陪伴感",
        "elements": "低矮收纳柜、软垫活动区、圆角家具、可擦写墙、开放餐厨、充足自然光",
    },
    {
        "name": "阅读角慢生活风",
        "tag": "热门",
        "scene": "客厅窗边做成阅读角，书架、单椅、边几和柔软地毯围合出慢生活小角落",
        "palette": "暖白、浅木、燕麦色、雾蓝、植物绿",
        "mood": "安静、治愈、温柔、有书卷气但不冷",
        "elements": "窗边书架、舒适单椅、落地灯、羊毛地毯、茶几、绿植",
    },
    {
        "name": "清新艺术工作室风",
        "tag": "小众",
        "scene": "小户型融合居住与创作工作室，明亮工作台、作品展示墙、客厅和睡眠区自然分区",
        "palette": "白色、浅木、天空蓝、柠檬黄、珊瑚粉",
        "mood": "创意、阳光、色彩缤纷、灵感充足",
        "elements": "大工作台、开放画架、展示墙、彩色收纳盒、轨道灯、轻盈窗帘",
    },
    {
        "name": "午后咖啡民宿风",
        "tag": "热门",
        "scene": "温馨民宿式小家，开放餐厨、咖啡吧台、软沙发和卧室区域在同一画面内清楚呈现",
        "palette": "奶油白、咖啡棕、浅木、焦糖、浅绿",
        "mood": "温暖、松弛、像午后咖啡馆一样治愈",
        "elements": "咖啡吧台、木餐桌、吊灯、软沙发、绿植、开放层板",
    },
    {
        "name": "春日薄荷厨房风",
        "tag": "小众",
        "scene": "明亮开放式厨房连接餐厅和小客厅，薄荷色橱柜、白色台面和花草让空间轻盈清新",
        "palette": "白色、薄荷绿、浅木、奶黄、透明玻璃",
        "mood": "清新、轻盈、干净、像春天早晨",
        "elements": "薄荷橱柜、白色台面、玻璃吊灯、餐边柜、鲜花、浅色地砖",
    },
    {
        "name": "暖黄灯客厅治愈风",
        "tag": "热门",
        "scene": "傍晚但不昏暗的温馨客厅，窗外还有余晖，室内用落地灯、壁灯和地毯制造被包围的暖意",
        "palette": "暖白、蜂蜜黄、浅木、杏色、少量橄榄绿",
        "mood": "温暖、安心、治愈、适合下班回家",
        "elements": "落地灯、壁灯、软沙发、厚地毯、收纳柜、窗边绿植",
    },
]

HOME_LAYOUT_SCENE_DIRECTIONS = [
    "晨光开放客餐厨：大窗、白纱、木餐桌、绿植、早餐吧台",
    "阳台花园小家：客厅连阳台、藤编椅、花架、小圆桌、自然光",
    "彩色多巴胺公寓：奶白底色搭配柠檬黄、珊瑚粉、薄荷绿、天空蓝",
    "海盐度假公寓：贝壳白、海盐蓝、浅沙色、百叶窗和清爽阳台",
    "南法花园餐厨：拱门、花砖、木百叶、花草和午后餐桌",
    "日式暖木杂货小家：榻榻米、木格门、低矮家具和整洁收纳",
    "复古彩色客厅：中古边柜、彩色地毯、画框、玻璃花瓶和阳光",
    "亲子暖居收纳：圆角家具、低矮收纳墙、开放餐厨和柔和色彩",
    "阅读角慢生活：窗边书架、舒适单椅、落地灯、地毯和茶几",
    "清新艺术工作室：工作台、展示墙、彩色收纳和明亮创作区",
    "午后咖啡民宿：咖啡吧台、木餐桌、软沙发、吊灯和绿植",
    "春日薄荷厨房：薄荷橱柜、白色台面、鲜花和开放餐厅",
]

HOME_LAYOUT_BRIGHT_GUARD = (
    "画面必须明亮、温馨、温暖、治愈、真实可居住，优先清晨/白天/午后自然光或不昏暗的暖黄灯；"
    "不要暗黑压抑，不要阴冷恐怖氛围，不要赛博夜店感，不要废土工业风，不要大面积黑灰墙面，不要过暗低曝光。"
)


def ensure_home_layout_account(store):
    account = store.get_product(HOME_LAYOUT_ACCOUNT_ID)
    if account:
        return account
    return store.create_product(
        {
            "id": HOME_LAYOUT_ACCOUNT_ID,
            "name": HOME_LAYOUT_ACCOUNT_NAME,
            "category": "AI 家居灵感",
            "tone": "家居灵感 + 户型拆解 + 情绪价值种草",
            "audience": "独居人群、情侣、装修小白、小户型业主、家居爱好者",
            "selling_points": ["AI 户型视觉灵感", "可复制软装建议", "小红书家居文案"],
            "scene": "loft、公寓、小户型、民宿、室内设计灵感",
        }
    )


def _chat_url():
    return settings.text_api_base.rstrip("/") + "/chat/completions"


def _headers():
    return {
        settings.text_api_key_header: settings.text_api_key_prefix + settings.text_api_key,
        "Content-Type": "application/json",
    }


def _extract_json(text):
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Some chat providers occasionally emit otherwise-valid JSON with a
    # trailing comma before a closing brace/bracket.  Accept that harmless
    # formatting slip so a usable AI plan is not discarded unnecessarily.
    try:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
    start, end = raw.find("["), raw.rfind("]")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
    raise ValueError("AI 返回的内容不是有效 JSON")


def _base_layout_prompt(data, style, extra=""):
    layout_type = data.get("layout_type") or data.get("layoutType") or "双层 loft 公寓"
    area = data.get("area") or "面积可自适应"
    household = data.get("household") or "独居或两人居住"
    needs = data.get("needs") or "兼顾休息、收纳、办公和做饭"
    description = data.get("description") or ""
    aspect_ratio = data.get("aspect_ratio") or data.get("aspectRatio") or "9:16"
    palette = style.get("palette") or data.get("palette") or "低饱和自然色"
    mood = style.get("mood") or data.get("mood") or "温暖、有生活感"
    scene = style.get("scene") or data.get("scene") or "阳光充足、温馨治愈、真实可居住的家居生活场景"
    elements = style.get("elements") or "真实软装和自然光"
    return (
        f"{style.get('name') or data.get('style_hint') or '现代自然风'} {layout_type} 户型室内效果图，{aspect_ratio} 竖版。"
        f"户型信息：{area}，居住者：{household}，核心需求：{needs}。"
        f"用户描述：{description or '请根据户型类型补全合理空间布局'}。"
        f"场景方向：{scene}。整体色调：{palette}；氛围：{mood}；关键软装与材质：{elements}。"
        "必须呈现清晰、可居住的空间布局和功能分区，包含客厅、餐厨、卧室、卫浴、收纳、工作区等与户型相匹配的区域；"
        "如为 loft，使用完整双层剖面/娃娃屋式全景视角，楼梯、上下层动线与尺度合理。"
        "优先使用清晨、白天、午后或有余晖的明亮时段，充足自然光、柔和暖光、轻盈窗帘、鲜活色彩和真实生活细节；"
        "室内设计效果图，真实材质，细节丰富，明亮通透，温暖灯光，生活气息，高级家居杂志风，小红书家居灵感视觉，超清，8K。"
        "不要人物，不要文字，不要 logo，不要水印，不要乱码，不要畸形家具，不要错误透视，不要过度拥挤，不要低清晰度，不要暗黑压抑，不要阴冷恐怖氛围，不要赛博夜店感，不要废土工业风，不要大面积黑灰墙面，不要冷冰冰样板间，不要廉价塑料质感，不要过曝。"
        f"{extra}"
    )


def _ensure_bright_home_prompt(prompt, scene=""):
    text = str(prompt or "").strip()
    if scene and scene not in text:
        text = f"场景方向：{scene}。{text}"
    if "不要暗黑压抑" not in text and "不要暗黑" not in text:
        separator = "" if text.endswith(("。", "；", ";", ".", "！", "!")) else "。"
        text = f"{text}{separator}{HOME_LAYOUT_BRIGHT_GUARD}"
    return text


def _fallback_plans(data):
    count = max(1, min(int(data.get("count") or 6), 8))
    style_hint = (data.get("style_hint") or data.get("styleHint") or "").strip()
    discover = bool(data.get("discover"))
    candidates = FALLBACK_STYLES[:]
    if style_hint:
        candidates = sorted(candidates, key=lambda style: style_hint not in style["name"])
    elif discover:
        random.shuffle(candidates)
    plans = []
    for index in range(count):
        style = candidates[index % len(candidates)]
        plans.append(
            {
                "id": f"layout_plan_{index + 1}",
                "index": index + 1,
                "approved": True,
                "name": f"{style['name']} · {style['tag']}方向",
                "style": style["name"],
                "style_tag": style["tag"],
                "scene": style["scene"],
                "palette": style["palette"],
                "mood": style["mood"],
                "layout_highlights": data.get("needs") or "通透动线、可复制软装、充足收纳",
                "summary": f"{style['name']}，重点呈现 {style['scene']}，软装包含 {style['elements']}。",
                "prompt": _base_layout_prompt(data, style),
                "source": "fallback",
            }
        )
    return plans


def _normalize_plan(item, index, data):
    item = item if isinstance(item, dict) else {}
    style = str(item.get("style") or item.get("风格") or data.get("style_hint") or "AI 家居灵感风")
    tag = str(item.get("style_tag") or item.get("风格标签") or "AI 推荐")
    scene = str(item.get("scene") or item.get("场景") or item.get("scene_direction") or item.get("场景方向") or "阳光充足、温馨治愈的真实家居场景")
    palette = str(item.get("palette") or item.get("色调") or "低饱和自然色")
    mood = str(item.get("mood") or item.get("氛围") or "温暖、松弛、有生活感")
    highlights = str(item.get("layout_highlights") or item.get("空间亮点") or item.get("layout") or "空间动线清晰，兼顾收纳与生活感")
    summary = str(item.get("summary") or item.get("方案说明") or f"{style} 的可居住户型灵感方案")
    prompt = str(item.get("prompt") or item.get("生图提示词") or "")
    if not prompt:
        prompt = _base_layout_prompt(data, {"name": style, "scene": scene, "palette": palette, "mood": mood, "elements": highlights})
    prompt = _ensure_bright_home_prompt(prompt, scene)
    return {
        "id": f"layout_plan_{index}",
        "index": index,
        "approved": item.get("approved") is not False,
        "name": str(item.get("name") or item.get("方案名称") or f"{style} · {tag}方向"),
        "style": style,
        "style_tag": tag,
        "scene": scene,
        "palette": palette,
        "mood": mood,
        "layout_highlights": highlights,
        "summary": summary,
        "prompt": prompt,
        "source": "ai",
    }


def generate_home_layout_plans(data):
    count = max(1, min(int(data.get("count") or 6), 8))
    if not is_text_provider_configured():
        return {"plans": _fallback_plans(data), "source": "fallback"}

    user_payload = {
        "任务": f"为小红书 AI 家居户型图账号生成 {count} 个可审核的生图方案",
        "用户描述": data.get("description") or "用户还没有明确想法，请提供热门与小众兼具的方向",
        "户型类型": data.get("layout_type") or data.get("layoutType") or "未指定",
        "面积": data.get("area") or "未指定",
        "居住者": data.get("household") or "未指定",
        "核心需求": data.get("needs") or "未指定",
        "风格偏好": data.get("style_hint") or data.get("styleHint") or "未指定",
        "氛围偏好": data.get("mood") or "未指定",
        "用户方案建议": data.get("advice") or data.get("plan_revision") or data.get("planRevision") or "",
        "是否探索风格": bool(data.get("discover")),
        "画幅": data.get("aspect_ratio") or data.get("aspectRatio") or "9:16",
        "上一组方案": data.get("previous_plans") or data.get("previousPlans") or [],
        "推荐场景库": HOME_LAYOUT_SCENE_DIRECTIONS,
        "整体审美方向": [
            "默认生成阳光、色彩缤纷、温馨、温暖、治愈、真实可居住的家居场景",
            "优先选择清晨、白天、午后或有余晖的明亮时段；如果需要灯光，也必须是温暖不昏暗的室内灯光",
            "可以多给彩色软装、花草、阳台、开放餐厨、阅读角、咖啡角、亲子收纳、艺术工作室等有生活气的场景",
            "不要暗黑、压抑、阴冷、恐怖、废土、重工业、赛博夜店、大面积黑灰墙面或过度冷色夜景",
        ],
        "硬性要求": [
            "只输出方案 JSON，不生成图片，不输出解释文字",
            "每个方案必须是完整可直接调用生图模型的中文 prompt",
            "户型图必须具备真实可居住的空间关系、合理动线、正确透视和清晰功能分区",
            "同一批方案要有明确风格和场景差异；用户没指定风格时，混合热门与小众明亮治愈方向",
            "每个 prompt 都必须写明场景方向、色调、光线时段、软装材质和空间功能分区",
            "prompt 必须包含无人物、无文字、无 logo、无水印、无乱码、无畸形家具、无错误透视、不要暗黑压抑等负向约束",
        ],
        "输出格式": {
            "plans": [
                {
                    "name": "方案名",
                    "style": "具体风格",
                    "style_tag": "热门/小众/混搭",
                    "scene": "具体场景方向",
                    "palette": "主色调",
                    "mood": "氛围关键词",
                    "layout_highlights": "空间亮点",
                    "summary": "方案说明",
                    "prompt": "完整中文生图提示词",
                }
            ]
        },
    }
    payload = prepare_text_payload({
        "model": settings.text_model,
        "messages": [
            {
                "role": "system",
                "content": "你是资深室内设计师、AI 家居视觉策划和小红书家居内容主理人。输出必须是严格 JSON。",
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.95,
    }, json_output=True)
    try:
        result = post_json(_chat_url(), payload, _headers(), timeout=300, ssl_verify=settings.text_ssl_verify)
        content = result["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        raw_plans = parsed.get("plans") if isinstance(parsed, dict) else parsed
        if not isinstance(raw_plans, list) or not raw_plans:
            raise ValueError("AI 没有返回方案列表")
        return {"plans": [_normalize_plan(item, index + 1, data) for index, item in enumerate(raw_plans[:count])], "source": "ai"}
    except Exception as exc:
        return {"plans": _fallback_plans(data), "source": "fallback", "warning": str(exc)}


def _fallback_copy_item(context, hook, index):
    style = context.get("style") or "治愈自然风"
    layout_type = context.get("layout_type") or "loft 公寓"
    highlights = context.get("layout_highlights") or "上下层分区、采光和收纳"
    mood = context.get("mood") or "温暖松弛"
    scene = context.get("scene") or "阳光充足的温馨家居场景"
    title_map = {
        "emotion": f"谁懂啊！{style}{layout_type}真的太想住进去了",
        "layout": f"{layout_type}这样装，把空间利用得太聪明了",
        "save": f"装修前先收藏，这套{style}小家太有参考价值",
        "prompt": f"想要这套{style}户型图提示词的姐妹看这里",
        "soft": f"普通家也能抄的{style}软装公式",
        "compare": f"{style}和奶油风，你更想住进哪一套？",
    }
    title = title_map.get(hook, title_map["emotion"])
    content = (
        f"{title}\n\n"
        f"这套图最打动我的不是看起来多贵，而是每个角落都像真的会有人在里面生活。"
        f"整体是 {style}，主打 {mood}。场景重点是 {scene}，{highlights}，看起来通透但不空，细节也很有家的温度。\n\n"
        "普通家不用照搬全套硬装，先从配色、暖光、窗帘、地毯和收纳开始，已经能把氛围拉起来。"
        "装修前多看图，不是为了复制同一套房，而是找到自己想回去的生活方式。\n\n"
        "你们下一套想看什么风格？评论区告诉我。"
    )
    return {
        "hook": HOOK_LABELS.get(hook, hook),
        "title": title,
        "content": content,
        "cover_phrases": ["这才是我想住的家", f"{style} 太治愈了", "装修前先收藏", "城市里的理想小家", "把家装成会呼吸的样子"],
        "comment_ctas": ["你更喜欢这种风格还是下一套？", "想要同款提示词可以评论“风格”。", "下一期想看什么户型？"],
        "hashtags": ["#loft公寓", "#室内设计", "#家居灵感", "#装修灵感", "#梦中情房", "#小户型装修", "#AI家居设计", "#理想生活"],
        "soft_furnishing_keywords": ["暖光台灯", "浅色地毯", "原木家具", "棉麻窗帘", "绿植", "开放书架"],
    }


def _normalize_copy_item(item, hook, context):
    fallback = _fallback_copy_item(context, hook, 1)
    item = item if isinstance(item, dict) else {}
    def text_list(value, fallback_value):
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()][:12] or fallback_value
        if isinstance(value, str):
            values = [x.strip(" -•") for x in value.splitlines() if x.strip()]
            return values[:12] or fallback_value
        return fallback_value
    return {
        "hook": str(item.get("hook") or item.get("钩子类型") or fallback["hook"]),
        "title": str(item.get("title") or item.get("标题") or fallback["title"]),
        "content": str(item.get("content") or item.get("正文") or fallback["content"]),
        "cover_phrases": text_list(item.get("cover_phrases") or item.get("封面短句"), fallback["cover_phrases"]),
        "comment_ctas": text_list(item.get("comment_ctas") or item.get("评论区引导"), fallback["comment_ctas"]),
        "hashtags": text_list(item.get("hashtags") or item.get("标签"), fallback["hashtags"]),
        "soft_furnishing_keywords": text_list(item.get("soft_furnishing_keywords") or item.get("软装关键词"), fallback["soft_furnishing_keywords"]),
    }


def generate_home_layout_copy(context, hooks, goal="引导收藏"):
    hooks = [hook for hook in hooks if hook in HOOK_LABELS] or ["emotion", "layout", "save"]
    if not is_text_provider_configured():
        return {"items": [_fallback_copy_item(context, hook, index) for index, hook in enumerate(hooks, start=1)], "source": "fallback"}

    user_payload = {
        "任务": "基于一张已经生成的 AI 家居户型图，生成小红书爆款图文文案",
        "账号定位": "AI 家居灵感 + 户型拆解 + 可复制软装建议 + 情绪价值种草",
        "图片信息": context,
        "钩子方向": [{"id": hook, "name": HOOK_LABELS[hook]} for hook in hooks],
        "转化目标": goal,
        "固定输出要求": [
            "每个钩子方向输出 1 套完整内容",
            "每套包含 5 个爆款标题、1 篇正文、5 个封面短句、3 个评论区引导、8-12 个标签、同款软装关键词",
            "正文必须包含情绪钩子、空间拆解、风格亮点、普通人可复制建议、生活场景想象、互动引导",
            "语言像小红书真人博主，不像设计公司；避免“本方案采用、空间规划合理、高级感爆棚、豪宅既视感”等表达",
            "不要声称图片由 AI 生成；不要编造图片中看不见的面积、预算、品牌或施工效果",
        ],
        "输出格式": {
            "items": [
                {
                    "hook": "钩子名称",
                    "title": "从 5 个标题中选出的主标题",
                    "titles": ["标题1", "标题2", "标题3", "标题4", "标题5"],
                    "content": "完整正文",
                    "cover_phrases": ["封面短句1"],
                    "comment_ctas": ["评论引导1"],
                    "hashtags": ["#标签"],
                    "soft_furnishing_keywords": ["软装关键词"],
                }
            ]
        },
    }
    text_content = json.dumps(user_payload, ensure_ascii=False)
    message_content = text_content
    image_url = context.get("image_url") or ""
    if text_provider_supports_images() and isinstance(image_url, str) and image_url.startswith(("http://", "https://", "data:image/")):
        message_content = [
            {"type": "text", "text": text_content},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    payload = prepare_text_payload({
        "model": settings.text_model,
        "messages": [
            {
                "role": "system",
                "content": "你是小红书家居爆款内容策划，擅长把家居图转化为有情绪、有空间逻辑、可收藏的真实种草笔记。输出严格 JSON。",
            },
            {"role": "user", "content": message_content},
        ],
        "temperature": 0.9,
    }, json_output=True)
    try:
        result = post_json(_chat_url(), payload, _headers(), timeout=300, ssl_verify=settings.text_ssl_verify)
        content = result["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        raw_items = parsed.get("items") if isinstance(parsed, dict) else parsed
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("AI 没有返回文案列表")
        return {"items": [_normalize_copy_item(item, hooks[index % len(hooks)], context) for index, item in enumerate(raw_items[: len(hooks)])], "source": "ai"}
    except Exception as exc:
        return {"items": [_fallback_copy_item(context, hook, index) for index, hook in enumerate(hooks, start=1)], "source": "fallback", "warning": str(exc)}


def run_home_layout_image_job(store, job_id):
    job = store.get_job(job_id)
    if not job:
        return
    config = job.get("config") or {}
    plans = config.get("plans") or []
    if not plans:
        store.update_job(job_id, status="failed", progress=100, detail="没有可生成的户型图方案")
        return

    store.update_job(job_id, progress=8, detail="整理户型图生图提示词")
    created_assets = []
    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        sleep(0.1)
        prompt = str(plan.get("prompt") or "").strip()
        if not prompt:
            plan = _normalize_plan(plan, index, config)
            prompt = plan["prompt"]
        try:
            store.update_job(job_id, progress=max(10, int((index - 1) / total * 85)), detail=f"正在生成户型图 {index}/{total}")
            result = create_image_task(
                prompt=prompt,
                size="auto",
                aspect_ratio=config.get("aspect_ratio") or config.get("aspectRatio") or "9:16",
                images=None,
            )
            result = wait_for_image_result(result, max_wait=300)
            provider_status = result.get("status") or ("succeeded" if result.get("url") else "failed")
            if not result.get("url") and str(provider_status).lower() in {"completed", "succeeded", "success"}:
                provider_status = "failed"
        except ImageProviderNotConfigured as exc:
            result = {"error": str(exc)}
            provider_status = "failed"
        except Exception as exc:
            result = {"error": str(exc)}
            provider_status = "failed"

        asset = store.create_asset(
            {
                "product_id": HOME_LAYOUT_ACCOUNT_ID,
                "product_name": HOME_LAYOUT_ACCOUNT_NAME,
                "type": "cover",
                "title": f"{plan.get('style') or 'AI 家居'} · 户型图 {index}",
                "status": "review",
                "style": "home_layout",
                "content": prompt,
                "url": result.get("url") or "",
                "provider_task": result,
                "provider_status": provider_status,
                "generation_plan": {"kind": "home_layout", **plan, "prompt": prompt},
            }
        )
        created_assets.append(asset)

    succeeded = [asset for asset in created_assets if asset.get("url")]
    detail = f"已生成 {len(succeeded)}/{total} 张户型图"
    if not succeeded:
        detail += "，图片接口没有返回可用图片"
    store.update_job(
        job_id,
        status="completed" if succeeded else "failed",
        progress=100,
        detail=detail,
        result={"asset_ids": [asset["id"] for asset in created_assets]},
    )
