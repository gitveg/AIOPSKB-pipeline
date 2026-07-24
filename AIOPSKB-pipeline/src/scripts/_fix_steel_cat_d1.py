# -*- coding: utf-8 -*-
"""钢铁故障类别白名单+D1枚举通用映射修复。
遍历 faults/*.md，将非白名单类别映射到白名单标签，非枚举D1映射到合法枚举。
基于 failure_categories.yaml 白名单 + D1七枚举(机械/电气/绝缘/热/化学/控制/环境)。"""
import os, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 类别非白名单值 → 白名单标签（基于failure_categories.yaml各分组categories）
CAT_FIXES = {
    '跑圈': '跑圈（走圈或蠕动）',
    '疲劳': '断裂',
    '胶合': '齿面胶合',
    '机械故障': '其他',
    '结构失效': '断裂',
    '老化/劣化': '老化',
    '绝缘异常': '绝缘老化',
    '振动异常': '异常振动',
    '咬死': '卡滞',
    '性能劣化': '性能退化',
    '泄漏、振动异常': '泄漏；异常振动',
    '泄漏、堵塞': '泄漏；堵塞',
    '物理损伤': '破裂',
    '弯曲变形': '变形',
    '烧损': '其他',
    '熔损': '其他',
    '绕组断路': '断路',
    '汽蚀': '气蚀',
    '空化': '气蚀',
    '破损老化': '老化',
    '破损': '破裂',
    '老化变形': '老化',
    '绝缘': '绝缘老化',
    '机械松动': '松动',
    '机械磨损': '磨损',
    '机械': '其他',
    '化学': '其他',
    '冲蚀': '磨损',
    '泵体泄漏': '泄漏',
    '---': '其他',
}
# D1非枚举值 → 合法枚举（机械/电气/绝缘/热/化学/控制/环境；多选用全角；）
D1_FIXES = {
    '流体': '机械',
    '机械、热': '机械；热',
    '热力': '热',
    '疲劳': '机械',
    '老化': '机械',
    '化学、机械': '化学；机械',
    '磁': '电气',
    '---': '机械',
}

root = sys.argv[1] if len(sys.argv) > 1 else 'src/data/steel/离心泵'
apply = '--apply' in sys.argv
mode = 'APPLY' if apply else 'DRY-RUN(未写回)'
cat_n = d1_n = files = 0
SEP_RE = re.compile(r':?-+:?')
for dirpath, _, fns in os.walk(root):
    if os.path.basename(dirpath) != 'faults':
        continue
    for fn in fns:
        if not fn.endswith('.md'):
            continue
        fp = os.path.join(dirpath, fn)
        with open(fp, encoding='utf-8') as f:
            lines = f.readlines()
        changed = False
        for i, line in enumerate(lines):
            s = line.strip()
            if not s.startswith('|'):
                continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if len(cells) < 4:
                continue
            if all(SEP_RE.fullmatch(c) for c in cells if c):
                continue
            if '故障名称' in line and '物理属性' in line:
                continue
            parts = line.split('|')
            cat, d1 = cells[1], cells[2]
            if cat in CAT_FIXES:
                old = parts[2]
                parts[2] = ' ' * (len(old)-len(old.lstrip())) + CAT_FIXES[cat] + ' ' * (len(old)-len(old.rstrip()))
                cat_n += 1; changed = True
            if d1 in D1_FIXES:
                old = parts[3]
                parts[3] = ' ' * (len(old)-len(old.lstrip())) + D1_FIXES[d1] + ' ' * (len(old)-len(old.rstrip()))
                d1_n += 1; changed = True
            if changed:
                lines[i] = '|'.join(parts)
        if changed and apply:
            with open(fp, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            files += 1
print(f'目标:{root} 模式:{mode} 类别修:{cat_n} D1修:{d1_n} 改动文件:{files}')
