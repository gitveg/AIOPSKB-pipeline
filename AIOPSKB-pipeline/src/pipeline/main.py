import os
import sys
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from orchestrator import Orchestrator
from config import INDUSTRY_CODES


PHASES = ["sub_industry", "equipment", "component", "fault", "validate"]


def main():
    parser = argparse.ArgumentParser(description="工业设备智能运维知识库构建管道")
    parser.add_argument("industry", nargs="?", default="电力",
                        help="行业名称 (如: 电力, 石化, 冶金)")
    parser.add_argument("--phase", "-p", choices=PHASES, required=True,
                        help="要执行的阶段: sub_industry | equipment | component | fault | validate")
    parser.add_argument("--sub", "-s", default=None,
                        help="限定子行业 (如: 火电)。不指定则处理全部子行业")
    parser.add_argument("--equip", "-e", default=None,
                        help="限定设备名 (如: 锅炉)。仅 component/fault 阶段有效")
    parser.add_argument("--equip-type", "-t", default=None,
                        choices=["主设备", "辅助设备", "公用系统"],
                        help="按设备类型筛选 (主设备/辅助设备/公用系统)。仅 component/fault 阶段有效")
    parser.add_argument("--workers", "-w", type=int, default=1,
                        help="并行工作线程数 (默认1=串行，推荐3-5)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="强制重跑，覆盖已有数据（默认跳过已有数据的条目）")
    parser.add_argument("--comp", "-c", default=None,
                        help="限定部件名 (如: 水冷壁)。仅 fault 阶段有效")

    args = parser.parse_args()

    if args.industry not in INDUSTRY_CODES:
        print(f"未知行业: {args.industry}，支持: {list(INDUSTRY_CODES.keys())}")
        sys.exit(1)

    seed_subs = None
    if args.industry == "电力":
        seed_subs = ["火电", "水电", "风电", "核电", "光伏", "输电", "变电", "配电", "储能"]

    orchestrator = Orchestrator(args.industry, seed_subs=seed_subs)

    if args.phase == "sub_industry":
        orchestrator.run_sub_industry()
    elif args.phase == "equipment":
        orchestrator.run_equipment(sub_filter=args.sub)
    elif args.phase == "component":
        orchestrator.run_component(sub_filter=args.sub, equip_filter=args.equip,
                                   equip_type=args.equip_type)
    elif args.phase == "fault":
        orchestrator.run_fault(sub_filter=args.sub, equip_filter=args.equip,
                               comp_filter=args.comp, equip_type=args.equip_type,
                               force=args.force, workers=args.workers)
    elif args.phase == "validate":
        orchestrator.run_validate(sub_filter=args.sub)


if __name__ == "__main__":
    main()
