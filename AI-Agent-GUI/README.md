# AI-Agent-GUI (WinUI 3 原生桌面启动器)

把原来黑窗口的 C++ 启动器（`AI-Agent.cpp` / `AI-Agent.exe`）升级为 **WinUI 3 原生桌面 GUI**：
深色主题、左侧会话栏、流式打字机、Markdown 渲染、可折叠的工具调用卡片——界面风格参考 DeepSeek Harness Web GUI。

## 架构

```
AI-Agent-GUI.exe (WinUI 3, C#)
      │  WebSocket (ws://127.0.0.1:8000/ws)
      ▼
webui.py  (FastAPI 后端, 由 GUI 启动时自动拉起, 隐藏窗口)
      │  MCP stdio
      ▼
server.py  (15 个系统级工具: shell/文件/进程/剪贴板/截图/系统信息…)
```

- **原生窗口 + 本地后端**：GUI 启动时自动查找项目根目录（`webui.py` 所在处），
  若 8000 端口没有服务则隐藏启动 `.venv\Scripts\python.exe webui.py`，就绪后连接 WebSocket。
- 所有 AI 逻辑（DeepSeek 调用、MCP 工具执行）都在 Python 后端，C# 端只负责界面渲染。
- 若 8000 端口已有服务（比如上次没关），会自动复用，不会重复启动。

## 环境要求

- Windows 10 1809+ / Windows 11
- **Visual Studio 2022**（推荐 17.8+）：
  - 工作负载：**.NET 桌面开发**
  - 组件：**Windows 应用 SDK (WinUI)** / "适用于 Windows 的 C++" 非必需
- 或 .NET 8 SDK + 命令行构建（见下）
- 项目根目录必须有 `.venv`（含 openai/mcp/fastapi/uvicorn/websockets）和 `webui.py`
- 环境变量 `OPENAI_API_KEY`（后端读取，同 chat.py）

## 构建

### 方式一：Visual Studio

1. 打开 `AI-Agent-GUI.csproj`（或把整个 `AI-Agent-GUI` 文件夹加入现有解决方案）。
2. 平台选 **x64**（Debug/Release 均可）。
3. 首次打开会还原 NuGet（`Microsoft.WindowsAppSDK` 1.5 + BuildTools），等待完成。
4. **生成 → 生成解决方案**。
5. 输出：`AI-Agent-GUI\bin\x64\Debug\net8.0-windows10.0.19041.0\win-x64\AI-Agent-GUI.exe`
   （或 Release 对应目录）。

### 方式二：命令行

```powershell
dotnet restore AI-Agent-GUI.csproj -r win-x64
dotnet build   AI-Agent-GUI.csproj -c Release -r win-x64
```

## 运行

- 直接运行生成的 `AI-Agent-GUI.exe` 即可（exe 在 bin 目录，会自动向上找到项目根目录的 `webui.py`）。
- 想替换旧的 `AI-Agent.exe`：把编译产物拷贝到项目根目录并改名，双击即启动 GUI。

## 界面功能

| 功能 | 说明 |
|---|---|
| 左侧会话栏 | 新建对话 / 切换会话（内存态，重启后清空） |
| 流式回复 | 打字机效果 + Markdown（粗体/行内代码/代码块） |
| 工具调用卡片 | 🔧 卡片可折叠，显示参数与执行结果（等宽字体） |
| 状态指示 | 顶栏绿点=已连接，蓝点闪烁=思考中 |
| Enter 发送 / Shift+Enter 换行 | 与聊天工具一致 |
| ⚙ 自定义设置 | 顶栏按钮：模型（下拉菜单）/API 地址/API 密钥/端口/消息字号/主题色/**背景色（默认白，自动亮暗主题）**，持久化到根目录 `settings.json`（与网页版共用）；后端配置变更自动重启后端生效 |

## 常见问题

- **启动提示"无法启动后端服务"**：检查 `OPENAI_API_KEY` 是否已设置；或手动先跑
  `webui.bat`（项目根目录）看后端报错。
- **端口被占用**：设置环境变量 `WEBUI_PORT` 改端口（后端和 GUI 都要一致）。
- **找不到项目根目录**：可通过环境变量 `AI_AGENT_ROOT` 显式指定（指向含 `webui.py` 的目录）。
- **.NET 运行时缺失**：安装 ".NET 8 Desktop Runtime"（x64）。
- **想停掉后台服务**：任务管理器结束 `python.exe`（后端为隐藏进程），或重启电脑；
  开发调试时用根目录 `webui.bat` 前台运行（Ctrl+C 可停）。
- **纯网页回退方案**：根目录 `webui.bat` → 浏览器打开 http://127.0.0.1:8000 ，
  界面与 GUI 功能等价，适合排查问题。

## 备注

- 原 `AI-Agent.cpp` / `start.bat`（命令行聊天）保留，不影响。
- 会话历史目前为内存态；如需持久化，后续可给 `webui.py` 增加 JSON 存储。
