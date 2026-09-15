import json
from openai import OpenAI
from core import config as cfg
import httpx
from cxapi.schema import QuestionModel
from . import SearcherBase, SearcherResp
from core.logger import Logger

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_PROMPT = "请回答下这个{type}：\n{value}\n{options}"
_DEFAULT_SYSTEM_PROMPT = (
    "你是一位专业的学习通题目答题助手。\n\n"
    "请严格遵循以下规则作答：\n"
    " - 单选题：只输出选项字母\n"
    " - 判断题：只输出「对」或「错」\n"
    " - 多选题：只输出选项字母，用英文逗号分隔(至少两个)\n\n"
    "请确保每个选择都严格符合题干限定的主题范围，不扩大不缩小。只回复答案，不要输出除答案以外任何内容。"
)


class OpenAISearcher(SearcherBase):
    """ChatGPT 在线答题器

    配置项: api_key(必填), base_url / model / system_prompt / prompt / tools / tool_choice(可选)
    """

    #: 搜索器加载器使用的参数表
    CONFIG_KEYS = {"api_key", "base_url", "model", "system_prompt", "prompt", "tools", "tool_choice"}
    REQUIRED_CONFIG_KEYS = {"api_key"}

    client: OpenAI
    config: dict

    def __init__(self, **config) -> None:
        super().__init__()
        # 留空的配置项回退默认值
        self.config = {
            **config,
            "base_url": config.get("base_url") or _DEFAULT_BASE_URL,
            "model": config.get("model") or _DEFAULT_MODEL,
            "prompt": config.get("prompt") or _DEFAULT_PROMPT,
            "system_prompt": config.get("system_prompt") or _DEFAULT_SYSTEM_PROMPT,
        }
        self.logger = Logger("OpenAISearcher")
        # 强制客户端忽略 Clash 等系统代理
        proxy_url = None
        if cfg.HTTP_EN:
            raw = cfg.HTTP
            if isinstance(raw, list) and raw:
                proxy_url = raw[0]
            elif isinstance(raw, str) and raw:
                proxy_url = raw
            if proxy_url:
                self.logger.info(f"OpenAI 客户端已配置代理: {proxy_url}")

        http_client = httpx.Client(trust_env=False, proxy=proxy_url)

        self.client = OpenAI(
            api_key=self.config["api_key"],
            base_url=self.config["base_url"],
            http_client=http_client,
        )

    def invoke(self, question: QuestionModel) -> SearcherResp:

        #self.logger.info("传入的question.options" + json.dumps(question.options))

        # 将选项从JSON转换成人类(GPT)易读形式
        options_str = ""
        if type(question.options) is not None:
            options_str = "选项：\n"
            if type(question.options) is dict:
                for k, v in question.options.items():
                    options_str += k + ". " + v + ";"
            elif type(question.options) is list:
                for v in question.options:
                    options_str += v + ";"

        self.logger.info(
            "从 "
            + self.config["prompt"]
            + " 生成提问："
            + str(self.config["prompt"]).format(
                type=question.type.name,
                value=question.value,
                options=options_str,
            ),
        )
        try:
            # 构建调用参数
            api_args = {
                "model": self.config["model"],
                "temperature": 0.2,  # 答题场景适合把temperature调低
                "messages": [
                    {"role": "system", "content": self.config["system_prompt"]},
                    {
                        "role": "user",
                        "content": str(self.config["prompt"]).format(
                            type="单选题",
                            value="国家安全能力是国家（）表现出来的治理效能。",
                            options="选项：\nA. 经济体系;B. 文化体系;C. 科学体系;D. 安全体系;",
                        )
                    },# 这里给个单选题回复示例供 AI 模仿
                    {"role": "assistant", "content": "D"},
                    {
                        "role": "user",
                        "content": str(self.config["prompt"]).format(
                            type="多选题",
                            value="我国国家安全形势更趋复杂，从国内来看面临的风险挑战有()",
                            options="选项：\nA. 发展不平衡不充分问题仍然突出;B. 科技创新能力强;C. 意识形态领域存在不少挑战;D. 生态环境保护任务轻松;",
                        )
                    },  # 这里给个多选题回复示例供 AI 模仿
                    {"role": "assistant", "content": "A,C"},
                    #多选题示例
                    {
                        "role": "user",
                        "content": str(self.config["prompt"]).format(
                            type=question.type.name,
                            value=question.value,
                            options=options_str,
                        ),
                    },
                ],
            }

            # 如果配置了 tools，则加入调用参数
            if "tools" in self.config and self.config["tools"]:
                api_args["tools"] = self.config["tools"]
                if "tool_choice" in self.config and self.config["tool_choice"]:
                    api_args["tool_choice"] = self.config["tool_choice"]

            response = self.client.chat.completions.create(**api_args)

            # 优先处理 tool_calls 返回（如果模型调用了 function）
            choice = response.choices[0]
            if choice.message.tool_calls:
                tool_call = choice.message.tool_calls[0]
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                    # 尝试从 tool 参数中提取答案（常见字段名：answer / result / response）
                    response = tool_args.get("answer") or tool_args.get("result") or tool_args.get("response") or ""
                except (json.JSONDecodeError, KeyError) as e:
                    self.logger.warning(f"解析 tool_calls 参数失败: {e}")
                    response = choice.message.content or ""
            else:
                response = choice.message.content

            if response is None :
                # 防止预处理时报错
                response = ''
        except Exception as err:
            return SearcherResp(-500, err.__str__(), self, question.value, None)

        # 单选题需要进一步预处理AI返回结果，以使 QuestionResolver 能正确命中
        if question.type.value == 0:
            response = response.strip()# A. insurance
            for k, v in question.options.items():
                #单独选项、或者包含 insurance
                if response == k or (v in response):
                    response = v
                    break
        # 多选同理 
        if question.type.value == 1:
            choice = response.strip().split(',')
            awa = ""
            for k, v in question.options.items():
                if k in choice or v in response:
                    awa += v+"#"
            response = awa
        
        self.logger.info("返回结果：" + response)
        return SearcherResp(0, "", self, question.value, response)
