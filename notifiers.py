import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass
class NotificationMessage:
    title: str
    content: str


class BaseNotifier:
    name = "base"

    def notify(self, message: NotificationMessage) -> None:
        raise NotImplementedError


class ConsoleNotifier(BaseNotifier):
    name = "console"

    def notify(self, message: NotificationMessage) -> None:
        logging.info(f"[{self.name}] {message.title}\n{message.content}")


class FeishuNotifier(BaseNotifier):
    name = "feishu"

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK")

    def notify(self, message: NotificationMessage) -> None:
        if not self.webhook_url:
            logging.warning("⚠️ 未配置 FEISHU_WEBHOOK，跳过飞书通知。")
            return

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": message.title,
                        "content": [[{"tag": "text", "text": message.content}]],
                    }
                }
            }
        }
        response = requests.post(self.webhook_url, json=payload, timeout=10)
        if response.status_code != 200:
            logging.error(f"❌ 飞书推送失败: {response.text}")


class MacNotifier(BaseNotifier):
    name = "mac"

    def notify(self, message: NotificationMessage) -> None:
        if sys.platform != "darwin":
            return
        safe_title = message.title.replace('"', '\\"')
        safe_content = message.content[:120].replace('"', '\\"')
        os.system(
            f"osascript -e 'display notification \"{safe_content}\" with title \"{safe_title}\" sound name \"Crystal\"'"
        )


class CompositeNotifier(BaseNotifier):
    name = "composite"

    def __init__(self, notifiers: Optional[List[BaseNotifier]] = None):
        self.notifiers = notifiers or []

    def notify(self, message: NotificationMessage) -> None:
        for notifier in self.notifiers:
            try:
                notifier.notify(message)
            except Exception as exc:
                logging.error(f"❌ 通知器 {notifier.name} 执行失败: {exc}")


def build_notifier(
    enable_console: bool = False,
    enable_feishu: bool = True,
    enable_mac: bool = True,
) -> CompositeNotifier:
    notifiers: List[BaseNotifier] = []
    if enable_console:
        notifiers.append(ConsoleNotifier())
    if enable_feishu:
        notifiers.append(FeishuNotifier())
    if enable_mac:
        notifiers.append(MacNotifier())
    return CompositeNotifier(notifiers)
