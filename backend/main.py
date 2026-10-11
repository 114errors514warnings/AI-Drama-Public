"""FastAPI 应用：API 路由 + 前端静态托管。

启动：uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config
from .exporter import export_json, export_markdown
from .judge import judge_session
from .llm_client import LLMError
from .memory_ops import merge_facts
from .metrics import session_metrics as compute_metrics
from .session import SessionManager

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
FRONTEND_DIR = ROOT / "frontend"

# 启动时读取 API Key（仅保存在内存中，任何接口都不返回完整 key）
config = Config(strict=False)

app = FastAPI(title="AI Drama · 群聊剧情模拟系统", version="1.0.0")
manager = SessionManager(config, SESSIONS_DIR)


# ---------- 请求模型 ----------
class SessionCreate(BaseModel):
    name: str
    kb_path: str


class ConfigBody(BaseModel):
    model: str | None = None
    temperature: float | None = None
    world_check: bool | None = None
    world_check_mode: str | None = None
    world_check_retries: int | None = None
    base_url: str | None = None
    api_key: str | None = None
    time_format: str | None = None
    time_fallback: str | None = None
    provider: str | None = None
    llm_providers: dict | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    max_tokens: int | None = None
    character_temperature: float | None = None
    anti_ai_flavor: bool | None = None


class SessionUpdate(BaseModel):
    name: str | None = None


class ChatBody(BaseModel):
    session_id: str | None = None
    message: str
    agent_name: str | None = None


class AgentActionBody(BaseModel):
    session_id: str | None = None
    name: str


class MemoryBody(BaseModel):
    long_memory: list[str] = []


class PromptBody(BaseModel):
    name: str
    system_prompt: str = ""
    lock: bool = True


class RulesBody(BaseModel):
    rules: str = ""


class DebugTurnBody(BaseModel):
    message: str = ""
    agent_name: str | None = None
    commit: bool = False


def _session(session_id: str | None):
    sid = session_id or manager.active_id
    if not sid:
        raise HTTPException(status_code=400, detail="还没有任何会话，请先创建一个群聊会话")
    ws = manager.get(sid)
    if not ws:
        raise HTTPException(status_code=404, detail=f"会话不存在: {sid}")
    return ws


def _to_info(ws):
    """按当前时间格式配置返回会话信息。"""
    return ws.to_info(time_format=config.time_format, fallback=config.time_fallback)


# ---------- 配置 ----------
@app.get("/api/config")
def get_config():
    return {
        "model": config.model,
        "temperature": config.temperature,
        "world_check": config.world_check,
        "world_check_mode": config.world_check_mode,
        "world_check_retries": config.world_check_retries,
        "time_format": config.time_format,
        "time_fallback": config.time_fallback,
        "base_url": config.base_url,
        "masked_key": config.masked_key() if config.api_key else "",
        "key_loaded": bool(config.api_key),
        "key_file": config.api_key_file,
        "config_error": config.error,
        "provider": config.provider,
        "providers": [
            {"name": name, "base_url": cfg.get("base_url", ""), "model": cfg.get("model", ""),
             "key_loaded": bool(cfg.get("api_key"))}
            for name, cfg in sorted(config.llm_providers.items())
        ],
        "top_p": config.top_p,
        "frequency_penalty": config.frequency_penalty,
        "presence_penalty": config.presence_penalty,
        "max_tokens": config.max_tokens,
        "character_temperature": config.character_temperature,
        "anti_ai_flavor": config.anti_ai_flavor,
    }


@app.post("/api/config")
def set_config(body: ConfigBody):
    config.update(
        model=body.model,
        temperature=body.temperature,
        world_check=body.world_check,
        world_check_mode=body.world_check_mode,
        world_check_retries=body.world_check_retries,
        base_url=body.base_url,
        api_key=body.api_key,
        time_format=body.time_format,
        time_fallback=body.time_fallback,
        provider=body.provider,
        llm_providers=body.llm_providers,
        top_p=body.top_p,
        frequency_penalty=body.frequency_penalty,
        presence_penalty=body.presence_penalty,
        max_tokens=body.max_tokens,
        character_temperature=body.character_temperature,
        anti_ai_flavor=body.anti_ai_flavor,
    )
    return get_config()


@app.post("/api/config/test")
def test_config():
    """用当前 API Key 发送一次极小请求验证连通性。"""
    if not config.api_key:
        raise HTTPException(status_code=400, detail="尚未设置 API Key")
    try:
        reply = manager.llm.chat(
            [{"role": "user", "content": "ping"}], max_tokens=10)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"连接失败: {exc}")
    return {"ok": True, "reply": (reply or "")[:50]}


# ---------- 知识库目录浏览 / 校验 ----------

@app.get("/api/kb/browse")
def kb_browse(path: str = Query("", description="浏览的目录；为空表示“此电脑”顶层")):
    """列出目录下的子文件夹，供前端“预览并选择”知识库路径。
    为空时返回本机各盘符（起始根 = 此电脑）。"""
    import string
    if not path:
        items = []
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                items.append({"name": f"{letter}:", "path": str(drive), "is_dir": True})
        return {"root": True, "path": "", "parent": "", "items": items}
    base = Path(path)
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=400, detail="路径不存在或不是文件夹")
    items = []
    for child in sorted(base.iterdir()):
        if child.is_dir():
            items.append({"name": child.name, "path": str(child), "is_dir": True})
    parent = "" if base.parent == base else str(base.parent)
    return {"root": False, "path": str(base), "parent": parent, "items": items}


@app.get("/api/kb/validate")
def kb_validate(path: str = Query(..., description="知识库根目录绝对路径")):
    """校验目录是否可作为知识库：需含 Character / Memory / World 三个子目录。"""
    base = Path(path)
    exists = base.exists()
    is_dir = base.is_dir()
    missing = []
    if exists and is_dir:
        for sub in ("Character", "Memory", "World"):
            if not (base / sub).exists():
                missing.append(sub)
    return {
        "path": str(base),
        "exists": exists,
        "is_dir": is_dir,
        "missing_dirs": missing,
        "valid": exists and is_dir and len(missing) == 0,
    }


@app.post("/api/kb/native-pick")
def kb_native_pick():
    """在服务端本机弹出 Windows 系统「资源管理器风格」选择文件夹对话框，返回所选绝对路径。

    浏览器无法向外提供文件夹的磁盘绝对路径，故由同机后端弹原生对话框并取回路径。
    用系统自带 powershell.exe(5.1) + Add-Type 封装 IFileOpenDialog（FOS_PICKFOLDERS），
    即新版资源管理器风格、顶部带地址栏/路径输入框的文件夹选择窗口。
    若弹不出 / 用户取消等，抛 500，前端据此 tips 报错。
    """
    import subprocess  # noqa: PLC0415
    code = """Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
public class FileOpenDialog_RCW { }

[ComImport, Guid("D57C7288-D4AD-4768-BE02-9D969532D960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IFileOpenDialogNative
{
    [PreserveSig] int Show(IntPtr hwndOwner);
    [PreserveSig] int SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
    [PreserveSig] int SetFileTypeIndex(uint iFileType);
    [PreserveSig] int GetFileTypeIndex(out uint piFileType);
    [PreserveSig] int Advise(IntPtr pfde, out uint pdwCookie);
    [PreserveSig] int Unadvise(uint dwCookie);
    [PreserveSig] int SetOptions(uint fos);
    [PreserveSig] int GetOptions(out uint pfos);
    [PreserveSig] int SetDefaultFolder(IShellItem psi);
    [PreserveSig] int SetFolder(IShellItem psi);
    [PreserveSig] int GetFolder(out IShellItem ppsi);
    [PreserveSig] int GetCurrentSelection(out IShellItem ppsi);
    [PreserveSig] int SetFileName(string pszName);
    [PreserveSig] int GetFileName(out string pszName);
    [PreserveSig] int SetTitle(string pszTitle);
    [PreserveSig] int SetOkButtonLabel(string pszText);
    [PreserveSig] int SetFileNameLabel(string pszLabel);
    [PreserveSig] int GetResult(out IShellItem ppsi);
    [PreserveSig] int AddPlace(IShellItem psi, int fdap);
    [PreserveSig] int SetDefaultExtension(string pszDefaultExtension);
    [PreserveSig] int Close(int hr);
    [PreserveSig] int SetClientGuid(ref Guid guid);
    [PreserveSig] int ClearClientData();
    [PreserveSig] int SetFilter(object pFilter);
}

[ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellItem
{
    void BindToHandler();
    [PreserveSig] int GetParent(out IShellItem ppsi);
    [PreserveSig] int GetDisplayName(uint sigdnName, out string pszName);
    [PreserveSig] int GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    [PreserveSig] int Compare(IShellItem psi, uint hint, out int piOrder);
}

public static class ModernFolderPicker
{
    public static string Pick(string title)
    {
        const uint FOS_PICKFOLDERS = 0x20;
        const uint FOS_FORCEFILESYSTEM = 0x40;
        const uint SIGDN_FILESYSPATH = 0x80058000;
        var dlg = (IFileOpenDialogNative)(object)new FileOpenDialog_RCW();
        dlg.SetOptions(FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
        dlg.SetTitle(title);
        if (dlg.Show(IntPtr.Zero) == 0)
        {
            IShellItem item;
            if (dlg.GetResult(out item) == 0)
            {
                string path;
                if (item.GetDisplayName(SIGDN_FILESYSPATH, out path) == 0)
                    return path ?? "";
            }
        }
        return "";
    }
}
"@
[Console]::Write([ModernFolderPicker]::Pick('选择知识库目录'))
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", code],
            capture_output=True, text=True, timeout=600,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500,
                            detail=f"无法打开系统文件夹选择对话框: {exc}")
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        tail = err.splitlines()[-1] if err else "未知错误"
        raise HTTPException(status_code=500,
                            detail=f"无法打开系统文件夹选择对话框: {tail}")
    if not out:
        raise HTTPException(status_code=500, detail="未选择文件夹（已取消）")
    return {"path": out}


# ---------- 会话 ----------
@app.get("/api/sessions")
def list_sessions():
    return {"active_id": manager.active_id, "sessions": manager.list_info()}


@app.post("/api/sessions")
def create_session(body: SessionCreate):
    name = (body.name or "").strip() or "新群聊"
    kb_path = (body.kb_path or "").strip()
    if not kb_path:
        raise HTTPException(status_code=400, detail="必须指定知识库路径")
    try:
        ws = manager.create(name, kb_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"创建会话失败: {exc}")
    return _to_info(ws)


@app.post("/api/sessions/{sid}/activate")
def activate_session(sid: str):
    try:
        ws = manager.activate(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _to_info(ws)


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    try:
        manager.delete(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@app.get("/api/sessions/{sid}/info")
def session_info(sid: str):
    return _to_info(_session(sid))


@app.patch("/api/sessions/{sid}")
def update_session(sid: str, body: SessionUpdate):
    ws = _session(sid)
    ws.rename(body.name or "")
    return _to_info(ws)


@app.post("/api/sessions/{sid}/clear")
def clear_session(sid: str):
    ws = _session(sid)
    ws.clear_transcript()
    return _to_info(ws)


@app.get("/api/sessions/{sid}/characters")
def session_characters(sid: str):
    ws = _session(sid)
    agents = {a.name: a.status for a in ws.registry.list()}
    chars = []
    for name in ws.kb.character_names():
        profile = ws.kb.get_character_profile(name) or ""
        chars.append({
            "name": name,
            "status": agents.get(name, "未实例化"),
            "profile_preview": profile[:150],
            "brief": ws.kb.get_character_brief(name),
        })
    return {"characters": chars, "world": ws.kb.overview()}


@app.get("/api/sessions/{sid}/character")
def character_detail(sid: str, name: str = Query(..., description="角色名（可为任意字符，走查询串传输）")):
    ws = _session(sid)
    resolved = ws.kb.resolve_character(name)
    display = resolved or name
    # 功能 Agent（如导演）不在知识库，也从 Registry 取它，使其详情/记忆可读
    agent = ws.registry.get(display)
    kb_profile = ws.kb.get_character_profile(display) or ""
    profile = kb_profile or (agent.profile if agent else "")
    return {
        "name": display,
        "role": agent.role if agent else "",
        "status": agent.status if agent else "未实例化",
        "profile": profile,
        "emotion_state": agent.emotion_state if agent else "—",
        "relationships": agent.relationships if agent else {},
        "long_memory": agent.long_memory if agent else [],
        "skills": agent.skills if agent else [],
        "system_prompt": agent.system_prompt if agent else "",
        "prompt_locked": bool(getattr(agent, "prompt_locked", False)) if agent else False,
        "world_name": ws.kb.world_name,
    }


@app.put("/api/sessions/{sid}/character/memory")
def update_character_memory(sid: str, body: MemoryBody, name: str = Query(..., description="角色名（可为任意字符，走查询串传输）")):
    """整表替换角色的长期记忆（增/删/改一次完成），并重建 System Prompt 后落盘。"""
    ws = _session(sid)
    # 通用取 Agent：角色按知识库名自动创建，功能 Agent（导演）也走 Registry/创建
    agent = ws.runtime.get_or_create_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"找不到该 Agent: {name}")
    # 清洗 + 去重 + 冲突消解（与 Memory Manager 自动抽取使用同一套治理逻辑），上限 80 条
    merged, stats = merge_facts([], body.long_memory)
    agent.long_memory = merged
    ws.runtime.refresh_prompt(agent)
    ws.memory.save_agent(agent)
    ws.save()
    return {"ok": True, "long_memory": agent.long_memory, "stats": stats}


# ---------- 提示词查看 / 编辑（V4） ----------
@app.put("/api/sessions/{sid}/agents/prompt")
def set_agent_prompt(sid: str, body: PromptBody):
    """手动设置 Agent 提示词（lock=True 后不再被自动重建覆盖）。"""
    ws = _session(sid)
    agent = ws.runtime.get_or_create_agent((body.name or "").strip())
    if not agent:
        raise HTTPException(status_code=404, detail=f"找不到该 Agent: {body.name}")
    ws.runtime.set_prompt(agent, body.system_prompt, lock=body.lock)
    ws.save()
    return {"ok": True, "name": agent.name, "prompt_locked": agent.prompt_locked}


@app.delete("/api/sessions/{sid}/agents/prompt")
def reset_agent_prompt(sid: str, name: str = Query(...)):
    """解除手动覆盖，按角色卡/世界自动重建提示词。"""
    ws = _session(sid)
    agent = ws.registry.get(name) or ws.runtime.get_or_create_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"找不到该 Agent: {name}")
    ws.runtime.reset_prompt(agent)
    ws.memory.save_agent(agent)
    ws.save()
    return {"ok": True, "name": agent.name, "system_prompt": agent.system_prompt,
            "prompt_locked": agent.prompt_locked}


@app.put("/api/sessions/{sid}/world/rules")
def set_world_rules(sid: str, body: RulesBody):
    """手动覆盖世界背景（注入提示词），并立即重建未锁定的 Agent 提示词。"""
    ws = _session(sid)
    ws.world.rules_override = body.rules or ""
    for agent in ws.registry.list():
        if not getattr(agent, "prompt_locked", False):
            ws.runtime.refresh_prompt(agent)
    ws.save()
    return {"ok": True, "rules_override": ws.world.rules_override}


@app.delete("/api/sessions/{sid}/world/rules")
def reset_world_rules(sid: str):
    """清除世界背景覆盖，回退为知识库装载内容。"""
    ws = _session(sid)
    ws.world.rules_override = ""
    for agent in ws.registry.list():
        if not getattr(agent, "prompt_locked", False):
            ws.runtime.refresh_prompt(agent)
    ws.save()
    return {"ok": True, "rules": ws.world.rules, "rules_override": ""}



# ---------- 对话 ----------
@app.post("/api/sessions/{sid}/chat")
def group_chat(sid: str, body: ChatBody):
    ws = _session(sid)
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        return ws.director.run_group_turn(msg)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))




@app.post("/api/sessions/{sid}/chat/agent")
def agent_chat(sid: str, body: ChatBody):
    """单Agent对话（场外，不进群聊转录/记忆）。"""
    ws = _session(sid)
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="消息不能为空")
    name = (body.agent_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请指定对话的 Agent 名称")
    try:
        return ws.director.run_agent_turn(name, msg)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/sessions/{sid}/side_chat/{agent}")
def side_chat_history(sid: str, agent: str):
    ws = _session(sid)
    return {"side_chat": ws.side_chats.get(agent, [])[-200:]}

# ---------- Agent Registry / Runtime ----------
@app.get("/api/sessions/{sid}/agents")
def list_agents(sid: str):
    ws = _session(sid)
    return {
        "agents": ws.registry.to_dict(),
        "characters_in_kb": ws.kb.character_names(),
    }


@app.post("/api/sessions/{sid}/agents/create")
def create_agent(sid: str, body: AgentActionBody):
    ws = _session(sid)
    name = (body.name or "").strip()
    try:
        agent = ws.runtime.create_agent(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    ws.save()
    return {"ok": True, "agent": {"name": agent.name, "status": agent.status}}


@app.post("/api/sessions/{sid}/agents/{action}")
def agent_action(sid: str, action: str, body: AgentActionBody):
    ws = _session(sid)
    if action not in ("destroy", "pause", "resume"):
        raise HTTPException(status_code=400, detail="未知操作")
    ok = getattr(ws.runtime, f"{action}_agent")((body.name or "").strip())
    if not ok:
        raise HTTPException(status_code=404, detail=f"Agent 不存在或操作失败: {body.name}")
    ws.save()
    return {"ok": True}


# ---------- 调试 / 自检（TODO-4：群聊 + 单 Agent） ----------
# 说明：以下接口只读或 dry-run（默认 commit=false），不污染转录/世界状态，便于复现问题。

@app.get("/api/sessions/{sid}/debug/group/preview")
def debug_group_preview(sid: str, message: str = Query(..., description="本轮用户输入")):
    """群聊模式：构建导演规划消息但不调用 LLM（看提示词与上下文来源）。"""
    return _session(sid).director.preview_group_plan(message)


@app.post("/api/sessions/{sid}/debug/group/plan")
def debug_group_plan(sid: str, body: DebugTurnBody):
    """群聊模式：真调用一次导演规划，返回原始输出与解析结果；不写任何状态。"""
    return _session(sid).director.run_group_plan(body.message or "")


@app.get("/api/sessions/{sid}/debug/agent/messages")
def debug_agent_messages(sid: str,
                         agent_name: str = Query(..., description="Agent 名（导演/世界/记忆管理/梗概/角色）"),
                         message: str = Query("", description="本轮单聊输入")):
    """单 Agent：构建对话消息但不调用 LLM，并给出提示词是否强制 JSON。"""
    ws = _session(sid)
    agent = ws.registry.get(agent_name) or ws.runtime.get_or_create_agent(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"找不到该 Agent: {agent_name}")
    system = agent.system_prompt or ""
    return {
        "agent": {"name": agent.name, "role": agent.role, "status": agent.status,
                  "prompt_locked": bool(getattr(agent, "prompt_locked", False))},
        "messages": ws.director.build_agent_messages(agent, message),
        "system_prompt": system,
        "system_prompt_requires_json": ("只输出导演规划 JSON" in system) or ("只输出严格 JSON" in system),
        "side_chat_len": len(ws.side_chats.get(agent.name, [])),
    }


@app.post("/api/sessions/{sid}/debug/agent/turn")
def debug_agent_turn(sid: str, body: DebugTurnBody):
    """单 Agent：调用一次对话；commit=false（默认）为 dry-run，不写入场外记录。"""
    name = (body.agent_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请指定 agent_name")
    return _session(sid).director.run_agent_turn(name, body.message or "", commit=body.commit)


@app.get("/api/sessions/{sid}/debug/context")
def debug_context(sid: str, agent_name: str = Query("", description="可选：查看某 Agent 的提示词与单聊长度")):
    """上下文自检：群聊规划引用什么、场外单聊是否被引用。"""
    return _session(sid).director.debug_context(agent_name)


@app.delete("/api/sessions/{sid}/debug/side-chats")
def debug_clear_side_chats(sid: str, agent_name: str = Query("", description="留空=清全部")):
    """清空场外单聊（测试隔离用；不影响群聊转录与角色记忆）。"""
    ws = _session(sid)
    if agent_name:
        ws.side_chats.pop(agent_name, None)
    else:
        ws.side_chats = {}
    ws.save()
    return {"ok": True, "side_chats": {k: len(v) for k, v in ws.side_chats.items()}}


# ---------- 世界 / 转录 ----------
@app.get("/api/sessions/{sid}/world")
def world_info(sid: str):
    return _session(sid).world.to_dict(
        time_format=config.time_format, fallback=config.time_fallback)


@app.post("/api/sessions/{sid}/synopsis")
def update_synopsis(sid: str):
    """手动刷新剧情梗概。"""
    ws = _session(sid)
    try:
        synopsis = ws.director.update_synopsis(force=True)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"synopsis": synopsis}


@app.get("/api/sessions/{sid}/transcript")
def transcript(sid: str):
    ws = _session(sid)
    return {"transcript": ws.transcript[-300:]}


# ---------- 评测 / 观测 / 导出（V2） ----------
@app.get("/api/sessions/{sid}/metrics")
def session_metrics(sid: str):
    """会话硬指标：编排成功率、世界违规率、场外泄漏数、token/延迟、梗概覆盖度 + 门禁判定。"""
    ws = _session(sid)
    return compute_metrics(ws)


@app.get("/api/sessions/{sid}/turns")
def session_turns(sid: str, limit: int = Query(50, ge=1, le=500)):
    """每轮编排明细（含 Agent 调用图与耗时）。"""
    ws = _session(sid)
    return {"turns": ws.memory.load_turns(limit)}


@app.get("/api/sessions/{sid}/export")
def session_export(sid: str, format: str = Query("md", pattern="^(md|json)$")):
    """导出会话（Markdown / JSON）。"""
    ws = _session(sid)
    if format == "json":
        return JSONResponse(export_json(ws))
    return PlainTextResponse(export_markdown(ws), media_type="text/markdown; charset=utf-8")


@app.post("/api/sessions/{sid}/judge")
def session_judge(sid: str, samples: int = Query(3, ge=1, le=5)):
    """LLM 裁判观察项（人设一致率）：多采样取均值，仅观察，不进入硬门禁。"""
    ws = _session(sid)
    try:
        return judge_session(ws, samples=samples)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------- 前端静态托管 ----------
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

