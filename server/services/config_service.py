"""
配置服务 — 线程安全的 config.yml 读写

提供:
- ConfigService: 配置加载/保存/快照
- SEARCHER_TEMPLATES: 搜索器模板定义 (从 webui.py 迁移)
"""

import copy
import threading
from pathlib import Path

import yaml


# ============================================================
# 搜索器模板定义
# ============================================================

SEARCHER_TEMPLATES = {
    "OpenAISearcher": {
        "label": "OpenAI 兼容接口",
        "icon": "brain",
        "color": "#10b981",
        "desc": "支持 OpenAI / DeepSeek / 豆包 等兼容 API 的模型",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "OpenAISearcher"},
            {"key": "base_url", "label": "API 地址 (base_url)", "type": "url", "default": "https://api.openai.com/v1", "placeholder": "https://api.openai.com/v1", "required": True},
            {"key": "api_key", "label": "API 密钥 (api_key)", "type": "password", "default": "", "placeholder": "sk-...", "required": True},
            {"key": "model", "label": "模型名称 (model)", "type": "text", "default": "gpt-4o", "placeholder": "gpt-4o / deepseek-chat / doubao-seed-...", "required": True},
            {"key": "system_prompt", "label": "系统提示词 (system_prompt)", "type": "textarea", "default": "你是一位专业的学习通题目答题助手。\n\n请严格遵循以下规则作答：\n\n 多选题至少选择两个正确选项\n - 选项字母用英文逗号分隔\n\n输出格式：\n - 单选题：只输出选项字母\n - 判断题：只输出「对」或「错」\n - 多选题：只输出选项字母，用逗号分隔.\n\n请确保每个选择都严格符合题干限定的主题范围，不扩大不缩小。只回复答案，不要输出除答案以外任何内容。", "rows": 6},
            {"key": "prompt", "label": "提问模板 (prompt)", "type": "textarea", "default": "请回答下这个{type}：\n{value}\n{options}", "rows": 3, "help": "可用变量: {type}题目类型, {value}题干, {options}选项文本"},
            {"key": "tools", "label": "Function Calling 工具定义 (tools)", "type": "textarea", "default": "", "placeholder": "JSON 格式的工具定义数组，留空则不启用", "rows": 6, "help": "可选。定义后可让AI调用函数返回结构化答案。格式: [{\"type\":\"function\",\"function\":{\"name\":\"answer\",\"parameters\":{...}}}]"},
            {"key": "tool_choice", "label": "工具选择策略 (tool_choice)", "type": "text", "default": "", "placeholder": "auto / required / none 或具体函数名", "help": "可选。控制模型调用工具的倾向"},
            {"key": "note", "label": "备注", "type": "text", "default": "", "placeholder": "自定义备注，如用途说明"},
        ],
    },
    "GeminiWebSearcher": {
        "label": "Gemini Web (免API Key)",
        "icon": "sparkles",
        "color": "#8b5cf6",
        "desc": "通过 Gemini 网页版 Cookie 进行答题",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "GeminiWebSearcher"},
            {"key": "proxy_enable", "label": "启用代理", "type": "switch", "default": False},
            {"key": "proxy", "label": "代理地址", "type": "text", "default": "http://127.0.0.1:7897", "placeholder": "http://127.0.0.1:7897"},
            {"key": "Secure_1PSID", "label": "Secure_1PSID", "type": "password", "default": "", "placeholder": "从 Gemini Cookie 获取", "required": True},
            {"key": "Secure_1PSIDTS", "label": "Secure_1PSIDTS", "type": "password", "default": "", "placeholder": "从 Gemini Cookie 获取", "required": True},
            {"key": "model", "label": "模型", "type": "select", "default": "G-3.1-PRO", "options": ["G-3.1-PRO", "G-3.0-FLASH-THINKING", "G-3.0-FLASH"]},
            {"key": "system_prompt", "label": "系统提示词", "type": "textarea", "default": "你是一个学习通答题助手,你会得到一些有关题目,你需要回答这些题目,包括单选题,多选题,判断题,多选题至少选择两个选项,用逗号分隔答案.\n\n输出格式:\n单选题：只输出选项字母\n判断题：只输出「对」或「错」\n多选题：只输出选项字母，用逗号分隔.\n\n只回复答案，不要输出除答案以外任何内容。", "rows": 4},
            {"key": "prompt", "label": "提问模板", "type": "textarea", "default": "请回答下这个{type}：\n{value}\n{options}", "rows": 3},
            {"key": "note", "label": "备注", "type": "text", "default": "", "placeholder": "自定义备注"},
        ],
    },
    "TranscriptAISearcher": {
        "label": "章节视频文稿 + AI 作答",
        "icon": "film",
        "color": "#6366f1",
        "desc": "把章节视频的本地转录文稿作为上下文交给 AI 作答(需先在配置中开启 transcript.enable 并安装 ASR 依赖)",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "TranscriptAISearcher"},
            {"key": "base_url", "label": "API 地址 (base_url)", "type": "url", "default": "https://api.openai.com/v1", "placeholder": "https://api.openai.com/v1", "required": True},
            {"key": "api_key", "label": "API 密钥 (api_key)", "type": "password", "default": "", "placeholder": "sk-...", "required": True},
            {"key": "model", "label": "模型名称 (model)", "type": "text", "default": "gpt-4o-mini", "placeholder": "gpt-4o / deepseek-chat", "required": True},
            {"key": "wait_ready", "label": "文稿等待秒数 (wait_ready)", "type": "number", "default": 30, "help": "答题时章节文稿未就绪最多等待的秒数，超时本轮弃权，不影响其他搜索器"},
            {"key": "max_context_chars", "label": "文稿最大字符数 (max_context_chars)", "type": "number", "default": 24000, "help": "超出后保留首尾两段，避免超出模型上下文"},
            {"key": "system_prompt", "label": "系统提示词 (system_prompt)", "type": "textarea", "default": "", "rows": 8, "placeholder": "留空使用内置提示词(已声明文稿可能有 ASR 识别错误)", "help": "可选。留空时使用内置提示词"},
            {"key": "prompt", "label": "提问模板 (prompt)", "type": "textarea", "default": "", "rows": 6, "placeholder": "留空使用内置模板", "help": "可用变量: {type}题目类型, {value}题干, {options}选项文本, {transcript}章节文稿"},
            {"key": "note", "label": "备注", "type": "text", "default": "", "placeholder": "自定义备注，如用途说明"},
        ],
    },
    "restApiSearcher": {
        "label": "REST API 搜题",
        "icon": "server",
        "color": "#f59e0b",
        "desc": "自定义 REST API 接口搜题",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "restApiSearcher"},
            {"key": "url", "label": "API URL", "type": "url", "default": "", "placeholder": "http://example.com/api/search", "required": True},
            {"key": "method", "label": "请求方式", "type": "select", "default": "POST", "options": ["GET", "POST"]},
            {"key": "q_field", "label": "题目参数名", "type": "text", "default": "question", "placeholder": "question"},
            {"key": "o_field", "label": "选项参数名 (可选)", "type": "text", "default": "", "placeholder": "留空表示不传选项"},
            {"key": "a_field", "label": "答案 JSONPath", "type": "text", "default": "$.data", "placeholder": "$.data", "required": True},
            {"key": "headers", "label": "自定义请求头 (JSON)", "type": "textarea", "default": "{}", "rows": 2, "placeholder": '{"Authorization":"Bearer xxx"}'},
            {"key": "ext_params", "label": "额外参数 (JSON)", "type": "textarea", "default": "{}", "rows": 2, "placeholder": '{"token":"xxx"}'},
        ],
    },
    "jsonFileSearcher": {
        "label": "本地 JSON 题库",
        "icon": "database",
        "color": "#06b6d4",
        "desc": "本地 JSON 文件 (key: 题目, value: 答案)",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "jsonFileSearcher"},
            {"key": "file_path", "label": "文件路径", "type": "text", "default": "questions.json", "placeholder": "questions.json", "required": True},
        ],
    },
    "sqliteSearcher": {
        "label": "SQLite 题库",
        "icon": "hard-drive",
        "color": "#64748b",
        "desc": "本地 SQLite 数据库搜题",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "sqliteSearcher"},
            {"key": "file_path", "label": "数据库文件路径", "type": "text", "default": "questions.db", "placeholder": "questions.db", "required": True},
            {"key": "table", "label": "表名", "type": "text", "default": "question", "placeholder": "question", "required": True},
            {"key": "req_field", "label": "题目字段", "type": "text", "default": "question", "placeholder": "question"},
            {"key": "rsp_field", "label": "答案字段", "type": "text", "default": "answer", "placeholder": "answer"},
        ],
    },
    "enncySearcher": {
        "label": "Enncy 题库",
        "icon": "cloud",
        "color": "#ec4899",
        "desc": "Enncy 在线题库 (https://tk.enncy.cn/)",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "enncySearcher"},
            {"key": "token", "label": "Token", "type": "password", "default": "", "placeholder": "Enncy 题库 Token", "required": True},
        ],
    },
    "cxSearcher": {
        "label": "网课小工具 (Go题)",
        "icon": "search",
        "color": "#3b82f6",
        "desc": "网课小工具题库 (https://cx.icodef.com/)",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "cxSearcher"},
            {"key": "token", "label": "Token", "type": "password", "default": "", "placeholder": "网课小工具 Token", "required": True},
        ],
    },
    "LemonSearcher": {
        "label": "柠檬题库",
        "icon": "citrus",
        "color": "#fbbf24",
        "desc": "柠檬题库 (https://www.lemtk.xyz)",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "LemonSearcher"},
            {"key": "token", "label": "Token", "type": "password", "default": "", "placeholder": "柠檬题库 Token", "required": True},
        ],
    },
    "TiKuHaiSearcher": {
        "label": "题库海",
        "icon": "waves",
        "color": "#14b8a6",
        "desc": "题库海搜索源",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "TiKuHaiSearcher"},
            {"key": "token", "label": "Token", "type": "password", "default": "", "placeholder": "题库海 Token"},
        ],
    },
    "LyCk6Searcher": {
        "label": "冷月题库",
        "icon": "moon",
        "color": "#6366f1",
        "desc": "冷月题库 (免费限制4秒一次请求)",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "LyCk6Searcher"},
            {"key": "token", "label": "Token", "type": "password", "default": "", "placeholder": "冷月题库 Token"},
        ],
    },
    "MukeSearcher": {
        "label": "Muke 题库",
        "icon": "graduation-cap",
        "color": "#ef4444",
        "desc": "Muke 题库搜索器",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "MukeSearcher"},
        ],
    },
    "JsonApiSearcher": {
        "label": "JSON API 搜题",
        "icon": "code",
        "color": "#0ea5e9",
        "desc": "JSON 格式 API 接口搜题",
        "fields": [
            {"key": "type", "label": "类型", "type": "hidden", "default": "JsonApiSearcher"},
            {"key": "url", "label": "API URL", "type": "url", "default": "", "placeholder": "http://example.com/api/search", "required": True},
            {"key": "q_field", "label": "题目参数名", "type": "text", "default": "question", "placeholder": "question"},
            {"key": "o_field", "label": "选项参数名 (可选)", "type": "text", "default": "", "placeholder": "留空表示不传选项"},
            {"key": "a_field", "label": "答案 JSONPath", "type": "text", "default": "$.data", "placeholder": "$.data", "required": True},
            {"key": "headers", "label": "自定义请求头 (JSON)", "type": "textarea", "default": "{}", "rows": 2},
        ],
    },
}


# ============================================================
# ConfigService
# ============================================================

CONFIG_PATH = Path("config.yml")
_CONFIG_LOCK = threading.Lock()


class ConfigService:
    """线程安全的 config.yml 读写服务"""

    @staticmethod
    def load() -> dict:
        """加载完整配置"""
        if not CONFIG_PATH.exists():
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @staticmethod
    def save(data: dict) -> None:
        """保存完整配置 (带锁)"""
        with _CONFIG_LOCK:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    @staticmethod
    def patch_section(section: str, data: dict) -> dict:
        """更新配置的某一个 section (深度合并)"""
        with _CONFIG_LOCK:
            current = ConfigService._load_locked()
            current[section] = {**current.get(section, {}), **data}
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(current, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return current

    @staticmethod
    def get_snapshot() -> dict:
        """获取线程安全的配置快照 (深拷贝，供 worker 使用)"""
        with _CONFIG_LOCK:
            return copy.deepcopy(ConfigService._load_locked())

    @staticmethod
    def _load_locked() -> dict:
        """内部: 加载配置 (调用方需持锁)"""
        if not CONFIG_PATH.exists():
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
