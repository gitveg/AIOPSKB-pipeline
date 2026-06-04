"""
一键导出知识库 XLSX。

用法:
  python src/data/power/export_xlsx.py              # 使用代码中指定的版本号
  python src/data/power/export_xlsx.py --version 4  # 命令行覆盖版本号

输出:
  src/data/power/knowledge_base_v{VERSION}.xlsx
"""

import argparse
import json
import os
import subprocess
import sys

# ── 版本号（在此手动修改）──
VERSION = "5.5"

# ── 路径 ──
POWER_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.normpath(os.path.join(POWER_DIR, "..", ".."))
SCRIPTS_DIR = os.path.join(SRC_DIR, "scripts")
MD_TO_JSON = os.path.join(SCRIPTS_DIR, "md_to_json.py")


def run_step1():
    print(f"\n{'='*50}")
    print(f"  Step 1/2: Markdown -> JSON")
    print(f"{'='*50}")
    result = subprocess.run(
        [sys.executable, MD_TO_JSON, POWER_DIR],
        cwd=SRC_DIR,
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"[错误] md_to_json 失败 (exit code {result.returncode})", file=sys.stderr)
        sys.exit(1)


def step2_json_to_xlsx(json_path, xlsx_path):
    print(f"\n{'='*50}")
    print(f"  Step 2/2: JSON -> XLSX")
    print(f"{'='*50}")

    # 直接导入 json_to_csv 的函数，避免生成 CSV
    sys.path.insert(0, SCRIPTS_DIR)
    from json_to_csv import flatten, write_xlsx

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = flatten(data)
    write_xlsx(rows, xlsx_path)

    fault_count = sum(1 for r in rows if r.get("故障名称"))
    print(f"  总行数: {len(rows)} (含故障: {fault_count})", file=sys.stderr)
    print(f"  XLSX: {xlsx_path}", file=sys.stderr)


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="一键导出知识库 XLSX")
    parser.add_argument("--version", "-v", default=VERSION, help="版本号 (默认使用代码中指定的版本)")
    args = parser.parse_args()

    version = args.version
    json_path = os.path.join(POWER_DIR, "knowledge_base.json")
    xlsx_path = os.path.join(POWER_DIR, f"knowledge_base_v{version}.xlsx")

    run_step1()
    step2_json_to_xlsx(json_path, xlsx_path)

    print(f"\n{'='*50}")
    print(f"  导出完成 v{version}")
    print(f"{'='*50}")
    print(f"  {xlsx_path}")
    if os.path.exists(xlsx_path):
        size_mb = os.path.getsize(xlsx_path) / (1024 * 1024)
        print(f"  {size_mb:.1f} MB")
    print()


if __name__ == "__main__":
    main()
