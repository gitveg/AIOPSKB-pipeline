#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1/故障类别 列对调修复。

LLM 偶发把 D1(物理属性) 与 故障类别 两列内容写反：
  D1 填了失效机理(磨损/老化/破裂…)，故障类别填了物理属性(机械/化学/热…)。
精确检测这类对调行：D1 含非枚举值 且 故障类别 ∈ 物理属性七值 → 交换两列。
交换后 D1=物理属性(合规枚举)，故障类别=失效机理(白名单)。

用法：
  python src/scripts/_fix_d1_cat_swap.py src/data/power/thermal/boiler/煤粉锅炉        # DRY-RUN
  python src/scripts/_fix_d1_cat_swap.py src/data/power/thermal/boiler/煤粉锅炉 --apply
"""
import os, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else \
       'src/data/power/thermal/boiler/煤粉锅炉'
APPLY = '--apply' in sys.argv
D1_ENUM = {'机械', '电气', '绝缘', '热', '化学', '控制', '环境'}
SEP_RE = re.compile(r':?-+:?')

stats = {'交换': 0, '文件': 0}
details = []
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
            if len(cells) < 3:
                continue
            if '故障名称' in line and '物理属性' in line:
                continue
            if all(SEP_RE.fullmatch(c) for c in cells if c):
                continue
            cat = cells[1]   # 故障类别
            d1 = cells[2]    # D1 物理属性
            # D1 多值拆分（;或；）
            d1_vals = [v.strip() for v in re.split(r'[;；]', d1) if v.strip()]
            if not d1_vals:
                continue
            d1_all_enum = all(v in D1_ENUM for v in d1_vals)
            # 对调判据：D1 含非枚举值 且 故障类别 ∈ 物理属性七值
            if (not d1_all_enum) and cat in D1_ENUM:
                # 交换 cells[1] 与 cells[2]
                old_cat_part = parts[2]   # 故障类别原始(含空格)
                old_d1_part = parts[3]    # D1原始
                parts[2], parts[3] = parts[3], parts[2]
                lines[i] = '|'.join(parts)
                stats['交换'] += 1
                details.append(f"  {f} 第{i+1}行: D1'{d1}'↔类别'{cat}'")
                changed = True
        if changed:
            stats['文件'] += 1
            if APPLY:
                open(fp, 'w', encoding='utf-8').writelines(lines)

print(f"目标: {BASE}  模式: {'APPLY' if APPLY else 'DRY-RUN'}")
print(f"交换:{stats['交换']} 文件:{stats['文件']}")
for d in details[:12]:
    print(d)
