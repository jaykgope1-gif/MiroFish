# sales_engine

Stress-tests for tenders and campaigns, sold as a TenderFind SA upsell.

| File | What it's for |
|---|---|
| `stress_test.py` | Runs a client document past a panel of simulated evaluators (tender) or buyers (campaign) on Claude, and writes a Before vs After report with rewrites. Refuses to run without recorded client consent; removes personal details first; stops at the budget. |
| `offers.md` | What you sell, the price ladder, words to avoid, the client consent wording, and an honest look at the R100,000 target. |
| `outreach.md` | Scripts for existing clients, Facebook groups, referral partners and agencies, inside your rules and POPIA. |
| `playbook_28_days.md` | Day-by-day plan from Thu 12 Nov 08:00 to Wed 9 Dec. |
| `leads.csv` + `pipeline.py` | Lead tracker (imports into Google Sheets) and the 20:00 check: money in vs target, follow-ups due. |

## Running a stress-test

One-time setup in the repository's `.env` (see `.env.example`):

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
USD_ZAR_RATE=18.5
```

Then, from `backend/`:

```bash
uv run python ../sales_engine/stress_test.py tender bid.pdf --client "ABC Civils" --dry-run
```

```bash
uv run python ../sales_engine/stress_test.py tender bid.pdf --client "ABC Civils" --criteria criteria.txt --consent "WhatsApp consent, A. Nkosi, 12 Nov 2026"
```

```bash
uv run python ../sales_engine/stress_test.py campaign landing.md --client "XYZ Agency" --audience "Owners of 5-50 person construction firms in Gauteng" --consent "Email consent, 12 Nov 2026"
```

`--criteria` is a text file with the tender's own functionality criteria, one per line; without it a generic rubric is used. Reports go to `sales_engine/reports/` (not committed to git). Delete client reports when you are done (POPIA).

Each evaluator runs on Claude Haiku 5.5; the summary and rewrites on Claude Sonnet 5.5. A 100-page bid costs roughly R7; `--dry-run` shows the estimate first.

For bigger campaign tests, MiroFish's full simulation (`/god` terminal) can run thousands of simulated social-media reactions; `stress_test.py` is the fast, cheap 24-hour product.
