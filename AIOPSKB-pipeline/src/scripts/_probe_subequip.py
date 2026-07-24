"""探查：数据仓库能否支撑「子设备(技术路线)」层确定"""
import sys, io, json, datetime
import psycopg2
from psycopg2.extras import RealDictCursor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PG = {'host':'172.21.1.10','port':'5432','user':'postgres',
      'password':'Postgres_Rozh123srv','database':'alg_analysis'}

now = datetime.datetime.now()
start = now.replace(year=now.year-5)

conn = psycopg2.connect(**PG)
cur = conn.cursor(cursor_factory=RealDictCursor)

# A. 设备表自带 industry 字段的分布(近5年)
print("=== A. stat_device_info.industry 直接分布 (近5年) ===")
cur.execute("""SELECT industry, count(*) c FROM stat_device_info
               WHERE creationtime>=%s GROUP BY industry ORDER BY c DESC""", (start,))
for r in cur.fetchall():
    print(f"  {r['industry']:24s} {r['c']:>7d}")

# B. havedevicemodel 分布
print("\n=== B. havedevicemodel 分布 ===")
cur.execute("""SELECT havedevicemodel, count(*) c FROM stat_device_info
               WHERE creationtime>=%s GROUP BY havedevicemodel ORDER BY c DESC""", (start,))
for r in cur.fetchall():
    print(f"  havedevicemodel={r['havedevicemodel']}  {r['c']}")

# C. 高频 devicetype 的 devicename 样本(挖技术路线线索)
print("\n=== C. Top devicetype 的 devicename 样本 ===")
cur.execute("""SELECT devicetype, count(*) c FROM stat_device_info
               WHERE creationtime>=%s GROUP BY devicetype ORDER BY c DESC LIMIT 6""", (start,))
top_types = cur.fetchall()
enum_devtype = {}
cur.execute("SELECT value, label FROM tools_enum_info WHERE type='devicetype'")
for r in cur.fetchall():
    enum_devtype[str(r['value'])] = r['label']

for t in top_types:
    dt = t['devicetype']
    label = enum_devtype.get(str(dt), '?')
    print(f"\n  devicetype={dt} [{label}] 共 {t['c']} 台:")
    cur.execute("""SELECT devicename FROM stat_device_info
                   WHERE creationtime>=%s AND devicetype=%s LIMIT 10""", (start, dt))
    for r in cur.fetchall():
        print(f"     - {r['devicename']}")

# D. 一个有模型设备的 devicemodeljson 结构
print("\n=== D. devicemodeljson 结构样本 ===")
cur.execute("""SELECT devicename, devicetype, devicemodeljson
               FROM stat_device_info
               WHERE creationtime>=%s AND havedevicemodel=1
                 AND devicemodeljson IS NOT NULL AND devicemodeljson!=''
               LIMIT 3""", (start,))
for r in cur.fetchall():
    print(f"\n  设备: {r['devicename']} (devicetype={r['devicetype']})")
    raw = r['devicemodeljson']
    print(f"  json 长度: {len(raw)} 字符")
    print(f"  片段(前800): {raw[:800]}")

cur.close(); conn.close()
