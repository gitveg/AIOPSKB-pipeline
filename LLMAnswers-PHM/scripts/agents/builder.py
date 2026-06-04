"""
主智能体 — 组装结构、填充故障诊断子维度、根据反馈迭代
"""
from __future__ import annotations

import json
import logging

from .base import BaseAgent
from .collector import CollectorAgent
from models.schema import (
    KnowledgeBase, Industry, Equipment, Component, Fault,
    EquipmentInfo, Lifecycle, EquipmentSeed, ComponentSeed, FaultSeed,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

ENRICH_SYSTEM = (
    "你是一名工业设备智能运维（PHM）领域的资深专家，精通故障诊断、状态监测、健康评估和预测性维护。"
    "你的任务是为指定的设备部件故障填充完整的诊断生命周期信息。"
)

ENRICH_USER = """\
请为以下设备部件的故障填充完整的诊断生命周期信息。

设备：{equipment_name}
设备描述：{equipment_desc}
部件：{component_name}
部件描述：{component_desc}

故障列表：
{faults_json}

请为每个故障填充以下 10 个维度，输出 JSON 数组，与输入故障一一对应：
1. "故障描述"：故障现象概述
2. "故障机理"：根因分析（物理/化学机理）
3. "监测手段"：检测方法/传感器（含具体类型和参数）
4. "诊断手段"：分析和判断方法（含算法名）
5. "诊断指标与特征"：关键特征参数和阈值
6. "健康评估方法"：量化退化程度的方法
7. "寿命预测方法"：RUL 预估方法
8. "维护策略"：维护策略类型（CBM/PdM/PM 等）
9. "检修方法"：具体维修操作步骤
10. "备件与资源"：所需备件、工具和资源

要求：
- 每个维度都要有实质性内容，具体到传感器型号、算法名、标准编号等
- 内容必须准确，符合 PHM 领域的专业实践
- 保持 JSON 格式严格正确

输出格式：
[
  {{
    "name": "故障名",
    "故障描述": "...",
    "故障机理": "...",
    "监测手段": "...",
    "诊断手段": "...",
    "诊断指标与特征": "...",
    "健康评估方法": "...",
    "寿命预测方法": "...",
    "维护策略": "...",
    "检修方法": "...",
    "备件与资源": "..."
  }}
]

仅输出 JSON 数组，不要其他内容。
"""

REFINE_SYSTEM = (
    "你是一名工业设备智能运维（PHM）领域的资深架构师，擅长知识体系审查和优化。"
    "你的任务是根据评估反馈，确定需要补充和修改的具体条目。"
)

REFINE_USER = """\
以下是知识库的评估反馈。请分析反馈内容，输出需要执行的具体操作列表。

=== 评估反馈 ===
{evaluation_report}

=== 当前知识库统计 ===
- 行业数：{n_industries}
- 设备数：{n_equipments}
- 部件数：{n_components}
- 故障数：{n_faults}

请输出 JSON 对象，包含以下字段：
- "add_equipment": [{{"industry": "行业名", "name": "设备名"}}]  — 需要新增的设备
- "add_component": [{{"equipment": "设备名", "name": "部件名"}}]  — 需要新增的部件
- "add_fault": [{{"equipment": "设备名", "component": "部件名", "name": "故障名"}}]  — 需要新增的故障
- "enrich_fault": [{{"equipment": "设备名", "component": "部件名", "fault": "故障名", "reason": "原因"}}]  — 需要重新填充子维度的故障

仅输出 JSON，不要其他内容。
"""


class BuilderAgent(BaseAgent):
    """主智能体：组装结构、丰富故障、根据反馈迭代。"""

    def __init__(self) -> None:
        super().__init__()
        self.collector = CollectorAgent.__new__(CollectorAgent)
        # 共享同一个 client，避免重复初始化
        self.collector.client = self.client
        self.collector.model = self.model

    def enrich_faults(
        self,
        equipment_name: str,
        equipment_desc: str,
        component_name: str,
        component_desc: str,
        fault_seeds: list[dict],
    ) -> list[Fault]:
        """为故障骨架填充 10 个诊断子维度。

        Args:
            equipment_name: 设备名称
            equipment_desc: 设备描述
            component_name: 部件名称
            component_desc: 部件描述
            fault_seeds: 故障骨架列表 [{name, description}, ...]

        Returns:
            完整的 Fault 对象列表
        """
        if not fault_seeds:
            return []

        messages = [
            {"role": "system", "content": ENRICH_SYSTEM},
            {"role": "user", "content": ENRICH_USER.format(
                equipment_name=equipment_name,
                equipment_desc=equipment_desc or "工业设备",
                component_name=component_name,
                component_desc=component_desc or "关键部件",
                faults_json=json.dumps(fault_seeds, ensure_ascii=False, indent=2),
            )},
        ]

        result = self.call_llm_json(messages)
        faults = []
        for i, item in enumerate(result):
            # 保留原始 name 作为 fallback
            name = item.get("name", fault_seeds[i]["name"] if i < len(fault_seeds) else f"故障{i+1}")
            fault = Fault(
                编号="",
                名称=name,
                故障描述=item.get("故障描述", ""),
                故障机理=item.get("故障机理", ""),
                监测手段=item.get("监测手段", ""),
                诊断手段=item.get("诊断手段", ""),
                诊断指标与特征=item.get("诊断指标与特征", ""),
                健康评估方法=item.get("健康评估方法", ""),
                寿命预测方法=item.get("寿命预测方法", ""),
                维护策略=item.get("维护策略", ""),
                检修方法=item.get("检修方法", ""),
                备件与资源=item.get("备件与资源", ""),
            )
            faults.append(fault)

        logger.info(
            "enrich_faults: %s/%s — %d 个故障已填充",
            equipment_name, component_name, len(faults),
        )
        return faults

    def build_equipment(
        self,
        equipment_seed: dict,
        industry_name: str,
        industry_no: str,
        equipment_idx: int,
    ) -> Equipment:
        """完整的设备构建流程：枚举部件 → 枚举故障 → 填充子维度。

        Args:
            equipment_seed: collector 输出的设备骨架 {name, ...}
            industry_name: 所属行业名称
            industry_no: 行业编号
            equipment_idx: 设备序号（用于编号）
        """
        eq_name = equipment_seed["name"]
        eq_no = f"{industry_no}.{equipment_idx}"
        eq_desc = equipment_seed.get("description", "")

        logger.info("构建设备: %s (%s)", eq_name, eq_no)

        # 1. 枚举部件
        seed_components = equipment_seed.get("seed_components", [])
        comp_seeds = self.collector.enumerate_components(
            equipment_name=eq_name,
            equipment_desc=eq_desc,
            seed_components=seed_components,
        )

        # 2. 对每个部件枚举故障 + 填充子维度
        components: list[Component] = []
        for comp_idx, comp_seed in enumerate(comp_seeds, 1):
            comp_name = comp_seed["name"]
            comp_no = f"{eq_no}.{comp_idx}"
            comp_desc = comp_seed.get("description", "")

            # 枚举故障骨架
            fault_seeds = self.collector.enumerate_faults(
                equipment_name=eq_name,
                component_name=comp_name,
                component_desc=comp_desc,
            )

            # 填充 10 个子维度
            faults = self.enrich_faults(
                equipment_name=eq_name,
                equipment_desc=eq_desc,
                component_name=comp_name,
                component_desc=comp_desc,
                fault_seeds=fault_seeds,
            )

            # 分配编号
            for fault_idx, fault in enumerate(faults, 1):
                fault.编号 = f"{comp_no}.{fault_idx}"

            components.append(Component(
                编号=comp_no,
                名称=comp_name,
                故障列表=faults,
            ))

        return Equipment(
            编号=eq_no,
            名称=eq_name,
            类别=equipment_seed.get("subcategory", ""),
            基本信息=EquipmentInfo(
                设备类型=equipment_seed.get("aliases", ""),
                作用与工作原理=eq_desc,
            ),
            部件列表=components,
        )

    def refine_from_feedback(
        self,
        kb: KnowledgeBase,
        evaluation_report: str,
    ) -> KnowledgeBase:
        """根据评估反馈改进知识库。

        分析反馈 → 定向补充 → 重新填充子维度。
        """
        stats = kb.count_stats()
        messages = [
            {"role": "system", "content": REFINE_SYSTEM},
            {"role": "user", "content": REFINE_USER.format(
                evaluation_report=evaluation_report,
                **stats,
            )},
        ]

        ops = self.call_llm_json(messages)
        logger.info("refine_from_feedback: 操作列表 = %s", json.dumps(ops, ensure_ascii=False)[:500])

        # 执行新增操作
        for item in ops.get("add_equipment", []):
            ind = self._find_industry(kb, item["industry"])
            if ind is None:
                continue
            eq_idx = len(ind.设备列表) + 1
            eq = self.build_equipment(
                equipment_seed={"name": item["name"], "description": item.get("description", "")},
                industry_name=ind.名称,
                industry_no=ind.编号,
                equipment_idx=eq_idx,
            )
            ind.设备列表.append(eq)

        for item in ops.get("add_component", []):
            eq = self._find_equipment(kb, item["equipment"])
            if eq is None:
                continue
            comp_idx = len(eq.部件列表) + 1
            fault_seeds = self.collector.enumerate_faults(
                equipment_name=eq.名称,
                component_name=item["name"],
            )
            faults = self.enrich_faults(
                equipment_name=eq.名称,
                equipment_desc=eq.基本信息.作用与工作原理,
                component_name=item["name"],
                component_desc="",
                fault_seeds=fault_seeds,
            )
            comp_no = f"{eq.编号}.{comp_idx}"
            for fi, fault in enumerate(faults, 1):
                fault.编号 = f"{comp_no}.{fi}"
            eq.部件列表.append(Component(编号=comp_no, 名称=item["name"], 故障列表=faults))

        for item in ops.get("add_fault", []):
            comp = self._find_component(kb, item["equipment"], item["component"])
            if comp is None:
                continue
            fault_idx = len(comp.故障列表) + 1
            new_faults = self.enrich_faults(
                equipment_name=item["equipment"],
                equipment_desc="",
                component_name=item["component"],
                component_desc="",
                fault_seeds=[{"name": item["name"], "description": ""}],
            )
            for nf in new_faults:
                nf.编号 = f"{comp.编号}.{fault_idx}"
                fault_idx += 1
                comp.故障列表.append(nf)

        # 重新填充标记的故障
        for item in ops.get("enrich_fault", []):
            fault = self._find_fault(kb, item["equipment"], item["component"], item["fault"])
            if fault is None:
                continue
            new_faults = self.enrich_faults(
                equipment_name=item["equipment"],
                equipment_desc="",
                component_name=item["component"],
                component_desc="",
                fault_seeds=[{"name": fault.名称, "description": fault.故障描述}],
            )
            if new_faults:
                new_faults[0].编号 = fault.编号
                # 替换原故障
                comp = self._find_component(kb, item["equipment"], item["component"])
                if comp:
                    for i, f in enumerate(comp.故障列表):
                        if f.编号 == fault.编号:
                            comp.故障列表[i] = new_faults[0]
                            break

        return kb

    # -- 辅助查找方法 --

    def _find_industry(self, kb: KnowledgeBase, name: str) -> Industry | None:
        for ind in kb.industries:
            if ind.名称 == name:
                return ind
        return None

    def _find_equipment(self, kb: KnowledgeBase, name: str) -> Equipment | None:
        for ind in kb.industries:
            for eq in ind.设备列表:
                if eq.名称 == name:
                    return eq
        return None

    def _find_component(self, kb: KnowledgeBase, eq_name: str, comp_name: str) -> Component | None:
        eq = self._find_equipment(kb, eq_name)
        if eq:
            for comp in eq.部件列表:
                if comp.名称 == comp_name:
                    return comp
        return None

    def _find_fault(self, kb: KnowledgeBase, eq_name: str, comp_name: str, fault_name: str) -> Fault | None:
        comp = self._find_component(kb, eq_name, comp_name)
        if comp:
            for fault in comp.故障列表:
                if fault.名称 == fault_name:
                    return fault
        return None
