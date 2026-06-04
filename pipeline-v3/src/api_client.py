"""Unified API client for 4 LLM providers: OpenAI, DeepSeek, Gemini, Zhipu (GLM)."""

import time
import logging
from typing import Optional

from openai import OpenAI
import google.generativeai as genai
from zhipuai import ZhipuAI

from utils import load_config, load_model_assignment, TokenTracker

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ["openai", "deepseek", "gemini", "zhipu"]


class LLMClient:
    """Unified interface for calling multiple LLM providers."""

    def __init__(self, token_tracker: Optional[TokenTracker] = None):
        config = load_config()
        self.api_keys = {
            "openai": config.get("openai_api_key", ""),
            "deepseek": config.get("deepseek_api_key", ""),
            "gemini": config.get("gemini_api_key", ""),
            "zhipu": config.get("zhipu_api_key", ""),
        }
        self.api_base_urls = {
            "deepseek": config.get("deepseek_base_url", "https://api.deepseek.com/v1"),
        }
        self.token_tracker = token_tracker or TokenTracker()

        self._openai_client = OpenAI(api_key=self.api_keys["openai"]) if self.api_keys["openai"] else None
        self._deepseek_client = OpenAI(
            api_key=self.api_keys["deepseek"],
            base_url=self.api_base_urls["deepseek"],
        ) if self.api_keys["deepseek"] else None

        if self.api_keys["zhipu"]:
            self._zhipu_client = ZhipuAI(api_key=self.api_keys["zhipu"])
        else:
            self._zhipu_client = None

        if self.api_keys["gemini"]:
            genai.configure(api_key=self.api_keys["gemini"])
        self._gemini_configured = bool(self.api_keys["gemini"])

    def call(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        stage: str = "unknown",
        max_retries: int = 3,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> str:
        """Call an LLM with retry logic and return the response text."""
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Supported: {SUPPORTED_PROVIDERS}")

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[{stage}] Calling {provider}/{model} (attempt {attempt})")
                result = self._dispatch(provider, model, system_prompt, user_prompt, temperature, max_tokens)
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"[{stage}] {provider}/{model} attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)

        raise RuntimeError(
            f"All {max_retries} attempts failed for {provider}/{model} in stage [{stage}]. Last error: {last_error}"
        )

    def _dispatch(self, provider: str, model: str, system_prompt: str, user_prompt: str,
                  temperature: float, max_tokens: int) -> str:
        if provider == "openai":
            return self._call_openai(model, system_prompt, user_prompt, temperature, max_tokens)
        elif provider == "deepseek":
            return self._call_deepseek(model, system_prompt, user_prompt, temperature, max_tokens)
        elif provider == "gemini":
            return self._call_gemini(model, system_prompt, user_prompt, temperature, max_tokens)
        elif provider == "zhipu":
            return self._call_zhipu(model, system_prompt, user_prompt, temperature, max_tokens)
        return ""

    def _track(self, provider: str, model: str, stage: str, usage: dict):
        self.token_tracker.add(
            model=f"{provider}/{model}",
            stage=stage,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    # ── OpenAI (ChatGPT) ──────────────────────────────────────

    def _call_openai(self, model: str, system_prompt: str, user_prompt: str,
                     temperature: float, max_tokens: int) -> str:
        if not self._openai_client:
            raise RuntimeError("OpenAI client not initialized. Check openai_api_key in config.yaml")
        response = self._openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        }
        self._track("openai", model, "unknown", usage)
        return response.choices[0].message.content

    # ── DeepSeek (OpenAI-compatible) ──────────────────────────

    def _call_deepseek(self, model: str, system_prompt: str, user_prompt: str,
                       temperature: float, max_tokens: int) -> str:
        if not self._deepseek_client:
            raise RuntimeError("DeepSeek client not initialized. Check deepseek_api_key in config.yaml")
        response = self._deepseek_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        self._track("deepseek", model, "unknown", usage)
        return response.choices[0].message.content

    # ── Gemini ────────────────────────────────────────────────

    def _call_gemini(self, model: str, system_prompt: str, user_prompt: str,
                     temperature: float, max_tokens: int) -> str:
        if not self._gemini_configured:
            raise RuntimeError("Gemini not configured. Check gemini_api_key in config.yaml")
        gemini_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
        )
        response = gemini_model.generate_content(
            user_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        prompt_tokens = response.usage_metadata.prompt_token_count if response.usage_metadata else 0
        completion_tokens = response.usage_metadata.candidates_token_count if response.usage_metadata else 0
        self._track("gemini", model, "unknown", {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        })
        return response.text

    # ── Zhipu (GLM) ───────────────────────────────────────────

    def _call_zhipu(self, model: str, system_prompt: str, user_prompt: str,
                    temperature: float, max_tokens: int) -> str:
        if not self._zhipu_client:
            raise RuntimeError("Zhipu client not initialized. Check zhipu_api_key in config.yaml")
        response = self._zhipu_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
            "completion_tokens": getattr(response.usage, "completion_tokens", 0),
        }
        self._track("zhipu", model, "unknown", usage)
        return response.choices[0].message.content


class AgentRouter:
    """Routes each agent role to the correct provider/model based on model_assignment.yaml."""

    def __init__(self, client: LLMClient):
        self.client = client
        self.assignment = load_model_assignment()

    def _get_config(self, agent: str) -> tuple[str, str]:
        agent_config = self.assignment.get("agents", {}).get(agent)
        if not agent_config:
            raise ValueError(f"Agent '{agent}' not found in model_assignment.yaml")
        return agent_config["provider"], agent_config["model"]

    def call_agent(
        self,
        agent: str,
        system_prompt: str,
        user_prompt: str,
        stage: str = "unknown",
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> str:
        provider, model = self._get_config(agent)
        logger.info(f"[{stage}] Agent={agent} → {provider}/{model}")
        return self.client.call(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stage=stage,
            temperature=temperature,
            max_tokens=max_tokens,
        )
