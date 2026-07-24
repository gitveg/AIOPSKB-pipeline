#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1/故障类别 综合修复（煤粉锅炉 pilot）。

修正 LLM 零散错误：D2等级误填、物理属性误填故障类别、D1多值格式(顿号/无分隔)、
故障类别复合词/自创词。FIXES 字典精确映射，多值(；分隔)逐子值替换。

用法：
  python src/scripts/_fix_d1_cat_thermal.py src/data/power/thermal/boiler/煤粉锅炉        # DRY-RUN
  python src/scripts/_fix_d1_cat_thermal.py src/data/power/thermal/boiler/煤粉锅炉 --apply
"""
import os, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else \
       'src/data/power/thermal/boiler/煤粉锅炉'
APPLY = '--apply' in sys.argv
SEP_RE = re.compile(r':?-+:?$')


def _set_cell(parts, idx, val):
    """重建单元格，保留原前后空白。"""
    old = parts[idx]
    lead = len(old) - len(old.lstrip())
    trail = len(old) - len(old.rstrip())
    parts[idx] = ' ' * lead + val + ' ' * trail


# D1 物理属性修复（非枚举 → 枚举，或格式修正）
FIXES_D1 = {
    '机械、热': '机械；热', '化学、热': '化学；热',
    '机械热': '机械；热', '机械环境': '机械；环境',
    '流体': '机械',      # 管路介质误填→机械失效
    '光学': '热',        # 火焰光学感知→热
    '老化': '热',        # 老化多热致
    '堵塞': '机械',
    '严重': '机械', '一般': '机械', '危急': '机械',  # D2等级误填D1
    '机械、化学': '机械；化学', '机械、环境': '机械；环境', '电气、化学': '电气；化学',
    '泄漏': '机械', '腐蚀': '化学', '松动': '机械', '断裂': '机械', '声学': '环境', '热化学': '热；化学',
    '化学、机械': '化学；机械', '机械化学': '机械；化学', '电气、热': '电气；热', '环境、热': '环境；热', '机械、控制': '机械；控制', '电气、控制': '电气；控制',
    '机械控制': '机械；控制', '控制机械': '控制；机械', '热、电气': '热；电气', '热电气': '热；电气',
    '热力': '热', '变形': '机械', '共振': '机械', '疲劳': '机械', '积灰': '环境',
    '结垢、堵塞': '机械', '性能退化': '机械',
    '---': '机械',
}

# 故障类别修复（非白名单 → 白名单）
FIXES_CAT = {
    '严重': '磨损', '危急': '断裂', '一般': '磨损',    # D2等级误填
    '热': '老化', '化学': '腐蚀', '机械': '磨损', '环境': '积灰',  # 物理属性误填
    '老化/劣化': '老化',
    '松动脱落': '脱落', '磨损泄漏': '磨损', '断裂泄漏': '断裂',
    '堵塞与泄漏': '堵塞', '老化与积灰': '老化',
    '异常': '性能退化', '退化故障': '性能退化', '污染': '混入杂质',
    '结垢积灰': '结垢', '腐蚀磨损': '腐蚀', '跑圈': '跑圈（走圈或蠕动）',
    '机械故障': '磨损', '磨损故障': '磨损', '电气故障': '失效', '工质故障': '变质',
    '控制': '失效', '填塞物': '堵塞', '结垢堵塞': '结垢', '磨损破裂': '磨损', '老化退化': '老化', '咬堵积灰': '积灰',
    '金属部件': '磨损', '塑料变形': '变形', '控制故障': '失效', '积垢': '结垢', '断裂裂纹': '断裂',
    '腐蚀泄漏': '腐蚀', '老化泄漏': '老化', '老化变形': '老化', '变形堵塞': '变形', '破损': '破裂', '破损故障': '破裂', '物理损伤': '磨损', '泄漏故障': '泄漏',
    '老化破裂': '老化', '烧损': '磨损', '破裂、泄漏': '破裂', '老化、性能退化': '老化', '机械、化学': '磨损',
    '化学、电气': '腐蚀', '振动': '异常振动', '异常振动、温度异常': '异常振动', '疲劳': '断裂', '裂纹、断裂': '裂纹', '断裂、松动': '断裂', '粘着磨损': '磨损', '击穿': '电腐蚀', '劣化': '老化',
    '电气': '失效', '通信故障': '失效', '腐蚀破裂': '腐蚀',
    '---': '堵塞',
}

stats = {'d1修': 0, 'cat修': 0, '文件': 0}
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
            if len(cells) < 3 or '故障名称' in line:
                continue
            if all(SEP_RE.match(x) for x in cells if x):
                continue
            row_changed = False
            # D1（cells[2], parts[3]）：多值逐个修
            d1 = cells[2]
            d1vals = [v.strip() for v in re.split(r'[;；]', d1)]
            new_d1vals = [FIXES_D1.get(v, v) for v in d1vals]
            if new_d1vals != d1vals:
                new_d1 = '；'.join(new_d1vals)
                stats['d1修'] += 1
                _set_cell(parts, 3, new_d1)
                cells[2] = new_d1
                row_changed = True
            # 故障类别（cells[1], parts[2]）：多值逐个修
            cat = cells[1]
            if cat not in ('', '—', '-'):
                catvals = [v.strip() for v in re.split(r'[;；]', cat)]
                new_catvals = [FIXES_CAT.get(v, v) for v in catvals]
                if new_catvals != catvals:
                    new_cat = '；'.join(new_catvals)
                    stats['cat修'] += 1
                    _set_cell(parts, 2, new_cat)
                    cells[1] = new_cat
                    row_changed = True
            if row_changed:
                lines[i] = '|'.join(parts)
                changed = True
        if changed:
            stats['文件'] += 1
            if APPLY:
                open(fp, 'w', encoding='utf-8').writelines(lines)

print(f"目标:{BASE} 模式:{'APPLY' if APPLY else 'DRY-RUN'}")
print(f"D1修:{stats['d1修']} 故障类别修:{stats['cat修']} 文件:{stats['文件']}")
