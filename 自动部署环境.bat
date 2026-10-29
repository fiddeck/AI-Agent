@echo off
setlocal
cd /d "%~dp0"
chcp 936 >nul 2>&1
title AI-Agent 环境自动部署

set "PY_VER=3.13.15"
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-amd64.exe"
set "INSTALLER=%TEMP%\ai-agent-python-%PY_VER%-amd64.exe"
set "VENV_PY=.venv\Scripts\python.exe"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

echo ============================================================
echo   AI-Agent 环境自动部署
echo ============================================================
echo.

if not exist "pyproject.toml" goto :err_project
if not exist "webui.py" goto :err_project
echo [1/6] 项目目录: "%CD%"

if defined PROCESSOR_ARCHITEW6432 goto :arch_checked
if /I "%PROCESSOR_ARCHITECTURE%"=="x86" goto :err_32bit
:arch_checked
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" echo [提示] 检测到 ARM64 Windows，桌面端为 win-x64，将以模拟方式运行。
echo.

if not exist ".venv" goto :venv_checked
if not exist "%VENV_PY%" goto :remove_venv
"%VENV_PY%" -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if errorlevel 1 goto :remove_venv
goto :venv_checked

:remove_venv
echo [2/6] 发现不可用或版本不符的 .venv，正在删除重建...
rmdir /s /q ".venv"
if exist ".venv" goto :err_venv_locked

:venv_checked
echo.

where uv >nul 2>&1
if errorlevel 1 goto :pip_path

echo [3/6] 检测到 uv，执行 uv sync（会自动准备 Python 3.13 和依赖）...
echo       首次执行可能需要 5-20 分钟，请不要关闭窗口。
uv sync --python 3.13
if errorlevel 1 goto :uv_failed
if not exist "%VENV_PY%" goto :err_uv_missing_venv
"%VENV_PY%" -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if errorlevel 1 goto :err_uv_python
goto :uv_ready

:uv_ready
"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo 正在为虚拟环境补充 pip...
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 echo [警告] 补充 pip 失败，Agent 将无法自行安装额外的 Python 包。
)
goto :verify

:uv_failed
echo [警告] uv sync 失败，回退到 venv + pip 方式重试...
echo.
if not exist "%VENV_PY%" goto :pip_path
"%VENV_PY%" -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if errorlevel 1 goto :pip_path
goto :venv_ready_pip

:pip_path
if not exist "%VENV_PY%" goto :find_python_path
"%VENV_PY%" -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if errorlevel 1 goto :find_python_path
goto :venv_ready_pip

:find_python_path
echo [3/6] 查找 Python 3.13（64 位）...
call :find_python
if defined PYTHON_CMD goto :install_ready
goto :install_python

:install_python
echo 未找到可用的 Python 3.13，准备下载官方安装包...
echo 下载地址: %PY_URL%
where curl.exe >nul 2>&1
if errorlevel 1 goto :download_ps
curl.exe -fL --retry 3 --connect-timeout 20 -o "%INSTALLER%" "%PY_URL%"
if errorlevel 1 goto :err_download
goto :install_runner

:download_ps
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL%' -OutFile '%INSTALLER%' } catch { exit 1 }"
if errorlevel 1 goto :err_download

:install_runner
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Unblock-File -LiteralPath '%INSTALLER%' -ErrorAction SilentlyContinue } catch { }" >nul 2>&1
for %%A in ("%INSTALLER%") do set "INSTALLER_SIZE=%%~zA"
if not defined INSTALLER_SIZE goto :err_download
if %INSTALLER_SIZE% LSS 1000000 goto :err_download
echo 正在为当前用户静默安装 Python %PY_VER%（无需管理员权限）...
"%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
set "PY_RC=%ERRORLEVEL%"
del "%INSTALLER%" >nul 2>&1
if not "%PY_RC%"=="0" if not "%PY_RC%"=="3010" goto :err_python_install

if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python313;%LocalAppData%\Programs\Python\Python313\Scripts;%PATH%"
call :find_python
if not defined PYTHON_CMD goto :err_reopen
echo Python 安装完成。
echo.

:install_ready
echo [4/6] 准备虚拟环境...
if exist "%VENV_PY%" goto :venv_ready
if exist ".venv" rmdir /s /q ".venv"
if exist ".venv" goto :err_venv_locked
%PYTHON_CMD% -m venv ".venv"
if errorlevel 1 goto :err_venv_create
if not exist "%VENV_PY%" goto :err_venv_create

:venv_ready
"%VENV_PY%" -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if errorlevel 1 goto :rebuild_venv
goto :venv_ready_pip

:rebuild_venv
echo [警告] 现有 .venv 不可用，正在重新创建...
rmdir /s /q ".venv"
if exist ".venv" goto :err_venv_locked
%PYTHON_CMD% -m venv ".venv"
if errorlevel 1 goto :err_venv_create
if not exist "%VENV_PY%" goto :err_venv_create
"%VENV_PY%" -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if errorlevel 1 goto :err_venv_broken

:venv_ready_pip
"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo 虚拟环境缺少 pip，正在安装...
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 goto :err_pip
)
echo [5/6] 升级 pip 并安装项目依赖...
echo       首次执行可能需要 5-20 分钟，依赖包含 torch 等，请预留 5GB 以上磁盘空间。
"%VENV_PY%" -m pip install --upgrade pip --disable-pip-version-check
if errorlevel 1 echo [警告] pip 升级失败，继续尝试安装依赖...
"%VENV_PY%" -m pip install -e . -i "%PIP_INDEX%" --retries 3 --timeout 60 --disable-pip-version-check
if errorlevel 1 goto :pip_retry
goto :verify

:pip_retry
echo [警告] 使用清华镜像安装失败，改用默认 PyPI 重试...
"%VENV_PY%" -m pip install -e . --retries 3 --timeout 60 --disable-pip-version-check
if errorlevel 1 goto :err_pip

:verify
echo [6/6] 验证关键依赖...
"%VENV_PY%" -c "import sys; print('Python', sys.version.split()[0])"
if errorlevel 1 goto :err_verify
"%VENV_PY%" -c "import fastapi, uvicorn, websockets, mcp, openai, psutil"
if errorlevel 1 goto :err_verify
"%VENV_PY%" -c "import agent_core, server, webui_page, chat"
if errorlevel 1 goto :err_verify
"%VENV_PY%" -c "import bs4" >nul 2>&1
if errorlevel 1 echo [提示] 未安装 beautifulsoup4，Agent 需要抓取网页时会按需安装。

if not exist "dist\AI-Agent-GUI\AI-Agent-GUI.exe" goto :done
echo 正在更新桌面快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$dir = (Get-Location).Path; $exe = Join-Path $dir 'dist\AI-Agent-GUI\AI-Agent-GUI.exe'; $lnk = Get-ChildItem -LiteralPath $dir -Filter 'AI-Agent *.lnk' -ErrorAction SilentlyContinue | Select-Object -First 1; if ($null -eq $lnk) { $lnkPath = Join-Path $dir 'AI-Agent Desktop.lnk' } else { $lnkPath = $lnk.FullName }; $shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut($lnkPath); $shortcut.TargetPath = $exe; $shortcut.WorkingDirectory = Split-Path -Parent $exe; $shortcut.IconLocation = $exe + ',0'; $shortcut.Save(); Write-Host ('Shortcut updated: ' + $lnkPath)"
if errorlevel 1 echo [警告] 快捷方式更新失败，可直接运行 webui.bat。

:done
echo.
echo ============================================================
echo   环境部署完成
echo ============================================================
echo   下一步:
echo     1) 配置 API Key（二选一）:
echo          setx OPENAI_API_KEY "sk-..."
echo          或打开界面后在 设置 中填写
echo     2) 网页版: 双击 webui.bat
echo     3) 桌面版: 双击项目根目录的 AI-Agent 快捷方式
echo     4) 命令行: start.bat
echo.
if defined OPENAI_API_KEY (echo [提示] 已检测到环境变量 OPENAI_API_KEY。) else (echo [提示] 尚未检测到 OPENAI_API_KEY。)
pause
exit /b 0

:find_python
set "PYTHON_CMD="
py -3.13 -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.13"
if defined PYTHON_CMD goto :eof

python -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"
if defined PYTHON_CMD goto :eof

python3 -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python3"
if defined PYTHON_CMD goto :eof

if not exist "%LocalAppData%\Programs\Python\Python313\python.exe" goto :fp_programfiles
set PYTHON_CMD="%LocalAppData%\Programs\Python\Python313\python.exe"
%PYTHON_CMD% -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if not errorlevel 1 goto :eof
set "PYTHON_CMD="

:fp_programfiles
if not exist "%ProgramFiles%\Python313\python.exe" goto :fp_done
set PYTHON_CMD="%ProgramFiles%\Python313\python.exe"
%PYTHON_CMD% -c "import sys, platform; raise SystemExit(0 if sys.version_info[:2] == (3, 13) and platform.architecture()[0] == '64bit' else 1)" >nul 2>&1
if not errorlevel 1 goto :eof
set "PYTHON_CMD="

:fp_done
goto :eof

:err_project
echo [错误] 请在项目根目录运行本脚本（需要 pyproject.toml 和 webui.py）。
goto :fail

:err_32bit
echo [错误] 检测到 32 位 Windows，本项目依赖仅支持 64 位。
goto :fail

:err_venv_locked
echo [错误] 无法删除 .venv，可能桌面端或后端仍在运行。请关闭后重试。
goto :fail

:err_uv_missing_venv
echo [错误] uv sync 完成，但未找到 .venv\Scripts\python.exe。
goto :fail

:err_uv_python
echo [错误] uv sync 使用的 Python 不是 3.13（64 位），请检查 .python-version 或 uv 配置。
goto :fail

:err_download
echo [错误] Python 安装包下载失败，请检查网络或代理。
echo        也可手动安装 Python 3.13（64 位）后重新运行本脚本。
if exist "%INSTALLER%" del "%INSTALLER%" >nul 2>&1
goto :fail

:err_python_install
echo [错误] Python 安装失败，退出码 %PY_RC%。
goto :fail

:err_reopen
echo [错误] Python 已安装，但当前窗口无法定位新解释器。
echo        请关闭本窗口，重新打开后再次运行本脚本。
goto :fail

:err_venv_create
echo [错误] 创建虚拟环境失败。
goto :fail

:err_venv_broken
echo [错误] 虚拟环境创建后仍不可用。
goto :fail

:err_pip
echo [错误] 依赖安装失败，请检查网络、代理或磁盘空间。
echo        也可安装 uv 后执行: uv sync
goto :fail

:err_verify
echo [错误] 依赖验证失败，请查看上方报错。
goto :fail

:fail
echo.
echo 环境部署未完成，请根据上面的提示处理后重试。
pause
exit /b 1
