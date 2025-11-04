@echo off
setlocal enabledelayedexpansion

echo 检查 Python 是否安装...

:: 检查 Python 是否可用
python --version >nul 2>&1
if %errorlevel% == 0 (
    goto python_installed
)

python3 --version >nul 2>&1
if %errorlevel% == 0 (
    goto python_installed
)

echo 未检测到 Python，正在自动下载安装...

:: 使用稳定的 Python 版本
set "PYTHON_VERSION=3.13.5"
set "PYTHON_INSTALLER=python-installer.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.13.5/python-3.13.5-amd64.exe"

echo 正在下载 Python %PYTHON_VERSION%...
powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%' -UserAgent 'Mozilla/5.0'"

if not exist "%PYTHON_INSTALLER%" (
    echo Python 安装包下载失败，请检查网络连接。
    pause
    exit /b 1
)

echo 正在静默安装 Python...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=0
del "%PYTHON_INSTALLER%"

echo Python 安装完成，请重新启动命令行并再次运行此脚本。
pause
exit /b 0

:python_installed
echo Python 已安装，继续后续操作...

:: 创建虚拟环境
if not exist ".venv" (
    echo 正在创建虚拟环境...
    python -m venv .venv
) else (
    echo 虚拟环境已存在。
)

:: 激活虚拟环境
call .venv\Scripts\activate.bat

:: 升级 pip
echo 正在升级 pip...
python -m pip install --upgrade pip

:: 安装依赖
if exist requirements.txt (
    echo 正在安装依赖包...
    pip install -r requirements.txt
) else (
    echo requirements.txt 不存在，创建基础版本...
    echo requests > requirements.txt
    echo 正在安装基础依赖包...
    pip install requests
)

pause
endlocal