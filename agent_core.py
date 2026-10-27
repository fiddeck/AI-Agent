"""
agent_core.py — AI-Agent 的共享核心

chat.py(命令行)、webui.py(网页/桌面后端) 原先各自复制了一份设置读取、系统提示词、
工具格式转换、流式工具调用循环。本模块把这些逻辑收敛为一处，并提供:

  * Settings / SettingsManager : settings.json 的读写、校验、环境变量覆盖、跨端字段兼容
  * build_system_prompt()      : 按真实工具列表 + 运行环境动态生成系统提示词
  * to_openai_tools()          : MCP 工具 -> OpenAI Chat Completions 工具定义
  * AgentRunner                : 流式对话 + 工具调用循环(可注入 client, 便于测试)
  * SessionStore               : 会话持久化(data/sessions/*.json), 供网页版/桌面版复用
  * 若干无依赖工具函数          : 输出截断、上下文裁剪、子进程输出解码、端口选择

约定:
  * settings.json 落盘使用 camelCase(GUI 端 System.Text.Json 默认风格)，读取时同时兼容
    snake_case / PascalCase，避免两端各写一份互不相认的键。
  * 只有用户显式修改的字段才写回文件；环境变量覆盖不会把 API Key 落盘。
"""

from __future__ import annotations

import asyncio
import json
import locale
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence

APP_NAME = "AI-Agent"
APP_VERSION = "1.1.0"

ROOT = Path(__file__).resolve().parent
# 允许用环境变量重定向配置/数据目录(便于测试、便携部署或多实例)
SETTINGS_FILE = Path(os.getenv("AI_AGENT_SETTINGS") or (ROOT / "settings.json"))
DATA_DIR = Path(os.getenv("AI_AGENT_DATA_DIR") or (ROOT / "data"))
SESSION_DIR = DATA_DIR / "sessions"

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_PORT = 8000
DEFAULT_FONT_SIZE = 14.0
DEFAULT_ACCENT = "#4D9FFF"
DEFAULT_BACKGROUND = "#0C1117"

# 单次工具结果进入模型上下文前的上限；超过会被截断并标注
MAX_TOOL_RESULT_CHARS = 20000
# 模型上下文的历史消息总字符预算(粗略)，超过则丢弃最早的对话轮次
MAX_CONTEXT_CHARS = 180_000
# 一轮对话里最多执行多少次工具调用，防止模型死循环
MAX_TOOL_STEPS = 24

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# settings.json 的键名归一化: model / Model / base_url / BaseUrl 都指向同一字段
_ALIASES = {
    "model": "model",
    "baseurl": "baseUrl",
    "apikey": "apiKey",
    "port": "port",
    "fontsize": "fontSize",
    "accent": "accent",
    "background": "background",
}


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #

def _canonical_key(key: object) -> str:
    """把 settings 键归一化为比对用的形式(忽略大小写/下划线/连字符/空格)。"""
    return re.sub(r"[\s_-]", "", str(key)).lower()


def _as_text(value: Any, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _as_int(value: Any, default: int, low: int | None = None, high: int | None = None) -> int:
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    if low is not None and number < low:
        number = low
    if high is not None and number > high:
        number = high
    return number


def _as_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_hex(value: Any, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return default
    if not text.startswith("#"):
        text = "#" + text
    return text.upper() if _COLOR_RE.match(text) else default


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    """原子写入 JSON: 先写同目录临时文件再 os.replace, 避免断电/并发留下半个文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def truncate_text(text: Any, limit: int = 8000, *, note: bool = True) -> str:
    """截断超长文本，避免把模型上下文/界面撑爆。"""
    if text is None:
        return ""
    body = str(text)
    if limit <= 0 or len(body) <= limit:
        return body
    if not note:
        return body[:limit]
    return body[:limit] + f"\n...[输出已截断, 共 {len(body)} 字符, 仅显示前 {limit} 字符]"


def decode_process_output(data: bytes | str | None) -> str:
    """解码子进程输出。

    Windows 中文环境下 cmd 内建命令按控制台代码页(通常是 cp936)输出，直接按 UTF-8
    解码会得到乱码；这里依次尝试 UTF-8 / 系统首选编码 / GB18030。
    另外，按字节截断的输出末尾可能只剩半个 UTF-8 字符：如果 UTF-8 容错解码只产生极少数
    替换字符，就认定它本来就是 UTF-8，避免误判成 GBK 后把整段文字解成乱码。
    """
    if not data:
        return ""
    if isinstance(data, str):
        return data

    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    utf8_lossy = data.decode("utf-8", "replace")
    replacements = utf8_lossy.count("\ufffd")
    if replacements <= max(1, len(utf8_lossy) // 200):
        return utf8_lossy

    preferred = locale.getpreferredencoding(False)
    candidates = [preferred] if preferred else []
    candidates.append("gb18030")
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return utf8_lossy


def mcp_python() -> str:
    """返回用于拉起 server.py 的解释器路径。

    Windows 上 venv 的 sys.executable 可能指向 base 解释器(pyvenv.cfg 里写死，换电脑即失效)，
    因此优先使用 sys.prefix 下的解释器。
    """
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        candidate = Path(sys.prefix) / "Scripts" / "python.exe"
        if candidate.is_file():
            return str(candidate)
        candidate = Path(sys.prefix) / "bin" / "python"
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def mcp_server_params():
    """构造 server.py 的 stdio 连接参数(绝对路径，不依赖当前工作目录)。"""
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=mcp_python(),
        args=[str(ROOT / "server.py")],
        env=None,
        cwd=str(ROOT),
    )


def pick_free_port(start: int, tries: int = 30) -> int:
    """从 start 起找一个可绑定的本机端口(跳过被占用/被系统保留的端口段)。"""
    import socket

    for offset in range(max(1, tries)):
        port = start + offset
        if not 1 <= port <= 65535:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    return start


def new_session_id() -> str:
    """时间序 + 随机后缀，便于按文件名排序又不重名。"""
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def make_title(text: str, limit: int = 24) -> str:
    title = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(title) > limit:
        title = title[:limit].rstrip() + "…"
    return title or "新对话"


# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #

@dataclass
class Settings:
    """运行期设置(文件值 + 环境变量覆盖后的最终结果)。"""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    port: int = DEFAULT_PORT
    font_size: float = DEFAULT_FONT_SIZE
    accent: str = DEFAULT_ACCENT
    background: str = DEFAULT_BACKGROUND
    path: Path = field(default_factory=lambda: SETTINGS_FILE, repr=False, compare=False)
    api_key_source: str = field(default="none", compare=False)

    def __post_init__(self) -> None:
        self.model = _as_text(self.model, DEFAULT_MODEL)
        self.base_url = _as_text(self.base_url, DEFAULT_BASE_URL).rstrip("/")
        self.api_key = str(self.api_key or "").strip()
        self.port = _as_int(self.port, DEFAULT_PORT, 1024, 65535)
        self.font_size = _as_float(self.font_size, DEFAULT_FONT_SIZE, 10, 26)
        self.accent = _as_hex(self.accent, DEFAULT_ACCENT)
        self.background = _as_hex(self.background, DEFAULT_BACKGROUND)

    # ---- 构造 ----

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None, path: Path | None = None) -> "Settings":
        """从任意大小写风格的字典构造，未知键忽略。"""
        payload = _canonical_payload(raw or {})
        return cls(
            model=payload.get("model", DEFAULT_MODEL),
            base_url=payload.get("baseUrl", DEFAULT_BASE_URL),
            api_key=payload.get("apiKey", ""),
            port=payload.get("port", DEFAULT_PORT),
            font_size=payload.get("fontSize", DEFAULT_FONT_SIZE),
            accent=payload.get("accent", DEFAULT_ACCENT),
            background=payload.get("background", DEFAULT_BACKGROUND),
            path=Path(path or SETTINGS_FILE),
        )

    @classmethod
    def load(cls, path: Path | str | None = None, *, use_env: bool = True) -> "Settings":
        path = Path(path or SETTINGS_FILE)
        raw = read_json(path, default=None)
        settings = cls.from_mapping(raw if isinstance(raw, Mapping) else {}, path=path)
        if use_env:
            settings.apply_env()
        else:
            settings.api_key_source = "file" if settings.api_key else "none"
        return settings

    def apply_env(self) -> "Settings":
        """环境变量优先级高于设置文件(与旧版行为一致)。"""
        env = os.environ
        env_key = str(env.get("OPENAI_API_KEY") or "").strip()
        if env_key:
            self.api_key = env_key
            self.api_key_source = "env"
        else:
            self.api_key_source = "file" if self.api_key else "none"
        if env.get("OPENAI_MODEL"):
            self.model = _as_text(env["OPENAI_MODEL"], self.model)
        if env.get("OPENAI_BASE_URL"):
            self.base_url = _as_text(env["OPENAI_BASE_URL"], self.base_url).rstrip("/")
        if env.get("WEBUI_PORT"):
            self.port = _as_int(env["WEBUI_PORT"], self.port, 1024, 65535)
        return self

    # ---- 输出 ----

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def public_dict(self) -> dict[str, Any]:
        """给前端/健康检查用的安全视图(不含明文密钥)。"""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "has_api_key": bool(self.api_key),
            "api_key_source": self.api_key_source,
            "accent": self.accent,
            "background": self.background,
            "port": self.port,
            "font_size": self.font_size,
        }

    # ---- 落盘 ----

    def save(self, path: Path | str | None = None) -> Path:
        """把当前设置写回文件。

        只写文件级字段；环境变量覆盖项(如 OPENAI_API_KEY)不应因为一次保存而被持久化。
        调用方若要保存用户输入，请使用 SettingsManager.update()。
        """
        target = Path(path or self.path)
        raw = read_json(target, default=None)
        file_payload = _canonical_payload(raw if isinstance(raw, Mapping) else {})
        merged = {key: value for key, value in (raw or {}).items()
                  if _canonical_key(key) not in _ALIASES}
        write_values = self.to_file_dict()
        if self.api_key_source == "env":
            # 密钥来自环境变量时不落盘，保留文件里原有的值
            write_values["apiKey"] = str(file_payload.get("apiKey") or "")
        merged.update(write_values)
        atomic_write_json(target, merged)
        self.path = target
        return target

    def to_file_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "baseUrl": self.base_url,
            "apiKey": self.api_key,
            "port": self.port,
            "fontSize": self.font_size,
            "accent": self.accent,
            "background": self.background,
        }


def _canonical_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """任意键名写法 -> 规范 camelCase 键。"""
    payload: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = _ALIASES.get(_canonical_key(key))
        if canonical:
            payload[canonical] = value
    return payload


class SettingsManager:
    """带 mtime 检测的设置管理器。

    网页版与桌面版共用 settings.json：桌面端改完设置后，网页版不必重启即可在下一次
    请求/对话时生效。
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or SETTINGS_FILE)
        self._lock = threading.RLock()
        self._settings = Settings.load(self.path)
        self._stamp = self._stat()

    def _stat(self) -> tuple[int, int]:
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return 0, 0

    def current(self) -> Settings:
        with self._lock:
            stamp = self._stat()
            if stamp != self._stamp:
                self._settings = Settings.load(self.path)
                self._stamp = stamp
            return self._settings

    def update(self, payload: Mapping[str, Any]) -> Settings:
        """合并式更新设置文件并返回新的生效设置。

        语义:
          * 未提供的字段保持文件中的原值；
          * api_key 为空字符串时不覆盖已有密钥，除非 clear_api_key 为真；
          * 环境变量覆盖仍然优先，但不会被写进文件。
        """
        updates = dict(payload or {})
        clear_key = bool(updates.pop("clear_api_key", False))
        key_value = updates.pop("api_key", updates.pop("apiKey", None))

        with self._lock:
            existing = read_json(self.path, default=None)
            file_payload = _canonical_payload(existing if isinstance(existing, Mapping) else {})
            canonical_updates = _canonical_payload(updates)
            file_payload.update(canonical_updates)
            if clear_key:
                file_payload["apiKey"] = ""
            elif key_value is not None and str(key_value).strip():
                file_payload["apiKey"] = str(key_value).strip()

            # 复用 Settings 的校验，保证写盘的值一定是合法值
            validated = Settings.from_mapping(file_payload, path=self.path)

            extras = {key: value for key, value in (existing or {}).items()
                      if _canonical_key(key) not in _ALIASES}
            extras.update(validated.to_file_dict())
            atomic_write_json(self.path, extras)

            self._settings = Settings.load(self.path)
            self._stamp = self._stat()
            return self._settings


# --------------------------------------------------------------------------- #
# 系统提示词
# --------------------------------------------------------------------------- #

_PROMPT_RULES = """\
## 工作方式
1. 需要与电脑交互时优先调用专用工具，不要用 Python/Shell 去模拟已有工具：
   列目录用 list_files、读文本用 read_file、跑命令用 run_shell_command、查进程用 list_processes。
2. 执行 Python/Shell 前先想清楚要验证什么；把需要观察的结果 print 出来，工具会回传
   标准输出、错误输出与退出码。不要依赖"最后一行表达式"返回结果。
3. 一次只做必要的操作，避免重复执行同一条失败命令；失败后先读错误信息再换思路。
4. 读取大文件/长输出时注意截断上限，必要时分段读取；不要一次性把整份大文件塞进上下文。
5. 耗时操作(下载/安装/编译/网络请求)要设置合理的 timeout，并先告诉用户可能耗时。
6. Shell 默认在 Windows cmd 下执行，请使用 Windows 语法(cd /d、dir、where 等)。
7. 需要第三方库时先用 run_python_code 检查是否已安装，缺失再询问是否安装，不要假设一定存在。
8. 需要最新信息或网页内容时，用 run_python_code + requests/BeautifulSoup 抓取；优先官方来源。
9. 用户提到"我的电脑/系统/文件"等模糊对象时，先用 get_system_info、list_files 探查再给方案。
10. 打开文件或程序时，先看桌面的 .lnk/.url 快捷方式；打开网页用 open_url。

## 常见文件处理
- docx: python-docx；xlsx: openpyxl；pptx: python-pptx；pdf: PyMuPDF(fitz)；
- 图片文字: pytesseract 或 EasyOCR(已安装时)。
- 缺失依赖时如实说明，不要伪造结果。

## 安全边界(必须遵守)
- 删除文件/目录、结束进程、格式化磁盘、关机、递归删除等危险操作，必须先向用户说明
  影响并获得明确同意，再以 confirm=True 调用对应工具；用户未同意时禁止执行。
- 不要读取、上传或泄露与本任务无关的隐私文件；不要在文件或输出中写入 API Key 等凭据。
- 只做用户要求的事，不做"顺手"的破坏性变更。

## 输出规范
- 用简洁的中文回答，先给结论再给细节；工具执行过程用一两句话概括，不要粘贴整段原始日志。
- 代码放在 ``` 围栏里；命令、路径、参数用 `行内代码` 标注。
- 不确定的事情要说明不确定，不要编造工具结果。"""


def build_system_prompt(tools: Sequence[str] | Iterable[str], *, extra: str = "") -> str:
    """根据真实连接到的工具列表与当前运行环境生成系统提示词。"""
    names = [str(name) for name in tools if name]
    if names:
        tool_lines = "\n".join(f"- {name}" for name in names)
    else:
        tool_lines = "（当前没有已连接的工具，请直接基于已知信息回答）"

    import platform

    env_lines = [
        f"- 操作系统: {platform.platform()}",
        f"- Python: {sys.version.split()[0]}",
        f"- 工作目录: {ROOT}",
        f"- 时间: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    prompt = f"""你是 {APP_NAME}，一个运行在用户 Windows 电脑上的本地智能体。
你可以通过 MCP 工具直接操作这台电脑(执行代码/命令、读写文件、管理系统)，目标是准确、
安全地完成用户的需求，而不是只给建议。

## 运行环境
{chr(10).join(env_lines)}

## 可用工具
{tool_lines}

{_PROMPT_RULES}"""
    if extra.strip():
        prompt += "\n\n## 附加要求\n" + extra.strip()
    return prompt


# --------------------------------------------------------------------------- #
# 工具格式转换
# --------------------------------------------------------------------------- #

def _tool_field(tool: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(tool, Mapping):
            value = tool.get(name)
        else:
            value = getattr(tool, name, None)
        if value is not None:
            return value
    return default


def to_openai_tools(tools: Iterable[Any]) -> list[dict[str, Any]]:
    """MCP 工具描述 -> OpenAI Chat Completions 的 tools 定义。"""
    converted: list[dict[str, Any]] = []
    for tool in tools or []:
        name = _tool_field(tool, "name", default="")
        if not name:
            continue
        description = _tool_field(tool, "description", default="") or ""
        schema = _tool_field(tool, "input_schema", "inputSchema", default=None)
        if not isinstance(schema, Mapping) or not schema:
            schema = {"type": "object", "properties": {}}
        converted.append({
            "type": "function",
            "function": {
                "name": str(name),
                "description": str(description),
                "parameters": dict(schema),
            },
        })
    return converted


def tool_names(tools: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for tool in tools or []:
        name = _tool_field(tool, "name", default="")
        if name:
            names.append(str(name))
    return names


# --------------------------------------------------------------------------- #
# 上下文裁剪
# --------------------------------------------------------------------------- #

def _message_chars(message: Mapping[str, Any]) -> int:
    size = len(str(message.get("content") or ""))
    tool_calls = message.get("tool_calls")
    if tool_calls:
        try:
            size += len(json.dumps(tool_calls, ensure_ascii=False))
        except (TypeError, ValueError):
            size += 200
    return size


def count_message_chars(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(_message_chars(message) for message in messages)


def trim_messages(messages: list[dict[str, Any]], max_chars: int = MAX_CONTEXT_CHARS) -> list[dict[str, Any]]:
    """按"对话轮次"裁剪历史，保留 system 与最近的完整轮次。

    以 user 消息作为轮次边界，整轮丢弃，避免留下孤立的 tool 消息(会导致 API 400)。
    返回新的列表；调用方可用 `messages[:] = trim_messages(...)` 就地替换。
    """
    if max_chars <= 0 or count_message_chars(messages) <= max_chars:
        return list(messages)

    system: list[dict[str, Any]] = []
    rest = list(messages)
    if rest and rest[0].get("role") == "system":
        system = [rest.pop(0)]

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in rest:
        if message.get("role") == "user" and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)

    while len(groups) > 1 and count_message_chars(system + [m for g in groups for m in g]) > max_chars:
        groups.pop(0)

    result = system + [message for group in groups for message in group]
    while result and result[0].get("role") == "tool":
        result.pop(0)
    return result


def display_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """从模型消息中提取可持久化/可渲染的 user/assistant 文本。"""
    result: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in ("user", "assistant") and content:
            result.append({"role": str(role), "content": str(content)})
    return result


# --------------------------------------------------------------------------- #
# 会话持久化
# --------------------------------------------------------------------------- #

class SessionStore:
    """把会话以单个 JSON 文件存到 data/sessions/ 下。

    存的是"显示消息"(user/assistant 文本)，工具调用细节只在进程内保留；这样重启后
    仍能看到历史对话并继续聊天，同时避免把巨大的工具输出反复写盘。
    """

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory or SESSION_DIR)
        self._lock = threading.RLock()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _path(self, sid: str) -> Path:
        sid = str(sid)
        if not _SID_RE.match(sid):
            raise ValueError(f"非法的会话 ID: {sid!r}")
        return self.directory / f"{sid}.json"

    def exists(self, sid: str) -> bool:
        try:
            return self._path(sid).is_file()
        except ValueError:
            return False

    def create(self, sid: str | None = None, title: str = "") -> dict[str, Any]:
        session = {
            "sid": sid or new_session_id(),
            "title": title or "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "messages": [],
        }
        self.save(session)
        return session

    def load(self, sid: str) -> dict[str, Any] | None:
        try:
            path = self._path(sid)
        except ValueError:
            return None
        with self._lock:
            data = read_json(path, default=None)
        if not isinstance(data, Mapping):
            return None
        messages = data.get("messages")
        return {
            "sid": str(data.get("sid") or sid),
            "title": str(data.get("title") or ""),
            "created_at": str(data.get("created_at") or ""),
            "updated_at": str(data.get("updated_at") or ""),
            "messages": [m for m in messages if isinstance(m, Mapping)] if isinstance(messages, list) else [],
        }

    def save(self, session: Mapping[str, Any]) -> None:
        sid = str(session.get("sid") or "")
        if not sid:
            raise ValueError("会话缺少 sid")
        payload = {
            "sid": sid,
            "title": str(session.get("title") or ""),
            "created_at": str(session.get("created_at") or now_iso()),
            "updated_at": str(session.get("updated_at") or now_iso()),
            "messages": [
                {"role": str(m.get("role")), "content": str(m.get("content") or "")}
                for m in session.get("messages") or []
                if isinstance(m, Mapping) and m.get("role") in ("user", "assistant") and m.get("content")
            ],
        }
        with self._lock:
            atomic_write_json(self._path(sid), payload)

    def delete(self, sid: str) -> bool:
        try:
            path = self._path(sid)
        except ValueError:
            return False
        with self._lock:
            try:
                path.unlink()
                return True
            except OSError:
                return False

    def list(self) -> list[dict[str, Any]]:
        """返回会话元信息，按 updated_at 倒序。"""
        items: list[dict[str, Any]] = []
        try:
            files = list(self.directory.glob("*.json"))
        except OSError:
            return items
        with self._lock:
            for path in files:
                if not _SID_RE.match(path.stem):
                    continue
                data = read_json(path, default=None)
                if not isinstance(data, Mapping):
                    continue
                messages = data.get("messages")
                items.append({
                    "sid": str(data.get("sid") or path.stem),
                    "title": str(data.get("title") or "") or "新对话",
                    "updated_at": str(data.get("updated_at") or ""),
                    "message_count": len(messages) if isinstance(messages, list) else 0,
                })
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return items

    def latest(self) -> dict[str, Any] | None:
        items = self.list()
        if not items:
            return None
        return self.load(items[0]["sid"])

    def prune(self, keep: int = 200) -> int:
        """只保留最近 keep 个会话，返回删除数量。"""
        removed = 0
        for item in self.list()[max(0, keep):]:
            if self.delete(item["sid"]):
                removed += 1
        return removed


# --------------------------------------------------------------------------- #
# Agent 循环
# --------------------------------------------------------------------------- #

CallTool = Callable[[str, dict[str, Any]], Awaitable[str]]


def parse_tool_args(raw: str | None) -> tuple[dict[str, Any], str | None]:
    """解析模型给出的工具参数；返回 (参数, 错误说明)。"""
    text = (raw or "").strip()
    if not text:
        return {}, None
    try:
        value = json.loads(text)
    except ValueError as exc:
        return {}, f"JSON 解析失败: {exc}"
    if not isinstance(value, dict):
        return {}, "工具参数必须是 JSON 对象"
    return value, None


def _merge_tool_delta(calls: list[dict[str, Any]], deltas: Iterable[Any]) -> None:
    """把流式返回的 tool_calls 增量拼成完整调用(按 index 归并)。"""
    for delta in deltas:
        try:
            index = int(getattr(delta, "index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        while len(calls) <= index:
            calls.append({"id": "", "name": "", "arguments": ""})
        slot = calls[index]
        call_id = getattr(delta, "id", None)
        if call_id:
            slot["id"] = call_id
        function = getattr(delta, "function", None)
        if function is not None:
            name = getattr(function, "name", None)
            arguments = getattr(function, "arguments", None)
            if name:
                slot["name"] += name
            if arguments:
                slot["arguments"] += arguments


def _friendly_api_error(exc: Exception) -> str:
    """把常见 API 异常翻译成用户能照着处理的提示。"""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    text = str(exc)
    if status == 401 or "invalid_api_key" in text or "Unauthorized" in text:
        return "API Key 无效或已过期，请在右上角 ⚙ 设置中重新填写。"
    if status == 402 or "Insufficient Balance" in text:
        return "账户余额不足，请先充值后再试。"
    if status == 429 or "rate_limit" in text.lower():
        return "请求过于频繁或额度用尽，请稍后再试。"
    if status and int(status) >= 500:
        return f"模型服务端错误({status})，请稍后重试。详情: {text[:300]}"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "请求模型超时，请检查网络后重试。"
    return f"调用模型失败: {text[:500]}"


class AgentRunner:
    """一轮对话的执行器: 流式回复 -> 工具调用 -> 继续，直到模型给出最终答案。

    通过 `run()` 异步产出事件字典，调用方(网页版/CLI)自行决定如何渲染:
      {"type": "token", "content": str}
      {"type": "tool_call", "id": str, "name": str, "arguments": str, "args": dict}
      {"type": "tool_result", "id": str, "name": str, "content": str}
      {"type": "step", "index": int}
      {"type": "done", "content": str, "stopped": bool, "truncated": bool}
      {"type": "error", "message": str}
    """

    def __init__(
        self,
        client: Any,
        model: str,
        tools: Sequence[Mapping[str, Any]],
        call_tool: CallTool,
        *,
        max_steps: int = MAX_TOOL_STEPS,
        max_tool_result_chars: int = MAX_TOOL_RESULT_CHARS,
        max_context_chars: int = MAX_CONTEXT_CHARS,
        retries: int = 2,
    ) -> None:
        self.client = client
        self.model = model
        self.tools = list(tools or [])
        self.call_tool = call_tool
        self.max_steps = max(1, int(max_steps))
        self.max_tool_result_chars = max(1000, int(max_tool_result_chars))
        self.max_context_chars = max(0, int(max_context_chars))
        self.retries = max(0, int(retries))
        self.final_text = ""

    async def _open_stream(self, messages: list[dict[str, Any]]):
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                }
                if self.tools:
                    kwargs["tools"] = self.tools
                    kwargs["tool_choice"] = "auto"
                return await self.client.chat.completions.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 网络/鉴权异常统一转成用户提示
                last_error = exc
                if attempt < self.retries:
                    await asyncio.sleep(1.2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    async def run(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        texts: list[str] = []
        for step in range(1, self.max_steps + 1):
            trimmed = trim_messages(messages, self.max_context_chars)
            if len(trimmed) != len(messages):
                messages[:] = trimmed

            yield {"type": "step", "index": step}
            try:
                stream = await self._open_stream(messages)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                yield {"type": "error", "message": _friendly_api_error(exc)}
                self.final_text = "\n\n".join(texts)
                return

            content = ""
            calls: list[dict[str, Any]] = []
            try:
                async for chunk in stream:
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    delta = choices[0].delta
                    if delta is None:
                        continue
                    piece = getattr(delta, "content", None)
                    if piece:
                        content += piece
                        yield {"type": "token", "content": piece}
                    tool_deltas = getattr(delta, "tool_calls", None)
                    if tool_deltas:
                        _merge_tool_delta(calls, tool_deltas)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                yield {"type": "error", "message": f"流式接收中断: {exc}"}
                self.final_text = "\n\n".join(texts)
                return

            if content:
                texts.append(content)

            valid_calls = [call for call in calls if call.get("name")]
            assistant: dict[str, Any] = {"role": "assistant", "content": content or None}
            if valid_calls:
                assistant["tool_calls"] = [
                    {
                        "id": call.get("id") or f"call_{step}_{index}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call.get("arguments") or "{}",
                        },
                    }
                    for index, call in enumerate(valid_calls)
                ]
            # 既没有文本也没有工具调用时不要追加空 assistant 消息(部分接口会拒绝 content=null)
            if content or valid_calls:
                messages.append(assistant)

            if not valid_calls:
                self.final_text = "\n\n".join(texts)
                yield {"type": "done", "content": self.final_text, "stopped": False, "truncated": False}
                return

            for index, call in enumerate(valid_calls):
                name = call["name"]
                raw_arguments = call.get("arguments") or "{}"
                call_id = assistant["tool_calls"][index]["id"]
                args, parse_error = parse_tool_args(raw_arguments)
                yield {
                    "type": "tool_call",
                    "id": call_id,
                    "name": name,
                    "arguments": raw_arguments,
                    "args": args,
                }
                if parse_error:
                    text = f"未执行 {name}: {parse_error}。请重新生成合法的 JSON 参数。"
                else:
                    try:
                        text = await self.call_tool(name, args)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        text = f"执行 {name} 时出错: {exc}"
                text = truncate_text(text, self.max_tool_result_chars)
                yield {"type": "tool_result", "id": call_id, "name": name, "content": text}
                messages.append({"role": "tool", "tool_call_id": call_id, "content": text})

        self.final_text = "\n\n".join(texts)
        yield {
            "type": "error",
            "message": (
                f"已达到单轮最大工具调用次数({self.max_steps})，已停止继续调用工具。"
                "如果是长任务，请让用户确认后分步继续。"
            ),
        }
        yield {"type": "done", "content": self.final_text, "stopped": False, "truncated": True}


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ROOT",
    "SETTINGS_FILE",
    "SESSION_DIR",
    "Settings",
    "SettingsManager",
    "SessionStore",
    "AgentRunner",
    "build_system_prompt",
    "to_openai_tools",
    "tool_names",
    "trim_messages",
    "display_messages",
    "count_message_chars",
    "truncate_text",
    "decode_process_output",
    "mcp_python",
    "mcp_server_params",
    "pick_free_port",
    "new_session_id",
    "make_title",
    "parse_tool_args",
    "atomic_write_json",
    "read_json",
    "now_iso",
]
