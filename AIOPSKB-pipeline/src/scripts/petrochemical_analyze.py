"""
石化行业数据仓库分析 (KB 未构建, 作为构建起点)
=============================================
分析维度:
  1. 总览 + 按知识库层级
  2. 设备级按工艺/设备类型归类 (动设备/静设备/输送/破碎/起重/电气)
  3. 泵类细分 (石化核心, 占比最大)
  4. 压缩机类细分
  5. 异常/跨界设备 (如环冷机出现在石化)
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

EXPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_export')
df = pd.read_csv(os.path.join(EXPORT, 'industry_devicetype_topN.csv'),
                 encoding='utf-8-sig', dtype={'devicetype': str})
pe = df[df['industry_cn'] == '石化'].sort_values('device_count', ascending=False)

print("=" * 80)
print("石化行业数据仓库分析 (近5年)")
print("=" * 80)
total = pe['device_count'].sum()
classified = pe[pe['devicetype_cn'] != '(未分类)']
print(f"设备总数: {total} 台 | 企业: {pe['enterprise_count'].max()} 家 | 型号数: {len(pe)}")
print(f"已分类: {len(classified)} 型号 / 未分类: {pe[pe['devicetype_cn']=='(未分类)']['device_count'].sum()} 台")

# ---- 1. 按知识库层级 ----
print("\n--- 按知识库层级 ---")
for lvl in ['设备', '部件', '其他']:
    sub = pe[pe['kb_level'] == lvl]
    if len(sub):
        print(f"  {lvl}: {len(sub)} 型号, {sub['device_count'].sum()} 台 ({sub['device_count'].sum()/total*100:.1f}%)")

# ---- 2. 设备级按工艺/类型归类 ----
print("\n" + "=" * 80)
print("设备级按工艺/设备类型归类 (动设备/静设备/...)")
print("=" * 80)
eq = pe[pe['kb_level'] == '设备'].copy()

CATEGORIES = [
    ('泵类(动设备)', ['泵']),
    ('压缩机类(动设备)', ['压缩机']),
    ('风机类(动设备)', ['风机']),
    ('搅拌/混合(动设备)', ['搅拌', '混合', '捏合']),
    ('离心/分离(动设备)', ['离心机', '分离机', '分离器']),
    ('塔器/反应(静设备)', ['塔', '反应釜', '反应器', '结晶器', '蒸发器']),
    ('换热设备(静设备)', ['换热器', '冷凝器', '冷却器', '冷却塔']),
    ('输送设备', ['输送机', '提升机', '给料机', '喂料机']),
    ('破碎/磨', ['破碎机', '磨机', '磨']),
    ('起重设备', ['行车', '吊车', '起重机', '卷扬']),
    ('电气设备', ['变压器', '开关柜', '配电', '发电机', '电动机']),
    ('阀门', ['阀']),
    ('容器/储罐', ['罐', '容器']),
]
assigned = set()
for cat, kws in CATEGORIES:
    mask = eq['devicetype_cn'].apply(lambda n: any(k in str(n) for k in kws))
    sub = eq[mask & ~eq['devicetype'].isin(assigned)]
    if len(sub):
        assigned |= set(sub['devicetype'])
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(4).iterrows())
        print(f"  {cat:<22} {len(sub):>3}型号 {sub['device_count'].sum():>6}台  | {examples}")
# 未归类
rest = eq[~eq['devicetype'].isin(assigned)]
if len(rest):
    print(f"  {'其他':<22} {len(rest):>3}型号 {rest['device_count'].sum():>6}台")
    for _, r in rest.head(10).iterrows():
        print(f"     - {r['devicetype_cn']} ({int(r['device_count'])}台)")

# ---- 3. 泵类细分 ----
print("\n" + "=" * 80)
print("泵类细分 (石化第一大设备类别)")
print("=" * 80)
pumps = pe[pe['devicetype_cn'].apply(lambda n: '泵' in str(n))].copy()
PUMP_TYPES = [
    ('离心泵', ['离心泵']), ('屏蔽泵', ['屏蔽泵']), ('磁力泵', ['磁力泵']),
    ('齿轮泵', ['齿轮泵']), ('螺杆泵', ['螺杆泵']),
    ('柱塞泵', ['柱塞泵']), ('真空泵', ['真空泵']), ('喷射泵', ['喷射泵']),
    ('往复/活塞泵', ['往复', '活塞']), ('轴流泵', ['轴流泵']),
    ('高速泵', ['高速泵']), ('立式筒袋泵', ['立式筒袋']),
    ('滑片泵', ['滑片泵']), ('隔膜泵', ['隔膜泵']), ('罗茨泵', ['罗茨泵']),
]
p_assigned = set()
pump_total = pumps['device_count'].sum()
print(f"泵类合计: {len(pumps)} 型号, {pump_total} 台 (占石化 {pump_total/total*100:.1f}%)")
for pt, kws in PUMP_TYPES:
    mask = pumps['devicetype_cn'].apply(lambda n: any(k in str(n) for k in kws))
    sub = pumps[mask & ~pumps['devicetype'].isin(p_assigned)]
    if len(sub):
        p_assigned |= set(sub['devicetype'])
        print(f"  {pt:<14} {sub['device_count'].sum():>6}台 ({sub['device_count'].sum()/pump_total*100:>4.1f}%)  {len(sub)}型号")
generic = pumps[~pumps['devicetype'].isin(p_assigned)]
if len(generic):
    print(f"  {'通用泵(泵/大机组等)':<14} {generic['device_count'].sum():>6}台")

# ---- 4. 压缩机细分 ----
print("\n" + "=" * 80)
print("压缩机类细分")
print("=" * 80)
comps = pe[pe['devicetype_cn'].apply(lambda n: '压缩机' in str(n))]
print(f"压缩机合计: {len(comps)} 型号, {comps['device_count'].sum()} 台")
for _, r in comps.iterrows():
    print(f"  {r['devicetype_cn']:<16} {int(r['device_count']):>5}台  {int(r['enterprise_count'])}企业")

# ---- 5. 异常/跨界 ----
print("\n" + "=" * 80)
print("异常/跨界设备 (石化里不该出现的, 可能行业标注错误)")
print("=" * 80)
ANOMALY = ['环冷机', '轧机', '烧结', '高炉', '浮选', '斗提', '回转窑', '磨煤']
for _, r in pe.iterrows():
    if any(a in str(r['devicetype_cn']) for a in ANOMALY):
        print(f"  ⚠ {r['devicetype_cn']:<14} ({r['devicetype']}) {int(r['device_count'])}台  — 疑似冶金/矿业设备")
