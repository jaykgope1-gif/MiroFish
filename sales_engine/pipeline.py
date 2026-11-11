"""
Pipeline check for the 20:00 review.

    python sales_engine/pipeline.py                 # uses sales_engine/leads.csv
    python sales_engine/pipeline.py my_export.csv   # a CSV exported from your Google Sheet

Columns are those of leads.csv. stage is one of:
new, contacted, call_booked, proposal, won, lost.
paid_zar is money actually received; value_zar is the deal size.
"""

import csv
import os
import sys
from datetime import date

TARGETS = [  # cumulative stress-test revenue (offers.md)
    (date(2026, 11, 15), 0),
    (date(2026, 11, 22), 4_500),
    (date(2026, 11, 29), 12_000),
    (date(2026, 12, 6), 22_000),
    (date(2026, 12, 9), 25_000),
]
# Rough chance a deal at each stage closes, for the weighted pipeline.
CHANCE = {"new": 0.05, "contacted": 0.10, "call_booked": 0.30, "proposal": 0.50, "won": 1.0, "lost": 0.0}


def money(value):
    try:
        return float(str(value).replace("R", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def main(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.csv")
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("name") or "").strip()]

    today = date.today()
    paid = sum(money(r.get("paid_zar")) for r in rows)
    weighted = sum(money(r.get("value_zar")) * CHANCE.get((r.get("stage") or "").strip(), 0)
                   for r in rows if (r.get("stage") or "").strip() not in ("won", "lost"))
    target_date, target = next(((d, t) for d, t in TARGETS if d >= today), TARGETS[-1])

    print(f"Paid so far: R{paid:,.0f}   Target by {target_date:%a %d %b}: R{target:,.0f}   "
          f"{'ON TRACK' if paid >= target else f'R{target - paid:,.0f} to go'}")
    print(f"Open pipeline (weighted): R{weighted:,.0f}")

    by_stage = {}
    for r in rows:
        stage = (r.get("stage") or "new").strip()
        by_stage[stage] = by_stage.get(stage, 0) + 1
    print("Leads by stage: " + ", ".join(f"{s} {n}" for s, n in sorted(by_stage.items())))

    due = []
    for r in rows:
        if (r.get("stage") or "").strip() in ("won", "lost"):
            continue
        try:
            when = date.fromisoformat((r.get("next_action_date") or "").strip())
        except ValueError:
            due.append((date.min, r))
            continue
        if when <= today:
            due.append((when, r))
    print(f"\nNext actions due ({len(due)}):")
    for when, r in sorted(due, key=lambda x: x[0]):
        label = "no date set" if when == date.min else f"{when:%d %b}"
        print(f"  [{label}] {r.get('name')} ({r.get('company')}): {r.get('next_action') or 'decide next step'}")
    no_consent = [r for r in rows if not (r.get("consent_to_contact") or "").lower().startswith("yes")
                  and (r.get("source") or "") not in ("existing_client", "inbound")]
    if no_consent:
        print(f"\n{len(no_consent)} lead(s) without recorded consent: one consent-asking message only (outreach.md).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
