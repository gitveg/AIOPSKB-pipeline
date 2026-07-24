"""
知识库自动化校验脚本。

对阶段2-4生成的数据进行程序化质量检查，不依赖LLM。

用法:
  python src/scripts/validate_kb.py --stage 2 --target src/data/power/thermal
  python src/scripts/validate_kb.py --stage 3 --target src/data/power/thermal/boiler
  python src/scripts/validate_kb.py --stage 4 --target src/data/power/thermal/boiler
  python src/scripts/validate_kb.py --target src/data/power   # 全量校验（扫描所有子阶段）

校验项:
  - 行级去重（阶段2-4）
  - 表头完整性（阶段2-4）
  - 父部件引用完整性（阶段3）
  - 故障文件名与部件名称对应（阶段4）
  - 必填字段非空（阶段3-4）
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

# 确保 pipeline 包可 import（与 md_to_json.py 一致的路径处理）
try:
    _SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
except Exception:
    pass

# ── Format detection (shared with orchestrator) ──

def is_new_format(directory: str) -> bool:
    """检测目录是否使用新的三层结构（子系统→部件→零件）。"""
    return os.path.exists(os.path.join(directory, "sub_system.md"))

# ── Schema 定义 ──

SCHEMA = {
    2: {
        "files": ["equipment_registry.md", "sub_equipment.md"],
        "headers": {
            "equipment_registry.md": ["设备类型名称", "设备属性", "描述"],
            "sub_equipment.md": ["子设备名称", "描述"],
        },
    },
    3: {
        "files": ["components.md"],
        "headers": {
            "components.md": ["部件名称", "父部件", "描述", "易损标识", "维护方法", "报废方法"],
        },
    },
    4: {
        "files": ["faults/*.md"],
        "headers": {
            "fault": ["故障名称", "故障类别", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"],  # 改造5（12列，向后兼容）
            "fault_old": ["故障名称", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"],  # 改造5前（11列，向后兼容）
            "fault_retrofit6": ["故障名称", "故障类别", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11", "D12", "D13", "D14", "D15"],  # 改造6（17列，D11-D15检维修）
        },
    },
}

# 新格式 Schema（三层结构：子系统→部件→零件）
SCHEMA_NEW = {
    "sub_system": {
        "files": ["sub_system.md"],
        "headers": {
            "sub_system.md": ["子系统名称", "描述"],
        },
    },
    3: {
        "files": ["components.md"],
        "headers": {
            "components.md": ["部件", "零件", "描述", "易损标识", "维护方法", "报废方法"],
        },
    },
}

FAULT_REQUIRED_COLS = [
    "故障名称", "故障类别", "D1_物理属性", "D2_故障等级", "D3_故障描述与机理",
    "D4_故障征兆", "D5_故障特征参数", "D6_监测与检测手段",
    "D7_诊断方法", "D8_检修方法", "D9_预防措施", "D10_易混淆故障",
]


# ── 数据结构 ──

@dataclass
class CheckResult:
    level: str          # "ok" | "warning" | "error"
    check: str          # 校验项名称
    file: str           # 文件路径
    message: str        # 描述
    auto_fixed: bool = False


@dataclass
class ValidationReport:
    target: str
    results: list[CheckResult] = field(default_factory=list)
    # 全库 D5 置信分布聚合计数器，由 check_d5_confidence 累加
    d5_stats: dict = field(default_factory=lambda: {
        "standard": 0, "experience": 0, "experience_unverified": 0, "pending": 0, "untagged": 0
    })
    # 全库 D8 级别分布聚合计数器，由 check_d8_level 累加
    d8_stats: dict = field(default_factory=lambda: {
        "regulatory": 0, "experience": 0, "unlabeled": 0
    })

    @property
    def errors(self) -> list[CheckResult]:
        return [r for r in self.results if r.level == "error"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.level == "warning"]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


# ── Markdown 表格解析 ──

def parse_md_table(filepath: str) -> tuple[list[str], list[list[str]]]:
    """解析 Markdown 表格，返回 (headers, data_rows)。"""
    if not os.path.exists(filepath):
        return [], []

    headers = []
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not cells:
                continue
            if not headers:
                headers = cells
                continue
            if len(cells) != len(headers):
                continue
            rows.append(cells)
    return headers, rows


def write_md_table(filepath: str, headers: list[str], rows: list[list[str]]):
    """写回 Markdown 表格。"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("| " + " | ".join(headers) + " |\n")
        sep = "|" + "|".join(["---"] * len(headers)) + "|"
        f.write(sep + "\n")
        for row in rows:
            f.write("| " + " | ".join(row) + " |\n")


# ── 校验函数 ──

def check_dedup(report: ValidationReport, filepath: str, auto_fix: bool = False):
    """行级去重检查。"""
    headers, rows = parse_md_table(filepath)
    if not rows:
        return

    row_strs = ["|".join(r) for r in rows]
    unique_strs = list(dict.fromkeys(row_strs))

    if len(row_strs) != len(unique_strs):
        dup_count = len(row_strs) - len(unique_strs)
        if auto_fix:
            unique_rows = [rows[row_strs.index(s)] for s in unique_strs]
            write_md_table(filepath, headers, unique_rows)
            report.results.append(CheckResult(
                level="warning", check="行级去重", file=filepath,
                message=f"发现并自动移除 {dup_count} 条重复行（{len(row_strs)}→{len(unique_strs)}）",
                auto_fixed=True,
            ))
        else:
            report.results.append(CheckResult(
                level="warning", check="行级去重", file=filepath,
                message=f"发现 {dup_count} 条重复行（总计{len(row_strs)}行，唯一{len(unique_strs)}行）",
            ))


def check_headers(report: ValidationReport, filepath: str, expected: list[str]):
    """表头完整性检查。"""
    headers, _ = parse_md_table(filepath)
    if not headers:
        return

    if len(headers) != len(expected):
        report.results.append(CheckResult(
            level="error", check="表头完整性", file=filepath,
            message=f"列数不匹配：期望 {len(expected)} 列 {expected}，实际 {len(headers)} 列 {headers}",
        ))
        return

    for i, (actual, exp) in enumerate(zip(headers, expected)):
        if not actual.strip().startswith(exp):
            report.results.append(CheckResult(
                level="error", check="表头完整性", file=filepath,
                message=f"第{i+1}列不匹配：期望以'{exp}'开头，实际为'{actual}'",
            ))


def check_parent_refs(report: ValidationReport, filepath: str):
    """部件引用完整性检查。旧格式检查父部件引用，新格式检查部件-零件关系。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    # 检测格式：第二列是否为"零件"
    if len(headers) >= 2 and headers[1].strip() == "零件":
        _check_comp_part_refs_new(report, filepath, headers, rows)
    else:
        _check_parent_refs_old(report, filepath, headers, rows)


def _check_parent_refs_old(report: ValidationReport, filepath: str,
                            headers: list, rows: list):
    """旧格式：父部件引用完整性检查。"""
    try:
        name_idx = headers.index("部件名称")
        parent_idx = headers.index("父部件")
    except ValueError:
        report.results.append(CheckResult(
            level="error", check="父部件引用", file=filepath,
            message="缺少'部件名称'或'父部件'列",
        ))
        return

    all_names = set()
    parent_refs = {}
    for row in rows:
        name = row[name_idx].strip()
        parent = row[parent_idx].strip()
        all_names.add(name)
        if parent not in ("—", "-", ""):
            parent_refs[name] = parent

    orphans = []
    for name, parent in parent_refs.items():
        if parent not in all_names:
            orphans.append(f"'{name}' 引用了不存在的父部件 '{parent}'")

    if orphans:
        report.results.append(CheckResult(
            level="error", check="父部件引用", file=filepath,
            message=f"发现 {len(orphans)} 个孤立引用：{'; '.join(orphans[:5])}",
        ))


def _check_comp_part_refs_new(report: ValidationReport, filepath: str,
                               headers: list, rows: list):
    """新格式：检查每个部件必须有零件列='—'的独立行，零件行关联到存在的部件。"""
    try:
        comp_idx = headers.index("部件")
        part_idx = headers.index("零件")
    except ValueError:
        report.results.append(CheckResult(
            level="error", check="部件-零件关系", file=filepath,
            message="缺少'部件'或'零件'列",
        ))
        return

    all_components = set()
    components_with_standalone = set()
    orphan_parts = []

    for row in rows:
        comp = row[comp_idx].strip()
        part = row[part_idx].strip()
        if comp:
            all_components.add(comp)
        if part in ("—", "-", ""):
            components_with_standalone.add(comp)
        else:
            # Part row: verify component exists
            if comp not in all_components and comp not in components_with_standalone:
                orphan_parts.append(f"零件'{part}'引用了未定义的部件'{comp}'")

    missing_standalone = all_components - components_with_standalone
    if missing_standalone:
        report.results.append(CheckResult(
            level="error", check="部件独立行", file=filepath,
            message=f"{len(missing_standalone)} 个部件缺少零件列='—'的独立行：{', '.join(list(missing_standalone)[:5])}",
        ))
    if orphan_parts:
        report.results.append(CheckResult(
            level="error", check="部件-零件关系", file=filepath,
            message=f"{len(orphan_parts)} 个零件引用了未定义的部件：{'; '.join(orphan_parts[:5])}",
        ))


def check_fault_file_mapping(report: ValidationReport, equip_dir: str):
    """故障文件名与部件/零件名称对应检查。自动检测新旧格式。"""
    if is_new_format(equip_dir):
        _check_fault_file_mapping_new(report, equip_dir)
    else:
        _check_fault_file_mapping_old(report, equip_dir)


def _check_fault_file_mapping_old(report: ValidationReport, equip_dir: str):
    """旧格式：扁平 faults/ 目录。"""
    faults_dir = os.path.join(equip_dir, "faults")
    comp_path = os.path.join(equip_dir, "components.md")

    if not os.path.isdir(faults_dir) or not os.path.exists(comp_path):
        return

    headers, rows = parse_md_table(comp_path)
    if not headers or not rows:
        return

    try:
        name_idx = headers.index("部件名称")
        parent_idx = headers.index("父部件")
    except ValueError:
        return

    parent_set = {row[parent_idx].strip() for row in rows if row[parent_idx].strip() not in ("—", "-", "")}
    all_comp_names = {row[name_idx].strip() for row in rows}
    leaf_names = {n for n in all_comp_names if n not in parent_set}

    fault_files = {os.path.splitext(f)[0] for f in os.listdir(faults_dir) if f.endswith(".md")}

    missing_files = leaf_names - fault_files
    extra_files = fault_files - all_comp_names

    if missing_files:
        report.results.append(CheckResult(
            level="warning", check="故障文件对应", file=faults_dir,
            message=f"{len(missing_files)} 个部件缺少故障文件（叶节点）：{', '.join(list(missing_files)[:5])}",
        ))
    if extra_files:
        report.results.append(CheckResult(
            level="warning", check="故障文件对应", file=faults_dir,
            message=f"{len(extra_files)} 个故障文件无对应部件：{', '.join(list(extra_files)[:5])}",
        ))


def _check_fault_file_mapping_new(report: ValidationReport, base_dir: str):
    """新格式：遍历子系统→部件/零件目录下的 faults/。"""
    sub_systems = _read_sub_systems(base_dir)
    for ss_name, _ in sub_systems:
        ss_dir = os.path.join(base_dir, ss_name)
        comp_path = os.path.join(ss_dir, "components.md")
        if not os.path.exists(comp_path):
            continue

        headers, rows = parse_md_table(comp_path)
        if not headers or not rows:
            continue

        try:
            comp_idx = headers.index("部件")
            part_idx = headers.index("零件")
        except ValueError:
            continue

        # 收集所有部件名和零件名
        all_names = set()
        for row in rows:
            comp = row[comp_idx].strip()
            part = row[part_idx].strip()
            if comp:
                all_names.add(comp)
            if part and part not in ("—", "-"):
                all_names.add(part)

        # 检查每个部件和零件目录下的 faults/
        for name in all_names:
            name_dir = os.path.join(ss_dir, name)
            if not os.path.isdir(name_dir):
                # 目录不存在可能是正常的（尚未生成故障）
                continue
            faults_dir = os.path.join(name_dir, "faults")
            if os.path.isdir(faults_dir):
                fault_files = {os.path.splitext(f)[0] for f in os.listdir(faults_dir) if f.endswith(".md")}
                # 至少应有该部件/零件自身的故障文件
                if name not in fault_files:
                    report.results.append(CheckResult(
                        level="warning", check="故障文件对应", file=faults_dir,
                        message=f"子系统'{ss_name}'下 '{name}' 缺少故障文件 {name}.md",
                    ))


def check_required_fields_comp(report: ValidationReport, filepath: str):
    """components.md 必填字段非空检查。自动检测新旧格式。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    # 检测格式
    if len(headers) >= 2 and headers[1].strip() == "零件":
        _check_required_fields_comp_new(report, filepath, headers, rows)
    else:
        _check_required_fields_comp_old(report, filepath, headers, rows)


def _check_required_fields_comp_old(report: ValidationReport, filepath: str,
                                     headers: list, rows: list):
    """旧格式：叶节点的维护方法、报废方法非空。"""
    try:
        name_idx = headers.index("部件名称")
        parent_idx = headers.index("父部件")
        maint_idx = headers.index("维护方法")
        disposal_idx = headers.index("报废方法")
    except ValueError:
        return

    parent_set = {row[parent_idx].strip() for row in rows if row[parent_idx].strip() not in ("—", "-", "")}
    empty_fields = []

    for i, row in enumerate(rows):
        name = row[name_idx].strip()
        if name in parent_set:
            continue
        for label, idx in [("维护方法", maint_idx), ("报废方法", disposal_idx)]:
            if idx < len(row) and row[idx].strip() in ("", "—", "-"):
                empty_fields.append(f"第{i+3}行 '{name}' 的{label}为空")

    if empty_fields:
        report.results.append(CheckResult(
            level="warning", check="必填字段", file=filepath,
            message=f"{len(empty_fields)} 个叶节点必填字段为空：{'; '.join(empty_fields[:5])}",
        ))


def _check_required_fields_comp_new(report: ValidationReport, filepath: str,
                                     headers: list, rows: list):
    """新格式：部件行（零件='—'）的维护方法/报废方法非空；零件行这两列应为'—'。"""
    try:
        comp_idx = headers.index("部件")
        part_idx = headers.index("零件")
        maint_idx = headers.index("维护方法")
        disposal_idx = headers.index("报废方法")
    except ValueError:
        return

    empty_fields = []
    wrong_mount = []

    for i, row in enumerate(rows):
        comp = row[comp_idx].strip()
        part = row[part_idx].strip()

        if part in ("—", "-", ""):
            # 部件独立行：维护方法/报废方法应非空
            for label, idx in [("维护方法", maint_idx), ("报废方法", disposal_idx)]:
                if idx < len(row) and row[idx].strip() in ("", "—", "-"):
                    empty_fields.append(f"第{i+3}行 部件'{comp}' 的{label}为空")
        else:
            # 零件行：维护方法/报废方法应为"—"（上挂部件层）
            for label, idx in [("维护方法", maint_idx), ("报废方法", disposal_idx)]:
                if idx < len(row) and row[idx].strip() not in ("—", "-"):
                    wrong_mount.append(f"第{i+3}行 零件'{part}' 的{label}不应有值（应上挂到部件层）")

    if empty_fields:
        report.results.append(CheckResult(
            level="warning", check="必填字段", file=filepath,
            message=f"{len(empty_fields)} 个部件行必填字段为空：{'; '.join(empty_fields[:5])}",
        ))
    if wrong_mount:
        report.results.append(CheckResult(
            level="warning", check="属性挂载", file=filepath,
            message=f"{len(wrong_mount)} 处属性挂载违规：{'; '.join(wrong_mount[:5])}",
        ))


def check_required_fields_fault(report: ValidationReport, filepath: str):
    """故障文件必填字段非空检查（D1-D10）。D10允许"—"。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    fname = os.path.basename(filepath)
    empty_rows = []

    for i, row in enumerate(rows):
        if len(row) < 12:
            continue
        # 故障类别+D1-D9 必填，D10 允许"—"
        all_empty = all(cell.strip() in ("", "—", "-") for cell in row[1:11])
        if all_empty:
            empty_rows.append(f"第{i+3}行")
            continue
        for j in range(1, min(11, len(row))):
            if row[j].strip() in ("", "—", "-"):
                # 按表头名报告（列顺序经改造5修正：故障类别在第2列，用表头名最准）
                col_name = headers[j] if j < len(headers) else f"第{j+1}列"
                empty_rows.append(f"第{i+3}行的{col_name}为空")

    if empty_rows:
        report.results.append(CheckResult(
            level="warning", check="必填字段", file=filepath,
            message=f"{len(empty_rows)} 处必填维度为空：{'; '.join(empty_rows[:5])}",
        ))


def check_d5_confidence(report: ValidationReport, filepath: str):
    """D5置信标注检查：统计各置信级别分布，检出未标注的参数。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    # 找到 D5 列
    d5_idx = None
    for i, h in enumerate(headers):
        if "D5" in h or "特征参数" in h:
            d5_idx = i
            break
    if d5_idx is None:
        return

    untagged = 0   # 完全没有置信标注
    pending = 0    # 标注为"待核实"
    standard = 0   # 标注为"标准值"
    experience = 0 # 标注为"经验值"（纯经验值，不含"未核实"）
    unverified = 0 # 标注为"经验值-未核实"（兜底降级）

    for row in rows:
        if d5_idx >= len(row):
            continue
        d5_val = row[d5_idx]
        # 按参数项标签 [xxx] 边界拆分（参数项内部可能含；如"适用：xxx；置信：yyy"，按；拆会误判前段未标注）
        _m = list(re.finditer(r"\[[^\]]+\]", d5_val))
        if _m:
            params = []
            for k, mm in enumerate(_m):
                start = mm.start()
                end = _m[k + 1].start() if k + 1 < len(_m) else len(d5_val)
                params.append(d5_val[start:end])
        else:
            params = re.split(r"[；;]", d5_val)  # 无标签fallback按；拆
        for p in params:
            p = p.strip()
            if not p or p in ('---', '-', '—'):
                continue
            if "置信：标准值" in p or "置信:标准值" in p:
                standard += 1
            elif "经验值-未核实" in p or "经验值：未核实" in p:
                unverified += 1
            elif "置信：经验值" in p or "置信:经验值" in p:
                experience += 1
            elif "置信：待核实" in p or "置信:待核实" in p:
                pending += 1
            elif "待核实" in p or "经验值" in p:
                # 兼容旧格式（缺少"置信："前缀的简写）
                untagged += 1
            else:
                untagged += 1

    total = untagged + pending + standard + experience + unverified
    if total == 0:
        return

    # 累加到全库汇总计数器
    report.d5_stats["standard"] += standard
    report.d5_stats["experience"] += experience
    report.d5_stats["experience_unverified"] += unverified
    report.d5_stats["pending"] += pending
    report.d5_stats["untagged"] += untagged

    fname = os.path.basename(filepath)
    # 未标注的参数视为高优先级警告
    if untagged > 0:
        report.results.append(CheckResult(
            level="warning", check="D5置信标注", file=filepath,
            message=f"{fname}: {untagged}/{total}条参数缺少置信标注（标准值{standard}/经验值{experience}/未核实{unverified}/待核实{pending}/未标注{untagged}）",
        ))
    else:
        report.results.append(CheckResult(
            level="ok", check="D5置信标注", file=filepath,
            message=f"{fname}: 全部{total}条参数已标注（标准值{standard}/经验值{experience}/未核实{unverified}/待核实{pending}）",
        ))


def check_maintenance_confidence(report: ValidationReport, filepath: str):
    """检维修5列置信标注检查（改造6新增）。

    复用 D5 置信机制：用工需求/工机具/备件用料/安全注意事项/验收标准 每列内容末尾应标注置信级别
    （标准值/经验值/待核实）。安全注意事项、验收标准鼓励标"标准值"并带标准号。
    选填列：内容为"—"或空时不计入。非17列格式（旧数据）跳过，保证向后兼容。
    """
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    maint_col_names = ["D11", "D12", "D13", "D14", "D15"]
    col_indices = []
    for name in maint_col_names:
        for i, h in enumerate(headers):
            if h.strip().startswith(name):
                col_indices.append(i)
                break

    if not col_indices:  # 非17列格式（旧数据），跳过
        return

    untagged = 0
    standard = 0
    experience = 0
    total = 0

    for row in rows:
        for i in col_indices:
            if i >= len(row):
                continue
            val = row[i].strip()
            if val in ("", "—", "-"):
                continue  # 选填列，空值不计
            total += 1
            if "置信：标准值" in val or "置信:标准值" in val:
                standard += 1
            elif "置信：经验值" in val or "置信:经验值" in val:
                experience += 1
            elif "置信：待核实" in val or "置信:待核实" in val or "经验值-未核实" in val:
                experience += 1  # 已标注，归入经验类统计
            else:
                untagged += 1

    fname = os.path.basename(filepath)
    if total > 0 and untagged > 0:
        report.results.append(CheckResult(
            level="warning", check="检维修置信标注", file=filepath,
            message=f"{fname}: 检维修5列有{untagged}/{total}条内容缺少置信标注（标准值{standard}/经验值{experience}/未标注{untagged}）",
        ))
    elif total > 0:
        report.results.append(CheckResult(
            level="ok", check="检维修置信标注", file=filepath,
            message=f"{fname}: 全部{total}条检维修内容已标注置信（标准值{standard}/经验值{experience}）",
        ))


def check_d5_standard_whitelist(report: ValidationReport, filepath: str):
    """D5标准号检查（路线9放宽）：标准号格式合法（带号的标准编号）即允许，
    不强制在 D5_STANDARD_REFERENCE 白名单内。标准号真实性（防伪造）由 judge 第16项把关。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return
    d5_idx = None
    for i, h in enumerate(headers):
        if "D5" in h or "特征参数" in h:
            d5_idx = i
            break
    if d5_idx is None:
        return

    try:
        from pipeline.config import D5_STANDARD_REFERENCE, INDUSTRY_CODES, SUB_INDUSTRY_CODES
    except ImportError:
        return

    _VALID_STANDARDS = set()
    for info in D5_STANDARD_REFERENCE.values():
        for std_num, _scope in info["standards"]:
            _VALID_STANDARDS.add(std_num.upper().replace(" ", ""))

    _STANDARD_REF_PATTERN = re.compile(
        r"(?:DL/T|GB/T|GB|IEC|ISO|ASME|VDI|AGMA|IEEE|TSG|NB|HJ|JB|NAS)\s*[A-Z]?\s*\d+(?:[.-]\d+)*"
    )

    # 路线9放宽：标准号格式合法（_STANDARD_REF_PATTERN 匹配，如 DL/T xxxx、GB/T xxxx、IEC xxxx）
    # 即允许，不强制在 D5_STANDARD_REFERENCE 白名单内——行业标准众多无法穷举，
    # 白名单仅作"已知标准"参考。标准号真实性（防伪造）由 judge 第16项"D5假冒标准值核查"把关。
    # 故此处不再对白名单外的标准号产生 WARNING。
    _ = _STANDARD_REF_PATTERN  # 保留引用（供未来按需恢复严格白名单检查）


def check_d8_level(report: ValidationReport, filepath: str):
    """D8规程级/经验级标注检查：统计各级别分布，检出未标注的行。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    # 找到 D8 列
    d8_idx = None
    for i, h in enumerate(headers):
        if "D8" in h or "检修" in h:
            d8_idx = i
            break
    if d8_idx is None:
        return

    regulatory = 0
    experience = 0
    unlabeled = 0

    for row in rows:
        if d8_idx >= len(row):
            continue
        d8_val = row[d8_idx].strip()
        if not d8_val or d8_val in ("—", "-"):
            continue
        if "[规程级]" in d8_val:
            regulatory += 1
        elif "[经验级]" in d8_val:
            experience += 1
        else:
            unlabeled += 1

    total = regulatory + experience + unlabeled
    if total == 0:
        return

    report.d8_stats["regulatory"] += regulatory
    report.d8_stats["experience"] += experience
    report.d8_stats["unlabeled"] += unlabeled

    fname = os.path.basename(filepath)
    if unlabeled > 0:
        report.results.append(CheckResult(
            level="warning", check="D8级别标注", file=filepath,
            message=f"{fname}: {unlabeled}/{total}条故障缺少级别标注（规程级{regulatory}/经验级{experience}/未标注{unlabeled}）",
        ))
    else:
        report.results.append(CheckResult(
            level="ok", check="D8级别标注", file=filepath,
            message=f"{fname}: 全部{total}条已标注（规程级{regulatory}/经验级{experience}）",
        ))


def check_d5_d6_crossfill(report: ValidationReport, filepath: str):
    """D5/D6互填检测：检查参数阈值是否误写在D6，传感器是否误写在D5。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    d5_idx = None
    d6_idx = None
    for i, h in enumerate(headers):
        if "D5" in h or "特征参数" in h:
            d5_idx = i
        elif "D6" in h or "监测" in h:
            d6_idx = i
    if d5_idx is None or d6_idx is None:
        return

    # D5中不应出现的传感器关键词
    sensor_keywords = ["传感器", "探头", "检测仪", "监测装置", "在线监测", "巡检仪"]
    # D6中不应出现的阈值模式
    threshold_pattern = re.compile(r'[>≥＞<≤＜]\s*\d+\.?\d*\s*(mm|μm|ppm|mg|kV|MΩ|dB|%|℃|°C|Hz|rpm)')

    # 任意阈值迹象（>数字 等）：D5若同时含阈值，说明是参数描述里顺带提到传感器，不算互填
    any_threshold = re.compile(r'[>≥＞<≤＜~≈]\s*\d')
    monitor_keywords = ["在线", "离线", "带电", "传感器", "探头", "检测", "监测", "测量",
                        "巡检", "目视", "仪", "表", "分析"]

    crossfills = []
    for i, row in enumerate(rows):
        if d5_idx < len(row):
            d5_val = row[d5_idx]
            has_thresh = bool(any_threshold.search(d5_val))
            for kw in sensor_keywords:
                if kw in d5_val:
                    # 仅当D5不含任何阈值（纯监测手段、无参数）时才判为真互填
                    if not has_thresh:
                        crossfills.append(f"第{i+3}行D5疑似纯监测手段（含'{kw}'且无参数阈值，应填在D6）")
                    break

        if d6_idx < len(row):
            d6_val = row[d6_idx]
            if threshold_pattern.search(d6_val):
                has_monitor = any(kw in d6_val for kw in monitor_keywords)
                # 仅当D6不含任何监测手段词（纯阈值、无监测描述）时才判为真互填
                if not has_monitor:
                    crossfills.append(f"第{i+3}行D6疑似纯阈值表达式（无监测手段词，应填在D5）")

    if crossfills:
        report.results.append(CheckResult(
            level="warning", check="D5/D6互填", file=filepath,
            message=f"{os.path.basename(filepath)}: 检出{len(crossfills)}处疑似互填：{'; '.join(crossfills[:5])}",
        ))


def check_fault_category(report: ValidationReport, filepath: str):
    """故障类别取值校验（改造5 §5.4）：必须在 failure_categories.yaml 白名单内。

    故障类别由静态 yaml 维护，LLM 只能从枚举中选择，禁止自创。支持多值（限1-3个），
    多值必须用全角"；"分隔（禁止半角";"），每个值须在白名单内。
    合法标签 = 所有分组的 categories 并集。
    """
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return
    cat_idx = None
    for i, h in enumerate(headers):
        if "故障类别" in h:
            cat_idx = i
            break
    if cat_idx is None:
        return
    # 加载白名单（所有分组的 categories 并集）
    try:
        from pipeline.config import FAILURE_CATEGORIES
    except Exception:
        return
    valid = set()
    for g in FAILURE_CATEGORIES.get("groups", {}).values():
        for c in g.get("categories", []):
            valid.add(c.strip())
    if not valid:
        return

    fname = os.path.basename(filepath)
    bad = []      # 原子值不在白名单
    semi = []     # 半角分号残留
    toomany = []  # 类别数>3
    for ri, row in enumerate(rows):
        if cat_idx >= len(row):
            continue
        val = row[cat_idx].strip()
        if val in ("", "—", "-"):
            continue
        # 分隔符规范：必须用全角 ；，禁止半角 ;
        if ";" in val:
            semi.append(f"第{ri+3}行")
        parts = [p.strip() for p in re.split(r"[;；]", val) if p.strip()]
        if len(parts) > 3:
            toomany.append(f"第{ri+3}行({len(parts)}个)")
        for p in parts:
            if p not in valid:
                bad.append(f"第{ri+3}行故障类别='{p}'")

    if bad:
        report.results.append(CheckResult(
            level="warning", check="故障类别白名单", file=filepath,
            message=f"{fname}: {len(bad)} 处故障类别值不在白名单（共{len(valid)}个合法标签）：{'; '.join(bad[:5])}",
        ))
    if semi:
        report.results.append(CheckResult(
            level="warning", check="故障类别分隔符", file=filepath,
            message=f"{fname}: {len(semi)} 处故障类别用了半角分号';'，须统一为全角'；'：{'; '.join(semi[:5])}",
        ))
    if toomany:
        report.results.append(CheckResult(
            level="warning", check="故障类别数量", file=filepath,
            message=f"{fname}: {len(toomany)} 处故障类别超过3个（限1-3个）：{'; '.join(toomany[:5])}",
        ))


def check_d1_enum(report: ValidationReport, filepath: str):
    """D1 物理属性取值校验：必须在 机械/电气/绝缘/热/化学/控制/环境 内（多选用 ; 或 ；分隔）。

    合法值来源：schemas.py SCHEMA["D1"]["options"]。防止 LLM 自创如"物理"等非枚举值。
    """
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    d1_idx = None
    for i, h in enumerate(headers):
        if "D1" in h or "物理属性" in h:
            d1_idx = i
            break
    if d1_idx is None:
        return

    valid = {"机械", "电气", "绝缘", "热", "化学", "控制", "环境"}
    fname = os.path.basename(filepath)
    bad = []
    for ri, row in enumerate(rows):
        if d1_idx >= len(row):
            continue
        val = row[d1_idx].strip()
        if val in ("", "—", "-"):
            continue
        # 多选用 ; 或 ；分隔，逐项校验
        parts = [p.strip() for p in re.split(r"[;；]", val) if p.strip()]
        for p in parts:
            if p not in valid:
                bad.append(f"第{ri+3}行D1='{p}'")

    if bad:
        report.results.append(CheckResult(
            level="warning", check="D1物理属性取值", file=filepath,
            message=f"{fname}: {len(bad)} 处D1取值非枚举（合法：机械/电气/绝缘/热/化学/控制/环境）：{'; '.join(bad[:5])}",
        ))


def check_d2_severity_distribution(report: ValidationReport, filepath: str):
    """D2严重度分布异常检测：若某部件80%以上故障被标为同一等级，可能是LLM偏置。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    d2_idx = None
    for i, h in enumerate(headers):
        if "D2" in h or "故障等级" in h:
            d2_idx = i
            break
    if d2_idx is None:
        return

    if len(rows) < 3:
        return

    counts = {}
    for row in rows:
        if d2_idx >= len(row):
            continue
        level = row[d2_idx].strip()
        if level:
            counts[level] = counts.get(level, 0) + 1

    total = sum(counts.values())
    if total == 0:
        return

    n_levels = len(counts)
    for level, count in counts.items():
        ratio = count / total
        if ratio >= 0.8 and total >= 3:
            # 有≥2个等级（存在梯度区分，如4严重+1危急）视为合理集中，不报偏置；
            # 仅100%单等级（无任何梯度）才报，提示人工确认是否真偏置
            if n_levels >= 2:
                return
            report.results.append(CheckResult(
                level="warning", check="D2严重度偏置", file=filepath,
                message=f"{os.path.basename(filepath)}: D2严重度分布异常——100%({count}/{total})被标为'{level}'且无等级梯度，疑似LLM偏置（若该部件故障客观同质则为合理分布，请人工确认）",
            ))
            return


def check_standard_version_age(report: ValidationReport, filepath: str):
    """标准号版本时效检测：扫描所有引用的标准号，标记10年以上的版本。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    std_pattern = re.compile(r'(GB/T|DL/T|JB/T|NB/T|IEC|ISO|IEEE)\s*\d+(?:\.\d+)?-(\d{4})')
    current_year = 2026
    old_standards = []

    for row in rows:
        for cell in row:
            for match in std_pattern.finditer(cell):
                year = int(match.group(2))
                age = current_year - year
                if age >= 10:
                    std_ref = match.group(0).strip()
                    old_standards.append(f"{std_ref}（{age}年前）")

    if old_standards:
        unique_old = list(dict.fromkeys(old_standards))
        report.results.append(CheckResult(
            level="warning", check="标准版本时效", file=filepath,
            message=f"{os.path.basename(filepath)}: 检出{len(unique_old)}个10年以上的标准引用：{'; '.join(unique_old[:5])}",
        ))


def check_fault_name_consistency(report: ValidationReport, equip_dir: str):
    """跨部件故障命名一致性扫描：检测相似故障名（可能是同义异名）。"""
    faults_dir = os.path.join(equip_dir, "faults")
    if not os.path.isdir(faults_dir):
        return

    all_fault_names = {}
    for f in sorted(os.listdir(faults_dir)):
        if not f.endswith(".md"):
            continue
        fpath = os.path.join(faults_dir, f)
        headers, rows = parse_md_table(fpath)
        if not rows:
            continue
        comp_name = os.path.splitext(f)[0]
        for row in rows:
            if row:
                fault_name = row[0].strip()
                if fault_name:
                    all_fault_names.setdefault(fault_name, []).append(comp_name)

    # 检测相似命名（简单编辑距离启发式）
    names = list(all_fault_names.keys())
    similar_pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if abs(len(a) - len(b)) > 3:
                continue
            # 计算共同字符比例
            common = sum(1 for c in a if c in b)
            ratio = common / max(len(a), len(b))
            if ratio >= 0.85 and a != b:
                similar_pairs.append(f"'{a}' vs '{b}'")

    if similar_pairs:
        report.results.append(CheckResult(
            level="warning", check="故障命名一致性", file=faults_dir,
            message=f"检出{len(similar_pairs)}对相似故障名，可能需要归并：{'; '.join(similar_pairs[:5])}",
        ))


# ── 编码唯一性与格式校验（改造7）──

# 目录 slug → 中文子行业名（与 md_to_json.SUB_SLUGS 反向一致，用于从路径推断子行业代码）
_SUB_SLUGS_REVERSE = {
    "thermal": "火电", "hydro": "水电", "wind": "风电", "pv": "光伏",
    "nuclear": "核电", "gas_turbine": "燃气轮机", "pumped_storage": "抽水蓄能",
    "transmission": "输电", "substation": "变电", "distribution": "配电",
    "energy_storage": "储能",
}
# 行业目录名 → 中文行业名（与 md_to_json.build_industry 的 name_map 一致）
_INDUSTRY_DIR_NAMES = {
    "power": "电力", "petrochemical": "石化", "metallurgy": "冶金",
    "cement": "水泥", "coal": "煤炭", "rail_transit": "轨道交通",
    "manufacturing": "制造业", "aerospace_marine": "航空航天与船舶",
}

_CODE_PATTERN = re.compile(
    r'^[A-Z]{2}(-[A-Z]{2})?-\d{3}(-\d{3})?-\d{3}-\d{3}-\d{3}-\d{3}$'
)


def _build_code_for_validate(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, part_idx, fault_idx=None):
    """段式编码格式化原语（与 md_to_json.build_code 规则一致，独立实现以交叉验证）。"""
    def _seg(v):
        if v is None:
            return None
        if isinstance(v, str):
            return v
        return f"{int(v):03d}"
    parts = [ind_code]
    if sub_code:
        parts.append(sub_code)
    parts.append(_seg(eq_idx))
    if se_idx is not None:
        parts.append(_seg(se_idx))
    parts.append(_seg(ss_idx))
    parts.append(_seg(comp_idx))
    parts.append(_seg(part_idx))
    if fault_idx is not None:
        parts.append(_seg(fault_idx))
    return "-".join(parts)


def _infer_codes_from_path(target: str):
    """从路径组件推断 (ind_code, sub_code)。遍历路径各段，匹配行业/子行业目录名。"""
    try:
        from pipeline.config import INDUSTRY_CODES, SUB_INDUSTRY_CODES
    except ImportError:
        INDUSTRY_CODES = {"电力": "PW", "石化": "PE", "冶金": "MT", "水泥": "CM",
                          "煤炭": "CL", "轨道交通": "RT", "制造业": "MF", "航空航天与船舶": "AS"}
        SUB_INDUSTRY_CODES = {"火电": "TH", "水电": "HY", "风电": "WI", "光伏": "PV",
                              "核电": "NU", "燃气轮机": "GT", "抽水蓄能": "PS",
                              "输电": "TM", "变电": "SS", "配电": "DS", "储能": "ES"}
    parts = os.path.normpath(target).replace("\\", "/").split("/")
    ind_code = sub_code = None
    for p in parts:
        if p in _INDUSTRY_DIR_NAMES:
            ind_code = INDUSTRY_CODES.get(_INDUSTRY_DIR_NAMES[p], ind_code)
        elif p in _SUB_SLUGS_REVERSE:
            sub_code = SUB_INDUSTRY_CODES.get(_SUB_SLUGS_REVERSE[p], sub_code)
    return ind_code, sub_code


def _find_eq_dir(sub_dir: str, eq_name: str) -> str | None:
    """根据设备名查找其目录（镜像 md_to_json.find_eq_dir；EQ_SLUGS 为共享目录映射数据，非生成逻辑）。"""
    try:
        from md_to_json import EQ_SLUGS
    except ImportError:
        EQ_SLUGS = {}
    slug = EQ_SLUGS.get(eq_name)
    if slug and os.path.isdir(os.path.join(sub_dir, slug)):
        return os.path.join(sub_dir, slug)
    direct = eq_name.replace("/", "_").replace("／", "_").replace("（", "(").replace("）", ")")
    if os.path.isdir(os.path.join(sub_dir, direct)):
        return os.path.join(sub_dir, direct)
    return None


def check_encoding(report: ValidationReport, target: str, auto_fix: bool = False):
    """编码唯一性与格式校验（改造7）。

    独立遍历目录树按规则重算码，校验：
      ① 格式匹配正则（行业2字母[-子行业2字母]-设备3[-子设备3]-子系统3-部件3-零件3-故障3）
      ② 全局无重复（重复即违反 MECE 唯一性）
    故意不 import md_to_json 的生成逻辑（避免循环论证）；遍历顺序对齐（文件行顺序 + sorted）。
    target: 行业目录 / 子行业目录 / 设备目录（自适应）。
    """
    ind_code, sub_code = _infer_codes_from_path(target)
    if ind_code is None:
        # 无法推断行业代码（路径不含已知行业目录），跳过
        report.results.append(CheckResult(
            level="warning", check="编码格式", file=target,
            message="无法从路径推断行业代码，跳过编码校验",
        ))
        return

    codes_seen: dict = {}        # code -> (fault_name, path)
    duplicates = []              # (code, fault_name, path, prev)
    invalid_format = []          # (code, path)
    total_codes = 0

    def _record(code: str, fault_name: str, path: str):
        nonlocal total_codes
        total_codes += 1
        if not _CODE_PATTERN.match(code):
            invalid_format.append((code, path))
        if code in codes_seen:
            duplicates.append((code, fault_name, path, codes_seen[code]))
        else:
            codes_seen[code] = (fault_name, path)

    def _read_faults(faults_dir: str, name: str):
        safe = name.replace("/", "／")
        fpath = os.path.join(faults_dir, f"{safe}.md")
        if not os.path.exists(fpath):
            return []
        _, rows = parse_md_table(fpath)
        return [(row[0].strip(), fpath) for row in rows if row]

    def _process_device_base(base_dir, eq_idx, se_idx):
        """处理子设备/设备目录本体（sub_system.md 新格式 或 components.md 旧格式）。"""
        ss_path = os.path.join(base_dir, "sub_system.md")
        if os.path.exists(ss_path):
            _, ss_rows = parse_md_table(ss_path)
            for ss_idx, ss_row in enumerate(ss_rows, 1):
                if not ss_row:
                    continue
                ss_name = ss_row[0].strip()
                comp_path = os.path.join(base_dir, ss_name, "components.md")
                if not os.path.exists(comp_path):
                    continue
                _, comp_rows = parse_md_table(comp_path)
                comp_idx = 0
                part_idx = 0
                last_comp = None
                for crow in comp_rows:
                    if not crow or len(crow) < 2:
                        continue
                    comp_name = crow[0].strip()
                    part_name = crow[1].strip()
                    if comp_name != last_comp:
                        comp_idx += 1
                        part_idx = 0
                        last_comp = comp_name
                    if part_name in ("—", "-", ""):
                        faults = _read_faults(os.path.join(base_dir, ss_name, comp_name, "faults"), comp_name)
                        for f_idx, (fn, fp) in enumerate(faults, 1):
                            code = _build_code_for_validate(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, "000", f_idx)
                            _record(code, fn, fp)
                    else:
                        part_idx += 1
                        faults = _read_faults(os.path.join(base_dir, ss_name, part_name, "faults"), part_name)
                        for f_idx, (fn, fp) in enumerate(faults, 1):
                            code = _build_code_for_validate(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, part_idx, f_idx)
                            _record(code, fn, fp)
        else:
            # 旧格式扁平 components.md（子系统段=000，零件段=000）
            comp_path = os.path.join(base_dir, "components.md")
            if not os.path.exists(comp_path):
                return
            _, comp_rows = parse_md_table(comp_path)
            seen_comp = {}
            comp_idx = 0
            for crow in comp_rows:
                if not crow:
                    continue
                comp_name = crow[0].strip()
                if comp_name and comp_name not in seen_comp:
                    comp_idx += 1
                    seen_comp[comp_name] = comp_idx
                    faults = _read_faults(os.path.join(base_dir, "faults"), comp_name)
                    for f_idx, (fn, fp) in enumerate(faults, 1):
                        code = _build_code_for_validate(ind_code, sub_code, eq_idx, se_idx, "000", comp_idx, "000", f_idx)
                        _record(code, fn, fp)

    def _process_equipment(eq_dir, eq_idx):
        sub_eq_path = os.path.join(eq_dir, "sub_equipment.md")
        if os.path.exists(sub_eq_path):
            _, se_rows = parse_md_table(sub_eq_path)
            for se_idx, se_row in enumerate(se_rows, 1):
                if not se_row:
                    continue
                se_name = se_row[0].strip()
                se_dir = os.path.join(eq_dir, se_name.replace("/", "／"))
                _process_device_base(se_dir, eq_idx, se_idx)
        else:
            _process_device_base(eq_dir, eq_idx, None)

    # 自适应 target 层级
    if os.path.exists(os.path.join(target, "equipment_registry.md")):
        # 子行业目录：读设备清单，按顺序编号
        reg_path = os.path.join(target, "equipment_registry.md")
        _, eq_rows = parse_md_table(reg_path)
        for eq_idx, eq_row in enumerate(eq_rows, 1):
            if not eq_row:
                continue
            eq_name = eq_row[0].strip()
            eq_dir = _find_eq_dir(target, eq_name)
            if eq_dir:
                _process_equipment(eq_dir, eq_idx)
    elif os.path.exists(os.path.join(target, "sub_system.md")) \
            or os.path.exists(os.path.join(target, "sub_equipment.md")) \
            or os.path.exists(os.path.join(target, "components.md")):
        # 单设备目录：eq_idx 无法从清单推断，用 1（仅校验设备内唯一性 + 格式）
        _process_equipment(target, 1)
    else:
        # 可能是行业目录，递归找子行业
        for d in sorted(os.listdir(target)):
            sub_dir = os.path.join(target, d)
            if os.path.isdir(sub_dir) and os.path.exists(os.path.join(sub_dir, "equipment_registry.md")):
                check_encoding(report, sub_dir, auto_fix)
        return

    # 汇总
    if invalid_format:
        details = [f"{c} @ {os.path.relpath(p)}" for c, p in invalid_format[:5]]
        report.results.append(CheckResult(
            level="error", check="编码格式", file=target,
            message=f"{len(invalid_format)} 个编码格式不合法：{'; '.join(details)}",
        ))
    if duplicates:
        details = [f"'{c}'（{fn}@{os.path.relpath(fp)} vs {pn}@{os.path.relpath(pp)}）"
                   for c, fn, fp, (pn, pp) in duplicates[:5]]
        report.results.append(CheckResult(
            level="error", check="编码唯一性", file=target,
            message=f"{len(duplicates)} 个编码重复（违反 MECE 唯一性）：{'; '.join(details)}",
        ))
    if total_codes > 0 and not invalid_format and not duplicates:
        report.results.append(CheckResult(
            level="ok", check="编码校验", file=target,
            message=f"共 {total_codes} 个故障编码，格式合法且全局唯一",
        ))


def check_cross_subsystem_dup(report: ValidationReport, equip_dir: str):
    """跨子系统MECE校验：扫描设备下所有子系统的 components.md，
    检测部件名/零件名是否在>1个子系统中出现。"""
    sub_systems = _read_sub_systems(equip_dir)
    if not sub_systems:
        return

    # name -> set(ss_name)  每个名称出现在哪些子系统中
    name_ss_map: dict[str, set[str]] = {}

    for ss_name, _ in sub_systems:
        comp_path = os.path.join(equip_dir, ss_name, "components.md")
        if not os.path.exists(comp_path):
            continue
        headers, rows = parse_md_table(comp_path)
        if not headers or not rows:
            continue
        try:
            comp_idx = headers.index("部件")
            part_idx = headers.index("零件")
        except ValueError:
            continue
        for row in rows:
            comp = row[comp_idx].strip()
            part = row[part_idx].strip()
            if comp:
                name_ss_map.setdefault(comp, set()).add(ss_name)
            if part and part not in ("—", "-", ""):
                name_ss_map.setdefault(part, set()).add(ss_name)

    # 找出出现在>1个子系统的名称
    dupes = {name: ss_set for name, ss_set in name_ss_map.items() if len(ss_set) > 1}
    if dupes:
        details = []
        for name, ss_set in dupes.items():
            ss_list = "、".join(f"「{ss}」" for ss in ss_set)
            details.append(f"「{name}」出现在 {ss_list}")
        report.results.append(CheckResult(
            level="error", check="跨子系统MECE", file=equip_dir,
            message=f"发现 {len(dupes)} 个跨子系统重复件（违反MECE）：{'; '.join(details[:10])}",
        ))


# ── 阶段校验 ──

def _read_sub_systems(base_dir: str) -> list[tuple[str, str]]:
    """读取 sub_system.md，返回 [(子系统名称, 描述), ...]。"""
    ss_path = os.path.join(base_dir, "sub_system.md")
    if not os.path.exists(ss_path):
        return []
    headers, rows = parse_md_table(ss_path)
    if not headers or not rows:
        return []
    try:
        name_idx = headers.index("子系统名称")
        desc_idx = headers.index("描述")
    except ValueError:
        return []
    return [(row[name_idx].strip(), row[desc_idx].strip()) for row in rows]


def validate_sub_system(report: ValidationReport, target: str, auto_fix: bool):
    """校验 sub_system.md（新格式专用）。"""
    ss_path = os.path.join(target, "sub_system.md")
    if not os.path.exists(ss_path):
        return
    check_dedup(report, ss_path, auto_fix=auto_fix)
    expected = SCHEMA_NEW["sub_system"]["headers"]["sub_system.md"]
    check_headers(report, ss_path, expected)
    # 子系统数量限制（v3.1）：>6 WARNING（仅大型主设备允许），>7 阻断
    sub_systems = _read_sub_systems(target)
    n_ss = len(sub_systems)
    if n_ss > 7:
        report.results.append(CheckResult(level="error", check="子系统数量", file=ss_path,
            message=f"子系统数 {n_ss} 超过硬上限7，须论证功能不可合并或精简"))
    elif n_ss > 6:
        report.results.append(CheckResult(level="warning", check="子系统数量", file=ss_path,
            message=f"子系统数 {n_ss}>6，仅大型主设备（锅炉/汽轮机/反应器）允许，须论证功能不可合并"))


def validate_stage2(report: ValidationReport, target: str, auto_fix: bool):
    """校验阶段2：设备枚举。"""
    schema = SCHEMA[2]

    for fname in schema["files"]:
        fpath = os.path.join(target, fname)
        if not os.path.exists(fpath):
            continue

        check_dedup(report, fpath, auto_fix=auto_fix)

        expected = schema["headers"].get(fname)
        if expected:
            check_headers(report, fpath, expected)


def check_component_naming(report, filepath):
    """部件/零件命名规范：禁总成后缀、禁本体零件、禁过度细化（防再生）。"""
    OVER_FINE = {"外圈", "内圈", "滚动体", "保持架", "圆锥滚子", "圆柱滚子", "钢球", "滚珠", "滚子"}
    headers, rows = parse_md_table(filepath)
    if not headers or "部件" not in headers:
        return
    ci = headers.index("部件"); pi = headers.index("零件")
    fname = os.path.basename(filepath)
    for ri, row in enumerate(rows):
        if ci < len(row) and row[ci].strip().endswith("总成"):
            report.results.append(CheckResult(level="warning", check="部件命名", file=filepath,
                message=f"{fname}: 第{ri+2}行部件'{row[ci].strip()}'含'总成'后缀，应去掉"))
        if pi < len(row):
            p = row[pi].strip()
            if p not in ("—", "") and p.endswith("本体"):
                report.results.append(CheckResult(level="warning", check="部件命名", file=filepath,
                    message=f"{fname}: 第{ri+2}行零件'{p}'为'XX本体'，部件自身不该作零件"))
            elif p in OVER_FINE:
                report.results.append(CheckResult(level="warning", check="部件命名", file=filepath,
                    message=f"{fname}: 第{ri+2}行零件'{p}'过度细化（不可独立拆换）"))


def check_fault_cross_layer(report, ss_dir, comp_path):
    """部件级故障若指向具体零件（含零件名）= 越界告警（防再生）。"""
    headers, rows = parse_md_table(comp_path)
    if not headers or "部件" not in headers:
        return
    ci = headers.index("部件"); pi = headers.index("零件")
    part_names = set(); comp_level = set()
    for row in rows:
        p = row[pi].strip() if pi < len(row) else ""
        c = row[ci].strip() if ci < len(row) else ""
        if p and p != "—":
            part_names.add(p)
        if p == "—" and c:
            comp_level.add(c)
    OVERALL = ["振动", "温度", "油质", "油路", "接口", "耦合", "整体", "综合", "性能", "系统", "功能", "噪声", "效率", "功率", "进水"]
    for comp in comp_level:
        fp = os.path.join(ss_dir, comp, "faults", comp + ".md")
        if not os.path.exists(fp):
            continue
        fh, frows = parse_md_table(fp)
        for ri, row in enumerate(frows):
            fn = row[0].strip() if row else ""
            if any(w in fn for w in OVERALL):
                continue
            for pn in part_names:
                if pn in fn and pn != comp and comp not in fn:
                    report.results.append(CheckResult(level="warning", check="故障越界", file=fp,
                        message=f"{comp}.md: 故障'{fn}'指向零件'{pn}'，应挂零件级"))
                    break


def validate_stage3(report: ValidationReport, target: str, auto_fix: bool):
    """校验阶段3：部件拆解。自动检测新旧格式。"""
    if is_new_format(target):
        # 新格式：先校验 sub_system.md，再逐子系统校验 components.md
        validate_sub_system(report, target, auto_fix)
        sub_systems = _read_sub_systems(target)
        for ss_name, _ in sub_systems:
            ss_dir = os.path.join(target, ss_name)
            comp_path = os.path.join(ss_dir, "components.md")
            if not os.path.exists(comp_path):
                continue
            check_dedup(report, comp_path, auto_fix=auto_fix)
            expected = SCHEMA_NEW[3]["headers"]["components.md"]
            check_headers(report, comp_path, expected)
            check_parent_refs(report, comp_path)
            check_required_fields_comp(report, comp_path)
            check_component_naming(report, comp_path)
            check_fault_cross_layer(report, ss_dir, comp_path)
        # 跨子系统MECE校验
        check_cross_subsystem_dup(report, target)
    else:
        # 旧格式
        schema = SCHEMA[3]
        for fname in schema["files"]:
            fpath = os.path.join(target, fname)
            if not os.path.exists(fpath):
                continue
            check_dedup(report, fpath, auto_fix=auto_fix)
            expected = schema["headers"].get(fname)
            if expected:
                check_headers(report, fpath, expected)
            check_parent_refs(report, fpath)
            check_required_fields_comp(report, fpath)


def validate_stage4(report: ValidationReport, target: str, auto_fix: bool):
    """校验阶段4：故障知识。自动检测新旧故障格式（12列 vs 11列）。"""
    schema = SCHEMA[4]

    # 递归收集 target 下所有 faults/ 目录中的 .md 文件
    # 兼容旧格式（target/faults/）与新三层格式（子系统/部件/faults/、子系统/部件/零件/faults/）
    fault_files = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in ("_archive", "__pycache__")]
        if os.path.basename(root) != "faults":
            continue
        for f in sorted(files):
            if f.endswith(".md"):
                fault_files.append(os.path.join(root, f))

    for fpath in fault_files:
        check_dedup(report, fpath, auto_fix=auto_fix)

        # Detect fault format: old (11-col) vs retrofit5 (12-col) vs retrofit6 (17-col)
        headers, _ = parse_md_table(fpath)
        is_new_fault = any("物理属性" in h for h in headers) if headers else False
        if is_new_fault:
            is_retrofit6 = any(h.strip().startswith("D11") or h.strip().startswith("D15") for h in headers) if headers else False
            expected = schema["headers"]["fault_retrofit6"] if is_retrofit6 else schema["headers"]["fault"]
        else:
            expected = schema["headers"]["fault_old"]
        check_headers(report, fpath, expected)

        check_required_fields_fault(report, fpath)
        check_d1_enum(report, fpath)  # 改造6补：D1物理属性取值枚举校验
        check_fault_category(report, fpath)  # 改造5补：故障类别白名单校验
        check_d5_confidence(report, fpath)
        check_maintenance_confidence(report, fpath)  # 改造6新增：检维修5列置信检查
        check_d5_standard_whitelist(report, fpath)
        check_d8_level(report, fpath)
        check_d5_d6_crossfill(report, fpath)
        check_d2_severity_distribution(report, fpath)
        check_standard_version_age(report, fpath)

    check_fault_file_mapping(report, target)
    check_fault_name_consistency(report, target)


def validate_full(report: ValidationReport, target: str, auto_fix: bool):
    """全量校验：扫描target下的所有子目录，自动检测阶段并校验。"""
    for root, dirs, files in os.walk(target):
        # 跳过非数据目录和归档目录
        dirs[:] = [d for d in dirs if d not in ("_archive", "kb_exports", "__pycache__")]
        rel = os.path.relpath(root, target)
        if rel.startswith("docs") or rel.startswith("scripts"):
            continue

        # 阶段2文件
        for fname in ["equipment_registry.md", "sub_equipment.md"]:
            if fname in files:
                fpath = os.path.join(root, fname)
                check_dedup(report, fpath, auto_fix=auto_fix)
                expected = SCHEMA[2]["headers"].get(fname)
                if expected:
                    check_headers(report, fpath, expected)

        # 阶段3文件（自动检测新旧格式）
        if "components.md" in files:
            fpath = os.path.join(root, "components.md")
            # 检测格式
            comp_headers, _ = parse_md_table(fpath)
            if comp_headers and len(comp_headers) >= 2 and comp_headers[1].strip() == "零件":
                expected = SCHEMA_NEW[3]["headers"]["components.md"]
            else:
                expected = SCHEMA[3]["headers"]["components.md"]
            check_dedup(report, fpath, auto_fix=auto_fix)
            check_headers(report, fpath, expected)
            check_parent_refs(report, fpath)
            check_required_fields_comp(report, fpath)

        # sub_system.md（新格式）
        if "sub_system.md" in files:
            fpath = os.path.join(root, "sub_system.md")
            check_dedup(report, fpath, auto_fix=auto_fix)
            expected = SCHEMA_NEW["sub_system"]["headers"]["sub_system.md"]
            check_headers(report, fpath, expected)
            # 跨子系统MECE校验（只在包含 sub_system.md 的目录触发）
            check_cross_subsystem_dup(report, root)

        # 阶段4文件
        if os.path.isdir(os.path.join(root, "faults")):
            validate_stage4(report, root, auto_fix)

    # 编码唯一性与格式校验（改造7）：在原始 target 上一次性运行
    check_encoding(report, target, auto_fix)


# ── 报告输出 ──

def print_report(report: ValidationReport):
    print(f"\n{'='*60}")
    print(f"校验目标: {report.target}")
    print(f"{'='*60}")

    if not report.results:
        print("  所有检查通过，无问题。")
        return

    errors = report.errors
    warnings = report.warnings
    fixed = [r for r in report.results if r.auto_fixed]

    if fixed:
        print(f"\n🔧 自动修复 ({len(fixed)}):")
        for r in fixed:
            print(f"  [FIX] {os.path.relpath(r.file)}: {r.message}")

    if errors:
        print(f"\n❌ 阻断错误 ({len(errors)}):")
        for r in errors:
            print(f"  [ERROR] {os.path.relpath(r.file)} | {r.check}: {r.message}")

    if warnings:
        print(f"\n⚠️  警告 ({len(warnings)}):")
        for r in warnings:
            if r.auto_fixed:
                continue
            print(f"  [WARN] {os.path.relpath(r.file)} | {r.check}: {r.message}")

    status = "通过" if report.passed else "未通过（存在阻断错误）"
    print(f"\n结果: {status} | 错误: {len(errors)} | 警告: {len(warnings)} | 自动修复: {len(fixed)}")

    # 全库 D5 置信分布汇总
    d5 = report.d5_stats
    d5_total = d5["standard"] + d5["experience"] + d5["experience_unverified"] + d5["pending"] + d5["untagged"]
    if d5_total > 0:
        def pct(n):
            return f"{n/d5_total*100:.0f}%"
        print(f"\nD5置信分布（全库）: "
              f"标准值 {d5['standard']}条 ({pct(d5['standard'])}) / "
              f"经验值 {d5['experience']}条 ({pct(d5['experience'])}) / "
              f"经验值-未核实 {d5['experience_unverified']}条 ({pct(d5['experience_unverified'])}) / "
              f"待核实 {d5['pending']}条 ({pct(d5['pending'])}) / "
              f"未标注 {d5['untagged']}条 ({pct(d5['untagged'])})")

    # D8 规程级/经验级分布汇总
    d8 = report.d8_stats
    d8_total = d8["regulatory"] + d8["experience"] + d8["unlabeled"]
    if d8_total > 0:
        def d8_pct(n):
            return f"{n/d8_total*100:.0f}%"
        print(f"D8级别分布（全库）: "
              f"规程级 {d8['regulatory']}条 ({d8_pct(d8['regulatory'])}) / "
              f"经验级 {d8['experience']}条 ({d8_pct(d8['experience'])}) / "
              f"未标注 {d8['unlabeled']}条 ({d8_pct(d8['unlabeled'])})")


# ── 入口 ──

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="知识库自动化校验脚本")
    parser.add_argument("--stage", type=int, choices=[2, 3, 4], help="校验阶段（2/3/4），不指定则全量校验")
    parser.add_argument("--target", required=True, help="校验目标目录")
    parser.add_argument("--fix", action="store_true", help="自动修复可修复的问题（如去重）")
    args = parser.parse_args()

    target = os.path.normpath(args.target)
    if not os.path.isdir(target):
        print(f"目录不存在: {target}", file=sys.stderr)
        sys.exit(1)

    report = ValidationReport(target=target)

    if args.stage:
        validators = {2: validate_stage2, 3: validate_stage3, 4: validate_stage4}
        validators[args.stage](report, target, auto_fix=args.fix)
    else:
        validate_full(report, target, auto_fix=args.fix)

    print_report(report)
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
