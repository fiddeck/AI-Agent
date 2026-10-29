# AI-Agent-GUI (WinUI 3 原生桌面端)

WinUI 3 原生桌面客户端：深色/浅色主题、左侧会话栏、流式打字机、Markdown 渲染、
可折叠工具调用卡片、停止生成——界面风格参考 DeepSeek Harness Web GUI。

## 架构

```
AI-Agent-GUI.exe (WinUI 3, C#)
      │  WebSocket (ws://127.0.0.1:<port>/ws)
      ▼
webui.py  (FastAPI 后端, 由 GUI 启动时自动拉起, 隐藏窗口)
      │  MCP stdio
      ▼
server.py  (15 个系统级工具: shell/文件/进程/剪贴板/截图/系统信息…)
```

- **原生窗口 + 本地后端**：GUI 启动时自动查找项目根目录（`webui.py` 所在处），
  若端口没有服务则隐藏启动 `.venv\Scripts\python.exe webui.py`，就绪后连接 WebSocket；
- 若已有本项目的后端在跑（例如上次没关、或手动跑了 `webui.bat`），会自动复用；
- 所有 AI 逻辑（模型调用、MCP 工具执行、会话存储）都在 Python 后端，C# 端只负责渲染。

## 环境要求

- Windows 10 1809+ / Windows 11
- **Visual Studio 2022**（推荐 17.8+）或更新版本：
  - 工作负载：**.NET 桌面开发**
  - 组件：**Windows 应用 SDK (WinUI)**
- 项目根目录必须有 `.venv`（含 openai/mcp/fastapi/uvicorn/websockets）和 `webui.py`
- 环境变量 `OPENAI_API_KEY`（或第一次运行时在设置里填写）

## 构建

### 方式一：Visual Studio

1. 打开 `AI-Agent-GUI.csproj`（或把整个 `AI-Agent-GUI` 文件夹加入现有解决方案）。
2. 平台选 **x64**（Debug/Release 均可）。
3. 首次打开会还原 NuGet（`Microsoft.WindowsAppSDK` 1.5 + BuildTools），等待完成。
4. **生成 → 生成解决方案**。
5. 输出：`AI-Agent-GUI\bin\x64\Debug\net8.0-windows10.0.19041.0\AI-Agent-GUI.exe`。

### 方式二：命令行（需要 VS 的 MSBuild，自带 WinUI 的 PRI 打包任务）

```powershell
& "F:\Visual Studio 2026\MSBuild\Current\Bin\amd64\MSBuild.exe" `
  AI-Agent-GUI\AI-Agent-GUI.csproj /t:Build `
  /p:Configuration=Release /p:Platform=x64
```

> `dotnet build` 缺少 WinUI 的 PRI 生成任务，可能出现 `PRI`/`xbf` 缺失导致启动闪退，建议用 MSBuild。

## 运行

- 直接运行生成的 `AI-Agent-GUI.exe` 即可（exe 在 bin 目录，会自动向上找到项目根目录的 `webui.py`）。
- 发布独立版见项目根目录 README 的"构建桌面版"一节。

## 界面功能

| 功能 | 说明 |
|---|---|
| 左侧会话栏 | 新建 / 切换会话；会话由后端持久化到 `data/sessions/`，**重启后自动恢复最近一次会话** |
| 流式回复 | 打字机效果 + Markdown（标题/粗体/行内代码/代码块） |
| 工具调用卡片 | 🔧 可折叠，等宽字体显示参数与执行结果，完成后显示 ✓ |
| 停止生成 | 生成中发送按钮变为红色 **■**，点击即停止；若正在执行工具，会结束工具进程 |
| 状态指示 | 顶栏绿点=已连接，蓝点闪烁=思考中/执行中，停止后显示"已停止" |
| Enter 发送 / Shift+Enter 换行 | 与聊天工具一致 |
| ⚙ 自定义设置 | 模型（下拉）/API 地址/API 密钥/端口/字号/主题色/背景色，持久化到根目录 `settings.json`，**与网页版真正互通** |

## 设置互通（本轮修复）

旧版 C# 用 `System.Text.Json` 默认的 PascalCase 写入（`Model` / `ApiKey` / `Background`），
而 `webui.py` 读的是 `model` / `api_key` / `background`，导致两边设置实际上互不相认
（典型表现：桌面版存了密钥，网页版仍提示未配置）。

现在：

- C# 端写 **camelCase**，读取时 `PropertyNameCaseInsensitive = true`，旧文件仍可识别；
- Python 端读取时兼容 camelCase / PascalCase / snake_case，写盘统一 camelCase；
- 环境变量里的 API Key **不会**被写回 `settings.json`；
- 网页版按文件 mtime 自动重载，桌面版改完设置后，网页版无需重启即可生效。

## 常见问题

- **点右上角"设置"没反应**：已在当前版本修复。WinUI 3 的 `SetTitleBar` 会把指定元素的整个区域
  当成拖拽区，旧版把含按钮的整条标题栏交给它，按钮点击就被当成拖动窗口（
  [WindowsAppSDK #2574](https://github.com/microsoft/WindowsAppSDK/issues/2574)）。现在拖拽区只覆盖
  左侧非交互区域。若仍异常，查看项目根目录 `gui.log`：正常点击会记录"设置按钮被点击"，
  打开失败会记录异常堆栈。
- **启动提示"无法启动后端服务"**：检查 `OPENAI_API_KEY` 是否已设置；或手动先跑
  `webui.bat`（项目根目录）看后端报错。
- **端口被占用**：设置里改端口，或设置环境变量 `WEBUI_PORT`；后端会自动顺延并写日志。
- **找不到项目根目录**：可通过环境变量 `AI_AGENT_ROOT` 显式指定（指向含 `webui.py` 的目录）。
- **.NET 运行时缺失**：安装 ".NET 8 Desktop Runtime"（x64），或使用 self-contained 发布。
- **想停掉后台服务**：关闭主窗口会结束本程序拉起的后端；若是外部启动的后端，去对应控制台 Ctrl+C。
- **纯网页回退方案**：根目录 `webui.bat` → 浏览器打开 `http://127.0.0.1:8000`，
  界面与 GUI 功能等价，适合排查问题。

## 备注

- 原 `AI-Agent.cpp` / `start.bat`（命令行聊天）保留，互不影响。
- 桌面端会随后端升级自动获得新能力（会话持久化、停止、多标签同步等），
  协议对未知消息类型保持向前兼容。
