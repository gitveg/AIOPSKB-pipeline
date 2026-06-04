"""Industrial PHM Knowledge Base Pipeline v5 — 3-stage execution logic.

Stage 1: Multi-model parallel generation (Gemini + ChatGPT + DeepSeek)
Stage 2: Cross-review by Kimi (scope gate + PHM quality gate)
Stage 3: Synthesis into final outline by Gemini

Aligned with pipeline-plan-v5.md (industrial equipment / OT, PHM-centric).
"""

import logging
from api_client import LLMClient
from utils import save_output, Timer, TokenTracker
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

# ============================================================
# Domain Charter — single source (pipeline-plan-v5 §六)
# ============================================================

DOMAIN_CHARTER = """【领域宪章 — 工业设备 PHM 智能运维知识库】
本任务仅服务于流程/能源/重工业等场景下的「工业设备与产线」智能运维知识库大纲，
且以 PHM（故障预测与健康管理）为主线：状态监测、健康评估、故障诊断、退化与预测（RUL/风险，视场景）、
维修与运行决策支持、闭环复盘与度量。

读者画像：设备/可靠性/检修/工艺相关工程师；目标是当关键设备异常或健康退化时，
能按「数据—健康状态—诊断/预测—处置—复盘」路径检索可执行知识。

必须覆盖的主干（可与章节命名不同，但不得整体缺失）：
设备资产与工况上下文；OT 侧数据采集与质量；状态监测与报警解释；健康指标与基线（含工况归一思路）；
故障模式与案例库；诊断与根因分析（规则与数据驱动，区分于预测）；退化趋势与预测性维护（须交代数据前提与不确定性）；
维修与备件策略及与工单闭环；安全联锁与合规约束；PHM 验证与工业侧 KPI（告警质量、提前量、复盘等）。

严格禁止作为独立章节或知识域：IT AIOps / 云原生（如 Kubernetes、微服务链路）、
企业通用 IT 运维、与具体设备无关的纯 AI/大模型训练教程、空洞数字化口号；
禁止将 PHM 窄化为「仅异常检测」或「仅 IT 化监控」而无故障语义与维修闭环。
若某技术概念（如异常检测、边缘计算）出现，必须锚定到设备信号、故障模式、健康评估或维修决策，
不得写成互联网业务运维教材。"""

# ============================================================
# Prompt Definitions (pipeline-plan-v5 §七)
# ============================================================

STAGE1_SYSTEM = """你是一位资深的工业设备 PHM（故障预测与健康管理）与流程工业关键机组专家，
熟悉状态监测、健康评估、故障诊断、退化与 RUL 场景边界、CBM/RCM 与 OT 数据特点。"""

STAGE1_USER = """请设计一份「工业设备 PHM 智能运维知识库目录大纲」。

要求：
1. 大纲定位：面向设备/可靠性/检修/工艺工程师；服务于关键设备异常与健康退化时的检索、诊断、预测预警（若适用）与处置决策支持
2. PHM 主线：整体结构须能映射到「数据采集与质量 → 状态监测 → 健康评估（含基线/工况上下文）→ 故障诊断 → 退化与预测性维护（须区分诊断与预测）→ 维修与运行闭环 → 验证与 KPI」；禁止把 PHM 收缩为仅「异常检测」或仅「IT 监控」
3. 覆盖范围：仅限工业设备与产线 OT 语境；不得扩展到 IT AIOps、云原生应用运维或纯软件发布运维
4. 结构深度：2–3 级目录（一级域 → 二级主题 → 关键知识点）
5. 每个一级域附：一句话说明 + 「典型设备/工况锚点」（如离心泵轴承振动、往复压缩机气阀、换热器结垢与压降等，可多条）
6. 成熟度标注：对每个一级域标注 L1–L4，措辞对齐设备可用性、故障损失、维修成本、安全风险、PHM 能力成熟度（而非 IT SLA）
7. 一级域方向（可合并或重命名，但不得整体缺失；并体现 PHM 链条）：
   资产与设备树；工况与工艺上下文；数据采集与 OT 连接；状态监测与报警；健康指标与基线；故障模式与案例/ FMEA 入门；
   诊断与根因（与预测分设或可清晰检索）；退化与预测性维护（RUL/风险须写清数据前提与不确定性）；维修与备件与工单闭环；
   安全与合规；组织流程与 PHM 相关 KPI；智能化与工业数据治理（锚定设备与 PHM 闭环）
8. 输出格式：结构化 Markdown

禁止：Kubernetes、微服务、FinOps、CDN、通用 ChatOps 等 IT 专章；无设备语义的纯算法竞赛向章节；
若提及大模型/RAG，仅允许在「工业运维知识助手/案例检索/报告辅助」等限定小节，且不超过全文约 10%。"""

STAGE2_SYSTEM = """你是一位严苛的工业 PHM 知识体系架构师，熟悉 IT/OT 边界与 PHM 能力链。
你的任务是评审多份「工业设备 PHM 智能运维知识库大纲」草案：专业对比、
守住工业设备场景边界，并检验是否「像 PHM」而非泛运维或假 PHM。
对任何 IT AIOps、云原生、泛 IT 运维内容必须标注为越界并建议删除。"""

STAGE2_USER = """你收到了三份「工业设备 PHM 智能运维知识库大纲」草案。请交叉评审。

评审步骤：
1. 共识提取：三份都强调的工业侧与 PHM 相关知识域
2. 分歧标注：独有内容判断是「PHM/设备场景高价值」还是「偏离主题/过泛/ IT 向」
3. 盲区识别：三份都未覆盖的重要域（如健康指标与基线、诊断/预测分界、不确定性、PHM 验证与工业 KPI、联锁与安全、静设备与腐蚀等，按实际草案判断）
4. 结构对比：哪份更适合工程师在异常与健康退化场景下检索，且 PHM 链条完整
5. 深度对比：二级/三级是否落到设备/信号/故障模式/健康状态，而非空泛「智能化」
6. 仲裁建议：分歧项采纳结论

【强制 — PHM 质量守门】
6a. PHM 链条检查：按「监测—评估—诊断—预测—闭环」逐段标注草案覆盖度（缺失段须写入盲区）。
6b. 术语守门：是否混淆诊断与预测、异常与退化、工况波动与故障；若有，写入分歧或盲区并给出终稿修正建议。
6c. 假 PHM 识别：是否出现「仅异常检测/RUL 黑盒/无维修与安全边界」占主干；若有，列入剔除或合并建议。

【强制 — 范围守门（IT 越界）】
7. 越界内容剔除清单：逐条列出任一新草案中出现的 IT AIOps/云原生/泛 IT 专章或明显互联网运维导向的条目（含章节路径）。
   对每个条目说明：为何越界、是否有一工业/PHM 映射可保留（若可，仅一句映射到哪个域；否则整节删除）。
8. 自检：若某草案 80% 内容为 IT 向或非设备向，建议「整体作废该草案结构，仅吸收个别工业/PHM 句子级要点」。

输出格式（Markdown）：
# 工业设备 PHM 智能运维知识库大纲 — 交叉评审报告
## 一、三方共识清单
[列出三份草案都包含的知识域]

## 二、分歧项与仲裁
[每个分歧项附：哪份草案有、其他草案没有、你的仲裁结论及理由]

## 三、盲区补充（含 PHM 链条缺失段）
[三份草案都遗漏的重要知识域]

## 四、结构优化建议（建议一级域顺序与 PHM 映射）
[对最终大纲的知识组织方式给出建议]

## 五、PHM 质量守门摘要（链条覆盖、术语问题、假 PHM 项）

## 六、越界内容剔除清单（Stage 3 必须执行删除）
[表格或列表：章节路径 | 越界类型 | 处理意见 删除/合并到xxx]

## 七、终稿结构建议（一级域顺序）

---

## 草案 A（Gemini 生成）
{draft_a}

---

## 草案 B（ChatGPT 生成）
{draft_b}

---

## 草案 C（DeepSeek 生成）
{draft_c}"""

STAGE3_SYSTEM = """你是工业设备 PHM 领域首席架构师。合成大纲时必须严格遵守评审报告中的
「越界内容剔除清单」：清单中的章节不得在终稿中以任何形式出现（包括改名套壳）。
须落实「PHM 质量守门摘要」中的链条缺失与术语修正，避免假 PHM。
若剔除后某域变单薄，应用「设备/工况/故障模式锚点」与 PHM 闭环知识补足，禁止用 IT 内容凑字数。"""

STAGE3_USER = """基于以下材料合成最终版「工业设备 PHM 智能运维知识库目录大纲」：
1. 三份大纲草案
2. 交叉评审报告（必须落实「越界内容剔除清单」与「PHM 质量守门摘要」）

合成原则：
1. 共识项采纳；分歧按仲裁；盲区补充（含 PHM 链条缺失段）
2. **删除**剔除清单中的全部条目；不得改头换面保留（例如将「Kubernetes 运维」改为「容器运维」仍禁止）
3. 知识结构须体现 PHM 主线：资产与工况上下文 → OT 数据与质量 → 状态监测与报警 → 健康指标与基线 → 故障模式与案例 →
   诊断与根因（与预测分设或可检索）→ 退化与预测性维护（数据前提、不确定性、与检修窗口衔接）→ 维修备件与工单闭环 →
   安全与合规 → 工业数据治理与智能化 → PHM 验证与 KPI（可按评审调整顺序，但不得整条缺失）
4. 每个一级域：名称、一句话说明、成熟度 L1–L4、二三级展开、至少一个设备/工况锚点示例
5. 文末附「知识域依赖关系图」（文字描述，建议标注监测/评估/诊断/预测/闭环流向）
6. 文末附「各域推荐优先级」（P0/P1/P2）— P0 优先保障「异常与健康退化能查、能判、能处置」
7. 文末附「范围与 PHM 自检声明」：5–7 条要点，说明终稿如何满足工业设备场景、PHM 链条、诊断/预测分界、如何排除 IT AIOps 与假 PHM

输出：单一 Markdown，不标注草案来源。

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

class IndustrialPHMPipeline:
    def __init__(self):
        self.token_tracker = TokenTracker()
        self.client = LLMClient(token_tracker=self.token_tracker)

    def run_stage1(self) -> dict:
        """Stage 1: 3 models generate outlines in parallel."""
        console.print("\n[bold blue][Stage 1][/] Multi-model parallel generation (Industrial PHM)...")

        user_prompt = f"{DOMAIN_CHARTER}\n\n{STAGE1_USER}"

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
                    user_prompt=user_prompt,
                    stage=f"stage1_{name.lower()}",
                    temperature=0.7,
                    max_tokens=16384,
                )
            save_output(result, filename)
            drafts[name.lower()] = result
            console.print(f"  [green]OK:[/] {name} draft saved ({t.elapsed:.1f}s)")

        return drafts

    def run_stage2(self, drafts: dict) -> str:
        """Stage 2: Kimi cross-reviews 3 drafts."""
        console.print("\n[bold blue][Stage 2][/] Cross-review by Kimi (PHM + scope gate)...")

        body = STAGE2_USER.format(
            draft_a=drafts.get("gemini", ""),
            draft_b=drafts.get("chatgpt", ""),
            draft_c=drafts.get("deepseek", ""),
        )
        user_prompt = f"{DOMAIN_CHARTER}\n\n{body}"

        with Timer("Stage 2") as t:
            result = self.client.call_kimi(
                system_prompt=STAGE2_SYSTEM,
                user_prompt=user_prompt,
                stage="stage2_review",
                temperature=1.0,
                max_tokens=16384,
            )

        save_output(result, "stage2_review_report.md")
        console.print(f"  [green]OK:[/] Review report saved ({t.elapsed:.1f}s)")
        return result

    def run_stage3(self, drafts: dict, review_report: str) -> str:
        """Stage 3: Gemini synthesizes final outline."""
        console.print("\n[bold blue][Stage 3][/] Synthesizing final outline...")

        body = STAGE3_USER.format(
            draft_a=drafts.get("gemini", ""),
            draft_b=drafts.get("chatgpt", ""),
            draft_c=drafts.get("deepseek", ""),
            review_report=review_report,
        )
        user_prompt = f"{DOMAIN_CHARTER}\n\n{body}"

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
        console.print("[bold magenta]  Industrial PHM Knowledge Base Pipeline v5 — Outline[/]")
        console.print("[bold magenta]  (Stage 1-3: Generate → Review → Synthesize)[/]")
        console.print("[bold magenta]════════════════════════════════════════════════════[/]")

        drafts = self.run_stage1()
        review_report = self.run_stage2(drafts)
        final_outline = self.run_stage3(drafts, review_report)

        console.print("\n[bold magenta]════════════════════════════════════════════════════[/]")
        console.print("[bold green]  Pipeline completed successfully![/]")
        console.print("[bold]  Final output: output/stage3_final_outline.md[/]")
        console.print(self.token_tracker.summary())
        console.print("[bold magenta]════════════════════════════════════════════════════[/]\n")

        return final_outline
