from __future__ import annotations
from dataclasses import dataclass
from providers.llm.base import LLMProvider
from providers.research.base import WebResearchProvider
from providers.vectorstore.base import VectorStoreProvider


@dataclass
class AgentContext:
    llm: LLMProvider
    research: WebResearchProvider
    vectorstore: VectorStoreProvider
