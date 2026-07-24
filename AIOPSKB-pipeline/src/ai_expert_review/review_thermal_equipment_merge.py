"""
review_thermal_equipment_merge.py — 火电设备清单合并精简评审

一次性脚本：加载 thermal/equipment_registry.md 全量设备（9台冻结标注），
构造合并评审 prompt，两轮辩论（R1各自提方案 / R2看到对方方案后修订），
归档 prompt 与响应到 reviews/thermal_equipment_merge/。

用法：
    cd src/ai_expert_review
    python review_thermal_equipment_merge.py            # 默认 2 轮
    python review_thermal_equipment_merge.py --rounds 1 # 仅 1 轮
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
_PIPELINE_DIR = str(SCRIPT_DIR.parent / "pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from slug_utils import slug_industry, slug_sub  # noqa: E402
from config import DATA_DIR  # noqa: E402
from AI_Expert import (  # noqa: E402
    EXPERT_PROFILES, init_sessions, do_chat, get_expert_config, load_session,
    save_session,
)
from response_parser import parse_expert_response, ResponseParseError  # noqa: E402

# 推理模型（deepseek-v4-pro / kimi-k2.6）reasoning 会吃掉大量 completion token，
# 8192 不够（reasoning 用满后 content 为空）。本次任务输出量大（62台设备分配+描述+理由），
# 提到 16384 给 reasoning + content 都留足空间。
MAX_TOKENS = 16384

REGISTRY_PATH = os.path.join(
    DATA_DIR, slug_industry("电力"), slug_sub("火电"), "equipment_registry.md"
)
OUTPUT_DIR = SCRIPT_DIR / "reviews" / "thermal_equipment_merge"

# 已生成故障数据的 9 台设备（冻结，不参与合并/删除）
# 注：registry 中为"冷却塔"，其已建实现目录为 湿冷塔（180条故障）
FROZEN = {
    "锅炉", "汽轮机", "发电机", "凝汽器",
    "主变压器", "发电机出口断路器", "励磁系统", "空冷岛", "冷却塔",
}

# 本次合并评审的专家角色（贴近"功能域合并/精简"任务）
MERGE_ROLES = {
    "deepseek": (
        "你是一位拥有 30 年火电厂设计、建设与运维经验的资深工程师，熟悉国内主要主机与辅机"
        "制造商、DL/GB 行业标准与 KKS 编码体系。本次评审你的职责是从工程实务角度提出火电"
        "设备清单的合并精简方案：判断哪些细粒度设备属于同一功能系统、结构相似、由同一班组"
        "维护而应合并；哪些是非主流配置而应删除。你会用 KKS 系统码与现场班组组织作为合并"
        "边界的客观锚点，务实严谨，不过度合并也不放过冗余。"
    ),
    "kimi": (
        "你是一位工业知识体系架构师，精通设备分类方法论（ISO 14224、KKS、MECE 原则）。"
        "本次评审你的职责是从知识工程角度提出火电设备清单的合并精简方案：审查合并后大设备"
        "的命名是否规范、功能边界是否清晰不重叠、合并维度是否单一（按功能域而非混维度）、"
        "粒度是否便于后续知识检索与故障诊断。你会关注分类逻辑的一致性与跨行业可复用性。"
    ),
}


def _parse_registry(path):
    """解析 equipment_registry.md，返回 [{name, attr, desc, frozen}]。"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    rows = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|") or re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 3:
            continue
        name = cells[0].strip()
        if name in ("设备类型名称", ""):
            continue
        rows.append({
            "name": name,
            "attr": cells[1],
            "desc": cells[2],
            "frozen": name in FROZEN,
        })
    return rows


def render_device_table(rows):
    """渲染全量设备表（含 ★冻结 标注）。"""
    lines = ["| 设备类型名称 | 设备属性 | 描述 | 状态 |",
             "|---|---|---|---|"]
    for r in rows:
        status = "★已建冻结" if r["frozen"] else ""
        desc = r["desc"] if len(r["desc"]) <= 80 else r["desc"][:78] + "…"
        lines.append(f"| {r['name']} | {r['attr']} | {desc} | {status} |")
    return "\n".join(lines)


def build_r1_prompt(expert_role, data_sections, total):
    with open(SCRIPT_DIR / "prompts" / "equipment_merge_review.md", "r", encoding="utf-8") as f:
        template = f.read()
    return template.format(
        expert_role=expert_role,
        data_sections=data_sections,
        total=total,
    )


def build_r2_prompt(other_name, other_json_str):
    return f"""以下是另一位专家（{other_name}）对同一火电设备合并精简任务的方案：

{other_json_str}

请你：
1. 简要指出你与对方的主要分歧（大设备边界划分、删除项、存疑项）；
2. 在吸纳对方合理观点、坚持自己有依据判断的基础上，**重新输出你修订后的完整 JSON**（结构与第一轮完全一致：overall_score / verdict / summary / merged_devices / kept_standalone / deleted_devices / disputed，且 merged_devices.sub_devices 并集 ∪ kept_standalone ∪ deleted_devices = 全部未冻结设备）。

只输出纯 JSON，不要 markdown 代码块标记和任何表外文字。"""


def _safe_json_str(obj):
    """把解析后的对象或原始文本转为可注入 prompt 的字符串。"""
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return str(obj)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2, help="辩论轮次（默认2）")
    args = ap.parse_args()
    max_rounds = max(1, min(args.rounds, 3))

    rows = _parse_registry(REGISTRY_PATH)
    total = len(rows)
    frozen_n = sum(1 for r in rows if r["frozen"])
    print(f"加载设备清单：共 {total} 台，冻结 {frozen_n} 台，待合并 {total - frozen_n} 台",
          file=sys.stderr)

    data_sections = render_device_table(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    experts = ["deepseek", "kimi"]
    init_sessions(experts, "火电设备清单合并精简评审", custom_roles=MERGE_ROLES)

    # 上一轮解析后的 JSON（或原始文本），用于 R2 交叉注入
    prev = {eid: None for eid in experts}
    final = {}

    for round_num in range(1, max_rounds + 1):
        label = f"R{round_num}/{max_rounds}"
        print(f"\n{'='*50}\n  {label} 开始\n{'='*50}", file=sys.stderr)

        for eid in experts:
            profile = EXPERT_PROFILES[eid]
            role = MERGE_ROLES.get(eid, profile["default_role"])

            if round_num == 1:
                prompt = build_r1_prompt(role, data_sections, total)
            else:
                other_eid = [e for e in experts if e != eid][0]
                other_name = EXPERT_PROFILES[other_eid]["name"]
                prompt = build_r2_prompt(other_name, _safe_json_str(prev[other_eid]))

            with open(OUTPUT_DIR / f"{eid}_prompt_r{round_num}.md", "w", encoding="utf-8") as f:
                f.write(prompt)

            print(f"  正在咨询 {profile['name']} ({label})...", file=sys.stderr)
            try:
                reply = do_chat(eid, prompt, temperature=0.3, max_tokens_override=MAX_TOKENS)
            except Exception as e:
                print(f"  {profile['name']} {label} 调用失败: {e}", file=sys.stderr)
                final[eid] = {"error": str(e)}
                continue

            # 空回复兜底：弹出刚追加的空 assistant 消息，避免毒化下一轮（曾导致 Kimi 400）
            if not reply or not reply.strip():
                print(f"  {profile['name']} {label} 返回空内容（reasoning 吃满 max_tokens），"
                      f"弹出空消息并标记失败", file=sys.stderr)
                sess = load_session(eid)
                if sess and sess["messages"] and sess["messages"][-1]["role"] == "assistant":
                    sess["messages"].pop()  # 空 assistant
                    if sess["messages"][-1]["role"] == "user":
                        sess["messages"].pop()  # 对应 user
                    save_session(eid, sess)
                final[eid] = {"error": "empty_content", "raw_text": ""}
                prev[eid] = None
                with open(OUTPUT_DIR / f"{eid}_response.json", "w", encoding="utf-8") as f:
                    json.dump(final[eid], f, indent=2, ensure_ascii=False, default=str)
                continue

            # 保存原始回复
            with open(OUTPUT_DIR / f"{eid}_raw_r{round_num}.md", "w", encoding="utf-8") as f:
                f.write(reply)

            # 解析 JSON
            try:
                parsed = parse_expert_response(reply)
                prev[eid] = parsed
                final[eid] = parsed
                nd = len(parsed.get("merged_devices", []))
                ns = len(parsed.get("kept_standalone", []))
                ndel = len(parsed.get("deleted_devices", []))
                ndis = len(parsed.get("disputed", []))
                print(f"  {profile['name']} {label}: verdict={parsed.get('verdict','?')} "
                      f"score={parsed.get('overall_score','?')} "
                      f"大设备={nd} 独立={ns} 删除={ndel} 存疑={ndis}", file=sys.stderr)
            except ResponseParseError as e:
                print(f"  {profile['name']} {label} JSON解析失败，重试...", file=sys.stderr)
                retry_ok = False
                try:
                    retry = do_chat(eid, "请只输出纯 JSON，不要其他文字或代码块标记。",
                                    temperature=0.3, max_tokens_override=MAX_TOKENS)
                    parsed = parse_expert_response(retry)
                    prev[eid] = parsed
                    final[eid] = parsed
                    retry_ok = True
                    print(f"  {profile['name']} {label}: 重试解析成功", file=sys.stderr)
                except Exception as e2:
                    print(f"  {profile['name']} {label}: 重试失败 ({type(e2).__name__}: {e2})，"
                          f"保存原始文本", file=sys.stderr)
                if not retry_ok:
                    prev[eid] = reply
                    final[eid] = {"raw_text": reply, "parse_error": True}

            with open(OUTPUT_DIR / f"{eid}_response.json", "w", encoding="utf-8") as f:
                json.dump(final[eid], f, indent=2, ensure_ascii=False, default=str)

    print(f"\n完成。归档目录: {OUTPUT_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
