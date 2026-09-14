"""基于章节视频转录文稿的 AI 搜索器

答题前由主线程把当前章节 ``knowledge_id`` 写入 ``transcript.context``,
本搜索器取出该章节的拼合文稿(章节内所有视频的转录全文), 连同题目交给
OpenAI 兼容 API 作答。

弃权而非阻塞: 文稿未就绪时按 ``wait_ready`` 等待, 超时返回未匹配结果,
不影响主流程与其他题库搜索器(见 docs/video-transcript-plan.md §7)。
"""

from __future__ import annotations

import json
from typing import Optional

import httpx
from openai import OpenAI

import config as cfg
from cxapi.schema import QuestionModel
from logger import Logger
from transcript import context
from transcript.worker import get_worker, is_enabled

from . import SearcherBase, SearcherResp

_DEFAULT_MAX_CONTEXT_CHARS = 24000
_DEFAULT_WAIT_READY = 30.0

_DEFAULT_SYSTEM_PROMPT = """你是一位专业的学习通题目答题助手，你会拿到一段【课程视频文稿】和一道题目。

请严格遵循以下规则作答：

1. 文稿来自语音识别(ASR)，可能存在错别字、术语误转、同音字错误或断句错误；遇到可疑字词请结合上下文与学科常识推断其真实含义。
2. 只有当文稿中明确含有作答依据时才依据文稿作答；若文稿与该题无关或不足以判断，请依靠你自己的学科知识作答，不要强行牵强附会。
3. 请确保每个选择都严格符合题干限定的主题范围，不扩大不缩小。
4. 多选题至少选择两个正确选项，选项字母用英文逗号分隔。

输出格式：
- 单选题：只输出选项字母
- 多选题：只输出选项字母，用英文逗号分隔
- 判断题：只输出“对”或“错”
- 填空题：只输出填空内容，多个空用“#”分隔

只回复答案，不要输出除答案以外任何内容。"""

_DEFAULT_PROMPT = """请根据下面的课程视频文稿回答这个{type}：

【课程视频文稿】
{transcript}

【题目】
{value}

{options}"""


def _shrink_text(text: str, limit: int) -> tuple[str, bool]:
    """超长文稿裁剪, 保留首尾两段

    Args:
        text: 文稿全文
        limit: 最大字符数
    Returns:
        tuple[str, bool]: (裁剪后的文稿, 是否发生裁剪)
    """
    if limit <= 0 or len(text) <= limit:
        return text, False
    head = int(limit * 0.6)
    tail = limit - head
    return f"{text[:head]}\n\n……(文稿过长, 中间部分已省略)……\n\n{text[-tail:]}", True


def _format_options(question: QuestionModel) -> str:
    """把选项渲染为人类/模型易读形式"""
    options = question.options
    if not options:
        return ""
    if isinstance(options, dict):
        return "选项：\n" + "".join(f"{key}. {value};\n" for key, value in options.items())
    if isinstance(options, list):
        return "选项：\n" + "".join(f"{value};\n" for value in options)
    return ""


class TranscriptAISearcher(SearcherBase):
    """章节视频文稿 + OpenAI 兼容 API 答题器"""

    def __init__(self, **config) -> None:
        super().__init__()
        self.config = config
        self.logger = Logger("TranscriptAISearcher")
        self.client = self._build_client()

    def _build_client(self) -> OpenAI:
        """构造 OpenAI 客户端(强制忽略 Clash 等系统代理, 与 OpenAISearcher 一致)"""
        proxy_url: Optional[str] = None
        if cfg.HTTP_EN:
            raw = cfg.HTTP
            if isinstance(raw, list) and raw:
                proxy_url = raw[0]
            elif isinstance(raw, str) and raw:
                proxy_url = raw
            if proxy_url:
                self.logger.info(f"客户端已配置代理: {proxy_url}")
        http_client = httpx.Client(trust_env=False, proxy=proxy_url)
        return OpenAI(
            api_key=self.config["api_key"],
            base_url=self.config["base_url"],
            http_client=http_client,
        )

    def _build_messages(self, question: QuestionModel, transcript: str) -> list[dict]:
        """构造对话消息

        使用纯字符串替换而非 ``str.format``, 避免自定义模板里的花括号引发异常。

        Args:
            question: 题目
            transcript: 章节文稿
        Returns:
            list[dict]: OpenAI messages
        """
        system_prompt = str(self.config.get("system_prompt") or _DEFAULT_SYSTEM_PROMPT)
        template = str(self.config.get("prompt") or _DEFAULT_PROMPT)
        options_str = _format_options(question)
        body = template
        for placeholder, value in (
            ("{type}", question.type.name),
            ("{value}", question.value),
            ("{options}", options_str),
            ("{transcript}", transcript),
        ):
            body = body.replace(placeholder, str(value))
        if "{transcript}" not in template:
            body = f"【课程视频文稿】\n{transcript}\n\n{body}"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": body},
        ]

    def _postprocess(self, response: str, question: QuestionModel) -> str:
        """把模型输出规整为 QuestionResolver.fill 能命中的形式

        Args:
            response: 模型原始输出
            question: 题目
        Returns:
            str: 规整后的答案
        """
        response = (response or "").strip()
        options = question.options
        match question.type.value:
            case 0 if isinstance(options, dict):  # 单选题 -> 返回选项原文
                for key, value in options.items():
                    if response == key or value in response:
                        return str(value)
                return response
            case 1 if isinstance(options, dict):  # 多选题 -> 以 # 连接选项原文
                choices = [part.strip() for part in response.replace("，", ",").split(",") if part.strip()]
                answer = "".join(
                    f"{value}#"
                    for key, value in options.items()
                    if key in choices or value in response
                )
                return answer or response
            case 3:  # 判断题 -> 统一为 对 / 错
                if response in ("对", "正确", "是", "true", "True", "√", "T"):
                    return "对"
                if response in ("错", "错误", "否", "false", "False", "×", "F"):
                    return "错"
                return response
            case _:
                return response
    def invoke(self, question: QuestionModel) -> SearcherResp:
        """调用接口

        Args:
            question: 题目数据模型
        Returns:
            SearcherResp: 搜索器响应, 弃权时 code != 0
        """
        if not is_enabled():
            return SearcherResp(-404, "视频转录管道未开启, 本轮弃权", self, question.value, None)

        knowledge_id = context.get_current_knowledge_id()
        if knowledge_id is None:
            return SearcherResp(-404, "未进入章节答题上下文, 本轮弃权", self, question.value, None)

        wait_ready = float(self.config.get("wait_ready", _DEFAULT_WAIT_READY) or 0)
        # 该章节已无待处理转录任务时(从未入队/已全部失败)不再空等
        if wait_ready > 0 and not get_worker().has_pending_for(knowledge_id):
            wait_ready = 0
        transcript = context.wait_for_text(knowledge_id, wait_ready)
        if not transcript:
            self.logger.warning(
                f"章节 {knowledge_id} 文稿未就绪(等待 {wait_ready}s), 本轮弃权"
            )
            return SearcherResp(
                -404,
                f"章节 {knowledge_id} 视频文稿未就绪, 本轮弃权",
                self,
                question.value,
                None,
            )

        limit = int(self.config.get("max_context_chars", _DEFAULT_MAX_CONTEXT_CHARS) or 0)
        transcript, truncated = _shrink_text(transcript, limit)
        if truncated:
            self.logger.warning(f"章节 {knowledge_id} 文稿超长, 已裁剪至 {limit} 字符")

        try:
            response = self.client.chat.completions.create(
                model=self.config["model"],
                temperature=0.2,  # 答题场景适合把 temperature 调低
                messages=self._build_messages(question, transcript),
            )
            choice = response.choices[0]
            if choice.message.tool_calls:
                try:
                    tool_args = json.loads(choice.message.tool_calls[0].function.arguments)
                    content = (
                        tool_args.get("answer")
                        or tool_args.get("result")
                        or tool_args.get("response")
                        or ""
                    )
                except (json.JSONDecodeError, KeyError) as err:
                    self.logger.warning(f"解析 tool_calls 参数失败: {err}")
                    content = choice.message.content or ""
            else:
                content = choice.message.content or ""
        except Exception as err:  # noqa: BLE001 - 搜索器失败必须降级为未匹配
            return SearcherResp(-500, err.__str__(), self, question.value, None)

        answer = self._postprocess(content, question)
        if not answer:
            return SearcherResp(-500, "模型返回空答案", self, question.value, None)
        self.logger.info(f"文稿作答 -> {answer}")
        return SearcherResp(0, "", self, question.value, answer)


__all__ = ["TranscriptAISearcher"]