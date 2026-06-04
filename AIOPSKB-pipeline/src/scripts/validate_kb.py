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

# ── Schema 定义 ──

SCHEMA = {
    2: {
        "files": ["equipment_registry.md", "sub_equipment.md"],
        "headers": {
            "equipment_registry.md": ["设备名称", "设备类型", "描述"],
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
            "fault": ["故障名称", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"],
        },
    },
}

FAULT_REQUIRED_COLS = [
    "故障名称", "D1_故障类别", "D2_故障等级", "D3_故障描述与机理",
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
    """父部件引用完整性检查（仅 components.md）。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

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


def check_fault_file_mapping(report: ValidationReport, equip_dir: str):
    """故障文件名与部件名称对应检查。"""
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

    # 叶节点必须有故障文件，父节点可选
    missing_files = leaf_names - fault_files
    # 故障文件必须对应某个部件（叶节点或父节点）
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


def check_required_fields_comp(report: ValidationReport, filepath: str):
    """components.md 必填字段非空检查（叶节点的维护方法、报废方法）。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

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


def check_required_fields_fault(report: ValidationReport, filepath: str):
    """故障文件必填字段非空检查（D1-D10）。D10允许"—"。"""
    headers, rows = parse_md_table(filepath)
    if not headers or not rows:
        return

    fname = os.path.basename(filepath)
    empty_rows = []

    for i, row in enumerate(rows):
        if len(row) < 11:
            continue
        # D1-D9 必填，D10 允许"—"
        all_empty = all(cell.strip() in ("", "—", "-") for cell in row[1:10])
        if all_empty:
            empty_rows.append(f"第{i+3}行")
            continue
        for j in range(1, min(10, len(row))):
            if row[j].strip() in ("", "—", "-"):
                col_letter = f"D{j}"
                empty_rows.append(f"第{i+3}行的{col_letter}为空")

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
        # 按常见分隔符拆分每条参数
        params = re.split(r'[；;]', d5_val)
        for p in params:
            p = p.strip()
            if not p:
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


def check_d5_standard_whitelist(report: ValidationReport, filepath: str):
    """Post-hoc validation: check standard numbers cited in D5 against the known whitelist."""
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
        from pipeline.config import D5_STANDARD_REFERENCE
    except ImportError:
        return

    _VALID_STANDARDS = set()
    for info in D5_STANDARD_REFERENCE.values():
        for std_num, _scope in info["standards"]:
            _VALID_STANDARDS.add(std_num.upper().replace(" ", ""))

    _STANDARD_REF_PATTERN = re.compile(
        r"(?:DL/T|GB/T|GB|IEC|ISO|ASME|VDI|AGMA|IEEE|TSG|NB|HJ|JB|NAS)\s*[A-Z]?\s*\d+(?:[.-]\d+)*"
    )

    unknown_refs = []
    for row in rows:
        if d5_idx >= len(row):
            continue
        d5_val = row[d5_idx]
        if "置信：标准值" not in d5_val:
            continue
        for std_ref in _STANDARD_REF_PATTERN.findall(d5_val):
            normalized = std_ref.upper().replace(" ", "").split("-")[0].split(":")[0]
            if not any(normalized.startswith(v) or v.startswith(normalized) for v in _VALID_STANDARDS):
                unknown_refs.append(std_ref)

    if unknown_refs:
        fname = os.path.basename(filepath)
        unique_unknowns = list(set(unknown_refs))[:5]
        report.results.append(CheckResult(
            level="warning", check="D5未知标准号", file=filepath,
            message=f"{fname}: {len(unknown_refs)}个标准号不在白名单: {', '.join(unique_unknowns)}",
        ))


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

    crossfills = []
    for i, row in enumerate(rows):
        if d5_idx < len(row):
            d5_val = row[d5_idx]
            for kw in sensor_keywords:
                if kw in d5_val:
                    crossfills.append(f"第{i+3}行D5含传感器关键词'{kw}'（应填在D6）")
                    break

        if d6_idx < len(row):
            d6_val = row[d6_idx]
            if threshold_pattern.search(d6_val):
                crossfills.append(f"第{i+3}行D6含阈值表达式（应填在D5）")

    if crossfills:
        report.results.append(CheckResult(
            level="warning", check="D5/D6互填", file=filepath,
            message=f"{os.path.basename(filepath)}: 检出{len(crossfills)}处疑似互填：{'; '.join(crossfills[:5])}",
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

    for level, count in counts.items():
        ratio = count / total
        if ratio >= 0.8 and total >= 3:
            report.results.append(CheckResult(
                level="warning", check="D2严重度偏置", file=filepath,
                message=f"{os.path.basename(filepath)}: D2严重度分布异常——{ratio:.0%}({count}/{total})被标为'{level}'，疑似LLM偏置",
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


# ── 阶段校验 ──

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


def validate_stage3(report: ValidationReport, target: str, auto_fix: bool):
    """校验阶段3：部件拆解。"""
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
    """校验阶段4：故障知识。"""
    schema = SCHEMA[4]

    faults_dir = os.path.join(target, "faults")
    if os.path.isdir(faults_dir):
        for f in sorted(os.listdir(faults_dir)):
            if not f.endswith(".md"):
                continue
            fpath = os.path.join(faults_dir, f)
            check_dedup(report, fpath, auto_fix=auto_fix)

            expected = schema["headers"].get("fault")
            if expected:
                check_headers(report, fpath, expected)

            check_required_fields_fault(report, fpath)
            check_d5_confidence(report, fpath)
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

        # 阶段3文件
        if "components.md" in files:
            fpath = os.path.join(root, "components.md")
            check_dedup(report, fpath, auto_fix=auto_fix)
            check_headers(report, fpath, SCHEMA[3]["headers"]["components.md"])
            check_parent_refs(report, fpath)
            check_required_fields_comp(report, fpath)

        # 阶段4文件
        if os.path.isdir(os.path.join(root, "faults")):
            validate_stage4(report, root, auto_fix)


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
