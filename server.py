"""
MCP 服务器: AI-Agent 系统级工具集

通过 FastMCP(stdio) 暴露给 chat.py 的工具:
  - run_python_code   : 执行 Python 代码 (原有工具)
  - run_shell_command : 执行 shell 命令 (cmd, 带高危命令防护)
  - list_files        : 列举目录/文件
  - read_file         : 读取文本文件 (带大小上限)
  - write_file        : 写入文本文件
  - search_files      : 递归搜索文件
  - delete_file       : 删除文件/目录 (需 confirm=True)
  - get_system_info   : 系统信息 (OS/CPU/内存/磁盘)
  - list_processes    : 进程列表
  - kill_process      : 结束进程 (需 confirm=True)
  - get_clipboard     : 读取剪贴板
  - set_clipboard     : 写入剪贴板
  - open_url          : 默认浏览器打开网址
  - take_screenshot   : 全屏截图
  - get_datetime      : 当前日期时间

安全说明:
  - 所有删除/结束进程/高危命令都要求 confirm=True, 由模型先向用户确认。
  - 输出统一做截断, 防止撑爆模型上下文。
  - psutil / pywin32 / Pillow 为可选依赖, 缺失时对应工具自动降级或报错提示。
"""

from mcp.server.fastmcp import FastMCP
import io
import os
import re
import sys
import shutil
import string
import platform
import subprocess
import contextlib
import traceback
from pathlib import Path
from datetime import datetime

# ---------- 可选依赖探测 ----------
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import win32clipboard
    import win32con
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False

try:
    from PIL import ImageGrab
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

mcp = FastMCP("AI-Agent-System")

# ---------- 通用辅助 ----------

def _path(p: str) -> Path:
    """展开环境变量/用户目录并解析为绝对路径。"""
    return Path(os.path.expandvars(os.path.expanduser(p))).resolve()


def _truncate(text: str, limit: int = 8000) -> str:
    """截断超长输出, 保护模型上下文。"""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[输出已截断, 共 {len(text)} 字符]"


# 高危命令模式: 匹配到且 confirm=False 时拒绝执行
_DANGEROUS_PATTERNS = [
    r"format\s+[a-zA-Z]:",            # 格式化磁盘
    r"\b(rd|rmdir)\s+/s",             # 递归删除目录
    r"\b(del|erase)\s+/[sfq]",        # 强制删除文件
    r"\bshutdown\b",                  # 关机
    r"\b(restart-computer|stop-computer)\b",  # PowerShell 重启/关机
    r"\bdiskpart\b",                  # 磁盘分区
    r"\breg\s+delete\b",              # 删除注册表
    r"\bnet\s+(user|localgroup)\b",   # 用户/组管理
    r"\bcipher\s+/w",                 # 擦除磁盘
    r"Remove-Item\s+(-Recurse|-Force)",   # PowerShell 递归/强制删除
    r"\bClear-Content\b",             # PowerShell 清空文件
    r"\bFormat-Volume\b",             # PowerShell 格式化卷
    r"\btaskkill\s+/f\b",             # 强制结束进程(请用 kill_process 工具)
    r"powershell\s+-e(nc|ncoded)?\b|pwsh\s+-e(nc|ncoded)?\b",  # 编码命令
]

_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS), re.IGNORECASE)


# ---------- 工具: 代码/命令执行 ----------

@mcp.tool()
def run_python_code(code: str) -> str:
    """执行 Python 代码。代码直接运行在用户电脑上, 请谨慎。

    参数:
      code: 要执行的 Python 代码
    """
    stdout_io = io.StringIO()
    stderr_io = io.StringIO()
    exec_namespace = {}
    try:
        with contextlib.redirect_stdout(stdout_io), contextlib.redirect_stderr(stderr_io):
            exec(code, exec_namespace)
    except Exception:
        stderr_io.write(traceback.format_exc())
    output = str(stdout_io.getvalue())
    error = str(stderr_io.getvalue())
    content = output
    if error:
        content += f"\nError: {error}"
    return content


@mcp.tool()
def run_shell_command(command: str, timeout: int = 60, confirm: bool = False) -> str:
    """在 Windows 上执行 shell 命令 (cmd)。返回 stdout、stderr 与退出码。

    用于安装程序、运行脚本、网络请求、系统管理等 Python 不好直接做的事。
    高危命令 (格式化磁盘、递归删除、关机、清空目录、结束进程等) 必须 confirm=True 才会执行。

    参数:
      command: 要执行的命令, 使用 Windows cmd 语法
      timeout: 超时秒数, 默认 60
      confirm: 高危命令需为 True 才会执行
    """
    if _DANGEROUS_RE.search(command):
        if not confirm:
            return ("拒绝执行: 该命令属于高危操作 (可能格式化磁盘/递归删除/关机/结束进程等)。"
                    "如需执行, 请先向用户说明并获得同意, 再以 confirm=True 重试。")
    try:
        result = subprocess.run(
            ["cmd", "/c", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"命令超时 (>{timeout}s), 已终止: {command}"
    except Exception as e:
        return f"执行失败: {e}"

    out = _truncate(result.stdout)
    err = _truncate(result.stderr)
    lines = [f"[退出码 {result.returncode}]"]
    if out:
        lines.append(out)
    if err:
        lines.append(f"[stderr]\n{err}")
    if not out and not err:
        lines.append("(无输出)")
    return "\n".join(lines)


# ---------- 工具: 文件系统 ----------

@mcp.tool()
def list_files(path: str = ".", pattern: str = "*", recursive: bool = False, max_results: int = 100) -> str:
    """列举目录中的文件和子目录。

    参数:
      path: 目录路径, 默认当前目录
      pattern: 文件名匹配模式, 支持通配符, 如 *.py、*data*
      recursive: 是否递归子目录
      max_results: 最多返回条数, 默认 100
    """
    root = _path(path)
    if not root.is_dir():
        return f"错误: 目录不存在 {root}"
    try:
        items = []
        if recursive:
            iterator = root.rglob(pattern)
        else:
            iterator = root.glob(pattern)
        for p in iterator:
            kind = "[DIR]" if p.is_dir() else "     "
            items.append(f"{kind} {p}")
            if len(items) >= max_results:
                items.append(f"...(已达上限 {max_results} 条)")
                break
        if not items:
            return f"未找到匹配 '{pattern}' 的内容: {root}"
        return "\n".join(items)
    except Exception as e:
        return f"列举失败: {e}"


@mcp.tool()
def read_file(path: str, max_bytes: int = 20000) -> str:
    """读取文本文件内容, 最多读取 max_bytes 字节 (默认 20KB), 超出部分截断并在末尾提示。

    参数:
      path: 文件路径
      max_bytes: 读取上限字节数
    """
    p = _path(path)
    if not p.is_file():
        return f"错误: 文件不存在 {p}"
    try:
        size = p.stat().st_size
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_bytes)
        tail = (f"\n...[已截断, 文件共 {size} 字节, 仅显示前 {max_bytes} 字节]"
                if size > max_bytes else f"\n[文件共 {size} 字节]")
        return content + tail
    except Exception as e:
        return f"读取失败: {e}"


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """写入文本文件 (默认覆盖, append=True 追加)。自动创建父目录。

    参数:
      path: 文件路径
      content: 要写入的内容
      append: True 追加, False 覆盖
    """
    p = _path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        return f"已{'追加' if append else '写入'} {p} ({len(content)} 字符)"
    except Exception as e:
        return f"写入失败: {e}"


@mcp.tool()
def search_files(path: str = ".", pattern: str = "*", max_results: int = 100) -> str:
    """递归搜索匹配 pattern 的文件。

    参数:
      path: 搜索起点目录
      pattern: 通配符模式, 如 *.py、**/*.txt、*report*
      max_results: 最多返回条数, 默认 100
    """
    root = _path(path)
    if not root.is_dir():
        return f"错误: 目录不存在 {root}"
    try:
        items = []
        for p in root.rglob(pattern):
            if p.is_file():
                items.append(str(p))
                if len(items) >= max_results:
                    items.append(f"...(已达上限 {max_results} 条)")
                    break
        if not items:
            return f"未找到匹配 '{pattern}' 的文件: {root}"
        return "\n".join(items)
    except Exception as e:
        return f"搜索失败: {e}"


@mcp.tool()
def delete_file(path: str, recursive: bool = False, confirm: bool = False) -> str:
    """删除文件或目录。任何删除都必须 confirm=True 才会执行。

    参数:
      path: 目标路径
      recursive: 删除目录时需要 True
      confirm: 确认删除, 必须为 True
    """
    p = _path(path)
    if not os.path.exists(p):
        return f"错误: 路径不存在 {p}"
    if not confirm:
        return (f"拒绝删除: 需要确认。请向用户说明将删除 {p}, "
                "获得同意后以 confirm=True 重试。")
    try:
        if p.is_dir():
            if not recursive:
                return f"拒绝删除: {p} 是目录, 删除目录需要 recursive=True。"
            shutil.rmtree(p)
            return f"已删除目录 {p}"
        os.remove(p)
        return f"已删除文件 {p}"
    except Exception as e:
        return f"删除失败: {e}"


# ---------- 工具: 系统信息与进程 ----------

def _get_memory_text() -> str:
    """内存信息: 优先 psutil, 回退 ctypes。"""
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        return (f"内存: 总 {vm.total / 1024 ** 3:.1f} GB, 可用 {vm.available / 1024 ** 3:.1f} GB, "
                f"使用率 {vm.percent}%")
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return (f"内存: 总 {m.ullTotalPhys / 1024 ** 3:.1f} GB, "
                f"可用 {m.ullAvailPhys / 1024 ** 3:.1f} GB, 使用率 {m.dwMemoryLoad}%")
    except Exception:
        return "内存: 无法获取"


def _list_drives() -> list:
    """返回 Windows 上存在的盘符列表, 如 [C:\\, D:\\]。"""
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    return drives


@mcp.tool()
def get_system_info() -> str:
    """获取系统信息: 操作系统、主机名、CPU 核心、内存、磁盘空间、Python 版本等。"""
    try:
        lines = [
            f"操作系统: {platform.platform()}",
            f"机器: {platform.machine()} / {platform.processor()}",
            f"主机名: {platform.node()}",
            f"CPU 逻辑核心: {os.cpu_count()}",
            _get_memory_text(),
        ]
        for drive in _list_drives():
            try:
                usage = shutil.disk_usage(drive)
                lines.append(
                    f"磁盘 {drive}: 总 {usage.total / 1024 ** 3:.1f} GB, "
                    f"可用 {usage.free / 1024 ** 3:.1f} GB "
                    f"({usage.free / usage.total * 100:.0f}% 可用)"
                )
            except Exception:
                lines.append(f"磁盘 {drive}: 无法获取")
        lines.append(f"Python: {sys.version.split()[0]}")
        lines.append(f"psutil: {'可用' if HAS_PSUTIL else '未安装(进程工具降级为 tasklist/taskkill)'}")
        return "\n".join(lines)
    except Exception as e:
        return f"获取系统信息失败: {e}"


@mcp.tool()
def list_processes(name_filter: str = "", max_results: int = 50) -> str:
    """列出正在运行的进程。

    参数:
      name_filter: 按进程名筛选 (如 python、chrome、code), 留空列出全部
      max_results: 最多返回条数, 默认 50
    """
    try:
        if HAS_PSUTIL:
            rows = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    pinfo = proc.info
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                name = pinfo.get("name") or ""
                if name_filter and name_filter.lower() not in name.lower():
                    continue
                rows.append(f"{pinfo['pid']:<8} {name}")
                if len(rows) >= max_results:
                    rows.append(f"...(已达上限 {max_results} 条)")
                    break
            if not rows:
                return f"没有匹配 '{name_filter}' 的进程"
            return "\n".join(rows)
        # 回退: tasklist
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="gbk", errors="replace", timeout=30,
        )
        rows = []
        for line in (r.stdout or "").splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                pname = parts[0].strip('"')
                pid = parts[1].strip('"')
                if name_filter and name_filter.lower() not in pname.lower():
                    continue
                rows.append(f"{pid:<8} {pname}")
        if not rows:
            return f"没有匹配 '{name_filter}' 的进程"
        if len(rows) > max_results:
            rows = rows[:max_results] + [f"...(还有 {len(rows) - max_results} 个进程未显示)"]
        return "\n".join(rows)
    except Exception as e:
        return f"获取进程列表失败: {e}"


@mcp.tool()
def kill_process(pid: int = 0, name: str = "", confirm: bool = False) -> str:
    """结束进程。指定 pid 或进程名 name, 二者至少一个。必须 confirm=True 才会执行。

    参数:
      pid: 进程 ID
      name: 进程名 (如 notepad.exe)
      confirm: 确认结束, 必须为 True
    """
    if not pid and not name:
        return "错误: 必须提供 pid 或 name, 二者至少一个。"
    if not confirm:
        target = f"PID {pid}" if pid else f"进程 {name}"
        return (f"拒绝结束{target}: 需要确认。请向用户说明后以 confirm=True 重试。")
    try:
        if HAS_PSUTIL:
            killed = []
            if pid:
                proc = psutil.Process(pid)
                proc.terminate()
                killed.append(f"PID {pid} ({proc.name()})")
            if name:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        if proc.info.get("name") and proc.info["name"].lower() == name.lower():
                            proc.terminate()
                            killed.append(f"PID {proc.info['pid']} ({proc.info['name']})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            return f"已结束: {', '.join(killed) if killed else '未找到目标进程'}"
        # 回退: taskkill
        if pid:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, text=True, encoding="gbk", errors="replace")
        else:
            r = subprocess.run(["taskkill", "/IM", name, "/F"],
                               capture_output=True, text=True, encoding="gbk", errors="replace")
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return f"退出码 {r.returncode}: {out}"
    except Exception as e:
        return f"结束进程失败: {e}"


# ---------- 工具: 剪贴板 / 浏览器 / 截图 / 时间 ----------

@mcp.tool()
def get_clipboard() -> str:
    """读取剪贴板中的文本内容。"""
    if not HAS_PYWIN32:
        return "错误: 未安装 pywin32, 无法读取剪贴板。"
    try:
        win32clipboard.OpenClipboard()
        try:
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return str(data) if data else "(剪贴板为空)"
    except Exception as e:
        return f"读取剪贴板失败: {e}"


@mcp.tool()
def set_clipboard(text: str) -> str:
    """将文本写入剪贴板。

    参数:
      text: 要写入的文本
    """
    if not HAS_PYWIN32:
        return "错误: 未安装 pywin32, 无法写入剪贴板。"
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return f"已写入剪贴板 ({len(text)} 字符)"
    except Exception as e:
        return f"写入剪贴板失败: {e}"


@mcp.tool()
def open_url(url: str) -> str:
    """在默认浏览器中打开网址。

    参数:
      url: 网址, 必须以 http:// 或 https:// 开头
    """
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return f"拒绝打开: {url} 不是有效的 http(s) 网址。"
    try:
        import webbrowser
        webbrowser.open(url)
        return f"已在默认浏览器打开: {url}"
    except Exception as e:
        return f"打开失败: {e}"


@mcp.tool()
def take_screenshot(path: str = "screenshot.png") -> str:
    """截取全屏并保存为图片, 返回保存路径。

    参数:
      path: 保存路径, 默认当前目录 screenshot.png
    """
    if not HAS_PIL:
        return "错误: 未安装 Pillow, 无法截屏。"
    try:
        p = _path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        img = ImageGrab.grab()
        img.save(p)
        return f"截图已保存: {p}"
    except Exception as e:
        return f"截屏失败: {e}"


@mcp.tool()
def get_datetime() -> str:
    """获取当前日期时间与时区。"""
    now = datetime.now()
    tz = now.astimezone().tzinfo
    return (f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S %A')}\n"
            f"时区: {tz}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
