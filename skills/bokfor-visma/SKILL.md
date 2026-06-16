---
name: bokfor-visma
description: >-
  Post classified Swedish bookkeeping documents to Visma eAccounting (eEkonomi)
  as vouchers (verifikationer) through the Spiris REST API. Use when booking or
  posting vouchers, running the Spiris poster, mapping a document to BAS accounts
  + VAT codes, doing the dry-run → review → --apply → read-back → verify-facit
  flow, onboarding a client's tenant (account/VAT/bank-account creation) before
  go-live, or taking a tenant to production. Swedish bokföring context
  (BAS-kontoplan, moms, omvänd skattskyldighet).
---

# Bokför till Visma eEkonomi via Spiris

The ledger lives in **Visma eAccounting**, written through the **Spiris REST API**.
The engine is owned end-to-end and lives at **`~/.hermes/spiris/`** (this is the
live source of truth; the copy under `~/Backups/claude-bokforing/spiris/` is a
backup and may lag by a revision). Every write is **dry-run → review → gated
`--apply` → per-voucher read-back → facit verify**, logged and reversible.

## Runtime (read first)

- **Interpreter:** the engine uses 3.10+ syntax (`str | Path`, `dict[str, Any]`).
  The `python3` on PATH is **3.9 and will crash** — run it with your **Python 3.11**.
- **Deps:** standard library only (raw `urllib`); nothing to `pip install`.
- **Creds:** loaded from `~/.hermes/spiris/sandbox.env` (`SPIRIS_CLIENT_ID/SECRET/REDIRECT_URI`).
  `assert_env()` allows **sandbox** (`sandbox.env`) by default; the gated **`--prod`**
  path is **built but inert** — it needs `--prod` + `prod.env` + a deliberate
  `~/.hermes/spiris/.prod-approved` token, else it STOPs cleanly.

## The safe posting workflow

The main poster is `write/batch_voucher_poster.py`. The write gate is **`--apply`**
everywhere (default = dry-run). Re-runs never double-post (dedup by `doc_ref`
across the `*_posted_*.jsonl` logs).

1. **Dry-run** (no writes) — produces a `review_batch_<utc>.md` table:
   ```
   python3.11 ~/.hermes/spiris/write/batch_voucher_poster.py --docs <docs.json>
   ```
   Classifies each doc `READY | REVIEW | ERROR | DUPLICATE`, prints the per-flow
   breakdown, balance re-check, sample payloads, and a read-only auth preflight.
2. **Review the plan** — read the generated `~/.hermes/spiris/harness/review_batch_*.md`.
   Run the `bokforing-granskare` subagent on it for an adversarial first pass, then
   you give the human OK. **Nothing posts before this.** (The safety hook blocks
   `--apply` if no review artifact exists, or if the newest one is stale.)
3. **Apply** (gated, sandbox) — posts READY vouchers, each read-back-verified:
   ```
   python3.11 ~/.hermes/spiris/write/batch_voucher_poster.py --docs <docs.json> --apply
   ```
   Useful flags: `--verify-facit` (byte-exact read-back vs the facit CSV — this is
   the full-coverage proof), `--samples N`, `--limit N`, `--sleep F`, `--no-preflight`.

## What maps to what (4 flows)

Full spec + the empirically-verified (code, rate) VAT resolver and account
universe: **`references/VISMA_MAPPNING.md`**. Worked debit/credit examples and the
rad-för-rad diff method: **`references/MANUAL_<klient>.md`**.

- **A — purchase / input VAT** (dominant): cost acct (DEBIT) + `2641` ingående moms
  (DEBIT, VatCode 48) + `2440` Leverantörsskulder (CREDIT).
- **B — sale / output VAT**: revenue acct (CREDIT) + output moms `2611`/`2621`/`2631`
  (CREDIT) + `1510` Kundfordringar (DEBIT).
- **C — omvänd skattskyldighet (bygg, 25%)**: `4425` (DEBIT, code 24) + `2614`
  (CREDIT, code 30) + `2647` (DEBIT, code 48) + `2440` (CREDIT).
- **D — EU/import (`2645`)**: import → **manual review**, not auto-posted.

Always-present details: `3740 Öres- och kronutjämning` rounding row (tolerance 6 kr,
larger gap = hard error); the `19xx` bank account is **personal per tenant** — never
generic; VAT is resolved by the **`(code, rate)` pair**, never code alone; the
`~75%` non-moms tail (payments, lön/arbetsgivaravgifter, omföringar, reclass) is
**manual by design** — this engine only auto-posts the moms-bearing A/B/C/D flows.

> **Account caveat to honour:** for *posting*, the client's actual accounts are the truth
> — `4616 Fordonsskatt och trängselskatt`, `6992` for non-deductible fines. The
> `56xx` numbers in the *sorting* docs (`KLIENT_LEDGER`) are standard-BAS
> expectation, not what gets posted. If the two ever need reconciling, `VISMA_MAPPNING`
> wins for the ledger.

## Onboarding a client's tenant (before posting)

Resolvers read `~/.hermes/spiris/tenant-cache.json` (per-tenant accounts, VAT GUIDs,
fiscal years, suppliers, customers). To prepare a tenant:

```
python3.11 ~/.hermes/spiris/write/accounts_discover.py     # read-only: which target accounts exist
python3.11 ~/.hermes/spiris/write/accounts_neighbors.py    # read-only: infer Type/VatCodeId for new ones
python3.11 ~/.hermes/spiris/write/accounts_create.py --apply        # create missing GL accounts (gated)
python3.11 ~/.hermes/spiris/write/bank_accounts_create.py --apply   # create personal bank accts 194x (gated)
python3.11 ~/.hermes/spiris/write/accounts_verify_refresh.py        # read-back + refresh the cache
```
`POST /v2/accounts` auto-propagates to all fiscal years (proven). Activate inactive
accounts; *create* truly-missing ones; *remap* only with the bookkeeper's decision.

## Go-live for a tenant (currently blocked on Spiris prod access)

Build + sandbox validation are **done**. Per tenant the remaining gated sequence is:
1. **(You)** obtain Spiris/Visma **production** OAuth app → `prod.env`, client authorizes.
2. The gated **`--prod`** code path is **built + inert** (triple-gated: `--prod` + `prod.env` + `.prod-approved`); it activates once prod creds exist.
3. Refresh the client's **real** prod chart, re-run the diff (prod chart ≠ sandbox chart).
4. Create/activate whatever's missing (gated write, your OK).
5. Re-verify byte-exact vs the **prod-resolved** VAT GUIDs, then dry-run → smoke 3 →
   read-back → rest → read-back.

The `.prod-approved` token (`~/.hermes/spiris/.prod-approved`) is the deliberate
human gate the safety hook checks before allowing any prod write.

## Hard rules

- Never `--apply` without a reviewed dry-run. Never post the non-moms tail with this
  engine. Per-tenant accounts/VAT always from the cache, never hardcoded. Every run
  is logged (`batch_posted_<utc>.jsonl`, 0600) and read-back-verified before "done".
