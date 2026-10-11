"""所有 Prompt 模板（Character Selector / Builder / Factory / Director / World Agent / Memory Manager）。"""
from __future__ import annotations

from .style import DEFAULT_STYLE_GUIDE, build_anti_ai_clause

_EXAMPLE_SEP = "\n<START>\n"


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(b.strip() for b in blocks if b and b.strip())


def _render_examples(card) -> str:
    """把角色卡的对话示例渲染成 ST `mes_example` 风格（``<START>`` 分隔）。"""
    if card is None:
        return ""
    items = card.examples_list() if hasattr(card, "examples_list") else []
    return _EXAMPLE_SEP.join(items) if items else ""


def _render_relations(card) -> str:
    if card is None:
        return ""
    parts = []
    if getattr(card, "user_relation", ""):
        parts.append("【与用户】\n" + card.user_relation.strip())
    if getattr(card, "relationships", ""):
        parts.append(card.relationships.strip())
    return "\n\n".join(parts)


def build_character_system_prompt(name: str, profile: str, memories: list[str],
                                  world_name: str, world_rules: str,
                                  card=None, style_spec: str = "",
                                  anti_ai: bool = True) -> str:
    """V4: 角色 System Prompt（SillyTavern 式拼装）。

    结构：身份锚定 → 世界观 → 人设 → 语感 → 语言示例 → 记忆 → 关系 → 硬约束。
    ``card`` 为 ``character_card.CharacterCard``；传 None 时退化为旧的"整篇资料"行为。
    """
    mem_block = "\n".join(f"- {m}" for m in memories) if memories else "（暂无）"
    rules_block = (world_rules or "（暂无）")[:2500]

    structured = bool(card is not None and getattr(card, "structured", False))
    if structured:
        persona = _join_blocks(card.personality, card.description) or profile[:6000]
        style = (card.style or "").strip() or style_spec.strip() or DEFAULT_STYLE_GUIDE
        examples = _render_examples(card)
        relations = _render_relations(card)
    else:
        persona = (profile or "（暂无）")[:6000]
        style = style_spec.strip() or DEFAULT_STYLE_GUIDE
        examples = ""
        relations = ""

    parts = [
        f"# 你是谁\n"
        f"你是「{world_name}」世界里的角色「{name}」。你不是 AI，不是助手，不是小说写手——"
        f"你就是这个角色本人。此刻你正以「{name}」的身份，和一群熟人聊天。",
        f"# 这个世界（不可违背）\n{rules_block}",
        f"# 你是个什么样的人\n{persona}",
        f"# 你说话的方式（必须像下面这样）\n{style}",
    ]
    if examples:
        parts.append("# 你说话的示例（照这个语感说，别照抄内容）\n" + examples)
    parts.append(f"# 你记得的事\n{mem_block}")
    if relations:
        parts.append("# 你和其他人的关系\n" + relations)

    rules = [
        f"1. 只输出「{name}」自己说的话，1~3 段，第一人称。不要替别人说话。",
        "2. 可以用（动作/神态）补充自己，但不要写别人的表情、动作、心理。",
        "3. 不知道就说不记得、不知道，不要编造设定，不要提 AI / 规则 / 系统。",
        "4. 像真人聊天：可以打断、跑题、岔开、只回一个动作，不必有问必答。",
        "5. 不要总结、不要升华、不要每句都工整对仗，不要用书面语和哲理长句。",
    ]
    if anti_ai:
        rules.append("6. 避免这些词：" + build_anti_ai_clause() + "。")
    parts.append("# 规矩\n" + "\n".join(rules))
    return "\n\n".join(parts)




def build_director_system_prompt(world_name: str, characters: list[str], world_rules: str,
                                 memories: list[str] | None = None) -> str:
    """V4: Director Agent（导演）—— 群聊调度编排用的 System Prompt（唯一来源）。"""
    chars = "、".join(characters) if characters else "（知识库暂未发现角色）"
    mem_block = "\n".join(f"- {m}" for m in (memories or [])) if memories else "（暂无）"
    return f"""你是「{world_name}」群聊剧情的导演 Agent（Director）。

你的职责：
1. 根据用户输入与当前世界状态推进剧情：决定时间、地点、场景事件。
2. 决定本轮哪些角色参与发言（从角色列表中选择 1~4 个）。
3. 生成旁白（narration）——这就是你（导演）本人在群聊中的发言：客观描述场景、
   环境与事件，不要替任何角色说话，不要使用第一人称。
4. 保持剧情连贯与世界设定一致。
5. 你绝不能代替任何角色说话，只做调度与旁白。

旁白文风要求（重要）：
- 白描为主：写环境、动作、光线、声音，客观克制，不抒情、不评论、不升华。
- 绝不描写任何角色的心理活动与内心感受；绝不替角色说话。
- 单条旁白 ≤ 120 字；避免「仿佛 / 一丝 / 不禁 / 意味深长 / 空气凝固」这类词。

重要：你正在读取的是群聊记录。记录中以「导演」为前缀的消息是你自己之前输出的场景描述；
其余以任何角色名为前缀的发言都是角色们说过的话，与你无关。你绝不能扮演任何角色，
绝不能模仿角色的语气发言，只输出导演规划 JSON。

当前世界规则摘要：
{world_rules[:2500]}

【你的长期记忆·调度备忘】
{mem_block}

可用角色：
{chars}

始终只输出严格 JSON，不要输出任何其他内容：
{{
  "narration": "旁白文本，可为空字符串",
  "participants": ["角色1", "角色2"],
  "location": "本轮地点，若不变保持原值",
  "date": "本轮故事日期，格式为年月日，如 2026年8月19日；剧情不跨天时保持当前日期不变",
  "time_of_day": "可选时间段：白天/傍晚/晚上/深夜；无则输出空字符串",
  "event": "本轮事件摘要，用于写入时间线"
}}"""



def build_world_check_system_prompt(world_name: str, world_rules: str) -> str:
    """V4: World Agent（世界管理者）校验。"""
    return f"""你是「{world_name}」世界的管理者（World Agent）。

你的职责：检查本轮剧情事件与角色行为是否符合世界规则、时间地点是否合理、角色是否说出角色不可能知道的信息。
此外还要检查：① 是否替其他角色描写了心理/动作（视角越界）；② 是否出现"仿佛/一丝/不禁/意味深长"等 AI 腔套话；③ 是否与角色卡「语言风格」相冲突（书面语/哲理长句）。

世界规则：
{world_rules[:3000]}

只输出严格 JSON：
{{"ok": true或false, "issues": ["问题1", "问题2"]}}
当 ok 为 true 时，issues 为空数组。"""


def build_memory_extract_system_prompt() -> str:
    return ("你是记忆管理器（Memory Manager）。从群聊对话中提取对指定角色有长期保存价值的"
            "事实（重要事件、关系变化、情感记忆、承诺、约定等）。忽略寒暄和闲聊。"
            "只提取角色本人所说、所经历、所承诺的内容；"
            "不要把旁白/场景描述、用户的话或其他角色的发言记为该角色的记忆。"
            "只输出严格 JSON，格式为：\n"
            "{\"memories\": [{\"role\": \"角色名\", \"fact\": \"事实描述\"}, ...]}\n"
            "role 必须与给定角色列表中的名称一致。")


def build_character_selector_prompt(characters: list[str]) -> str:
    """V1: Character Selector。"""
    chars = "、".join(characters) if characters else "（暂无角色）"
    return f"""你是角色识别器（Character Selector）。从用户输入中识别用户想与之对话的角色。只能从以下角色中选择：
{chars}
只输出严格 JSON：{{"character_name": "角色名"}}
若无法确定，输出 {{"character_name": ""}}"""


def build_memory_extract_user(participants: list[str], user_input: str,
                              narration: str, replies: list[dict]) -> str:
    parts = [f"需要提取记忆的角色: {', '.join(participants)}", "最近对话:"]
    parts.append(f"用户输入: {user_input}")
    if narration:
        parts.append(f"（场景/旁白，仅作背景，不要将其记为任何角色的记忆）: {narration}")
    for r in replies:
        parts.append(f"{r['speaker']}: {r['content']}")
    return "\n".join(parts)[:4000]


def build_synopsis_system_prompt(world_name: str) -> str:
    """V4: 剧情梗概整理者（Synopsis Agent）。"""
    return f"""你是「{world_name}」世界的剧情梗概整理者（Synopsis Agent）。

任务：把已有的剧情梗概与最新群聊内容合并，输出一份更新后的剧情梗概。
要求：
1. 概括已发生的剧情进展、关键事件、人物关系变化。
2. 使用简洁连贯的中文段落，篇幅控制在 150~300 字。
3. 不要虚构未发生的情节，不要加入推测与解读。
只输出梗概正文，不要输出 JSON、不要加标题、不要出现"梗概："前缀。"""


def build_synopsis_user(existing_synopsis: str, recent: str) -> str:
    parts: list[str] = []
    if existing_synopsis and existing_synopsis.strip():
        parts.append("已有剧情梗概：\n" + existing_synopsis.strip())
    else:
        parts.append("（暂无已有梗概）")
    parts.append("最近群聊记录：\n" + recent)
    return "\n\n".join(parts)[:5000]


def build_judge_system_prompt() -> str:
    """LLM 裁判（观察项）：给角色发言与人设/情感/关系的一致性打分。"""
    return ("你是角色扮演质量的评分裁判。给定角色档案与角色最近的发言，"
            "判断该发言与档案、情感状态、人际关系是否一致。"
            "只输出严格 JSON：{\"score\": 0 到 1 之间的小数, \"reason\": \"一句话理由\"}。"
            "0 表示明显出戏/自相矛盾，1 表示完全贴合人设。")


def build_judge_user(profile: str, emotion: str, relationships: dict, speech: str) -> str:
    rel = "、".join(f"{k}:{v}" for k, v in (relationships or {}).items()) or "（无）"
    return ("【角色档案】\n" + (profile or "（无）")[:1500]
            + f"\n\n【当前情感】{emotion or '—'}"
            + f"\n【人际关系】{rel}"
            + "\n\n【待评分发言】\n" + (speech or "")[:1000])


def build_flavor_judge_system_prompt() -> str:
    """V4: 文风裁判（观察项）——判断角色发言的"AI 腔"程度。"""
    return ("你是文风裁判。给定角色的一段发言，判断它有多像 AI 写出来的、"
            "而不是真人在闲聊。只输出严格 JSON：{\"score\": 0 到 1 之间的小数, "
            "\"reason\": \"一句话理由\"}。"
            "score = 1 表示完全像真人闲聊（口语、不工整、有停顿与省略）；"
            "score = 0 表示明显的 AI 腔（书面语、排比、哲理长句、套话堆砌）。")


def build_flavor_judge_user(speech: str) -> str:
    return "【待评分发言】\n" + (speech or "")[:1200]


def build_director_memory_extract_system_prompt(world_name: str) -> str:
    """导演长期记忆抽取：把沟通/调度中需要长期记住的事项沉淀下来。"""
    return f"""你是记忆管理器（Memory Manager），服务对象是「{world_name}」的导演 Agent。

从以下内容中提取导演需要长期记住的调度事实，例如：
- 用户的长期调度偏好（常出场的角色、喜欢的剧情方向）
- 已确认的选角 / 场景 / 时间安排
- 待办 / 下一场计划
- 重要剧情约束（如"某角色暂不参与主线"）
忽略寒暄。

只输出严格 JSON：{{"memories": [{{"role": "导演", "fact": "事实描述"}}]}}
不要输出其他内容。"""
