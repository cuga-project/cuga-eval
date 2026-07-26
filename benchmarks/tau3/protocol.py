from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TauToolSpec(BaseModel):
    name: str
    description: str = ""
    openai_schema: dict[str, Any]


class CreateCugaSessionRequest(BaseModel):
    session_id: str
    domain_policy: str
    tools: list[TauToolSpec]
    tau_bridge_url: str


class CreateCugaSessionResponse(BaseModel):
    session_id: str


class CugaRespondRequest(BaseModel):
    message: dict[str, Any]
    history: list[dict[str, Any]] = Field(default_factory=list)


class CugaRespondResponse(BaseModel):
    """Final natural-language response produced by CUGA.

    Tau-native tool calls are no longer returned through this response model.
    They travel through cuga_bridge_server while this /respond request remains
    active.
    """

    content: str