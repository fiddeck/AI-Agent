"""server.py (MCP 工具) 的集成测试: 编码、超时、文件操作、删除保护。"""

from __future__ import annotations

from pathlib import Path

import agent_core as core
import server


def test_dangerous_command_detection():
    dangerous = [
        "del /f /q important.txt",
        "rmdir /s /q build",
        "format D:",
        "shutdown /s /t 0",
        "diskpart",
        "taskkill /F /IM chrome.exe",
        "git reset --hard HEAD",
        "powershell -enc ZQBjAGgAbwA=",
        "Remove-Item -Recurse C:\\temp",
        "Stop-Process -Name notepad",
    ]
    for command in dangerous:
        assert server._dangerous_reason(command), command

    for command in ["dir", "echo hi", "python -m pip list", "git status", "git push origin main"]:
        assert server._dangerous_reason(command) is None, command


def test_run_shell_command_rejects_unconfirmed_danger():
    result = server.run_shell_command("del /f /q nothing.txt")
    assert "拒绝执行" in result
    assert "confirm=True" in result


def test_shell_output_is_decoded_as_gbk():
    result = server.run_shell_command("echo 中文测试")
    assert "中文测试" in result
    assert "[退出码 0]" in result


def test_shell_reports_exit_code_and_stderr():
    result = server.run_shell_command("echo out & echo err 1>&2 & exit /b 3")
    assert "[退出码 3]" in result
    assert "out" in result
    assert "err" in result


def test_shell_timeout_kills_process_tree():
    result = server.run_shell_command("ping -n 10 127.0.0.1 >nul", timeout=1)
    assert "超时" in result
    assert "已强制终止" in result


def test_run_python_code_returns_printed_output():
    result = server.run_python_code("print(6 * 7)")
    assert "[退出码 0]" in result
    assert "42" in result


def test_run_python_code_uses_venv_interpreter():
    code = "import sys; print(sys.prefix); print(sys.base_prefix)"
    result = server.run_python_code(code)
    prefix, base = [line for line in result.splitlines() if line and not line.startswith("[")]
    assert "Scripts" not in prefix  # sys.prefix 是目录, 不含 Scripts
    assert base.lower() != prefix.lower(), "应运行在虚拟环境而不是 base 解释器"


def test_run_python_code_timeout():
    result = server.run_python_code("import time; time.sleep(30)", timeout=1)
    assert "超时" in result


def test_run_python_code_captures_traceback():
    result = server.run_python_code("raise ValueError('boom')")
    assert "ValueError" in result
    assert "boom" in result


def test_file_write_read_roundtrip(tmp_path):
    target = tmp_path / "子目录" / "note.txt"
    message = server.write_file(str(target), "第一行\n第二行\n")
    assert "已写入" in message
    assert target.read_text(encoding="utf-8") == "第一行\n第二行\n"

    read = server.read_file(str(target))
    assert "第一行" in read
    assert "第二行" in read
    assert "文件共" in read

    server.write_file(str(target), "追加", append=True)
    assert target.read_text(encoding="utf-8").endswith("追加")


def test_read_file_reports_truncation_by_bytes(tmp_path):
    target = tmp_path / "big.txt"
    target.write_text("汉" * 1000, encoding="utf-8")
    result = server.read_file(str(target), max_bytes=30)
    assert "仅显示前" not in result or "截断" in result
    assert "已读取 0~30 字节" in result


def test_read_file_offset(tmp_path):
    target = tmp_path / "abc.txt"
    target.write_text("ABCDEFGHIJ", encoding="utf-8")
    result = server.read_file(str(target), max_bytes=3, offset=5)
    assert result.startswith("FGH")


def test_read_missing_file(tmp_path):
    assert "不存在" in server.read_file(str(tmp_path / "nope.txt"))


def test_list_and_search_files(tmp_path):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.txt").write_text("", encoding="utf-8")
    listing = server.list_files(str(tmp_path), "*.py")
    assert "a.py" in listing and "b.txt" not in listing

    found = server.search_files(str(tmp_path), "*.txt")
    assert "b.txt" in found


def test_delete_requires_confirm_and_guard(tmp_path):
    victim = tmp_path / "x.txt"
    victim.write_text("x", encoding="utf-8")

    refused = server.delete_file(str(victim))
    assert "拒绝删除" in refused and victim.exists()

    deleted = server.delete_file(str(victim), confirm=True)
    assert "已删除" in deleted and not victim.exists()

    project = server.delete_file(str(core.ROOT), recursive=True, confirm=True)
    assert "拒绝删除" in project and core.ROOT.exists()

    drive = server.delete_file(str(core.ROOT.anchor), recursive=True, confirm=True)
    assert "拒绝删除" in drive

    home = server.delete_file(str(Path.home()), recursive=True, confirm=True)
    assert "拒绝删除" in home


def test_get_datetime_and_system_info():
    now = server.get_datetime()
    assert "当前时间" in now and "时区" in now
    info = server.get_system_info()
    assert "操作系统" in info and "CPU" in info
