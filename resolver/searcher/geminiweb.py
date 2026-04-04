import json

import gemini_webapi.constants

import config as cfg
import httpx
import asyncio
from gemini_webapi import GeminiClient
from gemini_webapi.constants import Model
from cxapi.schema import QuestionModel
from . import SearcherBase, SearcherResp
from logger import Logger


class GeminiWebSearcher(SearcherBase):
    """Gemini Web 在线答题器"""
    client: GeminiClient
    config: dict

    def __init__(self, **config) -> None:
        super().__init__()
        self.client = None
        self.chat = None
        self.config = config
        self.give_system_prompt = False
        self.logger = Logger("GeminiWebSearcher")
        self.system_prompt = self.config["system_prompt"]
        if self.config["model"] == "G-3.1-PRO":
            self.model = Model.G_3_1_PRO
        elif self.config["model"] == "G-3.0-FLASH-THINKING":
            self.model = Model.G_3_0_FLASH_THINKING
        elif self.config["model"] == "G-3.0-FLASH":
            self.model = Model.G_3_0_FLASH
        else:
            self.model = Model.G_3_0_FLASH

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.gemini_init())

    async def gemini_init(self):
        proxy = None
        if self.config["proxy_enable"]:
            proxy = self.config["proxy"]

            self.logger.info(f"GeminiWeb 客户端已配置代理: {proxy}")
        self.client = GeminiClient(self.config["Secure_1PSID"], self.config["Secure_1PSIDTS"], proxy=proxy)
        await self.client.init(timeout=30, auto_close=False, close_delay=300, auto_refresh=True)
        self.chat = self.client.start_chat(model=self.model)

    async def gemini(self,question,in_chat_session=True):
        if in_chat_session:
            if not self.give_system_prompt:
                await self.chat.send_message(self.system_prompt)
                self.give_system_prompt = True
            response = await self.chat.send_message(
                str(self.config["prompt"]).format(
                    type=question.type.name,
                    value=question.value,
                    options=json.dumps(question.options),
                )
            )
        else:
            response = await self.client.generate_content(
                self.system_prompt + '------------' +
                str(self.config["prompt"]).format(
                    type=question.type.name,
                    value=question.value,
                    options=json.dumps(question.options),
                ),model=self.model
            )

        return response.text


    def invoke(self, question: QuestionModel) -> SearcherResp:

        # self.logger.info("传入的question.options" + json.dumps(question.options))

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
            response = self.loop.run_until_complete(self.gemini(question, in_chat_session=False))
            self.logger.info("返回结果: "+response)
            if response is None:
                # 防止预处理时报错
                response = ''
        except Exception as err:
            return SearcherResp(-500, err.__str__(), self, question.value, None)

        # 单选题需要进一步预处理AI返回结果，以使 QuestionResolver 能正确命中
        if question.type.value == 0:
            response = response.strip()  # A. insurance
            for k, v in question.options.items():
                # 单独选项、或者包含 insurance
                if response == k or (v in response):
                    response = v
                    break
        # 多选同理
        if question.type.value == 1:
            choice = response.strip().split(',')
            awa = ""
            for k, v in question.options.items():
                if k in choice or v in response:
                    awa += v + "#"
            response = awa

        return SearcherResp(0, "", self, question.value, response)
