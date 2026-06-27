"""Render Mermaid (.mmd) diagram sources to PNG images.

Primary renderer: Kroki (https://kroki.io) server-side Mermaid -> PNG.
Fallback renderer: mermaid.ink.

Usage:
    python scripts/render_diagrams.py
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

import requests

DIAGRAMS_DIR = Path(__file__).resolve().parent.parent / "docs" / "diagrams"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets"


def _kroki_url(source: str) -> str:
    compressed = zlib.compress(source.encode("utf-8"), 9)
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii")
    return f"https://kroki.io/mermaid/png/{encoded}"


def _mermaid_ink_url(source: str) -> str:
    encoded = base64.urlsafe_b64encode(source.encode("utf-8")).decode("ascii")
    return f"https://mermaid.ink/img/{encoded}?type=png"


def render(source: str) -> bytes:
    # Try Kroki (POST is simplest and avoids URL length limits)
    try:
        resp = requests.post(
            "https://kroki.io/mermaid/png",
            data=source.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=60,
        )
        if resp.status_code == 200 and resp.content[:8] == b"\x89PNG\r\n\x1a\n":
            return resp.content
        print(f"  kroki POST failed ({resp.status_code}); trying GET")
        resp = requests.get(_kroki_url(source), timeout=60)
        if resp.status_code == 200 and resp.content[:8] == b"\x89PNG\r\n\x1a\n":
            return resp.content
        print(f"  kroki GET failed ({resp.status_code}); trying mermaid.ink")
    except requests.RequestException as exc:  # pragma: no cover
        print(f"  kroki error: {exc}; trying mermaid.ink")

    resp = requests.get(_mermaid_ink_url(source), timeout=60)
    resp.raise_for_status()
    return resp.content


def main() -> int:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    sources = sorted(DIAGRAMS_DIR.glob("*.mmd"))
    if not sources:
        print("No .mmd sources found")
        return 1
    for src in sources:
        out = ASSETS_DIR / (src.stem + ".png")
        print(f"Rendering {src.name} -> {out.name}")
        png = render(src.read_text(encoding="utf-8"))
        out.write_bytes(png)
        print(f"  wrote {len(png):,} bytes")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
