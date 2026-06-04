"""
PHM 大纲并集合并 Pipeline
读取 sources/ 下所有 .md 文件，调用 LLM API 取并集合并为一份最全大纲。

用法（从项目根目录运行）：
  python scripts/main.py                            # 运行合并 Pipeline，生成 v1 大纲
  python scripts/main.py --judge                    # 审查模式：对最新版本大纲调用 Gemini 进行质量审查
  python scripts/main.py --iterate                  # 迭代模式：根据审查反馈迭代优化大纲，版本号自动递增
  python scripts/main.py --mentor_iterate DIR       # 导师迭代模式：综合导师建议目录中所有反馈文件进行迭代
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

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
# 路径
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
OUTLINES_DIR = PROJECT_ROOT / "outlines"
REVIEWS_DIR = PROJECT_ROOT / "reviews"
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_PATH = OUTLINES_DIR / "Merged_PHM_TOC.md"
SKIP_NAMES = frozenset({"merged_phm_toc.md"})

# ---------------------------------------------------------------------------
# .env 加载
# ---------------------------------------------------------------------------

def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if "#" in v:
        v = v.split("#", 1)[0].strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        v = v[1:-1].strip()
    return v


def load_env() -> None:
    if ENV_PATH.is_file():
        load_dotenv(ENV_PATH, override=False)
        logger.info("已加载 .env: %s", ENV_PATH)
    else:
        logger.warning("未找到 .env: %s", ENV_PATH)


# ---------------------------------------------------------------------------
# API 客户端构建
# ---------------------------------------------------------------------------

def build_client() -> tuple[OpenAI, str]:
    """按优先级构建 Judge 客户端，返回 (client, model_name)。"""
    candidates = [
        ("OPENAI", os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_BASE_URL"), os.getenv("OPENAI_MODEL")),
        ("CHAT (OpenAI/Gemini)", os.getenv("CHAT_API_KEY"), os.getenv("CHAT_BASE_URL"), os.getenv("OPENAI_MODEL")),
        ("CHAT (Gemini)", os.getenv("CHAT_API_KEY"), os.getenv("CHAT_BASE_URL"), os.getenv("GEMINI_MODEL")),
        ("DEEPSEEK", os.getenv("DEEPSEEK_API_KEY"), os.getenv("DEEPSEEK_BASE_URL"), os.getenv("DEEPSEEK_MODEL")),
        ("KIMI", os.getenv("KIMI_API_KEY"), os.getenv("KIMI_BASE_URL"), os.getenv("KIMI_MODEL")),
    ]

    for label, api_key, base_url, model in candidates:
        api_key = _strip(api_key)
        base_url = _strip(base_url)
        model = _strip(model)
        if not api_key or not model:
            continue
        try:
            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url.rstrip("/")
            client = OpenAI(**kwargs)
            logger.info("使用 %s | model=%s | base_url=%s", label, model, kwargs.get("base_url", "default"))
            return client, model
        except Exception as exc:
            logger.warning("%s 客户端初始化失败: %s", label, exc)
            continue

    raise RuntimeError("所有 API 配置均不可用，请检查 .env 文件。")


# ---------------------------------------------------------------------------
# Markdown 解析
# ---------------------------------------------------------------------------

def read_source_files() -> list[tuple[str, str]]:
    """读取 sources/ 目录下所有 .md 源文件，返回 [(filename, content), ...]。"""
    files = []
    for fp in sorted(SOURCES_DIR.glob("*.md")):
        if fp.name.lower() in SKIP_NAMES:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            files.append((fp.name, text))
            logger.info("已读取: %s (%d 字符)", fp.name, len(text))
        except OSError as exc:
            logger.error("读取失败（已跳过）: %s — %s", fp, exc)
    if not files:
        raise RuntimeError("未找到任何 .md 源文件。")
    logger.info("共读取 %d 个源文件。", len(files))
    return files


# ---------------------------------------------------------------------------
# LLM 合并
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "你是工业设备智能运维（PHM，Prognostics and Health Management）领域的资深架构师，"
    "擅长知识体系梳理和大纲设计。你的任务是合并多份 PHM 知识库大纲。"
)

USER_PROMPT_TEMPLATE = """\
以下是来自 {n} 个不同 LLM 生成的 PHM 知识库大纲。请对它们进行**严格并集合并**，生成一份最全面的知识库大纲。

=== 合并规则（必须严格遵守） ===

1. **并集原则**：任何一份源文件中出现的独特主题，必须在最终大纲中体现，不得遗漏。
2. **重叠合并**：多份文件中语义相同或高度相近的主题，合并为一条，保留最详细的描述和子项。
3. **层级结构**：使用 Markdown 的 ## 和 ### 组织层级（## 为一级章节，### 为二级节）。
4. **保留细节**：合并后的每一条目应包含源文件中最丰富的描述信息（传感器型号、算法名、标准编号等具体内容）。
5. **PHM 语境**：所有内容必须保持在工业设备 PHM 的专业语境中。
6. **完整性自检**：在输出前，请自行检查是否已覆盖每份源文件的所有独特主题。

=== 输出格式 ===

- 使用纯 Markdown 格式
- 每个一级章节使用 ## 编号（如 ## 1. xxx）
- 每个二级节使用 ### 编号（如 ### 1.1 xxx）
- 条目使用 - 列表
- 不要输出额外解释，只输出大纲本身
- 不要用 ```markdown 代码块包裹，直接输出 Markdown 文本
- 输出会很长，请务必输出完整内容，不要截断或省略

=== 源文件内容 ===

{content}
"""

CHUNK_MERGE_PROMPT = """\
以下是两份 PHM 知识库中间合并大纲。请将它们合并为一份更全面的大纲，严格取并集，不遗漏任何独特主题。

合并规则：并集原则、重叠合并、保留最详细描述。
输出格式：Markdown ##/### 层级，不要用代码块包裹，输出完整内容不要截断。

=== 大纲 A ===
{outline_a}

=== 大纲 B ===
{outline_b}
"""


def call_llm_with_retry(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    max_retries: int = 3,
) -> str:
    """调用 LLM API，失败时指数退避重试。"""
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=65536,
            )
            content = resp.choices[0].message.content if resp.choices else None
            if not content or not content.strip():
                raise RuntimeError("模型返回为空。")
            # 剥离 LLM 可能添加的 ```markdown ... ``` 包裹
            content = _strip_code_block(content)
            usage = resp.usage
            if usage:
                logger.info(
                    "API 调用成功 (attempt %d) | prompt_tokens=%d completion_tokens=%d",
                    attempt, usage.prompt_tokens, usage.completion_tokens,
                )
            return content.strip()
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning("API 调用失败 (attempt %d/%d): %s — %ds 后重试", attempt, max_retries, exc, wait)
            if attempt == max_retries:
                raise RuntimeError(f"API 调用失败（已重试 {max_retries} 次）: {exc}") from exc
            time.sleep(wait)
    raise RuntimeError("不应到达此处")


def _strip_code_block(text: str) -> str:
    """剥离 LLM 输出中可能存在的 ```markdown ... ``` 包裹。"""
    s = text.strip()
    # 匹配开头的 ```markdown 或 ``` 语言标记
    if s.startswith("```"):
        lines = s.split("\n", 1)
        if len(lines) > 1:
            first = lines[0].strip()
            if re.match(r"^```\w*$", first):
                s = lines[1]
    # 匹配结尾的 ```
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3].rstrip()
    return s.strip()


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 字符/token，英文约 4 字符/token，取中间值 2）。"""
    return len(text) // 2


def merge_outlines(
    client: OpenAI,
    model: str,
    files: list[tuple[str, str]],
    max_context_tokens: int = 100000,
) -> str:
    """
    合并多份大纲。如果总内容在上下文窗口内，一次性合并；
    否则分批合并后再合并中间结果。
    """
    labeled = []
    for fname, content in files:
        labeled.append(f"【来源: {fname}】\n{content.strip()}")
    all_content = "\n\n---\n\n".join(labeled)
    estimated_tokens = estimate_tokens(all_content)

    logger.info("总输入约 %d tokens（估算），上下文窗口 %d tokens", estimated_tokens, max_context_tokens)

    if estimated_tokens <= max_context_tokens:
        logger.info("采用一次性合并策略。")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(n=len(files), content=all_content)},
        ]
        return call_llm_with_retry(client, model, messages)

    # 分批合并
    logger.info("输入超出窗口限制，采用分批合并策略。")
    mid = len(files) // 2
    batch_a = files[:mid]
    batch_b = files[mid:]

    logger.info("批次 A: %d 个文件，批次 B: %d 个文件", len(batch_a), len(batch_b))

    outline_a = merge_outlines(client, model, batch_a, max_context_tokens)
    logger.info("批次 A 合并完成（%d 字符）。", len(outline_a))

    outline_b = merge_outlines(client, model, batch_b, max_context_tokens)
    logger.info("批次 B 合并完成（%d 字符）。", len(outline_b))

    logger.info("合并两个中间结果...")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": CHUNK_MERGE_PROMPT.format(outline_a=outline_a, outline_b=outline_b)},
    ]
    return call_llm_with_retry(client, model, messages)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def write_output(merged: str, source_names: list[str]) -> Path:
    """写入合并后的大纲文件。"""
    header = (
        f"# 工业设备智能运维（PHM）知识库 — 合并大纲\n"
        f"\n"
        f"> 合并时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"> 源文件: {', '.join(source_names)}\n"
        f"> 合并策略: 严格并集（取所有源文件的唯一主题并集）\n"
        f"\n"
        f"---\n"
        f"\n"
    )
    body = merged
    # 去掉 LLM 可能生成的顶层 # 标题（避免与 header 冲突）
    body = re.sub(r"^#\s+.+\n*", "", body, count=1)

    content = header + body + "\n"
    OUTPUT_PATH.write_text(content, encoding="utf-8", newline="\n")
    logger.info("合并大纲已保存: %s（%d 字符）", OUTPUT_PATH, len(content))
    return OUTPUT_PATH


# ---------------------------------------------------------------------------
# 版本管理
# ---------------------------------------------------------------------------

def detect_latest_version() -> int:
    """自动检测 outlines/ 目录中最新的版本号。未标明版本的 Merged_PHM_TOC.md 为 v1。"""
    max_ver = 0
    if OUTPUT_PATH.is_file():
        max_ver = 1
    for fp in OUTLINES_DIR.glob("Merged_PHM_TOC_v*.md"):
        m = re.match(r"Merged_PHM_TOC_v(\d+)\.md", fp.name)
        if m:
            max_ver = max(max_ver, int(m.group(1)))
    logger.info("检测到最新版本: v%d", max_ver)
    return max_ver


def get_merged_path(version: int) -> Path:
    """获取指定版本的合并大纲路径。"""
    if version <= 1:
        return OUTPUT_PATH
    return OUTLINES_DIR / f"Merged_PHM_TOC_v{version}.md"


def get_review_path(version: int) -> Path:
    """获取指定版本的审查报告路径。"""
    if version <= 1:
        return REVIEWS_DIR / "PHM_TOC_Review.md"
    return REVIEWS_DIR / f"PHM_TOC_Review_v{version}.md"


# ---------------------------------------------------------------------------
# 审查模式
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = (
    "你是工业设备智能运维领域的资深专家，精通 PHM（故障预测与健康管理）、设备全生命周期管理、"
    "多模态状态监测、检修工程、可靠性工程、工业AI与知识体系设计。"
    "你的任务是从「工业设备智能运维知识库」的整体视角出发，对知识库大纲进行专业审查，"
    "确保大纲不仅覆盖 PHM 算法体系，还覆盖设备管理、监测感知、检修执行、运维组织等完整业务维度。"
)

JUDGE_USER_PROMPT = """\
请对以下「工业设备智能运维知识库大纲」进行全面、深入的专业审查。

=== 审查原则 ===

1. **客观务实**：只在确实存在问题时才指出不足，不要为了提不足而硬凑问题。如果某个维度做得很好，直接肯定即可，无需强行挑刺。
2. **聚焦大纲**：所有建议必须围绕「大纲的章节结构、知识覆盖面、层级组织」展开。不要建议添加具体的代码片段、流程图、表格示例、公式等内容——这些属于正文撰写阶段的工作，不是大纲层面的事。

=== 审查维度 ===

请从以下维度逐一分析，并给出具体评价和改进建议：

1. **完整性与覆盖面审查**
   - 是否覆盖了完整的智能运维知识体系（设备全生命周期管理、多模态监测与感知、PHM算法与模型、检修执行与工单闭环、运维组织与人员能力、系统平台与数据治理、标准规范、行业应用等）？
   - 是否有重要的业务维度或知识领域被遗漏？
   - 各章节的粒度是否均衡？

2. **设备全生命周期维度审查**
   - 是否覆盖了设备从选型、采购、安装调试、运行使用、维护检修、更新改造到退役报废的全过程管理知识？
   - 各阶段的典型知识（如选型的可监测性设计、安装的基线建立、运行的操作规程、检修的SOP等）是否充分？
   - 生命周期数据贯通与设备主数据管理是否考虑？

3. **多模态监测维度审查**
   - 是否按数据模态（工艺参数、振动、温度、声学/超声、图像/视频、电气信号、油液等）分别构建了看护知识体系？
   - 不同模态对应的传感器选型、特征工程、分析方法是否充分？
   - 多模态数据融合策略是否有覆盖？

4. **PHM算法与技术准确性审查**
   - 算法分类是否准确完整（机理驱动、数据驱动、混合方法）？
   - 技术术语使用是否规范一致？
   - 故障诊断、健康评估、寿命预测、决策优化的技术链路是否完整？
   - 评估指标是否合理（算法指标与业务指标兼顾）？

5. **检修业务闭环与实用性审查**
   - 从监测发现异常到检修执行完毕的完整闭环是否覆盖（告警→诊断→决策→工单→检修→验证→经验沉淀）？
   - 是否涵盖维修SOP、工单管理、备件调度、外委管理、维修质量验收、经验复用等关键业务环节？
   - 大纲对实际知识库建设的指导性如何？各条目是否具体到可以指导内容撰写？

6. **结构与逻辑合理性审查**
   - 章节之间的逻辑关系是否清晰？知识组织的多维视角（时间轴、数据轴、技术轴、业务轴）是否明确？
   - 层级划分是否合理？是否存在内容放错层级或不同章节内容重叠的情况？
   - 是否兼顾了不同角色（设备工程师、算法工程师、运维管理者）的知识需求？

7. **前瞻性与发展趋势审查**
   - 是否纳入了前沿技术（大模型/Agent、数字孪生、联邦学习、边缘智能、机器人巡检等）？
   - 是否考虑了行业发展趋势（智能制造、工业互联网、工业数据资产化等）？

8. **总体评价与建议**
   - 给出大纲的整体质量评分（1-10 分）并说明理由
   - 列出真正需要优先改进的问题（仅列出确实存在的不足，数量不限）
   - 给出具体的改进方向建议（仅限大纲层面的章节、结构、覆盖面调整）

=== 输出格式 ===

请使用 Markdown 格式输出审查报告，包含以下部分：
- 各维度的分析和评价（使用二级标题）
- 每个维度下给出优点、不足（如有）和改进建议（如有）
- 最后给出总结和评分

=== 待审查的大纲内容 ===

{content}
"""


def build_gemini_client() -> tuple[OpenAI, str]:
    """构建专用于审查模式的 Gemini 客户端。"""
    api_key = _strip(os.getenv("CHAT_API_KEY"))
    base_url = _strip(os.getenv("CHAT_BASE_URL"))
    model = _strip(os.getenv("GEMINI_MODEL"))
    if not api_key or not model:
        raise RuntimeError("审查模式需要 CHAT_API_KEY 和 GEMINI_MODEL 配置，请检查 .env 文件。")
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    client = OpenAI(**kwargs)
    logger.info("审查模式 | 使用 Gemini | model=%s | base_url=%s", model, kwargs.get("base_url", "default"))
    return client, model


def judge_mode() -> None:
    """审查模式：读取最新版本大纲，调用 Gemini 进行专业审查。"""
    logger.info("=" * 60)
    logger.info("PHM 大纲审查模式启动")
    logger.info("=" * 60)

    # Step 1: 加载环境 & 检测版本
    load_env()
    cur_version = detect_latest_version()
    if cur_version == 0:
        raise RuntimeError("未找到任何合并大纲文件，请先运行合并 Pipeline。")
    merged_path = get_merged_path(cur_version)

    # Step 2: 读取大纲
    merged_content = merged_path.read_text(encoding="utf-8", errors="replace")
    logger.info("已读取大纲 v%d: %s（%d 字符）", cur_version, merged_path, len(merged_content))

    # Step 3: 构建 Gemini 客户端
    client, model = build_gemini_client()

    # Step 4: 调用 Gemini 进行审查
    logger.info("开始调用 Gemini 进行大纲审查 (v%d)...", cur_version)
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": JUDGE_USER_PROMPT.format(content=merged_content)},
    ]
    t0 = time.time()
    review_result = call_llm_with_retry(client, model, messages, max_retries=3)
    elapsed = time.time() - t0
    logger.info("Gemini 审查完成，耗时 %.1f 秒，结果 %d 字符。", elapsed, len(review_result))

    # Step 5: 写入审查报告
    review_path = get_review_path(cur_version)
    header = (
        f"# PHM 知识库大纲审查报告 — v{cur_version}\n"
        f"\n"
        f"> 审查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"> 审查对象: {merged_path.name}（v{cur_version}）\n"
        f"> 审查模型: {model}\n"
        f"\n"
        f"---\n"
        f"\n"
    )
    body = re.sub(r"^#\s+.+\n*", "", review_result, count=1)
    content = header + body + "\n"
    review_path.write_text(content, encoding="utf-8", newline="\n")
    logger.info("审查报告已保存: %s（%d 字符）", review_path, len(content))

    logger.info("=" * 60)
    logger.info("审查完成！输出文件: %s", review_path)
    logger.info("提示: 运行 --iterate 可基于此审查报告迭代优化大纲")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# 迭代模式
# ---------------------------------------------------------------------------

ITERATE_SYSTEM_PROMPT = (
    "你是工业设备智能运维（PHM，Prognostics and Health Management）领域的资深架构师，"
    "擅长知识体系梳理和大纲设计。你的任务是根据审查反馈对 PHM 知识库大纲进行迭代优化。"
)

ITERATE_USER_PROMPT = """\
请根据以下审查反馈，对 PHM 知识库大纲进行迭代优化。

=== 迭代要求 ===

1. **逐条响应审查意见**：对审查报告中的每一条改进建议，在大纲中落实对应修改。
2. **保持已有优势**：审查报告中指出的优点和良好结构应予以保留。
3. **不降低覆盖面**：优化过程中不得删除已有的独特主题，只能增加、调整或重组。
4. **输出完整大纲**：输出迭代后的完整大纲，而非仅输出修改部分。
5. **PHM 语境**：所有内容必须保持在工业设备 PHM 的专业语境中。

=== 输出格式 ===

- 使用纯 Markdown 格式
- 每个一级章节使用 ## 编号（如 ## 1. xxx）
- 每个二级节使用 ### 编号（如 ### 1.1 xxx）
- 条目使用 - 列表
- 不要输出额外解释，只输出大纲本身
- 不要用 ```markdown 代码块包裹，直接输出 Markdown 文本
- 输出会很长，请务必输出完整内容，不要截断或省略

=== 当前大纲（v{cur_version}） ===

{outline}

=== 审查反馈 ===

{review}
"""


def iterate_mode() -> None:
    """迭代模式：读取最新大纲和审查反馈，调用 LLM 进行迭代优化。"""
    logger.info("=" * 60)
    logger.info("PHM 大纲迭代模式启动")
    logger.info("=" * 60)

    # Step 1: 加载环境 & 检测版本
    load_env()
    cur_version = detect_latest_version()
    if cur_version == 0:
        raise RuntimeError("未找到任何合并大纲文件，请先运行合并 Pipeline。")

    next_version = cur_version + 1
    merged_path = get_merged_path(cur_version)
    review_path = get_review_path(cur_version)

    # Step 2: 读取大纲和审查报告
    outline = merged_path.read_text(encoding="utf-8", errors="replace")
    logger.info("已读取大纲 v%d: %s（%d 字符）", cur_version, merged_path, len(outline))

    if not review_path.is_file():
        raise RuntimeError(f"未找到 v{cur_version} 的审查报告: {review_path}，请先运行 --judge。")
    review = review_path.read_text(encoding="utf-8", errors="replace")
    logger.info("已读取审查报告: %s（%d 字符）", review_path, len(review))

    # Step 3: 构建 API 客户端
    client, model = build_client()

    # Step 4: 调用 LLM 进行迭代
    logger.info("开始调用 LLM 进行大纲迭代优化 (v%d -> v%d)...", cur_version, next_version)
    messages = [
        {"role": "system", "content": ITERATE_SYSTEM_PROMPT},
        {"role": "user", "content": ITERATE_USER_PROMPT.format(
            cur_version=cur_version, outline=outline, review=review,
        )},
    ]
    t0 = time.time()
    result = call_llm_with_retry(client, model, messages, max_retries=3)
    elapsed = time.time() - t0
    logger.info("LLM 迭代完成，耗时 %.1f 秒，结果 %d 字符。", elapsed, len(result))

    # Step 5: 写入新版本
    next_path = get_merged_path(next_version)
    header = (
        f"# 工业设备智能运维（PHM）知识库 — 合并大纲 v{next_version}\n"
        f"\n"
        f"> 迭代时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"> 基于版本: v{cur_version}（{merged_path.name}）\n"
        f"> 审查报告: {review_path.name}\n"
        f"> 迭代模型: {model}\n"
        f"\n"
        f"---\n"
        f"\n"
    )
    body = re.sub(r"^#\s+.+\n*", "", result, count=1)
    content = header + body + "\n"
    next_path.write_text(content, encoding="utf-8", newline="\n")
    logger.info("迭代大纲 v%d 已保存: %s（%d 字符）", next_version, next_path, len(content))

    logger.info("=" * 60)
    logger.info("迭代完成！v%d -> v%d，输出文件: %s", cur_version, next_version, next_path)
    logger.info("提示: 运行 --judge 可对 v%d 生成审查报告", next_version)
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# 导师迭代模式
# ---------------------------------------------------------------------------

MENTOR_ITERATE_SYSTEM_PROMPT = (
    "你是工业设备智能运维（PHM，Prognostics and Health Management）领域的资深架构师，"
    "擅长知识体系梳理和大纲设计。你的任务是根据导师指导意见和多位 LLM 审查反馈，"
    "对 PHM 知识库大纲进行全面迭代优化。导师意见具有最高优先级，必须逐条落实。"
)

MENTOR_ITERATE_USER_PROMPT = """\
请根据以下多方反馈，对 PHM 知识库大纲进行全面迭代优化。

=== 迭代要求 ===

1. **保留所有知识点**：当前大纲中的每一个具体知识点（条目级）都必须在最终大纲中有所体现，不得丢失。但知识点的归属章节可以调整、移动和重组。
2. **大胆重构章节结构**：反馈如果要求新增维度（如按设备类型、按故障模式等正交维度），应当以新增独立章节的方式体现，而不是把新内容硬塞进已有章节。新增章节 + 重组原有内容 = 更合理的知识架构。
3. **反馈意见最高优先级**：反馈中提出的每一个维度和具体要求，必须在大纲中体现。
4. **综合多源审查**：合理吸收各方建议中的有价值意见。
5. **输出完整大纲**：输出迭代后的完整大纲，而非仅输出修改部分。
6. **PHM 语境**：所有内容必须保持在工业设备智能运维的专业语境中。

=== 输出格式 ===

- 使用纯 Markdown 格式
- 每个一级章节使用 ## 编号（如 ## 1. xxx）
- 每个二级节使用 ### 编号（如 ### 1.1 xxx）
- 条目使用 - 列表
- 不要输出额外解释，只输出大纲本身
- 不要用 ```markdown 代码块包裹，直接输出 Markdown 文本
- 输出会很长，请务必输出完整内容，不要截断或省略

=== 当前大纲（v{cur_version}） ===

{outline}

=== 自动审查反馈 ===

{review}

=== 导师与多源反馈 ===

{mentor_feedback}
"""


def _read_feedback_dir(feedback_dir: Path) -> list[tuple[str, str]]:
    """读取反馈目录下所有 .md / .txt 文件，返回 [(filename, content), ...]。"""
    files = []
    for fp in sorted(feedback_dir.iterdir()):
        if fp.suffix.lower() not in {".md", ".txt"}:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            files.append((fp.name, text))
            logger.info("已读取反馈: %s（%d 字符）", fp.name, len(text))
        except OSError as exc:
            logger.error("读取失败（已跳过）: %s — %s", fp, exc)
    return files


def mentor_iterate_mode(feedback_dir: str) -> None:
    """导师迭代模式：综合导师建议目录和审查报告，调用 LLM 进行迭代优化。"""
    logger.info("=" * 60)
    logger.info("PHM 大纲导师迭代模式启动")
    logger.info("=" * 60)

    # Step 1: 加载环境 & 检测版本
    load_env()
    cur_version = detect_latest_version()
    if cur_version == 0:
        raise RuntimeError("未找到任何合并大纲文件，请先运行合并 Pipeline。")

    next_version = cur_version + 1
    merged_path = get_merged_path(cur_version)
    review_path = get_review_path(cur_version)

    # Step 2: 读取当前版本大纲
    outline = merged_path.read_text(encoding="utf-8", errors="replace")
    logger.info("已读取大纲 v%d: %s（%d 字符）", cur_version, merged_path, len(outline))

    # Step 3: 读取自动审查报告（可选）
    review = ""
    if review_path.is_file():
        review = review_path.read_text(encoding="utf-8", errors="replace")
        logger.info("已读取审查报告: %s（%d 字符）", review_path, len(review))
    else:
        logger.info("未找到审查报告 %s，跳过。", review_path)

    # Step 4: 读取导师与多源反馈目录
    fb_dir = Path(feedback_dir)
    if not fb_dir.is_dir():
        raise RuntimeError(f"反馈目录不存在: {fb_dir}")
    feedback_files = _read_feedback_dir(fb_dir)
    if not feedback_files:
        raise RuntimeError(f"反馈目录中没有 .md 或 .txt 文件: {fb_dir}")

    mentor_feedback_parts = []
    for fname, content in feedback_files:
        mentor_feedback_parts.append(f"【{fname}】\n{content.strip()}")
    mentor_feedback = "\n\n---\n\n".join(mentor_feedback_parts)
    logger.info("共读取 %d 份反馈文件。", len(feedback_files))

    # Step 5: 构建 API 客户端
    client, model = build_client()

    # Step 6: 调用 LLM 进行迭代
    logger.info("开始调用 LLM 进行导师迭代优化 (v%d -> v%d)...", cur_version, next_version)
    messages = [
        {"role": "system", "content": MENTOR_ITERATE_SYSTEM_PROMPT},
        {"role": "user", "content": MENTOR_ITERATE_USER_PROMPT.format(
            cur_version=cur_version, outline=outline, review=review,
            mentor_feedback=mentor_feedback,
        )},
    ]
    t0 = time.time()
    result = call_llm_with_retry(client, model, messages, max_retries=3)
    elapsed = time.time() - t0
    logger.info("LLM 迭代完成，耗时 %.1f 秒，结果 %d 字符。", elapsed, len(result))

    # Step 7: 写入新版本
    next_path = get_merged_path(next_version)
    header = (
        f"# 工业设备智能运维（PHM）知识库 — 合并大纲 v{next_version}\n"
        f"\n"
        f"> 迭代时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"> 基于版本: v{cur_version}（{merged_path.name}）\n"
        f"> 审查报告: {review_path.name if review else '无'}\n"
        f"> 导师反馈目录: {fb_dir.name}（{len(feedback_files)} 份文件）\n"
        f"> 迭代模型: {model}\n"
        f"\n"
        f"---\n"
        f"\n"
    )
    body = re.sub(r"^#\s+.+\n*", "", result, count=1)
    content = header + body + "\n"
    next_path.write_text(content, encoding="utf-8", newline="\n")
    logger.info("迭代大纲 v%d 已保存: %s（%d 字符）", next_version, next_path, len(content))

    logger.info("=" * 60)
    logger.info("导师迭代完成！v%d -> v%d，输出文件: %s", cur_version, next_version, next_path)
    logger.info("提示: 运行 --judge 可对 v%d 生成审查报告", next_version)
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PHM 大纲并集合并 Pipeline")
    parser.add_argument("--judge", action="store_true", help="审查模式：对最新版本大纲调用 Gemini 进行质量审查")
    parser.add_argument("--iterate", action="store_true", help="迭代模式：根据审查反馈迭代优化大纲")
    parser.add_argument("--mentor_iterate", type=str, metavar="DIR", help="导师迭代模式：指定反馈目录，综合导师和多源反馈进行迭代")
    args = parser.parse_args()

    if args.judge:
        judge_mode()
        return

    if args.iterate:
        iterate_mode()
        return

    if args.mentor_iterate:
        mentor_iterate_mode(args.mentor_iterate)
        return

    logger.info("=" * 60)
    logger.info("PHM 大纲并集合并 Pipeline 启动")
    logger.info("=" * 60)

    # Step 1: 加载环境 & 解析文件
    load_env()
    files = read_source_files()

    # Step 2: 构建 API 客户端
    client, model = build_client()

    # Step 3: LLM 合并
    logger.info("开始调用 LLM 进行并集合并...")
    t0 = time.time()
    merged = merge_outlines(client, model, files)
    elapsed = time.time() - t0
    logger.info("LLM 合并完成，耗时 %.1f 秒，结果 %d 字符。", elapsed, len(merged))

    # Step 4: 写入输出
    source_names = [f for f, _ in files]
    write_output(merged, source_names)

    logger.info("=" * 60)
    logger.info("Pipeline 完成！输出文件: %s", OUTPUT_PATH)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
