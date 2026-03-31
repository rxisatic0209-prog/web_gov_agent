import os
from typing import Dict, List, Optional

from openai import OpenAI


class LLM:
    """
    项目的 LLM 基建层。
    负责：
    - 构造 OpenAI 兼容客户端
    - 统一模型调用接口
    - 将业务层与具体 SDK 解耦
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        client: Optional[OpenAI] = None,
    ):
        self.model = model or os.getenv("LLM_MODEL_ID")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "60"))

        if client is not None:
            self.client = client
            return

        if not all([self.model, self.api_key, self.base_url]):
            raise ValueError("模型ID、API密钥和服务地址必须被提供或在环境变量中定义。")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )

    def think(self, messages: List[Dict[str, str]], temperature: float = 0.1) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
