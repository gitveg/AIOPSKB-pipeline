"""
response_parser.py — 专家回复 JSON 提取与 schema 校验

从 LLM 原始文本中提取 JSON（复用 standard_checker.py 的模式），
校验是否符合评审输出 schema。
"""

import json
import re


class ResponseParseError(Exception):
    """专家回复无法解析为有效 JSON 时抛出。"""
    pass


def parse_expert_response(raw_text: str) -> dict:
    """从专家原始回复中提取 JSON 对象。

    提取策略：去掉 markdown 代码块标记后 json.loads。
    与 pipeline/agents/standard_checker.py 保持一致的提取模式。

    Args:
        raw_text: LLM 返回的原始文本

    Returns:
        解析后的 dict

    Raises:
        ResponseParseError: 无法解析时抛出，含原始文本前200字符
    """
    # 尝试提取 ```json ... ``` 块
    json_match = re.search(r'```json\s*(.*?)\s*```', raw_text, re.DOTALL)
    if json_match:
        cleaned = json_match.group(1).strip()
    else:
        # fallback: 去掉所有 code fence 标记
        cleaned = re.sub(r'```\w*\s*|```', '', raw_text).strip()

    # 去掉可能残留的非 JSON 内容（取第一个 { 到最后一个 }）
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ResponseParseError(
            f"JSON 解析失败: {e}\n原始文本前200字符: {raw_text[:200]}"
        )


# ── Schema 校验 ──

ALLOWED_VERDICTS = {"通过", "需修订", "需重做"}
ALLOWED_SEVERITIES = {"致命", "严重", "一般"}
ALLOWED_LEVELS = {"equipment", "sub_equipment", "subsystem", "component", "part"}

REQUIRED_TOP_KEYS = {"layer", "overall_score", "verdict", "issues", "missing", "redundant"}
ISSUE_REQUIRED_KEYS = {"level", "node", "dimension", "severity", "problem", "suggestion"}
MISSING_REQUIRED_KEYS = {"level", "parent", "name", "reason"}
REDUNDANT_REQUIRED_KEYS = {"level", "node", "reason"}


def validate_review_schema(data: dict, layer: str) -> list[str]:
    """校验专家回复 JSON 是否符合评审 schema。

    Args:
        data: parse_expert_response 返回的 dict
        layer: 当前评审层级（用于校验 layer 字段一致性）

    Returns:
        错误列表，空列表表示校验通过
    """
    errors = []

    # 顶层必需字段
    missing_top = REQUIRED_TOP_KEYS - set(data.keys())
    if missing_top:
        errors.append(f"缺少顶层必需字段: {missing_top}")

    # overall_score
    score = data.get("overall_score")
    if score is not None:
        if not isinstance(score, (int, float)) or not (0 <= score <= 10):
            errors.append(f"overall_score 应为 0-10 的数值，实际: {score}")

    # verdict
    verdict = data.get("verdict")
    if verdict is not None and verdict not in ALLOWED_VERDICTS:
        errors.append(f"verdict 应为 {ALLOWED_VERDICTS} 之一，实际: {verdict}")

    # layer 一致性（宽松：只检查是否存在，不强制匹配）
    resp_layer = data.get("layer")
    if resp_layer and resp_layer != layer:
        errors.append(f"响应 layer='{resp_layer}' 与请求 layer='{layer}' 不一致")

    # issues 列表
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        errors.append("issues 应为列表")
    else:
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                errors.append(f"issues[{i}] 不是对象")
                continue
            missing = ISSUE_REQUIRED_KEYS - set(issue.keys())
            if missing:
                errors.append(f"issues[{i}] 缺少字段: {missing}")
            sev = issue.get("severity")
            if sev and sev not in ALLOWED_SEVERITIES:
                errors.append(f"issues[{i}].severity 应为 {ALLOWED_SEVERITIES} 之一，实际: {sev}")

    # missing 列表
    missing_list = data.get("missing", [])
    if not isinstance(missing_list, list):
        errors.append("missing 应为列表")
    else:
        for i, item in enumerate(missing_list):
            if not isinstance(item, dict):
                errors.append(f"missing[{i}] 不是对象")
                continue
            mk = MISSING_REQUIRED_KEYS - set(item.keys())
            if mk:
                errors.append(f"missing[{i}] 缺少字段: {mk}")

    # redundant 列表
    redundant_list = data.get("redundant", [])
    if not isinstance(redundant_list, list):
        errors.append("redundant 应为列表")
    else:
        for i, item in enumerate(redundant_list):
            if not isinstance(item, dict):
                errors.append(f"redundant[{i}] 不是对象")
                continue
            rk = REDUNDANT_REQUIRED_KEYS - set(item.keys())
            if rk:
                errors.append(f"redundant[{i}] 缺少字段: {rk}")

    return errors
