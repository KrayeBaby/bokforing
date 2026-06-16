# bokforing — Claude plugin

Swedish bokföring automation for the Företaget clients. Packages the working
system into one portable, versioned unit:

| Component | What it is |
|---|---|
| `skills/bokfor-visma/` | Posting skill: classify → map → dry-run → review → `--apply` → read-back → verify-facit, against the live Spiris engine at `~/.hermes/spiris/`. Bundles `VISMA_MAPPNING`, `MANUAL_<klient>`, `FACIT_COVERAGE`. |
| `agents/bokforing-granskare.md` | Read-only review-gate subagent that pre-reviews a sort plan or a voucher dry-run before the human OK. |
| `hooks/guard-spiris-apply.py` | PreToolUse Bash guard: blocks prod writes without the `.prod-approved` gate, and `--apply` without a *recent* reviewed dry-run (freshness window, default 6 h, override `BOKFORING_REVIEW_MAX_AGE_MIN`). Fail-**closed** on a recognised write it cannot verify; fail-open for everything unrelated. |
| `references/` | Sorting/structure docs: `SORTERINGSLOGIK`, `FILING_CONVENTIONS`, `FORETAGET_STRUKTUR`, `KLIENT_LEDGER`. |

The actual file-sorting pipeline stays in the existing `foretaget-bokforing`
skill; this plugin adds the posting layer, the review gate, and the safety rail.

## Activation

**Now (this machine):** the skill + agent are symlinked into `~/.claude/`, and the
hook is wired into `~/.claude/settings.json` by absolute path — active immediately.

**Portable / Cowork:** hand off this directory; the standard `.claude-plugin/plugin.json`
makes it a normal Claude plugin (skills/agents/hooks auto-discovered). Formal
marketplace packaging (`marketplace.json` + `claude plugin install`) is a follow-up
if you want versioned distribution.

## Notes

- **Client data stays local.** `references/` and `skills/*/references/` hold real client PII (roster, org numbers, plate ledger, per-client manuals); they are git-ignored and live only on this machine + `~/Backups/claude-bokforing` — never pushed to GitHub.
- **Secret/PII scanning.** A `secret-scan` GitHub Action (pinned gitleaks) runs on every push/PR — secrets plus Swedish personnummer/org-nr shapes, and a job that fails if any sensitive path gets tracked. Activate the matching local guard once per clone: `git config core.hooksPath .githooks`, then `cp .githooks/pii-denylist.example.txt .githooks/pii-denylist.txt` and add client names (that file is git-ignored).
- Engine needs **Python ≥3.10**; run it with your **Python 3.11** (the system `python3` is 3.9 and crashes on the 3.10+ syntax).
- For *posting*, the client's real accounts are truth (`4616`, `6992`); the `56xx` in the
  sorting docs are standard-BAS expectation. `VISMA_MAPPNING` wins for the ledger.
- Production is gated: create `~/.hermes/spiris/.prod-approved` deliberately, once
  Spiris prod is authorized, to let the guard pass a `--prod` run.
