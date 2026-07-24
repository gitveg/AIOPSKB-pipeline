"""故障跨层去重（dry-run / 执行）

部件级故障若指向具体零件 = 越界，删部件级行（保留零件级）。
判据：部件级故障名含该子系统某零件名（子串）→ 越界。
白名单：故障名含整体性词（振动/油质/接口/耦合/整体/综合/性能/温度/系统/功能/噪声/效率/功率/进水）不删。

用法:
    python scripts/dedup_fault_layers.py          # dry-run
    python scripts/dedup_fault_layers.py --apply
"""
import os, glob, sys
sys.path.insert(0, "scripts")
from validate_kb import parse_md_table, write_md_table

ROOT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "data/power/wind/风电机组"
APPLY = "--apply" in sys.argv
# 整体性失效词（部件级合理，不删）
OVERALL = ["振动", "温度", "油质", "油路", "润滑油", "接口", "耦合", "整体", "综合",
           "性能", "系统", "功能", "噪声", "效率", "功率", "负荷", "进水", "多点",
           "联动", "配合", "互联", "耦合退化"]
# 零件级失效模式词（若部件级故障名含这些 + 零件名 → 越界）
PART_FAIL = ["齿面", "断齿", "点蚀", "剥落", "胶合", "磨损", "裂纹", "断裂", "变形",
             "松动", "老化", "泄漏", "堵塞", "腐蚀", "烧蚀", "拉伤"]

deleted_total = 0
samples = []

_ss_dirs = [r for r, _, fs in os.walk(ROOT) if "components.md" in fs and "_archive" not in r]
for ss_dir in _ss_dirs:
    comp_path = os.path.join(ss_dir, "components.md")
    if not os.path.exists(comp_path):
        continue
    headers, rows = parse_md_table(comp_path)
    if "部件" not in headers:
        continue
    ci = headers.index("部件"); pi = headers.index("零件")
    # 收集零件名（零件列非—）+ 部件级部件名（部件列，该部件有零件=—行）
    part_names = set()
    comp_level = set()  # 部件级部件名（有 零件=— 行的）
    for row in rows:
        p = row[pi].strip() if pi < len(row) else ""
        c = row[ci].strip() if ci < len(row) else ""
        if p and p != "—":
            part_names.add(p)
        if p == "—" and c:
            comp_level.add(c)
    if not part_names or not comp_level:
        continue
    # 部件级 faults 文件
    for comp in comp_level:
        fault_fp = os.path.join(ss_dir, comp, "faults", comp + ".md")
        if not os.path.exists(fault_fp):
            continue
        fh, frows = parse_md_table(fault_fp)
        if not fh:
            continue
        new_rows = []
        moves = []  # (part_fault_path, row) 越界行移到零件级
        changed = False
        for row in frows:
            fname = row[0].strip() if row else ""
            is_overall = any(w in fname for w in OVERALL)
            # 越界：故障名含某零件名（子串），且非整体性，且不含部件名（避免部件名含零件名子串误判）
            crosses = [pn for pn in part_names if pn in fname and pn != comp and comp not in fname]
            if crosses and not is_overall:
                deleted_total += 1; changed = True
                pn = crosses[0]
                moves.append((os.path.join(ss_dir, pn, "faults", pn + ".md"), row))
                if len(samples) < 15:
                    samples.append((ss_dir.replace("\\", "/")[-32:], comp, fname, pn))
                continue  # 从部件级移除
            new_rows.append(row)
        if changed and APPLY:
            write_md_table(fault_fp, fh, new_rows)
            for part_fp, row in moves:
                os.makedirs(os.path.dirname(part_fp), exist_ok=True)
                if os.path.exists(part_fp):
                    _, er = parse_md_table(part_fp)
                    er.append(row)
                    write_md_table(part_fp, fh, er)
                else:
                    write_md_table(part_fp, fh, [row])

print(f"=== 故障跨层去重（部件级越界）===")
print(f"删除越界故障行: {deleted_total}")
for ss, comp, fname, pn in samples:
    print(f"  [{ss}] {comp}「{fname}」→ 指向零件「{pn}」")
print("已应用" if APPLY else "DRY-RUN（--apply执行）")
