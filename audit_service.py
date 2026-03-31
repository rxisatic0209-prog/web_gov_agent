import logging
import os
import time
from typing import Any, Dict, List

from blacklist_service import BlacklistService
from LLM import LLM
from memory_store import AuditMemoryStore
from notifiers import NotificationMessage, build_notifier
from ReActEngine import ReActEngine
from ToolExecutor import ToolExecutor


class AuditService:
    def __init__(
        self,
        llm=None,
        tools_inst=None,
        tool_executor=None,
        engine=None,
        blacklist_service=None,
        memory_store=None,
        notifier=None,
    ):
        self.memory_store = memory_store or AuditMemoryStore()
        self.tool_executor = tool_executor or ToolExecutor(
            tools_inst=tools_inst,
            memory_store=self.memory_store,
            eager_login=False,
        )
        self.tools = tools_inst or self.tool_executor.tools
        self.llm = llm or LLM()
        self.engine = engine or ReActEngine(
            llm=self.llm,
            tool_executor=self.tool_executor,
        )
        self.blacklist_service = blacklist_service or BlacklistService(memory_store=self.memory_store)
        self.notifier = notifier or build_notifier(enable_console=False, enable_feishu=True, enable_mac=True)
        self.order_delay_seconds = int(os.getenv("AUDIT_ORDER_DELAY_SECONDS", "0"))

    def build_order_id(self, order: Dict[str, Any]) -> str:
        raw_order_id = order.get("id") or order.get("orderId")
        if raw_order_id:
            return str(raw_order_id)
        return "|".join(
            [
                str(order.get("buyer", "未知用户")),
                str(order.get("giftName", "N/A")),
                str(order.get("createdTime", "未知时间")),
            ]
        )

    def build_user_id(self, order: Dict[str, Any]) -> str:
        for key in ("uid", "userId", "memberId", "buyerId", "customerId"):
            if order.get(key):
                return str(order[key])
        return str(order.get("buyer", "未知用户"))

    def classify_report(self, report: str) -> str:
        normalized_report = str(report or "").strip()
        if not normalized_report or normalized_report.lower() == "none":
            return "待人工复核"
        if "引擎内部故障" in normalized_report or "审计中止" in normalized_report:
            return "待人工复核"
        if "[违规]" in normalized_report or "违规" in normalized_report:
            return "违规"
        if "[高风险待观察]" in normalized_report or "[高风险]" in normalized_report or "风险待观察" in normalized_report:
            return "高风险待观察"
        if "Finish[" not in normalized_report and "Final Answer:" not in normalized_report:
            return "待人工复核"
        return "合规"

    def build_result_title(self, status: str, is_blacklisted: bool) -> tuple[str, str]:
        if is_blacklisted:
            return "🚫 用户已在黑名单中", "⛔"
        if status == "待人工复核":
            return "📝 待人工复核", "🟠"
        if status == "违规":
            return "🚨 发现积分违规行为", "🔴"
        if status == "高风险待观察":
            return "⚠️ 风险待观察", "🟡"
        return "✅ 审计合规", "🟢"

    def build_notification(self, result: Dict[str, object]) -> NotificationMessage:
        title = str(result["title"])
        content = (
            f"判定状态: {result['emoji']} {result['title']}\n"
            f"买家昵称: {result['buyer']}\n"
            f"用户标识: {result['user_id']}\n"
            f"订单编号: {result['order_id']}\n"
            f"礼品名称: {result['gift_name']}\n"
            f"异常连续次数: {result['abnormal_streak']}\n"
            f"黑名单状态: {'是' if result['is_blacklisted'] else '否'}\n"
            f"------------------------------\n"
            f"🤖 AI 审计结论：\n{result['report']}"
        )
        return NotificationMessage(title=title, content=content)

    def audit_order(self, order: Dict[str, object], notify: bool = True) -> Dict[str, object]:
        order_id = self.build_order_id(order)
        existing_record = self.memory_store.get_record(order_id)
        if existing_record:
            return {
                "order_id": order_id,
                "user_id": existing_record.get("user_id") or self.build_user_id(order),
                "buyer": order.get("buyer", "未知用户"),
                "gift_name": order.get("giftName", "N/A"),
                "status": existing_record.get("status", "已处理"),
                "report": existing_record.get("report", ""),
                "abnormal_streak": existing_record.get("abnormal_streak", 0),
                "is_blacklisted": self.memory_store.is_blacklisted(
                    existing_record.get("user_id") or self.build_user_id(order)
                ),
                "skipped": True,
            }

        report = self.engine.run_audit(self.tools.format_order_for_audit(order))
        status = self.classify_report(report)
        evaluation = {
            "order_id": self.build_order_id(order),
            "user_id": self.build_user_id(order),
            "buyer": str(order.get("buyer", "未知用户")),
            "gift_name": str(order.get("giftName", "N/A")),
            "status": status,
            "report": report,
            "abnormal": status in ("违规", "高风险待观察"),
            "order_data": order,
        }
        blacklist_state = self.blacklist_service.apply_evaluation(evaluation)
        title, emoji = self.build_result_title(
            evaluation["status"],
            bool(blacklist_state["is_blacklisted"]),
        )

        self.memory_store.save_audit_record(
            order_id=evaluation["order_id"],
            user_id=evaluation["user_id"],
            order_data=evaluation["order_data"],
            report=evaluation["report"],
            status=evaluation["status"],
            abnormal=evaluation["abnormal"],
            abnormal_streak=int(blacklist_state["abnormal_streak"]),
        )

        result = {
            "order_id": evaluation["order_id"],
            "user_id": evaluation["user_id"],
            "buyer": evaluation["buyer"],
            "gift_name": evaluation["gift_name"],
            "status": evaluation["status"],
            "report": evaluation["report"],
            "abnormal": evaluation["abnormal"],
            "abnormal_streak": int(blacklist_state["abnormal_streak"]),
            "is_blacklisted": bool(blacklist_state["is_blacklisted"]),
            "auto_blacklisted": bool(blacklist_state["auto_blacklisted"]),
            "title": title,
            "emoji": emoji,
            "skipped": False,
        }

        if notify:
            self.notifier.notify(self.build_notification(result))

        return result

    def scan_once(self, size: int = 5, notify: bool = True) -> List[Dict[str, object]]:
        orders = self.tools.get_latest_orders(size=size)
        results = []
        for index, order in enumerate(orders):
            results.append(self.audit_order(order, notify=notify))
            if index < len(orders) - 1 and self.order_delay_seconds > 0:
                logging.info(f"⏳ 订单间限速保护：休眠 {self.order_delay_seconds} 秒后处理下一笔订单...")
                time.sleep(self.order_delay_seconds)
        return results
