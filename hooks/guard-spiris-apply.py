#!/usr/bin/env python3
"""PreToolUse Bash guard for the Spiris/Visma posting engine.

Blocks ledger-writing commands that bypass the review or production gates:
  * any PROD write (prod.env / --prod) unless ~/.hermes/spiris/.prod-approved exists
  * any real write (--apply, or a direct voucher_write_probe.py run) unless a
    dry-run review artifact exists in ~/.hermes/spiris/harness/

It is deliberately surgical: it only ever acts on commands that name a Spiris
write script. Everything else is allowed instantly. It FAILS OPEN on any
unexpected error so it can never brick the shell.
"""
import sys
import json
import re
import glob
from pathlib import Path

WRITE_SCRIPTS = (
    "batch_voucher_poster.py",
    "run_harness.py",
    "accounts_create.py",
    "bank_accounts_create.py",
)
PROBE = "voucher_write_probe.py"


def allow():
    sys.exit(0)


def block(reason):
    sys.stderr.write("BLOCKED by bokföring safety hook: " + reason + "\n")
    sys.exit(2)


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        allow()
    data = json.loads(raw)
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not isinstance(cmd, str) or not cmd:
        allow()

    touches_writer = any(s in cmd for s in WRITE_SCRIPTS)
    touches_probe = PROBE in cmd
    if not (touches_writer or touches_probe):
        allow()

    is_prod = ("prod.env" in cmd) or bool(re.search(r"(^|\s)--prod(\s|=|$)", cmd))
    has_apply = bool(re.search(r"(^|\s)--apply(\s|=|$)", cmd))

    spiris = Path.home() / ".hermes" / "spiris"
    harness = spiris / "harness"
    reviews = glob.glob(str(harness / "review_batch_*.md")) + glob.glob(str(harness / "review_*.md"))
    prod_token = spiris / ".prod-approved"

    if is_prod:
        if not prod_token.exists():
            block(
                "PRODUCTION posting is gated. No ~/.hermes/spiris/.prod-approved token "
                "found. Going live on a real tenant is a deliberate human-in-the-loop "
                "step — create that token on purpose once Spiris prod is authorized."
            )
        if not reviews:
            block(
                "production write requested but no dry-run review artifact exists in "
                "~/.hermes/spiris/harness/. Run the dry-run and review it first."
            )
        allow()

    if has_apply or touches_probe:
        if not reviews:
            block(
                "real write (--apply) requested but no dry-run review artifact found in "
                "~/.hermes/spiris/harness/. Run the poster WITHOUT --apply first, review "
                "the generated review_batch_*.md, then re-run with --apply."
            )
        allow()

    # writer named but no --apply and not prod => dry-run, fine.
    allow()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Never block the shell because of a bug in this guard.
        sys.exit(0)
