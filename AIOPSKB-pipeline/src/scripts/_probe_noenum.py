"""反查「无枚举」devicetype 的真实含义 (用 devicename 高频词反推)"""
import sys, io, datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
PG = {'host': '172.21.1.10', 'port': '5432', 'user': 'postgres',
      'password': 'Postgres_Rozh123srv', 'database': 'alg_analysis'}

now = datetime.datetime.now()
start = now.replace(year=now.year - 5)

conn = psycopg2.connect(**PG)
cur = conn.cursor(cursor_factory=RealDictCursor)

# 取近5年 TopN 清单里出现过的「无枚举」devicetype
cur.execute("SELECT DISTINCT value FROM tools_enum_info WHERE type='devicetype'")
enum_set = {str(r['value']) for r in cur.fetchall()}

# 全部 (industry, devicetype, devicename) 近5年
cur.execute("""SELECT industry, devicetype, devicename
               FROM stat_device_info
               WHERE creationtime >= %s AND devicetype IS NOT NULL AND devicetype <> ''""", (start,))
rows = cur.fetchall()
cur.close(); conn.close()

# 筛无枚举代码, 按 devicetype 聚合 devicename 频次 + 主要行业
by_dt = {}
for r in rows:
    dt = str(r['devicetype'])
    if dt in enum_set or dt == '0':
        continue
    d = by_dt.setdefault(dt, {'names': Counter(), 'ind': Counter(), 'total': 0})
    d['names'][r['devicename'] or '(空)'] += 1
    d['ind'][r['industry'] or '(空)'] += 1
    d['total'] += 1

# 只看 total>=50 的 (够量才有参照意义)
cands = sorted(by_dt.items(), key=lambda x: -x[1]['total'])
print(f"无枚举 devicetype 共 {len(by_dt)} 个, 下面列 total>=50 的 (按量降序):\n")
print(f"{'devicetype':>10} {'总量':>7}  {'主要行业(top2)':<22}  devicename 高频 top5")
print("-" * 110)
for dt, d in cands:
    if d['total'] < 50:
        break
    inds = ', '.join(f"{k}:{v}" for k, v in d['ind'].most_common(2))
    names = ' | '.join(f"{n}({c})" for n, c in d['names'].most_common(5))
    print(f"{dt:>10} {d['total']:>7}  {inds:<22}  {names[:80]}")
