import importlib
import json

import httpx
import pytest
from mcp import Client

import addy_mcp
from addy_mcp import server
from addy_mcp.client import AddyClient


@pytest.fixture
def addy(monkeypatch):
    """Route the server's API client through a mock transport and record requests."""
    calls = []
    responses = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, dict(request.url.params), body, request.headers))
        key = (request.method, request.url.path)
        if key in responses:
            return responses[key]
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"data": {"ok": True}})

    client = AddyClient(api_key="test-key", base_url="https://addy.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "api", client)
    return calls, responses


async def call(name, args=None):
    async with Client(server.mcp) as c:
        return await c.call_tool(name, args or {})


async def test_auth_headers_and_base_url(addy):
    calls, _ = addy
    result = await call("get_account_details")
    assert not result.is_error
    method, path, _, _, headers = calls[0]
    assert (method, path) == ("GET", "/api/v1/account-details")
    assert headers["authorization"] == "Bearer test-key"
    assert headers["accept"] == "application/json"


async def test_list_aliases_builds_filters(addy):
    calls, _ = addy
    await call(
        "list_aliases",
        {"search": "shop", "active": False, "sort": "created_at", "descending": True,
         "include": "labels", "page": 2},
    )  # fmt: skip
    _, path, params, _, _ = calls[0]
    assert path == "/api/v1/aliases"
    assert params == {
        "filter[search]": "shop",
        "filter[active]": "false",
        "sort": "-created_at",
        "with": "labels",
        "page[number]": "2",
        "page[size]": "25",
    }


async def test_create_alias_omits_unset_fields(addy):
    calls, _ = addy
    await call("create_alias", {"domain": "anonaddy.me", "description": "Amazon"})
    assert calls[0][:2] == ("POST", "/api/v1/aliases")
    assert calls[0][3] == {"domain": "anonaddy.me", "description": "Amazon"}


@pytest.mark.parametrize(
    ("tool", "id_arg", "option", "resource"),
    [
        ("set_alias_option", "alias_id", "active", "active-aliases"),
        ("set_alias_option", "alias_id", "pinned", "pinned-aliases"),
        ("set_recipient_option", "recipient_id", "can_reply_send", "allowed-recipients"),
        ("set_recipient_option", "recipient_id", "protected_headers", "protected-headers-recipients"),
        ("set_domain_option", "domain_id", "catch_all", "catch-all-domains"),
        ("set_username_option", "username_id", "can_login", "loginable-usernames"),
    ],
)
async def test_toggles(addy, tool, id_arg, option, resource):
    calls, _ = addy
    await call(tool, {id_arg: "abc", "option": option, "enabled": True})
    await call(tool, {id_arg: "abc", "option": option, "enabled": False})
    assert calls[0][:2] == ("POST", f"/api/v1/{resource}")
    assert calls[0][3] == {"id": "abc"}
    assert calls[1][:2] == ("DELETE", f"/api/v1/{resource}/abc")


async def test_delete_returns_success_on_204(addy):
    result = await call("delete_alias", {"alias_id": "abc"})
    assert not result.is_error
    assert json.loads(result.content[0].text) == {"success": True}


async def test_api_errors_reach_the_model(addy):
    _, responses = addy
    responses[("POST", "/api/v1/aliases")] = httpx.Response(
        422, json={"message": "The given data was invalid.", "errors": {"domain": ["The domain field is required."]}}
    )
    result = await call("create_alias", {"domain": "nope.example"})
    assert result.is_error
    text = result.content[0].text
    assert "422" in text and "domain: The domain field is required." in text


async def test_update_rule_merges_with_existing(addy):
    calls, responses = addy
    existing = {
        "name": "Old",
        "conditions": [{"type": "sender", "match": "is exactly", "values": ["a@b.com"]}],
        "actions": [{"type": "block"}],
        "operator": "AND",
        "forwards": True,
        "replies": False,
        "sends": False,
    }
    responses[("GET", "/api/v1/rules/r1")] = httpx.Response(200, json={"data": existing})
    await call("update_rule", {"rule_id": "r1", "name": "New", "replies": True})
    assert calls[1][:2] == ("PATCH", "/api/v1/rules/r1")
    assert calls[1][3] == {**existing, "name": "New", "replies": True}


async def test_create_rule_serialises_models(addy):
    calls, _ = addy
    await call(
        "create_rule",
        {
            "name": "No newsletters",
            "conditions": [{"type": "header", "match": "exists", "values": ["List-Unsubscribe"]}],
            "actions": [{"type": "webhook", "value": {"url": "https://x.test/hook", "include_body": False}}],
        },
    )
    body = calls[0][3]
    assert body["conditions"] == [{"type": "header", "match": "exists", "values": ["List-Unsubscribe"]}]
    assert body["actions"] == [{"type": "webhook", "value": {"url": "https://x.test/hook", "include_body": False}}]
    assert body["operator"] == "AND" and body["forwards"] is True


async def test_blocklist_uses_bulk_endpoint_for_many(addy):
    calls, _ = addy
    await call("add_to_blocklist", {"type": "domain", "values": ["spam.com"]})
    await call("add_to_blocklist", {"type": "domain", "values": ["spam.com", "junk.net"]})
    assert calls[0][:2] == ("POST", "/api/v1/blocklist")
    assert calls[0][3] == {"type": "domain", "value": "spam.com"}
    assert calls[1][:2] == ("POST", "/api/v1/blocklist/store/bulk")
    assert calls[1][3] == {"type": "domain", "values": ["spam.com", "junk.net"]}


async def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("ADDY_API_KEY", raising=False)
    monkeypatch.setattr(server, "api", AddyClient())
    result = await call("list_recipients")
    assert result.is_error
    assert "ADDY_API_KEY" in result.content[0].text


async def test_get_recipient_alias_count_flag(addy):
    calls, _ = addy
    await call("get_recipient", {"recipient_id": "r1", "include_alias_count": False})
    assert calls[0][1:3] == ("/api/v1/recipients/r1", {"filter[alias_count]": "false"})


async def test_read_only_mode_hides_write_tools():
    try:
        server.apply_read_only_mode()
        async with Client(server.mcp) as c:
            names = {t.name for t in (await c.list_tools()).tools}
        assert {"list_aliases", "get_alias", "check_domain_sending_records"} <= names
        assert not names & {"create_alias", "delete_alias", "forget_alias", "set_alias_option", "update_rule"}
        assert all(not t.startswith(("create_", "delete_", "update_", "set_")) for t in names)
    finally:
        importlib.reload(server)


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        server.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"addy-mcp {addy_mcp.__version__}"
