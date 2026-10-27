# AI-Agent（Python 后端 + 网页版 + WinUI 3 桌面版）

一个本地运行的 AI Agent：基于 DeepSeek（或任意 OpenAI 兼容接口），通过 **MCP 工具集**
直接操作你的电脑——执行 Python/Shell 命令、读写文件、查系统信息、管理进程、控制剪贴板、
截屏等。提供 **网页版** 与 **WinUI 3 桌面版** 两种界面（深色/浅色主题跟随背景色自动切换）。

> 需自备 DeepSeek（或任意 OpenAI 兼容）API Key。

## 架构

```
┌─ 网页版（浏览器） ─┐      ┌─ 桌面版（WinUI 3 原生窗口） ─┐
│  webui_page.py    │      │  AI-Agent-GUI.exe           │
└────────┬──────────┘      └──────────────┬──────────────┘
         │  HTTP / WebSocket (仅监听 127.0.0.1)
         ▼                                ▼
   webui.py（FastAPI：会话管理 + 流式转发 + 停止生成 + 设置接口）
         │
         ├── agent_core.py（共享核心：设置 / 提示词 / AgentRunner / 会话持久化）
         │
         ▼  MCP stdio（全进程复用一个连接）
   server.py（15 个系统级 MCP 工具）
```

- **网页版与桌面版共用同一个后端** `webui.py`，界面只负责渲染；
- **CLI、网页、桌面共用** `agent_core.py` 的 Agent 循环与系统提示词，不再三份拷贝；
- 会话保存在 **`data/sessions/*.json`**，刷新页面、重启后端、重启桌面端都不会丢对话；
- 设置保存在项目根目录 **`settings.json`**（网页版 ⚙ 与桌面版 ⚙ 实时互通）。

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python 3.13+ | 建议用 [uv](https://github.com/astral-sh/uv) 管理虚拟环境 |
| API Key | DeepSeek 平台申请：https://platform.deepseek.com |
| Windows 10/11 | 工具集与界面均面向 Windows |
| (可选) VS 2022/2026 | 仅构建桌面版需要，见下文 |

## 快速开始

```powershell
# 1. 克隆并进入项目
git clone <仓库地址> && cd AI-Agent

# 2. 安装依赖（自动创建 .venv）
uv sync

# 3. 配置 API Key（三选一，优先级从高到低）
#    方式A: 系统环境变量（推荐，桌面版/网页版/CLI 均生效）
setx OPENAI_API_KEY "sk-你的密钥"
#    方式B: 首次打开界面时在 ⚙ 设置里填写（保存到 settings.json）
#    方式C: 复制 settings.json 模板并填 apiKey 字段（键名兼容 camelCase/PascalCase/snake_case）
```

## 使用方式（三选一）

### 方式 1：网页版（零构建，推荐先用这个）

```powershell
webui.bat
```

浏览器打开 `http://127.0.0.1:8000`（端口被占用/保留时自动顺延，以控制台打印的地址为准）。
首次使用页面顶部会提示配置 API Key，点右上角 **⚙** 填写即可。

网页版特性：

- 左侧会话列表：**新建 / 切换 / 删除**，会话落盘，重启后仍在；
- 流式回复 + Markdown（标题/列表/表格/代码块/引用/链接），代码块一键复制；
- 工具调用可折叠卡片，显示参数与执行结果；
- **■ 停止生成**：生成中点停止按钮立即中止；若正在执行工具，会结束工具子进程；
- 多标签页同时打开时，同一会话的消息会实时同步；
- 断线自动重连（指数退避），不需要刷新页面。

### 方式 2：WinUI 3 桌面版（原生窗口）

构建/发布后直接双击项目根目录的 `AI-Agent 桌面版.lnk`（或 `dist\AI-Agent-GUI\AI-Agent-GUI.exe`）：

- 自动查找项目根目录并隐藏启动后端；若已有本项目的后端在跑则直接复用；
- 首次使用（无密钥）自动弹出配置对话框；
- 启动时恢复最近一次会话（不会每次多出一个空会话）；
- 生成中发送按钮变为 **■ 停止**；
- 顶栏 ⚙ 设置与网页版共享同一份 `settings.json`，主题色/字号即时生效，后端配置变更自动重启后端。

> ⚠️ 不要单独把 `AI-Agent-GUI.exe` 拷出来双击：.NET/WinUI 程序的 exe 只是引导器，
> 必须和同目录下的 `AI-Agent-GUI.dll`、`AI-Agent-GUI.pri`、`*.xbf` 及整套运行库放在
> 一起才能启动（在 VS 里能跑是因为 VS 是从 bin 完整目录启动的）。

### 方式 3：命令行（调试用）

```powershell
start.bat    # 等价于 .venv\Scripts\python chat.py
```

命令行支持 `/new`（清空上下文）、`/tools`（列工具）、`/help`、`exit`。
也可直接双击根目录的 `AI-Agent.exe`（C++ 启动器，自动定位项目根目录并新开控制台）。

## 构建桌面版 (AI-Agent-GUI)

1. 安装 **Visual Studio 2022**（17.8+）或更新版本，工作负载勾选 **".NET 桌面开发"**，
   组件勾选 **"Windows 应用 SDK (WinUI)"**；
2. 打开 `AI-Agent-GUI\AI-Agent-GUI.csproj`，平台选 **x64**，等待 NuGet 还原；
3. 生成解决方案（VS 内直接 F5 调试）；
4. 产物在 `AI-Agent-GUI\bin\x64\Release\net8.0-windows10.0.19041.0\AI-Agent-GUI.exe`。

**发布独立版（推荐，双击即用，自带 .NET 运行时）：**

```bat
:: 注意: 必须用 VS 自带的 MSBuild (dotnet CLI 缺少 WinUI 的 PRI 打包任务)
"F:\Visual Studio 2026\MSBuild\Current\Bin\amd64\MSBuild.exe" ^
  AI-Agent-GUI\AI-Agent-GUI.csproj /t:Publish ^
  /p:Configuration=Release /p:Platform=x64 /p:RuntimeIdentifier=win-x64 ^
  /p:SelfContained=true /p:PublishDir="G:\Python文件\AI-Agent 2.0\dist\AI-Agent-GUI\"
```

> ⚠️ 发布完成后需把 `AI-Agent-GUI\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64\`
> 里本应用的 `AI-Agent-GUI.pri` 与 `App.xbf`/`MainWindow.xbf`/`SettingsDialog.xbf`
> 一并复制进 `dist\AI-Agent-GUI\`（WinUI 发布会漏掉这几个文件，缺失会导致双击闪退）。

## 自定义设置

设置存于项目根目录 **`settings.json`**（网页版 ⚙ 与桌面版 ⚙ 共用）。写入使用
**camelCase**（`model` / `baseUrl` / `apiKey` / `port` / `fontSize` / `accent` / `background`），
读取时兼容 `Model`、`base_url` 等旧写法。

| 字段 | 默认值 | 说明 |
|---|---|---|
| `model` | `deepseek-v4-flash` | 模型名（设置里是下拉菜单，可自定义） |
| `baseUrl` | `https://api.deepseek.com` | OpenAI 兼容 API 地址 |
| `apiKey` | `""` | 留空则使用环境变量 `OPENAI_API_KEY`（环境变量优先，且不会被写回文件） |
| `port` | `8000` | 后端端口（被占用时自动顺延） |
| `fontSize` | `14` | 消息字号（桌面版） |
| `accent` | `#4D9FFF` | 主题色 |
| `background` | `#0C1117` | 背景色（背景偏亮自动切浅色主题，偏暗切深色主题） |

环境变量优先级高于设置文件：`OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` / `WEBUI_PORT`。
另有 `AI_AGENT_SETTINGS`（设置文件路径）、`AI_AGENT_DATA_DIR`（会话数据目录），便于测试或便携部署。

## 系统级工具（15 个 MCP 工具）

`run_python_code` · `run_shell_command` · `list_files` · `read_file` · `write_file` ·
`search_files` · `delete_file` · `get_system_info` · `list_processes` · `kill_process` ·
`get_clipboard` · `set_clipboard` · `open_url` · `take_screenshot` · `get_datetime`

执行与安全机制（本轮已重构）：

- Python 代码与 shell 命令在**独立子进程**中执行：死循环/崩溃不会拖死 MCP 服务，
  超时会**结束整棵进程树**（`taskkill /T`），不会留下野进程；
- 输出按字节上限截断，写入临时文件而不是管道，避免被大量输出撑爆内存；
- Windows 中文环境下 cmd 输出按 **UTF-8 → 系统代码页(GBK) → GB18030** 依次解码，
  不再出现 `���Ĳ���` 乱码；
- 长代码通过 stdin 传给解释器，不受 Windows 命令行 8K 长度限制；
- 删除文件/目录、结束进程、格式化/关机/递归删除、`git reset --hard` 等高危操作必须
  `confirm=True`；此外**关键目录**（磁盘根、用户主目录、桌面/下载、系统目录、项目目录及其上级）
  即使 confirm 也会被拒绝删除；
- 模型侧提示词根据**实际连接到的工具列表**动态生成，不再是硬编码的 15 条清单。

## 测试

```powershell
.venv\Scripts\python -m pytest              # 全部测试（含真实子进程端到端）
.venv\Scripts\python -m pytest -m "not e2e" # 只跑单元/集成测试，跳过启动后端的端到端
```

- `tests/test_agent_core.py`：设置兼容/校验/密钥不落盘、会话存储、上下文裁剪、AgentRunner
  （文本流、工具调用、非法参数、最大步数、重试、API 错误）；
- `tests/test_server_tools.py`：高危命令识别、GBK 输出、超时杀进程树、文件读写与删除保护；
- `tests/test_webui_e2e.py`：启动真实 `webui.py` 子进程 + 模拟 OpenAI SSE 接口 + WebSocket
  客户端，验证流式回复、MCP 工具调用、会话持久化、切换/新建会话、设置接口。

## 常见问题

| 问题 | 解决 |
|---|---|
| 后端起不来 / 提示配置 | 运行 `webui.bat` 看真实报错；确认 `uv sync` 成功（`fastapi/uvicorn/websockets` 已安装） |
| 端口被占用报 `winerror 10013` | 正常现象：Windows 保留端口段（Hyper-V/WSL）。系统会自动顺延端口，无需处理 |
| 网页版启动报错乱码 | 批处理必须保持纯 ASCII（不要往 `webui.bat` 里加中文） |
| 找不到后端根目录 | 桌面版通过环境变量 `AI_AGENT_ROOT` 可指定项目根目录 |
| 双击 `AI-Agent-GUI.exe` 打不开/闪退 | 只把 exe 单独拷走了。请双击根目录 `AI-Agent 桌面版.lnk` 或 `dist\AI-Agent-GUI\AI-Agent-GUI.exe`，整个文件夹要一起保留 |
| 想停止后端 | 网页版：关掉 `webui.bat` 窗口；桌面版：关闭主窗口会自动结束它拉起的后端 |
| 生成太久想中断 | 网页版点输入框旁 **■ 停止**；桌面版点发送位置的 **■**。若正在跑工具，会同时结束工具进程 |
| 会话太多了 | 网页版左栏悬停会话 → 点 **×** 删除；数据在 `data/sessions/`，可直接清理（服务运行时建议用界面删） |
| 换电脑后提示 `Could not find executable at 'E:\Python\python.exe'` / 后端退出码 103 | 旧 `.venv` 绑定了原电脑的 Python 路径。双击根目录 **`修复环境.bat`** 重建虚拟环境即可 |

## 迁移到其他电脑

1. **打包时不要包含 `.venv` 目录**——虚拟环境在 `pyvenv.cfg` 里写死了创建它的那台电脑的 Python 路径；
2. 拷贝项目到新电脑后，先双击 **`修复环境.bat`**（自动删除旧 `.venv` 并用本机 Python 重建，
   优先 `uv sync`，无 uv 时回退 `python -m venv` + `pip install -e .`）；
3. 设置 API Key：`setx OPENAI_API_KEY "sk-你的密钥"`（或打开界面后在 ⚙ 里填写）；
4. 然后双击 `AI-Agent 桌面版.lnk` 或运行 `webui.bat`。

## 一键安装包（可选）

项目提供 Inno Setup 打包脚本（`installer\AI-Agent-installer.iss`），可打出
`dist\AI-Agent-Setup.exe` 安装包：

- **桌面端已 self-contained**，目标机无需安装 .NET / Windows App SDK；
- **后端依赖在安装时自动创建**（`uv sync` 或 pip + 清华镜像），目标机无需预装 Python；
- 安装到用户目录（免管理员权限），并创建开始菜单/桌面快捷方式；
- 编译方法：安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 后编译该 .iss（或 `ISCC.exe installer\AI-Agent-installer.iss`）。

> 依赖体积较大（含 torch/easyocr 等），首次安装联网拉取约 5-20 分钟属正常。
> Docker 方案不适用于本项目：桌面 GUI 无法容器化，且 MCP 工具集依赖 Windows 宿主。

## 目录结构

```
AI-Agent/
├── agent_core.py      # 共享核心: 设置 / 提示词 / 工具转换 / AgentRunner / 会话持久化
├── server.py          # MCP 服务器 (15 个系统级工具, 子进程隔离执行)
├── webui.py           # FastAPI 后端 + WebSocket 协议
├── webui_page.py      # 网页版 HTML/CSS/JS 模板 (render_page 注入主题)
├── chat.py            # 命令行聊天 (调试用)
├── command.py         # start.bat 入口
├── webui.bat          # 网页版启动器 (纯 ASCII, 勿加中文)
├── settings.json      # 共享设置 (首次配置后生成)
├── data/sessions/     # 会话持久化 (运行时生成, 已加入 .gitignore)
├── tests/             # pytest 单元 + 端到端测试
├── AI-Agent-GUI/      # WinUI 3 桌面版源码
├── docs/IMPROVEMENTS.md  # 本轮重构/审计说明
└── requirements.txt   # 依赖清单 (uv sync 使用 pyproject.toml)
```
