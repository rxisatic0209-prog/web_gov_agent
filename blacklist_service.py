from typing import Dict, List

from memory_store import AuditMemoryStore


class BlacklistService:
    def __init__(self, memory_store=None, threshold: int = 2):
        self.memory_store = memory_store or AuditMemoryStore()
        self.threshold = max(1, int(threshold))

    def apply_evaluation(self, evaluation) -> Dict[str, object]:
        streak = self.memory_store.update_user_state(
            user_id=evaluation.user_id,
            user_name=evaluation.buyer,
            status=evaluation.status,
            report=evaluation.report,
            abnormal=evaluation.abnormal,
        )

        auto_blacklisted = False
        if evaluation.abnormal and streak >= self.threshold and not self.memory_store.is_blacklisted(evaluation.user_id):
            self.memory_store.add_to_blacklist(
                user_id=evaluation.user_id,
                user_name=evaluation.buyer,
                reason=f"连续检测 {streak} 次异常行为",
                source="system",
            )
            auto_blacklisted = True

        return {
            "abnormal_streak": streak,
            "is_blacklisted": self.memory_store.is_blacklisted(evaluation.user_id),
            "auto_blacklisted": auto_blacklisted,
            "threshold": self.threshold,
        }

    def list_blacklist(self, active_only: bool = True) -> List[Dict[str, object]]:
        return self.memory_store.list_blacklist(active_only=active_only)

    def add_manual(self, user_id: str, user_name: str, reason: str) -> None:
        self.memory_store.add_to_blacklist(
            user_id=str(user_id).strip(),
            user_name=str(user_name).strip() or str(user_id).strip(),
            reason=str(reason).strip() or "手动加入黑名单",
            source="manual",
        )

    def remove(self, user_id: str) -> None:
        self.memory_store.remove_from_blacklist(str(user_id).strip())
