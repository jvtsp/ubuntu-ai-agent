"""
Testes para o módulo de prompts (agent/prompts.py).
"""

import pytest
from src.agent.prompts import SYSTEM_PROMPT, EVALUATION_PROMPT, build_context_messages


class TestSystemPrompt:
    def test_prompt_not_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_prompt_mentions_bash(self):
        assert "bash" in SYSTEM_PROMPT.lower() or "Bash" in SYSTEM_PROMPT

    def test_prompt_mentions_ubuntu(self):
        assert "Ubuntu" in SYSTEM_PROMPT

    def test_prompt_has_safety_rules(self):
        assert "destrutivo" in SYSTEM_PROMPT.lower() or "NUNCA" in SYSTEM_PROMPT


class TestEvaluationPrompt:
    def test_prompt_not_empty(self):
        assert len(EVALUATION_PROMPT) > 50

    def test_prompt_mentions_satisfatorio(self):
        assert "SATISFATORIO" in EVALUATION_PROMPT

    def test_prompt_mentions_insatisfatorio(self):
        assert "INSATISFATORIO" in EVALUATION_PROMPT


class TestBuildContextMessages:
    def test_empty_history(self):
        assert build_context_messages([]) == ""

    def test_single_entry(self):
        history = [{"user_input": "instale vim", "extracted_command": "sudo apt install vim", "exit_code": 0}]
        result = build_context_messages(history)
        assert "instale vim" in result
        assert "apt install vim" in result
        assert "0" in result

    def test_multiple_entries(self):
        history = [
            {"user_input": "cmd1", "extracted_command": "echo 1"},
            {"user_input": "cmd2", "extracted_command": "echo 2"},
        ]
        result = build_context_messages(history)
        assert "cmd1" in result and "cmd2" in result

    def test_truncates_long_stdout(self):
        history = [{"user_input": "test", "stdout": "x" * 1000, "exit_code": 0}]
        result = build_context_messages(history)
        assert "..." in result  # truncated

    def test_handles_missing_fields(self):
        history = [{"user_input": "test"}]
        result = build_context_messages(history)
        assert "test" in result

    def test_contains_separator(self):
        history = [{"user_input": "test"}]
        result = build_context_messages(history)
        assert "---" in result
