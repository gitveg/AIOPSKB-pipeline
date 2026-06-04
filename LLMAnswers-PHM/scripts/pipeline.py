"""
PHM 知识库多智能体 Pipeline — 主入口

用法（从项目根目录运行）：
  python scripts/pipeline.py --build          # 构建/重建知识库（v10 种子 → v11）
  python scripts/pipeline.py --evaluate       # 评估最新版本
  python scripts/pipeline.py --refine         # 根据评估改进最新版本
  python scripts/pipeline.py --full           # 完整流程：build → evaluate → refine
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 确保 scripts/ 在 import 路径中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.base import OUTLINES_DIR, REVIEWS_DIR, DATA_DIR
from agents.collector import CollectorAgent
from agents.builder import BuilderAgent
from agents.evaluator import EvaluatorAgent
from models.schema import KnowledgeBase, Industry
from models.markdown_io import (
    extract_v10_seeds, write_kb_md, write_kb_json, write_kb_csv,
)

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Build 阶段
# ---------------------------------------------------------------------------

# 8 个行业定义（与 v10 一致，可扩展）
INDUSTRIES = [
    {"编号": "2", "名称": "电力行业"},
    {"编号": "3", "名称": "石化行业"},
    {"编号": "4", "名称": "冶金行业"},
    {"编号": "5", "名称": "水泥行业"},
    {"编号": "6", "名称": "煤炭行业"},
    {"编号": "7", "名称": "轨道交通"},
    {"编号": "8", "名称": "制造业"},
    {"编号": "9", "名称": "航空航天与船舶"},
]


def build_phase(start_version: int = 10) -> int:
    """构建知识库。从 v10 提取种子，生成 v{start_version+1}。

    Returns:
        新版本号
    """
    new_version = start_version + 1
    logger.info("=" * 60)
    logger.info("Build 阶段启动: v%d → v%d", start_version, new_version)
    logger.info("=" * 60)

    # Step 1: 提取 v10 种子
    v10_path = OUTLINES_DIR / f"Merged_PHM_TOC_v{start_version}.md"
    if not v10_path.is_file():
        logger.error("未找到 v%d: %s", start_version, v10_path)
        sys.exit(1)

    seeds = extract_v10_seeds(v10_path)
    logger.info("从 v%d 提取了 %d 个设备的种子数据", start_version, len(seeds))

    # 按行业分组种子
    seeds_by_industry: dict[str, list[dict]] = {}
    for s in seeds:
        ind = s["industry"]
        seeds_by_industry.setdefault(ind, []).append(s)

    # Step 2: 初始化智能体
    collector = CollectorAgent()
    builder = BuilderAgent()

    # Step 3: 逐行业构建
    kb = KnowledgeBase()

    for ind_def in INDUSTRIES:
        ind_name = ind_def["名称"]
        ind_no = ind_def["编号"]

        logger.info("-" * 40)
        logger.info("处理行业: %s (%s)", ind_name, ind_no)
        logger.info("-" * 40)

        industry = Industry(编号=ind_no, 名称=ind_name)

        # 获取该行业的种子设备名
        industry_seeds = seeds_by_industry.get(ind_name, [])
        seed_names = [s["equipment"] for s in industry_seeds]
        seed_comp_map = {s["equipment"]: s["components"] for s in industry_seeds}

        # 3a. 枚举设备
        equipment_list = collector.enumerate_equipment(
            industry_name=ind_name,
            seed_names=seed_names,
        )

        # 3b. 逐设备构建
        for eq_idx, eq_seed in enumerate(equipment_list, 1):
            eq_name = eq_seed.get("name", f"设备{eq_idx}")
            # 附加种子部件信息
            if eq_name in seed_comp_map:
                eq_seed["seed_components"] = seed_comp_map[eq_name]

            try:
                equipment = builder.build_equipment(
                    equipment_seed=eq_seed,
                    industry_name=ind_name,
                    industry_no=ind_no,
                    equipment_idx=eq_idx,
                )
                industry.设备列表.append(equipment)
                logger.info("  设备 %s 完成: %d 部件", equipment.名称, len(equipment.部件列表))
            except Exception as exc:
                logger.error("  设备 %s 构建失败: %s", eq_name, exc)
                continue

        kb.industries.append(industry)
        logger.info("行业 %s 完成: %d 设备", ind_name, len(industry.设备列表))

    # Step 4: 写入输出
    stats = kb.count_stats()
    logger.info("构建完成: %s", json.dumps(stats, ensure_ascii=False))

    # 确保目录存在
    OUTLINES_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Markdown
    md_path = OUTLINES_DIR / f"KB_v{new_version}.md"
    header = (
        f"# PHM 知识库 — 行业·设备·部件·故障\n"
        f"\n"
        f"> 构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"> 基于版本: v{start_version}（种子提取）\n"
        f"> 统计: {stats['行业数']} 行业 / {stats['设备数']} 设备 / "
        f"{stats['部件数']} 部件 / {stats['故障数']} 故障\n"
        f"\n"
        f"---\n\n"
    )
    md_content = header
    # 写入临时文件再读取
    write_kb_md(kb, md_path)
    raw_md = md_path.read_text(encoding="utf-8")
    md_path.write_text(md_content + raw_md, encoding="utf-8", newline="\n")
    logger.info("Markdown 已写入: %s", md_path)

    # JSON
    json_path = DATA_DIR / f"KB_v{new_version}.json"
    write_kb_json(kb, json_path)
    logger.info("JSON 已写入: %s", json_path)

    # CSV
    csv_path = DATA_DIR / f"KB_v{new_version}.csv"
    write_kb_csv(kb, csv_path)
    logger.info("CSV 已写入: %s", csv_path)

    logger.info("=" * 60)
    logger.info("Build 完成！版本: v%d", new_version)
    logger.info("=" * 60)

    return new_version


# ---------------------------------------------------------------------------
# Evaluate 阶段
# ---------------------------------------------------------------------------

def evaluate_phase(version: int | None = None) -> Path:
    """评估指定版本的知识库。"""
    if version is None:
        # 自动检测最新 KB 版本
        version = _detect_latest_kb_version()
        if version == 0:
            logger.error("未找到任何 KB 版本，请先运行 --build")
            sys.exit(1)

    kb_path = OUTLINES_DIR / f"KB_v{version}.md"
    if not kb_path.is_file():
        logger.error("未找到 KB v%d: %s", version, kb_path)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Evaluate 阶段启动: v%d", version)
    logger.info("=" * 60)

    evaluator = EvaluatorAgent()
    report = evaluator.evaluate_kb(str(kb_path))

    # 写入评估报告
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REVIEWS_DIR / f"Evaluation_v{version}.md"
    header = (
        f"# PHM 知识库可用性评估报告 — v{version}\n"
        f"\n"
        f"> 评估时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"> 评估对象: KB_v{version}.md\n"
        f"\n"
        f"---\n\n"
    )
    report_path.write_text(header + report, encoding="utf-8", newline="\n")
    logger.info("评估报告已写入: %s", report_path)

    logger.info("=" * 60)
    logger.info("Evaluate 完成！")
    logger.info("提示: 运行 --refine 可基于此报告改进")
    logger.info("=" * 60)

    return report_path


# ---------------------------------------------------------------------------
# Refine 阶段
# ---------------------------------------------------------------------------

def refine_phase(version: int | None = None) -> int:
    """根据评估报告改进知识库。"""
    if version is None:
        version = _detect_latest_kb_version()

    new_version = version + 1

    kb_path = OUTLINES_DIR / f"KB_v{version}.md"
    report_path = REVIEWS_DIR / f"Evaluation_v{version}.md"
    json_path = DATA_DIR / f"KB_v{version}.json"

    if not report_path.is_file():
        logger.error("未找到 v%d 的评估报告: %s，请先运行 --evaluate", version, report_path)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Refine 阶段启动: v%d → v%d", version, new_version)
    logger.info("=" * 60)

    # 读取评估报告
    report = report_path.read_text(encoding="utf-8", errors="replace")

    # 读取知识库
    builder = BuilderAgent()
    if json_path.is_file():
        kb = KnowledgeBase.model_validate_json(json_path.read_text(encoding="utf-8"))
    else:
        logger.error("未找到 JSON 数据: %s", json_path)
        sys.exit(1)

    # 改进
    kb = builder.refine_from_feedback(kb, report)

    # 写入新版本
    stats = kb.count_stats()
    logger.info("改进完成: %s", json.dumps(stats, ensure_ascii=False))

    write_kb_md(kb, OUTLINES_DIR / f"KB_v{new_version}.md")
    write_kb_json(kb, DATA_DIR / f"KB_v{new_version}.json")
    write_kb_csv(kb, DATA_DIR / f"KB_v{new_version}.csv")

    logger.info("=" * 60)
    logger.info("Refine 完成！v%d → v%d", version, new_version)
    logger.info("=" * 60)

    return new_version


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _detect_latest_kb_version() -> int:
    """检测最新的 KB 版本号。"""
    max_ver = 0
    for fp in OUTLINES_DIR.glob("KB_v*.md"):
        import re
        m = re.match(r"KB_v(\d+)\.md", fp.name)
        if m:
            max_ver = max(max_ver, int(m.group(1)))
    return max_ver


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PHM 知识库多智能体 Pipeline")
    parser.add_argument("--build", action="store_true", help="构建/重建知识库")
    parser.add_argument("--evaluate", action="store_true", help="评估最新版本")
    parser.add_argument("--refine", action="store_true", help="根据评估改进最新版本")
    parser.add_argument("--full", action="store_true", help="完整流程：build → evaluate → refine")
    parser.add_argument("--start_version", type=int, default=10, help="build 的起始版本号（默认 10）")
    parser.add_argument("--version", type=int, default=None, help="指定 evaluate/refine 的版本号")
    args = parser.parse_args()

    if args.full:
        v = build_phase(args.start_version)
        evaluate_phase(v)
        refine_phase(v)
        return

    if args.build:
        build_phase(args.start_version)
        return

    if args.evaluate:
        evaluate_phase(args.version)
        return

    if args.refine:
        refine_phase(args.version)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
