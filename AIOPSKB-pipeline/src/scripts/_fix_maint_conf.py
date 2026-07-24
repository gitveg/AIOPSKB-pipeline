#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D11-15 检维修置信标注治理。

对 fault 文件的 D11-D15（cells[12..16]）：
  - 已含"置信：" → 跳过（合规）
  - 含（经验值/标准值/待核实）但无"置信：" → 在括号内补"置信："前缀
  - 完全无标注 → 末尾加（置信：经验值）；内容含标准号则（置信：标准值）

用法：
  python src/scripts/_fix_maint_conf.py src/data/power/thermal/boiler/煤粉锅炉        # DRY-RUN
  python src/scripts/_fix_maint_conf.py src/data/power/thermal/boiler/煤粉锅炉 --apply
"""
import os, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else \
       'src/data/power/thermal/boiler/煤粉锅炉'
APPLY = '--apply' in sys.argv
STD_PAT = re.compile(r'(GB/T|DL/T|JB/T|NB/T|IEC|ISO|IEEE|TSG|GB|HJ)\s*\d')
SEP_RE = re.compile(r':?-+:?')
# 匹配 （经验值）/（标准值）/（待核实），保留全角/半角括号
TAG_RE = re.compile(r'([（(])(经验值|标准值|待核实)([)）])')

stats = {'补前缀': 0, '新增': 0, '跳过合规': 0, '文件': 0}
for root, dirs, files in os.walk(BASE):
    if '_archive' in root.split(os.sep):
        continue
    if os.path.basename(root) != 'faults':
        continue
    for f in sorted(files):
        if not f.endswith('.md'):
            continue
        fp = os.path.join(root, f)
        lines = open(fp, encoding='utf-8').readlines()
        changed = False
        for i, line in enumerate(lines):
            s = line.strip()
            if not s.startswith('|'):
                continue
            parts = line.split('|')
            cells = [p.strip() for p in parts[1:-1]]
            if len(cells) < 17:
                continue
            if '故障名称' in line and '物理属性' in line:
                continue
            if all(SEP_RE.fullmatch(c) for c in cells if c):
                continue
            row_changed = False
            for j in range(12, 17):  # D11-D15
                if j >= len(cells):
                    break
                v = cells[j]
                if v in ('', '—', '-'):
                    continue
                if '置信：' in v or '置信:' in v:
                    stats['跳过合规'] += 1
                    continue
                if TAG_RE.search(v):
                    newv = TAG_RE.sub(r'\1置信：\2\3', v)
                    stats['补前缀'] += 1
                    row_changed = True
                else:
                    tag = '标准值' if STD_PAT.search(v) else '经验值'
                    newv = v.rstrip('。；;.') + '（置信：' + tag + '）'
                    stats['新增'] += 1
                    row_changed = True
                old = parts[j + 1]
                lead = len(old) - len(old.lstrip())
                trail = len(old) - len(old.rstrip())
                parts[j + 1] = ' ' * lead + newv + ' ' * trail
                cells[j] = newv
            if row_changed:
                lines[i] = '|'.join(parts)
                changed = True
        if changed:
            stats['文件'] += 1
            if APPLY:
                open(fp, 'w', encoding='utf-8').writelines(lines)

print(f"目标: {BASE}")
print(f"模式: {'APPLY(已写回)' if APPLY else 'DRY-RUN(未写回)'}")
print(f"补前缀:{stats['补前缀']} 新增:{stats['新增']} 跳过合规:{stats['跳过合规']} 改动文件:{stats['文件']}")
