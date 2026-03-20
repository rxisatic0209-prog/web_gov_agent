import logging
import json
# 显式导入函数，避免直接使用 'tools' 作为模块名
from tools import get_tools_map 

class ToolExecutor:
    def __init__(self, tools_inst=None):
        # 将映射存入 _registry，避开关键字 'tools'
        self._registry = get_tools_map(tools_inst)
        logging.info(f"🛠️ 工具箱初始化完成，已加载: {list(self._registry.keys())}")

    def execute(self, tool_name, tool_input):
        """
        执行工具的具体逻辑
        """
        # 移除可能存在的空格或换行
        tool_name = tool_name.strip()
        
        if tool_name not in self._registry:
            logging.error(f"❌ 引擎尝试调用不存在的工具: {tool_name}")
            return f"错误: 工具 '{tool_name}' 未注册。可用工具: {list(self._registry.keys())}"
        
        try:
            # 执行对应的函数
            logging.info(f"⚙️ 正在执行工具: {tool_name}")
            func = self._registry[tool_name]
            return func(tool_input)
        except Exception as e:
            logging.error(f"❌ 执行工具 {tool_name} 时发生异常: {str(e)}")
            return f"工具执行出错: {str(e)}"
