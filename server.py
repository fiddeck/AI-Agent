"""
MCP 服务器: AI-Agent 系统级工具集

通过 FastMCP(stdio) 暴露给 webui.py / chat.py 的工具:
  - run_python_code   : 在独立子进程中执行 Python 代码(带超时与输出上限)
  - run_shell_command : 执行 shell 命令(cmd, 带高危命令防护与超时)
  - list_files        : 列举目录/文件
  - read_file         : 读取文本文件(按字节上限, 自动识别 UTF-8/GBK)
  - write_file        : 写入文本文件
  - search_files      : 递归搜索文件
  - delete_file       : 删除文件/目录(需 confirm=True, 且拒绝关键目录)
  - get_system_info   : 系统信息(OS/CPU/内存/磁盘)
  - list_processes    : 进程列表
  - kill_process      : 结束进程(需 confirm=True)
  - get_clipboard     : 读取剪贴板
  - set_clipboard     : 写入剪贴板
  - open_url          : 默认浏览器打开网址
  - take_screenshot   : 全屏截图
  - get_datetime      : 当前日期时间

设计要点:
  * 代码/命令都在子进程中执行: 死循环或崩溃不会拖死 MCP 服务本身，且超时后可杀掉整棵进程树。
  * Windows 中文环境下 cmd 输出是 cp936，统一交给 agent_core.decode_process_output 解码。
  * 所有返回给模型的输出都做长度截断，防止上下文被一次性撑爆。
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import string
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent_core import (
    APP_NAME,
    ROOT,
    decode_process_output,
    mcp_python,
    truncate_text,
)

# ---------- 可选依赖探测 ----------
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:  # pragma: no cover - 缺依赖时降级
    HAS_PSUTIL = False

try:
    import win32clipboard
    import win32con
    HAS_PYWIN32 = True
except ImportError:  # pragma: no cover
    HAS_PYWIN32 = False

try:
    from PIL import ImageGrab
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

mcp = FastMCP(APP_NAME + "-System")

# 单次工具输出进入模型上下文的上限
OUTPUT_LIMIT = 12000
# 子进程创建标志: 不弹出控制台窗口
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# 子进程默认工作目录 = 项目根目录(与旧版 MCP cwd 一致)
_WORKDIR = str(ROOT)


# ---------- 通用辅助 ----------

def _path(p: str) -> Path:
    """展开环境变量/用户目录并解析为绝对路径。"""
    return Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()


def _truncate(text: str, limit: int = OUTPUT_LIMIT) -> str:
    return truncate_text(text, limit)


def _subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if extra:
        env.update(extra)
    return env


def _kill_process_tree(pid: int) -> None:
    """强制结束进程及其子进程(cmd 的子进程不会随父进程自动退出)。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
        return
    except Exception:
        pass
    try:
        os.kill(pid, 9)
    except Exception:
        pass


def _run_process(
    argv: list[str],
    *,
    timeout: int,
    cwd: str | None = None,
    input_bytes: bytes | None = None,
) -> tuple[int | None, str, str, bool]:
    """运行子进程并收集输出。

    输出写入临时文件而不是 PIPE: 即使子进程疯狂输出也不会把本进程内存吃满。
    返回 (退出码, stdout, stderr, 是否超时)。
    """
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                stdout=out_file,
                stderr=err_file,
                cwd=cwd or _WORKDIR,
                env=_subprocess_env(),
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001 - 交给调用方转成中文提示
            return None, "", f"无法启动进程: {exc}", False

        timed_out = False
        try:
            proc.communicate(input=input_bytes, timeout=max(1, int(timeout)))
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc.pid)
            try:
                proc.communicate(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        out_file.seek(0)
        err_file.seek(0)
        raw_out = out_file.read(OUTPUT_LIMIT * 4)
        raw_err = err_file.read(OUTPUT_LIMIT * 4)
        return proc.returncode, decode_process_output(raw_out), decode_process_output(raw_err), timed_out


# 高危命令模式: 匹配到且 confirm=False 时拒绝执行
_DANGEROUS_PATTERNS = [
    (r"\bformat\s+[a-zA-Z]:", "格式化磁盘"),
    (r"\b(rd|rmdir)\s+/s\b", "递归删除目录"),
    (r"\b(del|erase)\b[^\n]*\s/[sfq]\b", "强制/静默删除文件"),
    (r"\bshutdown\b|\blogoff\b", "关机/注销"),
    (r"\b(restart-computer|stop-computer)\b", "重启/关机"),
    (r"\bdiskpart\b", "磁盘分区"),
    (r"\breg\s+delete\b", "删除注册表"),
    (r"\bnet\s+(user|localgroup)\b", "用户/组管理"),
    (r"\bcipher\s+/w\b", "擦除磁盘"),
    (r"Remove-Item\b", "PowerShell 删除"),
    (r"\bClear-Content\b", "清空文件"),
    (r"\bFormat-Volume\b", "格式化卷"),
    (r"\bStop-Process\b", "结束进程"),
    (r"\btaskkill\s+/f\b", "强制结束进程(请用 kill_process 工具)"),
    (r"\bgit\s+clean\b", "清理未跟踪文件"),
    (r"\bgit\s+reset\s+--hard\b", "丢弃未提交修改"),
    (r"\bgit\s+push\b[^\n]*--force", "强制推送(可能覆盖远端历史)"),
    (r"powershell\s+-e(nc|ncoded)?\b|pwsh\s+-e(nc|ncoded)?\b", "编码/混淆的 PowerShell 命令"),
]
_DANGEROUS_RULES = [(re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in _DANGEROUS_PATTERNS]


def _dangerous_reason(command: str) -> str | None:
    for regex, reason in _DANGEROUS_RULES:
        if regex.search(command):
            return reason
    return None


# 不允许删除的关键目录(连同其上级判断)
def _protected_directories() -> list[Path]:
    candidates = [
        ROOT,
        Path.home(),
        Path(os.environ.get("WINDIR", r"C:\Windows")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramData", r"C:\ProgramData")),
        Path(os.environ.get("USERPROFILE", str(Path.home()))),
    ]
    home = Path.home()
    for name in ("Desktop", "Downloads", "Documents", "Pictures", "Videos", "Music"):
        candidates.append(home / name)
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if drive.exists():
            candidates.append(drive)
    result: list[Path] = []
    for item in candidates:
        try:
            result.append(item.resolve())
        except OSError:
            continue
    return result


def _deletion_block_reason(target: Path) -> str | None:
    """删除前的兜底保护: 关键目录本身、以及项目的上级目录都不允许删。"""
    normalized = os.path.normcase(str(target))
    for protected in _protected_directories():
        if normalized == os.path.normcase(str(protected)):
            return f"{protected} 是关键目录，拒绝删除"
    try:
        if target == ROOT or target in ROOT.parents:
            return "目标是项目目录(或其上级)，删除会破坏运行环境，拒绝执行"
    except OSError:
        pass
    if target == target.anchor or normalized.strip("\\/") in ("", "c:", "d:", "e:", "f:"):
        return "拒绝删除磁盘根目录"
    return None


# ---------- 工具: 代码/命令执行 ----------

@mcp.tool()
def run_python_code(code: str, timeout: int = 120) -> str:
    """在独立 Python 子进程中执行代码，返回 print 的内容、错误输出与退出码。

    代码运行在用户电脑上(工作目录为项目根目录)，请谨慎。使用 print 输出你希望看到的结果；
    死循环等超时会被强制终止，不会拖死服务。

    参数:
      code: 要执行的 Python 代码
      timeout: 超时秒数，默认 120
    """
    if not str(code or "").strip():
        return "错误: 代码为空。"
    exit_code, out, err, timed_out = _run_process(
        [mcp_python(), "-"],
        timeout=timeout,
        input_bytes=str(code).encode("utf-8"),
    )
    if timed_out:
        body = (out or "") + (f"\n[stderr]\n{err}" if err else "")
        return _truncate(body) + f"\n[超时] 代码执行超过 {timeout} 秒，已强制终止(含子进程)。"
    if exit_code is None:
        return err or "执行失败。"
    return _format_result(exit_code, out, err)


@mcp.tool()
def run_shell_command(command: str, timeout: int = 60, confirm: bool = False, cwd: str = "") -> str:
    """在 Windows 上执行 shell 命令 (cmd)。返回 stdout、stderr 与退出码。

    用于安装程序、运行脚本、网络请求、系统管理等 Python 不好直接做的事。
    高危命令 (格式化磁盘、递归删除、关机、强制结束进程、git 破坏性操作等)
    必须 confirm=True 才会执行。

    参数:
      command: 要执行的命令，使用 Windows cmd 语法
      timeout: 超时秒数，默认 60
      confirm: 高危命令需为 True 才会执行
      cwd: 工作目录，留空使用项目根目录
    """
    command = str(command or "").strip()
    if not command:
        return "错误: 命令为空。"
    reason = _dangerous_reason(command)
    if reason and not confirm:
        return (
            f"拒绝执行: 该命令属于高危操作({reason})。\n"
            "如需执行，请先向用户说明影响并获得明确同意，再以 confirm=True 重试。\n"
            f"命令: {command}"
        )
    workdir = str(_path(cwd)) if cwd else _WORKDIR
    if not Path(workdir).is_dir():
        return f"错误: 工作目录不存在 {workdir}"
    exit_code, out, err, timed_out = _run_process(
        ["cmd", "/c", command],
        timeout=timeout,
        cwd=workdir,
    )
    if timed_out:
        body = _format_result(exit_code, out, err, include_code=False)
        return _truncate(body) + f"\n[超时] 命令执行超过 {timeout} 秒，已强制终止(含子进程)。"
    if exit_code is None:
        return err or "执行失败。"
    return _format_result(exit_code, out, err)


def _format_result(exit_code: int | None, stdout: str, stderr: str, *, include_code: bool = True) -> str:
    stdout = _truncate(stdout.rstrip())
    stderr = _truncate(stderr.rstrip())
    lines: list[str] = []
    if include_code:
        lines.append(f"[退出码 {exit_code}]")
    if stdout:
        lines.append(stdout)
    if stderr:
        lines.append(f"[stderr]\n{stderr}")
    if not stdout and not stderr:
        lines.append("(无输出)")
    return "\n".join(lines)


# ---------- 工具: 文件系统 ----------

@mcp.tool()
def list_files(path: str = ".", pattern: str = "*", recursive: bool = False, max_results: int = 100) -> str:
    """列举目录中的文件和子目录。

    参数:
      path: 目录路径，默认项目根目录
      pattern: 文件名匹配模式，支持通配符，如 *.py、*data*
      recursive: 是否递归子目录
      max_results: 最多返回条数，默认 100 (上限 1000)
    """
    root = _path(path)
    if not root.is_dir():
        return f"错误: 目录不存在 {root}"
    max_results = max(1, min(int(max_results or 100), 1000))
    try:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        items = []
        for item in sorted(iterator, key=lambda p: str(p).lower()):
            kind = "[DIR]" if item.is_dir() else "     "
            items.append(f"{kind} {item}")
            if len(items) >= max_results:
                items.append(f"...(已达上限 {max_results} 条)")
                break
        if not items:
            return f"未找到匹配 '{pattern}' 的内容: {root}"
        return "\n".join(items)
    except Exception as exc:  # noqa: BLE001
        return f"列举失败: {exc}"


@mcp.tool()
def read_file(path: str, max_bytes: int = 20000, offset: int = 0) -> str:
    """读取文本文件内容, 最多读取 max_bytes 字节 (默认 20KB), 超出部分截断并提示。

    自动识别 UTF-8 / GBK 编码；可用 offset 跳过开头若干字节以便分段读取大文件。

    参数:
      path: 文件路径
      max_bytes: 读取上限字节数 (上限 500000)
      offset: 起始字节偏移，默认 0
    """
    p = _path(path)
    if not p.is_file():
        return f"错误: 文件不存在 {p}"
    max_bytes = max(1, min(int(max_bytes or 20000), 500_000))
    offset = max(0, int(offset or 0))
    try:
        size = p.stat().st_size
        with open(p, "rb") as handle:
            if offset:
                handle.seek(offset)
            raw = handle.read(max_bytes + 1)
        truncated = len(raw) > max_bytes
        raw = raw[:max_bytes]
        content = decode_process_output(raw)
        tail = ""
        if offset or truncated:
            tail = (
                f"\n...[文件共 {size} 字节，已读取 {offset}~{offset + len(raw)} 字节"
                f"{'，后续内容被截断' if truncated else ''}]"
            )
        else:
            tail = f"\n[文件共 {size} 字节]"
        return content + tail
    except Exception as exc:  # noqa: BLE001
        return f"读取失败: {exc}"


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
        with open(p, mode, encoding="utf-8", newline="") as handle:
            handle.write(content or "")
        return f"已{'追加' if append else '写入'} {p} ({len(content or '')} 字符)"
    except Exception as exc:  # noqa: BLE001
        return f"写入失败: {exc}"


@mcp.tool()
def search_files(path: str = ".", pattern: str = "*", max_results: int = 100) -> str:
    """递归搜索匹配 pattern 的文件。

    参数:
      path: 搜索起点目录
      pattern: 通配符模式, 如 *.py、**/*.txt、*report*
      max_results: 最多返回条数, 默认 100 (上限 1000)
    """
    root = _path(path)
    if not root.is_dir():
        return f"错误: 目录不存在 {root}"
    max_results = max(1, min(int(max_results or 100), 1000))
    try:
        items = []
        for p in sorted(root.rglob(pattern), key=lambda x: str(x).lower()):
            if p.is_file():
                items.append(str(p))
                if len(items) >= max_results:
                    items.append(f"...(已达上限 {max_results} 条)")
                    break
        if not items:
            return f"未找到匹配 '{pattern}' 的文件: {root}"
        return "\n".join(items)
    except Exception as exc:  # noqa: BLE001
        return f"搜索失败: {exc}"


@mcp.tool()
def delete_file(path: str, recursive: bool = False, confirm: bool = False) -> str:
    """删除文件或目录。任何删除都必须 confirm=True 才会执行。

    关键目录(系统目录、用户主目录、桌面/下载、磁盘根目录、项目目录及其上级)
    即使 confirm=True 也会被拒绝，避免误删导致系统或项目损坏。

    参数:
      path: 目标路径
      recursive: 删除目录时需要 True
      confirm: 确认删除, 必须为 True
    """
    p = _path(path)
    if not p.exists():
        return f"错误: 路径不存在 {p}"
    block = _deletion_block_reason(p)
    if block:
        return f"拒绝删除: {block}"
    if not confirm:
        return (
            f"拒绝删除: 需要确认。请向用户说明将删除 {p}，"
            "获得明确同意后以 confirm=True 重试。"
        )
    try:
        if p.is_dir():
            if not recursive:
                return f"拒绝删除: {p} 是目录，删除目录需要 recursive=True。"
            shutil.rmtree(p)
            return f"已删除目录 {p}"
        os.remove(p)
        return f"已删除文件 {p}"
    except Exception as exc:  # noqa: BLE001
        return f"删除失败: {exc}"


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
    except Exception:  # noqa: BLE001
        return "内存: 无法获取"


def _list_drives() -> list[str]:
    """返回 Windows 上存在的盘符列表, 如 [C:\\, D:\\]。"""
    return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]


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
            except Exception:  # noqa: BLE001
                lines.append(f"磁盘 {drive}: 无法获取")
        lines.append(f"Python: {sys.version.split()[0]} ({sys.executable})")
        lines.append(f"psutil: {'可用' if HAS_PSUTIL else '未安装(进程工具降级为 tasklist/taskkill)'}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"获取系统信息失败: {exc}"


@mcp.tool()
def list_processes(name_filter: str = "", max_results: int = 50) -> str:
    """列出正在运行的进程。

    参数:
      name_filter: 按进程名筛选 (如 python、chrome、code), 留空列出全部
      max_results: 最多返回条数, 默认 50
    """
    max_results = max(1, min(int(max_results or 50), 500))
    try:
        rows: list[str] = []
        if HAS_PSUTIL:
            for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    pinfo = proc.info
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                name = pinfo.get("name") or ""
                if name_filter and name_filter.lower() not in name.lower():
                    continue
                memory = pinfo.get("memory_info")
                size = f"{memory.rss / 1024 ** 2:8.1f} MB" if memory else ""
                rows.append(f"{pinfo['pid']:<8} {name:<28} {size}")
                if len(rows) >= max_results:
                    rows.append(f"...(已达上限 {max_results} 条)")
                    break
            if not rows:
                return f"没有匹配 '{name_filter}' 的进程"
            return "PID      名称                         内存\n" + "\n".join(rows)
        # 回退: tasklist
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=30, creationflags=_CREATE_NO_WINDOW,
        )
        text = decode_process_output(result.stdout)
        for line in text.splitlines():
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
    except Exception as exc:  # noqa: BLE001
        return f"获取进程列表失败: {exc}"


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
        return f"拒绝结束{target}: 需要确认。请向用户说明后以 confirm=True 重试。"
    try:
        if HAS_PSUTIL:
            killed: list[str] = []
            targets: list[psutil.Process] = []
            if pid:
                targets.append(psutil.Process(pid))
            if name:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        if (proc.info.get("name") or "").lower() == name.lower():
                            targets.append(proc)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            for proc in targets:
                try:
                    label = f"PID {proc.pid} ({proc.name()})"
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    killed.append(label)
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    killed.append(f"{proc.pid}: {exc}")
            return f"已结束: {', '.join(killed) if killed else '未找到目标进程'}"
        # 回退: taskkill
        if pid:
            result = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                    capture_output=True, creationflags=_CREATE_NO_WINDOW)
        else:
            result = subprocess.run(["taskkill", "/IM", name, "/F"],
                                    capture_output=True, creationflags=_CREATE_NO_WINDOW)
        output = decode_process_output((result.stdout or b"").strip() or (result.stderr or b"").strip())
        return f"退出码 {result.returncode}: {output}"
    except Exception as exc:  # noqa: BLE001
        return f"结束进程失败: {exc}"


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
        return _truncate(str(data)) if data else "(剪贴板为空)"
    except Exception as exc:  # noqa: BLE001
        return f"读取剪贴板失败: {exc}"


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
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text or "")
        finally:
            win32clipboard.CloseClipboard()
        return f"已写入剪贴板 ({len(text or '')} 字符)"
    except Exception as exc:  # noqa: BLE001
        return f"写入剪贴板失败: {exc}"


@mcp.tool()
def open_url(url: str) -> str:
    """在默认浏览器中打开网址。

    参数:
      url: 网址, 必须以 http:// 或 https:// 开头
    """
    url = str(url or "").strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return f"拒绝打开: {url} 不是有效的 http(s) 网址。"
    try:
        import webbrowser
        webbrowser.open(url)
        return f"已在默认浏览器打开: {url}"
    except Exception as exc:  # noqa: BLE001
        return f"打开失败: {exc}"


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
        return f"截图已保存: {p} ({img.width}x{img.height})"
    except Exception as exc:  # noqa: BLE001
        return f"截屏失败: {exc}"


@mcp.tool()
def get_datetime() -> str:
    """获取当前日期时间与时区。"""
    now = datetime.now()
    tz = now.astimezone().tzinfo
    return (f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S %A')}\n"
            f"时区: {tz}\n"
            f"ISO: {now.astimezone().isoformat(timespec='seconds')}")


def main() -> None:
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - stderr 会被 webui 写入日志
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
