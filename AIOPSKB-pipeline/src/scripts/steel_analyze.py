"""
钢铁行业数据仓库分析 (KB 未构建, 作为构建起点)
=============================================
钢铁 = 数据量第二大(37,872 台), C 级(分散/未分类高 35%), 比石化更难啃
分析维度:
  1. 总览 + 按知识库层级
  2. 设备级按工艺/类型归类 (轧机/风机/泵/电机/输送/起重/液压/炉窑)
  3. 部件级清单 (钢铁特色: 辊/锥箱/齿轮箱/轴承座 数据丰富, 直接辅助部件层)
  4. 轧机及轧钢传动细分 (钢铁第一大监测设备类)
  5. 风机/泵细分 (通用动设备)
  6. 静设备盘点 (高炉/转炉/轧机本体 数据缺位, 须标准)
  7. 异常/跨界设备
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

EXPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_export')
df = pd.read_csv(os.path.join(EXPORT, 'industry_devicetype_topN.csv'),
                 encoding='utf-8-sig', dtype={'devicetype': str})

# ---- 确认行业名 (枚举翻译可能是"钢铁"/"冶金"/"黑色金属") ----
all_ind = sorted(df['industry_cn'].unique())
print("所有行业枚举:", all_ind)
steel_name = None
for k in ['钢铁', '冶金', '黑色金属', '黑色冶金']:
    if k in all_ind:
        steel_name = k
        break
if steel_name is None:
    for v in all_ind:
        if '钢' in str(v) or '冶' in str(v):
            steel_name = v
            break
print(f"\n=> 使用行业名: {steel_name}")
st = df[df['industry_cn'] == steel_name].sort_values('device_count', ascending=False)

print("=" * 80)
print(f"钢铁行业数据仓库分析 (近5年)  [{steel_name}]")
print("=" * 80)
total = st['device_count'].sum()
classified = st[st['devicetype_cn'] != '(未分类)']
unclassified = st[st['devicetype_cn'] == '(未分类)']['device_count'].sum()
print(f"设备总数: {total} 台 | 企业: {st['enterprise_count'].max()} 家 | 型号数: {len(st)}")
print(f"已分类: {len(classified)} 型号 / 未分类: {unclassified} 台 ({unclassified/total*100:.1f}%)")

# ---- 1. 按知识库层级 ----
print("\n--- 按知识库层级 ---")
for lvl in ['设备', '子设备', '部件', '其他']:
    sub = st[st['kb_level'] == lvl]
    if len(sub):
        print(f"  {lvl}: {len(sub)} 型号, {sub['device_count'].sum()} 台 ({sub['device_count'].sum()/total*100:.1f}%)")

# ---- 2. 设备级按工艺/类型归类 ----
print("\n" + "=" * 80)
print("设备级按工艺/设备类型归类")
print("=" * 80)
eq = st[st['kb_level'] == '设备'].copy()

CATEGORIES = [
    ('轧机及轧钢传动(核心)', ['轧机', '轧辊', '轧制', '连轧']),
    ('风机类(动设备)', ['风机']),
    ('泵类(动设备)', ['泵']),
    ('压缩机类(动设备)', ['压缩机']),
    ('电机/发电机', ['电机', '发电机', '电动机']),
    ('破碎/磨(原料准备)', ['破碎机', '磨机', '球磨', '破碎']),
    ('输送设备', ['输送机', '皮带', '斗提', '皮带机', '给料机', '喂料']),
    ('起重设备', ['行车', '吊车', '起重机', '卷扬', '天车']),
    ('液压设备', ['液压', '油缸']),
    ('连铸设备', ['连铸', '结晶器']),
    ('炉窑/反应(静设备)', ['高炉', '转炉', '电炉', '加热炉', '烧结', '焦炉', '热风炉', '锅炉', '窑']),
    ('电气设备', ['变压器', '开关柜', '配电']),
    ('阀门', ['阀']),
    ('容器/储罐', ['罐', '容器']),
]
assigned = set()
for cat, kws in CATEGORIES:
    mask = eq['devicetype_cn'].apply(lambda n: any(k in str(n) for k in kws))
    sub = eq[mask & ~eq['devicetype'].isin(assigned)]
    if len(sub):
        assigned |= set(sub['devicetype'])
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(5).iterrows())
        print(f"  {cat:<24} {len(sub):>3}型号 {sub['device_count'].sum():>6}台  | {examples}")
rest = eq[~eq['devicetype'].isin(assigned)]
if len(rest):
    print(f"  {'其他(未归类)':<24} {len(rest):>3}型号 {rest['device_count'].sum():>6}台")
    for _, r in rest.head(15).iterrows():
        print(f"     - {r['devicetype_cn']} ({int(r['device_count'])}台, {int(r['enterprise_count'])}企业)")

# ---- 3. 部件级清单 (钢铁特色, 直接辅助部件层) ----
print("\n" + "=" * 80)
print("部件级清单 (钢铁特色: 辊/锥箱/齿轮箱等被单独监测, 是部件层候选)")
print("=" * 80)
comp = st[st['kb_level'] == '部件'].sort_values('device_count', ascending=False)
print(f"部件级合计: {len(comp)} 型号, {comp['device_count'].sum()} 台 (占钢铁 {comp['device_count'].sum()/total*100:.1f}%)")
for _, r in comp.iterrows():
    flag = ' ⚠单企业' if r['enterprise_count'] <= 1 else ''
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>6}台  {int(r['enterprise_count']):>4}企业{flag}")

# ---- 4. 轧机及轧钢传动细分 ----
print("\n" + "=" * 80)
print("轧机及轧钢传动细分 (钢铁第一大监测设备类)")
print("=" * 80)
roll_all = st[st['devicetype_cn'].apply(lambda n: any(k in str(n) for k in ['轧机', '轧辊', '辊', '锥箱', '齿轮座']))].copy()
ROLL_TYPES = [
    ('主轧机', ['轧机']),
    ('轧辊(工作/支撑)', ['轧辊']),
    ('各类导辊/张力辊/夹送辊', ['辊']),
    ('锥箱/减速箱/齿轮座', ['锥箱', '减速箱', '减速机', '齿轮座', '齿轮箱']),
]
r_assigned = set()
roll_total = roll_all['device_count'].sum()
print(f"轧钢相关合计: {len(roll_all)} 型号, {roll_total} 台 (占钢铁 {roll_total/total*100:.1f}%)")
for rt, kws in ROLL_TYPES:
    mask = roll_all['devicetype_cn'].apply(lambda n: any(k in str(n) for k in kws))
    sub = roll_all[mask & ~roll_all['devicetype'].isin(r_assigned)]
    if len(sub):
        r_assigned |= set(sub['devicetype'])
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(6).iterrows())
        print(f"  {rt:<24} {len(sub):>3}型号 {sub['device_count'].sum():>6}台  | {examples}")

# ---- 5. 风机/泵 细分 ----
print("\n" + "=" * 80)
print("风机细分 (烧结主抽/高炉鼓风/除尘/焦炉风机)")
print("=" * 80)
fans = st[st['devicetype_cn'].apply(lambda n: '风机' in str(n))].sort_values('device_count', ascending=False)
print(f"风机合计: {len(fans)} 型号, {fans['device_count'].sum()} 台")
for _, r in fans.head(12).iterrows():
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>5}台  {int(r['enterprise_count'])}企业")

print("\n--- 泵细分 ---")
pumps = st[st['devicetype_cn'].apply(lambda n: '泵' in str(n))].sort_values('device_count', ascending=False)
print(f"泵合计: {len(pumps)} 型号, {pumps['device_count'].sum()} 台")
for _, r in pumps.head(10).iterrows():
    print(f"  {str(r['devicetype_cn'])[:14]:<16} {int(r['device_count']):>5}台  {int(r['enterprise_count'])}企业")

# ---- 6. 静设备盘点 (数据缺位, 须标准) ----
print("\n" + "=" * 80)
print("静设备盘点 (高炉/转炉/轧机本体等, 数据缺位, 须标准构建)")
print("=" * 80)
STATIC = ['高炉', '热风炉', '转炉', '电炉', '精炼', '加热炉', '烧结机', '焦炉',
          '连铸', '结晶器', '球团', '链篦', '回转窑', '锅炉', '窑', '塔', '反应']
for kw in STATIC:
    sub = st[st['devicetype_cn'].apply(lambda n: kw in str(n))]
    if len(sub):
        examples = ', '.join(f"{r['devicetype_cn']}({int(r['device_count'])})" for _, r in sub.head(3).iterrows())
        print(f"  [{kw}] {len(sub)}型号 {sub['device_count'].sum()}台  | {examples}")

# ---- 7. 异常/跨界 (钢铁里不该出现的) ----
print("\n" + "=" * 80)
print("异常/跨界设备 (钢铁里不该出现, 可能行业标注错误)")
print("=" * 80)
ANOMALY = ['浮选', '选矿', '磁选', '塔器', '精馏', '反应釜', '挤出机', '切粒机',
           '混炼', '聚合', '采煤', '掘进', '液压支架']
found = False
for _, r in st.iterrows():
    if any(a in str(r['devicetype_cn']) for a in ANOMALY):
        print(f"  ⚠ {r['devicetype_cn']:<14} ({r['devicetype']}) {int(r['device_count'])}台  {int(r['enterprise_count'])}企业")
        found = True
if not found:
    print("  (无明显跨界设备)")

# ---- 8. Top30 优先级快照 (按设备数降序, 排除部件级和未分类) ----
print("\n" + "=" * 80)
print("Top30 设备级优先级快照 (排除部件级 + 未分类 + 单企业特例)")
print("=" * 80)
prio = st[(st['kb_level'] == '设备') &
          (st['devicetype_cn'] != '(未分类)') &
          (st['enterprise_count'] > 1)].head(30)
for i, (_, r) in enumerate(prio.iterrows(), 1):
    print(f"  {i:>2}. {str(r['devicetype_cn'])[:16]:<18} {int(r['device_count']):>6}台  {int(r['enterprise_count']):>4}企业")
