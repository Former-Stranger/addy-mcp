# Changelog

## 0.1.2 - 2026-10-14

- `ADDY_API_KEY_FILE`: read the API key from a file (e.g. a `chmod 600` file or a Docker/Kubernetes secret). Takes precedence over `ADDY_API_KEY`; a missing or empty file is an error rather than a silent fallback.
- README: new "Storing your key securely" section (Claude Desktop extension, macOS Keychain or 1Password wrapper, key file, VS Code secret input).
- README: installing a newer `.mcpb` keeps your API key and settings.
- README: Claude Desktop stores the key encrypted (previously described as "in your system keychain", which wasn't verified).

## 0.1.1 - 2026-10-13

- Added `--version` (and `--help`): `uvx addy-mcp@latest --version` shows the newest release without starting the server.
- Install instructions now use `addy-mcp@latest`, so uvx picks up new releases whenever the server starts. Without `@latest`, uvx keeps using the version it first downloaded.
- README: new "Updating" section.
- Maintenance: weekly check for addy.io API changes, Dependabot for dependencies and GitHub Actions, and releases now need maintainer approval before publishing to PyPI.

## 0.1.0 - 2026-10-13

First public release.

- 62 tools covering the full addy.io API: aliases (including bulk actions), recipients, usernames, custom domains, labels, rules, blocklist and failed deliveries.
- Tool annotations mark read-only and destructive tools.
- `ADDY_READ_ONLY=true` hides every tool that can change the account.
- `ADDY_BASE_URL` for self-hosted addy.io instances.
- TLS certificates are verified against the operating system's trust store, so it works behind corporate proxies.
- Claude Desktop extension (`.mcpb`) with the API key stored encrypted by Claude Desktop.
