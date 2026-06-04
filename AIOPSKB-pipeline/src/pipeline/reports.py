import os
import json
from datetime import datetime

from config import REPORTS_DIR


def _industry_dir(industry: str) -> str:
    d = os.path.join(REPORTS_DIR, industry)
    os.makedirs(d, exist_ok=True)
    return d


def write_report(industry: str, phase: str, content: str, extra: dict = None):
    out_dir = _industry_dir(industry)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{phase}_{ts}.md"
    filepath = os.path.join(out_dir, filename)
    header = f"# 进度报告: {industry} - {phase}\n> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(header + content)
    return filepath


def write_judge_report(industry: str, layer: str, round_num: int,
                       judge_result: dict, _unused=None):
    out_dir = _industry_dir(industry)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{layer}_judge_r{round_num}_{ts}.md"
    filepath = os.path.join(out_dir, filename)
    content = f"""# Judge审查报告: {industry} - {layer} (第{round_num}轮)
> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Judge (DeepSeek-V4)
- **评分**: {judge_result.get('score', 'N/A')}
- **结论**: {judge_result.get('verdict', 'N/A')}
- **缺失项**: {json.dumps(judge_result.get('missing_items', []), ensure_ascii=False)}
- **问题**: {json.dumps(judge_result.get('issues', []), ensure_ascii=False)}
- **分类问题**: {json.dumps(judge_result.get('classification_issues', []), ensure_ascii=False)}
- **建议**: {json.dumps(judge_result.get('suggestions', []), ensure_ascii=False)}
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath
