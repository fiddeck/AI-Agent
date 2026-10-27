"""
AI-Agent 后端 (FastAPI + WebSocket)

职责:
  * 提供网页版界面 (/) 与桌面版共用的 WebSocket 引擎 (/ws)
  * 通过 MCP stdio 调用 server.py 的 15 个系统级工具
  * 会话持久化到 data/sessions/*.json —— 刷新页面 / 重启后端 / 桌面端重启都不会丢对话
  * 支持停止生成、工具执行中停止(会重启 MCP 进程以中断子进程)

启动:  python webui.py     (默认 http://127.0.0.1:8000，端口被占用/保留时自动顺延)
配置:  settings.json (网页版 ⚙ 与桌面版共用)；环境变量 OPENAI_API_KEY / OPENAI_MODEL /
       OPENAI_BASE_URL / WEBUI_PORT 优先级更高。

WebSocket 协议
  客户端 -> 服务端:
    {"type":"new_chat"}                      新建对话
    {"type":"switch","sid":"..."}            切换会话
    {"type":"chat","sid":"...","content":""} 发送消息
    {"type":"stop","sid":"..."}              停止当前生成
    {"type":"delete","sid":"..."}            删除会话
    {"type":"ping"}                          保活
  服务端 -> 客户端:
    {"type":"ready","model","tools","version"}
    {"type":"session","sid","sessions":[...]}     当前会话已切换
    {"type":"sessions","list":[...]}              会话列表更新
    {"type":"history","sid","messages":[...]}     历史消息(user/assistant 文本)
    {"type":"user_message","sid","content"}       用户消息回显(多标签页同步)
    {"type":"token","sid","content"}              流式文本
    {"type":"tool_call","sid","id","name","arguments"}
    {"type":"tool_result","sid","id","name","content"}
    {"type":"done","sid","content","stopped"}     本轮结束
    {"type":"error","sid","message"}
    {"type":"pong"}
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Mapping
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

import agent_core as core
from webui_page import render_page

log = logging.getLogger("ai-agent")

settings_manager = core.SettingsManager()
session_store = core.SessionStore()


# --------------------------------------------------------------------------- #
# MCP 桥接: 全进程复用一个 stdio 连接，避免每个网页标签页都拉起一个 server.py
# --------------------------------------------------------------------------- #

class McpBridge:
    def __init__(self) -> None:
        self.session: ClientSession | None = None
        self.tools: list[dict[str, Any]] = []
        self.names: list[str] = []
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()

    async def ensure(self) -> None:
        async with self._lock:
            if self.session is not None:
                return
            stack = AsyncExitStack()
            try:
                read, write = await stack.enter_async_context(
                    stdio_client(core.mcp_server_params())
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                raw = await session.list_tools()
                items = getattr(raw, "tools", raw) or []
                self.tools = core.to_openai_tools(items)
                self.names = core.tool_names(items)
                self.session = session
                self._stack = stack
                log.info("MCP 已连接，可用工具 %d 个: %s", len(self.names), ", ".join(self.names))
            except BaseException:
                await stack.aclose()
                raise

    async def reset(self) -> None:
        """断开并结束 server.py 进程；下次 ensure() 时自动重连。"""
        async with self._lock:
            stack, self._stack = self._stack, None
            self.session = None
            self.tools = []
            self.names = []
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 - 关闭时的异常不影响主流程
                log.debug("关闭 MCP 连接时出错", exc_info=True)

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        await self.ensure()
        session = self.session
        if session is None:
            raise RuntimeError("MCP 未连接")
        try:
            result = await session.call_tool(name, arguments=arguments)
        except Exception as exc:  # noqa: BLE001 - 连接可能已失效，重置后由下一轮重连
            log.warning("工具 %s 调用失败: %s", name, exc)
            await self.reset()
            raise
        parts: list[str] = []
        for item in getattr(result, "content", None) or []:
            text = getattr(item, "text", None)
            parts.append(str(text) if text is not None else str(item))
        body = "\n".join(parts)
        if getattr(result, "isError", False):
            return "工具返回错误: " + (body or "(无错误详情)")
        return body or "(工具未返回内容)"

    async def close(self) -> None:
        await self.reset()


bridge = McpBridge()


# --------------------------------------------------------------------------- #
# 连接管理
# --------------------------------------------------------------------------- #

class Hub:
    def __init__(self) -> None:
        self.clients: set["ChatClient"] = set()

    def add(self, client: "ChatClient") -> None:
        self.clients.add(client)

    def remove(self, client: "ChatClient") -> None:
        self.clients.discard(client)

    async def broadcast(self, payload: Mapping[str, Any]) -> None:
        for client in list(self.clients):
            await client.send(payload)

    async def send_to_session(self, sid: str, payload: Mapping[str, Any]) -> None:
        for client in list(self.clients):
            if client.sid == sid:
                await client.send(payload)


class ChatClient:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.sid: str | None = None
        self.running_sid: str | None = None

    async def send(self, payload: Mapping[str, Any]) -> None:
        try:
            await self.websocket.send_json(dict(payload))
        except Exception:  # noqa: BLE001 - 对端已断开时忽略
            pass


hub = Hub()


# --------------------------------------------------------------------------- #
# 会话运行时
# --------------------------------------------------------------------------- #

class ChatRuntime:
    def __init__(self, store: core.SessionStore, mcp: McpBridge,
                 settings: core.SettingsManager, hub_: Hub) -> None:
        self.store = store
        self.bridge = mcp
        self.settings = settings
        self.hub = hub_
        self.model_messages: dict[str, list[dict[str, Any]]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.phase: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ---- 会话 ----

    def initial_session(self) -> dict[str, Any]:
        session = self.store.latest()
        return session or self.store.create()

    def fresh_session(self) -> dict[str, Any]:
        """新对话；如果最近一个会话还是空的就复用，避免每次启动堆积空会话。"""
        latest = self.store.latest()
        if latest and not latest.get("messages"):
            return latest
        session = self.store.create()
        self.store.prune(keep=200)
        return session

    def model_history(self, session: Mapping[str, Any]) -> list[dict[str, Any]]:
        sid = str(session["sid"])
        prompt = core.build_system_prompt(self.bridge.names)
        cached = self.model_messages.get(sid)
        if cached is None:
            # 只缓存有限个会话的完整上下文(含工具输出)，避免长时间运行后内存无限增长
            if len(self.model_messages) > 12:
                for stale in [key for key in self.model_messages if key not in self.tasks]:
                    self.model_messages.pop(stale, None)
                    if len(self.model_messages) <= 12:
                        break
            cached = [{"role": "system", "content": prompt}]
            for message in session.get("messages") or []:
                if message.get("role") in ("user", "assistant") and message.get("content"):
                    cached.append({"role": message["role"], "content": str(message["content"])})
            self.model_messages[sid] = cached
        else:
            cached[0] = {"role": "system", "content": prompt}
        return cached

    async def open_session(self, client: ChatClient, sid: str | None, *, create_new: bool = False) -> None:
        if create_new:
            session = self.fresh_session()
        elif sid:
            session = self.store.load(sid)
            if session is None:
                await client.send({"type": "error", "message": "会话不存在或已被删除，新建一个对话继续吧。"})
                return
        else:
            session = self.initial_session()

        client.sid = str(session["sid"])
        client.running_sid = None
        await client.send({
            "type": "session",
            "sid": client.sid,
            "sessions": self.store.list(),
        })
        await client.send({
            "type": "history",
            "sid": client.sid,
            "messages": core.display_messages([
                {"role": message.get("role"), "content": message.get("content")}
                for message in session.get("messages") or []
            ]),
        })

    async def delete_session(self, sid: str) -> bool:
        if not sid:
            return False
        await self.stop(sid)
        removed = self.store.delete(sid)
        self.model_messages.pop(sid, None)
        self.tasks.pop(sid, None)
        self.phase.pop(sid, None)

        # 所有正在查看被删会话的客户端，换到一个新会话
        for client in list(self.hub.clients):
            if client.sid == sid:
                await self.open_session(client, None, create_new=True)
        await self.hub.broadcast({"type": "sessions", "list": self.store.list()})
        return removed

    # ---- 生成 ----

    async def start_turn(self, client: ChatClient, sid: str, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        settings = self.settings.current()
        if not settings.api_key:
            await client.send({
                "type": "error",
                "sid": sid,
                "message": "尚未配置 API Key。请点右上角 ⚙ 填写，或设置环境变量 OPENAI_API_KEY 后重启。",
            })
            return
        if sid in self.tasks:
            await client.send({"type": "error", "sid": sid,
                               "message": "该会话正在回复中，请先停止或等待完成。"})
            return
        session = self.store.load(sid)
        if session is None:
            await client.send({"type": "error", "sid": sid, "message": "会话不存在，请新建对话。"})
            return

        if len(text) > 32000:
            text = text[:32000]
            await client.send({"type": "error", "sid": sid,
                               "message": "消息过长，已截断到 32000 字符。"})

        if not session.get("title"):
            session["title"] = core.make_title(text)

        # 先基于"本轮之前"的历史构造模型消息，再把用户消息写入会话与上下文，
        # 避免新会话首次对话时用户消息被重复添加两次。
        messages = self.model_history(session)
        session["messages"].append({"role": "user", "content": text})
        session["updated_at"] = core.now_iso()
        self.store.save(session)
        await self.hub.broadcast({"type": "sessions", "list": self.store.list()})

        messages.append({"role": "user", "content": text})
        client.running_sid = sid
        # 广播用户消息: 同一会话的其他标签页/窗口也能同步看到这条提问
        await self.hub.send_to_session(sid, {"type": "user_message", "sid": sid, "content": text})
        task = asyncio.create_task(self._run_turn(client, sid, session, messages), name=f"turn-{sid}")
        self.tasks[sid] = task

    async def _run_turn(self, client: ChatClient, sid: str, session: dict[str, Any],
                        messages: list[dict[str, Any]]) -> None:
        settings = self.settings.current()
        final_text = ""
        streamed: list[str] = []
        runner: core.AgentRunner | None = None
        try:
            api = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url,
                              timeout=180.0, max_retries=0)
            runner = core.AgentRunner(api, settings.model, self.bridge.tools, self.bridge.call)
            async for event in runner.run(messages):
                kind = event.get("type")
                if kind == "token":
                    self.phase[sid] = "model"
                    piece = str(event.get("content") or "")
                    streamed.append(piece)
                    await self.hub.send_to_session(sid, {
                        "type": "token", "sid": sid, "content": piece,
                    })
                elif kind == "tool_call":
                    self.phase[sid] = "tool"
                    await self.hub.send_to_session(sid, {
                        "type": "tool_call", "sid": sid, "id": event.get("id", ""),
                        "name": event.get("name", ""), "arguments": event.get("arguments", ""),
                    })
                elif kind == "tool_result":
                    self.phase[sid] = "model"
                    await self.hub.send_to_session(sid, {
                        "type": "tool_result", "sid": sid, "id": event.get("id", ""),
                        "name": event.get("name", ""), "content": event.get("content", ""),
                    })
                elif kind == "done":
                    final_text = str(event.get("content") or "")
                    await self.hub.send_to_session(sid, {
                        "type": "done", "sid": sid, "content": final_text,
                        "stopped": bool(event.get("stopped")), "truncated": bool(event.get("truncated")),
                    })
                elif kind == "error":
                    await self.hub.send_to_session(sid, {
                        "type": "error", "sid": sid, "message": str(event.get("message") or "未知错误"),
                    })
        except asyncio.CancelledError:
            final_text = (runner.final_text if runner else "") or "\n\n".join(streamed)
            await self.hub.send_to_session(sid, {
                "type": "done", "sid": sid, "content": final_text, "stopped": True,
            })
        except Exception as exc:  # noqa: BLE001 - 兜底，避免任务静默失败
            log.exception("会话 %s 处理异常", sid)
            final_text = (runner.final_text if runner else "") or "\n\n".join(streamed)
            await self.hub.send_to_session(sid, {
                "type": "error", "sid": sid, "message": f"会话异常: {exc}",
            })
        finally:
            self.tasks.pop(sid, None)
            self.phase.pop(sid, None)
            if final_text and self.store.exists(sid):
                stored = self.store.load(sid) or session
                last = (stored.get("messages") or [])[-1] if stored.get("messages") else {}
                if not (last.get("role") == "assistant" and last.get("content") == final_text):
                    stored.setdefault("messages", []).append(
                        {"role": "assistant", "content": final_text}
                    )
                stored["updated_at"] = core.now_iso()
                self.store.save(stored)
            if client.running_sid == sid:
                client.running_sid = None
            await self.hub.broadcast({"type": "sessions", "list": self.store.list()})

    async def stop(self, sid: str) -> bool:
        task = self.tasks.get(sid)
        if task is None:
            return False
        task.cancel()
        # 工具执行中停止: 结束 MCP 进程(连同其子进程)，让长命令/死循环立即中断
        if self.phase.get(sid) == "tool":
            await self.bridge.reset()
        await asyncio.wait({task}, timeout=5)
        return True

    async def stop_client_turn(self, client: ChatClient) -> None:
        if client.running_sid:
            await self.stop(client.running_sid)


runtime = ChatRuntime(session_store, bridge, settings_manager, hub)


# --------------------------------------------------------------------------- #
# HTTP / WebSocket 应用
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await bridge.ensure()
    except Exception as exc:  # noqa: BLE001 - 工具不可用不应阻止界面启动
        log.warning("MCP 初始化失败(稍后重试): %s", exc)
    yield
    await bridge.close()


app = FastAPI(title="AI-Agent Web UI", version=core.APP_VERSION, lifespan=lifespan)


def _is_local_origin(origin: str | None) -> bool:
    """只接受来自本机页面的请求，防止任意网站通过 127.0.0.1 驱动本地 Agent。

    桌面版(ClientWebSocket) 通常不带 Origin头，因此"缺少 Origin"是允许的。
    """
    if not origin:
        return True
    try:
        host = (urlparse(origin).hostname or "").lower()
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if not _is_local_origin(request.headers.get("origin")):
        return JSONResponse({"detail": "forbidden origin"}, status_code=403)
    response = await call_next(request)
    if request.url.path in ("/", "/api/settings", "/api/sessions"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", response_class=HTMLResponse)
async def index():
    settings = settings_manager.current()
    page = render_page(settings.public_dict(), len(bridge.tools))
    return HTMLResponse(page)


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/healthz")
async def healthz():
    settings = settings_manager.current()
    return {
        "ok": True,
        "app": core.APP_NAME,
        "version": core.APP_VERSION,
        "model": settings.model,
        "configured": settings.configured,
        "tools": len(bridge.tools),
        "sessions": len(session_store.list()),
    }


@app.get("/api/settings")
async def get_settings():
    payload = settings_manager.current().public_dict()
    payload.update({"tools": len(bridge.tools), "version": core.APP_VERSION})
    return payload


@app.post("/api/settings")
async def post_settings(payload: dict):
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "请求格式错误"}, status_code=400)
    before = settings_manager.current().port
    try:
        settings = settings_manager.update(payload)
    except Exception as exc:  # noqa: BLE001
        log.exception("保存设置失败")
        return JSONResponse({"ok": False, "error": f"保存失败: {exc}"}, status_code=500)
    result = {"ok": True, **settings.public_dict(), "restart_required": settings.port != before}
    log.info("设置已更新: model=%s base_url=%s key=%s", settings.model, settings.base_url,
             settings.api_key_source)
    return result


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": session_store.list()}


async def _handle_client_message(client: ChatClient, data: Mapping[str, Any]) -> None:
    kind = data.get("type")
    sid = str(data.get("sid") or client.sid or "")

    if kind == "ping":
        await client.send({"type": "pong"})
    elif kind == "new_chat":
        await runtime.open_session(client, None, create_new=True)
    elif kind == "switch":
        await runtime.open_session(client, sid, create_new=False)
    elif kind == "chat":
        if not sid:
            await runtime.open_session(client, None, create_new=True)
            sid = client.sid or ""
            if not sid:
                return
        await runtime.start_turn(client, sid, str(data.get("content") or ""))
    elif kind == "stop":
        target = sid or client.running_sid or ""
        if target:
            stopped = await runtime.stop(target)
            if not stopped:
                await client.send({"type": "done", "sid": target, "stopped": True, "content": ""})
    elif kind == "delete":
        if sid:
            await runtime.delete_session(sid)
    else:
        await client.send({"type": "error", "message": f"未知消息类型: {kind}"})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    if not _is_local_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    client = ChatClient(websocket)
    hub.add(client)
    try:
        await bridge.ensure()
        settings = settings_manager.current()
        await client.send({
            "type": "ready",
            "model": settings.model,
            "tools": len(bridge.tools),
            "version": core.APP_VERSION,
            "configured": settings.configured,
        })
        await runtime.open_session(client, None, create_new=False)

        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                data = json.loads(raw)
            except ValueError:
                await client.send({"type": "error", "message": "消息不是合法 JSON"})
                continue
            if not isinstance(data, dict):
                continue
            await _handle_client_message(client, data)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("WebSocket 会话异常")
        await client.send({"type": "error", "message": "会话异常，请刷新页面重试。"})
    finally:
        hub.remove(client)
        try:
            await runtime.stop_client_turn(client)
        except Exception:  # noqa: BLE001
            log.debug("清理会话任务失败", exc_info=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = settings_manager.current()
    requested = settings.port
    port = core.pick_free_port(requested)
    if port != requested:
        print(f"[webui] 端口 {requested} 不可用, 已自动改用端口 {port}")
    print(f"[webui] 请打开: http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
