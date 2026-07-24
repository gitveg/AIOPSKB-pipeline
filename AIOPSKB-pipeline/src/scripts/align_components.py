"""components.md 对齐 - 步骤1-3（dry-run / 执行）

1. 去总成后缀（部件列 endswith"总成"→去掉）
2. 删本体零件行（零件列 endswith"本体" 且≠"—"）
3. 删过度细化零件行（零件列 ∈ 过度细化集）

步骤4（轴承归属B）单独脚本处理（方法迁移复杂）。

用法:
    python scripts/align_components.py          # dry-run
    python scripts/align_components.py --apply
"""
import os, glob, sys
sys.path.insert(0, "scripts")
from validate_kb import parse_md_table, write_md_table

ROOT = "data/power/wind/风电机组"
APPLY = "--apply" in sys.argv
# 过度细化：轴承内部不可独立拆换件
OVER_FINE = {"外圈", "内圈", "滚动体", "保持架", "圆锥滚子", "圆柱滚子", "钢球", "滚珠",
             "滚子", "滚动体隔离块", "回转支承内圈", "回转支承外圈", "回转支承滚动体"}

stats = {"去总成": 0, "删本体": 0, "删过度细化": 0}
samples = {"去总成": [], "删本体": [], "删过度细化": []}
changed_files = 0

for fp in glob.glob(os.path.join(ROOT, "**", "components.md"), recursive=True):
    if "_archive" in fp:
        continue
    headers, rows = parse_md_table(fp)
    if not headers or not rows:
        continue
    ci = pi = None
    for i, h in enumerate(headers):
        if h.strip() == "部件":
            ci = i
        elif h.strip() == "零件":
            pi = i
    if ci is None or pi is None:
        continue
    new_rows = []
    file_changed = False
    rel = fp.split("风电机组")[1][:40]
    for row in rows:
        part = row[pi].strip() if pi < len(row) else ""
        comp = row[ci].strip() if ci < len(row) else ""
        # 步骤2: 删本体零件行
        if part not in ("—", "") and part.endswith("本体"):
            stats["删本体"] += 1; file_changed = True
            if len(samples["删本体"]) < 6:
                samples["删本体"].append((rel, comp, part))
            continue
        # 步骤3: 删过度细化
        if part in OVER_FINE:
            stats["删过度细化"] += 1; file_changed = True
            if len(samples["删过度细化"]) < 6:
                samples["删过度细化"].append((rel, comp, part))
            continue
        # 步骤1: 去总成后缀
        if comp.endswith("总成"):
            row[ci] = comp[:-2]
            stats["去总成"] += 1; file_changed = True
            if len(samples["去总成"]) < 6:
                samples["去总成"].append((rel, comp, comp[:-2]))
        new_rows.append(row)
    if file_changed:
        changed_files += 1
        if APPLY:
            write_md_table(fp, headers, new_rows)

print(f"=== components 对齐 步骤1-3 ===")
for k in ("去总成", "删本体", "删过度细化"):
    print(f"\n{k}: {stats[k]} 处")
    for f, c, p in samples[k][:4]:
        extra = p if k == "去总成" else f"{c}|{p}"
        print(f"  [{f}] {extra if k!='去总成' else c+'→'+p}")
print(f"\n改动文件: {changed_files}")
print("已应用" if APPLY else "DRY-RUN（--apply执行）")
