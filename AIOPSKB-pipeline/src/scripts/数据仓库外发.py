"""
数据仓库——大表、小表获取
"""
import math
import json
import pickle
import time
import os
import datetime
import pandas as pd
import numpy as np
import math
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor





class DataWarehouse:
    """
    数据仓库——大表、小表获取;
    本次实现大表部分、并核查正确性；
    """

    def __init__(self):

        # PHM PG库配置 测试'192.168.0.114',
        self.pg_paras = {
            'host': '172.21.1.10',
            'port': '5432',
            'user': 'postgres',
            'password': 'Postgres_Rozh123srv',
            'database': 'alg_analysis'
        }

    def get_taurus_alarm(self,version, start_date, end_date):
        # input("起始时间 YYYY/MM/DD HH:MM:SS :")
        # start_date = (datetime.datetime.now() - datetime.timedelta(day_num)).strftime("%Y-%m-%d").replace('-','/') + ' 00:00:00'
        # input("结束时间 YYYY/MM/DD HH:MM:SS :")
        # end_date = time.strftime('%Y-%m-%d', time.localtime()).replace('-','/') + ' 23:59:59'
        # start_date = '\'' + start_date + '\''
        # end_date = '\'' + end_date + '\''

        # 根据不同版本获取不同的报警表
        if version == 'A':
            # A版报警
            sheet = "diag_alarm_confirm_a"
        elif version == 'B':
            # B版报警
            sheet = "diag_alarm_confirm_b"
        elif version == 'detail':
            # 报警详情
            sheet = "diag_alarm_confirm_detail"
        elif version == 'fault':  # fiz: 故障报警  and processstatus = 1
            # 故障报警
            sheet = "diag_fault_alarm"
        elif version == 'abnormal':
            # 异常记录
            sheet = "diag_abnormal_records"
        elif version == 'case':
            # 故障案例
            sheet = "diag_fault_case"
        elif version == 'enterprise':
            # 企业信息
            sheet = "stat_enterprise_info"
        elif version == 'device':
            # 设备信息
            sheet = "stat_device_info"
        elif version == 'record':
            # 诊断记录
            sheet = "stat_diagnosis_record"
        elif version == 'point':
            # 工况测点的设备清单表
            sheet = "business_device_condition_point"
        elif version == 'device_image':
            # 设备图片表
            sheet = "business_device_image"
        elif version == 'device_screenshot':
            # 设备截图表
            sheet = "business_device_screenshot"
        elif version == 'record_screenshot':
            # 诊断记录截图表
            sheet = "business_record_screenshot"
        elif version == 'tools_enum_info':
            # 枚举字典映射表
            sheet = "tools_enum_info"
        else:
            raise ValueError(f"Unknown version: {version}")

        # sql = "select * from " + sheet
        sql = "select * from " + sheet + " where creationtime between " + start_date + " and " + end_date + " order by creationtime"
        # sql = "select * from " + sheet + " where measdatatime between" + start_date + "and" + end_date + " order by measdatatime"
        # sql = "select * from " + sheet + " where creationtime between " + start_date + " and " + end_date + ' and assettype=40 ' + " order by creationtime"
        # where creationtime >= '2024/11/01'

        # sql = "select * from diag_alarm_confirm_a where deviceid = '3A16D196-954B-21C7-29E1-1AE620AB43B6' and creationtime between '2025-02-14 11:47:54' and '2025-02-16 11:47:54'"
        # sql = "select * from tools_enum_info"

        # sql = """
        # select * from diag_abnormal_records where enterprisecode = 'RZGTJC' and creationtime between '2025-01-28 19:57:31' and '2025-02-28 19:57:31'
        # """
        # 'select * from diag_alarm_confirm_a where devicename = '2#水处理P101-3软水泵''
        # sql = """
        # select * from diag_fault_case where enterprisecode = 'RZGTJC' and creationtime between '2001-03-10 11:47:54' and '2025-03-10 11:47:54'
        # """


        connect = psycopg2.connect(**self.pg_paras)


        if connect:
            print("连接成功!")
            cursor = connect.cursor(cursor_factory=RealDictCursor)
            cursor.execute(sql)
            result = cursor.fetchall()
            connect.close()
            cursor.close()
            taurus_alarm = pd.DataFrame(result)
            return taurus_alarm
        raise LookupError('ERROR:连接失败!')


    @staticmethod
    def device_statistics():
        """
        针对设备变化进行统计
        :return:
        """

    @staticmethod
    # 字符串——datetime转换
    def string_toDatetime(string):
        if 'T' in string:
            rst = datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M:%S")
        else:
            rst = datetime.datetime.strptime(string, "%Y-%m-%d %H:%M:%S")
        return rst

    @staticmethod
    # datetime——matlab datenum转换
    def datetime2matlabdn(dt):
        mdn = dt + datetime.timedelta(days=366)
        frac = (dt - datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0)).seconds / (24.0 * 60.0 * 60.0)
        return mdn.toordinal() + frac

    @staticmethod
    # matlab datenum——datetime转换
    def matlabdn2datetime(dt: float):
        if math.isnan(dt):
            return float('NaN')
        d_int = int(math.floor(dt))
        d_frac = dt - d_int
        dt_out = datetime.datetime.fromordinal(d_int - 366) + datetime.timedelta(seconds=round(d_frac * 24 * 3600, 0))
        return dt_out




def truncate_df(df, n_head=3, n_tail=3):
    if len(df) > n_head + n_tail:
        head = df.head(n_head)
        tail = df.tail(n_tail)
        # 创建一行，用 ... 表示
        ellipsis = pd.DataFrame([["..."] * len(df.columns)], columns=df.columns)
        ellipsis.index = ["..."]
        return pd.concat([head, ellipsis, tail], ignore_index=False)
    else:
        return df



if __name__ == '__main__':

    # ============================================================
    # 导出知识库改造所需的关键表到本地 CSV
    # 用途：对齐 failure_categories.yaml 与公司监测平台枚举
    # ============================================================

    import sys
    import io

    # Windows 控制台 UTF-8 输出
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # 输出目录
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    EXPORT_DIR = os.path.join(SCRIPT_DIR, 'db_export')
    os.makedirs(EXPORT_DIR, exist_ok=True)

    dw = DataWarehouse()

    def export_table(name, sql, filename):
        """通用导出函数"""
        print(f"\n[{name}] 查询中...")
        try:
            conn = psycopg2.connect(**dw.pg_paras)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql)
            rows = cur.fetchall()
            df = pd.DataFrame(rows)
            out = os.path.join(EXPORT_DIR, filename)
            df.to_csv(out, index=False, encoding='utf-8-sig')
            print(f"  OK | {len(df)} rows -> {filename}")
            print(f"  columns: {list(df.columns)}")
            # 打印前3行预览
            if len(df) > 0:
                for i, row in df.head(3).iterrows():
                    preview = {k: str(v)[:60] for k, v in row.items()}
                    print(f"  [{i}] {preview}")
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"  FAIL | {e}")
            return False

    print("=" * 60)
    print("数据库导出开始")

    # 1. 枚举字典映射表（最关键，全量导出）
    export_table("1/5 tools_enum_info",
                 "SELECT * FROM tools_enum_info",
                 "tools_enum_info.csv")

    # 2. 设备信息表
    export_table("2/5 stat_device_info",
                 """SELECT deviceid, devicename, devicetype, assettype,
                           enterprisecode, creationtime
                    FROM stat_device_info
                    ORDER BY creationtime DESC LIMIT 5000""",
                 "stat_device_info.csv")

    # 3. 故障报警表
    export_table("3/5 diag_fault_alarm",
                 """SELECT * FROM diag_fault_alarm
                    ORDER BY creationtime DESC LIMIT 5000""",
                 "diag_fault_alarm.csv")

    # 4. 故障案例表
    export_table("4/5 diag_fault_case",
                 """SELECT * FROM diag_fault_case
                    ORDER BY creationtime DESC LIMIT 1000""",
                 "diag_fault_case.csv")

    # 5. 工况测点设备清单表
    export_table("5/5 business_device_condition_point",
                 """SELECT * FROM business_device_condition_point
                    ORDER BY creationtime DESC LIMIT 5000""",
                 "business_device_condition_point.csv")

    # 汇总
    print("\n" + "=" * 60)
    print(f"导出目录: {EXPORT_DIR}")
    if os.path.exists(EXPORT_DIR):
        for f in sorted(os.listdir(EXPORT_DIR)):
            fpath = os.path.join(EXPORT_DIR, f)
            size_kb = os.path.getsize(fpath) / 1024
            print(f"  {f}  ({size_kb:.1f} KB)")
    else:
        print("  (目录不存在，导出可能全部失败)")
    print("完成!")




