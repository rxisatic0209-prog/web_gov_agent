import json

import requests
from bs4 import BeautifulSoup

class AuditTools:
    def __init__(self, executor):
        self.executor = executor

    def format_order_for_audit(self, order_data):
        """将原始订单转换为 AI 审计目标文本"""
        buyer = order_data.get('buyer', '未知')
        return (
            f"--- 待审计订单 ---\n"
            f"买家: {buyer} | 订单号: {order_data.get('id')}\n"
            f"礼品: {order_data.get('giftName')} | 备注: {order_data.get('describe', '无')}\n"
            f"请核查【{buyer}】的流水，判断其是否通过灌水、高频刷分等违规手段获取积分。"
        )

    def get_latest_orders(self, size=10):
        for attempt in range(2):
            token = self.executor.ensure_token(force_refresh=attempt > 0)
            if not token:
                return []

            headers = {"Authorization": token}
            try:
                resp = requests.get(
                    self.executor.order_api,
                    params={"pageIndex": 1, "pageSize": size},
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code == 200:
                    return resp.json().get("data", [])
                if resp.status_code not in (401, 403):
                    return []
            except Exception:
                return []
        return []

    def get_user_points(self, user_input):
        """核心审计工具：获取清洗后的流水"""
        user_name = str(user_input).strip().replace('"', '').replace("'", "")
        for attempt in range(2):
            token = self.executor.ensure_token(force_refresh=attempt > 0)
            if not token:
                return "Error: Token Missing"

            try:
                headers = {"Authorization": token}
                resp = requests.get(
                    self.executor.point_api,
                    params={"userName": user_name, "pageIndex": 1, "pageSize": 15},
                    headers=headers,
                )
                if resp.status_code in (401, 403) and attempt == 0:
                    continue

                raw_list = resp.json().get("data", [])
                if not raw_list:
                    return f"未找到用户 {user_name} 的记录。"

                clean_data = []
                for item in raw_list:
                    # 清洗 HTML 标签
                    clean_desc = BeautifulSoup(str(item.get("description", "")), "html.parser").get_text(strip=True)
                    clean_data.append({
                        "时间": item.get("createdTime"),
                        "事项": item.get("pointItemName"),
                        "金币": item.get("tradePoints"),
                        "描述": clean_desc[:40]
                    })
                return json.dumps(clean_data, ensure_ascii=False)
            except Exception as e:
                return f"查询失败: {e}"
        return f"查询失败: 用户 {user_name} 的鉴权已失效。"

    def get_audit_history(self, query_input):
        """查询历史审计记录，支持买家昵称、订单号、礼品名关键词"""
        query = str(query_input or "").strip().replace('"', '').replace("'", "")
        records = self.executor.memory_store.search_records(query=query, limit=5)
        if not records:
            return "未找到匹配的历史审计记录。"

        compact_records = []
        for item in records:
            compact_records.append({
                "订单号": item.get("order_id"),
                "用户标识": item.get("user_id"),
                "买家": item.get("buyer"),
                "礼品": item.get("gift_name"),
                "状态": item.get("status"),
                "连续异常次数": item.get("abnormal_streak", 0),
                "审计时间": item.get("audited_at"),
                "结论": item.get("report", "")[:200]
            })
        return json.dumps(compact_records, ensure_ascii=False)


def get_tools_map(inst):
    return {
        "get_latest_orders": inst.get_latest_orders,
        "get_user_points": inst.get_user_points,
        "get_audit_history": inst.get_audit_history,
    }
