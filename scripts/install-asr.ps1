<#
.SYNOPSIS
    安装 CxKitty 视频转录管道所需的 ASR 依赖(torch + funasr + modelscope)并下载模型。

.DESCRIPTION
    视频转录管道(transcript/)需要以下额外依赖, 它们体积较大且与主程序解耦,
    因此放在 poetry 的可选依赖组 `asr` 中, 未安装时不影响原有刷课功能:

      torch / torchaudio  ->  PyTorch 运行时(CPU 或 CUDA 版本)
      funasr==1.4.2       ->  SenseVoiceSmall 推理框架
      modelscope          ->  模型下载与本地缓存快照

    Python 版本要求 3.11 / 3.12(torch wheel 覆盖范围)。

.PARAMETER Device
    安装 CUDA(cu128) 还是 CPU 版本的 torch。默认 cuda。

.PARAMETER ModelRoot
    模型根目录, 需包含 sensevoice-small/ 与 fsmn-vad/ 两个子目录。
    默认从 config.yml 的 transcript.model_root 读取, 读取不到则用
    D:/Project/search_via_bilibili/models。

.PARAMETER Python
    指定 Python 解释器路径。默认优先使用 `poetry env info -p`, 其次使用 .venv。

.PARAMETER SkipModelDownload
    只安装依赖, 不下载模型(例如模型已存在于 ModelRoot)。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/install-asr.ps1 -Device cuda
#>
param(
    [ValidateSet("cuda", "cpu")]
    [string]$Device = "cuda",
    [string]$ModelRoot = "",
    [string]$Python = "",
    [switch]$SkipModelDownload
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DefaultModelRoot = "D:/Project/search_via_bilibili/models"

function Resolve-Python {
    param([string]$Explicit)
    if ($Explicit) {
        if (-not (Test-Path -LiteralPath $Explicit)) { throw "指定的 Python 不存在: $Explicit" }
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) { return $venvPython }
    if (Get-Command poetry -ErrorAction SilentlyContinue) {
        Push-Location $ProjectRoot
        try {
            $poetryPath = (& poetry env info -p 2>$null | Select-Object -First 1)
        } finally {
            Pop-Location
        }
        if ($poetryPath) {
            $candidate = Join-Path $poetryPath.Trim() "Scripts\python.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    throw "未找到可用的 Python 解释器, 请用 -Python 指定(例如 poetry 虚拟环境的 Scripts\python.exe)"
}

function Resolve-ModelRoot {
    param([string]$Explicit)
    if ($Explicit) { return $Explicit }
    $configPath = Join-Path $ProjectRoot "config.yml"
    if (Test-Path -LiteralPath $configPath) {
        $match = Select-String -Path $configPath -Pattern '^\s*model_root:\s*"?([^"#]+)"?' | Select-Object -First 1
        if ($match) {
            $value = $match.Matches[0].Groups[1].Value.Trim().TrimEnd('/')
            if ($value) { return $value }
        }
    }
    return $DefaultModelRoot
}

$PythonExe = Resolve-Python -Explicit $Python
$ModelRoot = (Resolve-ModelRoot -Explicit $ModelRoot).TrimEnd('\', '/')

Write-Host "Python      : $PythonExe" -ForegroundColor Cyan
Write-Host "ModelRoot   : $ModelRoot" -ForegroundColor Cyan
Write-Host "Torch 通道  : $Device" -ForegroundColor Cyan

if ($Device -eq "cuda") {
    & $PythonExe -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cu128
} else {
    & $PythonExe -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cpu
}

& $PythonExe -m pip install --upgrade "funasr==1.4.2" "modelscope>=1.20,<2"

Push-Location $ProjectRoot
try {
    if (-not $SkipModelDownload) {
        & $PythonExe -c "from pathlib import Path; from modelscope.hub.snapshot_download import snapshot_download; root = Path(r'$ModelRoot'); sv = root / 'sensevoice-small'; vad = root / 'fsmn-vad'; sv.mkdir(parents=True, exist_ok=True); vad.mkdir(parents=True, exist_ok=True); snapshot_download('iic/SenseVoiceSmall', local_dir=str(sv)); snapshot_download('iic/speech_fsmn_vad_zh-cn-16k-common-pytorch', local_dir=str(vad)); print('models=' + str(sv) + ',' + str(vad))"
    }
    & $PythonExe -c "from transcript.asr import LocalSenseVoiceTranscriber, model_root_status; status = model_root_status(r'$ModelRoot'); print('model_root_status=' + str(status)); t = LocalSenseVoiceTranscriber.from_model_root(r'$ModelRoot'); print('device=' + t.load())"
} finally {
    Pop-Location
}

Write-Host "ASR 依赖与模型准备完成。请在 config.yml 中设置 transcript.enable: true" -ForegroundColor Green