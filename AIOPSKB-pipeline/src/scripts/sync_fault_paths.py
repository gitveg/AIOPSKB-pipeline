"""faults 路径同步（dry-run / 执行）

components.md 对齐后，同步物理目录 + faults 文件：
1. 改名：目录名含"总成"后缀但 components 已去 → 目录+faults文件 重命名（主轴总成→主轴）
2. 孤儿：目录存在但 components.md 已无（删掉的零件，如本体/过度细化）→ 删目录

用法:
    python scripts/sync_fault_paths.py          # dry-run
    python scripts/sync_fault_paths.py --apply
"""
import os, glob, sys, shutil
sys.path.insert(0, "scripts")
from validate_kb import parse_md_table

ROOT = "data/power/wind/风电机组"
APPLY = "--apply" in sys.argv

renames = []  # (ss_dir, old, new)
orphans = []  # (ss_dir, name)

for ss_dir in glob.glob(os.path.join(ROOT, "*", "*") + os.sep):
    comp_path = os.path.join(ss_dir, "components.md")
    if not os.path.exists(comp_path):
        continue
    headers, rows = parse_md_table(comp_path)
    if not headers:
        continue
    ci = pi = None
    for i, h in enumerate(headers):
        if h.strip() == "部件":
            ci = i
        elif h.strip() == "零件":
            pi = i
    if ci is None:
        continue
    expected = set()
    for row in rows:
        for idx in (ci, pi):
            if idx is not None and idx < len(row):
                v = row[idx].strip()
                if v and v != "—":
                    expected.add(v)
    for name in os.listdir(ss_dir):
        full = os.path.join(ss_dir, name)
        if not os.path.isdir(full):
            continue
        if name in expected:
            continue  # OK
        cand = name[:-2] if name.endswith("总成") else None
        if cand and cand in expected:
            renames.append((ss_dir, name, cand))
        else:
            orphans.append((ss_dir, name))

print(f"=== faults 路径同步 ===")
print(f"改名(目录+faults文件): {len(renames)}")
for ss, o, n in renames[:20]:
    print(f"  {o} → {n}")
print(f"\n孤儿(目录存在但components已删，将删目录): {len(orphans)}")
for ss, n in orphans[:20]:
    print(f"  {n}")

if APPLY:
    conflicts = []
    done = 0
    for ss, o, n in renames:
        old_dir = os.path.join(ss, o)
        new_dir = os.path.join(ss, n)
        if os.path.exists(new_dir):
            conflicts.append((ss, o, n))  # 目标已存在，冲突跳过
            continue
        old_faults = os.path.join(old_dir, "faults", o + ".md")
        new_faults = os.path.join(old_dir, "faults", n + ".md")
        if os.path.exists(old_faults):
            os.rename(old_faults, new_faults)
        os.rename(old_dir, new_dir)
        done += 1
    for ss, n in orphans:
        full = os.path.join(ss, n)
        if os.path.exists(full):
            shutil.rmtree(full)
    print(f"\n已应用: 改名{done} + 删孤儿{len(orphans)}")
    if conflicts:
        print(f"\n冲突(目标目录已存在，需手动合并): {len(conflicts)}")
        for ss, o, n in conflicts:
            print(f"  {o} → {n}（{n}/已存在）")
