"""Detect changes to the addy.io API by comparing its docs against a saved snapshot.

The snapshot lists every endpoint and its documented parameters. A weekly workflow runs this and
opens an issue when they change, so the MCP tools can be updated.

    python3 scripts/check_api_docs.py            # compare live docs to the snapshot (exit 1 if changed)
    python3 scripts/check_api_docs.py --update   # rewrite the snapshot
    python3 scripts/check_api_docs.py --html docs.html   # use a saved copy of the docs page
"""

from __future__ import annotations

import argparse
import difflib
import html
import re
import sys
import urllib.request
from pathlib import Path

DOCS_URL = "https://app.addy.io/docs/"
SNAPSHOT = Path(__file__).resolve().parent / "addy_api_snapshot.txt"

ENDPOINT = re.compile(r"^(GET|POST|PATCH|PUT|DELETE)\s+(api/\S+)$")
PARAM = re.compile(r"^([A-Za-z_][\w\[\].]*)\s+(string\[\]|string|integer|boolean|number|object)(?!\w)(.*)$")
SECTIONS = {"URL Parameters", "Query Parameters", "Body Parameters"}


def docs_text(raw_html: str) -> list[str]:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw_html, flags=re.S)
    text = re.sub(r"<(br|p|div|h[1-6]|li|tr|pre)[^>]*>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return [line.strip() for line in text.splitlines() if line.strip()]


def snapshot(raw_html: str) -> str:
    """One line per endpoint, followed by its parameters (name, type, required/optional)."""
    out: list[str] = []
    section = None
    for line in docs_text(raw_html):
        if match := ENDPOINT.match(line):
            out.append(f"{match[1]} {match[2]}")
            section = None
        elif line in SECTIONS:
            section = line.split()[0].lower()
        elif section and out and (match := PARAM.match(line)):
            optional = "optional" if "optional" in match[3] else "required"
            out.append(f"    {section} {match[1]}: {match[2]} ({optional})")
        elif section and line in {"Example request:", "Response", "Request"}:
            section = None
    if not any(line.startswith("GET api/v1/aliases") for line in out):
        raise SystemExit("Could not find the alias endpoints in the docs; the page layout may have changed.")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="rewrite the snapshot instead of comparing")
    parser.add_argument("--html", type=Path, help="read the docs from this file instead of downloading them")
    args = parser.parse_args()

    if args.html:
        raw = args.html.read_text(encoding="utf-8")
    else:
        request = urllib.request.Request(DOCS_URL, headers={"User-Agent": "addy-mcp-api-watch"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")

    current = snapshot(raw)
    if args.update:
        SNAPSHOT.write_text(current)
        print(f"Wrote {SNAPSHOT.name} ({current.count(chr(10))} lines)")
        return 0

    saved = SNAPSHOT.read_text()
    if current == saved:
        print("addy.io API docs unchanged.")
        return 0
    diff = difflib.unified_diff(
        saved.splitlines(keepends=True), current.splitlines(keepends=True), "snapshot", "live docs"
    )
    sys.stdout.writelines(diff)
    return 1


if __name__ == "__main__":
    sys.exit(main())
