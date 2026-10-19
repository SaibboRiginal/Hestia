"""Tests — outbound MCP servers list (names and status only, never a key)."""
import pytest

from core.outbound import bearer_for, outbound_servers

ENV = {"HECATE_MCP_NOTION_URL": "https://mcp.notion.example/mcp?x=1", "HECATE_MCP_NOTION_KEY": "sk-secret",
       "HECATE_MCP_LOCAL_URL": "http://192.168.1.5:8000/mcp", "HECATE_MCP_BAD_URL": "not a url", "OTHER": "1"}


@pytest.mark.unit
def test_lists_servers_without_secrets_or_paths():
    servers = outbound_servers(ENV)
    assert [s["name"] for s in servers] == ["bad", "local", "notion"]
    notion = servers[2]
    assert notion == {"name": "notion", "host": "mcp.notion.example", "auth": "key", "status": "configured"}
    assert servers[0]["status"] == "invalid_url" and servers[1]["auth"] == "none"
    assert "sk-secret" not in str(servers) and "/mcp" not in str(servers)


@pytest.mark.unit
def test_bearer_for_reads_the_key():
    assert bearer_for("notion", ENV) == "sk-secret" and bearer_for("local", ENV) is None
