"""
Python 代码解释器工具 - 允许 Agent 编写并执行 Python 代码。

本模块创建了一个 Python REPL 工具，Agent 可以通过它：
- 执行复杂的数学计算（如数值分析、方程式求解）。
- 进行数据处理和分析（如 CSV 解析、统计分析）。
- 验证和调试代码片段。

使用场景示例：
    - 用户："帮我计算 pi 的前 100 位" → Agent 调用 python_repl 执行计算。
    - 用户："分析一下这个数据列表的统计特征" → Agent 运行 numpy/pandas 操作。

安全注意事项：
    - 当前在 Docker 容器内运行，需确保容器的网络和文件系统隔离。
    - 工具的描述中提示 Agent 不要执行网络请求或文件操作。
    - 生产环境建议升级为 E2B 沙盒以获得更严格的安全隔离。

依赖：
    pip install langchain-experimental
    如果未安装，python_repl_tool 为 None，功能自动禁用。
"""

from app.core.logging import logger

# 尝试导入 PythonREPLTool（需要 langchain-experimental 包）
try:
    from langchain_experimental.tools import PythonREPLTool

    python_repl_tool = PythonREPLTool(
        description=(
            "Python 代码解释器。用于执行 Python 代码来完成数学计算、数据处理等任务。"
            "输入：Python 代码字符串。输出：代码执行结果。"
            "注意：仅用于合法的计算和数据处理，不执行网络请求或文件操作。"
        )
    )
    logger.info("python_repl_tool_initialized")
    PYTHON_REPL_AVAILABLE = True

except ImportError:
    # langchain-experimental 未安装时的降级处理
    logger.warning(
        "langchain_experimental_not_installed_python_repl_unavailable",
    )
    python_repl_tool = None
    PYTHON_REPL_AVAILABLE = False
