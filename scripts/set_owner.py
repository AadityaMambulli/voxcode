"""Replace the single marketplace-owner placeholder in plugin configuration."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("owner")
    args = parser.parse_args()
    if "/" in args.owner or not args.owner.strip():
        parser.error("owner must be a non-empty GitHub account name")
    path = Path("plugins/voxcode/.mcp.json")
    text = path.read_text(encoding="utf-8")
    updated = text.replace("__GITHUB_OWNER__", args.owner)
    if updated == text:
        raise SystemExit("placeholder not found; refusing to rewrite the file")
    path.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
