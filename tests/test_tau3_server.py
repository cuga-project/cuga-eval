import asyncio
from types import SimpleNamespace

from benchmarks.tau3 import server
from benchmarks.tau3.protocol import CreateCugaSessionRequest


def test_special_instructions_append_tau_policy():
    instructions = server._build_special_instructions("  Follow the Tau rule.  ")

    assert "Adapter-specific discoverable-tool mapping:" in instructions
    assert instructions.endswith("Domain policy:\nFollow the Tau rule.\n\n")


def test_create_session_uses_baseline_agent_without_experiment_registry(monkeypatch):
    constructed = []
    remote_tools = [SimpleNamespace(name="test_tool")]

    class FakeAgent:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

    monkeypatch.setattr(server, "CugaAgent", FakeAgent)
    monkeypatch.setattr(server, "make_remote_tau_tools", lambda **kwargs: remote_tools)

    request = CreateCugaSessionRequest(
        session_id="baseline-test-session",
        domain_policy="Follow the Tau rule.",
        tools=[],
        tau_bridge_url="http://127.0.0.1:8766",
    )

    try:
        response = asyncio.run(server.create_session(request))
        assert response.session_id == request.session_id
        assert len(constructed) == 1
        assert constructed[0]["tool_mode"] == "external"
        assert constructed[0]["tools"] is remote_tools
        assert constructed[0]["enable_knowledge"] is False
        assert constructed[0]["enable_skills"] is False
        assert "Domain policy:\nFollow the Tau rule." in constructed[0]["special_instructions"]
    finally:
        server._SESSIONS.pop(request.session_id, None)
