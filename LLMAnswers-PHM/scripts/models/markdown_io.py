"""
四级结构 Markdown / JSON / CSV 读写器

支持：
- 解析 v10 第二部分，提取种子数据（行业名、设备名、关键部件名）
- 程序化生成新的四级 Markdown 文件
- 导出 JSON 和 CSV
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .schema import (
    KnowledgeBase, Industry, Equipment, Component, Fault,
    EquipmentInfo, Lifecycle,
)


# ---------------------------------------------------------------------------
# v10 种子数据提取
# ---------------------------------------------------------------------------

def extract_v10_seeds(filepath: Path) -> list[dict]:
    """从 v10 第二部分提取种子数据。

    返回 [{"industry": str, "equipment": str, "components": [str, ...]}, ...]
    """
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")

    # 定位第二部分
    start = end = None
    for i, line in enumerate(lines):
        if "# 第二部分" in line:
            start = i
        if "# 第三部分" in line:
            end = i
            break
    if start is None:
        return []
    part2 = lines[start:end]

    seeds = []
    industry_name = ""
    equipment_name = ""
    components: list[str] = []
    in_equipment = False
    in_basic_info = False

    for line in part2:
        # 行业
        m = re.match(r"^## \d+\.\s+(.+)$", line)
        if m:
            if equipment_name and components:
                seeds.append({
                    "industry": industry_name,
                    "equipment": equipment_name,
                    "components": components,
                })
            industry_name = m.group(1).strip()
            equipment_name = ""
            components = []
            in_equipment = False
            continue

        # 设备类别 / 设备（### 或 ####）
        m = re.match(r"^#{3,4}\s+[\d.]+\s+(.+)$", line)
        if m:
            if equipment_name and components:
                seeds.append({
                    "industry": industry_name,
                    "equipment": equipment_name,
                    "components": components,
                })
            equipment_name = m.group(1).strip()
            components = []
            in_equipment = True
            in_basic_info = False
            continue

        if in_equipment:
            # 关键部件字段
            m_comp = re.match(r"^\s*-\s*关键部件[：:]\s*(.+)$", line)
            if m_comp:
                raw = m_comp.group(1).strip()
                components = [c.strip() for c in re.split(r"[、,，;；]", raw) if c.strip()]
                in_basic_info = True
                continue

    # 最后一个设备
    if equipment_name and components:
        seeds.append({
            "industry": industry_name,
            "equipment": equipment_name,
            "components": components,
        })

    return seeds


# ---------------------------------------------------------------------------
# Markdown 写入
# ---------------------------------------------------------------------------

def write_kb_md(kb: KnowledgeBase, filepath: Path) -> None:
    """将 KnowledgeBase 程序化写入 Markdown 文件。"""
    lines: list[str] = []

    for ind in kb.industries:
        lines.append(f"## {ind.编号}. {ind.名称}")
        lines.append("")

        for eq in ind.设备列表:
            lines.append(f"### {eq.编号} {eq.名称}")
            lines.append("")

            # 基本信息
            info = eq.基本信息
            if info.设备类型 or info.作用与工作原理:
                lines.append("- **基本信息**")
                if info.设备类型:
                    lines.append(f"  - 设备类型：{info.设备类型}")
                if info.作用与工作原理:
                    lines.append(f"  - 作用与工作原理：{info.作用与工作原理}")
                lines.append("")

            # 生命周期
            lc = eq.生命周期
            has_lc = any(v for v in (
                lc.设计选型, lc.安装调试, lc.运行看护, lc.维护检修, lc.退役报废,
            ))
            if has_lc:
                lines.append("- **生命周期**")
                for stage_name in ("设计选型", "安装调试", "运行看护", "维护检修", "退役报废"):
                    val = getattr(lc, stage_name)
                    if val:
                        lines.append(f"  - {stage_name}：{val}")
                lines.append("")

            # 部件列表
            for comp in eq.部件列表:
                lines.append(f"#### {comp.编号} {comp.名称}")
                lines.append("")
                for fault in comp.故障列表:
                    lines.append(f"##### {fault.编号} {fault.名称}")
                    lines.append("")
                    fault_fields = [
                        ("故障描述", fault.故障描述),
                        ("故障机理", fault.故障机理),
                        ("监测手段", fault.监测手段),
                        ("诊断手段", fault.诊断手段),
                        ("诊断指标与特征", fault.诊断指标与特征),
                        ("健康评估方法", fault.健康评估方法),
                        ("寿命预测方法", fault.寿命预测方法),
                        ("维护策略", fault.维护策略),
                        ("检修方法", fault.检修方法),
                        ("备件与资源", fault.备件与资源),
                    ]
                    for label, value in fault_fields:
                        if value:
                            lines.append(f"- **{label}**：{value}")
                    lines.append("")

            # 风险与标准
            if eq.风险与标准:
                lines.append("- **风险与标准**")
                lines.append(f"  {eq.风险与标准}")
                lines.append("")

            # 智能化应用
            if eq.智能化应用:
                lines.append("- **智能化应用**")
                for app in eq.智能化应用:
                    lines.append(f"  - {app}")
                lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# JSON 导出
# ---------------------------------------------------------------------------

def write_kb_json(kb: KnowledgeBase, filepath: Path) -> None:
    """导出嵌套 JSON。"""
    filepath.write_text(
        kb.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )


# ---------------------------------------------------------------------------
# CSV 导出 — 每行一个故障
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "行业编号", "行业名称",
    "设备编号", "设备名称", "设备类别",
    "部件编号", "部件名称",
    "故障编号", "故障名称",
    "故障描述", "故障机理",
    "监测手段", "诊断手段", "诊断指标与特征",
    "健康评估方法", "寿命预测方法",
    "维护策略", "检修方法", "备件与资源",
]


def write_kb_csv(kb: KnowledgeBase, filepath: Path) -> None:
    """导出扁平 CSV，每行一个故障条目。"""
    rows: list[dict] = []
    for ind in kb.industries:
        for eq in ind.设备列表:
            for comp in eq.部件列表:
                for fault in comp.故障列表:
                    rows.append({
                        "行业编号": ind.编号,
                        "行业名称": ind.名称,
                        "设备编号": eq.编号,
                        "设备名称": eq.名称,
                        "设备类别": eq.类别,
                        "部件编号": comp.编号,
                        "部件名称": comp.名称,
                        "故障编号": fault.编号,
                        "故障名称": fault.名称,
                        "故障描述": fault.故障描述,
                        "故障机理": fault.故障机理,
                        "监测手段": fault.监测手段,
                        "诊断手段": fault.诊断手段,
                        "诊断指标与特征": fault.诊断指标与特征,
                        "健康评估方法": fault.健康评估方法,
                        "寿命预测方法": fault.寿命预测方法,
                        "维护策略": fault.维护策略,
                        "检修方法": fault.检修方法,
                        "备件与资源": fault.备件与资源,
                    })

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
