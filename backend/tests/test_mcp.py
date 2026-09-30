"""MCP server: an AI agent can search, run a due diligence and screen names over JSON-RPC."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def rpc(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    resp = client.post("/api/mcp", json=body)
    assert resp.status_code == 200
    return resp.json()


def call(name, **arguments):
    return rpc("tools/call", {"name": name, "arguments": arguments})["result"]


def test_handshake_and_tool_list():
    init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "kyc-1-click" and "tools" in init["capabilities"]
    assert "analyst" in init["instructions"]
    assert rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
    tools = {t["name"]: t for t in rpc("tools/list")["result"]["tools"]}
    assert set(tools) == {"search_entities", "run_due_diligence", "screen_names", "quick_checks"}
    assert all(t["inputSchema"]["type"] == "object" for t in tools.values())
    assert rpc("ping")["result"] == {}


def test_agent_runs_a_due_diligence_end_to_end():
    found = call("search_entities", query="Northgate Maritime")["structuredContent"]
    ids = found["candidates"][0]["record_ids"]
    res = call("run_due_diligence", record_ids=ids, depth=2)
    assert res["isError"] is False
    dd = res["structuredContent"]
    assert dd["subject"]["name"] == "Northgate Maritime Holdings Ltd"
    assert dd["risk"]["level"] == "critical"
    assert dd["blocked_by_ownership"][0]["blocked"] is True  # OFAC 50 % rule
    assert any(o["sanctioned"] for o in dd["beneficial_owners"])
    assert any("OFAC 50 % rule" in item["provisions"] for item in dd["legal_basis"])
    assert dd["open_in_browser"].endswith("depth=2") and dd["disclaimer"]
    assert res["content"][0]["type"] == "text"  # the same data as text for older clients


def test_screen_names_and_tool_errors():
    res = call("screen_names", names=["Ruslan Terekhov", "Jane Example"], type="person")
    rows = res["structuredContent"]["results"]
    assert rows[0]["matches"] and rows[0]["matches"][0]["type"] == "sanction"
    assert rows[1]["matches"] == []
    assert call("search_entities", query=" ")["isError"] is True
    assert call("run_due_diligence")["isError"] is True
    assert call("quick_checks")["isError"] is True


def test_protocol_errors_notifications_and_batches():
    assert rpc("unknown/method")["error"]["code"] == -32601
    assert rpc("tools/call", {"name": "nope"})["error"]["code"] == -32602
    note = client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
    batch = client.post(
        "/api/mcp",
        json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "x"}],
    )
    assert batch.json() == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    assert client.post("/api/mcp", content=b"{not json").json()["error"]["code"] == -32700
    assert client.get("/api/mcp").status_code == 405
