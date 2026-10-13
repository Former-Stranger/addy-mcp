"""End-to-end check against a real addy.io account.

Runs the read-only tools, then creates a throwaway alias and label, changes them, and cleans up:
the alias is deleted, restored and finally *forgotten* (permanently removed); the label is deleted.
Nothing else in the account is modified.

    ADDY_API_KEY=... uv run --no-editable python scripts/live_test.py --yes
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp import Client  # noqa: E402

from addy_mcp.server import mcp  # noqa: E402

failures: list[str] = []


async def step(client: Client, label: str, tool: str, args: dict[str, Any] | None = None) -> Any:
    result = await client.call_tool(tool, args or {})
    text = result.content[0].text if result.content else ""
    if result.is_error:
        failures.append(f"{label}: {text}")
        print(f"  FAIL  {label}\n        {text}")
        return None
    print(f"  ok    {label}")
    try:
        return json.loads(text)
    except ValueError:
        return text


async def main() -> int:
    if "--yes" not in sys.argv:
        print(__doc__)
        print("Re-run with --yes to confirm you want to modify the account as described above.")
        return 2
    if not os.environ.get("ADDY_API_KEY"):
        print("Set ADDY_API_KEY first.")
        return 2

    tag = f"addy-mcp live test {time.strftime('%Y-%m-%d %H:%M:%S')}"
    async with Client(mcp) as c:
        print("Read-only tools")
        await step(c, "get_account_details", "get_account_details")
        await step(c, "get_api_token_details", "get_api_token_details")
        options = await step(c, "get_domain_options", "get_domain_options")
        await step(c, "list_aliases (include=labels)", "list_aliases", {"include": "labels", "page_size": 1})
        await step(c, "list_aliases (include=recipients)", "list_aliases", {"include": "recipients", "page_size": 1})
        recipients = await step(c, "list_recipients", "list_recipients", {"include_alias_count": False})
        for tool in ("list_usernames", "list_domains", "list_labels", "list_rules", "list_blocklist"):
            await step(c, tool, tool)
        await step(c, "list_failed_deliveries", "list_failed_deliveries", {"page_size": 1})
        if recipients and recipients.get("data"):
            await step(c, "get_recipient", "get_recipient", {"recipient_id": recipients["data"][0]["id"]})

        if not options:
            return 1
        domain = options.get("defaultAliasDomain") or options["data"][0]
        print(f"\nWrite tools (throwaway alias on {domain})")
        created = await step(c, "create_alias", "create_alias", {"domain": domain, "description": tag})
        if not created:
            return 1
        alias_id = created["data"]["id"]
        print(f"        created {created['data']['email']}")
        try:
            await step(c, "get_alias", "get_alias", {"alias_id": alias_id})
            await step(c, "update_alias", "update_alias", {"alias_id": alias_id, "description": tag + " (updated)"})
            for option in ("active", "pinned", "attached_recipients_only"):
                current = option == "active"  # new aliases are active, unpinned and unrestricted
                await step(c, f"set_alias_option {option}={not current}", "set_alias_option",
                           {"alias_id": alias_id, "option": option, "enabled": not current})  # fmt: skip
                await step(c, f"set_alias_option {option}={current}", "set_alias_option",
                           {"alias_id": alias_id, "option": option, "enabled": current})  # fmt: skip

            label = await step(c, "create_label", "create_label", {"name": "addy-mcp test", "colour": "#64748b"})
            if label:
                label_id = label["data"]["id"]
                await step(c, "set_alias_labels", "set_alias_labels", {"alias_id": alias_id, "label_ids": [label_id]})
                await step(c, "update_label", "update_label", {"label_id": label_id, "name": "addy-mcp test 2"})
                await step(c, "set_alias_labels (clear)", "set_alias_labels", {"alias_id": alias_id, "label_ids": []})
                await step(c, "delete_label", "delete_label", {"label_id": label_id})

            await step(c, "bulk_alias_action get", "bulk_alias_action", {"action": "get", "alias_ids": [alias_id]})
            await step(c, "delete_alias", "delete_alias", {"alias_id": alias_id})
            await step(c, "restore_alias", "restore_alias", {"alias_id": alias_id})
        finally:
            await step(c, "forget_alias (cleanup)", "forget_alias", {"alias_id": alias_id})

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll steps passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
