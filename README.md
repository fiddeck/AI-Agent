# Python版 AI Agent Project

一个本地运行的 AI Agent：基于 DeepSeek（OpenAI 兼容接口），通过 **MCP 工具集** 可以直接操作你的电脑——执行 Python/Shell 命令、读写文件、查系统信息、管理进程、控制剪贴板、截屏等。提供 **网页版** 和 **WinUI 3 桌面版** 两种界面（DSH 风格深色/浅色主题）。

> 需自备 DeepSeek（或任意 OpenAI 兼容）API Key。

## 架构

```
┌─  网页版 (浏览器) ──┐   ┌─ 桌面版 (WinUI 3 原生窗口) ─┐
│  webui.py 渲染页面  │   │  AI-Agent-GUI.exe         │
└─────────┬──────────┘   └────────────┬───────────────┘
          │  WebSocket (本地端口)       │
          ▼                            ▼
      webui.py (FastAPI 后端引擎: DeepSeek 流式调用 + 工具调度)
          │  MCP stdio
          ▼
      server.py (15 个系统级 MCP 工具)
```

- **网页版与桌面版共用同一个后端** `webui.py`，界面只负责渲染；
- 设置存于项目根目录 **`settings.json`**，两端互通。

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python 3.13+ | 建议用 [uv](https://github.com/astral-sh/uv) 管理虚拟环境 |
| API Key | DeepSeek 平台申请：https://platform.deepseek.com |
| Windows 10/11 | 工具集与界面均面向 Windows |
| (可选) VS2022 | 仅构建桌面版需要，见下文 |

## 快速开始

```powershell
# 1. 克隆并进入项目
git clone <仓库地址> && cd AI-Agent

# 2. 安装依赖 (自动创建 .venv)
uv sync

# 3. 配置 API Key (二选一)
#    方式A: 系统环境变量 (推荐, 桌面版/网页版均生效)
setx OPENAI_API_KEY "sk-你的密钥"
#    方式B: 首次打开界面时在 ⚙ 设置里填写 (会保存到 settings.json)
```

## 使用方式（三选一）

### 方式 1：网页版（零构建，推荐先用这个）

```powershell
webui.bat
```

浏览器自动/手动打开 `http://127.0.0.1:8000`（端口被占用时自动顺延，以控制台打印的地址为准）。
首次使用页面顶部会提示配置 API Key，点右上角 **⚙** 填写即可。

### 方式 2：WinUI 3 桌面版（原生窗口，最接近本地应用体验）

见下方"构建桌面版"。构建后直接运行 `AI-Agent-GUI.exe`：
- 自动查找项目根目录并隐藏启动后端，无需手动开服务；
- 首次使用（无密钥）自动弹出配置对话框；
- 顶栏 ⚙ 设置与网页版共享同一份 `settings.json`。

### 方式 3：命令行（调试用）

```powershell
start.bat    # 等价于 .venv\Scripts\python chat.py
```
目前已经换回Python3.13.15，通过了本地实机测试

## 构建桌面版 (AI-Agent-GUI)

1. 安装 **Visual Studio 2022**（17.8+），工作负载勾选 **".NET 桌面开发"**，组件勾选 **"Windows 应用 SDK (WinUI)"**；
2. 打开 `AI-Agent-GUI\AI-Agent-GUI.csproj`，平台选 **x64**，等待 NuGet 还原；
3. 生成解决方案；
4. 产物在 `AI-Agent-GUI\bin\x64\Debug\net8.0-windows10.0.19041.0\win-x64\AI-Agent-GUI.exe`，直接运行。

> 也可命令行构建：`dotnet build AI-Agent-GUI\AI-Agent-GUI.csproj -c Release -r win-x64`

## 自定义设置

设置存于项目根目录 **`settings.json`**（网页版 ⚙ 与桌面版 ⚙ 共用）：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `model` | `deepseek-v4-flash` | 模型名（设置里是下拉菜单，可自定义） |
| `base_url` | `https://api.deepseek.com` | OpenAI 兼容 API 地址 |
| `api_key` | `""` | 留空则使用环境变量 `OPENAI_API_KEY` |
| `port` | `8000` | 后端端口（被占用时自动顺延） |
| `font_size` | `14` | 消息字号（仅桌面版） |
| `accent` | `#4D9FFF` | 主题色 |
| `background` | `#FFFFFF` | 背景色（默认白色；背景偏亮自动切换浅色主题，偏暗切换深色主题） |

环境变量优先级高于设置文件：`OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` / `WEBUI_PORT`。

## 系统级工具（15 个 MCP 工具）

`run_python_code` · `run_shell_command` · `list_files` · `read_file` · `write_file` · `search_files` · `delete_file` · `get_system_info` · `list_processes` · `kill_process` · `get_clipboard` · `set_clipboard` · `open_url` · `take_screenshot` · `get_datetime`

> 安全机制：删除文件/目录、结束进程、高危 shell 命令（格式化/递归删除/关机等）必须 `confirm=True` 才会执行，模型会先向你确认。

## 常见问题

| 问题 | 解决 |
|---|---|
| 后端起不来 / 提示配置 | 运行 `webui.bat` 看真实报错；确认 `uv sync` 成功（`fastapi/uvicorn/websockets` 已安装） |
| 端口被占用报 `winerror 10013` | 正常现象：Windows 保留端口段（Hyper-V/WSL）。系统会自动顺延端口，无需处理 |
| 网页版启动报错乱码 | 批处理必须保持纯 ASCII（不要往 `webui.bat` 里加中文） |
| 找不到后端根目录 | 桌面版通过环境变量 `AI_AGENT_ROOT` 可指定项目根目录 |
| 想停止后端 | 网页版：关掉 `webui.bat` 窗口；桌面版：关闭主窗口会自动结束它拉起的后端 |

## 目录结构

```
AI-Agent - rc1/
├── chat.py            # 命令行聊天 (调试用)
├── command.py         # start.bat 入口
├── server.py          # MCP 服务器 (15 个系统级工具)
├── webui.py           # FastAPI 后端 + 网页版界面 (含 ⚙ 设置)
├── webui.bat          # 网页版启动器 (纯 ASCII, 勿加中文)
├── settings.json      # 共享设置 (首次配置后生成)
├── AI-Agent-GUI/      # WinUI 3 桌面版源码
└── requirements.txt   # 依赖清单 (uv sync 使用 pyproject.toml)
```
