"""AIOps Knowledge Base Pipeline v4 — 3-stage execution logic.

Stage 1: Multi-model parallel generation (Gemini + ChatGPT + DeepSeek)
Stage 2: Cross-review by Kimi (kimi-k2.6)
Stage 3: Synthesis into final outline by Gemini
"""

import logging
from api_client import LLMClient
from utils import save_output, Timer, TokenTracker
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

# ============================================================
# Prompt Definitions
# ============================================================

STAGE1_SYSTEM = """你是一位资深的 AIOps（智能运维）领域架构师，拥有 15 年以上运维平台设计与实施经验。"""

STAGE1_USER = """请为一家企业级组织设计一份「智能运维（AIOps）知识库目录大纲」。

要求：
1. 大纲定位：面向运维工程师、SRE、运维管理层的系统性知识框架
2. 覆盖范围：从运维基础（监控、日志、告警）到智能化（异常检测、根因分析、大模型运维）的完整技术链路
3. 结构深度：2-3 级目录（一级域 → 二级主题 → 关键知识点）
4. 每个一级域附：一句话说明其定位与价值
5. 标注每个一级域的 AIOps 成熟度等级：
   - L1（基础运维）：手工操作为主
   - L2（辅助分析）：数据驱动，人为主
   - L3（智能推荐）：AI 辅助决策
   - L4（高度自愈）：自动化闭环
6. 不要只罗列技术名词，要体现知识之间的逻辑关系和组织思路
7. 输出格式：结构化 Markdown

注意：你的大纲应该是一份可以直接用于指导知识库建设的目录结构文档。"""

STAGE2_SYSTEM = """你是一位严苛的知识体系架构师，擅长对多份方案进行交叉对比评审。
你的特点是：逻辑严密，不做和事佬，每一个分歧都必须有明确结论。"""

STAGE2_USER = """你收到了三份由不同 AI 模型独立生成的「AIOps 知识库大纲」草案。
你的任务是进行交叉对比评审。

评审步骤：
1. **共识提取**：三份草案中共同出现的知识域，说明业界对其重要性有共识
2. **分歧标注**：某份草案有但其他草案没有的内容，分析是"有价值的独特视角"还是"不必要的边缘内容"
3. **盲区识别**：三份草案都遗漏的重要知识域
4. **结构对比**：哪份草案的知识组织结构更合理？为什么？
5. **深度对比**：哪份草案的二级/三级展开更充实？有哪些值得吸收的细节？
6. **仲裁建议**：对于分歧项，给出你的采纳建议及理由

输出格式：
```markdown
# AIOps 知识库大纲 — 交叉评审报告

## 一、三方共识清单
[列出三份草案都包含的知识域]

## 二、分歧项列表
[每个分歧项附：哪份草案有、其他草案没有、你的仲裁结论及理由]

## 三、盲区补充
[三份草案都遗漏的重要知识域]

## 四、独特点子推荐
[某份草案中有价值的独特视角，建议采纳]

## 五、结构优化建议
[对最终大纲的知识组织方式给出建议]
```

---

## 草案 A（Gemini 生成）
{draft_a}

---

## 草案 B（ChatGPT 生成）
{draft_b}

---

## 草案 C（DeepSeek 生成）
{draft_c}"""

STAGE3_SYSTEM = """你是 AIOps 领域首席架构师。你需要将多份大纲草案和评审报告合成为一份最终大纲。
合成要求：产出物必须浑然一体，不能再标注"来自草案X"，应该像一份经过深思熟虑的完整文档。"""

STAGE3_USER = """你需要基于以下材料合成一份最终版的「AIOps 知识库目录大纲」：
1. 三份独立生成的大纲草案
2. 一份交叉评审报告

合成原则：
1. 共识项直接采纳
2. 分歧项按评审报告的仲裁结论处理
3. 盲区必须补充
4. 有价值的独特点子吸收进来
5. 知识结构按"从底层数据 → 上层应用 → 智能化"的逻辑组织
6. 每个一级域包含：域名称、一句话说明、成熟度等级、二级/三级展开
7. 文末附「知识域依赖关系图」（文字描述）
8. 文末附「各域推荐优先级」（P0/P1/P2）

输出要求：
- 一份完整的、可直接使用的 Markdown 大纲文档
- 不要再标注"来自草案A/B/C"，产出物应该是浑然一体的
- 格式清晰，层级分明

---

## 草案 A（Gemini 生成）
{draft_a}

---

## 草案 B（ChatGPT 生成）
{draft_b}

---

## 草案 C（DeepSeek 生成）
{draft_c}

---

## 交叉评审报告
{review_report}"""


# ============================================================
# Pipeline Execution
# ============================================================

class AIOpsPipeline:
    def __init__(self):
        self.token_tracker = TokenTracker()
        self.client = LLMClient(token_tracker=self.token_tracker)

    def run_stage1(self) -> dict:
        """Stage 1: 3 models generate outlines in parallel."""
        console.print("\n[bold blue][Stage 1][/] Multi-model parallel generation...")

        generators = [
            ("Gemini", "call_gemini", "stage1_draft_a_gemini.md"),
            ("ChatGPT", "call_openai", "stage1_draft_b_chatgpt.md"),
            ("DeepSeek", "call_deepseek", "stage1_draft_c_deepseek.md"),
        ]

        drafts = {}
        for name, method_name, filename in generators:
            console.print(f"  [cyan]Generating with {name}...[/]")
            with Timer(f"Stage 1 [{name}]") as t:
                method = getattr(self.client, method_name)
                result = method(
                    system_prompt=STAGE1_SYSTEM,
                    user_prompt=STAGE1_USER,
                    stage=f"stage1_{name.lower()}",
                    temperature=0.7,
                    max_tokens=16384,
                )
            path = save_output(result, filename)
            drafts[name.lower()] = result
            console.print(f"  [green]OK:[/] {name} draft saved ({t.elapsed:.1f}s)")

        return drafts

    def run_stage2(self, drafts: dict) -> str:
        """Stage 2: Kimi cross-reviews 3 drafts."""
        console.print("\n[bold blue][Stage 2][/] Cross-review by Kimi...")

        user_prompt = STAGE2_USER.format(
            draft_a=drafts.get("gemini", ""),
            draft_b=drafts.get("chatgpt", ""),
            draft_c=drafts.get("deepseek", ""),
        )

        with Timer("Stage 2") as t:
            result = self.client.call_kimi(
                system_prompt=STAGE2_SYSTEM,
                user_prompt=user_prompt,
                stage="stage2_review",
                temperature=1.0,
                max_tokens=16384,
            )

        path = save_output(result, "stage2_review_report.md")
        console.print(f"  [green]OK:[/] Review report saved ({t.elapsed:.1f}s)")
        return result

    def run_stage3(self, drafts: dict, review_report: str) -> str:
        """Stage 3: Gemini synthesizes final outline."""
        console.print("\n[bold blue][Stage 3][/] Synthesizing final outline...")

        user_prompt = STAGE3_USER.format(
            draft_a=drafts.get("gemini", ""),
            draft_b=drafts.get("chatgpt", ""),
            draft_c=drafts.get("deepseek", ""),
            review_report=review_report,
        )

        with Timer("Stage 3") as t:
            result = self.client.call_gemini(
                system_prompt=STAGE3_SYSTEM,
                user_prompt=user_prompt,
                stage="stage3_synthesis",
                temperature=0.5,
                max_tokens=32768,
            )

        path = save_output(result, "stage3_final_outline.md")
        console.print(f"  [green]OK:[/] Final outline saved to {path} ({t.elapsed:.1f}s)")
        return result

    def run_full(self):
        """Run the complete 3-stage pipeline."""
        console.print("\n[bold magenta]════════════════════════════════════════════════════[/]")
        console.print("[bold magenta]  AIOps Knowledge Base Pipeline v4 — Outline Generation[/]")
        console.print("[bold magenta]  (Stage 1-3: Generate → Review → Synthesize)[/]")
        console.print("[bold magenta]════════════════════════════════════════════════════[/]")

        # Stage 1
        drafts = self.run_stage1()

        # Stage 2
        review_report = self.run_stage2(drafts)

        # Stage 3
        final_outline = self.run_stage3(drafts, review_report)

        # Summary
        console.print("\n[bold magenta]════════════════════════════════════════════════════[/]")
        console.print("[bold green]  Pipeline completed successfully![/]")
        console.print("[bold]  Final output: output/stage3_final_outline.md[/]")
        console.print(self.token_tracker.summary())
        console.print("[bold magenta]════════════════════════════════════════════════════[/]\n")

        return final_outline
