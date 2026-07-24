# -*- coding: utf-8 -*-
"""钢铁库工况污染清洗：石化术语 → 钢铁/通用术语，目标计数=0。
- GB 30871(化学品特殊作业,石化专用): 删标准号,置信标准值→经验值
- API 610/682(石化工艺泵/密封) → GB/T 5656 / GB/T 5894(通用)
- GB/T 3215(石油石化离心泵) → GB/T 5656
- 工况词: 易燃易爆→高温重载, 有毒介质/物料→工艺介质, 腐蚀性介质→循环冷却水, 易挥发→(删)"""
import os, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DIRECT = {
    'API 610': 'GB/T 5656',
    'API 682': 'GB/T 5894',
    'GB/T 3215': 'GB/T 5656',
    '易燃易爆': '高温重载',
    '有毒物料': '工艺介质',
    '有毒介质': '工艺介质',
    '腐蚀性介质': '循环冷却水',
}
root = sys.argv[1] if len(sys.argv) > 1 else 'src/data/steel/离心泵'
apply = '--apply' in sys.argv
direct_n = gb_n = files = 0
for dirpath, _, fns in os.walk(root):
    for fn in fns:
        if not fn.endswith('.md'):
            continue
        fp = os.path.join(dirpath, fn)
        with open(fp, encoding='utf-8') as f:
            txt = f.read()
        orig = txt
        # 1. GB 30871 在置信标注里(标准值→经验值,删标准号)，两种格式
        txt = re.sub(r'（置信：标准值[^）]*GB ?30871[-\d]*[^）]*）', '（置信：经验值）', txt)
        txt = re.sub(r'（[^）]*GB ?30871[-\d]*[^）]*置信：标准值[^）]*）', '（置信：经验值）', txt)
        # 2. 删除残留 GB 30871（含年份），清理多余逗号/空格
        before = len(re.findall(r'GB ?30871', txt))
        txt = re.sub(r'[，,、\s]*GB ?30871[-\d]*(?=[，,、）\s])', '', txt)
        txt = re.sub(r'GB ?30871[-\d]*', '', txt)
        gb_n += before
        # 3. 易挥发（单独删除，注意上下文，仅2处）
        txt = txt.replace('、易挥发', '').replace('易挥发、', '').replace('易挥发', '')
        # 4. 直接替换
        for k, v in DIRECT.items():
            c = txt.count(k)
            if c:
                txt = txt.replace(k, v)
                direct_n += c
        # 5. 清理替换后的多余标点
        txt = re.sub(r'（\s*）', '', txt)
        txt = re.sub(r'[，,]\s*[）)]', '）', txt)
        txt = re.sub(r'[、]\s*[）)]', '）', txt)
        if txt != orig:
            files += 1
            if apply:
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(txt)
print(f'目标:{root} 模式:{"APPLY" if apply else "DRY-RUN"} 直接替换:{direct_n} GB30871处理:{gb_n} 易挥发删 改动文件:{files}')
