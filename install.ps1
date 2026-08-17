[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$Repository = "",
    [int]$Port = 0,
    [switch]$InstallOnly,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw "安装失败：$Message"
}

try {
    if ([string]::IsNullOrWhiteSpace($Repository)) {
        $Repository = if ($env:HDU_SAFETY_REPOSITORY) {
            $env:HDU_SAFETY_REPOSITORY
        } else {
            "https://github.com/yuaiccc/HDU-xiaoyuananquantong.git"
        }
    }

    if ([string]::IsNullOrWhiteSpace($InstallDir)) {
        $InstallDir = if ($env:HDU_SAFETY_DIR) {
            $env:HDU_SAFETY_DIR
        } elseif ($env:LOCALAPPDATA) {
            Join-Path $env:LOCALAPPDATA "hdu-safety-answer"
        } else {
            Join-Path $HOME ".local\share\hdu-safety-answer"
        }
    }
    $InstallDir = [Environment]::ExpandEnvironmentVariables($InstallDir)
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)

    if ($Port -eq 0) {
        $Port = if ($env:PORT) { [int]$env:PORT } else { 8090 }
    }
    if ($Port -lt 1 -or $Port -gt 65535) {
        Fail "PORT 必须是 1 到 65535 之间的数字"
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Fail "未找到 Git，请先安装 Git for Windows"
    }

    $python = Get-Command py -ErrorAction SilentlyContinue
    $pythonArgs = @()
    if ($python) {
        $pythonArgs = @("-3")
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            Fail "未找到 Python，请先安装 Python 3"
        }
    }

    if (Test-Path -LiteralPath $InstallDir) {
        if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) {
            Fail "安装位置已存在且不是目录：$InstallDir"
        }
        foreach ($RequiredFile in @("server.py", "xy_auto.py", "xy_bank.json", "index.html")) {
            if (-not (Test-Path -LiteralPath (Join-Path $InstallDir $RequiredFile) -PathType Leaf)) {
                Fail "安装目录不完整：缺少 $RequiredFile"
            }
        }
        Write-Host "使用已有安装：$InstallDir"
    } else {
        $ParentDir = Split-Path -Parent $InstallDir
        New-Item -ItemType Directory -Force -Path $ParentDir | Out-Null
        Write-Host "正在下载到：$InstallDir"
        & $git.Source clone --depth 1 $Repository $InstallDir
        if ($LASTEXITCODE -ne 0) {
            Fail "代码下载失败，请检查网络或设置 HDU_SAFETY_REPOSITORY 使用镜像"
        }
    }

    $CompileArgs = @($pythonArgs + @(
        "-m", "py_compile",
        (Join-Path $InstallDir "server.py"),
        (Join-Path $InstallDir "xy_auto.py")
    ))
    & $python.Source @CompileArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "Python 文件编译失败，请检查 server.py / xy_auto.py"
    }

    try {
        $Bank = Get-Content -LiteralPath (Join-Path $InstallDir "xy_bank.json") -Raw | ConvertFrom-Json
    } catch {
        Fail "题库不是有效 JSON"
    }
    if ($Bank -is [Array]) {
        $QuestionCount = $Bank.Count
    } elseif ($Bank -is [PSCustomObject]) {
        $QuestionCount = @($Bank.PSObject.Properties).Count
    } else {
        Fail "题库不是 JSON 对象或数组"
    }
    if ($QuestionCount -le 0) {
        Fail "题库为空"
    }
    Write-Host "题库校验完成：$QuestionCount 题"

    $InstallOnly = $InstallOnly -or ($env:HDU_SAFETY_INSTALL_ONLY -eq "1")
    if ($InstallOnly) {
        Write-Host "安装完成：$InstallDir"
        exit 0
    }

    $Client = New-Object System.Net.Sockets.TcpClient
    try {
        $ConnectTask = $Client.ConnectAsync("127.0.0.1", $Port)
        $ConnectionFinished = $false
        try {
            $ConnectionFinished = $ConnectTask.Wait(500)
        } catch [AggregateException] {
            # 端口未监听时 ConnectAsync 会以“连接被拒绝”结束，这是预期结果。
            $ConnectionFinished = $false
        }
        if ($ConnectionFinished -and $Client.Connected) {
            Fail "端口 $Port 已被占用，可用 -Port xxxx 指定其他端口"
        }
    } finally {
        $Client.Dispose()
    }

    $Url = "http://127.0.0.1:$Port"
    Write-Host "`n服务正在启动：$Url"
    Write-Host "关闭此窗口或按 Ctrl+C 即可停止。`n"
    if (-not ($NoOpen -or ($env:HDU_SAFETY_NO_OPEN -eq "1"))) {
        Start-Process $Url
    }

    $PreviousHost = $env:HOST
    $PreviousPort = $env:PORT
    try {
        $env:HOST = "127.0.0.1"
        $env:PORT = [string]$Port
        Set-Location $InstallDir
        & $python.Source @($pythonArgs + @("server.py"))
        $ExitCode = $LASTEXITCODE
    } finally {
        $env:HOST = $PreviousHost
        $env:PORT = $PreviousPort
    }
    exit $ExitCode
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
