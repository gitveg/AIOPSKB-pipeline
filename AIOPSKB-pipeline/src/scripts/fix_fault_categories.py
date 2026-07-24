# -*- coding: utf-8 -*-
"""精确修正凝汽器 Phase 4 故障类别违规：仅替换表格第2列(故障类别)的值，不动描述文本。（改造5修正后故障类别位于第2列）"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 文件 -> 该文件故障类别列需要的替换
FIXES = {
    'src/data/power/thermal/condenser/冷却水系统/防腐蚀衬里/faults/防腐蚀衬里.md':
        {'化学侵蚀': '腐蚀'},
    'src/data/power/thermal/condenser/真空维持系统/抽气管道/faults/抽气管道.md':
        {'堵塞（水封）': '堵塞'},
    'src/data/power/thermal/condenser/真空维持系统/滤网组件/faults/滤网组件.md':
        {'结构失效': '裂纹'},
}

SEP_RE = re.compile(r':?-+:?')

for fpath, repls in FIXES.items():
    with open(fpath, encoding='utf-8') as f:
        lines = f.readlines()
    changed = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) < 3:
            continue
        # 跳过分隔行/表头
        if all(SEP_RE.fullmatch(c) for c in cells if c):
            continue
        if '故障名称' in line and '物理属性' in line:
            continue
        cat = cells[1]  # 故障类别（改造5修正后位于第2列）
        if cat in repls:
            new_cat = repls[cat]
            # 重建该单元格：保持 | 分隔，替换第2列(故障类别)
            parts = line.split('|')
            # parts[0]='' parts[1]=故障名称 parts[2]=故障类别 parts[3]=D1 parts[-1]=换行
            old_cell = parts[2]
            # 保留原前后空白
            lead = len(old_cell) - len(old_cell.lstrip())
            trail = len(old_cell) - len(old_cell.rstrip())
            parts[2] = ' ' * lead + new_cat + ' ' * trail
            lines[i] = '|'.join(parts)
            changed += 1
            print(f'  [{fpath.split("/")[-1]}] 第{i+1}行: {cat} -> {new_cat}')
    with open(fpath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f'  共修正 {changed} 处\n')
print('完成')
