import argparse
import csv
import logging
import os
import sys
import time

from dotenv import load_dotenv, set_key

from audit_service import AuditService
from blacklist_service import BlacklistService
from LLM import LLM
from memory_store import AuditMemoryStore
from notifiers import build_notifier
from ReActEngine import ReActEngine
from ToolExecutor import ToolExecutor


DEFAULT_AUTO_INTERVAL = 24 * 60 * 60


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - 🤖 - %(message)s'
)


def setup_config(require_api_key=True, require_webhook=False):
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("")

    load_dotenv()

    print("\n" + " 🛡️  XREAL 智能审计系统配置 ".center(50, "="))

    if require_api_key and not os.getenv("LLM_API_KEY"):
        print("\n🔑 检测到未配置 LLM API KEY")
        api_key = input("👉 请输入您的 API KEY: ").strip()
        if api_key:
            set_key(env_path, "LLM_API_KEY", api_key)
            os.environ["LLM_API_KEY"] = api_key
        else:
            print("❌ 错误：必须提供 API KEY 才能运行。")
            sys.exit(1)

    if require_webhook and not os.getenv("FEISHU_WEBHOOK"):
        print("\n📢 检测到未配置飞书机器人 Webhook")
        webhook = input("👉 请输入 Webhook 地址 (留空则仅在本地运行): ").strip()
        if webhook:
            set_key(env_path, "FEISHU_WEBHOOK", webhook)
            os.environ["FEISHU_WEBHOOK"] = webhook

    print("\n✅ 配置完成。")
    print("=" * 50 + "\n")


def build_arg_parser():
    parser = argparse.ArgumentParser(description="XREAL 积分审计机器人")
    parser.add_argument(
        "--mode",
        choices=("manual", "auto"),
        default="manual",
        help="manual 为手动巡查一次，auto 为自动巡查",
    )
    parser.add_argument("--interval", type=int, default=None, help="自动巡查间隔，单位秒")
    parser.add_argument("--size", type=int, default=5, help="每次扫描拉取的订单数量")
    parser.add_argument("--history", nargs="?", const="", default=None, help="查询历史审计记录")
    parser.add_argument("--history-limit", type=int, default=10, help="历史查询返回数量")
    parser.add_argument("--blacklist", action="store_true", help="显示当前黑名单")
    parser.add_argument("--add-blacklist", default=None, help="手动加入黑名单的用户标识")
    parser.add_argument("--blacklist-name", default="", help="手动加入黑名单时的用户名称")
    parser.add_argument("--blacklist-reason", default="手动加入黑名单", help="手动黑名单原因")
    parser.add_argument("--remove-blacklist", default=None, help="移出黑名单的用户标识")
    parser.add_argument("--no-feishu", action="store_true", help="禁用飞书通知")
    parser.add_argument("--with-console-notifier", action="store_true", help="开启控制台通知插件")
    parser.add_argument("--export-csv", action="store_true", help="将本次巡查结果导出为人工复核 CSV")
    return parser


def print_history(records):
    if not records:
        print("📚 暂无匹配的历史审计记录。")
        return

    print(f"📚 命中 {len(records)} 条历史审计记录：")
    for item in records:
        print("-" * 50)
        print(f"订单号: {item.get('order_id')}")
        print(f"用户标识: {item.get('user_id')}")
        print(f"买家: {item.get('buyer')}")
        print(f"礼品: {item.get('gift_name')}")
        print(f"状态: {item.get('status')}")
        print(f"连续异常次数: {item.get('abnormal_streak', 0)}")
        print(f"时间: {item.get('audited_at')}")
        print(f"结论: {item.get('report')}")


def print_blacklist(records):
    if not records:
        print("🚫 当前没有激活的黑名单用户。")
        return

    print(f"🚫 当前黑名单共 {len(records)} 人：")
    for item in records:
        print("-" * 50)
        print(f"用户标识: {item.get('user_id')}")
        print(f"用户名称: {item.get('user_name')}")
        print(f"来源: {item.get('source')}")
        print(f"原因: {item.get('reason')}")
        print(f"更新时间: {item.get('updated_at')}")


def run_scan(service: AuditService, size: int, notify: bool):
    current_time = time.strftime("%H:%M:%S")
    print(f"📡 [{current_time}] 系统：正在扫描商城最新订单...")
    results = service.scan_once(size=size, notify=notify)

    if not results:
        print("☕ 系统：暂无可处理订单。")
        return results

    processed_count = sum(1 for item in results if not item["skipped"])
    skipped_count = len(results) - processed_count
    print(f"🚨 系统：本轮拉取 {len(results)} 笔订单，新增处理 {processed_count} 笔，跳过已处理 {skipped_count} 笔。")

    for item in results:
        if item["skipped"]:
            print(f"⏭️  已跳过：订单 {item['order_id']} 已存在历史记录。")
            continue

        print(f"\n{'—' * 15} 🔍 已审计：{item['buyer']} {'—' * 15}")
        print(f"用户标识：{item['user_id']}")
        print(f"订单号：{item['order_id']}")
        print(f"礼品：{item['gift_name']}")
        print(f"结论：{item['title']}")
        print(f"连续异常次数：{item['abnormal_streak']}")
        print(f"黑名单：{'是' if item['is_blacklisted'] else '否'}")
        print("—" * 50)

    return results


def export_results_to_csv(results, output_path=None):
    export_dir = os.path.abspath("./data/exports")
    os.makedirs(export_dir, exist_ok=True)

    if not output_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(export_dir, f"manual_review_{timestamp}.csv")

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "订单号",
                "用户标识",
                "买家",
                "礼品",
                "系统判定",
                "连续异常次数",
                "是否在黑名单",
                "是否自动入黑名单",
                "是否跳过历史记录",
                "AI审计结论",
                "人工复核结果",
                "是否命中",
                "备注",
            ],
        )
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    "订单号": item.get("order_id"),
                    "用户标识": item.get("user_id"),
                    "买家": item.get("buyer"),
                    "礼品": item.get("gift_name"),
                    "系统判定": item.get("status"),
                    "连续异常次数": item.get("abnormal_streak", 0),
                    "是否在黑名单": "是" if item.get("is_blacklisted") else "否",
                    "是否自动入黑名单": "是" if item.get("auto_blacklisted") else "否",
                    "是否跳过历史记录": "是" if item.get("skipped") else "否",
                    "AI审计结论": item.get("report", ""),
                    "人工复核结果": "",
                    "是否命中": "",
                    "备注": "",
                }
            )

    return output_path


def main():
    args = build_arg_parser().parse_args()
    memory_store = AuditMemoryStore()
    blacklist_service = BlacklistService(memory_store=memory_store)

    if args.history is not None:
        print_history(memory_store.search_records(query=args.history, limit=args.history_limit))
        return

    if args.blacklist:
        print_blacklist(blacklist_service.list_blacklist())
        return

    if args.add_blacklist:
        blacklist_service.add_manual(args.add_blacklist, args.blacklist_name, args.blacklist_reason)
        print(f"✅ 用户 {args.add_blacklist} 已加入黑名单。")
        return

    if args.remove_blacklist:
        blacklist_service.remove(args.remove_blacklist)
        print(f"✅ 用户 {args.remove_blacklist} 已移出黑名单。")
        return

    setup_config(require_api_key=True, require_webhook=not args.no_feishu)

    try:
        notifier = build_notifier(
            enable_console=args.with_console_notifier,
            enable_feishu=not args.no_feishu,
            enable_mac=True,
        )
        llm = LLM()
        tool_executor = ToolExecutor(memory_store=memory_store, eager_login=False)
        react_engine = ReActEngine(llm=llm, tool_executor=tool_executor)
        service = AuditService(
            llm=llm,
            tool_executor=tool_executor,
            engine=react_engine,
            memory_store=memory_store,
            blacklist_service=blacklist_service,
            notifier=notifier,
        )

        results = run_scan(service, size=args.size, notify=True)
        if args.export_csv:
            export_path = export_results_to_csv(results)
            print(f"🧾 巡查结果已导出：{export_path}")
        if args.mode == "manual":
            print("🧾 手动巡查完成，程序已退出。")
            return

        check_interval = args.interval or int(os.getenv("CHECK_INTERVAL", str(DEFAULT_AUTO_INTERVAL)))
        while True:
            print(f"💤 自动巡查模式已启用，{check_interval / 3600:.1f} 小时后进行下一次检查...")
            time.sleep(check_interval)
            results = run_scan(service, size=args.size, notify=True)
            if args.export_csv:
                export_path = export_results_to_csv(results)
                print(f"🧾 巡查结果已导出：{export_path}")

    except KeyboardInterrupt:
        print("\n👋 收到停止信号，机器人已安全线下。")
    except Exception as e:
        print(f"\n❌ 系统运行发生严重错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
