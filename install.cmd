@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "REPOSITORY=https://github.com/yuaiccc/HDU-xiaoyuananquantong/archive/refs/heads/main.zip"
set "INSTALL_DIR=%HDU_SAFETY_DIR%"
if not defined INSTALL_DIR set "INSTALL_DIR=%LOCALAPPDATA%\hdu-safety-answer"
set "PORT=%PORT%"
if not defined PORT set "PORT=8090"
set "TMP_DIR=%TEMP%\hdu-safety-answer-%RANDOM%-%RANDOM%"

where curl.exe >nul 2>&1
if errorlevel 1 (
    set "ERROR_MESSAGE=未找到 Windows 自带的 curl.exe，请更新 Windows 10/11。"
    goto :fail
)
where tar.exe >nul 2>&1
if errorlevel 1 (
    set "ERROR_MESSAGE=未找到 Windows 自带的 tar.exe，请更新 Windows 10/11。"
    goto :fail
)

if exist "%INSTALL_DIR%" (
    for %%F in (server.py xy_auto.py xy_bank.json index.html) do (
        if not exist "%INSTALL_DIR%\%%F" (
            set "ERROR_MESSAGE=安装目录不完整：缺少 %%F"
            goto :fail
        )
    )
    echo 使用已有安装：%INSTALL_DIR%
) else (
    echo 正在下载项目代码...
    mkdir "%TMP_DIR%" >nul 2>&1
    curl.exe -fL --retry 3 --connect-timeout 15 -o "%TMP_DIR%\source.zip" "%REPOSITORY%"
    if errorlevel 1 (
        set "ERROR_MESSAGE=项目下载失败，请检查网络。"
        goto :fail
    )
    tar.exe -xf "%TMP_DIR%\source.zip" -C "%TMP_DIR%"
    if errorlevel 1 (
        set "ERROR_MESSAGE=项目压缩包解压失败。"
        goto :fail
    )
    if not exist "%TMP_DIR%\HDU-xiaoyuananquantong-main\server.py" (
        set "ERROR_MESSAGE=下载内容不完整。"
        goto :fail
    )
    mkdir "%INSTALL_DIR%" >nul 2>&1
    xcopy "%TMP_DIR%\HDU-xiaoyuananquantong-main\*" "%INSTALL_DIR%\" /E /I /Y /Q >nul
    if errorlevel 1 (
        set "ERROR_MESSAGE=项目文件复制失败。"
        goto :fail
    )
    echo 项目已下载到：%INSTALL_DIR%
)

set "PY_KIND="
where py >nul 2>&1
if not errorlevel 1 set "PY_KIND=py"
if not defined PY_KIND (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PY_KIND=python"
        set "PYTHON_EXE=python"
    )
)

if not defined PY_KIND (
    where winget >nul 2>&1
    if errorlevel 1 (
        set "ERROR_MESSAGE=未找到 Python，也未找到 winget；请先安装 Python 3。"
        goto :fail
    )
    echo 未找到 Python，正在尝试通过 winget 安装 Python 3...
    winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        set "ERROR_MESSAGE=Python 自动安装失败，请先安装 Python 3 后重试。"
        goto :fail
    )
    where py >nul 2>&1
    if not errorlevel 1 set "PY_KIND=py"
    if not defined PY_KIND (
        where python >nul 2>&1
        if not errorlevel 1 (
            set "PY_KIND=python"
            set "PYTHON_EXE=python"
        )
    )
    if not defined PY_KIND (
        set "ERROR_MESSAGE=Python 已安装，但当前窗口尚未找到它；请重新打开 CMD 后重试。"
        goto :fail
    )
)

echo 正在校验 Python 文件和题库...
if "%PY_KIND%"=="py" (
    py -3 -m py_compile "%INSTALL_DIR%\server.py" "%INSTALL_DIR%\xy_auto.py"
    if errorlevel 1 (
        set "ERROR_MESSAGE=Python 文件编译失败。"
        goto :fail
    )
    py -3 -c "import json; d=json.load(open(r'%INSTALL_DIR%\xy_bank.json', encoding='utf-8')); assert isinstance(d, (dict, list)) and d"
) else (
    "%PYTHON_EXE%" -m py_compile "%INSTALL_DIR%\server.py" "%INSTALL_DIR%\xy_auto.py"
    if errorlevel 1 (
        set "ERROR_MESSAGE=Python 文件编译失败。"
        goto :fail
    )
    "%PYTHON_EXE%" -c "import json; d=json.load(open(r'%INSTALL_DIR%\xy_bank.json', encoding='utf-8')); assert isinstance(d, (dict, list)) and d"
)
if errorlevel 1 (
    set "ERROR_MESSAGE=题库不是有效的非空 JSON。"
    goto :fail
)

echo 安装完成：%INSTALL_DIR%
echo 服务地址：http://127.0.0.1:%PORT%
start "" "http://127.0.0.1:%PORT%"
set "HOST=127.0.0.1"
cd /d "%INSTALL_DIR%"
set "PORT=%PORT%"
if "%PY_KIND%"=="py" (
    py -3 server.py
) else (
    "%PYTHON_EXE%" server.py
)
exit /b %errorlevel%

:fail
echo 安装失败：%ERROR_MESSAGE%
exit /b 1
