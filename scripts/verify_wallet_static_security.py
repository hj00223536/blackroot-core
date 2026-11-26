#!/usr/bin/env python3
"""Fail closed if the static wallet prototype gains active or remote content."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WALLET = ROOT / "web-wallet" / "index.html"


class WalletAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.csp_seen = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self.errors.append("script elements are not permitted in the static prototype")
        if tag in {"iframe", "object", "embed", "form"}:
            self.errors.append(f"{tag} elements are not permitted in the static prototype")
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.errors.append(f"inline event handler {name} is not permitted")
            if name.lower() in {"src", "href", "action"} and value:
                if value.startswith(("http://", "https://", "//")):
                    self.errors.append(f"remote resource/reference is not permitted: {value}")
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            policy = values.get("content", "")
            required = (
                "default-src 'none'",
                "connect-src 'none'",
                "object-src 'none'",
                "frame-src 'none'",
                "base-uri 'none'",
                "form-action 'none'",
            )
            missing = [directive for directive in required if directive not in policy]
            if missing:
                self.errors.append("CSP is missing: " + ", ".join(missing))
            self.csp_seen = True


def main() -> int:
    if not WALLET.is_file():
        print(f"FAIL: missing wallet entry point: {WALLET}", file=sys.stderr)
        return 1
    audit = WalletAudit()
    audit.feed(WALLET.read_text(encoding="utf-8"))
    audit.close()
    if not audit.csp_seen:
        audit.errors.append("restrictive Content-Security-Policy meta element is missing")
    if audit.errors:
        for error in audit.errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: static wallet prototype has restrictive CSP and no active/remote content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
