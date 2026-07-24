"""
行业设备分布统计
================
从 PHM 数据仓库 (alg_analysis) 导出「每个行业下的设备分布」。

为什么需要这个脚本:
  stat_device_info 本身没有「行业」字段, 行业是绑在企业上的。
  需要 stat_enterprise_info (企业->行业) 来桥接, 再用 tools_enum_info
  把 industry / devicetype 代码翻译成中文, 最后按行业分组统计。

数据流:
  stat_device_info  (近5年设备, 按 creationtime 过滤, 全量; 不再用 LIMIT 5000)
        +  stat_enterprise_info  (企业 -> 行业 映射)
        +  tools_enum_info       (industry / devicetype 代码 -> 中文)

输出 (写到 db_export/):
  - industry_device_distribution.csv   各行业 -> 设备数 / 企业数 汇总
  - industry_devicetype_detail.csv     行业 x 设备类型 明细
"""

import os
import sys
import io
import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# Windows 控制台 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# === 库配置 (与 数据仓库外发.py 一致, 需内网访问) ===
PG_PARAS = {
    'host': '172.21.1.10',
    'port': '5432',
    'user': 'postgres',
    'password': 'Postgres_Rozh123srv',
    'database': 'alg_analysis',
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(SCRIPT_DIR, 'db_export')
os.makedirs(EXPORT_DIR, exist_ok=True)


def query_df(sql, params=None):
    """执行 SQL, 返回 DataFrame"""
    conn = psycopg2.connect(**PG_PARAS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return pd.DataFrame(rows)
    finally:
        conn.close()


def find_col(columns, keywords):
    """按关键词模糊匹配列名 (大小写无关)"""
    for col in columns:
        cl = str(col).lower()
        if any(k in cl for k in keywords):
            return col
    return None


def main():
    # ---------- 1. 时间范围: 近5年 ----------
    now = datetime.datetime.now()
    try:
        start = now.replace(year=now.year - 5)
    except ValueError:  # 处理 2/29 这种边界
        start = now.replace(year=now.year - 5, month=2, day=28)
    print(f"时间范围: {start:%Y-%m-%d} ~ {now:%Y-%m-%d} (近5年)")

    # ---------- 2. 设备表 (近5年, 全量) ----------
    print("\n[1/4] 读取设备表 stat_device_info (近5年)...")
    df_dev = query_df(
        """SELECT deviceid, devicename, devicetype, assettype,
                  enterprisecode, creationtime
           FROM stat_device_info
           WHERE creationtime >= %s
           ORDER BY creationtime""",
        (start,)
    )
    print(f"  OK | {len(df_dev)} 台设备")

    # ---------- 3. 企业表 (探明结构 + 全量) ----------
    print("\n[2/4] 读取企业表 stat_enterprise_info...")
    df_ent = query_df("SELECT * FROM stat_enterprise_info")
    print(f"  OK | {len(df_ent)} 家企业")
    print(f"  企业表列名: {list(df_ent.columns)}")

    # ---------- 4. 枚举字典 (代码 -> 中文) ----------
    print("\n[3/4] 读取枚举字典 tools_enum_info...")
    df_enum = query_df("SELECT type, value, label FROM tools_enum_info")
    enum_industry = dict(zip(
        df_enum.loc[df_enum['type'] == 'industry', 'value'].astype(str),
        df_enum.loc[df_enum['type'] == 'industry', 'label'].astype(str),
    ))
    enum_devtype = dict(zip(
        df_enum.loc[df_enum['type'] == 'devicetype', 'value'].astype(str),
        df_enum.loc[df_enum['type'] == 'devicetype', 'label'].astype(str),
    ))
    print(f"  OK | industry 枚举 {len(enum_industry)} 条, devicetype 枚举 {len(enum_devtype)} 条")

    # ---------- 5. 自动探测企业表的「企业代码」和「行业」列 ----------
    ent_cols = list(df_ent.columns)
    col_ent_code = find_col(ent_cols, ['enterprisecode', 'enterpriseid', 'enterpriseno'])
    col_industry = find_col(ent_cols, ['industry', '行业'])
    print(f"\n  探测 -> 企业代码列: {col_ent_code!r}   行业列: {col_industry!r}")
    if not col_ent_code or not col_industry:
        print("  !! 未能自动定位企业代码列或行业列, 请对照上面的「企业表列名」")
        print("     在脚本里手动把 col_ent_code / col_industry 改成正确的列名后重跑。")
        return

    # ---------- 6. 关联: 设备 -> 行业 ----------
    print("\n[4/4] 关联 + 统计...")
    ent_map = (df_ent[[col_ent_code, col_industry]]
               .dropna()
               .drop_duplicates(subset=[col_ent_code])  # 企业代码可能重复, 去重保唯一
               .copy())
    ent_map[col_ent_code] = ent_map[col_ent_code].astype(str)
    ent_map = ent_map.set_index(col_ent_code)[col_industry]

    df_dev['enterprisecode'] = df_dev['enterprisecode'].astype(str)
    df_dev['industry_raw'] = df_dev['enterprisecode'].map(ent_map)
    # 行业: 若是 IndustryType_xx 代码则翻译成中文, 若已是中文则原样保留
    df_dev['industry'] = df_dev['industry_raw'].map(lambda x: enum_industry.get(x, x))
    # 设备类型: 代码(558010) -> 中文(结晶器)
    df_dev['devicetype'] = df_dev['devicetype'].astype(str)
    df_dev['device_type'] = df_dev['devicetype'].map(lambda x: enum_devtype.get(x, x))

    matched = int(df_dev['industry_raw'].notna().sum())
    print(f"  设备关联到行业的: {matched}/{len(df_dev)} ({matched / max(len(df_dev), 1):.0%})")
    # 打印行业原始值样本, 方便核对翻译是否正确
    raw_samples = df_dev['industry_raw'].dropna().unique()[:20].tolist()
    print(f"  行业列原始值样本: {raw_samples}")

    # ---------- 7. 汇总统计 ----------
    # (a) 每个行业 -> 设备数 / 企业数
    summary = (df_dev.groupby('industry')
                     .agg(设备数=('deviceid', 'count'),
                          企业数=('enterprisecode', 'nunique'))
                     .sort_values('设备数', ascending=False)
                     .reset_index())

    # (b) 行业 x 设备类型 明细
    detail = (df_dev.groupby(['industry', 'device_type'])
                    .agg(设备数=('deviceid', 'count'))
                    .reset_index()
                    .sort_values(['industry', '设备数'], ascending=[True, False]))

    # ---------- 8. 输出 ----------
    print("\n" + "=" * 60)
    print("各行业设备分布 (近5年)")
    print("=" * 60)
    print(summary.to_string(index=False))

    p1 = os.path.join(EXPORT_DIR, 'industry_device_distribution.csv')
    p2 = os.path.join(EXPORT_DIR, 'industry_devicetype_detail.csv')
    summary.to_csv(p1, index=False, encoding='utf-8-sig')
    detail.to_csv(p2, index=False, encoding='utf-8-sig')
    print(f"\n已导出:")
    print(f"  汇总 -> {p1}")
    print(f"  明细 -> {p2}")


if __name__ == '__main__':
    try:
        main()
    except psycopg2.OperationalError as e:
        print(f"\n数据库连接失败 (需内网访问 172.21.1.10): {e}")
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
