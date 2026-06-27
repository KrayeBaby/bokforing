# bokforing — Claude Code plugin

Swedish bokföring automation for a small accounting practice, packaged as one
portable, versioned Claude Code plugin. It bundles the ledger-posting skill, a
read-only review-gate agent, and a production safety hook over the working engine
at `~/.hermes/spiris/`.

| Component | What it is |
|---|---|
| `skills/bokfor-visma/` | Posting skill — classify, map, dry-run, review, `--apply`, read back, then verify against facit — driving the live Spiris engine at `~/.hermes/spiris/`. Bundles `VISMA_MAPPNING`, `MANUAL_<klient>`, and `FACIT_COVERAGE`. |
| `agents/bokforing-granskare.md` | Read-only review-gate subagent that pre-reviews a sort plan or a voucher dry-run before the human OK. |
| `hooks/guard-spiris-apply.py` | PreToolUse Bash guard — blocks production writes without the `.prod-approved` token, and any `--apply` without a *recent* reviewed dry-run (freshness window, default 6 h, override via `BOKFORING_REVIEW_MAX_AGE_MIN`). Fail-**closed** on a recognised write it cannot verify; fail-open for everything unrelated. |
| `references/` | Sorting and structure docs: `SORTERINGSLOGIK`, `FILING_CONVENTIONS`, `FORETAGET_STRUKTUR`, `KLIENT_LEDGER` (git-ignored — see Notes). |

The document-sorting pipeline itself lives in the separate `foretaget-bokforing`
skill; this plugin adds the posting layer, the review gate, and the safety hook.

## Installation

The repository is both the plugin and a single-plugin marketplace
(`.claude-plugin/marketplace.json`), so it installs as an ordinary Claude Code
plugin — the skill, agent, and hook are auto-discovered once it is enabled, with no
symlinks or hand-edited `settings.json` entries.

```bash
# from a local clone
claude plugin marketplace add /path/to/bokforing
claude plugin install bokforing@bokforing-local
```

Verify with `claude plugin list` (shows `bokforing@bokforing-local … ✔ enabled`) and
`claude plugin details bokforing@bokforing-local` (lists the skill, the review-gate
agent, and the PreToolUse hook). Plugin components load at session start, so restart
Claude Code after enabling; after changing the source, run
`claude plugin update bokforing@bokforing-local` to refresh the installed copy.

## Notes

- **Client data stays local.** `references/` and `skills/*/references/` hold real client PII (roster, org numbers, plate ledger, per-client manuals). They are git-ignored and live only on the working machine plus a local backup — never pushed to GitHub.
- **Secret / PII scanning.** A `secret-scan` GitHub Action (pinned gitleaks) runs on every push and PR — credential patterns plus Swedish personnummer / org-nr shapes, and a job that fails if any sensitive path is tracked. Enable the matching local guard once per clone: `git config core.hooksPath .githooks`, then copy `.githooks/pii-denylist.example.txt` to `.githooks/pii-denylist.txt` and add the client names (that file is git-ignored).
- **Python.** The engine uses 3.10+ syntax and needs **Python ≥ 3.10** (a Homebrew or pyenv interpreter); the macOS system `python3` (`/usr/bin/python3`, 3.9) will not run it. The guard hook is 3.9-safe and runs under either.
- **Account truth.** For posting, the client's real accounts are authoritative (e.g. `4616`, `6992`); the `56xx` accounts in the sorting docs are standard-BAS expectations. `VISMA_MAPPNING` wins for the ledger.
- **Production is live** (Spiris production authorized 2026-06-21; first tenant live 2026-06-23). The `~/.hermes/spiris/.prod-approved` token is present, and the guard still requires it **plus** a fresh, sha256-bound reviewed dry-run for every `--prod` run.
