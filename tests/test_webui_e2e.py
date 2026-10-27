"""端到端测试: 启动真实 webui.py 子进程 + 模拟 OpenAI 接口 + WebSocket 客户端。

覆盖: 流式回复、MCP 工具调用、会话持久化、切换/新建会话、设置接口。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import websockets

import agent_core as core

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "win32", reason="项目面向 Windows"),
]


# --------------------------------------------------------------------------- #
# 模拟 OpenAI Chat Completions (SSE)
# --------------------------------------------------------------------------- #

def _text_chunks(text: str) -> list[dict]:
    return [{
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "mock",
        "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
    } for piece in text]


def _stop_chunk() -> dict:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "mock",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }


def _tool_call_chunks(name: str, arguments: str) -> list[dict]:
    base = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "mock",
    }
    first = dict(base)
    first["choices"] = [{
        "index": 0,
        "delta": {
            "role": "assistant",
            "tool_calls": [{
                "index": 0,
                "id": "call_mock_1",
                "type": "function",
                "function": {"name": name, "arguments": ""},
            }],
        },
        "finish_reason": None,
    }]
    second = dict(base)
    second["choices"] = [{
        "index": 0,
        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments}}]},
        "finish_reason": None,
    }]
    return [first, second]


class MockOpenAIHandler(BaseHTTPRequestHandler):
    mode = "text"           # text | tool
    reply_text = "你好"
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            payload = {}
        MockOpenAIHandler.requests.append(payload)

        messages = payload.get("messages") or []
        last_role = messages[-1].get("role") if messages else None

        if MockOpenAIHandler.mode == "tool" and last_role != "tool":
            chunks = _tool_call_chunks("get_datetime", "{}")
        else:
            chunks = _text_chunks(MockOpenAIHandler.reply_text)

        data = b""
        for chunk in chunks + [_stop_chunk()]:
            data += b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n"
        data += b"data: [DONE]\n\n"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def log_message(self, *args):  # 静默
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_healthy(port: int, process: subprocess.Popen, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/healthz"
    while time.time() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"webui 提前退出，退出码 {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001 - 服务尚未就绪
            pass
        time.sleep(0.25)
    raise AssertionError("webui 未在超时时间内就绪")


async def _recv_until(ws, wanted: str, timeout: float = 30.0) -> tuple[dict, list[dict]]:
    collected: list[dict] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        collected.append(message)
        if message.get("type") == wanted:
            return message, collected
    raise AssertionError(f"等待 {wanted} 超时，已收到: {[m.get('type') for m in collected]}")


async def _scenario(port: int) -> None:
    uri = f"ws://127.0.0.1:{port}/ws"
    async with websockets.connect(uri, open_timeout=15) as ws:
        _, initial = await _recv_until(ws, "history")
        types = [m["type"] for m in initial]
        assert "ready" in types and "session" in types
        ready = next(m for m in initial if m["type"] == "ready")
        assert ready["tools"] >= 15
        session = next(m for m in initial if m["type"] == "session")
        first_sid = session["sid"]
        assert session["sessions"][0]["sid"] == first_sid

        # --- 纯文本一轮 ---
        await ws.send(json.dumps({"type": "chat", "sid": first_sid, "content": "打个招呼"}))
        done, events = await _recv_until(ws, "done")
        assert done.get("stopped") is False
        assert "user_message" in [m["type"] for m in events]
        text = "".join(m.get("content", "") for m in events if m["type"] == "token")
        assert text == "你好"

        # --- 工具调用一轮 ---
        MockOpenAIHandler.mode = "tool"
        MockOpenAIHandler.reply_text = "现在时间已取回"
        await ws.send(json.dumps({"type": "chat", "sid": first_sid, "content": "现在几点"}))
        done, events = await _recv_until(ws, "done")
        tool_calls = [m for m in events if m["type"] == "tool_call"]
        tool_results = [m for m in events if m["type"] == "tool_result"]
        assert tool_calls and tool_calls[0]["name"] == "get_datetime"
        assert tool_results and "当前时间" in tool_results[0]["content"]
        text = "".join(m.get("content", "") for m in events if m["type"] == "token")
        assert text == "现在时间已取回"

        # --- 新建会话 ---
        await ws.send(json.dumps({"type": "new_chat"}))
        new_session, _ = await _recv_until(ws, "history")
        assert new_session["messages"] == []
        assert new_session["sid"] != first_sid

        # --- 切回旧会话，历史应保留 ---
        await ws.send(json.dumps({"type": "switch", "sid": first_sid}))
        history, _ = await _recv_until(ws, "history")
        contents = [m["content"] for m in history["messages"]]
        assert "打个招呼" in contents
        assert "你好" in contents
        assert "现在几点" in contents
        assert "现在时间已取回" in contents


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_webui_end_to_end(tmp_path):
    mock = ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
    mock_port = mock.server_address[1]
    thread = threading.Thread(target=mock.serve_forever, daemon=True)
    thread.start()

    port = _free_port()
    settings_path = tmp_path / "settings.json"
    data_dir = tmp_path / "data"
    log_path = tmp_path / "webui.log"

    env = os.environ.copy()
    env.update({
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_BASE_URL": f"http://127.0.0.1:{mock_port}/v1",
        "OPENAI_MODEL": "mock-model",
        "WEBUI_PORT": str(port),
        "AI_AGENT_SETTINGS": str(settings_path),
        "AI_AGENT_DATA_DIR": str(data_dir),
        "PYTHONIOENCODING": "utf-8",
    })

    process = subprocess.Popen(
        [sys.executable, str(core.ROOT / "webui.py")],
        cwd=str(core.ROOT),
        env=env,
        stdout=open(log_path, "wb"),
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_healthy(port, process)

        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read().decode("utf-8")
        assert "AI Agent" in page
        assert "__BG__" not in page

        health = _http_json(f"http://127.0.0.1:{port}/healthz")
        assert health["ok"] is True and health["configured"] is True
        assert health["tools"] >= 15

        api_settings = _http_json(f"http://127.0.0.1:{port}/api/settings")
        assert api_settings["model"] == "mock-model"
        assert api_settings["has_api_key"] is True
        assert "sk-test" not in json.dumps(api_settings)

        asyncio.run(_scenario(port))

        # 会话已落盘，并且助手回复保存在里面
        session_files = list((data_dir / "sessions").glob("*.json"))
        assert len(session_files) >= 2
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in session_files]
        assistant_texts = [m["content"] for payload in payloads
                           for m in payload.get("messages", []) if m["role"] == "assistant"]
        assert "你好" in assistant_texts
        assert "现在时间已取回" in assistant_texts

        sessions_api = _http_json(f"http://127.0.0.1:{port}/api/sessions")["sessions"]
        assert len(sessions_api) >= 2

        # 模型确实按 OpenAI 兼容协议收到了带工具定义的请求
        assert any(request.get("tools") for request in MockOpenAIHandler.requests)
        # 首次对话的用户消息只应发送一次(防止"新会话首轮重复添加用户消息"回归)
        first_request = MockOpenAIHandler.requests[0]
        user_messages = [m for m in first_request.get("messages", []) if m.get("role") == "user"]
        assert len(user_messages) == 1
        assert user_messages[0]["content"] == "打个招呼"
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, check=False)
        mock.shutdown()
        mock.server_close()
        MockOpenAIHandler.mode = "text"
        MockOpenAIHandler.reply_text = "你好"
        MockOpenAIHandler.requests = []
        if process.poll() is None:
            process.kill()
