"""
Markdown 文档整合 Pipeline（四阶段）：
解析分块 → Master TOC（Judge）→ 内容路由（Cheap）→ 深度融合写入最终知识库（Judge）。

业务边界：知识库严格限定在「工业设备 PHM / 智能运维」场景（如石化大型机组、压缩机、泵、
工控系统、PLC、振动与温度等），不包含通用 IT、互联网、云原生（K8s、Redis、微服务等）主题。
本目录 LLMAnswers/ 为开发与运行根目录（.env、.md 与入口脚本均在此）。
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# -----------------------------------------------------------------------------
# 日志
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 路径（脚本所在目录即 LLMAnswers 工作区）
# -----------------------------------------------------------------------------
LLM_ANSWERS_ROOT = Path(__file__).resolve().parent
DEFAULT_MD_DIR = LLM_ANSWERS_ROOT
DEFAULT_ENV_PATH = LLM_ANSWERS_ROOT / ".env"
DEFAULT_MASTER_TOC_PATH = LLM_ANSWERS_ROOT / "Master_TOC.md"
# 生成 TOC / 路由时跳过（避免把全局目录本身当源文档）
SKIP_SOURCE_MD_NAMES = frozenset(
    {
        "master_toc.md",
        "final_knowledge_base.md",
    }
)


def _strip_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if "#" in v:
        v = v.split("#", 1)[0].strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        v = v[1:-1].strip()
    return v


def _load_env() -> None:
    if DEFAULT_ENV_PATH.is_file():
        load_dotenv(DEFAULT_ENV_PATH, override=False)
        logger.info("已加载环境变量文件: %s", DEFAULT_ENV_PATH)
    else:
        logger.warning(
            "未找到 .env 文件: %s，将仅使用进程环境变量。",
            DEFAULT_ENV_PATH,
        )


def _build_openai_client(
    *,
    api_key: str | None,
    base_url: str | None,
    label: str,
) -> OpenAI:
    if not api_key:
        raise ValueError(f"{label}: 缺少 API Key（请检查 .env 或环境变量）。")
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    try:
        client = OpenAI(**kwargs)
    except Exception as exc:
        logger.exception("%s: OpenAI 客户端初始化失败。", label)
        raise RuntimeError(f"{label}: 客户端初始化失败。") from exc
    logger.info("%s: OpenAI 客户端已初始化 (base_url=%s)", label, kwargs.get("base_url", "default"))
    return client


_load_env()

# Cheap：优先 KIMI_*（月之暗面 OpenAI 兼容），其次 DEEPSEEK_* / CHEAP_*
_kimi_key = _strip_env_value(os.getenv("KIMI_API_KEY"))
_kimi_base = _strip_env_value(os.getenv("KIMI_BASE_URL"))
_cheap_key = (
    _kimi_key
    or _strip_env_value(os.getenv("DEEPSEEK_API_KEY"))
    or _strip_env_value(os.getenv("CHEAP_API_KEY"))
)
_cheap_base = (
    _kimi_base
    or _strip_env_value(os.getenv("DEEPSEEK_BASE_URL"))
    or _strip_env_value(os.getenv("CHEAP_BASE_URL"))
)
if _cheap_key and not _cheap_base and _kimi_key:
    _cheap_base = "https://api.moonshot.cn/v1"

# Judge：优先 CHAT_*，兼容 JUDGE_*
_judge_key = _strip_env_value(
    os.getenv("CHAT_API_KEY") or os.getenv("JUDGE_API_KEY")
)
_judge_base = _strip_env_value(
    os.getenv("CHAT_BASE_URL") or os.getenv("JUDGE_BASE_URL")
)

cheap_client = _build_openai_client(
    api_key=_cheap_key,
    base_url=_cheap_base,
    label="cheap_client",
)
judge_client = _build_openai_client(
    api_key=_judge_key,
    base_url=_judge_base,
    label="judge_client",
)

JUDGE_MODEL = _strip_env_value(
    os.getenv("OPENAI_MODEL")
    or os.getenv("GEMINI_MODEL")
    or os.getenv("JUDGE_MODEL")
    or "gpt-4o"
)
if not JUDGE_MODEL:
    JUDGE_MODEL = "gpt-4o"
logger.info("Judge 对话模型: %s", JUDGE_MODEL)

CHEAP_MODEL = _strip_env_value(
    os.getenv("KIMI_MODEL")
    or os.getenv("DEEPSEEK_MODEL")
    or os.getenv("CHEAP_MODEL")
    or "moonshot-v1-8k"
)
if not CHEAP_MODEL:
    CHEAP_MODEL = "moonshot-v1-8k"
logger.info("Cheap 对话模型（默认 Kimi / Moonshot）: %s", CHEAP_MODEL)


# -----------------------------------------------------------------------------
# Markdown 解析
# -----------------------------------------------------------------------------
_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class MarkdownParser:
    """读取目录下 Markdown 并按 ATX 标题（# …）层级切分。"""

    def parse_directory(self, dir_path: str | Path) -> list[dict[str, str]]:
        """
        读取目录下所有 .md 文件。

        Returns:
            每项包含 path（绝对路径字符串）、relative_path、content。
        """
        root = Path(dir_path).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"目录不存在或不是文件夹: {root}")

        results: list[dict[str, str]] = []
        try:
            md_files = sorted(root.glob("*.md"))
        except OSError as exc:
            logger.exception("枚举 Markdown 文件失败: %s", root)
            raise RuntimeError(f"无法读取目录: {root}") from exc

        if not md_files:
            logger.warning("目录中未发现 .md 文件: %s", root)

        for fp in md_files:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.error("读取文件失败（已跳过）: %s — %s", fp, exc)
                continue
            try:
                rel = str(fp.relative_to(root))
            except ValueError:
                rel = fp.name
            results.append(
                {
                    "path": str(fp),
                    "relative_path": rel,
                    "content": text,
                }
            )
            logger.info("已读取 Markdown: %s (%d 字符)", rel, len(text))

        return results

    def chunk_markdown(self, filepath: str | Path, content: str) -> list[dict[str, str]]:
        """
        按 H1–H6 层级切分；每个 chunk 含 source_file、hierarchy、content。

        hierarchy 为从根到当前节的标题链，例如 ``第一章 -> 第二节``。
        正文不包含 ATX 标题行本身。
        """
        source = str(Path(filepath).resolve()) if filepath else ""
        lines = content.splitlines()
        chunks: list[dict[str, str]] = []
        stack: list[tuple[int, str]] = []  # (level 1..6, title text)
        buffer: list[str] = []

        def hierarchy_str() -> str:
            return " -> ".join(title for _, title in stack) if stack else ""

        def flush_buffer() -> None:
            body = "\n".join(buffer).strip()
            buffer.clear()
            if not body:
                return
            h = hierarchy_str()
            chunks.append(
                {
                    "source_file": source,
                    "hierarchy": h if h else "(无前导标题)",
                    "content": body,
                }
            )

        for line in lines:
            m = _ATX_HEADING_RE.match(line)
            if m:
                flush_buffer()
                level = len(m.group(1))
                title = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                continue
            buffer.append(line)

        flush_buffer()
        logger.debug("chunk_markdown: %s -> %d 个块", source or "(内存)", len(chunks))
        return chunks


# -----------------------------------------------------------------------------
# 全局目录生成（Judge）
# -----------------------------------------------------------------------------
class TOCGenerator:
    """从 chunk 抽取标题路径，并调用 judge_client 生成工业 PHM 场景的 Master TOC。"""

    def __init__(
        self,
        client: OpenAI | None = None,
        model: str | None = None,
        master_toc_path: Path | None = None,
    ) -> None:
        self._client = client if client is not None else judge_client
        self._model = (model or JUDGE_MODEL).strip()
        self._master_toc_path = (
            Path(master_toc_path).expanduser().resolve()
            if master_toc_path is not None
            else DEFAULT_MASTER_TOC_PATH
        )

    @staticmethod
    def extract_all_headings(chunks: list[dict[str, str]]) -> str:
        """
        从 MarkdownParser 产出的 chunks 中仅保留层级标题路径（丢弃正文），
        去重后合并为一段大文本（每行一条 ``H1 -> H2 -> …`` 路径）。
        """
        skip = "(无前导标题)"
        seen: set[str] = set()
        lines: list[str] = []
        for ch in chunks:
            h = (ch.get("hierarchy") or "").strip()
            if not h or h == skip:
                continue
            if h in seen:
                continue
            seen.add(h)
            lines.append(h)
        text = "\n".join(lines)
        logger.info(
            "extract_all_headings: %d 条唯一路径（输入 %d 个 chunk）",
            len(lines),
            len(chunks),
        )
        return text

    def generate_master_toc(self, headings_text: str) -> Path:
        """
        调用 judge_client 生成《智能运维知识库全局标准目录》，写入 ``Master_TOC.md``。
        """
        if not headings_text.strip():
            raise ValueError("headings_text 为空，无法生成 Master TOC。")

        system_msg = (
            "你是资深工业设备智能运维（PHM，Prognostics and Health Management）架构师，"
            "熟悉石化等大型流程工业中的旋转机械（压缩机、泵、风机等）、静设备监测、工控网络、PLC/SCADA、"
            "振动与温度等状态监测与故障诊断体系。"
        )
        user_msg = (
            "你是资深工业设备智能运维（PHM）架构师。下面是从多份文档中抽取的大纲标题路径。"
            "请整合为一份全新的、MECE（相互独立、完全穷尽）的"
            "《工业设备智能运维（PHM）知识库全局标准目录 (Master TOC)》。\n\n"
            "硬性要求：\n"
            "1）场景限定：目录必须服务于「物理工业设备与工控现场」PHM，"
            "不得为通用互联网/企业 IT 运维或云原生应用运维单独设章。\n"
            "2）剔除：若原始路径明显属于纯 IT/云原生/微服务/前端与 Web 应用、通用中间件（如 Kubernetes、Redis "
            "纯缓存集群、通用日志 ELK 仅面向软件服务等）且与工业设备/工控现场无关，请直接丢弃，不要写入本目录。\n"
            "3）命名工业化：对偏通用的 AI/数据分析节点名称，须改写为工业 PHM 语境（示例："
            "「调用链分析」→「工业设备关联拓扑与工况传播分析」；"
            "「服务依赖」→「机组/子系统工况与传感器关联依赖」）。\n"
            "4）并集与专名：在工业相关范围内取并集，保留算法名、工业协议、监测指标与设备类专有名词。\n"
            "5）输出格式：严格使用纯 Markdown 列表，只展开到二级或三级目录即可。\n\n"
            "--- 抽取得到的标题路径（每行一条，以 \" -> \" 连接层级）---\n"
            f"{headings_text.strip()}"
        )

        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
            )
        except Exception as exc:
            logger.exception("judge_client 调用失败（Master TOC）。")
            raise RuntimeError("生成 Master TOC 时 API 调用失败。") from exc

        choice0 = completion.choices[0] if completion.choices else None
        raw = choice0.message.content if choice0 and choice0.message else None
        if raw is None or not str(raw).strip():
            logger.error("模型返回空内容，completion=%r", completion)
            raise RuntimeError("生成 Master TOC 失败：模型返回为空。")

        body = str(raw).strip()
        try:
            self._master_toc_path.write_text(body, encoding="utf-8", newline="\n")
        except OSError as exc:
            logger.exception("写入 Master TOC 失败: %s", self._master_toc_path)
            raise RuntimeError(f"无法写入文件: {self._master_toc_path}") from exc

        logger.info("Master TOC 已保存: %s（%d 字符）", self._master_toc_path, len(body))
        return self._master_toc_path


# -----------------------------------------------------------------------------
# 内容路由（Cheap + 并发）
# -----------------------------------------------------------------------------
_MASTER_TOC_ATX_H23 = re.compile(r"^#{2,3}\s+(.+?)\s*$")
_MASTER_TOC_LIST_ITEM = re.compile(
    r"^(\s*)(?:[-*+]|\d+\.)\s+(.*)$",
)


class ContentRouter:
    """
    解析 ``Master_TOC.md`` 得到目标节点，使用 cheap_client 将各 chunk 归类到节点下。
    非工业/纯 IT 内容通过输出 ``IGNORE`` 丢弃，不进入最终 ``routed_data``。
    """

    UNMATCHED = "__未匹配__"
    # 模型在 Prompt 中须对纯 IT/云原生等与物理工业无关的块输出此标记（可写作 IGNORE / [IGNORE] 等）
    IGNORE = "IGNORE"

    def __init__(
        self,
        client: OpenAI | None = None,
        model: str | None = None,
        max_workers: int = 8,
    ) -> None:
        self._client = client if client is not None else cheap_client
        self._model = (model or CHEAP_MODEL).strip()
        self._max_workers = max(1, int(max_workers))

    @staticmethod
    def _clean_node_label(raw: str) -> str:
        s = raw.strip()
        s = re.sub(r"^\[[ xX]\]\s*", "", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        return s.strip()

    @staticmethod
    def parse_master_toc(path: str | Path) -> list[str]:
        """
        从 ``Master_TOC.md`` 提取目标节点：``##`` / ``###`` 标题，以及缩进列表中
        深度为 2、3 的条目（按常见 2 空格一级列表缩进推算）。
        """
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Master TOC 不存在: {p}")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.exception("读取 Master TOC 失败: %s", p)
            raise RuntimeError(f"无法读取 Master TOC: {p}") from exc

        collected: list[str] = []
        seen: set[str] = set()

        def add_node(title: str) -> None:
            label = ContentRouter._clean_node_label(title)
            if not label or label in seen:
                return
            seen.add(label)
            collected.append(label)

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            stripped = line.lstrip()
            if stripped.startswith("#"):
                hm = _MASTER_TOC_ATX_H23.match(stripped)
                if hm:
                    add_node(hm.group(1))
                continue
            lm = _MASTER_TOC_LIST_ITEM.match(line)
            if lm:
                indent = len(lm.group(1).expandtabs(4))
                depth = indent // 2 + 1
                if depth in (2, 3):
                    add_node(lm.group(2))

        if not collected:
            logger.warning(
                "未解析到二级/三级节点，回退为收集所有列表项（深度 >= 1）。文件: %s",
                p.name,
            )
            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                if not line:
                    continue
                lm = _MASTER_TOC_LIST_ITEM.match(line)
                if lm:
                    indent = len(lm.group(1).expandtabs(4))
                    depth = indent // 2 + 1
                    if depth >= 1:
                        add_node(lm.group(2))

        logger.info("parse_master_toc: %d 个目标节点（%s）", len(collected), p.name)
        return collected

    @staticmethod
    def _normalize_for_match(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip()).casefold()

    @staticmethod
    def _is_discard_token(text: str) -> bool:
        """判定模型是否声明丢弃该块（IGNORE / DISCARD 等）。"""
        s = text.strip().strip("\"'「」")
        s = re.sub(r"^[-*•\d.、]+\s*", "", s)
        t = re.sub(r"[\[\]［］]", "", s).strip().casefold().rstrip("。.!！,，;；")
        return t in ("ignore", "discard", "忽略", "丢弃", "废弃")

    @classmethod
    def _resolve_predicted_node(cls, raw: str | None, master_nodes: list[str]) -> str:
        if raw is None:
            return cls.UNMATCHED
        s = raw.strip().strip("\"'「」")
        s = re.sub(r"^[-*•\d.、]+\s*", "", s)
        if not s:
            return cls.UNMATCHED
        if cls._is_discard_token(s):
            return cls.IGNORE
        if s in master_nodes:
            return s
        norm_map = {cls._normalize_for_match(m): m for m in master_nodes}
        key = cls._normalize_for_match(s)
        if key in norm_map:
            return norm_map[key]
        best: str | None = None
        best_len = 0
        for m in master_nodes:
            if m and m in s and len(m) > best_len:
                best = m
                best_len = len(m)
        if best:
            return best
        for m in master_nodes:
            if m and s in m:
                return m
        logger.warning("无法将模型输出匹配到目标节点，归入「%s」: %r", cls.UNMATCHED, s[:200])
        return cls.UNMATCHED

    def _classify_chunk(self, chunk: dict[str, str], industrial_nodes: list[str]) -> str:
        hierarchy = (chunk.get("hierarchy") or "").strip() or "(无层级)"
        industrial_lines = "\n".join(f"- {n}" for n in industrial_nodes)
        user_msg = (
            "你是工业设备智能运维（PHM）知识库编辑助手。场景限定：石化/流程工业等大型机械与工控现场"
            "（压缩机、泵、机组振动、轴承与温度、PLC/工控系统等）。\n\n"
            "【工业目标节点】列表如下：\n"
            f"{industrial_lines}\n\n"
            f"【特殊选项】{self.IGNORE}：若当前内容块与物理工业设备/工控现场无关（例如纯 Kubernetes/微服务/"
            "通用 Redis 缓存集群、前端页面报错、互联网应用发布等），不得归入任一工业节点；"
            f"此时请只输出 {self.IGNORE}，不要输出其它任何字符。\n\n"
            f"当前待归类内容块（仅标题路径）：{hierarchy}\n\n"
            "规则：\n"
            "1）若该块讨论物理工业设备、工况监测、PHM、振动/温度/油液等工业信号、工控与现场运维，"
            "请从【工业目标节点】中选出唯一最匹配的一项，只输出该节点名称（与列表中文字尽量完全一致）。\n"
            "2）否则只输出 IGNORE。\n"
            "3）输出中不要解释、不要标点修饰。"
        )
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0,
            )
        except Exception as exc:
            logger.exception("cheap_client 路由调用失败: hierarchy=%r", hierarchy[:120])
            raise RuntimeError("内容路由 API 调用失败。") from exc
        choice0 = completion.choices[0] if completion.choices else None
        raw = choice0.message.content if choice0 and choice0.message else None
        return self._resolve_predicted_node(raw if raw is None else str(raw), industrial_nodes)

    def route_chunks(
        self,
        master_nodes: list[str],
        chunks: list[dict[str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        """
        将每个 chunk 映射到一个目标节点；返回
        ``{ 节点名: [chunk, ...], ... }``，无法匹配时归入 ``__未匹配__``。
        """
        uniq = list(dict.fromkeys(n.strip() for n in master_nodes if n and n.strip()))
        if not uniq:
            raise ValueError("master_nodes 为空，无法进行路由。")
        if not chunks:
            logger.warning("route_chunks: chunks 为空。")
            empty: dict[str, list[dict[str, str]]] = {k: [] for k in uniq}
            empty[self.UNMATCHED] = []
            return empty

        workers = min(self._max_workers, max(1, len(chunks)))
        result: dict[str, list[dict[str, str]]] = {k: [] for k in uniq}
        result[self.UNMATCHED] = []
        ignored_n = 0

        def work(ch: dict[str, str]) -> tuple[dict[str, str], str]:
            try:
                node = self._classify_chunk(ch, uniq)
            except Exception:
                logger.exception(
                    "单个 chunk 路由 API 失败，归入「%s」。hierarchy=%r",
                    self.UNMATCHED,
                    (ch.get("hierarchy") or "")[:160],
                )
                return ch, self.UNMATCHED
            return ch, node

        logger.info(
            "route_chunks: %d 个 chunk，%d 个工业目标节点，并发数=%d（非工业块将输出 %s 并丢弃）",
            len(chunks),
            len(uniq),
            workers,
            self.IGNORE,
        )
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, ch) for ch in chunks]
            done = 0
            for fut in as_completed(futures):
                ch, node = fut.result()
                if node == self.IGNORE:
                    ignored_n += 1
                    done += 1
                    if done % 20 == 0 or done == len(chunks):
                        logger.info("路由进度: %d / %d", done, len(chunks))
                    continue
                if node not in result:
                    result.setdefault(node, [])
                result[node].append(ch)
                done += 1
                if done % 20 == 0 or done == len(chunks):
                    logger.info("路由进度: %d / %d", done, len(chunks))

        if ignored_n:
            logger.info("已按 PHM 边界过滤（IGNORE）的 chunk 数量: %d", ignored_n)
        unmatched_n = len(result.get(self.UNMATCHED, []))
        if unmatched_n:
            logger.warning("未匹配 chunk 数量: %d", unmatched_n)
        return result


# -----------------------------------------------------------------------------
# 深度融合与落盘（Judge + 追加写入）
# -----------------------------------------------------------------------------
class ContentMerger:
    """将同一工业 PHM 目标节点下的多源 chunk 经 Judge 合并（含场景强制翻译）后追加写入最终 Markdown。"""

    def __init__(
        self,
        client: OpenAI | None = None,
        model: str | None = None,
    ) -> None:
        self._client = client if client is not None else judge_client
        self._model = (model or JUDGE_MODEL).strip()

    @staticmethod
    def _combine_reference_blob(chunks: list[dict[str, str]]) -> str:
        parts: list[str] = []
        for i, ch in enumerate(chunks, 1):
            src = (ch.get("source_file") or "").strip()
            hier = (ch.get("hierarchy") or "").strip()
            body = (ch.get("content") or "").strip()
            parts.append(
                f"【参考块 {i}】\n"
                f"- 来源文件: {src}\n"
                f"- 标题路径: {hier}\n\n"
                f"{body}"
            )
        return "\n\n---\n\n".join(parts)

    def _call_judge_merge(self, node_name: str, reference_blob: str) -> str:
        system_msg = (
            "你是严谨的工业设备智能运维（PHM）技术文档合并专家，"
            "熟悉石化等流程工业中的机组、旋转机械、振动监测与工控系统，"
            "擅长在保持信息完整的前提下将多源材料整合为现场可用的技术叙述。"
        )
        user_msg = (
            f"你是一个严谨的技术文档合并专家。当前章节是：[{node_name}]。"
            "知识库场景严格限定为「工业设备 PHM」：大型机组/压缩机/泵/风机、轴承与密封、"
            "润滑油与油液、振动与温度等监测、工控系统与 PLC/SCADA、现场运维与故障诊断等；"
            "不得展开为通用互联网 IT、云原生应用运维或纯软件微服务体系的主线叙述。\n\n"
            "以下是来自不同来源的相关参考内容：\n"
            f"{reference_blob}\n\n"
            "请对这些内容进行高信息密度的无损合并，生成该章节的详细内容。\n"
            "严格要求：\n"
            "1）并集原则：信息合并而非删减观点；保留算法名、工业专有名词、现场工具与最佳实践。\n"
            "2）禁止为省篇幅而概括掉可操作细节。\n"
            "3）场景强制翻译：正文举例、类比与默认场景必须落在工业 PHM 上。"
            "若参考资料使用通用 IT 举例（如 CPU 飙高、Redis 缓存、前端报错、K8s Pod 重启等），"
            "须在合并稿中改写为工业等价场景（如轴承温度突升、机组振动谱能量增高、PLC 通信中断、"
            "泵入口压力波动、润滑油温升等）；不得保留与工业现场无关的纯 IT 案例作为主例证。\n"
            "4）使用 Markdown 格式输出。"
        )
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
            )
        except Exception as exc:
            logger.exception("judge_client 章节合并失败: %s", node_name)
            raise RuntimeError(f"章节「{node_name}」合并 API 调用失败。") from exc
        choice0 = completion.choices[0] if completion.choices else None
        raw = choice0.message.content if choice0 and choice0.message else None
        if raw is None or not str(raw).strip():
            raise RuntimeError(f"章节「{node_name}」合并失败：模型返回为空。")
        return str(raw).strip()

    def merge_and_save(
        self,
        routed_data: dict[str, list[dict[str, str]]],
        output_file: str | Path = "Final_Knowledge_Base.md",
    ) -> Path:
        """
        按目标节点遍历 ``routed_data``，合并各节点下 chunk 正文，调用 Judge 后**追加**写入输出文件。
        开始前会清空（若存在）输出文件；随后每一章完成后立即 ``open(..., \"a\")`` 写入。
        """
        out = Path(output_file).expanduser()
        if not out.is_absolute():
            out = LLM_ANSWERS_ROOT / out
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.exception("创建输出目录失败: %s", out.parent)
            raise RuntimeError(f"无法创建目录: {out.parent}") from exc

        try:
            if out.exists():
                out.unlink()
        except OSError as exc:
            logger.exception("无法清空旧输出文件: %s", out)
            raise RuntimeError(f"无法准备输出文件: {out}") from exc

        written = 0
        for node_name, chunks in routed_data.items():
            if node_name == ContentRouter.UNMATCHED:
                if chunks:
                    logger.warning(
                        "跳过「%s」下 %d 个块，不写入最终知识库。",
                        ContentRouter.UNMATCHED,
                        len(chunks),
                    )
                continue
            if not chunks:
                logger.info("节点「%s」无内容，跳过。", node_name)
                continue

            blob = self._combine_reference_blob(chunks)
            if not blob.strip():
                logger.warning("节点「%s」参考内容为空，跳过。", node_name)
                continue

            try:
                merged = self._call_judge_merge(node_name, blob)
            except RuntimeError as exc:
                logger.error("%s", exc)
                continue

            try:
                with out.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(merged)
                    fh.write("\n\n")
            except OSError as exc:
                logger.exception("追加写入失败: %s", out)
                raise RuntimeError(f"无法写入: {out}") from exc

            written += 1
            logger.info(
                "已追加章节「%s」（第 %d 章，本段 %d 字符）",
                node_name,
                written,
                len(merged),
            )

        if written == 0:
            logger.warning("未写入任何章节，输出文件可能为空: %s", out)
        else:
            logger.info("深度融合完成：共 %d 章 → %s", written, out)
        return out


def _should_skip_source_md(relative_path: str) -> bool:
    name = Path(relative_path).name.lower()
    return name in SKIP_SOURCE_MD_NAMES


def collect_source_chunks() -> list[dict[str, str]]:
    """读取工作区源 Markdown（排除 Master_TOC / 最终输出等），并分块。"""
    md_parser = MarkdownParser()
    files = md_parser.parse_directory(DEFAULT_MD_DIR)
    files = [it for it in files if not _should_skip_source_md(it["relative_path"])]
    all_chunks: list[dict[str, str]] = []
    for item in files:
        all_chunks.extend(md_parser.chunk_markdown(item["path"], item["content"]))
    return all_chunks


def run_content_route_pipeline(max_workers: int = 8) -> None:
    """阶段三：解析源文档 → 解析 Master TOC → cheap 并发路由（调用 API）。"""
    router = ContentRouter(max_workers=max_workers)
    if not DEFAULT_MD_DIR.is_dir():
        logger.error("工作目录无效: %s", DEFAULT_MD_DIR)
        sys.exit(1)
    if not DEFAULT_MASTER_TOC_PATH.is_file():
        logger.error("未找到 %s，请先运行 master-toc。", DEFAULT_MASTER_TOC_PATH)
        sys.exit(2)

    try:
        master_nodes = ContentRouter.parse_master_toc(DEFAULT_MASTER_TOC_PATH)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(2)

    all_chunks = collect_source_chunks()
    logger.info("待路由 chunk 总数: %d（已排除跳过列表中的源文件）", len(all_chunks))

    try:
        routed = router.route_chunks(master_nodes, all_chunks)
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(1)

    for node, lst in sorted(routed.items(), key=lambda x: (-len(x[1]), x[0])):
        logger.info("  「%s」: %d 块", node, len(lst))
    logger.info("路由完成，共 %d 个分组键。", len(routed))


def run_parse_only() -> None:
    """阶段一：仅解析目录与分块（不调用 API）。"""
    md_parser = MarkdownParser()
    if not DEFAULT_MD_DIR.is_dir():
        logger.error("工作目录无效: %s", DEFAULT_MD_DIR)
        sys.exit(1)
    files = md_parser.parse_directory(DEFAULT_MD_DIR)
    total_chunks = 0
    for item in files:
        chunks = md_parser.chunk_markdown(item["path"], item["content"])
        total_chunks += len(chunks)
        logger.info("  %s: %d 个 chunk", item["relative_path"], len(chunks))
    logger.info("共 %d 个文件, %d 个 chunk。", len(files), total_chunks)


def run_master_toc_pipeline() -> None:
    """阶段二：解析 → 抽取标题 → Judge 生成 Master_TOC.md（会调用 API）。"""
    toc_gen = TOCGenerator()
    if not DEFAULT_MD_DIR.is_dir():
        logger.error("工作目录无效: %s", DEFAULT_MD_DIR)
        sys.exit(1)

    all_chunks = collect_source_chunks()
    logger.info("合并后共 %d 个 chunk（已排除跳过列表中的源文件）。", len(all_chunks))

    headings_text = toc_gen.extract_all_headings(all_chunks)
    if not headings_text.strip():
        logger.error("未抽取到任何标题路径，请检查 Markdown 是否包含 ATX 标题（#）。")
        sys.exit(2)

    try:
        out_path = toc_gen.generate_master_toc(headings_text)
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(1)
    logger.info("完成。输出文件: %s", out_path)


def run_merge_pipeline(
    max_workers: int = 8,
    output_file: str | Path = "Final_Knowledge_Base.md",
) -> None:
    """阶段三+四：在已有 Master_TOC.md 前提下路由并深度融合（会多次调用 API）。"""
    if not DEFAULT_MD_DIR.is_dir():
        logger.error("工作目录无效: %s", DEFAULT_MD_DIR)
        sys.exit(1)
    if not DEFAULT_MASTER_TOC_PATH.is_file():
        logger.error("未找到 %s，请先运行 master-toc 或 full。", DEFAULT_MASTER_TOC_PATH)
        sys.exit(2)

    try:
        master_nodes = ContentRouter.parse_master_toc(DEFAULT_MASTER_TOC_PATH)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(2)

    all_chunks = collect_source_chunks()
    router = ContentRouter(max_workers=max_workers)
    try:
        routed = router.route_chunks(master_nodes, all_chunks)
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(1)

    merger = ContentMerger()
    try:
        merger.merge_and_save(routed, output_file=output_file)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)


def run_full_pipeline(
    max_workers: int = 8,
    output_file: str | Path = "Final_Knowledge_Base.md",
) -> None:
    """完整四阶段：分块 → Master TOC → 路由 → 深度融合落盘。"""
    if not DEFAULT_MD_DIR.is_dir():
        logger.error("工作目录无效: %s", DEFAULT_MD_DIR)
        sys.exit(1)

    all_chunks = collect_source_chunks()
    logger.info("阶段 1/4：分块完成，共 %d 个 chunk。", len(all_chunks))

    toc_gen = TOCGenerator()
    headings_text = toc_gen.extract_all_headings(all_chunks)
    if not headings_text.strip():
        logger.error("未抽取到任何标题路径，请检查 Markdown 是否包含 ATX 标题（#）。")
        sys.exit(2)

    logger.info("阶段 2/4：调用 Judge 生成 Master TOC …")
    try:
        toc_gen.generate_master_toc(headings_text)
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(1)

    try:
        master_nodes = ContentRouter.parse_master_toc(DEFAULT_MASTER_TOC_PATH)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(2)

    logger.info("阶段 3/4：Cheap 并发路由 …")
    router = ContentRouter(max_workers=max_workers)
    try:
        routed = router.route_chunks(master_nodes, all_chunks)
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(1)

    logger.info("阶段 4/4：Judge 深度融合并追加写入 …")
    merger = ContentMerger()
    try:
        merger.merge_and_save(routed, output_file=output_file)
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    out_final = Path(output_file).expanduser()
    if not out_final.is_absolute():
        out_final = LLM_ANSWERS_ROOT / out_final
    logger.info("全流程结束。Master TOC: %s；知识库: %s", DEFAULT_MASTER_TOC_PATH, out_final)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="LLMAnswers：Markdown 解析、Master TOC、路由与深度融合流水线。",
    )
    ap.add_argument(
        "command",
        nargs="?",
        default="parse",
        choices=("parse", "master-toc", "route", "merge", "full"),
        help=(
            "parse=仅分块；master-toc=生成 Master_TOC.md；route=仅路由；"
            "merge=路由+深度融合；full=四阶段一键跑完"
        ),
    )
    ap.add_argument(
        "-j",
        "--workers",
        type=int,
        default=8,
        metavar="N",
        help="route / merge / full 时路由并发数（默认 8）",
    )
    ap.add_argument(
        "-o",
        "--output",
        default="Final_Knowledge_Base.md",
        metavar="FILE",
        help="merge / full 输出文件名或路径（默认 Final_Knowledge_Base.md，相对 LLMAnswers/）",
    )
    args = ap.parse_args()
    if args.command == "parse":
        run_parse_only()
    elif args.command == "master-toc":
        run_master_toc_pipeline()
    elif args.command == "route":
        run_content_route_pipeline(max_workers=args.workers)
    elif args.command == "merge":
        run_merge_pipeline(max_workers=args.workers, output_file=args.output)
    else:
        run_full_pipeline(max_workers=args.workers, output_file=args.output)


if __name__ == "__main__":
    main()
