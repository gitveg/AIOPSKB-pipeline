import json
import re
from agents.base import call_llm

JUDGE_SYSTEM = """你是一个工业设备知识库的审查专家。你需要审查数据的完整性和准确性。

你必须以JSON格式返回审查结果。不要在JSON前后添加其他文字。"""


def judge_layer(agent_key: str, layer: str, context: dict, data: str) -> dict:
    prompt = _build_judge_prompt(layer, context, data)
    raw = call_llm(agent_key, JUDGE_SYSTEM, prompt, temperature=0.2)
    return _parse_judge_response(raw)


def judge_single(layer: str, context: dict, data: str) -> dict:
    """单Judge审查，使用DeepSeek V4"""
    return judge_layer("judge_b", layer, context, data)


def _build_judge_prompt(layer: str, ctx: dict, data: str) -> str:
    industry = ctx.get("industry", "")
    sub = ctx.get("sub_industry", "")
    equip = ctx.get("equipment", "")
    comp = ctx.get("component", "")

    if layer == "sub_industry":
        target = f"{industry}行业 - 子行业划分"
        item_type = "子行业/领域"
    elif layer == "equipment":
        target = f"{industry}-{sub} - 设备枚举"
        item_type = "设备种类"
    elif layer == "sub_equipment":
        target = f"{equip} - 子设备拆分"
        item_type = "子设备/技术路线"
    elif layer == "component":
        target = f"{equip} - 部件拆解"
        item_type = "部件"
    elif layer == "fault":
        target = f"{equip}-{comp} - 故障知识"
        item_type = "故障"
    else:
        target = layer
        item_type = "条目"

    if layer == "fault":
        return f"""知识库Schema约束（审查时必须校验）：
- D1 故障类别：机械/电气/绝缘/热/化学/控制/环境（多选用;分隔，优先单选）
- D2 故障等级：危急(须立即停机)/严重(72h内处理)/一般(下次计划检修)/轻微(跟踪观察)
- D5 填写特征参数+阈值（如[物理]振动速度>7.1mm/s），不是传感器名称
- D6 填写监测手段+传感器（如[在线]振动加速度传感器），不是参数阈值
- D8 格式：根本处理：xxx；临时处理：xxx（无临时处理时填"须立即停机处理"）
- D10 易混淆故障：填写症状相似的故障名+区分要点，无则填"—"

审查对象：{target}
审查数据：
{data}

审查标准：
1. 故障类型全面性：是否遗漏常见故障？
2. 故障征兆实用性(D4)：是否对应现场可观测信号？
3. 特征参数准确性(D5)：阈值是否合理？
4. 诊断逻辑正确性(D7)：是否采用鉴别诊断逻辑？是否回答了"与相似故障如何区分"而非仅仅确认？
5. 检修方法实用性(D8)：是否可在现场执行？是否涵盖根本处理和临时处理？
6. D5/D6区分正确性：D5是否填写的是特征参数（含阈值），D6是否填写的是监测手段（含传感器类型），是否存在信息反向填写？
7. D2等级判定合理性：故障等级是否与Schema定义的判定标准一致？
8. D3因果关系完整性：故障描述是否包含现象+根本原因+诱发条件？
9. D9预防措施可操作性：预防措施是否具体可执行，而非泛泛描述？
10. D10易混淆故障有效性：列出的易混淆故障是否确实容易与本故障混淆？区分要点是否在工程上成立？是否存在填"—"但实际有明显易混淆故障的情况？

以下为对抗性审查——请以一位有25年工龄的挑剔资深工程师视角，主动质疑以下内容，而非礼貌地认可：
11. D5工况适用性：该阈值是否适用于{equip}的实际工况（压力/温度/材质）？同一参数在不同压力等级下差异极大，是否存在工况错配？D5中标注了"适用："条件的参数，其适用条件是否准确合理？
12. D5置信分布：是否所有D5参数都标注了置信级别？标注为"标准值"的参数标准号是否带年份？统计"待核实"占全部D5子参数的比例：≤10%正常不扣分，10%-20%扣1分并在suggestions中指出待核实集中区域，>20%则研究不充分、verdict直接返回revision_needed。零待核实是正常的——说明搜索研究充分，不是可疑信号。
13. D7鉴别诊断充分性：D7是否包含鉴别逻辑（而非仅确认逻辑）？是否明确回答了"与哪个相似故障如何区分"？鉴别要点是否在工程上成立？
14. D8操作安全性：检修步骤是否有安全隐患（如未先泄压就操作、需要特种资质的工序未标注）？操作顺序是否合理？
15. D8规程级标注真实性：标注为[规程级]的检修步骤，是否确实存在对应的强制标准或厂商检修规程？标注为[经验级]的是否真的缺乏规程依据？
16. D5假冒标准值核查：标注为"标准值"的参数，其引用的标准号是否真实存在？是否存在编造的标准号？是否存在标准号正确但阈值数值与该标准实际规定不一致的情况？此类问题按"严重"级别处理，列入critical_issues。

重要规则：对抗审查（第11-16项）中发现的问题，按以下标准分级：
- "致命"：可能导致人身伤亡或设备重大损毁的错误（如D8操作顺序颠倒导致爆炸风险、D5阈值严重错配导致危急故障漏报）
- "严重"：技术逻辑错误但不直接危及安全（如D7诊断条件不充分、D5参数与工况明显不符）
若发现"致命"或"严重"问题，必须列入 critical_issues 字段；若无此类问题，critical_issues 返回空数组，不要强行找问题。

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["缺失的故障类型"], "critical_issues": [{{"dimension": "D5/D7/D8", "fault_name": "故障名称", "issue": "具体问题描述", "severity": "致命/严重"}}], "issues": ["一般性格式或完整性问题"], "suggestions": ["建议"]}}"""

    return f"""审查对象：{target}
审查数据：
{data}

审查标准：
1. 覆盖全面性：是否遗漏了重要的{item_type}？
2. 分类合理性：是否存在表述重合、边界模糊？是否需要更细拆分或合并？
3. 粒度适当性：{item_type}粒度是否一致？
4. 边界清晰性：有无重叠？
5. 实际验证：是否符合真实工业环境？

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["具体缺失项"], "classification_issues": ["重合/粒度问题"], "issues": ["其他问题"], "suggestions": ["建议"]}}"""


def _parse_judge_response(raw: str) -> dict:
    cleaned = re.sub(r'```json\s*', '', raw)
    cleaned = re.sub(r'```\s*', '', cleaned)
    cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
        if "score" not in result:
            result["score"] = 5
        if "verdict" not in result:
            result["verdict"] = "revision_needed"
        if "critical_issues" not in result:
            result["critical_issues"] = []
        return result
    except json.JSONDecodeError:
        score_match = re.search(r'[\'"]?score[\'"]?\s*[:=]\s*(\d+)', raw)
        score = int(score_match.group(1)) if score_match else 5
        return {"verdict": "revision_needed", "score": score, "raw_response": raw,
                "issues": ["Judge返回非JSON格式"], "missing_items": [], "critical_issues": [], "suggestions": []}
