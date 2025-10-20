import subprocess
import os

venv_python = os.path.abspath(r".venv\Scripts\python.exe")
script_path = os.path.abspath("chat.py")

# Windows 下用 start 命令打开新控制台
subprocess.Popen(f'start cmd /k "{venv_python} {script_path}"', shell=True)