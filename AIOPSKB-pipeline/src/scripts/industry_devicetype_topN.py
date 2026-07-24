"""
各行业设备类型 TopN 清单 (近5年)
================================
作用: 作为知识库「设备枚举 + 子设备(技术路线)划分」的外部参照。
      告诉你每个行业现场真实存在哪些设备型号、各有多少存量、多少企业在用。

N 的取法 (动态, 非固定):
  - 累计设备占比 >= 90% 即截止
  - 下限 10 / 上限 30
  - 排除空 devicetype (未分类, 单独统计)
  - 附企业数, 防止单企业刷量被误判为主流

输出 (db_export/):
  - industry_devicetype_topN.csv   全量 (industry x devicetype), 带 in_topn 标记
  - industry_summary.csv           行业汇总 (总设备/型号数/未分类/TopN覆盖度)
"""
import sys, io, os, datetime
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PG = {'host': '172.21.1.10', 'port': '5432', 'user': 'postgres',
      'password': 'Postgres_Rozh123srv', 'database': 'alg_analysis'}

N_MIN, N_MAX, COVERAGE = 10, 30, 90.0

now = datetime.datetime.now()
start = now.replace(year=now.year - 5)
print(f"时间范围: {start:%Y-%m-%d} ~ {now:%Y-%m-%d} (近5年)")
print(f"N 规则: 累计占比>={COVERAGE}% 截止, 范围 [{N_MIN},{N_MAX}], 排除空 devicetype\n")

conn = psycopg2.connect(**PG)
cur = conn.cursor(cursor_factory=RealDictCursor)

# 枚举字典
cur.execute("SELECT type, value, label FROM tools_enum_info")
enum = pd.DataFrame(cur.fetchall())
ind_cn = dict(zip(enum[enum['type'] == 'industry']['value'].astype(str),
                  enum[enum['type'] == 'industry']['label'].astype(str)))
dt_cn = dict(zip(enum[enum['type'] == 'devicetype']['value'].astype(str),
                 enum[enum['type'] == 'devicetype']['label'].astype(str)))

# 聚合: 行业 x 设备类型 -> 设备数, 企业数(distinct within group)
cur.execute("""SELECT industry,
                      COALESCE(NULLIF(devicetype, ''), '(未分类)') AS devicetype,
                      count(*) AS device_count,
                      count(DISTINCT enterprisecode) AS enterprise_count
               FROM stat_device_info
               WHERE creationtime >= %s
               GROUP BY industry, devicetype""", (start,))
df = pd.DataFrame(cur.fetchall())

# 行业级 distinct 企业数 (单独查, 避免跨型号重复求和)
cur.execute("""SELECT industry, count(DISTINCT enterprisecode) AS ent_total
               FROM stat_device_info WHERE creationtime >= %s GROUP BY industry""", (start,))
ent_total = {r['industry']: r['ent_total'] for r in cur.fetchall()}
cur.close(); conn.close()

df['industry'] = df['industry'].fillna('(空行业)').astype(str)
df['industry_cn'] = df['industry'].map(lambda x: ind_cn.get(x, x))
df['devicetype_cn'] = df['devicetype'].map(lambda x: dt_cn.get(x, '(无枚举)') if x != '(未分类)' else '(未分类)')
df['ent_total'] = df['industry'].map(ent_total).fillna(0).astype(int)

# 占比 (分母=该行业全量设备, 含未分类)
df['pct'] = df.groupby('industry')['device_count'].transform(lambda s: s / s.sum() * 100)

# 已分类子集 -> 排序/排名/累计
dfc = df[df['devicetype'] != '(未分类)'].copy()
dfc = dfc.sort_values(['industry', 'device_count'], ascending=[True, False])
dfc['rank'] = dfc.groupby('industry').cumcount() + 1
dfc['cum_pct'] = dfc.groupby('industry')['pct'].cumsum()

# 每行业达到覆盖度的截止 rank (非 apply, 避免 warning)
reach = dfc[dfc['cum_pct'] >= COVERAGE][['industry', 'rank']].groupby('industry').min()
max_rank = dfc.groupby('industry')['rank'].max()
cutoff = reach['rank'].reindex(max_rank.index).fillna(max_rank).astype(int)
n_by_ind = cutoff.clip(lower=N_MIN, upper=N_MAX)
dfc['n'] = dfc['industry'].map(n_by_ind)
dfc['in_topn'] = dfc['rank'] <= dfc['n']
dfc['single_ent'] = dfc['enterprise_count'] <= 1

# 未分类行
dfu = df[df['devicetype'] == '(未分类)'].copy()
dfu['rank'] = 0; dfu['cum_pct'] = 0; dfu['in_topn'] = False; dfu['single_ent'] = dfu['enterprise_count'] <= 1
dfu['n'] = 0

df_out = pd.concat([dfc, dfu], ignore_index=True)

# ---------- 行业汇总 (用 merge, 避免 map 要求唯一 index) ----------
ind_keys = df[['industry', 'industry_cn', 'ent_total']].drop_duplicates(subset=['industry'])
summary = (df.groupby(['industry', 'industry_cn'], as_index=False)
             .agg(设备总数=('device_count', 'sum')))
summary = summary.merge(ind_keys[['industry', 'ent_total']], on='industry', how='left')
summary['已分类型号数'] = summary['industry'].map(
    dfc.groupby('industry')['devicetype'].nunique()).fillna(0).astype(int)
summary['未分类设备数'] = summary['industry'].map(
    dfu.groupby('industry')['device_count'].sum()).fillna(0).astype(int)
summary['TopN个数'] = summary['industry'].map(
    dfc[dfc['in_topn']].groupby('industry').size()).fillna(0).astype(int)
summary['TopN覆盖度%'] = summary['industry'].map(
    dfc[dfc['in_topn']].groupby('industry')['pct'].sum()).round(1)
summary = summary.rename(columns={'ent_total': '企业数'})
summary = summary[['industry_cn', '设备总数', '企业数', '已分类型号数', '未分类设备数', 'TopN个数', 'TopN覆盖度%']]
summary = summary.sort_values('设备总数', ascending=False).reset_index(drop=True)

# ---------- 终端输出 ----------
print("=" * 92)
print("行业汇总 (按设备总数降序)")
print("=" * 92)
print(summary.to_string(index=False))

print("\n" + "=" * 92)
print("各行业 TopN 设备类型明细  (设备数降序; 企业数≤1 标 ⚠)")
print("=" * 92)
for ind in summary['industry_cn']:
    sub = dfc[(dfc['industry_cn'] == ind) & (dfc['in_topn'])].copy()
    if sub.empty:
        continue
    row = summary[summary['industry_cn'] == ind].iloc[0]
    print(f"\n▼ {ind}  | 设备 {row['设备总数']} 台 / 企业 {row['企业数']} 家 / "
          f"TopN {row['TopN个数']}个 (覆盖 {row['TopN覆盖度%']}%) / 未分类 {row['未分类设备数']} 台")
    disp = sub[['rank', 'devicetype_cn', 'devicetype', 'device_count',
                'enterprise_count', 'pct', 'cum_pct', 'single_ent']].copy()
    disp.columns = ['#', '设备类型(中)', 'devicetype', '设备数', '企业数', '占比%', '累计%', '单企业?']
    disp['设备类型(中)'] = disp['设备类型(中)'].str.slice(0, 14)
    disp['占比%'] = disp['占比%'].round(1)
    disp['累计%'] = disp['累计%'].round(1)
    disp['单企业?'] = disp['单企业?'].map({True: '⚠', False: ''})
    print(disp.to_string(index=False))

# ---------- 导出 ----------
EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_export')
os.makedirs(EXPORT_DIR, exist_ok=True)
cols = ['industry_cn', 'industry', 'rank', 'devicetype', 'devicetype_cn',
        'device_count', 'enterprise_count', 'single_ent', 'pct', 'cum_pct', 'in_topn']
df_out[cols].sort_values(['industry_cn', 'rank']).to_csv(
    os.path.join(EXPORT_DIR, 'industry_devicetype_topN.csv'), index=False, encoding='utf-8-sig')
summary.to_csv(os.path.join(EXPORT_DIR, 'industry_summary.csv'), index=False, encoding='utf-8-sig')

print(f"\n已导出:")
print(f"  {os.path.join(EXPORT_DIR, 'industry_devicetype_topN.csv')}")
print(f"  {os.path.join(EXPORT_DIR, 'industry_summary.csv')}")
