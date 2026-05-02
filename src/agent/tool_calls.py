"""Extração de chamadas de ferramentas nativas do texto gerado pelo LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

TOOL_BLOCK_PATTERN = re.compile(r"```(?:tool|json)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class ToolCall:
    """Chamada estruturada de tool gerada pelo LLM."""

    tool: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    def display_name(self) -> str:
        payload = json.dumps(self.args, ensure_ascii=False, sort_keys=True)
        return f"{self.tool}.{self.action} {payload}"


@dataclass(frozen=True)
class ToolExtractionResult:
    """Resultado da tentativa de extrair tool call."""

    success: bool
    tool_call: ToolCall | None = None
    error_message: str = ""


def extract_tool_call(llm_response: str) -> ToolExtractionResult:
    """Extrai um bloco ```tool``` ou ```json``` contendo tool/action/args."""
    if not llm_response:
        return ToolExtractionResult(False, error_message="Resposta vazia.")

    for block in TOOL_BLOCK_PATTERN.findall(llm_response):
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        tool = str(payload.get("tool", "")).strip()
        action = str(payload.get("action", "")).strip()
        args = payload.get("args", {})
        explanation = str(payload.get("explanation", "")).strip()

        if tool and action and isinstance(args, dict):
            return ToolExtractionResult(True, ToolCall(tool=tool, action=action, args=args, explanation=explanation))

    return ToolExtractionResult(False, error_message="Nenhuma chamada de tool válida encontrada.")
