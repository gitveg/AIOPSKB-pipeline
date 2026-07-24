"""
report_generator.py — 评审报告生成器

根据专家回复和辩论日志生成 markdown 评审报告。
参照 reviews/thermal_main_equipment/评审报告.md 的四段式格式。
"""

import json
import os
from datetime import datetime


def generate_report(layer, context, debate_log, expert_responses,
                     token_summary, output_dir, focus="all"):
    """生成评审报告和归档文件。

    输出文件：
        - {output_dir}/评审报告.md
        - {output_dir}/deepseek_response.json
        - {output_dir}/kimi_response.json
        - {output_dir}/debate_log.json

    Args:
        layer: equipment / sub_equipment / structure
        context: resolve_review_target 返回的上下文
        debate_log: run_debate 返回的 token 记录列表
        expert_responses: run_debate 返回的最终回复 {expert_id: parsed_json}
        token_summary: summarize_token_usage 返回的摘要
        output_dir: 输出目录路径
        focus: structure 层聚焦模式
    """
    os.makedirs(output_dir, exist_ok=True)

    # 保存原始数据
    for eid, resp in expert_responses.items():
        path = os.path.join(output_dir, f"{eid}_response.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(resp, f, indent=2, ensure_ascii=False, default=str)

    with open(os.path.join(output_dir, "debate_log.json"), "w", encoding="utf-8") as f:
        json.dump(debate_log, f, indent=2, ensure_ascii=False)

    # 生成 markdown 报告
    report = _build_report_md(layer, context, debate_log, expert_responses,
                               token_summary, focus)

    report_path = os.path.join(output_dir, "评审报告.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"  评审报告已保存: {report_path}", file=__import__('sys').stderr)


def _build_report_md(layer, context, debate_log, expert_responses,
                      token_summary, focus):
    """构建 markdown 报告文本。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    industry = context.get("industry", "")
    sub = context.get("sub_industry", "")
    equip = context.get("equipment", "")
    num_rounds = len(token_summary.get("rounds", []))

    # ── 层级中文 ──
    layer_names = {
        "equipment": "设备清单",
        "sub_equipment": "子设备清单",
        "structure": "结构树（子系统/部件/零件）",
    }
    layer_cn = layer_names.get(layer, layer)

    lines = []

    # ═══════════════════════════════════════════════
    # 标题与元信息
    # ═══════════════════════════════════════════════
    title = f"{sub} {equip} {layer_cn}评审报告" if equip else f"{sub} {layer_cn}评审报告"
    lines.append(f"# {title}\n")
    lines.append(f"> 日期: {now}")
    lines.append(f"> 评审方式: 双AI独立审查 + 多轮辩论（{num_rounds}轮） + 待人工仲裁")
    lines.append(f"> 评审层级: {layer_cn}" + (f"（聚焦: {focus}）" if focus != "all" else ""))
    lines.append(f"> 评审对象: {industry} - {sub}" + (f" - {equip}" if equip else ""))
    lines.append(f"> 总 Token 消耗: {token_summary.get('total_tokens', 0):,}")
    lines.append("")

    # ═══════════════════════════════════════════════
    # 一、评审背景
    # ═══════════════════════════════════════════════
    lines.append("## 一、评审背景\n")

    # Token 消耗明细
    lines.append("### Token 消耗统计\n")
    lines.append("| 轮次 | DeepSeek | Kimi | 合计 |")
    lines.append("|------|----------|------|------|")
    for rd in token_summary.get("rounds", []):
        rn = rd.get("round", "?")
        ds_total = rd.get("deepseek", {}).get("total", 0)
        km_total = rd.get("kimi", {}).get("total", 0)
        lines.append(f"| R{rn} | {ds_total:,} | {km_total:,} | {ds_total + km_total:,} |")
    lines.append("")

    # ═══════════════════════════════════════════════
    # 二、两位专家意见汇总
    # ═══════════════════════════════════════════════
    lines.append("## 二、两位专家意见汇总\n")

    ds_resp = expert_responses.get("deepseek", {})
    km_resp = expert_responses.get("kimi", {})

    # 如果有 parse_error 或 error，标注
    ds_ok = isinstance(ds_resp, dict) and "overall_score" in ds_resp
    km_ok = isinstance(km_resp, dict) and "overall_score" in km_resp

    if not ds_ok:
        lines.append(f"> ⚠️ DeepSeek 回复解析失败，数据不完整\n")
    if not km_ok:
        lines.append(f"> ⚠️ Kimi 回复解析失败，数据不完整\n")

    # 评分对比
    ds_score = ds_resp.get("overall_score", "—") if ds_ok else "—"
    km_score = km_resp.get("overall_score", "—") if km_ok else "—"
    ds_verdict = ds_resp.get("verdict", "—") if ds_ok else "—"
    km_verdict = km_resp.get("verdict", "—") if km_ok else "—"

    lines.append("### 2.1 评分与判定\n")
    lines.append("| 专家 | 评分 | 判定 |")
    lines.append("|------|------|------|")
    lines.append(f"| DeepSeek | {ds_score} | {ds_verdict} |")
    lines.append(f"| Kimi | {km_score} | {km_verdict} |")
    lines.append("")

    # Issues 汇总对比
    ds_issues = ds_resp.get("issues", []) if ds_ok else []
    km_issues = km_resp.get("issues", []) if km_ok else []

    if ds_issues or km_issues:
        lines.append("### 2.2 问题汇总\n")

        # 合并去重：按 node + dimension 匹配
        all_nodes = {}
        for iss in ds_issues:
            key = f"{iss.get('node', '')}#{iss.get('dimension', '')}"
            all_nodes.setdefault(key, {"ds": None, "km": None})
            all_nodes[key]["ds"] = iss
        for iss in km_issues:
            key = f"{iss.get('node', '')}#{iss.get('dimension', '')}"
            all_nodes.setdefault(key, {"ds": None, "km": None})
            all_nodes[key]["km"] = iss

        lines.append("| 节点 | 维度 | 严重度 | DeepSeek | Kimi | 共识 |")
        lines.append("|------|------|--------|----------|------|------|")

        for key, pair in all_nodes.items():
            node = pair.get("ds") or pair.get("km")
            node_name = node.get("node", "")
            dimension = node.get("dimension", "")

            # 严重度取更严重的
            sev_order = {"致命": 0, "严重": 1, "一般": 2}
            ds_sev = pair["ds"].get("severity", "") if pair["ds"] else ""
            km_sev = pair["km"].get("severity", "") if pair["km"] else ""
            sev = ds_sev if (sev_order.get(ds_sev, 99) <= sev_order.get(km_sev, 99)) else km_sev

            ds_brief = pair["ds"].get("problem", "")[:40] if pair["ds"] else "—"
            km_brief = pair["km"].get("problem", "")[:40] if pair["km"] else "—"

            both = pair["ds"] is not None and pair["km"] is not None
            consensus = "✅ 共识" if both else "⚠️ 单方"

            lines.append(
                f"| {node_name} | {dimension} | {sev} | {ds_brief} | {km_brief} | {consensus} |"
            )
        lines.append("")

    # 缺失项
    ds_missing = ds_resp.get("missing", []) if ds_ok else []
    km_missing = km_resp.get("missing", []) if km_ok else []

    if ds_missing or km_missing:
        lines.append("### 2.3 遗漏项\n")
        all_missing_names = set()
        for m in ds_missing + km_missing:
            name = m.get("name", "")
            if name not in all_missing_names:
                all_missing_names.add(name)
                ds_has = any(m2.get("name") == name for m2 in ds_missing)
                km_has = any(m2.get("name") == name for m2 in km_missing)
                source = "双方" if (ds_has and km_has) else ("DeepSeek" if ds_has else "Kimi")
                # 找到 reason
                reason = ""
                for m2 in ds_missing + km_missing:
                    if m2.get("name") == name:
                        reason = m2.get("reason", "")
                        break
                lines.append(f"- **{name}**（{source}）: {reason}")
        lines.append("")

    # 冗余项
    ds_redundant = ds_resp.get("redundant", []) if ds_ok else []
    km_redundant = km_resp.get("redundant", []) if km_ok else []

    if ds_redundant or km_redundant:
        lines.append("### 2.4 冗余项\n")
        seen = set()
        for r in ds_redundant + km_redundant:
            node = r.get("node", "")
            if node not in seen:
                seen.add(node)
                ds_has = any(r2.get("node") == node for r2 in ds_redundant)
                km_has = any(r2.get("node") == node for r2 in km_redundant)
                source = "双方" if (ds_has and km_has) else ("DeepSeek" if ds_has else "Kimi")
                lines.append(f"- **{node}**（{source}）: {r.get('reason', '')}")
        lines.append("")

    # ═══════════════════════════════════════════════
    # 三、最终裁定（待人工填写）
    # ═══════════════════════════════════════════════
    lines.append("## 三、最终裁定\n")
    lines.append("<!-- 待人工裁定 -->\n")

    # 列出所有分歧
    disagreements = []
    for key, pair in (all_nodes.items() if ds_issues or km_issues else []):
        ds_has = pair["ds"] is not None
        km_has = pair["km"] is not None
        if ds_has and not km_has:
            disagreements.append(("DeepSeek 单方", pair["ds"]))
        elif km_has and not ds_has:
            disagreements.append(("Kimi 单方", pair["km"]))

    if disagreements:
        lines.append("### 待裁定分歧\n")
        for tag, iss in disagreements:
            lines.append(f"- **{tag}** {iss.get('node', '')} — {iss.get('dimension', '')}: "
                          f"{iss.get('problem', '')}")
            lines.append(f"  - 建议: {iss.get('suggestion', '')}")
        lines.append("")
    else:
        lines.append("两方无分歧（所有问题均为共识项）。\n")

    lines.append("<!-- 在此处填写最终裁定 -->\n")

    # ═══════════════════════════════════════════════
    # 四、具体变更建议
    # ═══════════════════════════════════════════════
    lines.append("## 四、具体变更建议\n")

    # 按 severity 排序收集所有 issues
    all_issues = []
    for iss in ds_issues:
        all_issues.append({**iss, "_source": "DeepSeek"})
    for iss in km_issues:
        # 去重：如果 DeepSeek 已有同 node+dimension，跳过
        key = f"{iss.get('node', '')}#{iss.get('dimension', '')}"
        if not any(f"{i.get('node', '')}#{i.get('dimension', '')}" == key for i in all_issues):
            all_issues.append({**iss, "_source": "Kimi"})

    sev_order = {"致命": 0, "严重": 1, "一般": 2}
    all_issues.sort(key=lambda x: sev_order.get(x.get("severity", "一般"), 99))

    if all_issues:
        lines.append("| # | 操作 | 目标节点 | 维度 | 严重度 | 建议方 | 说明 |")
        lines.append("|---|------|---------|------|--------|--------|------|")
        for i, iss in enumerate(all_issues, 1):
            # 推断操作类型
            suggestion = iss.get("suggestion", "")
            if "新增" in suggestion or "添加" in suggestion:
                op = "新增"
            elif "删除" in suggestion or "移除" in suggestion:
                op = "删除"
            elif "合并" in suggestion:
                op = "合并"
            elif "拆分" in suggestion:
                op = "拆分"
            elif "修改" in suggestion or "调整" in suggestion or "修正" in suggestion:
                op = "修正"
            elif "降级" in suggestion:
                op = "降级"
            elif "升级" in suggestion:
                op = "升级"
            else:
                op = "审查"

            lines.append(
                f"| {i} | {op} | {iss.get('node', '')} | {iss.get('dimension', '')} "
                f"| {iss.get('severity', '')} | {iss.get('_source', '')} "
                f"| {suggestion[:50]} |"
            )
        lines.append("")

    # 遗漏项操作
    if ds_missing or km_missing:
        lines.append("### 待新增条目\n")
        for m in ds_missing + km_missing:
            lines.append(f"- 新增 `{m.get('name', '')}` → {m.get('parent', '')}（原因: {m.get('reason', '')}）")
        lines.append("")

    # 冗余项操作
    if ds_redundant or km_redundant:
        lines.append("### 待移除条目\n")
        for r in ds_redundant + km_redundant:
            lines.append(f"- 移除 `{r.get('node', '')}`（原因: {r.get('reason', '')}）")
        lines.append("")

    return "\n".join(lines)
