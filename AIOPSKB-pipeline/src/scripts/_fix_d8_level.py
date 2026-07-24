#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D8 级别启发式标注治理。

对 fault 文件的 D8(检修方法，第10列 cells[9])，若无 [规程级]/[经验级] 标注：
  - 内容含标准号(GB/T|DL/T|JB/T|NB/T|IEC|ISO|IEEE|TSG|GB|HJ + 数字) → 开头加 [规程级]
  - 否则 → 开头加 [经验级]（符合"无标准引用=经验级"标注规则）

用法：
  python src/scripts/_fix_d8_level.py src/data/power/thermal/boiler/煤粉锅炉        # DRY-RUN
  python src/scripts/_fix_d8_level.py src/data/power/thermal/boiler/煤粉锅炉 --apply
"""
import os, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else \
       'src/data/power/thermal/boiler/煤粉锅炉'
APPLY = '--apply' in sys.argv
STD_PAT = re.compile(r'(GB/T|DL/T|JB/T|NB/T|IEC|ISO|IEEE|TSG|GB|HJ|SH/T|HG/T|SY/T|API|AQ)\s*\d')
SEP_RE = re.compile(r':?-+:?')

stats = {'规程级': 0, '经验级': 0, '已标注跳过': 0, '文件改动': 0}
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
            if len(cells) < 10:
                continue
            if '故障名称' in line and '物理属性' in line:
                continue  # 表头
            if all(SEP_RE.fullmatch(c) for c in cells if c):
                continue  # 分隔行
            d8 = cells[9]
            if '[规程级]' in d8 or '[经验级]' in d8:
                stats['已标注跳过'] += 1
                continue
            tag = '[规程级]' if STD_PAT.search(d8) else '[经验级]'
            stats['规程级' if tag == '[规程级]' else '经验级'] += 1
            old = parts[10]
            lead = len(old) - len(old.lstrip())
            trail = len(old) - len(old.rstrip())
            parts[10] = ' ' * lead + tag + old.strip() + ' ' * trail
            lines[i] = '|'.join(parts)
            changed = True
        if changed:
            stats['文件改动'] += 1
            if APPLY:
                open(fp, 'w', encoding='utf-8').writelines(lines)

print(f"目标: {BASE}")
print(f"模式: {'APPLY(已写回)' if APPLY else 'DRY-RUN(未写回)'}")
print(f"将/已标注 → 规程级: {stats['规程级']}  经验级: {stats['经验级']}  已标注跳过: {stats['已标注跳过']}  改动文件: {stats['文件改动']}")
