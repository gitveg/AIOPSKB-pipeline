"""
BaseAgent — 所有智能体的共享基础设施

从 main.py 提取的 LLM 客户端构建、调用重试、环境加载等逻辑。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
OUTLINES_DIR = PROJECT_ROOT / "outlines"
REVIEWS_DIR = PROJECT_ROOT / "reviews"
DATA_DIR = PROJECT_ROOT / "data"
RESEARCH_DIR = PROJECT_ROOT / "research"
ENV_PATH = PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# 工具函数
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


def _strip_code_block(text: str) -> str:
    """剥离 LLM 输出中可能存在的 ```json ... ``` 包裹。"""
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n", 1)
        if len(lines) > 1:
            first = lines[0].strip()
            if re.match(r"^```\w*$", first):
                s = lines[1]
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3].rstrip()
    return s.strip()


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent:
    """智能体基类，提供 LLM 客户端构建和调用重试。"""

    def __init__(self) -> None:
        self._load_env()
        self.client, self.model = self._build_client()

    # -- 环境加载 --

    def _load_env(self) -> None:
        if ENV_PATH.is_file():
            load_dotenv(ENV_PATH, override=False)
            logger.info("已加载 .env: %s", ENV_PATH)
        else:
            logger.warning("未找到 .env: %s", ENV_PATH)

    # -- 客户端构建 --

    def _build_client(self) -> tuple[OpenAI, str]:
        """按优先级构建 LLM 客户端，返回 (client, model_name)。"""
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

    def _build_gemini_client(self) -> tuple[OpenAI, str]:
        """构建专用 Gemini 客户端（用于评估等高质量需求场景）。"""
        api_key = _strip(os.getenv("CHAT_API_KEY"))
        base_url = _strip(os.getenv("CHAT_BASE_URL"))
        model = _strip(os.getenv("GEMINI_MODEL"))
        if not api_key or not model:
            raise RuntimeError("需要 CHAT_API_KEY 和 GEMINI_MODEL 配置。")
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url.rstrip("/")
        client = OpenAI(**kwargs)
        logger.info("Gemini 客户端 | model=%s", model)
        return client, model

    # -- LLM 调用 --

    def call_llm(
        self,
        messages: list[dict[str, str]],
        max_retries: int = 3,
        temperature: float = 0.2,
        max_tokens: int = 65536,
    ) -> str:
        """调用 LLM API，失败时指数退避重试。"""
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = resp.choices[0].message.content if resp.choices else None
                if not content or not content.strip():
                    raise RuntimeError("模型返回为空。")
                content = _strip_code_block(content)
                usage = resp.usage
                if usage:
                    logger.info(
                        "API 调用成功 (attempt %d) | prompt=%d completion=%d",
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

    def call_llm_json(
        self,
        messages: list[dict[str, str]],
        max_retries: int = 3,
    ) -> Any:
        """调用 LLM 并解析 JSON 响应。"""
        raw = self.call_llm(messages, max_retries=max_retries)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON 块
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
            if match:
                return json.loads(match.group(1).strip())
            raise

    # -- 版本管理 --

    def detect_latest_version(self) -> int:
        """检测 outlines/ 目录中最新的版本号。"""
        max_ver = 0
        v1_path = OUTLINES_DIR / "Merged_PHM_TOC.md"
        if v1_path.is_file():
            max_ver = 1
        for fp in OUTLINES_DIR.glob("Merged_PHM_TOC_v*.md"):
            m = re.match(r"Merged_PHM_TOC_v(\d+)\.md", fp.name)
            if m:
                max_ver = max(max_ver, int(m.group(1)))
        return max_ver

    def get_merged_path(self, version: int) -> Path:
        if version <= 1:
            return OUTLINES_DIR / "Merged_PHM_TOC.md"
        return OUTLINES_DIR / f"Merged_PHM_TOC_v{version}.md"

    def get_kb_path(self, version: int) -> Path:
        """新 pipeline 输出路径。"""
        return OUTLINES_DIR / f"KB_v{version}.md"

    def get_eval_path(self, version: int) -> Path:
        return REVIEWS_DIR / f"Evaluation_v{version}.md"
