"""
收集调研智能体 — 枚举设备、部件、故障

三种枚举模式，每种返回结构化 JSON。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .base import BaseAgent, RESEARCH_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 提示词模板
# ---------------------------------------------------------------------------

EQUIPMENT_SYSTEM = (
    "你是一名工业设备智能运维（PHM）领域的资深专家，精通各行业的关键设备及其故障预测与健康管理。"
    "你的任务是全面列举指定行业中所有需要进行 PHM 的关键设备类型。"
)

EQUIPMENT_USER = """\
请列举 **{industry_name}** 行业中所有需要进行故障预测与健康管理（PHM）的关键设备。

要求：
1. 覆盖该行业所有主要子系统和工作站中的关键设备
2. 包括旋转设备、静止设备、电气设备、液压/气动设备等所有类型
3. 每种设备必须是独立的、可单独监测和维护的实体

{seed_hint}

请以 JSON 数组格式输出，每个设备包含：
- "name": 设备标准名称
- "aliases": 常见别名或简称（如有）
- "subcategory": 所属子类别（如 "风电"、"火电"等）
- "description": 一句话描述设备在行业中的作用

仅输出 JSON 数组，不要其他内容。
"""

COMPONENT_SYSTEM = (
    "你是一名工业设备结构设计专家，精通各类设备的内部结构和关键部件。"
    "你的任务是全面列举指定设备的所有可独立监测和更换的关键部件。"
)

COMPONENT_USER = """\
请列举 **{equipment_name}**（{equipment_desc}）的所有可独立监测和更换的关键部件。

要求：
1. 包括所有主要的机械部件、电气部件、液压/气动部件、控制系统部件
2. 每个部件必须是：可独立监测其健康状态、可独立更换或维修的
3. 不要遗漏任何对设备运行有重大影响的部件

{seed_hint}

请以 JSON 数组格式输出，每个部件包含：
- "name": 部件标准名称
- "description": 一句话描述该部件的功能

仅输出 JSON 数组，不要其他内容。
"""

FAULT_SYSTEM = (
    "你是一名工业设备故障诊断专家，精通各类设备部件的故障模式和失效机理。"
    "你的任务是全面列举指定设备部件的所有典型故障模式。"
)

FAULT_USER = """\
请列举 **{equipment_name}** 的 **{component_name}**（{component_desc}）的所有典型故障模式。

要求：
1. 包括所有常见的故障类型：磨损、疲劳、腐蚀、变形、断裂、泄漏、老化、卡滞等
2. 每种故障必须是独立的故障模式，不是故障后果
3. 覆盖从早期退化到完全失效的各类模式

请以 JSON 数组格式输出，每个故障包含：
- "name": 故障模式名称
- "description": 一句话描述故障现象和特征

仅输出 JSON 数组，不要其他内容。
"""


class CollectorAgent(BaseAgent):
    """收集调研智能体：枚举设备、部件、故障。"""

    def _load_research(self, topic: str) -> str:
        """从 research/ 目录读取相关调研资料（如有）。"""
        if not RESEARCH_DIR.is_dir():
            return ""
        context_parts = []
        for fp in sorted(RESEARCH_DIR.glob("*.md")):
            if topic in fp.stem or topic in fp.name:
                text = fp.read_text(encoding="utf-8", errors="replace")
                context_parts.append(f"【参考: {fp.name}】\n{text[:3000]}")
        return "\n\n".join(context_parts) if context_parts else ""

    def enumerate_equipment(
        self,
        industry_name: str,
        seed_names: list[str] | None = None,
        extra_context: str = "",
    ) -> list[dict]:
        """枚举指定行业的所有关键设备。

        Args:
            industry_name: 行业名称
            seed_names: v10 已有设备名列表（确保不遗漏）
            extra_context: 补充上下文（如 web search 结果）

        Returns:
            [{name, aliases, subcategory, description}, ...]
        """
        seed_hint = ""
        if seed_names:
            seed_hint = (
                f"以下是已知的设备（必须保留，不可遗漏，但可以在此基础上补充更多）：\n"
                f"{json.dumps(seed_names, ensure_ascii=False)}"
            )

        research = self._load_research(industry_name)
        if research:
            extra_context = f"{extra_context}\n\n{research}" if extra_context else research

        messages = [
            {"role": "system", "content": EQUIPMENT_SYSTEM},
            {"role": "user", "content": EQUIPMENT_USER.format(
                industry_name=industry_name,
                seed_hint=seed_hint,
            )},
        ]
        if extra_context:
            messages[1]["content"] += f"\n\n=== 补充参考资料 ===\n{extra_context}"

        result = self.call_llm_json(messages)
        if isinstance(result, dict) and "equipment" in result:
            result = result["equipment"]
        logger.info("行业 [%s] 枚举到 %d 个设备", industry_name, len(result))
        return result

    def enumerate_components(
        self,
        equipment_name: str,
        equipment_desc: str = "",
        seed_components: list[str] | None = None,
    ) -> list[dict]:
        """枚举指定设备的所有关键部件。

        Args:
            equipment_name: 设备名称
            equipment_desc: 设备描述
            seed_components: v10 已有部件名列表

        Returns:
            [{name, description}, ...]
        """
        seed_hint = ""
        if seed_components:
            seed_hint = (
                f"以下是已知的部件（必须保留，不可遗漏，但可以在此基础上补充更多）：\n"
                f"{json.dumps(seed_components, ensure_ascii=False)}"
            )

        messages = [
            {"role": "system", "content": COMPONENT_SYSTEM},
            {"role": "user", "content": COMPONENT_USER.format(
                equipment_name=equipment_name,
                equipment_desc=equipment_desc or "工业设备",
                seed_hint=seed_hint,
            )},
        ]

        result = self.call_llm_json(messages)
        if isinstance(result, dict) and "components" in result:
            result = result["components"]
        logger.info("设备 [%s] 枚举到 %d 个部件", equipment_name, len(result))
        return result

    def enumerate_faults(
        self,
        equipment_name: str,
        component_name: str,
        component_desc: str = "",
    ) -> list[dict]:
        """枚举指定设备部件的所有典型故障模式。

        Args:
            equipment_name: 设备名称
            component_name: 部件名称
            component_desc: 部件描述

        Returns:
            [{name, description}, ...]
        """
        messages = [
            {"role": "system", "content": FAULT_SYSTEM},
            {"role": "user", "content": FAULT_USER.format(
                equipment_name=equipment_name,
                component_name=component_name,
                component_desc=component_desc or "关键部件",
            )},
        ]

        result = self.call_llm_json(messages)
        if isinstance(result, dict) and "faults" in result:
            result = result["faults"]
        logger.info("部件 [%s/%s] 枚举到 %d 个故障", equipment_name, component_name, len(result))
        return result
