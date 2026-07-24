"""归档石化旧 6 子行业分类 (数据质量差, 石化改为不分子行业直接枚举设备)"""
import os, shutil, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

base = 'C:/Users/900009684/Desktop/AIOpsKB/AIOPSKB-pipeline/src/data/petrochemical'
arch = os.path.join(base, '_archive', 'petrochemical_subindustries_20260630')
os.makedirs(arch, exist_ok=True)

targets = ['石油炼制', '化肥', '合成树脂', '合成纤维', '合成橡胶', '基础有机化工原料', 'index.md']
moved, missing = [], []
for t in targets:
    src = os.path.join(base, t)
    if os.path.exists(src):
        shutil.move(src, os.path.join(arch, t))
        moved.append(t)
    else:
        missing.append(t)

print(f'已归档 {len(moved)} 项 -> _archive/petrochemical_subindustries_20260630/')
for m in moved:
    print(f'  ✓ {m}')
if missing:
    print(f'未找到(跳过): {missing}')

# 留 README 说明
readme = os.path.join(base, 'README.md')
with open(readme, 'w', encoding='utf-8') as f:
    f.write(
        "# 石化行业知识库（待重建）\n\n"
        "> **状态**：旧分类已归档，待 pipeline 重新构建\n\n"
        "## 历史\n"
        "原按 6 子行业组织（石油炼制/化肥/合成树脂/合成纤维/合成橡胶/基础有机化工原料），"
        "经评估数据质量差且石化**不需要分子行业**，已于 2026-06-30 全部归档至\n"
        "`_archive/petrochemical_subindustries_20260630/`。\n\n"
        "## 重建方式\n"
        "石化直接从**设备枚举**开始（不分子行业）。设备生成优先级参考：\n"
        "`src/docs/数据辅助知识库构建/石化数据分析与构建起点.md`\n"
    )
print('\n已创建说明 -> README.md')

print('\n归档后 petrochemical/ 结构:')
for item in sorted(os.listdir(base)):
    full = os.path.join(base, item)
    print(f'  {"[目录]" if os.path.isdir(full) else "[文件]"} {item}')
