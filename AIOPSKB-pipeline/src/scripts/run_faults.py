"""
火电 + 水电主设备故障知识重跑脚本

用法（在 src 目录下执行）：
    cd src
    python scripts/run_faults.py
    python scripts/run_faults.py --workers 5
    python scripts/run_faults.py --only 火电
    python scripts/run_faults.py --only 水电
"""

import os
import sys
import time

# 确保 src 目录在 path 中
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, src_dir)
sys.path.insert(0, os.path.join(src_dir, "pipeline"))
os.chdir(src_dir)

# 修复 Windows 中文输出
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from pipeline.orchestrator import Orchestrator

WORKERS = 5
SEED_SUBS = ["火电", "水电", "风电", "核电", "光伏", "输电", "变电", "配电", "储能"]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="火电+水电主设备故障重跑")
    parser.add_argument("--workers", "-w", type=int, default=WORKERS,
                        help=f"并行线程数 (默认{WORKERS})")
    parser.add_argument("--only", choices=["火电", "水电"], default=None,
                        help="只跑火电或水电 (默认两个都跑)")
    args = parser.parse_args()

    orchestrator = Orchestrator("电力", seed_subs=SEED_SUBS)

    tasks = []
    if args.only in (None, "火电"):
        tasks.append(("火电", "thermal"))
    if args.only in (None, "水电"):
        tasks.append(("水电", "hydro"))

    total_start = time.time()

    for sub_cn, _ in tasks:
        print(f"\n{'='*60}")
        print(f"  开始: {sub_cn} 主设备故障知识 (--workers {args.workers}, 增量模式)")
        print(f"{'='*60}\n")

        start = time.time()
        orchestrator.run_fault(
            sub_filter=sub_cn,
            equip_type="主设备",
            force=True,
            workers=args.workers,
        )
        elapsed = time.time() - start
        print(f"\n  {sub_cn} 完成，耗时 {elapsed/3600:.1f} 小时")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  全部完成，总耗时 {total_elapsed/3600:.1f} 小时")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
