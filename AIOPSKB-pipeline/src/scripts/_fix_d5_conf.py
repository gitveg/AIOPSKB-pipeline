#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D5 置信启发式标注。

对 fault 文件 D5(故障特征参数, cells[6])，按 ；/; 拆分参数，每个无"置信："的参数：
  - 含标准号 → 加"置信：标准值"，否则 → "置信：经验值"
  - 参数以全角/半角右括号结尾 → 在右括号前插入"，置信：X"
  - 参数无括号 → 末尾追加"（置信：X）"
参数间统一用全角；重组。

用法：
  python src/scripts/_fix_d5_conf.py src/data/power/thermal/boiler/煤粉锅炉        # DRY-RUN
  python src/scripts/_fix_d5_conf.py src/data/power/thermal/boiler/煤粉锅炉 --apply
"""
import os, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else \
       'src/data/power/thermal/boiler/煤粉锅炉'
APPLY = '--apply' in sys.argv
STD_PAT = re.compile(r'(GB/T|DL/T|JB/T|NB/T|IEC|ISO|IEEE|TSG|GB|HJ)\s*\d')
SEP_RE = re.compile(r':?-+:?$')

stats = {'参数修': 0, '文件': 0}


def fix_param(p):
    p = p.strip()
    if not p or p in ('---', '-', '—'):
        return p, False
    if '置信：' in p or '置信:' in p:
        return p, False
    tag = '标准值' if STD_PAT.search(p) else '经验值'
    if p.endswith('）'):
        return p[:-1] + '，置信：' + tag + '）', True
    if p.endswith(')'):
        return p[:-1] + ',置信：' + tag + ')', True
    return p + '（置信：' + tag + '）', True


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
            if len(cells) < 7 or '故障名称' in line:
                continue
            if all(SEP_RE.match(x) for x in cells if x):
                continue
            d5 = cells[6]
            if not d5 or d5 in ('---', '-', '—'):
                continue
            params = [p for p in re.split(r'[；;]', d5)]
            new_params = []
            row_changed = False
            for p in params:
                np, did = fix_param(p)
                if did:
                    stats['参数修'] += 1
                    row_changed = True
                new_params.append(np)
            if row_changed:
                new_d5 = '；'.join(new_params)
                old = parts[7]
                lead = len(old) - len(old.lstrip())
                trail = len(old) - len(old.rstrip())
                parts[7] = ' ' * lead + new_d5 + ' ' * trail
                lines[i] = '|'.join(parts)
                changed = True
        if changed:
            stats['文件'] += 1
            if APPLY:
                open(fp, 'w', encoding='utf-8').writelines(lines)

print(f"目标:{BASE} 模式:{'APPLY' if APPLY else 'DRY-RUN'}")
print(f"参数修:{stats['参数修']} 文件:{stats['文件']}")
