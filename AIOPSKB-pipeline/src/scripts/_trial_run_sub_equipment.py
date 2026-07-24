"""
改造4 试跑脚本：跑【完整 _run_layer 流程】生成指定设备的子设备划分。

用法:
  python src/scripts/_trial_run_sub_equipment.py [full|raw] [子行业] [设备]
默认: full 风电 风电机组

- 风电机组：硬对比人工验证的标准答案（DFIG/PMSG/半直驱）
- 锅炉等其他设备：软参考模式（无硬标准，看 LLM 独立裁剪 + judge 把关，人工评判）
"""
import sys
import os
import re

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJ = r"C:\Users\900009684\Desktop\AIOpsKB\AIOPSKB-pipeline"
os.chdir(PROJ)
sys.path.insert(0, os.path.join(PROJ, "src", "pipeline"))

from orchestrator import Orchestrator
from agents.collector import collect_layer

# 参考库：equip → {mainstream, niche, note, hard_compare}
REFERENCE = {
    "风电机组": {
        "mainstream": ["双馈", "DFIG", "直驱", "PMSG", "半直驱"],
        "niche": ["高速永磁", "异步双馈混合", "电励磁", "EESG", "液压传动", "无刷双馈", "鼠笼", "SCIG"],
        "note": "人工验证的标准答案（DFIG/PMSG/半直驱）",
        "hard_compare": True,
    },
    "锅炉": {
        "mainstream": ["煤粉", "PC", "循环流化床", "CFB", "流化床", "余热", "HRSG"],
        "niche": [],  # 锅炉未经验证，不预设小众清单
        "note": "行业常识参考（煤粉炉/CFB/余热锅炉），非硬标准——锅炉未经人工验证，仅供评判 LLM 独立裁剪是否合理",
        "hard_compare": False,
    },
}


def extract_names(md_text: str) -> list:
    names = []
    for line in md_text.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r'^\|[\s\-:|]+$', line):
            continue
        cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
        if cells and cells[0] not in ("子设备名称", ""):
            names.append(cells[0])
    return names


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    sub = sys.argv[2] if len(sys.argv) > 2 else "风电"
    equip = sys.argv[3] if len(sys.argv) > 3 else "风电机组"

    CONTEXT = {"industry": "电力", "sub_industry": sub, "equipment": equip}
    ref = REFERENCE.get(equip, {"mainstream": [], "niche": [], "note": "无参考，纯看 LLM 独立产出", "hard_compare": False})

    print("=" * 70)
    print(f"改造4 试跑：{sub}/{equip} 子设备划分（模式: {mode}）")
    print(f"参考说明: {ref['note']}")
    print("=" * 70)

    if mode == "raw":
        print("\n[单次裸 collect_layer]")
        result, _ = collect_layer("sub_equipment", CONTEXT)
        print("\n--- LLM 单次输出 ---")
        print(result)
        final = result
    else:
        print("\n[完整 _run_layer 流程：扩充→judge→整合]")
        orch = Orchestrator("电力")
        tmp_out = os.path.join(PROJ, "src", "scripts", "_trial_sub_equipment_output.md")
        final, _, _ = orch._run_layer("sub_equipment", CONTEXT.copy(), tmp_out)
        print("\n" + "=" * 70)
        print(f"=== 最终 {equip} 子设备划分（完整流程后）===")
        print("=" * 70)
        print(final)

    names = extract_names(final)
    print("\n" + "=" * 70)
    print("=== 结果分析 ===")
    print("=" * 70)
    print(f"提取到 {len(names)} 个子设备:")
    for n in names:
        print(f"    - {n}")

    joined = " ".join(names)
    hit_main = [k for k in ref["mainstream"] if k in joined]
    hit_niche = [k for k in ref["niche"] if k in joined]

    if ref["hard_compare"]:
        has_dfig = any(k in joined for k in ["双馈", "DFIG"])
        has_pmsg = any(k in joined for k in ["直驱", "PMSG"])
        has_semi = "半直驱" in joined
        print(f"\n主流覆盖: 双馈={has_dfig}  直驱={has_pmsg}  半直驱={has_semi}")
        print(f"误含小众: {hit_niche or '无'}")
        if has_dfig and has_pmsg and has_semi and not hit_niche:
            print(">>> 与标准答案一致（3 主流全覆盖、无小众）")
        else:
            print(">>> 与标准答案有偏差")
    else:
        print(f"\n[软参考] 行业常识主流关键词: {ref['mainstream']}")
        print(f"[软参考] LLM 命中: {hit_main}")
        print(f"[软参考] LLM 未命中: {[k for k in ref['mainstream'] if k not in joined]}")
        print(f"\n>>> {equip} 未经人工验证，无硬标准答案。请人工评判：")
        print("    1) 子设备是否覆盖了主流技术路线（煤粉炉/CFB 等）？")
        print("    2) 是否混入了小众/试验性机型，或混维度（如把'超临界'这种参数等级当子设备）？")
        print("    3) 数量是否克制（2-4 个），有没有为凑数注水？")


if __name__ == "__main__":
    main()
