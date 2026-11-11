# 28 days: Thu 12 Nov to Wed 9 Dec 2026

This runs **inside** the TenderFind 60-day sprint (Day 4 to Day 31), not instead of it. TenderFind work that brings money this week comes first. Stress-tests are an upsell to the same people.

## Daily rhythm

| Time | What |
|---|---|
| 06:35 | Read the task email |
| 08:00-09:00 | Reply to every enquiry (1-hour rule). Update `leads.csv` / your Google Sheet. |
| 09:00-11:00 | Paid work first: registrations, packs, Bid Help, stress-tests due today |
| 11:00-12:30 | Lead generation: 1 Facebook value post or 10 helpful comments; follow-ups due today |
| 14:00-16:00 | Referral partner visits (Tue/Thu), agency emails/calls (Mon/Wed) |
| 20:00 | Check-in: `python sales_engine/pipeline.py` |

## Week 1 (12-15 Nov): proof

**Thu 12 Nov, 08:00**

1. Create an Anthropic API account at platform.claude.com. Add a card and buy $10 of credits (about R185, enough for 20+ stress-tests). Create an API key.
2. Put it in `.env` (see `.env.example`): `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`, `USD_ZAR_RATE=` today's rate.
3. Run a stress-test on a bid of your own, or a public sample tender document. Never a client's document for this.
   ```bash
   cd backend
   uv run python ../sales_engine/stress_test.py tender sample_bid.pdf --client "Sample" --consent "own document"
   ```
4. Read the report. Is it actually useful? If not, stop here and tell me what's wrong before selling it.

**Fri 13 Nov:** offer 2 free Bid Checks to existing TenderFind clients with a bid due soon, in exchange for honest feedback and a testimonial if it helped. Get written consent first (offers.md).

**Sat 14 / Sun 15 Nov:** run the 2 free tests, deliver within 24 hours, ask for feedback. Turn the best one, anonymised and with permission, into a 1-page sample report to print.

**Target:** 2 tests done, 1 sample report. R0 is fine this week.

## Week 2 (16-22 Nov): first sales

- Message every existing TenderFind client (outreach.md §1). Aim for 3 paid Bid Checks (R4,500).
- 2 Facebook value posts (outreach.md §2).
- Tue and Thu: visit 5 referral partners each day with the sample report (§3).
- Wed: email 10 agencies once each (§4).

**Target:** R4,500 stress-test revenue, on top of TenderFind's R10k.

## Week 3 (23-29 Nov): first full stress-test and agency pilot

- Offer the R4,500 full Stress-Test + Rewrite to Bid Check clients who were happy.
- Call agencies that replied; book 1 paid pilot (R3,500).
- 28 Nov: mention Bid Checks at the "Get Tender-Ready" workshop. No hard sell.

**Target:** R12,000 cumulative.

## Week 4 (30 Nov-6 Dec): partners

- With 3+ full tests and 2 testimonials, offer Tender Bid Desk Partner (R10,000/month) to your 2 most active bidders.
- Offer the agency that did a pilot the White-Label Partner (R12,500/month).

**Target:** R22,000 cumulative.

## Days 26-28 (7-9 Dec): review

- What sold, at what price, from which source? Put the numbers in the sheet.
- Decide: keep it as a TenderFind upsell, raise prices, or drop it. Decide on numbers, not on hope.

**Target:** R25,000-R30,000 cumulative. More only if partners sign early.

## If you are behind

Do not add new ideas. Go back to existing clients (§1) and referral partners (§3); they convert best for you. Quality first: if you are too busy to deliver within 24 hours, say no or move the date.
