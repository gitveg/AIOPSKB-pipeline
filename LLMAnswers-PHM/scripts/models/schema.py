"""
PHM 知识库四级数据模型

行业 (Industry) → 设备 (Equipment) → 部件 (Component) → 故障 (Fault)
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 故障级 — 10 个诊断子维度
# ---------------------------------------------------------------------------

class Fault(BaseModel):
    """故障条目，含 10 个诊断子维度。"""
    编号: str = Field(description="故障编号，如 2.1.1.1")
    名称: str = Field(description="故障名称，如 齿面磨损")
    故障描述: str = Field(default="", description="故障现象概述")
    故障机理: str = Field(default="", description="根因分析（物理/化学机理）")
    监测手段: str = Field(default="", description="检测方法/传感器")
    诊断手段: str = Field(default="", description="分析和判断方法")
    诊断指标与特征: str = Field(default="", description="关键特征参数")
    健康评估方法: str = Field(default="", description="量化退化程度的方法")
    寿命预测方法: str = Field(default="", description="RUL 预估方法")
    维护策略: str = Field(default="", description="预防/预测/事后等策略")
    检修方法: str = Field(default="", description="具体维修操作")
    备件与资源: str = Field(default="", description="所需备件和工具")


# ---------------------------------------------------------------------------
# 部件级
# ---------------------------------------------------------------------------

class Component(BaseModel):
    """设备的关键部件。"""
    编号: str = Field(description="部件编号，如 2.1.1")
    名称: str = Field(description="部件名称，如 齿轮副")
    故障列表: list[Fault] = Field(default_factory=list, description="该部件的所有故障模式")


# ---------------------------------------------------------------------------
# 设备级
# ---------------------------------------------------------------------------

class EquipmentInfo(BaseModel):
    """设备基本信息。"""
    设备类型: str = Field(default="", description="设备分类")
    作用与工作原理: str = Field(default="", description="设备作用和工作原理概述")


class Lifecycle(BaseModel):
    """设备生命周期 5 阶段。"""
    设计选型: str = Field(default="")
    安装调试: str = Field(default="")
    运行看护: str = Field(default="")
    维护检修: str = Field(default="")
    退役报废: str = Field(default="")


class Equipment(BaseModel):
    """设备条目。"""
    编号: str = Field(description="设备编号，如 2.1")
    名称: str = Field(description="设备名称，如 齿轮箱")
    类别: str = Field(default="", description="所属子类别，如 风电")
    基本信息: EquipmentInfo = Field(default_factory=EquipmentInfo)
    生命周期: Lifecycle = Field(default_factory=Lifecycle)
    部件列表: list[Component] = Field(default_factory=list, description="所有关键部件")
    风险与标准: str = Field(default="", description="关键性评估 + 引用标准")
    智能化应用: list[str] = Field(default_factory=list, description="AI/数字孪生应用场景")


# ---------------------------------------------------------------------------
# 行业级
# ---------------------------------------------------------------------------

class Industry(BaseModel):
    """行业条目。"""
    编号: str = Field(description="行业编号，如 2")
    名称: str = Field(description="行业名称，如 电力行业")
    设备列表: list[Equipment] = Field(default_factory=list, description="该行业下所有设备")


# ---------------------------------------------------------------------------
# 汇总类型
# ---------------------------------------------------------------------------

class KnowledgeBase(BaseModel):
    """知识库第二部分完整数据。"""
    industries: list[Industry] = Field(default_factory=list)

    def count_stats(self) -> dict:
        """统计各级条目数量。"""
        n_ind = len(self.industries)
        n_equip = sum(len(ind.设备列表) for ind in self.industries)
        n_comp = sum(
            len(eq.部件列表)
            for ind in self.industries
            for eq in ind.设备列表
        )
        n_fault = sum(
            len(comp.故障列表)
            for ind in self.industries
            for eq in ind.设备列表
            for comp in eq.部件列表
        )
        return {
            "行业数": n_ind,
            "设备数": n_equip,
            "部件数": n_comp,
            "故障数": n_fault,
        }


# ---------------------------------------------------------------------------
# 枚举骨架（collector 输出的轻量结构）
# ---------------------------------------------------------------------------

class EquipmentSeed(BaseModel):
    """collector 枚举设备时输出的骨架。"""
    name: str
    aliases: str = ""
    subcategory: str = ""
    description: str = ""


class ComponentSeed(BaseModel):
    """collector 枚举部件时输出的骨架。"""
    name: str
    description: str = ""


class FaultSeed(BaseModel):
    """collector 枚举故障时输出的骨架。"""
    name: str
    description: str = ""
