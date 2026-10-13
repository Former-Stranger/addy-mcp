# addy-mcp

<!-- mcp-name: io.github.Former-Stranger/addy-mcp -->

[![PyPI](https://img.shields.io/pypi/v/addy-mcp)](https://pypi.org/project/addy-mcp/)
[![CI](https://github.com/Former-Stranger/addy-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Former-Stranger/addy-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that lets Claude (and other MCP clients) manage your [addy.io](https://addy.io) account: aliases, recipients, usernames, custom domains, labels, rules, the blocklist and failed deliveries. It covers the full [addy.io API](https://app.addy.io/docs/).

> **Unofficial.** This project is not affiliated with or endorsed by addy.io.

It runs on your own computer with your own API key. Nothing is hosted, and your key is only ever sent to addy.io.

## 1. Create an API key

In addy.io go to **Settings → API Keys** (<https://app.addy.io/settings/api>) and click **Create New API Key**. Consider giving it a name like "Claude" and an expiry date.

## 2. Install

### Claude Desktop (easiest)

1. Download the latest `addy-mcp-<version>.mcpb` from the [Releases page](https://github.com/Former-Stranger/addy-mcp/releases/latest).
2. Double-click it (or drag it into **Settings → Extensions** in Claude Desktop) and click **Install**.
3. Paste your API key when asked. Claude Desktop stores it in your system keychain.

### Claude Desktop (manual config)

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). Open **Settings → Developer → Edit Config** and add:

```json
{
  "mcpServers": {
    "addy": {
      "command": "uvx",
      "args": ["addy-mcp"],
      "env": {
        "ADDY_API_KEY": "paste-your-api-key-here"
      }
    }
  }
}
```

Then fully quit and reopen Claude Desktop. If it can't find `uvx`, replace `"uvx"` with the full path from `which uvx` (macOS/Linux) or `where uvx` (Windows). Desktop apps don't always see your shell's `PATH`.

### Claude Code

```bash
claude mcp add addy --scope user --env ADDY_API_KEY=paste-your-api-key-here -- uvx addy-mcp
```

This makes the server available in Claude Code (the CLI and the desktop app's Code tab). Claude Desktop's chat uses a separate config, set up above.

### Other MCP clients

Run `uvx addy-mcp` as a stdio server with `ADDY_API_KEY` set in its environment.

## Configuration

| Environment variable | Required | Description |
| --- | --- | --- |
| `ADDY_API_KEY` | Yes | Your addy.io API key. |
| `ADDY_READ_ONLY` | No | Set to `true` to hide every tool that can change your account. Claude can then only look things up. |
| `ADDY_BASE_URL` | No | For self-hosted addy.io instances, e.g. `https://addy.example.com`. Defaults to `https://app.addy.io`. |

## What you can ask

- "Make me a new alias for my Netflix account."
- "Which of my aliases have blocked the most emails? Deactivate the top 5."
- "Find every alias I created for shopping sites and label them 'Shopping'."
- "Block everything from marketing.example.com."
- "Create a rule that blocks newsletters (List-Unsubscribe header) sent to my shop@ alias."
- "Why did mail to my bank alias fail last week?"

## Tools

| Area | Tools |
| --- | --- |
| Account | `get_account_details`, `get_api_token_details`, `get_account_notifications`, `get_domain_options`, `get_app_version` |
| Aliases | `list_aliases`, `get_alias`, `create_alias`, `update_alias`, `delete_alias`, `restore_alias`, `forget_alias`, `set_alias_option` (active / pinned / attached-recipients-only), `set_alias_recipients`, `set_alias_labels` |
| Bulk aliases | `bulk_alias_action` (get / activate / deactivate / pin / unpin / delete / restore / forget), `bulk_set_alias_recipients`, `bulk_set_alias_labels` |
| Recipients | `list_recipients`, `get_recipient`, `create_recipient`, `update_recipient`, `delete_recipient`, `resend_recipient_verification`, `add_recipient_public_key`, `remove_recipient_public_key`, `set_recipient_option` (active / can reply-send / encryption / inline encryption / protected headers / strip PGP keys / strip PGP signatures) |
| Usernames | `list_usernames`, `get_username`, `create_username`, `update_username`, `delete_username`, `set_username_default_recipient`, `set_username_option` (active / catch-all / can login) |
| Domains | `list_domains`, `get_domain`, `create_domain`, `update_domain`, `delete_domain`, `set_domain_default_recipient`, `check_domain_sending_records`, `set_domain_option` (active / catch-all / shared with family) |
| Labels | `list_labels`, `get_label`, `create_label`, `update_label`, `delete_label` |
| Rules | `list_rules`, `get_rule`, `create_rule`, `update_rule`, `delete_rule`, `reorder_rules`, `set_rule_active` |
| Blocklist | `list_blocklist`, `add_to_blocklist`, `remove_from_blocklist` |
| Failed deliveries | `list_failed_deliveries`, `get_failed_delivery`, `download_failed_delivery`, `resend_failed_delivery`, `delete_failed_deliveries` |

Every tool is labelled read-only, write, or destructive (MCP tool annotations), so clients like Claude can ask before running anything risky. Deleting an alias can be undone with `restore_alias`. **Forgetting an alias is permanent.**

## Privacy and security

- The server runs locally and talks only to addy.io (or your `ADDY_BASE_URL`). It has no telemetry.
- Your API key gives full access to your addy.io account. Use a dedicated key so you can revoke it on its own, and turn on `ADDY_READ_ONLY` if you only want Claude to look things up.
- Anything the tools return (alias addresses, descriptions, failed-delivery emails) is passed to your AI client, and is subject to that client's privacy policy.

## Development

```bash
git clone https://github.com/Former-Stranger/addy-mcp
cd addy-mcp
uv run --no-editable python -m pytest      # unit tests (mocked HTTP, never touch a real account)
uv run ruff check && uv run ruff format --check
```

`scripts/live_test.py` exercises the server against a real account: it creates, updates, deletes, restores and finally forgets a throwaway alias and label. Run it with `ADDY_API_KEY=... uv run --no-editable python scripts/live_test.py --yes`.

`--no-editable`: on some macOS setups files in `.venv` get the "hidden" flag, and Python 3.13+ ignores hidden `.pth` files, which breaks editable installs. A regular install sidesteps that.

### Releasing

1. Bump `version` in `pyproject.toml`, run `uv run python scripts/sync_metadata.py`, and update `CHANGELOG.md`.
2. Commit, then tag and push: `git tag v0.2.0 && git push origin v0.2.0`.

The release workflow publishes to PyPI, attaches the `.mcpb` bundle to a GitHub release, and updates the MCP Registry listing.

## License

[MIT](LICENSE)
