"""
Testes da extração de chamadas de tools do LLM.
"""

from src.agent.tool_calls import extract_tool_call


class TestToolCallExtraction:
    def test_extract_tool_block(self):
        result = extract_tool_call(
            '```tool\n{"tool":"dbus_native","action":"service_status","args":{"service":"docker"}}\n```'
        )
        assert result.success is True
        assert result.tool_call
        assert result.tool_call.tool == "dbus_native"
        assert result.tool_call.action == "service_status"
        assert result.tool_call.args["service"] == "docker"

    def test_ignores_invalid_json(self):
        result = extract_tool_call("```tool\n{not-json}\n```")
        assert result.success is False

    def test_display_name_is_human_readable(self):
        result = extract_tool_call('```json\n{"tool":"resource_snapshot","action":"read","args":{}}\n```')
        assert result.tool_call
        assert result.tool_call.display_name() == "resource_snapshot.read {}"
