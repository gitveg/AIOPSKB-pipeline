# -*- coding: utf-8 -*-
"""修复故障表列数错位：16列(漏故障类别,D1/D2左移)补类别+D2归位；19列(D15含|t|绝对值符号)删|。"""
import os, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def infer_cat(name):
    for kw, cat in [('松动', '松动'), ('变形', '变形'), ('弯曲', '变形'),
                    ('腐蚀', '腐蚀'), ('磨损', '磨损'), ('泄漏', '泄漏'),
                    ('断裂', '断裂'), ('破裂', '破裂'), ('开裂', '裂纹'),
                    ('短路', '绕组短路'), ('断路', '断路'), ('漂移', '信号漂移'),
                    ('退化', '性能退化'), ('老化', '老化'), ('堵塞', '堵塞'),
                    ('失效', '失效'), ('卡涩', '卡滞'), ('卡死', '卡滞'),
                    ('脱落', '脱落'), ('积灰', '积灰'), ('结垢', '结垢')]:
        if kw in name:
            return cat
    return '其他'

root = sys.argv[1] if len(sys.argv) > 1 else 'src/data/steel/离心泵'
apply = '--apply' in sys.argv
fix16 = fix19 = files = 0
SEP_RE = re.compile(r':?-+:?')
for dp, _, fns in os.walk(root):
    if os.path.basename(dp) != 'faults':
        continue
    for fn in fns:
        if not fn.endswith('.md'):
            continue
        fp = os.path.join(dp, fn)
        with open(fp, encoding='utf-8') as f:
            lines = f.readlines()
        changed = False
        for i, line in enumerate(lines):
            s = line.strip()
            if not s.startswith('|') or '故障名称' in line:
                continue
            parts = line.split('|')
            cells = parts[1:-1]
            if len(cells) < 3:
                continue
            if all(SEP_RE.fullmatch(c.strip()) for c in cells if c.strip()):
                continue
            n = len(cells)
            if n == 16:
                # 漏类别: [故障名称, D2值, D1值, D3值...]; 修为[故障名称, 类别, D1值, D2值, D3值...]
                name = cells[0].strip().strip('*')
                cat = infer_cat(name)
                new_cells = [cells[0], ' ' + cat + ' ', cells[2], cells[1]] + cells[3:]
                parts[1:-1] = new_cells
                lines[i] = '|'.join(parts)
                fix16 += 1; changed = True
            elif n >= 18:
                # 多列: 多为 D15 含 |t| 等数学绝对值符号，删除 |（保留字母）
                new_line = re.sub(r'\|([a-zA-Z])\|', r'\1', line)
                new_line = re.sub(r'\\?\|t\\?\|', 't', new_line)
                if new_line != line:
                    lines[i] = new_line; fix19 += 1; changed = True
        if changed and apply:
            with open(fp, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            files += 1
print(f'目标:{root} 模式:{"APPLY" if apply else "DRY-RUN"} 16列补类别:{fix16} 19列删|:{fix19} 改动文件:{files}')
