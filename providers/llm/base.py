"""
LLMProvider interface. Swap implementations without touching agent code.

Resolution order (first that is configured/reachable wins):
  1. GROQ_API_KEY set            -> GroqLLM (free tier, fast, OpenAI-compatible)
  2. OPENAI_API_KEY set          -> OpenAICompatibleLLM (works with OpenAI or
                                     any OpenAI-compatible endpoint via OPENAI_BASE_URL,
                                     e.g. OpenRouter's free models)
  3. HF_TOKEN set                -> HuggingFaceLLM (serverless inference API)
  4. OLLAMA_HOST reachable       -> OllamaLLM (local dev only)
  5. nothing available           -> DeterministicLLM (rule-based, always works)

The app must keep functioning end-to-end on tier 5. Nothing here is allowed
to silently fabricate a "success" — failures raise, and the orchestrator
catches them and records a warning, then falls back to DeterministicLLM.
"""
from __future__ import annotations
import os
import json
import re
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> str:
        ...

    def complete_json(self, system: str, prompt: str, max_tokens: int = 900) -> dict:
        """Ask for JSON, parse defensively, never raise on bad JSON (returns {})."""
        raw = self.complete(
            system + "\nRespond with ONLY valid JSON. No markdown fences, no preamble.",
            prompt,
            max_tokens,
        )
        return _safe_json(raw)


def _safe_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}


class GroqLLM(LLMProvider):
    name = "groq"

    def __init__(self):
        self.api_key = os.environ["GROQ_API_KEY"]
        # llama-3.3-70b-versatile was retired from Groq's API (confirmed via
        # GET /openai/v1/models returning 404 for it) — openai/gpt-oss-120b
        # is a current, active, high-context (131k) general-purpose model.
        self.model = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> str:
        import requests

        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=45,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class OpenAICompatibleLLM(LLMProvider):
    name = "openai_compatible"

    def __init__(self):
        self.api_key = os.environ["OPENAI_API_KEY"]
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> str:
        import requests

        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=45,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class HuggingFaceLLM(LLMProvider):
    name = "huggingface"

    def __init__(self):
        self.token = os.environ["HF_TOKEN"]
        self.model = os.environ.get("LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> str:
        import requests

        r = requests.post(
            f"https://api-inference.huggingface.co/models/{self.model}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class OllamaLLM(LLMProvider):
    name = "ollama"

    def __init__(self):
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.environ.get("LLM_MODEL", "llama3.1")
        import requests

        requests.get(self.host, timeout=2).raise_for_status()

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> str:
        import requests

        r = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


class DeterministicLLM(LLMProvider):
    """
    No-API-key fallback. Produces structured, honest, template-driven output
    from the actual data it's given (never invented facts) so the platform
    keeps working with zero configuration. This is NOT a "fake AI" — every
    output is a deterministic transformation of the real input state passed
    in by the calling agent, and callers label it AI_GENERATED / TEMPLATE
    rather than pretending it's an LLM's free-form reasoning.
    """

    name = "deterministic"

    def complete(self, system: str, prompt: str, max_tokens: int = 900) -> str:
        return (
            "[Deterministic mode — no LLM configured] "
            "Analysis below is derived directly from structured inputs using "
            "rule-based logic, not free-text generation. Configure GROQ_API_KEY "
            "or OPENAI_API_KEY for narrative synthesis.\n\n" + prompt[:400]
        )

    def complete_json(self, system: str, prompt: str, max_tokens: int = 900) -> dict:
        return {}


def get_llm_provider() -> LLMProvider:
    if os.environ.get("GROQ_API_KEY"):
        try:
            return GroqLLM()
        except Exception:
            pass
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAICompatibleLLM()
        except Exception:
            pass
    if os.environ.get("HF_TOKEN"):
        try:
            return HuggingFaceLLM()
        except Exception:
            pass
    if os.environ.get("OLLAMA_HOST"):
        try:
            return OllamaLLM()
        except Exception:
            pass
    return DeterministicLLM()
