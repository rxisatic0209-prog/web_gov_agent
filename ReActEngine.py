import logging
import os
import re
import time

from LLM import LLM
from ToolExecutor import ToolExecutor

from prompt_jifen import REACT_PROMPT_TEMPLATE

class ReActEngine:
    def __init__(
        self,
        llm=None,
        tool_executor=None,
        max_steps=None,
        step_delay_seconds=None,
        retry_delay_seconds=None,
    ):
        self.llm = llm or LLM()
        self.executor = tool_executor or ToolExecutor()
        self.max_steps = max_steps or 5
        self.step_delay_seconds = (
            int(step_delay_seconds)
            if step_delay_seconds is not None
            else int(os.getenv("LLM_STEP_DELAY_SECONDS", "60"))
        )
        self.retry_delay_seconds = (
            int(retry_delay_seconds)
            if retry_delay_seconds is not None
            else int(os.getenv("LLM_429_RETRY_SECONDS", "70"))
        )

    def run_audit(self, formatted_question):
        """
        ReAct 编排层：
        - 组装消息
        - 调用 LLM
        - 解析 Action
        - 调度工具
        formatted_question: 已经由外部(tools.py/main.py)封装好的文本描述
        """
        prompt = REACT_PROMPT_TEMPLATE.format(
            question=formatted_question,
            history="审计开始，正在分析初步线索...",
            tools=(
                "- get_user_points[userName]: 【核心工具】查询目标用户的积分/金币流水记录。\n"
                "- get_audit_history[keyword]: 查询历史审计记录，避免重复判断并补充上下文。"
            ),
            gold_threshold=os.getenv("GOLD_THRESHOLD", "200"),
            exp_threshold=os.getenv("EXP_THRESHOLD", "150"),
            current_date=time.strftime("%Y-%m-%d"),
        )
        
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        logging.info("🧠 AI 引擎已接收审计任务，正在启动 ReAct 逻辑...")

        # 2. ReAct 循环
        for step in range(self.max_steps):
            try:
                # 🛑 强制降速：免费模型每一步之间必须休息 60 秒，彻底杜绝 429
                if step > 0 and self.step_delay_seconds > 0:
                    logging.info(f"💤 API 降速保护：休眠 {self.step_delay_seconds} 秒后进行第 {step+1} 步思考...")
                    time.sleep(self.step_delay_seconds)

                content = self.llm.think(
                    messages=messages,
                    temperature=0.1,
                )
                print(f"\n--- AI 思考 Step {step+1} ---\n{content}")

                # 检查是否完成
                if "Finish[" in content or "Final Answer:" in content:
                    return content

                # 解析 Action: tool_name[arguments]
                action_match = re.search(r"Action:\s*(\w+)\[(.*?)\]", content, re.DOTALL)
                
                if action_match:
                    tool_name = action_match.group(1)
                    tool_args = action_match.group(2).strip().replace('"', '').replace("'", "")
                    
                    # 调度工具执行
                    observation = self.executor.execute(tool_name, tool_args)
                    
                    # 将思考和观察记录存入对话历史
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Observation: {observation}"})
                else:
                    # 如果 AI 输出格式不对，引导它给出结论
                    if step < self.max_steps - 1:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": "请继续按照格式输出 Action 或直接给出 Finish[] 结论。"})
                    else:
                        return content

            except Exception as e:
                # 针对 429 的最后一道防线
                if "429" in str(e):
                    logging.warning(f"⚠️ 仍然触发了频率限制，深度休眠 {self.retry_delay_seconds}s 后尝试重试...")
                    time.sleep(self.retry_delay_seconds)
                    continue 
                return f"引擎内部故障: {str(e)}"

        return "审计中止：超过最大推理步数。"
