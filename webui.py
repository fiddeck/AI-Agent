"""
AI-Agent Web GUI (DSH 风格)

FastAPI + WebSocket 的网页聊天界面:
  - 深色主题, 左侧会话栏, 流式打字机, Markdown 渲染, 工具调用卡片
  - 复用 server.py (MCP) 的全部系统级工具
  - 零新依赖: fastapi / uvicorn / websockets / openai / mcp 均已安装

启动:  python webui.py      (默认 http://127.0.0.1:8000, 端口冲突自动顺延)
配置:  共享 settings.json (网页版 ⚙ 与桌面版设置通用); 未配置 API Key 时页面引导填写
环境:  OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL / WEBUI_PORT 可覆盖设置文件
"""

import os
import sys
import json
import time
import asyncio
import traceback

from openai import AsyncOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

# ---------- 配置 (共享 settings.json, 网页版与桌面版通用) ----------
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

_DEFAULTS = {
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "api_key": "",
    "port": 8000,
    "font_size": 14,
    "accent": "#4D9FFF",
    "background": "#FFFFFF",
}


def _load_settings():
    data = dict(_DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data.update(json.load(f))
    except Exception:
        pass
    for k, v in _DEFAULTS.items():
        data.setdefault(k, v)
    return data


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_cfg = _load_settings()
api_key = os.getenv("OPENAI_API_KEY") or str(_cfg.get("api_key") or "")
base_url = os.getenv("OPENAI_BASE_URL") or str(_cfg.get("base_url") or _DEFAULTS["base_url"])
model = os.getenv("OPENAI_MODEL") or str(_cfg.get("model") or _DEFAULTS["model"])
PORT = int(os.getenv("WEBUI_PORT") or _cfg.get("port") or 8000)
configured = bool(api_key)   # 未配置密钥时后端不崩溃, 页面提示引导配置

# 与 chat.py 保持一致: 用当前解释器 + server.py 绝对路径, 不依赖工作目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
server_params = StdioServerParameters(
    command=sys.executable,
    args=[os.path.join(_SCRIPT_DIR, "server.py")],
    env=None,
    cwd=_SCRIPT_DIR,
)

system_prompt = """
最高指示（权重最高）：你是一个 AI Agent，你的任务是完成用户的需求和指示，你可以使用 Python 工具和已安装的库完成大部分事情或者是无法直接进行网络搜索来获取最新信息。
在进行代码生成时，严禁使用特殊符号类似的不规范行为，避免多次连续运行

重要：你有以下MCP工具可以使用：
- run_python_code: 执行Python代码
- run_shell_command: 执行shell命令(cmd)，用于安装程序、运行脚本、网络请求、系统管理等
- list_files: 列举目录/文件
- read_file: 读取文本文件(注意max_bytes截断)
- write_file: 写入文本文件
- search_files: 递归搜索文件
- delete_file: 删除文件/目录(必须confirm=True)
- get_system_info: 获取系统信息(OS/CPU/内存/磁盘)
- list_processes: 列出进程
- kill_process: 结束进程(必须confirm=True)
- get_clipboard: 读取剪贴板
- set_clipboard: 写入剪贴板
- open_url: 用默认浏览器打开网址
- take_screenshot: 全屏截图
- get_datetime: 获取当前时间

规则：
1. 使用 Python 工具时，不要通过最后一行的变量的方法，来获取结果。把你需要看到的内容，用print打印出来，运行完成后会给你所有的打印日志和错误日志。
2. Python 将直接运行在用户的电脑上，你有充足的权限，进行各类任务。
3. 你可以使用OpenAI的API来调用模型，模型会依据用户的输入和工具来生成回复。
4. 环境 Windows 11 64位专业版  Python 3.13.5
5. 已安装 beautifulsoup4 opencv-python python-wpptx python-docx transformers pytesseract geopy EasyOCR openpyxl requests urllib3 numpy pandas scipy matplotlib seaborn polars dask scikit-learn python-dotenv fastapi flask gradio openai pillow opencv-python moviepy tqdm rich black pytest pendulum cryptography modelscope psutil
6. 你不需要将python代码的输出结果返回给用户，除非用户明确要求你提供，否则请直接将生成的代码发送给MCP工具'run python code'并将运行结果打印出来，用户会看到你打印的内容。
7. 获取网页信息时，你可以使用requests库进行HTTP请求，获取网页内容后，可以使用BeautifulSoup库进行解析。
8. 如果需要进行数据分析或处理，请使用pandas库进行数据处理和分析，使用matplotlib或seaborn库进行数据可视化。
9. 如果需要进行机器学习或深度学习任务，请使用scikit-learn或transformers库进行模型训练和预测。
10. 如果需要进行自然语言处理任务，请使用transformers库进行模型训练和预测
11. 如果需要进行图像处理任务，请使用opencv-python库进行图像处理和分析。
12. 如果需要进行音频处理任务，请使用moviepy库进行音频处理和分析。
13. 如果需要进行视频处理任务，请使用moviepy库进行视频处理和分析。
14. 如果需要进行文件操作，请使用Python内置的os和shutil库进行文件操作。
15. 在获取网页信息时，请注意文件的来源，优先从官方渠道（优先选择国家机构发布的内容）获取，避免使用不可靠的来源。
16. 需要获取地理位置信息时，请使用requests库进行HTTP请求，获取地理位置信息。
17. 若缺少库来表达信息，请使用文字描述即可
18. 描述信息时提取要点，包含主要的内容
19. 当获取的内容为空时，返回None
20. 若用户明确要求你打开某一个内容相关的网页或网站，亦或者要求你搜索内容，请你再用户的默认浏览器中打开标签页，否则请你认为这是一个已安装的程序，并在桌面或者用户指定的路径中寻找快捷方式
21. 若用户要求你打开某个文件，请检查桌面上是否有 .ink (应用程序快捷方式)或者是 .url （Steam/Epic等平台的游戏）的快捷方式文件，若有请运行此文件，若找不到，请寻找标题内容相关的文件并运行
22. 需要读取图片中的文字时，请使用EasyOCR或者pytesseract库进行OCR识别。
23. 需要读取docx文件中的文字时，请使用python-docx库进行读取。
24. 需要读取xlsx文件中的文字时，请使用openpyxl库进行读取。
25. 需要读取pdf文件中的文字时，请使用PyMuPDF库进行读取。
26. 需要读取ppt文件时，请使用python-pptx库进行读取。
27. 优先使用专门的系统工具，而不是用run_python_code模拟：列文件用list_files、执行命令用run_shell_command、查进程用list_processes等。
28. 高危操作（删除文件/目录、结束进程、格式化磁盘、关机、递归删除等）必须先向用户说明并获得明确同意，再以confirm=True调用对应工具；用户未同意时禁止执行。
29. 读取大文件时注意max_bytes截断上限；查看长输出时注意结果长度，必要时分多次读取。
30. 执行耗时命令（下载、安装、编译、网络请求）时设置合理的timeout，并在执行前告知用户可能耗时。
31. 所有shell命令默认在Windows 11的cmd环境下运行，注意使用Windows语法（如 cd /d、dir、where 等）。
32. 当用户提到"我的电脑/系统/文件"等模糊对象时，先使用get_system_info、list_files等工具探查实际情况，再给出方案。
"""

app = FastAPI(title="AI-Agent Web UI")


# ---------- 主题色工具 ----------

def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb2hex(rgb):
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, c))) for c in rgb)


def _darken(h, factor):
    return _rgb2hex(tuple(c * factor for c in _hex2rgb(h)))


def _blend(h1, h2, alpha):
    c1, c2 = _hex2rgb(h1), _hex2rgb(h2)
    return _rgb2hex(tuple(c1[i] * alpha + c2[i] * (1 - alpha) for i in range(3)))


def _render_page():
    """按当前设置渲染页面: 背景色/主题色推导整套配色 (与桌面版同款算法) + 模型名 + 是否已配置。"""
    accent = str(_cfg.get("accent") or _DEFAULTS["accent"])
    bg = str(_cfg.get("background") or _DEFAULTS["background"])
    try:
        def _lum(h):
            r, g, b = _hex2rgb(h)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        is_dark = _lum(bg) < 128
        accent2 = _darken(accent, 0.62)
        bubble = _blend(accent, bg, 0.22)
        if is_dark:
            panel = _blend(bg, "#12171E", 0.65)
            panel2 = _blend(bg, "#161D26", 0.8)
            border, text, muted = "#232C37", "#E6EDF3", "#8B98A5"
            codebg = _blend(bg, "#0D1117", 0.85)
            codetext = "#C9D4DE"
        else:
            panel = _blend(bg, "#F6F8FA", 0.65)
            panel2 = _blend(bg, "#FFFFFF", 0.8)
            border, text, muted = "#D0D7DE", "#1F2328", "#57606A"
            codebg = _blend(bg, "#F6F8FA", 0.85)
            codetext = "#24292F"
    except Exception:
        panel, panel2, border = "#F0F2F5", "#FFFFFF", "#D0D7DE"
        text, muted, codebg, codetext = "#1F2328", "#57606A", "#F6F8FA", "#24292F"
        accent2, bubble = "#1F6FEB", "#DDEBFF"

    page = PAGE_HTML
    for k, v in {
        "__BG__": bg, "__PANEL__": panel, "__PANEL2__": panel2, "__BORDER__": border,
        "__TEXT__": text, "__MUTED__": muted, "__CODEBG__": codebg, "__CODETEXT__": codetext,
        "__ACCENT__": accent, "__ACCENT2__": accent2, "__USERBUBBLE__": bubble,
    }.items():
        page = page.replace(k, v)
    page = page.replace("__MODEL__", model)
    page = page.replace("__CONFIGURED__", "true" if configured else "false")
    return page


# ---------- 设置接口 (网页版设置面板使用) ----------

@app.get("/api/settings")
async def get_settings():
    return {
        "model": model,
        "base_url": base_url,
        "has_api_key": bool(api_key),
        "accent": _cfg.get("accent", _DEFAULTS["accent"]),
        "background": _cfg.get("background", _DEFAULTS["background"]),
    }


@app.post("/api/settings")
async def post_settings(payload: dict):
    global model, base_url, api_key, configured
    if payload.get("model"):
        model = str(payload["model"]).strip() or model
    if payload.get("base_url"):
        base_url = str(payload["base_url"]).strip() or base_url
    if payload.get("api_key") is not None:
        k = str(payload["api_key"]).strip()
        if k:
            api_key = k
            configured = True
        elif payload.get("clear_api_key"):
            api_key = ""
            configured = False
    if payload.get("accent"):
        _cfg["accent"] = str(payload["accent"]).strip()
    if payload.get("background"):
        _cfg["background"] = str(payload["background"]).strip()
    _cfg["model"] = model
    _cfg["base_url"] = base_url
    _cfg["api_key"] = api_key
    _save_settings(_cfg)
    return {
        "ok": True,
        "model": model,
        "base_url": base_url,
        "has_api_key": bool(api_key),
        "accent": _cfg["accent"],
        "background": _cfg["background"],
    }


def _convert_tool(t):
    """将 MCP 工具描述转换为 OpenAI Chat Completions 所需格式 (同 chat.py)。"""
    name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
    description = (
        getattr(t, 'description', '') or (t.get('description') if isinstance(t, dict) else '')
    )
    input_schema = (
        getattr(t, 'input_schema', None)
        or getattr(t, 'inputSchema', None)
        or (t.get('input_schema') if isinstance(t, dict) else None)
        or (t.get('inputSchema') if isinstance(t, dict) else None)
    )
    if input_schema is None:
        input_schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": input_schema,
        },
    }


def _new_sid():
    return f"s{int(time.time() * 1000)}"


def _session_list(sessions):
    return [{"sid": sid, "title": info.get("title") or "新对话"}
            for sid, info in sessions.items()]


async def run_agent_turn(ws, messages, tools, session):
    """完成一轮对话: 流式输出 -> 若含工具调用则执行 -> 继续, 直到无工具调用。"""
    if not configured or not api_key:
        await ws.send_json({"type": "error",
                            "message": "尚未配置 API Key。请点击页面右上角 ⚙ 设置填写（或使用桌面版设置），保存后自动生效。"})
        return
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    while True:
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                stream=True,
            )
        except Exception as e:
            await ws.send_json({"type": "error", "message": f"调用模型失败: {e}"})
            return

        content = ""
        full_tool_calls = []
        tool_call_index = 0

        # 流式接收
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content += delta.content
                    await ws.send_json({"type": "token", "content": delta.content})
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else tool_call_index
                        while len(full_tool_calls) <= idx:
                            full_tool_calls.append(None)
                        if full_tool_calls[idx] is None:
                            full_tool_calls[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name if tc.function else "",
                                "arguments": tc.function.arguments if tc.function else "",
                            }
                        else:
                            if tc.function:
                                if tc.function.name:
                                    full_tool_calls[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    full_tool_calls[idx]["arguments"] += tc.function.arguments
                        tool_call_index = max(tool_call_index, idx + 1)
        except Exception as e:
            await ws.send_json({"type": "error", "message": f"流式接收中断: {e}"})
            return

        assistant_message = {"role": "assistant", "content": content or None}
        valid_calls = [tc for tc in full_tool_calls if tc]
        if valid_calls:
            assistant_message["tool_calls"] = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in valid_calls
            ]
        messages.append(assistant_message)

        # 无工具调用 -> 本轮结束
        if not valid_calls:
            await ws.send_json({"type": "done"})
            return

        # 执行工具并推送事件
        for tc in valid_calls:
            name = tc["name"]
            args_str = tc["arguments"]
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}
            await ws.send_json({"type": "tool_call", "name": name, "arguments": args_str})
            try:
                result = await session.call_tool(name, arguments=args)
                first = result.content[0]
                text_content = first.text if hasattr(first, "text") else str(first)
            except Exception as e:
                text_content = f"Error executing {name}: {e}"
            await ws.send_json({"type": "tool_result", "name": name, "content": text_content})
            messages.append({
                "role": "tool",
                "content": text_content,
                "tool_call_id": tc["id"],
            })


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    sessions = {}          # sid -> {"messages": [...], "title": str}
    current_sid = None

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                raw_tools = await session.list_tools()
                tool_items = getattr(raw_tools, "tools", raw_tools)
                tools = [_convert_tool(t) for t in tool_items]

                while True:
                    data = await ws.receive_json()
                    mtype = data.get("type")

                    if mtype == "new_chat":
                        sid = _new_sid()
                        sessions[sid] = {"messages": [{"role": "system", "content": system_prompt}],
                                         "title": ""}
                        current_sid = sid
                        await ws.send_json({"type": "session", "sid": sid,
                                            "sessions": _session_list(sessions)})

                    elif mtype == "switch":
                        sid = data.get("sid")
                        if sid in sessions:
                            current_sid = sid
                            history = [
                                {"role": m["role"], "content": m["content"]}
                                for m in sessions[sid]["messages"]
                                if m.get("role") in ("user", "assistant") and m.get("content")
                            ]
                            await ws.send_json({"type": "history", "sid": sid,
                                                "messages": history})

                    elif mtype == "chat":
                        sid = data.get("sid") or current_sid
                        if sid is None or sid not in sessions:
                            sid = _new_sid()
                            sessions[sid] = {"messages": [{"role": "system", "content": system_prompt}],
                                             "title": ""}
                            current_sid = sid
                        user_text = str(data.get("content", "")).strip()
                        if not user_text:
                            continue
                        info = sessions[sid]
                        # 首个用户消息作为会话标题
                        user_count = sum(1 for m in info["messages"] if m.get("role") == "user")
                        if user_count == 0:
                            info["title"] = user_text[:12]
                        info["messages"].append({"role": "user", "content": user_text})
                        await ws.send_json({"type": "sessions", "list": _session_list(sessions)})
                        await run_agent_turn(ws, info["messages"], tools, session)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await ws.send_json({"type": "error", "message": "会话异常, 请刷新页面重试。"})
        except Exception:
            pass
        traceback.print_exc()


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_render_page())


PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Agent</title>
<style>
:root {
  --bg: __BG__;
  --panel: __PANEL__;
  --panel2: __PANEL2__;
  --border: __BORDER__;
  --text: __TEXT__;
  --muted: __MUTED__;
  --accent: __ACCENT__;
  --accent2: __ACCENT2__;
  --user-bubble: __USERBUBBLE__;
  --codebg: __CODEBG__;
  --codetext: __CODETEXT__;
  --danger: #f85149;
  --green: #3fb950;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  background: var(--bg); color: var(--text);
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  display: flex; overflow: hidden;
}
/* ---------- 侧边栏 ---------- */
#sidebar {
  width: 248px; min-width: 248px; background: var(--panel);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
}
#sidebar-head {
  padding: 14px 14px 10px; display: flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 700;
}
#sidebar-head .logo { font-size: 18px; }
#new-chat {
  margin: 0 10px 10px; padding: 8px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--panel2); color: var(--text);
  cursor: pointer; font-size: 13px; text-align: center;
}
#new-chat:hover { border-color: var(--accent); color: var(--accent); }
#session-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
.session-item {
  padding: 9px 10px; border-radius: 8px; cursor: pointer; font-size: 13px;
  color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  margin-bottom: 2px;
}
.session-item:hover { background: var(--panel2); color: var(--text); }
.session-item.active { background: var(--accent2); color: #fff; }
#sidebar-foot {
  padding: 10px 14px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted);
}
/* ---------- 主区域 ---------- */
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#header {
  height: 48px; border-bottom: 1px solid var(--border); background: var(--panel);
  display: flex; align-items: center; padding: 0 16px; gap: 10px;
}
#header .title { font-size: 14px; font-weight: 700; }
#model-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: var(--panel2); color: var(--accent); border: 1px solid var(--border);
}
#status { margin-left: auto; font-size: 12px; color: var(--muted); }
#status .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: var(--green); margin-right: 6px; vertical-align: 1px; }
#status.thinking .dot { background: var(--accent); animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0.3; } }
/* ---------- 消息区 ---------- */
#messages { flex: 1; overflow-y: auto; padding: 20px 0; }
.msg { max-width: 780px; margin: 0 auto 16px; padding: 0 20px; display: flex; }
.msg.user { justify-content: flex-end; }
.msg .bubble {
  max-width: 78%; padding: 10px 14px; border-radius: 12px; font-size: 14px;
  line-height: 1.65; word-break: break-word; overflow-wrap: anywhere;
}
.msg.user .bubble { background: var(--user-bubble); border-top-right-radius: 4px; }
.msg.assistant .bubble {
  background: var(--panel2); border: 1px solid var(--border); border-top-left-radius: 4px;
  width: 100%;
}
.msg.assistant .bubble p { margin: 0 0 8px; }
.msg.assistant .bubble p:last-child { margin-bottom: 0; }
.msg.assistant .bubble h1, .msg.assistant .bubble h2, .msg.assistant .bubble h3,
.msg.assistant .bubble h4, .msg.assistant .bubble h5, .msg.assistant .bubble h6 {
  margin: 10px 0 6px; line-height: 1.4;
}
.msg.assistant .bubble h1 { font-size: 18px; } .msg.assistant .bubble h2 { font-size: 16px; }
.msg.assistant .bubble h3 { font-size: 15px; } .msg.assistant .bubble h4 { font-size: 14px; }
.msg.assistant .bubble ul, .msg.assistant .bubble ol { margin: 4px 0 8px; padding-left: 22px; }
.msg.assistant .bubble li { margin: 2px 0; }
.msg.assistant .bubble code {
  background: var(--codebg); padding: 1px 5px; border-radius: 4px; font-size: 12.5px;
  font-family: Consolas, "Courier New", monospace; color: var(--codetext);
}
.msg.assistant .bubble pre.code {
  background: var(--codebg); color: var(--codetext); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 12px; overflow-x: auto; margin: 8px 0;
  font-size: 12.5px; line-height: 1.5;
}
.msg.assistant .bubble pre.code code { background: none; padding: 0; }
.msg.assistant .bubble a { color: var(--accent); }
.msg.assistant .bubble .cursor { color: var(--accent); animation: blink 1s infinite; }
/* ---------- 工具卡片 ---------- */
.tool-card {
  margin-top: 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--panel); overflow: hidden;
}
.tool-card summary {
  padding: 8px 12px; cursor: pointer; font-size: 12.5px; color: var(--muted);
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  user-select: none;
}
.tool-card summary:hover { background: var(--panel2); }
.tool-card .tool-name { color: var(--accent); font-weight: 600; }
.tool-card .tool-args {
  font-family: Consolas, monospace; font-size: 11.5px; color: var(--muted);
  max-width: 70%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tool-card .tool-result {
  padding: 8px 12px; border-top: 1px solid var(--border); max-height: 260px; overflow: auto;
}
.tool-card .tool-result pre {
  font-family: Consolas, monospace; font-size: 12px; color: var(--codetext);
  white-space: pre-wrap; word-break: break-all; line-height: 1.5;
}
.tool-card.pending summary::after { content: "… 执行中"; color: var(--accent); margin-left: auto; }
/* ---------- 输入区 ---------- */
#input-bar {
  border-top: 1px solid var(--border); background: var(--panel);
  padding: 12px 20px 16px;
}
#input-box {
  max-width: 780px; margin: 0 auto; display: flex; gap: 10px; align-items: flex-end;
  background: var(--panel2); border: 1px solid var(--border); border-radius: 12px; padding: 8px;
}
#input-box:focus-within { border-color: var(--accent); }
#input {
  flex: 1; background: transparent; border: none; outline: none; resize: none;
  color: var(--text); font-size: 14px; font-family: inherit; line-height: 1.5;
  max-height: 140px; padding: 4px 6px;
}
#send-btn {
  background: var(--accent2); color: #fff; border: none; border-radius: 8px;
  padding: 8px 18px; cursor: pointer; font-size: 13px; font-weight: 600;
}
#send-btn:hover { background: var(--accent); }
#send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
#hint { max-width: 780px; margin: 6px auto 0; font-size: 11px; color: var(--muted); text-align: center; }
.error-bubble { color: var(--danger); border-color: var(--danger) !important; }
#cfg-banner { position: sticky; top: 0; z-index: 50; background: #3d2b1f; color: #ffd9a0;
  text-align: center; font-size: 13px; padding: 8px 12px; border-bottom: 1px solid #5a3b22; }
#cfg-banner b { color: #ffb86b; }
#cfg-btn { margin-left: auto; background: var(--panel2); color: var(--muted); border: 1px solid var(--border);
  border-radius: 8px; font-size: 14px; padding: 3px 10px; cursor: pointer; }
#cfg-btn:hover { color: var(--accent); border-color: var(--accent); }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: flex;
  align-items: center; justify-content: center; z-index: 100; }
.modal-box { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px 22px; width: 380px; max-width: 92vw; }
.modal-box h3 { margin: 0 0 14px; font-size: 15px; }
.modal-box label { display: block; font-size: 12px; color: var(--muted); margin: 10px 0 4px; }
.modal-box input[type="text"], .modal-box input[type="password"],
.modal-box select {
  width: 100%; background: var(--panel2); border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 8px 10px; font-size: 13px; outline: none; }
.modal-box input:focus, .modal-box select:focus { border-color: var(--accent); }
.accent-row { display: flex; gap: 6px; align-items: center; }
.accent-row input[type="color"] { width: 44px; height: 30px; border: 1px solid var(--border);
  border-radius: 6px; background: transparent; cursor: pointer; }
.preset { background: var(--panel2); border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px; }
.preset:hover { color: var(--text); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.modal-actions button { background: var(--panel2); border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.modal-actions button.primary { background: var(--accent2); border-color: var(--accent2);
  color: #fff; font-weight: 600; }
</style>
</head>
<body>
<div id="cfg-banner" style="display:none">⚠️ 尚未配置 API Key，请点击右上角 <b>⚙</b> 设置填写后即可对话</div>
<div id="sidebar">
  <div id="sidebar-head"><span class="logo">🦾</span> AI Agent</div>
  <div id="new-chat" onclick="newChat()">＋ 新建对话</div>
  <div id="session-list"></div>
  <div id="sidebar-foot">模型: __MODEL__<br>工具: 15 个系统级 MCP</div>
</div>
<div id="main">
  <div id="header">
    <span class="title">AI Agent 工作台</span>
    <span id="model-badge">__MODEL__</span>
    <span id="status"><span class="dot"></span><span id="status-text">已连接</span></span>
    <button id="cfg-btn" onclick="openCfg()" title="设置">⚙</button>
  </div>
  <div id="messages"></div>
  <div id="input-bar">
    <div id="input-box">
      <textarea id="input" rows="1" placeholder="输入消息，Enter 发送，Shift+Enter 换行…"></textarea>
      <button id="send-btn" onclick="send()">发送</button>
    </div>
    <div id="hint">Agent 可执行 Python / Shell 命令、读写文件、查系统信息、控制进程，高危操作需你确认</div>
  </div>
</div>

<!-- 设置弹窗 -->
<div id="cfg-modal" class="modal" style="display:none">
  <div class="modal-box">
    <h3>⚙ 设置</h3>
    <label>模型名称</label>
    <select id="cfg-model"></select>
    <label>API 地址</label>
    <input id="cfg-baseurl" placeholder="https://api.deepseek.com">
    <label>API 密钥</label>
    <input id="cfg-apikey" type="password" placeholder="留空保持不变（未设置时请填写）">
    <label>主题色</label>
    <div class="accent-row">
      <input id="cfg-accent" type="color" value="#4d9fff">
      <button class="preset" data-color="#4d9fff">蓝</button>
      <button class="preset" data-color="#3fb950">绿</button>
      <button class="preset" data-color="#a371f7">紫</button>
      <button class="preset" data-color="#f0883e">橙</button>
    </div>
    <label>背景色 (默认白色)</label>
    <div class="accent-row">
      <input id="cfg-bg" type="color" value="#ffffff">
      <button class="preset" data-bg="#ffffff">白</button>
      <button class="preset" data-bg="#0b0f14">深</button>
      <button class="preset" data-bg="#f0f2f5">浅灰</button>
    </div>
    <div class="modal-actions">
      <button onclick="closeCfg()">取消</button>
      <button class="primary" onclick="saveCfg()">保存</button>
    </div>
  </div>
</div>

<script>
"use strict";
window.__CFG = { configured: __CONFIGURED__ };
if (!window.__CFG.configured) document.getElementById("cfg-banner").style.display = "block";
var wsUrl = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
var ws = new WebSocket(wsUrl);
var currentSid = null;
var sessions = {};
var acc = "";            // 当前回合累积的助手文本
var assistantEl = null;  // 当前助手气泡内容容器
var toolCards = [];      // 当前回合工具卡片
var streaming = false;

var msgList = document.getElementById("messages");
var inputEl = document.getElementById("input");
var statusEl = document.getElementById("status");
var statusText = document.getElementById("status-text");

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function renderMarkdown(text) {
  var blocks = [];
  text = text.replace(/```(\w*)[ \t]*\n?([\s\S]*?)```/g, function (m, lang, code) {
    var id = "\u0000" + blocks.length + "\u0000";
    blocks.push('<pre class="code"><code>' + esc(code) + "</code></pre>");
    return id;
  });
  var h = esc(text);
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
  h = h.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
  h = h.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  h = h.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  h = h.replace(/^# (.*)$/gm, "<h1>$1</h1>");
  h = h.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  h = h.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  h = h.replace(/^\s*[-*] (.*)$/gm, "<li>$1</li>");
  h = h.replace(/(<li>[\s\S]*?<\/li>)(?:\n|$)/g, "<ul>$1</ul>");
  h = h.replace(/\n{2,}/g, "</p><p>");
  h = h.replace(/\n/g, "<br>");
  h = "<p>" + h + "</p>";
  h = h.replace(/\u0000(\d+)\u0000/g, function (m, i) { return blocks[+i]; });
  return h;
}

function scrollBottom() {
  msgList.scrollTop = msgList.scrollHeight;
}
function setStatus(text, thinking) {
  statusText.textContent = text;
  statusEl.className = thinking ? "thinking" : "";
}
function addUserBubble(text) {
  var m = document.createElement("div");
  m.className = "msg user";
  m.innerHTML = '<div class="bubble">' + esc(text).replace(/\n/g, "<br>") + "</div>";
  msgList.appendChild(m);
  scrollBottom();
}
function newAssistantBubble() {
  var m = document.createElement("div");
  m.className = "msg assistant";
  m.innerHTML = '<div class="bubble"><div class="content"></div><div class="tools"></div></div>';
  msgList.appendChild(m);
  assistantEl = m.querySelector(".content");
  toolCards = [];
  return m;
}
function addErrorBubble(text) {
  var m = document.createElement("div");
  m.className = "msg assistant";
  m.innerHTML = '<div class="bubble error-bubble">⚠️ ' + esc(text) + "</div>";
  msgList.appendChild(m);
  scrollBottom();
}
function prettyArgs(s) {
  try { return JSON.stringify(JSON.parse(s), null, 2); } catch (e) { return s; }
}
function addToolCard(name, argsStr) {
  var holder = assistantEl ? assistantEl.parentNode.querySelector(".tools") : null;
  if (!holder) return;
  var d = document.createElement("details");
  d.className = "tool-card pending";
  d.innerHTML = '<summary><span class="tool-name">🔧 ' + esc(name) + '</span>'
    + '<span class="tool-args">' + esc(argsStr) + "</span></summary>"
    + '<div class="tool-result"><pre>(等待结果…)</pre></div>';
  holder.appendChild(d);
  toolCards.push(d);
  scrollBottom();
}
function fillToolCard(name, content) {
  if (!toolCards.length) return;
  var d = toolCards[toolCards.length - 1];
  d.className = "tool-card";
  var pre = d.querySelector(".tool-result pre");
  if (pre) pre.textContent = content;
  scrollBottom();
}
function renderSessions(list) {
  var box = document.getElementById("session-list");
  box.innerHTML = "";
  (list || []).forEach(function (s) {
    sessions[s.sid] = { title: s.title };
    var item = document.createElement("div");
    item.className = "session-item" + (s.sid === currentSid ? " active" : "");
    item.textContent = s.title || "新对话";
    item.onclick = function () { switchSession(s.sid); };
    box.appendChild(item);
  });
}
function renderHistory(messages) {
  msgList.innerHTML = "";
  (messages || []).forEach(function (m) {
    if (m.role === "user") addUserBubble(m.content);
    else {
      var b = newAssistantBubble();
      b.querySelector(".content").innerHTML = renderMarkdown(m.content);
    }
  });
  scrollBottom();
}
function newChat() {
  ws.send(JSON.stringify({ type: "new_chat" }));
}
function switchSession(sid) {
  ws.send(JSON.stringify({ type: "switch", sid: sid }));
}
function send() {
  var text = inputEl.value.trim();
  if (!text || !currentSid) return;
  inputEl.value = "";
  inputEl.style.height = "auto";
  addUserBubble(text);
  if (sessions[currentSid] && !sessions[currentSid].title) {
    sessions[currentSid].title = text.slice(0, 12);
    renderSessions(Object.keys(sessions).map(function (k) {
      return { sid: k, title: sessions[k].title };
    }));
  }
  acc = "";
  assistantEl = null;
  toolCards = [];
  streaming = true;
  setStatus("正在思考…", true);
  document.getElementById("send-btn").disabled = true;
  ws.send(JSON.stringify({ type: "chat", sid: currentSid, content: text }));
}

ws.onmessage = function (ev) {
  var msg;
  try { msg = JSON.parse(ev.data); } catch (e) { return; }
  switch (msg.type) {
    case "session":
      currentSid = msg.sid;
      renderSessions(msg.sessions);
      msgList.innerHTML = "";
      break;
    case "sessions":
      renderSessions(msg.list);
      break;
    case "history":
      currentSid = msg.sid;
      renderHistory(msg.messages);
      setStatus("已连接", false);
      break;
    case "token":
      if (!assistantEl) newAssistantBubble();
      acc += msg.content;
      assistantEl.innerHTML = renderMarkdown(acc) + '<span class="cursor">▍</span>';
      streaming = true;
      setStatus("正在回复…", true);
      scrollBottom();
      break;
    case "tool_call":
      addToolCard(msg.name, msg.arguments);
      break;
    case "tool_result":
      fillToolCard(msg.name, msg.content);
      break;
    case "done":
      if (assistantEl) assistantEl.innerHTML = renderMarkdown(acc);
      streaming = false;
      setStatus("已连接", false);
      document.getElementById("send-btn").disabled = false;
      scrollBottom();
      break;
    case "error":
      if (assistantEl) assistantEl.innerHTML = renderMarkdown(acc);
      addErrorBubble(msg.message);
      streaming = false;
      setStatus("出错了", false);
      document.getElementById("send-btn").disabled = false;
      break;
  }
};
ws.onclose = function () {
  setStatus("连接断开，刷新页面重连", false);
  document.getElementById("send-btn").disabled = true;
};
ws.onopen = function () {
  newChat();
};

inputEl.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
inputEl.addEventListener("input", function () {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
});

/* ---------- 设置面板 ---------- */
var MODEL_PRESETS = ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner",
  "gpt-4o", "gpt-4o-mini", "claude-sonnet-4"];
function fillModelSelect(current) {
  var sel = document.getElementById("cfg-model");
  sel.innerHTML = "";
  var list = MODEL_PRESETS.slice();
  if (list.indexOf(current) < 0) list.unshift(current);
  list.forEach(function (m) {
    var opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    if (m === current) opt.selected = true;
    sel.appendChild(opt);
  });
}
function openCfg() {
  fetch("/api/settings").then(function (r) { return r.json(); }).then(function (s) {
    fillModelSelect(s.model);
    document.getElementById("cfg-baseurl").value = s.base_url;
    document.getElementById("cfg-apikey").value = "";
    document.getElementById("cfg-apikey").placeholder =
      s.has_api_key ? "已保存密钥 (留空保持不变)" : "填写 API Key";
    document.getElementById("cfg-accent").value = s.accent;
    document.getElementById("cfg-bg").value = s.background;
    document.getElementById("cfg-modal").style.display = "flex";
  }).catch(function () { alert("读取设置失败"); });
}
function closeCfg() { document.getElementById("cfg-modal").style.display = "none"; }
function applyTheme(accent, background) {
  function to(c) { return c.map(function (x) { return x.toString(16).padStart(2, "0"); }).join(""); }
  function lum(h) {
    var c = [0, 2, 4].map(function (i) { return parseInt(h.substr(i, 2), 16); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function dark(h, f) { return "#" + to([0, 2, 4].map(function (i) { return Math.min(255, parseInt(h.substr(i, 2), 16) * f) | 0; })); }
  function blend(h1, h2, a) {
    var c1 = [0, 2, 4].map(function (i) { return parseInt(h1.substr(i, 2), 16); });
    var c2 = [0, 2, 4].map(function (i) { return parseInt(h2.substr(i, 2), 16); });
    return "#" + to(c1.map(function (x, i) { return Math.round(x * a + c2[i] * (1 - a)); }));
  }
  var a = accent.replace(/^#/, ""), b = background.replace(/^#/, "");
  var isDark = lum(b) < 128;
  var st = document.documentElement.style;
  st.setProperty("--bg", background);
  st.setProperty("--accent", accent);
  st.setProperty("--accent2", dark(a, 0.62));
  st.setProperty("--user-bubble", blend(a, b, 0.22));
  st.setProperty("--panel", isDark ? blend(b, "12171e", 0.65) : blend(b, "f6f8fa", 0.65));
  st.setProperty("--panel2", isDark ? blend(b, "161d26", 0.8) : blend(b, "ffffff", 0.8));
  st.setProperty("--border", isDark ? "#232c37" : "#d0d7de");
  st.setProperty("--text", isDark ? "#e6edf3" : "#1f2328");
  st.setProperty("--muted", isDark ? "#8b98a5" : "#57606a");
  st.setProperty("--codebg", isDark ? blend(b, "0d1117", 0.85) : blend(b, "f6f8fa", 0.85));
  st.setProperty("--codetext", isDark ? "#c9d4de" : "#24292f");
}
function saveCfg() {
  var body = {
    model: document.getElementById("cfg-model").value.trim(),
    base_url: document.getElementById("cfg-baseurl").value.trim(),
    accent: document.getElementById("cfg-accent").value,
    background: document.getElementById("cfg-bg").value
  };
  var key = document.getElementById("cfg-apikey").value.trim();
  if (key) body.api_key = key;
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); }).then(function (s) {
    applyTheme(s.accent, s.background);
    document.getElementById("model-badge").textContent = s.model;
    var foot = document.querySelector("#sidebar-foot");
    if (foot) foot.textContent = "模型: " + s.model + "\n工具: 15 个系统级 MCP";
    if (s.has_api_key) document.getElementById("cfg-banner").style.display = "none";
    closeCfg();
  }).catch(function () { alert("保存失败"); });
}
document.addEventListener("click", function (e) {
  if (e.target.classList && e.target.classList.contains("preset")) {
    var c = e.target.getAttribute("data-color");
    var bg = e.target.getAttribute("data-bg");
    if (c) document.getElementById("cfg-accent").value = c;
    if (bg) document.getElementById("cfg-bg").value = bg;
  }
  if (e.target.id === "cfg-modal") closeCfg();
});
</script>
</body>
</html>
"""


def _pick_port(start: int, tries: int = 20) -> int:
    """找一个可绑定的端口 (跳过被系统保留/占用的端口, 如 Hyper-V 排除段)。"""
    import socket
    for offset in range(tries):
        port = start + offset
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", port))
                return port
            finally:
                s.close()
        except OSError:
            continue
    return start


if __name__ == "__main__":
    final_port = _pick_port(PORT)
    if final_port != PORT:
        print(f"[webui] 端口 {PORT} 不可用, 已自动改用端口 {final_port}")
    print(f"[webui] 请打开: http://127.0.0.1:{final_port}")
    uvicorn.run(app, host="127.0.0.1", port=final_port, log_level="info")
