"""
改造6 Token消耗测试脚本（一次性，测试完可删）

目的：测试17列故障表单段生成是否会超出 max_tokens=8192 导致截断。
方法：构造完整17列 fault prompt，调用 collector 模型，测量输出完整性和长度。
不联网搜索（聚焦 output token 测量——搜索只增加 input token，不影响 output 上限判断）。

运行：python src/scripts/token_test_retrofit6.py
"""

import os
import sys

# Windows 终端 UTF-8 输出（避免 GBK 编码错误）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 确保 pipeline 包可 import（与 validate_kb.py 一致的路径处理）
# 同时注入 src/ 和 src/pipeline/：后者让 base.py 内部的 `from config import` 可用
try:
    _SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    _PIPELINE = os.path.join(_SRC, "pipeline")
    for _p in (_SRC, _PIPELINE):
        if _p not in sys.path:
            sys.path.insert(0, _p)
except Exception:
    pass

from pipeline.agents.base import call_llm  # noqa: E402


# 完整17列 fault prompt（基于 collector.py 现有 prompt + 检维修5列）
PROMPT_17COL = """请对【火电 - 凝汽器 - 冷凝管】进行故障知识调研。

D5参数置信标注参考——以下标准速查表供判断"标准值"时参考：
  化学 → GB/T 12145-2016、DL/T 246-2015、DL/T 805
  热 → DL/T 932、GB/T 8117、DL/T 581-2013

要求：
1. 按以下失效层级系统化枚举故障（参考IEC 60812 FMEA框架），每个层级若有真实故障则列出，无则跳过：
   ① 功能失效 ② 性能退化 ③ 物理损伤 ④ 结构失效 ⑤ 接口失效 ⑥ 老化/劣化
   注意：不为凑数而强制每个层级都产出故障，少而准优于多而泛（5条左右）
2. D5每条参数必须以"置信：标准值""置信：经验值""置信：待核实"三者之一结尾，不允许遗漏。
3. D6填写监测手段+传感器，标注类型标签[在线][离线]。
4. D7诊断方法采用鉴别诊断逻辑（回答"与相似故障如何区分"）。
5. D8检修方法：[规程级]根本处理：xxx；临时处理：xxx
6. D10易混淆故障：列出症状相似的故障名+区分要点，无则填"—"。

检维修5列定义（改造6新增，D11-D15）：
- D11 用工需求：工种+人数+预计工时（如"钳工2名、管工1名；工时6-8h"，标"置信：经验值"）
- D12 工机具：通用工具类目（如"扭力扳手、胀管器、涡流探伤仪、堵管工具"，标"置信：经验值"）
- D13 备件用料：备件/耗材通用名（如"冷凝管备件、密封胶、堵头、锯末"，标"置信：经验值"，具体型号现场补）
- D14 安全注意事项：HSE/特种作业规程要求（有标准依据标"置信：标准值"并引用如DL/T 869-2012，否则标"置信：经验值"）
- D15 验收标准：检验规范/量化验收指标（有标准依据标"置信：标准值"并引用如DL/T 869-2012、GB/T 12145，否则标"置信：经验值"）

检维修5列置信标注规则（复用D5机制）：
- 每列内容末尾必须标注置信级别（标准值/经验值/待核实）
- D14 安全注意事项、D15 验收标准鼓励标"标准值"并带标准号
- 禁止伪造标准号：不确定来源就标"经验值"，不确定数值就标"待核实"

7. 输出严格为Markdown表格，17列（含故障名称+故障类别+D1-D15）
8. 表格前后不允许添加任何解释性文字、前言、总结
9. 不允许添加额外列

输出格式（严格17列）：
| 故障名称 | 故障类别 | D1 物理属性 | D2 故障等级 | D3 故障描述与机理 | D4 故障征兆 | D5 故障特征参数 | D6 监测与检测手段 | D7 诊断方法 | D8 检修方法 | D9 预防措施 | D10 易混淆故障 | D11 用工需求 | D12 工机具 | D13 备件用料 | D14 安全注意事项 | D15 验收标准 |

D1物理属性取值：机械/电气/绝缘/热/化学/控制/环境
故障类别取值（必须从以下枚举选择）：泄漏、堵塞、结垢、腐蚀、变质、磨损、破裂
D2取值：危急/严重/一般/轻微
"""


def analyze_output(result: str, label: str) -> dict:
    """分析LLM输出，返回完整性指标。"""
    lines = result.strip().split("\n")
    table_lines = [l for l in lines if l.strip().startswith("|")]
    sep_idx = -1
    for i, l in enumerate(table_lines):
        import re
        if re.match(r'^\|[\s\-:|]+\|$', l.strip()):
            sep_idx = i
            break
    data_rows = table_lines[sep_idx + 1:] if sep_idx >= 0 else table_lines[1:]

    header_cols = []
    last_row_cols = []
    if table_lines:
        header_cols = [c.strip() for c in table_lines[0].split("|")[1:-1] if c.strip()]
    if data_rows:
        last_row_cols = [c.strip() for c in data_rows[-1].split("|")[1:-1]]

    # token估算：中文约1.5字/token，英文约4字/token，混合取1.8
    est_tokens = len(result) / 1.8

    is_complete = (
        len(data_rows) >= 1
        and len(header_cols) >= 17
        and len(last_row_cols) >= 17
        and "验收标准" in table_lines[0] if table_lines else False
        and last_row_cols[-1] not in ("", "—", "-") if last_row_cols else False
    )

    return {
        "label": label,
        "total_chars": len(result),
        "est_output_tokens": int(est_tokens),
        "table_row_count": len(data_rows) + (2 if sep_idx >= 0 else 1),
        "data_rows": len(data_rows),
        "header_col_count": len(header_cols),
        "last_row_col_count": len(last_row_cols),
        "last_col_value": (last_row_cols[-1][:40] + "...") if last_row_cols and last_row_cols[-1] else "(空)",
        "is_complete": is_complete,
        "usage_pct": est_tokens / 8192 * 100,
    }


def main():
    print("=" * 64)
    print("改造6 Token消耗测试：17列故障表单段生成")
    print("=" * 64)
    print(f"模型：DeepSeek-V4-Pro | max_tokens=8192")
    print(f"测试部件：冷凝管（凝汽器/蒸汽冷凝系统，预期~5条故障）")
    print()

    try:
        result = call_llm(
            "collector",
            "你是一个工业设备运维知识库的调研智能体。你的任务是通过联网搜索获取的信息，系统性地收集工业设备相关知识。输出严格为Markdown表格，列名与要求完全一致。表格前后不允许添加任何解释性文字。",
            PROMPT_17COL,
            temperature=0.4,
            max_tokens=8192,
        )
    except Exception as e:
        print(f"[FAIL] LLM调用失败: {type(e).__name__}: {e}")
        print("请检查 .env 中 DEEPSEEK_API_KEY 是否有效（曾出现401失效）")
        sys.exit(1)

    stats = analyze_output(result, "冷凝管")

    print("=" * 64)
    print("测试结果分析")
    print("=" * 64)
    print(f"输出总字符数：{stats['total_chars']}")
    print(f"输出token估算：~{stats['est_output_tokens']} tokens")
    print(f"max_tokens：8192 | 使用率：{stats['usage_pct']:.1f}%")
    print(f"表格行数（含表头/分隔）：{stats['table_row_count']}")
    print(f"数据行数（故障条数）：{stats['data_rows']}")
    print(f"表头列数：{stats['header_col_count']}（期望17）")
    print(f"最后一行数据列数：{stats['last_row_col_count']}（期望17）")
    print(f"最后一行末列（验收标准）：{stats['last_col_value']}")

    print()
    print("=" * 64)
    print("分段决策")
    print("=" * 64)
    if stats["usage_pct"] < 60 and stats["is_complete"]:
        print(f"[OK] 使用率 {stats['usage_pct']:.1f}% < 60%，表格完整")
        print(f"  -> 结论：单段生成可行，无需分段")
    elif stats["usage_pct"] < 85 and stats["is_complete"]:
        print(f"[WARN] 使用率 {stats['usage_pct']:.1f}% 偏高（60-85%%），表格完整但冗余空间小")
        print(f"  -> 结论：单段可行，但建议提高 max_tokens 到 12288 留余量")
    else:
        print(f"[FAIL] 使用率 {stats['usage_pct']:.1f}% 过高或表格不完整")
        print(f"  -> 结论：需分段生成（段1诊断列 + 段2检维修5列）")

    # 保存完整输出
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_test_output.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\n完整输出已保存：{out_path}")


if __name__ == "__main__":
    main()
