"""临时：扫描 DFIG 故障层 D1 物理属性非枚举的真实样例。跑完即删。"""
import os
import re
import sys

src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(src_dir)
sys.stdout.reconfigure(encoding="utf-8")

VALID = {"机械", "电气", "绝缘", "热", "化学", "控制", "环境"}
base = r"data\power\wind\风电机组\双馈异步风电机组（DFIG）"

hits = []
for root, dirs, files in os.walk(base):
    if os.path.basename(root) != "faults":
        continue
    for f in sorted(files):
        if not f.endswith(".md"):
            continue
        p = os.path.join(root, f)
        for i, line in enumerate(open(p, encoding="utf-8"), 1):
            line = line.strip()
            if not line.startswith("|") or re.match(r"^\|[\s\-:|]+\|$", line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 3 or cells[1] == "故障类别":
                continue
            name, d1 = cells[0], cells[2]
            d1vals = [v.strip() for v in re.split(r"[;；]", d1)]
            bad = [v for v in d1vals if v not in VALID and v]
            if bad:
                rel = os.path.relpath(p, base).replace("\\", "/")
                hits.append((rel, i, name, d1, bad))

for rel, i, name, d1, bad in hits[:15]:
    print(f"{rel}:{i}  {name}")
    print(f"   D1 = '{d1}'   非枚举项 = {bad}")

# 统计非枚举值的频次
from collections import Counter
freq = Counter()
for _, _, _, _, bad in hits:
    for v in bad:
        freq[v] += 1
print(f"\n共 {len(hits)} 处 D1 非枚举。非枚举值频次 Top：")
for v, n in freq.most_common(15):
    print(f"   {n:>3}  {v}")
