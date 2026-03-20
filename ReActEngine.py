import json
import logging
import re
import os
import time
from openai import OpenAI
from ToolExecutor import ToolExecutor

# 尝试从外部导入模板
try:
    from prompt_jifen import REACT_PROMPT_TEMPLATE
except ImportError:
    # 兜底模板
    REACT_PROMPT_TEMPLATE = "Question: {question}\nHistory: {history}\nTools: {tools}"

class ReActEngine:
    def __init__(self, tools_inst=None):
        # 基础配置：只关心如何连接大模型
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        self.model = os.getenv("LLM_MODEL_ID", "gemini-3-flash-preview-free")
        self.step_delay_seconds = int(os.getenv("LLM_STEP_DELAY_SECONDS", "60"))
        self.retry_delay_seconds = int(os.getenv("LLM_429_RETRY_SECONDS", "70"))
        
        if not api_key:
            raise ValueError("❌ 环境变量中未找到 LLM_API_KEY")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.executor = ToolExecutor(tools_inst=tools_inst)
        self.max_steps = 5  # ReAct 推理轮次上限

    def _render_prompt(self, formatted_question):
        """
        纯粹的模板渲染逻辑：将外部传来的 question 与环境参数对齐
        """
        gold_threshold = os.getenv("GOLD_THRESHOLD", "200")
        exp_threshold = os.getenv("EXP_THRESHOLD", "150")
        
        # 定义模板中所有占位符的对应关系
        render_data = {
            "question": formatted_question,
            "history": "审计开始，正在分析初步线索...",
            "tools": (
                "- get_user_points[userName]: 【核心工具】查询目标用户的积分/金币流水记录。\n"
                "- get_audit_history[keyword]: 查询历史审计记录，避免重复判断并补充上下文。"
            ),
            "gold_threshold": gold_threshold,
            "exp_threshold": exp_threshold,
            "current_date": time.strftime("%Y-%m-%d")
        }

        # 自动提取模板里真正存在的变量，避免 KeyError
        keys = re.findall(r'\{(\w+)\}', REACT_PROMPT_TEMPLATE)
        final_data = {k: render_data.get(k, f"[{k} Missing]") for k in keys}
        
        return REACT_PROMPT_TEMPLATE.format(**final_data)

    def run_audit(self, formatted_question):
        """
        Engine 的核心：只负责对话逻辑和模型调用
        formatted_question: 已经由外部(tools.py/main.py)封装好的文本描述
        """
        # 1. 渲染最终发送给 AI 的 Prompt
        prompt = self._render_prompt(formatted_question)
        
        messages = [
            {"role": "system", "content": "你是一个专业的商城积分审计专家。请严格按照 Thought/Action 格式进行逻辑推理。"},
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

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1  # 审计任务需要高度确定性，调低温度
                )
                
                content = response.choices[0].message.content
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
