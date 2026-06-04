"""
知识库构建进度追踪脚本。

自动扫描目录结构，统计各子行业在每个阶段的完成情况，
输出 CSV 到 src/data/power/construct_progress.csv。

用法:
  python src/scripts/track_progress.py              # 更新CSV并打印汇总表
  python src/scripts/track_progress.py --no-csv     # 仅打印汇总表，不写CSV
"""

import csv
import glob
import os
import sys


POWER_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "power"
))

# 阶段状态标签
DONE = "✅"
REVIEWED = "✅ 已评审"
PARTIAL = "⚠️ 部分"
PENDING = "—"
NOT_STARTED = "—"

# 不算子行业的目录
SKIP_DIRS = {"_archive", "kb_exports"}

# 子行业中文→英文slug映射（用于排序）
SUB_ORDER = [
    "thermal", "hydro", "wind", "nuclear", "pv",
    "transmission", "substation", "distribution",
    "energy_storage",
]

# slug→中文名
CN_NAMES = {
    "thermal": "火电", "hydro": "水电", "wind": "风电",
    "nuclear": "核电", "pv": "光伏", "transmission": "输电",
    "substation": "变电", "distribution": "配电",
    "energy_storage": "储能",
}


def parse_table(filepath):
    """解析MD表格，返回行列表。"""
    if not os.path.exists(filepath):
        return []
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            if line.startswith("|--") or line.startswith("| ---"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not cells:
                continue
            # 跳过表头行（含"名称"或"部件名称"等关键词）
            if cells[0] in ("设备名称", "部件名称", "子行业名称", "子设备名称"):
                continue
            rows.append(cells)
    return rows


def count_equipment(sub_dir):
    """统计设备层信息。"""
    reg_path = os.path.join(sub_dir, "equipment_registry.md")
    rows = parse_table(reg_path)
    main = sum(1 for r in rows if len(r) >= 2 and "主设备" in r[1])
    aux = sum(1 for r in rows if len(r) >= 2 and "辅助" in r[1])
    pub = sum(1 for r in rows if len(r) >= 2 and "公用" in r[1])
    total = len(rows)
    return total, main, aux, pub


def count_components_and_faults(sub_dir):
    """统计部件层和故障层信息。"""
    eq_dirs = []
    comp_done = 0
    comp_rows = 0
    fault_done = 0
    fault_rows = 0

    for item in sorted(os.listdir(sub_dir)):
        item_path = os.path.join(sub_dir, item)
        if not os.path.isdir(item_path):
            continue
        eq_dirs.append(item)

        # 部件统计：设备级 components.md（无子设备时）
        comp_path = os.path.join(item_path, "components.md")
        if os.path.exists(comp_path):
            rows = parse_table(comp_path)
            if rows:
                comp_done += 1
                comp_rows += len(rows)

        # 故障统计：设备级 faults/（无子设备时）
        faults_dir = os.path.join(item_path, "faults")
        if os.path.isdir(faults_dir):
            fault_files = glob.glob(os.path.join(faults_dir, "*.md"))
            f_rows = 0
            for ff in fault_files:
                f_rows += len(parse_table(ff))
            if f_rows > 0:
                fault_done += 1
                fault_rows += f_rows

        # 子设备级统计：遍历子设备子目录
        for sub_item in sorted(os.listdir(item_path)):
            sub_path = os.path.join(item_path, sub_item)
            if not os.path.isdir(sub_path):
                continue
            if sub_item in ("_archive", "faults", "kb_exports"):
                continue
            # 检查是否为子设备目录（含 components.md 或 faults/）
            sub_comp = os.path.join(sub_path, "components.md")
            if os.path.exists(sub_comp):
                rows = parse_table(sub_comp)
                if rows:
                    comp_done += 1
                    comp_rows += len(rows)
            sub_faults = os.path.join(sub_path, "faults")
            if os.path.isdir(sub_faults):
                fault_files = glob.glob(os.path.join(sub_faults, "*.md"))
                f_rows = 0
                for ff in fault_files:
                    f_rows += len(parse_table(ff))
                if f_rows > 0:
                    fault_done += 1
                    fault_rows += f_rows

    return len(eq_dirs), comp_done, comp_rows, fault_done, fault_rows


def stage2_status(total, main):
    if total == 0:
        return NOT_STARTED
    if main > 0:
        return DONE
    return PENDING


def stage3_status(eq_total, comp_done):
    if eq_total == 0:
        return NOT_STARTED
    if comp_done == 0:
        return NOT_STARTED
    if comp_done >= eq_total:
        return DONE
    return PARTIAL


def stage4_status(comp_done, fault_done):
    if comp_done == 0:
        return NOT_STARTED
    if fault_done == 0:
        return NOT_STARTED
    if fault_done >= comp_done:
        return DONE
    return PARTIAL


def scan_all():
    """扫描所有子行业，返回进度数据列表。"""
    results = []

    # 获取所有子行业目录
    all_dirs = []
    for d in sorted(os.listdir(POWER_DIR)):
        dpath = os.path.join(POWER_DIR, d)
        if not os.path.isdir(dpath):
            continue
        if d in SKIP_DIRS or d.startswith("."):
            continue
        if d == "kb_exports":
            continue
        all_dirs.append(d)

    # 按预定义顺序排，未知的放后面
    ordered = []
    for slug in SUB_ORDER:
        if slug in all_dirs:
            ordered.append(slug)
    for d in all_dirs:
        if d not in ordered:
            ordered.append(d)

    for slug in ordered:
        sub_dir = os.path.join(POWER_DIR, slug)
        cn_name = CN_NAMES.get(slug, slug)

        # 阶段1：子行业划分（电力行业已完成，所有子行业都有index.md条目）
        s1 = DONE

        # 阶段2：设备枚举
        eq_total, main, aux, pub = count_equipment(sub_dir)
        s2 = stage2_status(eq_total, main)

        # 阶段3：部件拆解 & 阶段4：故障知识
        eq_dirs, comp_done, comp_rows, fault_done, fault_rows = \
            count_components_and_faults(sub_dir)
        s3 = stage3_status(eq_dirs, comp_done)
        s4 = stage4_status(comp_done, fault_done)

        # 阶段5：索引验证
        s5 = NOT_STARTED

        results.append({
            "子行业": cn_name,
            "slug": slug,
            "阶段1_子行业划分": s1,
            "阶段2_主设备": main,
            "阶段2_辅助设备": aux,
            "阶段2_公用系统": pub,
            "阶段2_合计": eq_total,
            "阶段2_状态": s2,
            "阶段3_设备目录数": eq_dirs,
            "阶段3_已有部件": comp_done,
            "阶段3_部件条目": comp_rows,
            "阶段3_状态": s3,
            "阶段4_有故障的设备": fault_done,
            "阶段4_故障条目": fault_rows,
            "阶段4_状态": s4,
            "阶段5_索引验证": s5,
        })

    return results


CSV_COLUMNS = [
    "子行业", "slug",
    "阶段1_子行业划分",
    "阶段2_主设备", "阶段2_辅助设备", "阶段2_公用系统", "阶段2_合计", "阶段2_状态",
    "阶段3_设备目录数", "阶段3_已有部件", "阶段3_部件条目", "阶段3_状态",
    "阶段4_有故障的设备", "阶段4_故障条目", "阶段4_状态",
    "阶段5_索引验证",
]


def write_csv(results, csv_path):
    """写入CSV文件。"""
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})


def print_table(results):
    """打印汇总表到终端。"""
    # 表头
    hdr = (
        f"{'子行业':<12} "
        f"{'阶段2':^20} "
        f"{'阶段3':^16} "
        f"{'阶段4':^16} "
        f"{'阶段5':^6}"
    )
    sep = "─" * 80

    print(f"\n{'='*80}")
    print(f"  电力行业知识库构建进度")
    print(f"{'='*80}\n")

    print(f"{'子行业':<10} │ {'主':>3} {'辅':>3} {'公':>3} {'计':>4} │"
          f" {'部件设备':>6} {'部件行':>6} │"
          f" {'故障设备':>6} {'故障行':>6} │"
          f" {'S2':^4} {'S3':^4} {'S4':^4} {'S5':^4}")
    print("─" * 75)

    sum_main = sum_aux = sum_pub = sum_eq = 0
    sum_comp_dirs = sum_comp_rows = sum_fault_dirs = sum_fault_rows = 0

    for r in results:
        name = r["子行业"]
        m, a, p, t = r["阶段2_主设备"], r["阶段2_辅助设备"], r["阶段2_公用系统"], r["阶段2_合计"]
        cd = r["阶段3_已有部件"]
        cr = r["阶段3_部件条目"]
        fd = r["阶段4_有故障的设备"]
        fr = r["阶段4_故障条目"]
        s2 = "✅" if t > 0 else "—"
        s3 = r["阶段3_状态"]
        s4 = r["阶段4_状态"]
        s5 = r["阶段5_索引验证"]

        # 缩短状态标签
        s3 = s3.replace("✅", "✅").replace("⚠️ 部分", "⚠️").replace("—", "—")
        s4 = s4.replace("✅", "✅").replace("⚠️ 部分", "⚠️").replace("—", "—")

        print(f"{name:<10} │ {m:>3} {a:>3} {p:>3} {t:>4} │"
              f" {cd:>6} {cr:>6} │"
              f" {fd:>6} {fr:>6} │"
              f" {s2:^4} {s3:^4} {s4:^4} {s5:^4}")

        sum_main += m
        sum_aux += a
        sum_pub += p
        sum_eq += t
        sum_comp_dirs += cd
        sum_comp_rows += cr
        sum_fault_dirs += fd
        sum_fault_rows += fr

    print("─" * 75)
    print(f"{'合计':<10} │ {sum_main:>3} {sum_aux:>3} {sum_pub:>3} {sum_eq:>4} │"
          f" {sum_comp_dirs:>6} {sum_comp_rows:>6} │"
          f" {sum_fault_dirs:>6} {sum_fault_rows:>6} │")
    print()


def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    write_csv_flag = "--no-csv" not in sys.argv

    results = scan_all()

    if write_csv_flag:
        csv_path = os.path.join(POWER_DIR, "construct_progress.csv")
        write_csv(results, csv_path)
        print(f"CSV 已更新: {csv_path}", file=sys.stderr)

    print_table(results)


if __name__ == "__main__":
    main()
