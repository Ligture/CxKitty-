"""视频转录管道的异常定义

转录管道整体是"尽力而为的增强", 任何环节失败都只应记录日志并放弃当前任务,
不应影响刷课主流程, 因此这里的异常统一继承自 RuntimeError。
"""


class TranscriptError(RuntimeError):
    """转录管道(下载 / 音频提取 / 缓存写入)异常"""


class TranscriptionError(TranscriptError):
    """语音识别后端(funasr / SenseVoiceSmall)异常"""


__all__ = ["TranscriptError", "TranscriptionError"]