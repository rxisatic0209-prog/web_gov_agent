from dataclasses import dataclass
from typing import Any, Dict

from ReActEngine import ReActEngine
from tools import AuditTools


@dataclass
class EvaluationResult:
    order_id: str
    user_id: str
    buyer: str
    gift_name: str
    status: str
    report: str
    abnormal: bool
    order_data: Dict[str, Any]


class BehaviorEvaluator:
    def __init__(self, tools_inst=None, engine=None):
        self.tools = tools_inst or AuditTools(eager_login=False)
        self.engine = engine or ReActEngine(tools_inst=self.tools)

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

    def evaluate(self, order: Dict[str, Any]) -> EvaluationResult:
        report = self.engine.run_audit(self.tools.format_order_for_audit(order))
        status = self.classify_report(report)
        return EvaluationResult(
            order_id=self.build_order_id(order),
            user_id=self.build_user_id(order),
            buyer=str(order.get("buyer", "未知用户")),
            gift_name=str(order.get("giftName", "N/A")),
            status=status,
            report=report,
            abnormal=status in ("违规", "高风险待观察"),
            order_data=order,
        )
