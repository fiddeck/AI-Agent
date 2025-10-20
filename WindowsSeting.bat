@echo off
setlocal

echo 检查 Python 是否安装...
python --version >nul 2>&1
if errorlevel 1 (
    echo 未检测到 Python，正在自动下载安装...
    set "PYTHON_INSTALLER=python-installer.exe"
    set "PYTHON_URL=https://www.python.org/ftp/python/3.13.5/python-3.13.0-amd64.exe"
    powershell -Command "Invoke-WebRequest -Uri %PYTHON_URL% -OutFile %PYTHON_INSTALLER%"
    if not exist %PYTHON_INSTALLER% (
        echo Python 安装包下载失败，请检查网络连接。
        pause
        exit /b 1
    )
    echo 正在静默安装 Python...
    start /wait "" %PYTHON_INSTALLER% /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    del %PYTHON_INSTALLER%
    echo Python 安装完成，正在刷新环境变量...
    setx PATH "%PATH%;C:\Program Files\Python313\Scripts;C:\Program Files\Python313\"
    echo 请关闭并重新打开命令行窗口以应用新的 PATH 设置。
    pause
    exit /b 0
)

echo Python 已安装，继续后续操作...

:: 创建虚拟环境
python -m venv venv

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 升级 pip
python -m pip install --upgrade pip

:: 安装依赖
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo requirements.txt not found, creating basic one...
    echo requests > requirements.txt
    pip install requests
)

:: 运行主程序
if exist main.py (
    python main.py
) else (
    echo main.py not found
)

pause
endlocal