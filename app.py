import os

import streamlit as st

from audit_service import AuditService
from blacklist_service import BlacklistService
from memory_store import AuditMemoryStore
from notifiers import build_notifier


DEFAULT_AUTO_INTERVAL = 24 * 60 * 60


@st.cache_resource
def get_store() -> AuditMemoryStore:
    return AuditMemoryStore()


@st.cache_resource
def get_blacklist_service() -> BlacklistService:
    return BlacklistService(memory_store=get_store())


@st.cache_resource
def get_audit_service(enable_feishu: bool, enable_console: bool) -> AuditService:
    notifier = build_notifier(
        enable_console=enable_console,
        enable_feishu=enable_feishu,
        enable_mac=True,
    )
    return AuditService(
        memory_store=get_store(),
        blacklist_service=get_blacklist_service(),
        notifier=notifier,
    )


def render_history_table(records):
    if not records:
        st.info("暂无记录。")
        return
    st.dataframe(records, use_container_width=True)


def render_blacklist_table(records):
    if not records:
        st.info("当前没有激活的黑名单用户。")
        return
    st.dataframe(records, use_container_width=True)


def main():
    st.set_page_config(page_title="XREAL 审计控制台", layout="wide")
    st.title("XREAL 审计控制台")
    st.caption("模块：用户行为评判系统 / 黑名单系统 / 通知器插件系统")

    mode = st.sidebar.radio("巡查模式", ("手动巡查", "自动巡查"))
    scan_size = st.sidebar.number_input("每次拉取订单数", min_value=1, max_value=50, value=5)
    auto_hours = st.sidebar.number_input("自动巡查间隔（小时）", min_value=1, max_value=168, value=24)
    enable_feishu = st.sidebar.checkbox("启用飞书通知插件", value=bool(os.getenv("FEISHU_WEBHOOK")))
    enable_console = st.sidebar.checkbox("启用控制台通知插件", value=False)

    st.sidebar.markdown("### 模式说明")
    if mode == "手动巡查":
        st.sidebar.info("点击页面按钮时执行一次巡查，执行完成后停止。")
    else:
        st.sidebar.info("自动巡查是用户主动选择的模式，不是默认行为。")
        st.sidebar.code(f"python3 main.py --mode auto --interval {int(auto_hours * 3600)}")

    audit_service = get_audit_service(enable_feishu, enable_console)
    blacklist_service = get_blacklist_service()
    store = get_store()

    tab_scan, tab_blacklist, tab_history = st.tabs(["巡查面板", "黑名单管理", "历史记录"])

    with tab_scan:
        st.subheader("用户行为评判系统")
        col1, col2, col3 = st.columns(3)
        col1.metric("当前模式", mode)
        col2.metric("自动巡查间隔", f"{auto_hours} 小时")
        col3.metric("黑名单阈值", "连续 2 次异常")

        if st.button("执行一次手动巡查", type="primary"):
            with st.spinner("正在巡查订单并评判用户行为..."):
                results = audit_service.scan_once(size=int(scan_size), notify=True)
            st.success(f"巡查完成，共处理 {len(results)} 笔订单。")
            render_history_table(results)

        st.markdown("### 自动巡查")
        st.write("自动巡查仅在你明确选择时启用。推荐通过命令行常驻运行：")
        st.code(f"python3 main.py --mode auto --interval {int(auto_hours * 3600)}")

    with tab_blacklist:
        st.subheader("黑名单系统")
        render_blacklist_table(blacklist_service.list_blacklist())

        with st.form("add_blacklist"):
            st.markdown("### 手动加入黑名单")
            user_id = st.text_input("用户标识")
            user_name = st.text_input("用户名称")
            reason = st.text_input("原因", value="手动加入黑名单")
            submitted = st.form_submit_button("加入黑名单")
            if submitted:
                if not user_id.strip():
                    st.error("用户标识不能为空。")
                else:
                    blacklist_service.add_manual(user_id, user_name, reason)
                    st.success(f"用户 {user_id} 已加入黑名单。")
                    st.rerun()

        st.markdown("### 移出黑名单")
        remove_user_id = st.text_input("输入要移出的用户标识")
        if st.button("移出黑名单"):
            if not remove_user_id.strip():
                st.error("用户标识不能为空。")
            else:
                blacklist_service.remove(remove_user_id)
                st.success(f"用户 {remove_user_id} 已移出黑名单。")
                st.rerun()

    with tab_history:
        st.subheader("历史记录与记忆系统")
        query = st.text_input("按用户标识、买家、订单号、礼品关键词检索")
        limit = st.slider("返回条数", min_value=5, max_value=50, value=20, step=5)
        records = store.search_records(query=query, limit=limit)
        render_history_table(records)


if __name__ == "__main__":
    main()
