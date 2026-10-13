# Changelog

## 0.1.0 - unreleased

First public release.

- 62 tools covering the full addy.io API: aliases (including bulk actions), recipients, usernames, custom domains, labels, rules, blocklist and failed deliveries.
- Tool annotations mark read-only and destructive tools.
- `ADDY_READ_ONLY=true` hides every tool that can change the account.
- `ADDY_BASE_URL` for self-hosted addy.io instances.
- TLS certificates are verified against the operating system's trust store, so it works behind corporate proxies.
- Claude Desktop extension (`.mcpb`) with the API key stored in the system keychain.
