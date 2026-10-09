import httpx

from provenpaid_mcp.client import ProvenPaidClient
from provenpaid_mcp.config import load_settings
from provenpaid_mcp.server import build_server

from .test_client import provenpaid_app


async def test_server_exposes_three_tools_with_descriptions(tmp_path):
    app, _ = provenpaid_app()
    settings = load_settings({"PROVENPAID_STATE_DIR": str(tmp_path), "PROVENPAID_API_URL": "https://api.provenpaid.test"})
    server = build_server(ProvenPaidClient(settings, transport=httpx.ASGITransport(app=app)))
    tools = {t.name: t for t in await server.list_tools()}
    assert set(tools) == {"check_x402_endpoint", "provenpaid_methodology", "provenpaid_status"}
    assert "0.01" in tools["check_x402_endpoint"].description
    assert tools["check_x402_endpoint"].input_schema["required"] == ["url"]
    status = await server.call_tool("provenpaid_status", {})
    assert '"ready_to_pay": false' in status.content[0].text
