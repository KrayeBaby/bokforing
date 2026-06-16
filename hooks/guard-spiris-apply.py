#!/usr/bin/env python3
"""PreToolUse Bash guard for the Spiris/Visma posting engine.

Blocks ledger-writing commands that bypass the review, freshness, batch-binding
or production gates:
  * any PROD write (prod.env / --prod) unless ~/.hermes/spiris/.prod-approved exists
  * any real write (--apply, or a direct voucher_write_probe.py run) unless a
    RECENT dry-run review artifact exists in ~/.hermes/spiris/harness/
  * a batch_voucher_poster.py --apply whose --docs file does not hash-match a
    FRESH dry-run (the dry-run stamps `docs_sha256=...` into review_batch_*.md)

Design:
  * Surgical: only ever acts on commands that name a Spiris write script.
    Everything else is allowed instantly.
  * Fail-OPEN for anything that is NOT a recognised write command — a bug in this
    guard must never brick an unrelated shell command.
  * Fail-CLOSED once a command IS recognised as a Spiris write but its safety
    cannot be positively verified. For a guard on a real ledger, "I am not sure"
    must mean "block", not "allow".
  * Freshness: the newest review artifact must be younger than
    BOKFORING_REVIEW_MAX_AGE_MIN minutes (default 360 = 6h).
  * Batch-binding: an --apply only proceeds if the exact --docs set was the one
    a fresh dry-run reviewed (sha256 match). Transitional: if no fresh review
    carries a marker yet (pre-binding engine), falls back to the freshness rule.
"""
import sys
import os
import json
import re
import glob
import time
import hashlib
from pathlib import Path

WRITE_SCRIPTS = (
    "batch_voucher_poster.py",
    "run_harness.py",
    "accounts_create.py",
    "bank_accounts_create.py",
)
PROBE = "voucher_write_probe.py"
POSTER = "batch_voucher_poster.py"

# Engine default for batch_voucher_poster.py --docs (used when --docs is omitted).
DEFAULT_DOCS = Path(
    "/Users/KrayeAgent/Claude/Projects/Claude Bokföring/reference/visma_export/batch_docs.json")
MARKER_RE = re.compile(r"docs_sha256=([0-9a-f]{64})")
DEFAULT_MAX_AGE_MIN = 360  # 6h: generous for a same-session dry-run -> review -> apply


def allow():
    sys.exit(0)


def block(reason):
    sys.stderr.write("BLOCKED by bokforing safety hook: " + reason + "\n")
    sys.exit(2)


def _max_age_seconds():
    raw = os.environ.get("BOKFORING_REVIEW_MAX_AGE_MIN", "").strip()
    try:
        val = float(raw)
        if val > 0:
            return val * 60.0
    except (TypeError, ValueError):
        pass
    return DEFAULT_MAX_AGE_MIN * 60.0


def _reviews(harness):
    return (glob.glob(str(harness / "review_batch_*.md"))
            + glob.glob(str(harness / "review_*.md")))


def _fresh_reviews(reviews, max_age_s):
    now = time.time()
    out = []
    for p in reviews:
        try:
            if now - os.path.getmtime(p) <= max_age_s:
                out.append(p)
        except OSError:
            continue
    return out


def _docs_path_from_cmd(cmd):
    m = re.search(r"""--docs(?:=|\s+)("[^"]*"|'[^']*'|\S+)""", cmd)
    if not m:
        return DEFAULT_DOCS
    raw = m.group(1).strip().strip('"').strip("'")
    return Path(raw).expanduser()


def _markers_in(reviews):
    have_marker = False
    shas = set()
    for p in reviews:
        try:
            txt = Path(p).read_text(errors="ignore")
        except OSError:
            continue
        for mm in MARKER_RE.finditer(txt):
            have_marker = True
            shas.add(mm.group(1))
    return have_marker, shas


def _binding_reason(cmd, fresh_reviews):
    """For batch_voucher_poster --apply: the --docs file must hash-match a FRESH
    dry-run's stamped docs_sha256. Returns a block reason, or None to allow."""
    if POSTER not in cmd:
        return None
    docs_path = _docs_path_from_cmd(cmd)
    try:
        docs_sha = hashlib.sha256(docs_path.read_bytes()).hexdigest()
    except OSError:
        return (f"cannot read the --docs file to verify the batch ({docs_path}); "
                "refusing the apply — check the path, run the dry-run, then --apply.")
    have_marker, fresh_shas = _markers_in(fresh_reviews)
    if have_marker and docs_sha not in fresh_shas:
        return ("these --docs do not match any FRESH dry-run (sha256 "
                f"{docs_sha[:12]}... absent from a recent review_batch). A stale or "
                "unrelated review must not authorise this apply — re-run the dry-run "
                "on THESE docs, review it, then --apply.")
    return None


def evaluate(cmd):
    """Return None to allow, or a string reason to block. The caller treats ANY
    exception raised here as a BLOCK (fail-closed) because by this point the
    command is known to be a recognised Spiris write."""
    is_prod = ("prod.env" in cmd) or bool(re.search(r"(^|\s)--prod(\s|=|$)", cmd))
    has_apply = bool(re.search(r"(^|\s)--apply(\s|=|$)", cmd))
    touches_probe = PROBE in cmd

    spiris = Path.home() / ".hermes" / "spiris"
    harness = spiris / "harness"
    reviews = _reviews(harness)
    max_age_s = _max_age_seconds()
    prod_token = spiris / ".prod-approved"

    if is_prod:
        if not prod_token.exists():
            return ("PRODUCTION posting is gated. No ~/.hermes/spiris/.prod-approved "
                    "token found. Going live on a real tenant is a deliberate "
                    "human-in-the-loop step - create that token on purpose once "
                    "Spiris prod is authorized.")
        if not reviews:
            return ("production write requested but no dry-run review artifact exists "
                    "in ~/.hermes/spiris/harness/. Run the dry-run and review it first.")
        fresh = _fresh_reviews(reviews, max_age_s)
        if not fresh:
            return ("production write requested but the newest dry-run review artifact "
                    "is older than the freshness window - re-run the dry-run so the "
                    "plan matches THIS batch (or set BOKFORING_REVIEW_MAX_AGE_MIN).")
        if has_apply:
            r = _binding_reason(cmd, fresh)
            if r:
                return r
        return None

    if has_apply or touches_probe:
        if not reviews:
            return ("real write (--apply) requested but no dry-run review artifact found "
                    "in ~/.hermes/spiris/harness/. Run the poster WITHOUT --apply first, "
                    "review the generated review_batch_*.md, then re-run with --apply.")
        fresh = _fresh_reviews(reviews, max_age_s)
        if not fresh:
            return ("real write (--apply) requested but the newest dry-run review "
                    "artifact is stale. A leftover review from an earlier batch must not "
                    "authorise this apply - re-run the dry-run, review it, then --apply "
                    "(or set BOKFORING_REVIEW_MAX_AGE_MIN).")
        if has_apply:
            r = _binding_reason(cmd, fresh)
            if r:
                return r
        return None

    # writer named but no --apply and not prod => dry-run, fine.
    return None


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

    # From here the command IS a recognised Spiris write/probe. Verify safety;
    # any failure to verify is fail-CLOSED (block).
    try:
        reason = evaluate(cmd)
    except Exception as e:
        block("could not verify the safety gate for a Spiris write command ("
              + type(e).__name__ + "); refusing to let it through. "
              "Check ~/.hermes/spiris/ then re-run.")
    if reason:
        block(reason)
    allow()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # A bug in this guard must never brick an UNRELATED shell command.
        # (Recognised writes are already fail-closed inside main().)
        sys.exit(0)
