"""CUGA tool provider that shows benchmark tools under their real app names.

``CugaAgent(tools=[...])`` puts every tool in one virtual app, ``runtime_tools``, so the prompt's Connected
Applications section says "runtime_tools (LANGCHAIN): Runtime LangChain tools (15 tools)". AppWorld runs list
the real apps (spotify, venmo, ...). This provider keeps the default provider's tool handling and only splits
the tools into named apps; pass it as ``CugaAgent(tool_provider=AppToolsProvider(tools, app_of))``.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from cuga.backend.cuga_graph.nodes.cuga_lite.providers.base import AppDefinition
from cuga.backend.cuga_graph.nodes.cuga_lite.providers.langchain import DirectLangChainToolsProvider


class AppToolsProvider(DirectLangChainToolsProvider):
    def __init__(
        self, tools: List, app_of: Callable[[object], str], descriptions: Optional[Dict[str, str]] = None
    ):
        super().__init__(tools=tools)
        self.groups: Dict[str, List] = {}
        for tool in self.tools:
            self.groups.setdefault(app_of(tool), []).append(tool)
        self.descriptions = descriptions or {}

    async def get_apps(self) -> List[AppDefinition]:
        if not self.initialized:
            await self.initialize()
        return [
            AppDefinition(
                name=app,
                type="langchain",
                description=self.descriptions.get(app) or f"{app} ({len(tools)} tools)",
            )
            for app, tools in self.groups.items()
        ]

    async def get_tools(self, app_name: str) -> List:
        if not self.initialized:
            await self.initialize()
        return list(self.groups.get(app_name, []))
