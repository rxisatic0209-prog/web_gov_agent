# web_gov_agent

一个基于 ReAct 的积分审计 Agent。

系统会拉取商城礼品兑换订单，查询用户积分流水，交给 LLM 做多步审计判断，并把结果写入本地记忆库；当同一用户连续两次出现异常行为时，自动加入黑名单。通知能力通过插件方式挂载，当前支持飞书、控制台和 macOS 本地通知。

## 当前结构

项目按下面几层组织：

- `LLM.py`
  LLM 基建层，统一封装 OpenAI 兼容接口调用，对外只暴露 `think()`
- `prompt_jifen.py`
  唯一的 ReAct Prompt 模板定义
- `ToolExecutor.py`
  工具注册系统和共享工具上下文，负责：
  - 工具注册与分发
  - Playwright 登录态维护
  - `user-Token` 获取与刷新
  - 工具共享配置和记忆存储入口
- `tools.py`
  具体工具实现：
  - 拉取最新订单
  - 查询用户积分流水
  - 查询历史审计记录
- `memory_store.py`
  记忆系统，基于 SQLite 持久化保存：
  - 审计记录
  - 用户连续异常状态
  - 黑名单状态
- `ReActEngine.py`
  只做多步推理编排：
  - 渲染 Prompt
  - 调用 LLM
  - 解析 `Action`
  - 调度工具
- `audit_service.py`
  审计主流程服务，负责串起：
  - 扫描订单
  - 单笔审计
  - 审计结果归类
  - 结果写入记忆系统
  - 调用黑名单系统
  - 调用通知插件
- `blacklist_service.py`
  黑名单规则层，当前规则是同一用户连续 `2` 次异常自动入黑名单
- `notifiers.py`
  通知插件系统
- `main.py`
  CLI 入口，只负责装配和跑通整个流程
- `app.py`
  Streamlit 最小 UI

## 核心流程

```text
main/app
  -> AuditService
    -> ToolExecutor.get_latest_orders
    -> ReActEngine
      -> LLM.think
      -> ToolExecutor.execute
        -> tools.get_user_points / tools.get_audit_history
    -> BlacklistService
    -> AuditMemoryStore
    -> Notifiers
```

单笔订单的处理逻辑：

1. 通过订单接口拉取最新订单
2. `ToolExecutor` 检查当前 `user-Token`
3. 如果 token 失效，重新走 Playwright 登录态获取
4. `ReActEngine` 按 Prompt 驱动 LLM 多步推理
5. LLM 按需调用积分流水工具和历史工具
6. `audit_service` 将结果归类为：
   - `合规`
   - `违规`
   - `高风险待观察`
   - `待人工复核`
7. 记忆系统保存审计结果
8. 黑名单系统更新用户连续异常次数，必要时自动拉黑
9. 通知插件发送结果

## 功能模块

### 1. 用户行为评判系统

当前评判方式是：

- 订单数据作为审计入口
- 积分流水作为核心证据
- LLM 做 ReAct 多步判断
- 代码侧负责结果状态化和后续动作

这层不是纯规则引擎，而是“LLM 审计 + 状态管理”。

### 2. 黑名单系统

当前支持：

- 自动入黑名单
- 查看黑名单
- 手动加入黑名单
- 手动移出黑名单

默认规则：

- 同一用户连续检测 `2` 次异常行为，自动加入黑名单

### 3. 通知器插件系统

当前支持：

- 飞书机器人通知
- 控制台通知
- macOS 本地通知

## 运行依赖

建议环境：

- Python 3.11+
- macOS
- Playwright Chromium

安装依赖：

```bash
pip install openai python-dotenv requests beautifulsoup4 playwright streamlit
playwright install chromium
```

## 环境变量

在 `.env` 中至少配置这些值：

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
LLM_STEP_DELAY_SECONDS=60
LLM_429_RETRY_SECONDS=70
AUDIT_ORDER_DELAY_SECONDS=0
```

说明：

- 默认模式是手动巡查，不会自动常驻
- `CHECK_INTERVAL` 只在 `--mode auto` 时生效
- token 失效时，工具系统会自动刷新一次

## CLI 用法

手动巡查一次：

```bash
python3 main.py
```

自动巡查：

```bash
python3 main.py --mode auto
```

指定扫描数量：

```bash
python3 main.py --size 30
```

关闭飞书通知：

```bash
python3 main.py --no-feishu
```

开启控制台通知：

```bash
python3 main.py --with-console-notifier
```

导出人工复核 CSV：

```bash
python3 main.py --size 30 --export-csv
```

查询历史审计记录：

```bash
python3 main.py --history
python3 main.py --history 某个买家昵称
```

查看黑名单：

```bash
python3 main.py --blacklist
```

手动加入黑名单：

```bash
python3 main.py --add-blacklist <uid> --blacklist-name <name> --blacklist-reason "手动加入"
```

移出黑名单：

```bash
python3 main.py --remove-blacklist <uid>
```

## UI 用法

启动 Streamlit：

```bash
streamlit run app.py
```

当前 UI 提供三个页签：

- 巡查面板
- 黑名单管理
- 历史记录

UI 只做最小交互，不会在页面里偷偷启动后台常驻任务。自动巡查仍然建议用 CLI 显式启动。

## 数据存储

- 审计数据库：`data/audit_memory.db`
- 人工复核导出：`data/exports/`
- Playwright 持久化会话：`data/pw_session/`

## 当前限制

- 判定核心仍然依赖 LLM，不是完全显式规则引擎
- Prompt 规则目前是写死的，还没有独立规则配置层
- `main.py` 仍然偏重，后面还可以继续瘦身
- 还没有 `requirements.txt` / `pyproject.toml`

## 后续适合继续做的事

- 引入显式规则引擎，提升可解释性和精确率稳定性
- 把配置读取进一步收敛成单独的 settings 层
- 把 UI 从最小管理台继续扩成完整产品界面
