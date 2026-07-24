"""
水泥行业数据仓库分析 (KB 未构建, 作为构建起点)
=============================================
水泥 = 数据量 17,072 台, C 级(未分类 38.9%, 和钢铁相似)
特色: 设备:部件 ≈ 1:1 (立磨/回转窑等设备本体有部件级监测)
分析维度:
  1. 总览 + 按知识库层级
  2. 设备级按工艺归类 (生料制备/烧成/熟料冷却/水泥粉磨/包装)
  3. 部件级清单 (水泥特色: 磨机辊/液压/回转窑部件)
  4. 立磨/回转窑细分 (水泥核心设备)
  5. 风机/泵 细分 (通用动设备)
  6. 静设备盘点 (回转窑本体/篦冷机数据缺位)
  7. 异常/跨界
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

EXPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_export')
df = pd.read_csv(os.path.join(EXPORT, 'industry_devicetype_topN.csv'),
                 encoding='utf-8-sig', dtype={'devicetype': str})

# ---- 确认行业名 ----
all_ind = sorted(df['industry_cn'].unique())
cement_name = None
for k in ['水泥', '建材', '新型建材']:
    if k in all_ind:
        cement_name = k
        break
if cement_name is None:
    for v in all_ind:
        if '水泥' in str(v):
            cement_name = v
            break
print(f"\n=> 使用行业名: {cement_name}")
ce = df[df['industry_cn'] == cement_name].sort_values('device_count', ascending=False)

print("=" * 80)
print(f"水泥行业数据仓库分析 (近5年)  [{cement_name}]")
print("=" * 80)
total = ce['device_count'].sum()
print(f"设备总数: {total} 台 | 企业: {ce['enterprise_count'].max()} 家 | 型号数: {len(ce)}")
print(f"未分类: {ce[ce['devicetype_cn']=='(未分类)']['device_count'].sum()} 台 "
      f"({ce[ce['devicetype_cn']=='(未分类)']['device_count'].sum()/total*100:.1f}%)")

# ---- 1. 按知识库层级 ----
print("\n--- 按知识库层级 ---")
for lvl in ['设备', '子设备', '部件', '其他']:
    sub = ce[ce['kb_level'] == lvl]
    if len(sub):
        print(f"  {lvl}: {len(sub)} 型号, {sub['device_count'].sum()} 台 ({sub['device_count'].sum()/total*100:.1f}%)")

# ---- 2. 设备级按工艺归类 ----
print("\n" + "=" * 80)
print("设备级按工艺/设备类型归类")
print("=" * 80)
eq = ce[ce['kb_level'] == '设备'].copy()

CATEGORIES = [
    ('立磨(核心-粉磨)', ['立磨', '生料磨', '水泥磨', '原料磨', '煤磨', '磨机']),
    ('回转窑(核心-烧成)', ['回转窑', '窑', '烧成']),
    ('篦冷机(熟料冷却)', ['篦冷机', '冷却机']),
    ('风机类(动设备)', ['风机']),
    ('泵类(动设备)', ['泵']),
    ('破碎机(原料制备)', ['破碎机', '破碎']),
    ('输送设备', ['输送机', '皮带', '斗提', '提升机', '给料']),
    ('提升机(垂直输送)', ['提升机', '斗式提升']),
    ('选粉机/分离器', ['选粉', '分离', '分级']),
    ('包装机/散装', ['包装', '散装']),
    ('除尘/环保', ['除尘', '收尘', '环保']),
    ('电机/发电机', ['电机', '发电机', '电动机']),
    ('液压设备', ['液压', '油缸']),
]
assigned = set()
for cat, kws in CATEGORIES:
    mask = eq['devicetype_cn'].apply(lambda n: any(k in str(n) for k in kws))
    sub = eq[mask & ~eq['devicetype'].isin(assigned)]
    if len(sub):
        assigned |= set(sub['devicetype'])
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(4).iterrows())
        print(f"  {cat:<22} {len(sub):>3}型号 {sub['device_count'].sum():>6}台  | {examples}")
rest = eq[~eq['devicetype'].isin(assigned)]
if len(rest):
    print(f"  {'其他(未归类)':<22} {len(rest):>3}型号 {rest['device_count'].sum():>6}台")
    for _, r in rest.head(10).iterrows():
        print(f"     - {r['devicetype_cn']} ({int(r['device_count'])}台, {int(r['enterprise_count'])}企业)")

# ---- 3. 部件级清单 ----
print("\n" + "=" * 80)
print("部件级清单 (水泥特色: 磨机辊/液压/回转窑部件)")
print("=" * 80)
comp = ce[ce['kb_level'] == '部件'].sort_values('device_count', ascending=False)
print(f"部件级合计: {len(comp)} 型号, {comp['device_count'].sum()} 台 (占水泥 {comp['device_count'].sum()/total*100:.1f}%)")
for _, r in comp.iterrows():
    flag = ' ⚠单企业' if r['enterprise_count'] <= 1 else ''
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>6}台  {int(r['enterprise_count']):>4}企业{flag}")

# ---- 4. 立磨细分 ----
print("\n" + "=" * 80)
print("立磨细分 (水泥核心设备)")
print("=" * 80)
mill_all = ce[ce['devicetype_cn'].apply(lambda n: any(k in str(n) for k in ['立磨', '磨机', '生料磨', '水泥磨', '原料磨', '煤磨']))].copy()
print(f"立磨及磨机相关: {len(mill_all)} 型号, {mill_all['device_count'].sum()} 台 (占水泥 {mill_all['device_count'].sum()/total*100:.1f}%)")
MILL_TYPES = [
    ('立磨(核心)', ['立磨', '生料磨', '原料磨']),
    ('水泥磨', ['水泥磨']),
    ('煤磨', ['煤磨']),
    ('磨机(通用)', ['磨机']),
]
m_assigned = set()
for mt, kws in MILL_TYPES:
    mask = mill_all['devicetype_cn'].apply(lambda n: any(k in str(n) for k in kws))
    sub = mill_all[mask & ~mill_all['devicetype'].isin(m_assigned)]
    if len(sub):
        m_assigned |= set(sub['devicetype'])
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(5).iterrows())
        print(f"  {mt:<14} {len(sub):>3}型号 {sub['device_count'].sum():>6}台  | {examples}")

# ---- 5. 回转窑/烧成细分 ----
print("\n--- 回转窑/烧成细分 ---")
kiln = ce[ce['devicetype_cn'].apply(lambda n: any(k in str(n) for k in ['回转窑', '窑', '烧成']))].sort_values('device_count', ascending=False)
print(f"回转窑及烧成相关: {len(kiln)} 型号, {kiln['device_count'].sum()} 台")
for _, r in kiln.head(8).iterrows():
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>6}台  {int(r['enterprise_count'])}企业")

# ---- 6. 风机/泵细分 ----
print("\n--- 风机细分 ---")
fans = ce[ce['devicetype_cn'].apply(lambda n: '风机' in str(n))].sort_values('device_count', ascending=False)
print(f"风机合计: {len(fans)} 型号, {fans['device_count'].sum()} 台")
for _, r in fans.head(8).iterrows():
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>6}台  {int(r['enterprise_count'])}企业")

print("\n--- 泵细分 ---")
pumps = ce[ce['devicetype_cn'].apply(lambda n: '泵' in str(n))].sort_values('device_count', ascending=False)
print(f"泵合计: {len(pumps)} 型号, {pumps['device_count'].sum()} 台")
for _, r in pumps.head(8).iterrows():
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>6}台  {int(r['enterprise_count'])}企业")

# ---- 7. 静设备盘点 ----
print("\n" + "=" * 80)
print("静设备盘点 (回转窑本体/篦冷机等, 数据缺位)")
print("=" * 80)
STATIC = ['回转窑', '篦冷机', '预热器', '分解炉', '窑', '塔', '反应器', '仓', '库']
for kw in STATIC:
    sub = ce[ce['devicetype_cn'].apply(lambda n: kw in str(n))]
    if len(sub):
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(3).iterrows())
        print(f"  [{kw}] {len(sub)}型号 {sub['device_count'].sum()}台  | {examples}")

# ---- 8. 异常跨界 ----
print("\n" + "=" * 80)
print("异常跨界 (水泥里不该出现)")
print("=" * 80)
ANOMALY = ['浮选', '选矿', '磁选', '轧机', '烧结', '高炉', '转炉', '反应釜', '聚合', '挤出']
found = False
for _, r in ce.iterrows():
    if any(a in str(r['devicetype_cn']) for a in ANOMALY):
        print(f"  ⚠ {r['devicetype_cn']:<14} ({r['devicetype']}) {int(r['device_count'])}台  {int(r['enterprise_count'])}企业")
        found = True
if not found:
    print("  (无明显跨界)")

# ---- 9. Top20 优先级快照 ----
print("\n" + "=" * 80)
print("Top20 设备级优先级快照 (排除部件级+未分类+单企业)")
print("=" * 80)
prio = ce[(ce['kb_level'] == '设备') &
          (ce['devicetype_cn'] != '(未分类)') &
          (ce['enterprise_count'] > 1)].head(20)
for i, (_, r) in enumerate(prio.iterrows(), 1):
    print(f"  {i:>2}. {str(r['devicetype_cn'])[:16]:<18} {int(r['device_count']):>6}台  {int(r['enterprise_count']):>4}企业")
