"""Keep manifest.json and server.json in sync with pyproject.toml and the server's tools.

Usage:
    uv run python scripts/sync_metadata.py          # rewrite the files
    uv run python scripts/sync_metadata.py --check  # exit 1 if they are out of date (used in CI)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp import Client  # noqa: E402

from addy_mcp.server import mcp  # noqa: E402


async def tool_summaries() -> list[dict[str, str]]:
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    return [{"name": t.name, "description": (t.description or "").strip().splitlines()[0]} for t in tools]


def render(path: Path, data: dict) -> tuple[str, str]:
    return path.read_text(), json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = version
    manifest["tools"] = asyncio.run(tool_summaries())

    server_path = ROOT / "server.json"
    server = json.loads(server_path.read_text())
    server["version"] = version
    for package in server["packages"]:
        if package["registryType"] == "pypi":
            package["version"] = version

    stale = []
    for path, data in ((manifest_path, manifest), (server_path, server)):
        current, updated = render(path, data)
        if current != updated:
            stale.append(path.name)
            if "--check" not in sys.argv:
                path.write_text(updated)

    if stale and "--check" in sys.argv:
        print(f"Out of date: {', '.join(stale)}. Run: uv run python scripts/sync_metadata.py", file=sys.stderr)
        return 1
    print(f"Updated: {', '.join(stale)}" if stale else f"Metadata up to date (version {version}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
