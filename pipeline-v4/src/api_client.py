"""Unified API client for 4 LLM providers: Gemini, OpenAI, DeepSeek, Kimi (Moonshot).

Configuration is read from environment variables (loaded via .env).

Gemini + ChatGPT can share one OpenAI-compatible relay (中转站):
  CHAT_API_KEY + CHAT_BASE_URL + GEMINI_MODEL + OPENAI_MODEL
When CHAT_API_KEY is set, call_gemini / call_openai both use this relay with
their respective model IDs (as exposed by the relay).

Fallback when CHAT_API_KEY is unset:
  - Gemini: Google AI Studio (GEMINI_API_KEY + google-generativeai, lazy-imported)
  - ChatGPT: OPENAI_API_KEY + OPENAI_BASE_URL
"""

import time
import logging
from typing import Callable, Optional

from openai import OpenAI

from utils import env, TokenTracker

logger = logging.getLogger(__name__)

# DeepSeek API: max_tokens must be in [1, 8192] for chat/completions
DEEPSEEK_MAX_TOKENS_CAP = int(env("DEEPSEEK_MAX_TOKENS_CAP", "8192"))

# 启动前连通性检测用（极短补全，不计入业务 Token 统计）
_PING_SYSTEM = "你只输出单词 OK，不要其它内容。"
_PING_USER = "连通性检测，请回复 OK。"
_PING_MAX_TOKENS = 8


def _assistant_message_text(message) -> str:
    """Normalize assistant `content` (str, None, or list of parts) to plain text."""
    c = getattr(message, "content", None)
    if isinstance(c, str) and c.strip():
        return c.strip()
    if isinstance(c, list):
        parts: list[str] = []
        for part in c:
            if isinstance(part, dict):
                if part.get("type") == "text" and part.get("text"):
                    parts.append(str(part["text"]))
            else:
                t = getattr(part, "text", None)
                if t:
                    parts.append(str(t))
        return "".join(parts).strip()
    return ""


class LLMClient:
    """Unified interface for calling multiple LLM providers."""

    def __init__(self, token_tracker: Optional[TokenTracker] = None):
        self.token_tracker = token_tracker or TokenTracker()
        self._genai_configured = False
        self._init_clients()

    def _init_clients(self):
        # ── OpenAI-compatible relay (中转站): Gemini + ChatGPT ──
        chat_key = env("CHAT_API_KEY")
        chat_base = env("CHAT_BASE_URL", "https://api.chatanywhere.tech/v1")
        self._relay_client = OpenAI(api_key=chat_key, base_url=chat_base) if chat_key else None

        # Model IDs on the relay (must match what your provider lists)
        self._gemini_model = env("GEMINI_MODEL", "gemini-2.5-pro")
        self._openai_model = env("OPENAI_MODEL", "gpt-4o")

        # ── Native Gemini (only when not using relay for Gemini) ──
        gemini_key = env("GEMINI_API_KEY")
        self._gemini_native_key = gemini_key if (gemini_key and not self._relay_client) else None

        # ── Direct OpenAI (only when relay is not configured) ──
        openai_key = env("OPENAI_API_KEY")
        self._openai_direct = None
        if openai_key and not self._relay_client:
            self._openai_direct = OpenAI(
                api_key=openai_key,
                base_url=env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )

        # DeepSeek (OpenAI-compatible)
        deepseek_key = env("DEEPSEEK_API_KEY")
        self._deepseek_client = OpenAI(
            api_key=deepseek_key,
            base_url=env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        ) if deepseek_key else None
        self._deepseek_model = env("DEEPSEEK_MODEL", "deepseek-chat")

        # Kimi（月之暗面 Moonshot，OpenAI 兼容接口）
        kimi_key = env("KIMI_API_KEY")
        kimi_base = env("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
        self._kimi_client = OpenAI(
            api_key=kimi_key,
            base_url=kimi_base,
        ) if kimi_key else None
        self._kimi_model = env("KIMI_MODEL", "kimi-k2.6")
        # Moonshot kimi-k2.6 等模型仅允许 temperature=1，否则会 400
        self._kimi_temperature = float(env("KIMI_TEMPERATURE", "1"))

    def _ensure_native_genai(self):
        """Lazy import google.generativeai only for Google-direct Gemini (avoids deprecation warning for relay-only users)."""
        import google.generativeai as genai

        if not self._genai_configured:
            genai.configure(api_key=self._gemini_native_key)
            self._genai_configured = True
        return genai

    # ── Startup connectivity checks ───────────────────────────

    def _ping_openai_compatible(
        self,
        client: OpenAI,
        model: str,
        label: str,
        timeout: float = 60.0,
        temperature: float = 0.0,
    ) -> None:
        """One minimal chat completion; raises RuntimeError on failure."""
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _PING_SYSTEM},
                    {"role": "user", "content": _PING_USER},
                ],
                temperature=temperature,
                max_tokens=_PING_MAX_TOKENS,
                timeout=timeout,
            )
        except Exception as e:
            raise RuntimeError(f"{label}（model={model}）: {e}") from e
        if not response.choices:
            raise RuntimeError(f"{label}（model={model}）: 无 choices")

        msg = response.choices[0].message
        text = _assistant_message_text(msg)
        usage = response.usage
        completion_tokens = usage.completion_tokens if usage else 0

        # 部分中转/模型在短探测下返回 200 但 content 为空；若已有 completion 消耗则视为链路可用
        if text:
            return
        if completion_tokens > 0:
            logger.info(
                "%s（model=%s）: 探测返回空文本但 completion_tokens=%s，视为连接可用",
                label,
                model,
                completion_tokens,
            )
            return
        raise RuntimeError(
            f"{label}（model={model}）: 空响应（且无 completion_tokens，可能是模型/Key 类型不匹配）"
        )

    def _ping_gemini(self) -> None:
        if self._relay_client:
            self._ping_openai_compatible(
                self._relay_client, self._gemini_model, "中转站 · Gemini"
            )
            return
        if self._gemini_native_key:
            genai = self._ensure_native_genai()
            try:
                model = genai.GenerativeModel(model_name=self._gemini_model)
                response = model.generate_content(
                    _PING_USER,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0,
                        max_output_tokens=_PING_MAX_TOKENS,
                    ),
                )
            except Exception as e:
                raise RuntimeError(
                    f"Google Gemini 直连（model={self._gemini_model}）: {e}"
                ) from e
            if not response.text:
                raise RuntimeError(
                    f"Google Gemini 直连（model={self._gemini_model}）: 空响应"
                )
            return
        raise RuntimeError(
            "Gemini 未配置：请在 .env 中设置 CHAT_API_KEY（中转）或 GEMINI_API_KEY（直连）"
        )

    def _ping_openai(self) -> None:
        if self._relay_client:
            self._ping_openai_compatible(
                self._relay_client, self._openai_model, "中转站 · ChatGPT"
            )
            return
        if self._openai_direct:
            self._ping_openai_compatible(
                self._openai_direct, self._openai_model, "OpenAI 直连"
            )
            return
        raise RuntimeError(
            "ChatGPT 未配置：请在 .env 中设置 CHAT_API_KEY（中转）或 OPENAI_API_KEY（直连）"
        )

    def _ping_deepseek(self) -> None:
        if not self._deepseek_client:
            raise RuntimeError("DeepSeek 未配置：请设置 DEEPSEEK_API_KEY")
        self._ping_openai_compatible(
            self._deepseek_client, self._deepseek_model, "DeepSeek"
        )

    def _ping_kimi(self) -> None:
        if not self._kimi_client:
            raise RuntimeError("Kimi 未配置：请设置 KIMI_API_KEY（Moonshot 开放平台）")
        self._ping_openai_compatible(
            self._kimi_client,
            self._kimi_model,
            "Kimi",
            temperature=self._kimi_temperature,
        )

    def verify_required_endpoints(
        self,
        *,
        full: bool = False,
        stage: Optional[int] = None,
    ) -> None:
        """
        按本次运行模式检测会用到的 LLM 端点；任一失败则抛出 RuntimeError。

        - full: Gemini + ChatGPT + DeepSeek + Kimi
        - stage 1: Gemini + ChatGPT + DeepSeek
        - stage 2: Kimi
        - stage 3: Gemini
        """
        checks: list[tuple[str, Callable[[], None]]] = []
        if full:
            checks = [
                ("Gemini", self._ping_gemini),
                ("ChatGPT", self._ping_openai),
                ("DeepSeek", self._ping_deepseek),
                ("Kimi", self._ping_kimi),
            ]
        elif stage == 1:
            checks = [
                ("Gemini", self._ping_gemini),
                ("ChatGPT", self._ping_openai),
                ("DeepSeek", self._ping_deepseek),
            ]
        elif stage == 2:
            checks = [("Kimi", self._ping_kimi)]
        elif stage == 3:
            checks = [("Gemini", self._ping_gemini)]

        failures: list[str] = []
        for name, fn in checks:
            try:
                fn()
                logger.info("Connectivity OK: %s", name)
            except Exception as e:
                failures.append(f"{name}: {e}")
                logger.warning("Connectivity failed: %s — %s", name, e)

        if failures:
            detail = "\n".join(f"  • {line}" for line in failures)
            raise RuntimeError(
                "启动前连接检查未通过，请检查网络、API Key、BASE_URL 与 MODEL 是否与中转站一致：\n"
                + detail
            )

    # ── Public interface ──────────────────────────────────────

    def call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        stage: str = "unknown",
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> str:
        return self._call_with_retry(
            self._call_gemini_once, system_prompt, user_prompt,
            stage, temperature, max_tokens,
        )

    def call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        stage: str = "unknown",
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> str:
        return self._call_with_retry(
            self._call_openai_once, system_prompt, user_prompt,
            stage, temperature, max_tokens,
        )

    def call_deepseek(
        self,
        system_prompt: str,
        user_prompt: str,
        stage: str = "unknown",
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> str:
        return self._call_with_retry(
            self._call_deepseek_once, system_prompt, user_prompt,
            stage, temperature, max_tokens,
        )

    def call_kimi(
        self,
        system_prompt: str,
        user_prompt: str,
        stage: str = "unknown",
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> str:
        return self._call_with_retry(
            self._call_kimi_once, system_prompt, user_prompt,
            stage, temperature, max_tokens,
        )

    # ── Retry wrapper ─────────────────────────────────────────

    def _call_with_retry(self, fn, system_prompt, user_prompt,
                         stage, temperature, max_tokens, max_retries=3):
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[{stage}] Calling {fn.__name__} (attempt {attempt})")
                return fn(system_prompt, user_prompt, stage, temperature, max_tokens)
            except Exception as e:
                last_error = e
                logger.warning(f"[{stage}] {fn.__name__} attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)
        raise RuntimeError(
            f"All {max_retries} attempts failed for {fn.__name__} in [{stage}]. Last error: {last_error}"
        )

    def _call_chat_completions(
        self,
        client: OpenAI,
        model: str,
        label: str,
        system_prompt: str,
        user_prompt: str,
        stage: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        pt = response.usage.prompt_tokens if response.usage else 0
        ct = response.usage.completion_tokens if response.usage else 0
        self.token_tracker.add(f"{label}/{model}", stage, pt, ct)
        if not response.choices:
            raise RuntimeError("API 返回无 choices")
        text = _assistant_message_text(response.choices[0].message)
        if text:
            return text
        if ct > 0:
            logger.warning(
                "[%s] %s 返回空文本但 completion_tokens=%s，请检查中转/模型是否将正文放在非标准字段",
                stage,
                label,
                ct,
            )
        raise RuntimeError(
            f"{label} 返回空 assistant 内容（model={model}），请检查模型与 API 兼容性"
        )

    # ── Provider implementations ──────────────────────────────

    def _call_gemini_once(self, system_prompt, user_prompt, stage, temperature, max_tokens):
        if self._relay_client:
            return self._call_chat_completions(
                self._relay_client,
                self._gemini_model,
                "relay-gemini",
                system_prompt,
                user_prompt,
                stage,
                temperature,
                max_tokens,
            )
        if self._gemini_native_key:
            genai = self._ensure_native_genai()
            model = genai.GenerativeModel(
                model_name=self._gemini_model,
                system_instruction=system_prompt,
            )
            response = model.generate_content(
                user_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            pt = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
            ct = response.usage_metadata.candidates_token_count if response.usage_metadata else 0
            self.token_tracker.add(f"gemini-native/{self._gemini_model}", stage, pt, ct)
            return response.text
        raise RuntimeError(
            "Gemini not configured. Set CHAT_API_KEY (中转 OpenAI 兼容) or GEMINI_API_KEY (Google 直连) in .env"
        )

    def _call_openai_once(self, system_prompt, user_prompt, stage, temperature, max_tokens):
        if self._relay_client:
            return self._call_chat_completions(
                self._relay_client,
                self._openai_model,
                "relay-openai",
                system_prompt,
                user_prompt,
                stage,
                temperature,
                max_tokens,
            )
        if self._openai_direct:
            return self._call_chat_completions(
                self._openai_direct,
                self._openai_model,
                "openai",
                system_prompt,
                user_prompt,
                stage,
                temperature,
                max_tokens,
            )
        raise RuntimeError(
            "ChatGPT / OpenAI not configured. Set CHAT_API_KEY (中转) or OPENAI_API_KEY (直连) in .env"
        )

    def _call_deepseek_once(self, system_prompt, user_prompt, stage, temperature, max_tokens):
        if not self._deepseek_client:
            raise RuntimeError("DeepSeek not configured. Set DEEPSEEK_API_KEY in .env")
        capped = min(max_tokens, DEEPSEEK_MAX_TOKENS_CAP)
        if capped < max_tokens:
            logger.info(
                "[%s] DeepSeek max_tokens %s 超过上限，已截断为 %s",
                stage,
                max_tokens,
                capped,
            )
        return self._call_chat_completions(
            self._deepseek_client,
            self._deepseek_model,
            "deepseek",
            system_prompt,
            user_prompt,
            stage,
            temperature,
            capped,
        )

    def _call_kimi_once(self, system_prompt, user_prompt, stage, temperature, max_tokens):
        if not self._kimi_client:
            raise RuntimeError("Kimi not configured. Set KIMI_API_KEY in .env (Moonshot)")
        eff_temp = self._kimi_temperature
        if abs(temperature - eff_temp) > 1e-9:
            logger.info(
                "[%s] Kimi 当前使用 KIMI_TEMPERATURE=%s（忽略传入的 %s）",
                stage,
                eff_temp,
                temperature,
            )
        return self._call_chat_completions(
            self._kimi_client,
            self._kimi_model,
            "kimi",
            system_prompt,
            user_prompt,
            stage,
            eff_temp,
            max_tokens,
        )
