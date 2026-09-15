# 视频转录辅助答题方案(SenseVoiceSmall)

> 状态:**P0 + P1 已实施**, P2 部分实施(ananas 字幕直取与断点续传未做; WebUI 已放弃并从项目移除)
> 目标:刷课过程中将章节视频下载→提取音频→本地 SenseVoiceSmall 转录→按章节缓存文稿→答题时作为上下文交给 AI,降低单 AI 搜索器的错误率

## 实施记录

| 计划项 | 状态 | 落地位置 |
|---|---|---|
| §3 新增模块 | ✅ | `transcript/{downloader,extractor,asr,cache,worker,context,errors}.py`(额外拆出 `errors.py` 存放异常) |
| §5.1 保留视频直链 | ✅ | `cxapi/task_point/video.py` 新增 `http` 字段, hls-only 记 warning |
| §5.2 视频入队 | ✅ | `main.py` 视频分支 |
| §5.3 章节文稿指针 | ✅ | `main.py` 测验分支前 `set_current_knowledge_id`, 考试前清空 |
| §6 配置项 | ✅ | `config.py`、`config.yml.example` |
| §6 TranscriptAISearcher | ✅ | `resolver/searcher/transcript.py`, 注册进 `SEARCHERS` |
| §7 弃权而非阻塞 | ✅ | 文稿未就绪按 `wait_ready` 等待后返回未匹配; 无可期待任务时不再空等 |
| §2 移植资产 | ✅ | `transcript/asr.py`(去 `paths.py` 依赖, model_root 由配置注入), `scripts/install-asr.ps1` |
| P2 ananas 字幕直取 | ⬜ | 未做(需 ananas 响应含 `subtitle` 字段) |
| P2 失败重试/断点续传 | 🟡 | 转录失败保留视频, 重跑复用已下载视频; 未做进程重启级断点 |
| ~~P2 WebUI 接入~~ | ❌ | 已放弃: `web/`(React 前端)、`server/`(FastAPI 后端)与 WebUI 专用代码均已删除 |

实施中补充的两点(计划外但必要):

1. `transcript/worker.py` 为转录日志单独挂 `logs/transcript.log` 文件 handler 并关闭向 root 传播——`Logger` 默认不挂 handler, 否则后台进度会丢失, 且 warning 会经 `lastResort` 写 stderr 干扰 rich Live 渲染。
2. `resolver/question.py` 的 `load_searcher()` 原先会 `del searcher_conf["type"]` 污染 `config.SEARCHERS`, 导致 `clear_searcher_cache()` 后二次加载 `KeyError`(每次任务重复加载时触发); 已改为先复制字典。

## 1. 总体思路

整条管道塞进现有"模拟播放"的时间窗口内,**不改变刷课主流程的节奏**:

```
主线程(不变,串行):
  遍历章节 → 视频任务点 parse_attachment/fetch → MediaPlayResolver 模拟播放(阻塞 N 分钟)
           → 测验任务点 fetch_all → QuestionResolver 逐题搜索/作答

后台转录线程(新增,单线程队列):
  视频 fetch 成功时入队 → 下载 mp4 → ffmpeg 提取 16k wav
  → SenseVoiceSmall+FSMN-VAD 转录 → 写缓存 transcripts/{object_id}.json
  → 注册到章节文稿表(knowledge_id → text)

答题时(新增注入):
  TranscriptAISearcher 从章节文稿表取当前章节文稿
  → 连同题目发给 OpenAI 兼容 API → 与现有题库搜索器结果交叉验证
```

时间预算验证:30 分钟视频 1 倍速播放 = 30 分钟窗口;下载约 2–5 分钟,ffmpeg 提取 <1 分钟,SenseVoiceSmall 在 CPU 上远快于实时(约 10 倍速,3 分钟内跑完),余量充足。2 倍速时窗口减半仍够,不够则该 searcher 本轮弃权(见 §6)。

## 2. 复用资产(来自 D:\Project\search_via_bilibili)

| 资产 | 内容 | 复用方式 |
|---|---|---|
| `LocalSenseVoiceTranscriber` | 模型加载(懒加载、cuda/cpu 自动选择、本地目录缺失时回退 modelscope 缓存)、VAD 切片参数(`max_single_segment_time=30000`、`batch_size_s=60`、`merge_vad=True`、`merge_length_s=15`)、结果解析(语言标签、`rich_transcription_postprocess`、句级时间戳) | **代码拷贝移植**(约 150 行,含 `Transcript`/`TranscriptSegment` 数据类),去除其 `paths.py` 依赖,模型路径改由 config 注入 |
| 本地模型 | `models/sensevoice-small/`(897MB,完整:model.pt/config.yaml/tokens.json/bpe)+ `models/fsmn-vad/`(3.9MB) | **不拷贝、不重复下载**,config 里 `model_root` 直接指向 `D:/Project/search_via_bilibili/models` |
| `scripts/install-asr.ps1` | torch(cpu/cu128 通道)→ `funasr==1.4.2` → `modelscope` → 模型下载 → 冒烟加载 | 抄成 CxKitty 的安装脚本/文档说明 |
| `model_directory_status()` | 就绪校验(model.pt + config.yaml 存在) | 一并移植,启动时探测给出清晰报错 |

依赖注意:`funasr==1.4.2` 拉起 torch 全家,与 CxKitty 现有依赖无冲突但体量大,故放入**可选依赖组** `[tool.poetry.group.asr]`(optional),懒加载,未安装时给出明确提示而非崩溃。Python 版本锁 3.11/3.12(torch wheel 覆盖范围),CxKitty 声明的 3.13/3.14 不保证。

## 3. 新增模块布局

```
transcript/                  # 新增包
├── __init__.py
├── downloader.py            # 流式下载(走 SessionWraper,自动继承代理配置),文件名非法字符清洗
├── extractor.py             # ffmpeg subprocess 音频提取(-vn -ar 16000 -ac 1 wav);启动时探测 ffmpeg 是否可用
├── asr.py                   # 移植的 LocalSenseVoiceTranscriber + 模型目录就绪校验
├── cache.py                 # transcripts/{object_id}.json 读写(schema 见 §4)
├── worker.py                # 单线程后台 worker(queue.Queue),串行消费,模型进程内单例
└── context.py               # 章节文稿注册表 knowledge_id -> 拼合文本(dict+锁,供 searcher 读)

resolver/searcher/transcript.py   # TranscriptAISearcher(注册进 SEARCHERS 字典)
cxapi/task_point/video.py         # fetch() 增加保留 json_content["http"] 字段(约 2 行)
main.py                           # 两处钩子(见 §5)
config.py / config.yml.example    # 新增配置段(见 §6)
```

## 4. 数据设计

转录缓存 `transcripts/{object_id}.json`(object_id 是视频唯一标识,天然去重,重复刷课直接命中):

```json
{
  "object_id": "...", "title": "...", "knowledge_id": 12345,
  "duration": 1800, "transcribed_at": 1697000000,
  "text": "全文...",
  "segments": [{"start_ms": 0, "end_ms": 5200, "text": "..."}]
}
```

章节文稿 = 同一 `knowledge_id` 下所有视频的 `text` 按任务点顺序拼接(DTO 已有 `knowledge_id` 字段)。30 分钟视频约 5–8k token,拼接后仍在现代模型上下文余量内。

## 5. 改动点(现有文件)

1. `cxapi/task_point/video.py`:`fetch()` 保留 `http` 直链字段;无 `http`(hls-only)记 warning 返回 None,第一版不支持 m3u8。
2. `main.py` 视频分支(`main.py:238`):`fetch()` 成功且配置开启时 `worker.enqueue(video_dto)`,随后照常播放——下载转录与模拟播放并行。
3. `main.py` 测验分支(`main.py:208`):`QuestionResolver` 执行前,把当前章节 `knowledge_id` 设入 `TranscriptAISearcher` 的上下文指针(模块级变量即可,主线程写、searcher 读)。

## 6. 配置设计(config.yml)

```yaml
tasks:
  video:
    # ...现有 enable/wait/speed/report_rate 不变
    download: true          # 刷课时下载视频(转录的前置)

transcript:
  enable: true
  model_root: "D:/Project/search_via_bilibili/models"   # 复用已有 SenseVoiceSmall+FSMN-VAD
  device: "auto"            # auto: 有 cuda 用 cuda,否则 cpu
  language: "auto"          # SenseVoice 支持 auto/zh/en/yue/ja/ko
  cache_path: "transcripts/"
  keep_video: false         # 转录完删除视频(磁盘紧张时);true 则保留到 videos/
  keep_audio: false

searchers:
  items:
    # ...现有搜索器不动,新增:
    - type: transcript
      base_url: "..."       # OpenAI 兼容 API,复用 openai 搜索器的配置习惯
      api_key: "..."
      model: "..."
      wait_ready: 30        # 答题时文稿未就绪则最多等待秒数,超时本轮弃权(返回未匹配,不影响其他搜索器)
```

## 7. 时序与并发要点

- **单 worker 串行**:队列逐个处理,不并发下载/转录(避免 CPU/IO 争抢影响主进程,也避免风控)。
- **模型懒加载**:worker 收到第一个任务才 `load()`(约 10–30 秒),进程生命周期内复用。
- **TUI 隔离**:worker 线程绝不碰 rich Live/Layout(非线程安全),进度只走 logger。
- **弃权而非阻塞**:答题时文稿未就绪,`TranscriptAISearcher` 按 `wait_ready` 等待后返回未匹配,主流程和题库搜索器不受影响——转录管道整体是"尽力而为的增强",任何环节失败都退化为现状。

### 内存占用(实测)

管道的内存几乎全部来自 ASR 依赖与模型本身。Windows 任务管理器里"提交大小"峰值约 4.6–5.8GB、常驻内存峰值约 3.6GB,构成如下(20 逻辑核心 CPU / RTX 5060,14 分钟音频实测):

| 阶段 | 常驻增量 | 提交增量 | 说明 |
|---|---|---|---|
| 启动导入基础依赖 | ~120MB | ~220MB | requests / rich / numpy / opencv / ddddocr / openai 等 |
| 启动依赖探测(旧实现) | ~690MB | ~1.7GB | `__import__("torch"/"funasr"/"modelscope")` 会连带加载整套 CUDA 运行库,即使本次运行一次转录都没有 |
| 计算线程池(BLAS/OpenMP) | ~0 | ~1.2GB | numpy(OpenBLAS)与 torch 按逻辑核心数预分配缓冲,每线程约 30–60MB |
| 首次模型加载 | ~940MB(峰值 3.6GB) | ~2.1GB | 893MB 权重文件 + 建图/搬运到 GPU 的一次性峰值;显存约 +1.1GB |
| 单次转录(14 分钟音频) | ~740MB(峰值) | ~1.1GB | fbank 特征提取 + VAD 分片 |

由此形成两条约束:

- **启动探测不导入重库**:`dependency_status()` 用 `importlib.util.find_spec` + 包元数据代替 `__import__`,只回答"是否已安装";模型仍在 worker 收到第一个任务时才 `load()`。旧实现让"只刷课 / 未开启转录"的场景也白交 1.7GB 提交内存。
- **`runtime.cpu_threads` 限制线程池**:设为 4 时实测提交内存下降约 1GB(funasr 导入 1.32GB vs 不限制时 2.36GB)。ASR 在 CUDA 上推理时 CPU 线程只服务 fbank 特征提取,调小影响很小;`device: cpu` 时线程数直接决定转录速度,按需调大。

模型加载后常驻属于正常现象:进程内单例复用,任务结束后不会卸载,想回收只能退出程序。

### 进程外转录服务(多账号复用一份模型)

`transcript.mode: service` 时, 模型不再进主进程, 而是由 `python -m transcript.server`(入口
`transcript/server.py`)单独持有; 多个 `main.py`(多账号)通过本机 HTTP 共享它:

```
main.py #1  ─┐  下载视频 / ffmpeg 提取 wav / 写本地缓存        ┌─ 单模型 SenseVoice + FSMN-VAD
main.py #2  ─┼─ POST /transcribe {"audio_path": "...", ...} ──►│  串行排队执行(GPU 上只跑一路)
main.py #3  ─┘   GET /health  查看设备 / 队列 / 累计次数        └─ 可选服务端缓存(跨账号去重)
```

| 接口 | 说明 |
|---|---|
| `GET /health` | 设备、模型是否已加载、队列深度、累计转录 / 缓存 / 失败次数 |
| `POST /transcribe` | 请求体含绝对路径 `audio_path` 与 `object_id` / `title` / `knowledge_id` / `duration` / `language` / `use_itn`, 返回 `text` / `language` / `segments` / `device` / `cached` / `elapsed` |
| `POST /unload` | 释放模型(内存 + 显存), 下次请求自动重新加载 |

* 客户端(worker)通过 `RemoteSenseVoiceTranscriber` 调用, 与本地实现同一套接口(`load()` / `device_in_use` / `transcribe()`), 因此下载 / 提取 / 缓存逻辑完全不变
* 服务端单推理线程 + 请求排队, 多账号并发提交不会争抢显存; 失败按"尽力而为"降级为不转录
* 服务端可选 `--cache-path`(默认取 `transcript.cache_path`)、`--idle-unload 秒`、`--token` 口令
* 客户端与服务端必须同机(按绝对路径读取音频), 跨机部署需自行共享路径并设置口令
* 实测(3 个账号): 各自加载模型约 5.3GB 常驻 / 10.7GB 提交 / 3.3GB 显存; 改成 1 个服务 + 3 个客户端后约 2.1GB 常驻 / 4.2GB 提交 / 1.1GB 显存

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 视频仅 hls(m3u8)无 mp4 直链 | 跳过+warning;m3u8 下载留待后续(需分片下载/解密,不在本期) |
| ffmpeg 未安装 | 启动探测,提示安装或改用 `imageio-ffmpeg` pip 包自带二进制(备选) |
| funasr/torch 体积大、py3.13+ 兼容 | 可选依赖组+文档声明支持 3.11/3.12;懒加载,不装 ASR 不影响原功能 |
| 转录错字/术语误转 | prompt 声明"文稿可能有识别错误,结合题意判断";与题库搜索器交叉,冲突时以题库优先并在 TUI 标注 |
| 文稿与测验弱相关(章节内多视频) | 全章节拼合作为上下文,噪声无害;prompt 限定"仅当文稿含答案依据时使用" |
| 超星频控 | 下载复用带 Cookie 的 session、串行、单线程,与官方播放器行为同源 |

## 9. 实施阶段

- **P0(管道,约 250–300 行)**:video.py 留直链 → downloader/extractor/asr/cache/worker 落地,跑通"刷课→transcripts/ 出 JSON",答题不接入。验证产物与耗时。
- **P1(注入,约 150–200 行)**:context 注册表 + TranscriptAISearcher + main.py 两个钩子 + 配置项,打通"文稿→AI 作答",与题库搜索器并行对比正确率。
- **P2(优化,可选)**:ananas 响应自带 `subtitle` 字段时直接拉字幕跳过 ASR;失败重试与断点续传。(WebUI 已放弃, 不再作为交付项)

预计 P0+P1 合计 1–2 个工作日,主要不确定性在 prompt 调优与真实课程的正确率验证,而非管道本身。
