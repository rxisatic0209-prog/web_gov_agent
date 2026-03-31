import logging
import os
import time
from typing import Optional

from playwright.sync_api import sync_playwright

from memory_store import AuditMemoryStore
from tools import AuditTools, get_tools_map

class ToolExecutor:
    def __init__(self, tools_inst=None, memory_store=None, eager_login: bool = False):
        self.memory_store = memory_store or AuditMemoryStore()
        self.token: Optional[str] = None
        self.order_api = os.getenv("ORDER_API_REAL")
        self.point_api = os.getenv("POINT_API_REAL")
        self.login_url = os.getenv("LOGIN_PAGE_URL")
        self.webhook_url = os.getenv("FEISHU_WEBHOOK")
        self.data_dir = os.path.abspath("./data")
        os.makedirs(self.data_dir, exist_ok=True)

        self.tools = tools_inst or AuditTools(executor=self)
        self._registry = get_tools_map(self.tools)
        logging.info(f"🛠️ 工具箱初始化完成，已加载: {list(self._registry.keys())}")

        if eager_login:
            self.ensure_token()

    def ensure_token(self, force_refresh: bool = False) -> Optional[str]:
        if self.token and not force_refresh:
            return self.token

        self.token = None

        logging.info("🔑 正在检查登录状态...")
        try:
            with sync_playwright() as p:
                context_dir = os.path.join(self.data_dir, "pw_session")
                context = p.chromium.launch_persistent_context(
                    context_dir,
                    headless=False,
                    slow_mo=500,
                )
                page = context.new_page()

                if page.url != self.login_url:
                    page.goto(self.login_url)

                for _ in range(60):
                    cookies = context.cookies()
                    for cookie in cookies:
                        if cookie["name"] == "user-Token" and cookie["value"] != "null":
                            self.token = cookie["value"]
                            logging.info("✅ Token 拦截成功！")
                            break
                    if self.token:
                        break
                    time.sleep(2)

                context.close()
        except Exception as exc:
            logging.error(f"❌ Playwright 运行异常: {exc}")

        return self.token

    def refresh_token(self) -> Optional[str]:
        return self.ensure_token(force_refresh=True)

    def execute(self, tool_name, tool_input):
        """
        执行工具的具体逻辑
        """
        # 移除可能存在的空格或换行
        tool_name = tool_name.strip()
        
        if tool_name not in self._registry:
            logging.error(f"❌ 引擎尝试调用不存在的工具: {tool_name}")
            return f"错误: 工具 '{tool_name}' 未注册。可用工具: {list(self._registry.keys())}"
        
        try:
            # 执行对应的函数
            logging.info(f"⚙️ 正在执行工具: {tool_name}")
            func = self._registry[tool_name]
            return func(tool_input)
        except Exception as e:
            logging.error(f"❌ 执行工具 {tool_name} 时发生异常: {str(e)}")
            return f"工具执行出错: {str(e)}"
