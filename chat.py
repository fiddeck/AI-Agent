"""
命令行版 AI Agent (调试用)

与网页版/桌面版共用同一套核心: agent_core.AgentRunner + server.py 的 MCP 工具，
并读取同一份 settings.json(环境变量优先)。

用法:
    .venv\\Scripts\\python chat.py      (或 start.bat)
    /new 清空上下文   /tools 查看工具   /help 帮助   exit 退出
"""

from __future__ import annotations

import asyncio
import sys
import traceback

from mcp import ClientSession
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

import agent_core as core

HELP_TEXT = """可用命令:
  /new    开始新对话(清空上下文)
  /tools  列出当前 MCP 工具
  /help   显示本帮助
  exit    退出 (也可用 /exit、quit、Ctrl+C)"""


def _print_token(text: str) -> None:
    print(text, end="", flush=True)


def _tool_result_text(result) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        parts.append(str(text) if text is not None else str(item))
    body = "\n".join(parts)
    if getattr(result, "isError", False):
        return "工具返回错误: " + (body or "(无错误详情)")
    return body or "(工具未返回内容)"


async def main() -> int:
    settings = core.Settings.load()
    if not settings.configured:
        print("未找到 API Key。")
        print("  * 方式A: 设置环境变量  setx OPENAI_API_KEY \"sk-...\"  然后重开终端")
        print("  * 方式B: 在网页版/桌面版的 ⚙ 设置里填写(会写入 settings.json)")
        return 2

    print(f"{core.APP_NAME} 命令行版 (模型: {settings.model})")
    print("输入 /help 查看命令，exit 退出\n")

    async with stdio_client(core.mcp_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            raw = await session.list_tools()
            items = getattr(raw, "tools", raw) or []
            tools = core.to_openai_tools(items)
            names = core.tool_names(items)

            async def call_tool(name: str, arguments: dict) -> str:
                result = await session.call_tool(name, arguments=arguments)
                return _tool_result_text(result)

            api = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url,
                              timeout=180.0, max_retries=0)
            messages: list[dict] = [{
                "role": "system",
                "content": core.build_system_prompt(names),
            }]

            print(f"已连接 MCP，可用工具 {len(names)} 个: {', '.join(names)}\n")

            while True:
                try:
                    line = await asyncio.to_thread(input, "你: ")
                except (EOFError, KeyboardInterrupt):
                    print("\n输入已结束，退出。")
                    break

                text = line.strip()
                if not text:
                    continue
                lowered = text.lower()
                if lowered in ("exit", "quit", "/exit", "/quit"):
                    break
                if lowered == "/help":
                    print(HELP_TEXT)
                    continue
                if lowered == "/tools":
                    print("可用工具:")
                    for name in names:
                        print(f"  - {name}")
                    continue
                if lowered == "/new":
                    messages = [{"role": "system", "content": core.build_system_prompt(names)}]
                    print("已开始新对话。")
                    continue

                messages.append({"role": "user", "content": text})
                runner = core.AgentRunner(api, settings.model, tools, call_tool)
                print()  # 与"你:"分行
                try:
                    async for event in runner.run(messages):
                        kind = event.get("type")
                        if kind == "token":
                            _print_token(str(event.get("content") or ""))
                        elif kind == "tool_call":
                            args = event.get("args") or {}
                            preview = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:4])
                            if len(preview) > 160:
                                preview = preview[:160] + "…"
                            print(f"\n[工具] {event.get('name')}({preview})", flush=True)
                        elif kind == "tool_result":
                            content = str(event.get("content") or "")
                            preview = content if len(content) <= 400 else content[:400] + "…"
                            print(f"[结果] {preview}\n", flush=True)
                        elif kind == "error":
                            print(f"\n[错误] {event.get('message')}\n", flush=True)
                        elif kind == "done":
                            if event.get("stopped"):
                                print("\n[已停止]")
                            elif not runner.final_text:
                                print("(模型没有返回内容)")
                except asyncio.CancelledError:
                    print("\n[已中断]")
                    raise
                except KeyboardInterrupt:
                    print("\n[已中断本回合]")
                print("\n")

    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n再见。")
    except Exception:  # noqa: BLE001
        print("主流程异常:")
        traceback.print_exc()
        raise SystemExit(1)
