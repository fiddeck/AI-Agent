"""在新控制台窗口里启动 chat.py（供快捷方式或旧启动方式调用）。

路径全部基于本文件位置解析，因此从任意工作目录双击/调用都能正确找到 .venv 与 chat.py。
直接命令行使用请优先运行 `start.bat` 或 `.venv\\Scripts\\python chat.py`。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SCRIPT = ROOT / "chat.py"


def main() -> int:
    if not SCRIPT.is_file():
        print(f"找不到 {SCRIPT}")
        return 1
    python = str(PYTHON if PYTHON.is_file() else Path(sys.executable))
    if not PYTHON.is_file():
        print("警告: 未找到 .venv，改用当前 Python 解释器。建议先运行 修复环境.bat。")

    command = f'start "" "{python}" "{SCRIPT}"'
    try:
        subprocess.run(command, shell=True, cwd=str(ROOT), check=False)
    except Exception as exc:  # noqa: BLE001
        print(f"启动失败: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
