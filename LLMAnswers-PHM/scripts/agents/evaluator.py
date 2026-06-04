"""
可用性判断智能体 — 工程师视角评估知识库实用性

四维评估：查询路径测试、覆盖完整性、可操作性、交叉检索
"""
from __future__ import annotations

import logging

from .base import BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

EVAL_SYSTEM = (
    "你是一名拥有 15 年工业设备运维经验的资深工程师，精通 PHM（故障预测与健康管理）。"
    "你同时也是知识库设计和信息检索方面的专家。"
    "你的任务是从一线工程师的实际使用角度，评估 PHM 知识库的可用性。"
)

EVAL_USER = """\
请对以下 PHM 知识库（行业→设备→部件→故障 四级结构）进行全面可用性评估。

=== 知识库内容 ===

{kb_content}

=== 评估要求 ===

请从以下 4 个维度进行评估：

## 1. 查询路径测试（最重要）

请构思 **15-20 个**真实工业场景中的故障查询需求，模拟工程师的使用场景。例如：
- "风电场 2MW 机组齿轮箱出现异常振动，特征频率显示齿轮啮合频率边带增大"
- "石化厂离心压缩机轴承温度持续升高，振动值超标"
- "水泥厂回转窑托轮出现异响"

对每个场景：
- 描述查询需求
- 列出从知识库根节点到目标故障条目的导航路径（行业→设备→部件→故障）
- 判断是否能精准定位（✓ 能定位 / ✗ 无法定位 / △ 部分定位）
- 如果无法定位，说明缺失了什么

## 2. 覆盖完整性

逐行业检查：
- 是否有遗漏的重要设备类型？
- 每个设备是否有遗漏的关键部件？
- 每个部件是否有遗漏的典型故障模式？
- 列出具体缺失的条目名称

## 3. 可操作性

抽样检查 5-10 个故障条目：
- 10 个诊断子维度是否都有实质性内容？
- 监测手段是否具体到传感器类型和安装位置？
- 诊断手段是否具体到算法名称和参数？
- 检修方法是否具体到操作步骤？
- 标出内容过于笼统、不具指导性的条目

## 4. 交叉检索能力

- 选择 2-3 个通用故障模式（如"轴承磨损"、"密封泄漏"），检查它们在不同行业的设备部件中是否都有对应记录
- 检查是否有跨行业的知识关联

=== 输出格式 ===

请使用 Markdown 格式输出评估报告，包含：
1. 总体评分（1-10 分）
2. 每个维度的详细分析（使用二级标题）
3. 具体改进建议（按优先级排序）
4. 每条建议标注涉及的行业/设备/部件/故障
"""


class EvaluatorAgent(BaseAgent):
    """可用性判断智能体：工程师视角评估知识库。"""

    def evaluate(self, kb_content: str) -> str:
        """评估知识库可用性。

        Args:
            kb_content: 知识库 Markdown 内容

        Returns:
            评估报告 Markdown 文本
        """
        messages = [
            {"role": "system", "content": EVAL_SYSTEM},
            {"role": "user", "content": EVAL_USER.format(kb_content=kb_content)},
        ]

        logger.info("开始可用性评估（知识库 %d 字符）...", len(kb_content))
        report = self.call_llm(messages, max_tokens=65536)
        logger.info("评估完成，报告 %d 字符", len(report))
        return report

    def evaluate_kb(self, kb_md_path: str) -> str:
        """从文件读取知识库并评估。

        Args:
            kb_md_path: 知识库 Markdown 文件路径

        Returns:
            评估报告 Markdown 文本
        """
        from pathlib import Path
        content = Path(kb_md_path).read_text(encoding="utf-8", errors="replace")
        return self.evaluate(content)
