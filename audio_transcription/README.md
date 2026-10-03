# 音频转录模块

可从 CxKitty 中单独复制、安装使用, 不读取 `config.yml`, 不依赖
`core`、章节缓存、课程下载器或后台 worker。导入时不加载 torch/FunASR。

## 安装

在项目根目录执行 (建议 Python 3.11/3.12):

```powershell
pip install ./audio_transcription
pip install "./audio_transcription[local,ffmpeg]"
# 仅使用已有的同机 HTTP 转录服务:
pip install "./audio_transcription[remote,ffmpeg]"
```

`local` 安装模型推理依赖; CUDA 用户应先按设备安装对应 PyTorch。
ffmpeg 可以安装到 PATH, 也可使用 `ffmpeg` 扩展提供的二进制。
模型目录布局为 `models/sensevoice-small/` 和 `models/fsmn-vad/`。
已有项目安装脚本 `scripts/install-asr.ps1` 仍可使用。

## Python API

```python
from pathlib import Path
from audio_transcription import LocalSenseVoiceTranscriber, extract_audio

audio = extract_audio(Path("input.mp4"), Path("output.wav"))
transcriber = LocalSenseVoiceTranscriber.from_model_root("models", device="auto")
result = transcriber.transcribe(audio, language="zh")
print(result.text)
print(result.to_dict())  # text / language / segments / 可选 raw
```

`transcribe()` 接收 16kHz 单声道 WAV。复用同一个转录器可以复用已加载模型。
`TranscriptSegment` 使用毫秒时间戳; 统一异常为 `TranscriptError` /
`TranscriptionError`。不指定模型路径时保留原有 ModelScope 模型别名和缓存回退行为。

```python
from audio_transcription.remote import RemoteSenseVoiceTranscriber

client = RemoteSenseVoiceTranscriber("http://127.0.0.1:8765", token="")
result = client.transcribe("output.wav")
```

远程客户端通过绝对路径共享音频, 要求客户端与服务端在同一机器上。
课程缓存、服务端和调度仍属于宿主项目, 继续用 `python -m transcript.server` 启动服务。

## 命令行

```powershell
python -m audio_transcription input.mp4 --model-root models --language zh --output result.json
audio-transcribe input.wav --device cpu --output result.json
python -m audio_transcription input.mp4 --service-url http://127.0.0.1:8765
```

命令行自动调用 ffmpeg 归一化输入为临时 WAV, 完成或失败后清理临时文件。
保留旧的 `transcript.asr` / `extractor` / `remote` / `errors` 导入路径作为兼容入口。
