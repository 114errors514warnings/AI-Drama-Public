"""会话导出（V2 工程化）：把群聊转录 + 世界状态 + 角色记忆导出为 Markdown / JSON。"""
from __future__ import annotations


def export_json(session) -> dict:
    agents = []
    for a in session.registry.list():
        agents.append({
            "name": a.name,
            "role": a.role,
            "status": a.status,
            "emotion_state": a.emotion_state,
            "relationships": a.relationships,
            "long_memory": list(a.long_memory),
        })
    return {
        "session": {
            "id": session.id,
            "name": session.name,
            "world_name": session.world.world_name,
            "kb_path": session.kb_path,
        },
        "world": session.world.to_dict(),
        "agents": agents,
        "transcript": list(session.transcript),
    }


def export_markdown(session) -> str:
    world = session.world
    lines: list[str] = [
        f"# {session.name}",
        "",
        f"- 世界：{world.world_name}",
        f"- 知识库：{session.kb_path}",
        f"- 当前时间：{world.display_time()}",
        f"- 当前地点：{world.location}",
        "",
    ]
    if world.synopsis.strip():
        lines += ["## 剧情梗概", "", world.synopsis.strip(), ""]
    if world.timeline:
        lines += ["## 时间线", ""]
        for entry in world.timeline[-50:]:
            time_text = world.display_time(date=entry.get("date", ""), time_of_day=entry.get("time_of_day", ""))
            lines.append(f"- {time_text} @ {entry.get('location', '')}：{entry.get('event', '')}")
        lines.append("")

    agents = [a for a in session.registry.list() if a.role == "character"]
    if agents:
        lines += ["## 角色与长期记忆", ""]
        for agent in agents:
            lines.append(f"### {agent.name}（{agent.status} · 情绪：{agent.emotion_state}）")
            if agent.long_memory:
                for fact in agent.long_memory:
                    lines.append(f"- {fact}")
            else:
                lines.append("-（暂无长期记忆）")
            lines.append("")

    lines += ["## 群聊转录", ""]
    for m in session.transcript:
        role = m.get("role", "assistant")
        if role == "user":
            who = "用户"
        elif role == "narrator":
            who = "导演"
        else:
            who = m.get("speaker", "角色")
        lines.append(f"**{who}**：{m.get('content', '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
