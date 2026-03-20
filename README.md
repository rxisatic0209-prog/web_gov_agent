# web_gov_agent

基于 ReAct 的社区治理 Agent。系统会拉取礼品兑换订单，结合用户积分流水做行为审计，输出违规判定，并支持黑名单管理、通知插件和审计结果留存。

## 功能概览

- 用户行为评判系统：读取订单和积分流水，结合大模型做违规判定
- 黑名单系统：支持自动拉黑、手动加入、手动移出、列表查看
- 通知器插件系统：当前支持飞书、控制台、Mac 通知
- 记忆系统：持久化保存审计历史、用户状态、黑名单状态
- 两种巡查模式：手动巡查一次，或用户主动选择自动巡查
- 最小 UI：基于 Streamlit 的管理台

## 项目结构

```text
.
├── main.py                 # CLI 入口
├── app.py                  # Streamlit UI
├── audit_service.py        # 审计流程编排
├── behavior_evaluator.py   # 用户行为评判
├── blacklist_service.py    # 黑名单管理
├── memory_store.py         # SQLite 记忆存储
├── notifiers.py            # 通知插件
├── ReActEngine.py          # ReAct 推理引擎
├── ToolExecutor.py         # 工具调度
├── tools.py                # 订单/积分/历史查询工具
├── prompt_jifen.py         # 审计规则 Prompt
└── LLM.py                  # 通用 LLM 客户端草稿
```

## 核心流程

1. 使用 Playwright 复用浏览器登录态，获取业务站点 `user-Token`
2. 通过订单接口拉取最新兑换订单
3. 调用积分流水接口查询用户近期行为
4. 由 ReAct Agent 根据审计规则输出 `合规 / 违规 / 高风险待观察 / 待人工复核`
5. 更新用户连续异常次数，满足阈值时自动加入黑名单
6. 写入 SQLite 记忆库，并按配置触发通知器

## 运行环境

- Python 3.11
- macOS 本地开发环境
- Playwright
- OpenAI 兼容接口的大模型服务

建议安装依赖：

```bash
pip install openai python-dotenv requests beautifulsoup4 playwright streamlit
playwright install chromium
```

## 环境变量

在 `.env` 中配置：

```env
LLM_API_KEY=your_key
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL_ID=your_model

ORDER_API_REAL=https://your-order-api
POINT_API_REAL=https://your-point-api
LOGIN_PAGE_URL=https://your-login-page

FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

CHECK_INTERVAL=86400
GOLD_THRESHOLD=200
EXP_THRESHOLD=150
```

说明：

- `CHECK_INTERVAL` 只在自动巡查模式下生效
- 自动巡查不是默认行为，默认是手动巡查一次

## CLI 使用

手动巡查一次：

```bash
python3 main.py
```

自动巡查：

```bash
python3 main.py --mode auto
```

关闭飞书通知：

```bash
python3 main.py --no-feishu
```

导出当前巡查结果为 CSV：

```bash
python3 main.py --mode manual --size 30 --no-feishu --export-csv
```

查看历史审计：

```bash
python3 main.py --history
python3 main.py --history Nreal初代用户
```

查看黑名单：

```bash
python3 main.py --blacklist
```

手动加入黑名单：

```bash
python3 main.py --add-blacklist <uid> --blacklist-name <name> --blacklist-reason "manual block"
```

移出黑名单：

```bash
python3 main.py --remove-blacklist <uid>
```

## UI 使用

项目提供了一个最小管理台：

```bash
streamlit run app.py
```

UI 包含三个标签页：

- 巡查面板
- 黑名单管理
- 历史记录

## 记忆与导出

- 审计数据库默认保存在 `data/audit_memory.db`
- 人工复核 CSV 默认导出到 `data/exports/`

## 当前判定方式

当前版本采用“大模型审计 + 规则补充”的结构：

- 模型负责阅读积分流水、分析高频行为、内容雷同、多账号线索，并生成审计理由
- 代码负责状态持久化、连续异常计数、自动拉黑和通知分发

后续如果要做更稳定的精确率验证，建议进一步加入纯代码规则引擎，把“时间窗口、频次、重复文本、积分阈值”做成可解释的显式规则。
