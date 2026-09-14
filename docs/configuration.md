# 配置文件说明 (v2)

配置文件为仓库根目录下的 `config.yml`（示例见 `config.yml.example`）。v2 采用**分段结构**：运行、路径、代理、任务、转录、搜索器各自成段，字段名统一小写，缺失字段自动使用默认值。

> 旧版 v1（扁平结构，如 `session_path:`、`proxies:` 直接写在顶层）**仍可读取**：程序启动时会给出兼容警告，按提示执行 `python scripts/migrate_config.py` 即可迁移（原文件自动备份为 `config.yml.bak.<时间戳>`）。

## 结构总览

```yaml
version: 2
runtime:    { ... }    # 运行 / 界面
paths:      { ... }    # 目录
proxy:      { ... }    # 网络代理
tasks:                 # 刷课任务
  video:    { ... }
  work:     { ... }
  document: { ... }
  exam:     { ... }
transcript: { ... }    # 视频转录管道
searchers:             # 题库 / AI 搜索器
  defaults: { ... }    # AI 搜索器公共默认值
  items:    [ ... ]    # 搜索器列表(自上而下依次调用)
```

启动时程序会校验配置：**未知字段**（多半是拼写错误）、**类型错误**都会以警告形式提示，并回退到默认值，不会静默生效。

---

## runtime — 运行与界面

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `multi_session` | bool | `true` | 多会话模式：启动时选择会话存档 |
| `mask_acc` | bool | `true` | 手机号 / 姓名打码 |
| `tui_max_height` | int / null | `25` | TUI 高度，`null` 表示自适应 |
| `fetch_uploaded_face` | bool | `true` | 登录后拉取云端已上传的人脸图片 |

## paths — 目录

| 字段 | 默认值 | 说明 |
|---|---|---|
| `session` | `session/` | 会话存档目录 |
| `logs` | `logs/` | 日志目录（含 `transcript.log`） |
| `export` | `export/` | 试题 / 错题导出目录 |
| `faces` | `faces/` | 人脸图片目录（文件名须为 `puid.jpg`） |

## proxy — 网络代理

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enable` | bool | `false` | 是否启用代理 |
| `http` | str | `http://127.0.0.1:7897` | HTTP 代理地址 |
| `https` | str | `http://127.0.0.1:7897` | HTTPS 代理地址 |

开启后同时作用于学习通请求与 AI 搜索器；Gemini 搜索器可用 `proxy_enable` / `proxy` 单独覆盖。

## tasks — 刷课任务

### tasks.video

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enable` | bool | `true` | 是否处理视频任务点 |
| `wait` | int | `15` | 单个任务点完成后的等待秒数 |
| `speed` | float | `1.0` | 播放倍速 |
| `report_rate` | int | `58` | 播放进度上报频率（没事别改） |
| `download` | bool | `true` | 刷课时下载视频（视频转录的前置条件） |

### tasks.work（作业 / 章节测验）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enable` | bool | `true` | 是否自动作答 |
| `export` | bool | `true` | 导出试题；`enable: true` 且 `export: false` 时只导出不作答（dry run） |
| `wait` | int | `15` | 完成后的等待秒数 |
| `fallback_fuzzer` | bool | `false` | 未匹配到答案时随机选择 |
| `fallback_save` | bool | `true` | 作答失败仍保存 |

### tasks.document / tasks.exam

- `document.enable`（bool，默认 `true`）、`document.wait`（int，默认 `15`）
- `exam.fallback_fuzzer`（bool，默认 `false`）、`exam.persubmit_delay`（int，默认 `15`）、`exam.confirm_submit`（bool，默认 `true`，为 `false` 时自动交卷）

## transcript — 视频转录管道

见 [video-transcript-plan.md](video-transcript-plan.md)。任一字段异常都不会影响刷课主流程。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enable` | bool | `false` | 是否启用转录管道 |
| `model_root` | str | `""` | 模型根目录，需包含 `sensevoice-small/` 与 `fsmn-vad/` |
| `device` | str | `auto` | `auto` / `cuda` / `cpu` |
| `language` | str | `auto` | `auto` / `zh` / `en` / `yue` / `ja` / `ko` |
| `use_itn` | bool | `true` | 逆文本正则化（数字、标点） |
| `cache_path` | str | `transcripts/` | 转录缓存目录（`object_id.json`） |
| `video_path` / `audio_path` | str | `videos/` / `audios/` | 临时目录 |
| `keep_video` / `keep_audio` | bool | `false` | 转录完成后是否保留临时文件（失败时一律保留以便重试） |

---

## searchers — 题库与 AI 搜索器

```yaml
searchers:
  defaults:            # 公共默认值(只对 AI 搜索器生效)
    prompt: |
      请回答下这个{type}：
      {value}
      {options}
    system_prompt: |
      你是一位专业的学习通题目答题助手。……
  items:               # 搜索器列表, 自上而下依次调用
    - type: json
      file_path: "questions.json"
    - type: openai
      enabled: true
      note: "deepseek"
      api_key: "sk-***"
      base_url: "https://api.deepseek.com/v1"
      model: "deepseek-chat"
```

### 调用顺序与元字段

搜索器**按 `items` 顺序调用**，`QuestionResolver` 依次尝试各搜索器的返回，先得到有效答案者生效——因此建议把本地题库放最前、AI 搜索器放最后。

| 元字段 | 必填 | 说明 |
|---|---|---|
| `type` | ✅ | 搜索器类型，大小写不敏感，可用类名（`OpenAISearcher`）或短别名（`openai`） |
| `enabled` | | 默认 `true`；显式 `false` 的条目会被跳过（便于保留备用配置） |
| `note` | | 备注，仅用于日志与 TUI 展示（如 `OpenAISearcher[deepseek]`） |

其余字段直接作为搜索器构造参数，未知字段、缺失的必填字段都会在启动答题时报错并列出可用字段。

### 公共默认值 `searchers.defaults`

`defaults` 中的字段会合并进**接受额外参数的搜索器**（即 `openai` / `gemini` / `transcript` 三个 AI 搜索器），条目内同名字段优先。典型用法是只写一份 `prompt` / `system_prompt`，多个 AI 搜索器共享。

### 搜索器参数表

| type（别名） | 必填 | 可选 |
|---|---|---|
| `json` / `JsonFileSearcher` | `file_path` | — |
| `sqlite` / `SqliteSearcher` | `file_path` | `table`（`question`）、`req_field`（`question`）、`rsp_field`（`answer`） |
| `rest` / `RestApiSearcher` | `url` | `method`（`POST`）、`q_field`（`question`）、`o_field`、`a_field`（`$.data`）、`headers`、`ext_params` |
| `jsonApi` / `JsonApiSearcher` | `url` | `q_field`、`o_field`、`a_field`、`headers`、`ext_params` |
| `cx` / `CxSearcher` | `token` | — |
| `enncy` / `EnncySearcher` | `token` | — |
| `tikuhai` / `TiKuHaiSearcher` | `token` | — |
| `lyck6` / `LyCk6Searcher` | `token`、`gpt` | — |
| `lemon` / `LemonSearcher` | `token` | — |
| `muke` / `MukeSearcher` | — | — |
| `openai` / `OpenAISearcher` | `api_key` | `base_url`、`model`、`system_prompt`、`prompt`、`tools`、`tool_choice` |
| `gemini` / `GeminiWebSearcher` | `Secure_1PSID`、`Secure_1PSIDTS` | `model`、`system_prompt`、`prompt`、`proxy_enable`、`proxy` |
| `transcript` / `TranscriptAISearcher` | `api_key`、`base_url`、`model` | `system_prompt`、`prompt`、`wait_ready`、`max_context_chars` |

字段含义：

- `file_path`：本地题库文件（JSON 为 `题目: 答案` 映射；SQLite 表中含请求 / 响应字段）
- `url` / `method` / `q_field` / `o_field` / `a_field` / `headers` / `ext_params`：在线题库接口参数，`a_field` 使用 [JsonPath](https://goessner.net/articles/JsonPath/) 语法，`o_field` 不为空时会把选项用 `#` 拼接后一并提交
- `token`：第三方题库 Token
- `api_key` / `base_url` / `model`：OpenAI 兼容接口参数（`base_url` 留空默认 `https://api.openai.com/v1`，`model` 留空默认 `gpt-4o-mini`）
- `system_prompt` / `prompt`：提示词；`prompt` 支持 `{type}` `{value}` `{options}`（`transcript` 额外支持 `{transcript}`），留空使用内置默认
- `tools` / `tool_choice`：OpenAI Tools / 函数调用配置（可选）
- `Secure_1PSID` / `Secure_1PSIDTS`：Gemini 网页版 cookie
- `proxy_enable` / `proxy`：Gemini 单独代理，留空回退 `proxy` 段
- `wait_ready` / `max_context_chars`：文稿未就绪时的最大等待秒数与上下文长度上限

### 示例组合

```yaml
searchers:
  items:
    # 先查本地题库
    - type: json
      file_path: "questions.json"
    # 再查免费题库
    - type: enncy
      token: "***"
    # 最后交给 AI 兜底(带备注便于在 TUI 中区分)
    - type: openai
      note: "deepseek"
      api_key: "sk-***"
      base_url: "https://api.deepseek.com/v1"
      model: "deepseek-chat"
```

---

## 校验与报错

| 现象 | 含义 |
|---|---|
| `config.yml: 未知配置项 \`xxx\`, 已忽略` | 字段名拼写错误或已废弃 |
| `config.yml: \`xxx\` 的值 ... 类型不正确, 已回退默认值 ...` | 类型错误（如把 `wait` 写成文本） |
| `config.yml 仍是 v1 扁平格式 ...` | 旧格式兼容提示，建议迁移 |
| `未配置任何搜索器: 请在 config.yml 的 searchers.items 中至少启用一个搜索器` | 没有可用搜索器，无法自动答题 |
| `所有搜索器都被禁用(enabled: false), 请至少启用一个搜索器` | `items` 中的条目全部被 `enabled: false` 跳过 |
| `搜索器 [xxx] 缺少必填配置项: ...` / `存在未知配置项: ...` | 搜索器条目参数有误 |

## 常见问题

- **只想导出题目、不自动作答？** 设 `tasks.work.enable: true`、`tasks.work.export: false`。
- **不用自动答题功能？** 可以不在 `searchers.items` 中配置任何搜索器；只有执行到测验环节时才会要求搜索器。
- **多个 AI 搜索器都要写提示词吗？** 不需要，写在 `searchers.defaults` 中共享，条目内按需覆盖。
- **想临时停用某个搜索器？** 把该条目改为 `enabled: false`（保留配置，不影响其他条目）。