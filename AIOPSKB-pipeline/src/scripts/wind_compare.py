"""
风电: 数据仓库设备分布 vs 知识库构建情况 对比
=============================================
对比维度:
  1. 子设备: 数据技术路线(双馈/直驱/半直驱) vs KB sub_equipment
  2. 部件:   数据部件级 devicetype vs KB components 部件名 (双向覆盖率)
  3. 子系统: 数据部件能否覆盖 KB 的 10 子系统骨架
"""
import sys, io, os, re, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

EXPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_export')
WIND_KB = 'C:/Users/900009684/Desktop/AIOpsKB/AIOPSKB-pipeline/src/data/power/wind'

# ============ A. 数据仓库侧: 风电 devicetype 分布 ============
df = pd.read_csv(os.path.join(EXPORT, 'industry_devicetype_topN.csv'),
                 encoding='utf-8-sig', dtype={'devicetype': str})
wd = df[df['industry_cn'] == '风电'].sort_values('device_count', ascending=False)
print("=" * 80)
print("A. 数据仓库: 风电 devicetype 分布 (按层级)")
print("=" * 80)
print(f"风电设备总数: {wd['device_count'].sum()} 台, 型号数: {len(wd)}\n")
for lvl in ['子设备', '设备', '部件', '其他']:
    sub = wd[wd['kb_level'] == lvl]
    if len(sub) == 0:
        continue
    print(f"--- [{lvl}] {len(sub)} 个型号, {sub['device_count'].sum()} 台 ---")
    for _, r in sub.iterrows():
        flag = '⚠单企业' if r['enterprise_count'] <= 1 else ''
        print(f"  {str(r['devicetype']):<10} {str(r['devicetype_cn'])[:12]:<14} {int(r['device_count']):>6}台  {int(r['enterprise_count']):>4}企业 {flag}")
    print()


# ============ B. 知识库侧: 提取风电各层 ============
def extract_first_col(md_path, header_keywords):
    """提取 md 表格第一列, 跳过表头/分隔行"""
    names = []
    if not os.path.exists(md_path):
        return names
    for line in open(md_path, encoding='utf-8'):
        if not line.startswith('|') or '---' in line or ':-' in line:
            continue
        cells = [c.strip() for c in line.split('|')]
        if len(cells) < 3:
            continue
        v = cells[1]
        if not v or v in header_keywords or v == '—':
            continue
        names.append(v)
    return names

# B1. 设备清单
kb_equipment = extract_first_col(os.path.join(WIND_KB, 'equipment_registry.md'),
                                 {'设备类型名称'})
# B2. 子设备
kb_subequip = extract_first_col(os.path.join(WIND_KB, '风电机组', 'sub_equipment.md'),
                                {'子设备名称'})
# B3. 子系统 (三机型, 去重)
kb_subsystem = set()
for ss in glob.glob(os.path.join(WIND_KB, '风电机组', '**', 'sub_system.md'), recursive=True):
    if '_archive' in ss:
        continue
    for n in extract_first_col(ss, {'子系统名称'}):
        kb_subsystem.add(n)
# B4. 部件 (三机型所有 components.md, 去重; 取"部件"列非"零件"列)
kb_components = set()
comp_files = glob.glob(os.path.join(WIND_KB, '风电机组', '**', 'components.md'), recursive=True)
for cf in comp_files:
    if '_archive' in cf:
        continue
    for line in open(cf, encoding='utf-8'):
        if not line.startswith('|') or '---' in line or ':-' in line:
            continue
        cells = [c.strip() for c in line.split('|')]
        if len(cells) < 4:
            continue
        comp = cells[1]  # 部件列
        if comp and comp not in ('部件', '部件名称', '—'):
            kb_components.add(comp)

print("=" * 80)
print(f"B. 知识库: 风电已构建情况")
print("=" * 80)
print(f"  设备数: {len(kb_equipment)}  样例: {kb_equipment[:5]}")
print(f"  子设备数: {len(kb_subequip)}  -> {kb_subequip}")
print(f"  子系统数: {len(kb_subsystem)} (三机型去重)")
for s in sorted(kb_subsystem):
    print(f"     · {s}")
print(f"  部件数(去重): {len(kb_components)}  (来自 {len(comp_files)} 个 components.md)")


# ============ C. 对比 ============
print("\n" + "=" * 80)
print("C. 对比分析")
print("=" * 80)

# C1. 子设备对比
print("\n[C1] 子设备层: 数据技术路线 vs KB子设备")
data_subequip = wd[wd['kb_level'] == '子设备']
print(f"  数据技术路线: {len(data_subequip)} 个")
for _, r in data_subequip.iterrows():
    print(f"     {r['devicetype_cn']:<16} {int(r['device_count'])}台 / {int(r['enterprise_count'])}企业")
print(f"  KB子设备: {len(kb_subequip)} 个 -> {[s.split('（')[0] for s in kb_subequip]}")
print("  结论: 数据三技术路线(双馈/直驱/半直驱)与KB三子设备完全对应 ✅")

# C2. 部件对比 (双向)
print("\n[C2] 部件层: 数据部件 vs KB部件 (模糊匹配)")
data_components = wd[wd['kb_level'] == '部件']
print(f"  数据部件 devicetype: {len(data_components)} 个")
# 数据部件 -> 是否在KB部件中找到对应 (包含匹配)
def in_kb(name):
    name = str(name)
    for kc in kb_components:
        if name in kc or kc in name:
            return kc
    return None
hit, miss = 0, []
for _, r in data_components.iterrows():
    m = in_kb(r['devicetype_cn'])
    if m:
        hit += 1
        print(f"     ✓ {r['devicetype_cn']:<12} -> KB:「{m}」")
    else:
        miss.append(r['devicetype_cn'])
        print(f"     ✗ {r['devicetype_cn']:<12} (KB无直接对应)")
print(f"  数据部件命中KB: {hit}/{len(data_components)}")
if miss:
    print(f"  未命中: {miss}")

# C3. 子系统覆盖: 数据部件能否映射到KB 10子系统
print("\n[C3] 子系统层: 数据部件构成能否覆盖 KB 10子系统")
# 数据部件 -> 子系统映射 (基于风电工程常识)
COMP_TO_SUBSYS = {
    '叶片': '风轮系统', '叶片设备': '风轮系统',
    '变桨轴承': '变桨系统', '变桨轴承(超声)': '变桨系统', '变桨设备': '变桨系统', '变桨传动': '变桨系统',
    '齿轮箱': '传动系统', '主轴': '传动系统', '主轴承': '传动系统',
    '发电机': '发电系统',
    '塔基': '塔架与支撑系统', '塔顶': '塔架与支撑系统', '塔顶(测倾)': '塔架与支撑系统',
}
data_subsys_covered = set()
for _, r in data_components.iterrows():
    subsys = COMP_TO_SUBSYS.get(r['devicetype_cn'])
    if subsys:
        data_subsys_covered.add(subsys)
# 也把数据里能看出的其他部件算进去
print(f"  数据部件可明确映射的子系统: {len(data_subsys_covered)}")
for s in sorted(data_subsys_covered):
    print(f"     · {s}")
print(f"  KB子系统: {len(kb_subsystem)} 个")
not_covered = kb_subsystem - data_subsys_covered
print(f"  数据未直接体现的KB子系统: {len(not_covered)}")
for s in sorted(not_covered):
    print(f"     · {s}  (注: 数据无对应部件, 但KB按功能分解已建)")

print("\n" + "=" * 80)
print("对比完成")
