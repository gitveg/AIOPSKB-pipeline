"""
review_wind_subsystems_compare.py — 风电机组三子设备子系统横向对比评审

一次性脚本：加载三个子设备的 sub_system.md，构造横向对比 prompt，
广播给 DeepSeek + Kimi，解析回复并归档。
"""

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

from slug_utils import slug_industry, slug_sub
from config import DATA_DIR
from AI_Expert import LAYER_EXPERT_ROLES, init_sessions, do_chat, get_expert_config, load_session
from response_parser import parse_expert_response, ResponseParseError

DATA_BASE = os.path.join(DATA_DIR, slug_industry("电力"), slug_sub("风电"), "风电机组")
SUB_DEVICES = [
    "双馈异步风电机组（DFIG）",
    "直驱永磁同步风电机组（PMSG）",
    "半直驱（中速永磁）风电机组",
]
OUTPUT_DIR = SCRIPT_DIR / "reviews" / "wind_subsystem_compare"


def _parse_sub_systems(path):
    """解析 sub_system.md，返回 [{name, desc}]"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    rows = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|") or re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 2:
            continue
        name = cells[0].strip("*").strip()
        if name in ("子系统名称", ""):
            continue
        rows.append({"name": name, "desc": cells[1]})
    return rows


def render_data_sections():
    """渲染三个子设备的子系统数据为对比 markdown。"""
    sections = []
    for sd in SUB_DEVICES:
        path = os.path.join(DATA_BASE, sd, "sub_system.md")
        subs = _parse_sub_systems(path)
        lines = [f"### 子设备：{sd}（{len(subs)} 个子系统）", ""]
        lines.append("| # | 子系统名称 | 描述 |")
        lines.append("|---|-----------|------|")
        for i, s in enumerate(subs, 1):
            lines.append(f"| {i} | {s['name']} | {s['desc']} |")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def main():
    with open(SCRIPT_DIR / "prompts" / "subsystem_compare_review.md", "r", encoding="utf-8") as f:
        template = f.read()

    data_sections = render_data_sections()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    experts = ["deepseek", "kimi"]
    roles = LAYER_EXPERT_ROLES.get("structure", {})

    # 初始化会话（用 structure 角色覆盖旧会话）
    init_sessions(experts, "风电机组三子设备子系统横向对比评审", custom_roles=roles)

    responses = {}
    for eid in experts:
        role = roles.get(eid, "评审专家")
        prompt = template.format(expert_role=role, data_sections=data_sections)

        with open(OUTPUT_DIR / f"{eid}_prompt.md", "w", encoding="utf-8") as f:
            f.write(prompt)

        print(f"  正在咨询 {eid}...", file=sys.stderr)
        try:
            reply = do_chat(eid, prompt, temperature=0.3)
        except Exception as e:
            print(f"  {eid} 失败: {e}", file=sys.stderr)
            responses[eid] = {"error": str(e)}
            continue

        # 读取 session 拿 token 记录
        session = load_session(eid)
        tu = session.get("token_usage", {})
        last_call = tu.get("calls", [{}])[-1] if tu.get("calls") else {}

        try:
            parsed = parse_expert_response(reply)
            responses[eid] = parsed
            print(f"  {eid}: score={parsed.get('overall_score','?')}, "
                  f"verdict={parsed.get('verdict','?')}, "
                  f"issues={len(parsed.get('issues',[]))}", file=sys.stderr)
        except ResponseParseError as e:
            print(f"  {eid} 解析失败，重试中...", file=sys.stderr)
            retry = do_chat(eid, "请只输出纯 JSON，不要其他文字。", temperature=0.3)
            try:
                parsed = parse_expert_response(retry)
                responses[eid] = parsed
                print(f"  {eid}: 重试成功", file=sys.stderr)
            except ResponseParseError:
                responses[eid] = {"raw_text": reply, "parse_error": True}
                print(f"  {eid}: 重试仍失败", file=sys.stderr)

        with open(OUTPUT_DIR / f"{eid}_response.json", "w", encoding="utf-8") as f:
            json.dump(responses[eid], f, indent=2, ensure_ascii=False, default=str)

    print(f"\n完成。归档目录: {OUTPUT_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
