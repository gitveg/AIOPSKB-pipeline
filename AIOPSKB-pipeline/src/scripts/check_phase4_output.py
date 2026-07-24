# -*- coding: utf-8 -*-
"""校验凝汽器 Phase 4 故障输出：列数、故障类别合规率"""
import sys, io, os, re, yaml
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('failure_categories.yaml', encoding='utf-8') as f:
    data = yaml.safe_load(f)
whitelist = set()
for g in data['groups'].values():
    whitelist.update(g['categories'])

base = 'src/data/power/thermal/condenser'
files = []
for root, dirs, fnames in os.walk(base):
    parts = root.replace('\\', '/').split('/')
    if '_archive' in parts:
        continue
    # 跳过旧根 faults/ (condenser/faults 直接子级)
    if parts[-1] == 'faults' and len(parts) >= 2 and parts[-2] == 'condenser':
        continue
    if parts[-1] != 'faults':
        continue
    for fn in fnames:
        if fn.endswith('.md'):
            files.append(os.path.join(root, fn))

print(f'=== 新格式故障文件校验 ({len(files)} 个) ===\n')
col_stats = {}
cat_violations = []
total_rows = 0
for fp in sorted(files):
    with open(fp, encoding='utf-8') as f:
        content = f.read()
    for l in content.split('\n'):
        s = l.strip()
        if not s.startswith('|'):
            continue
        cells = [c.strip() for c in l.split('|')[1:-1]]
        if not cells:
            continue
        # 跳过分隔行：所有单元格都是 ---/:--/-:/等分隔符样式
        if all(re.fullmatch(r':?-+:?', c) for c in cells if c):
            continue
        # 跳过表头
        if '故障名称' in l and '物理属性' in l:
            continue
        total_rows += 1
        ncols = len(cells)
        col_stats[ncols] = col_stats.get(ncols, 0) + 1
        if ncols >= 3:  # 故障类别在迁移后位于第2列(cells[1])
            for c in re.split(r'[;；、]', cells[1]):
                c = c.strip()
                if c and c not in whitelist:
                    cat_violations.append((os.path.basename(fp), c))

print(f'总故障条目数: {total_rows}')
print(f'列数分布: {dict(sorted(col_stats.items()))}')
n12 = col_stats.get(12, 0)
print(f'12列条目: {n12}/{total_rows} ({100*n12/max(total_rows,1):.1f}%)')
ok = total_rows - len(cat_violations)
print(f'\n故障类别合规: {ok}/{total_rows} 条在白名单内')
if cat_violations:
    print(f'  违规({len(cat_violations)}条):')
    for fn, c in cat_violations[:30]:
        print(f'    {fn}: "{c}"')
else:
    print('  ✅ 零违规，全部故障类别来自白名单')

# 统计故障类别分布
print('\n=== 故障类别使用分布 Top 20 ===')
from collections import Counter
all_cats = Counter()
for fp in files:
    with open(fp, encoding='utf-8') as f:
        content = f.read()
    for l in content.split('\n'):
        s = l.strip()
        if not s.startswith('|'):
            continue
        cells = [c.strip() for c in l.split('|')[1:-1]]
        if not cells or all(re.fullmatch(r':?-+:?', c) for c in cells if c):
            continue
        if '故障名称' in l:
            continue
        if len(cells) >= 3 and cells[1].strip():  # 故障类别（迁移后位于第2列）
            for c in re.split(r'[;；、]', cells[1]):
                c = c.strip()
                if c:
                    all_cats[c] += 1
for cat, cnt in all_cats.most_common(20):
    print(f'  {cat}: {cnt}')
print(f'  (共 {len(all_cats)} 种故障类别)')
