"""
24-Hour Buyer & Evaluator Stress-Test.

Runs a client's document past a panel of simulated evaluators on Claude,
then writes a "Before vs After" report with rewrites of the weakest parts.

    # A tender bid, scored the way an evaluation committee would read it
    python sales_engine/stress_test.py tender bid.pdf --client "ABC Civils" \
        --criteria tender_criteria.md --consent "Signed consent form, T. Mokoena, 12 Nov 2026"

    # An ad / landing page, read by simulated buyers
    python sales_engine/stress_test.py campaign landing.md --client "XYZ Agency" \
        --audience "Owners of 5-50 person construction firms in Gauteng" --consent "..."

    # See what it would cost first (no API calls, no consent needed)
    python sales_engine/stress_test.py tender bid.pdf --client "ABC Civils" --dry-run

Run it from the repository root with the backend's Python:
    cd backend && uv run python ../sales_engine/stress_test.py ...
It uses the same .env as MiroFish (ANTHROPIC_API_KEY, model names,
RUN_BUDGET_ZAR, USD_ZAR_RATE).

Models: each evaluator runs on the fast model (Claude Haiku 5.5 by default);
the summary and the rewrites run on the report model (Claude Sonnet 5.5).

What it is and is not: the panel is Claude role-playing evaluators. It finds
gaps, unclear claims and missing documents quickly; it is not a real
committee and its scores do not predict a win. Price and preference points
(PPPFA) are calculated by formula and are not assessed. The report says so.

Privacy (POPIA): the document is sent to Anthropic's API. The tool refuses
to run without --consent, and removes ID numbers, email addresses, phone
numbers and long account-style numbers before sending unless --no-redact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.config import Config  # noqa: E402  (loads the repository .env)
from app.utils import claude  # noqa: E402
from app.utils.file_parser import FileParser  # noqa: E402

# ------------------------------------------------------------------ panels

TENDER_PANEL = [
    ("Technical evaluator", "the end-user department's technical lead. You judge whether the bidder understands the scope and has a credible methodology."),
    ("SCM compliance officer", "the supply chain management officer. You look first for anything that disqualifies the bid: missing or unsigned SBD forms, CSD number, tax compliance status PIN, B-BBEE certificate or sworn affidavit, CIDB grading where the work requires it, and any returnable document the tender asks for."),
    ("Costing reviewer", "a finance reviewer. You check that pricing is complete, consistent with the scope and the bill of quantities, and not abnormally low or high. You do not award price points; you flag risks."),
    ("Risk and legal reviewer", "a contracts and legal reviewer. You look for qualifications, exclusions, conflicting statements and anything that shifts risk to the department."),
    ("Capacity assessor", "an assessor of experience and capacity. You want verifiable references, relevant completed projects, CVs of key personnel with qualifications, and proof of equipment and staff."),
    ("Project manager", "a programme manager. You judge whether the project plan, timelines, resources and deliverables are realistic and specific."),
    ("Evaluation committee chair", "the sceptical chair of the bid evaluation committee. You ask whether this bid would survive adjudication and audit, and whether its claims are backed by evidence in the document."),
]

TENDER_CRITERIA = [
    "Compliance with mandatory requirements and returnable documents",
    "Understanding of the scope",
    "Methodology and approach",
    "Project plan, timeline and resources",
    "Company experience and verifiable references",
    "Key personnel qualifications and experience",
    "Clarity and evidence behind claims",
]

CAMPAIGN_PANEL = [
    ("Price-sensitive owner", "a business owner who watches every rand and needs to see value quickly."),
    ("Sceptical decision-maker", "a senior decision-maker who has been burned by vendors before and looks for proof."),
    ("Busy scanner", "someone who gives this eight seconds on a phone between meetings."),
    ("Competitor's customer", "someone who already uses a competitor and needs a reason to switch."),
    ("Detail checker", "a careful buyer who reads the fine print, pricing and terms."),
    ("Internal champion", "an employee who likes the offer but must convince a boss to approve it."),
    ("First-time buyer", "someone who has never bought this kind of service and needs it explained simply."),
]

CAMPAIGN_CRITERIA = [
    "Clarity of the offer",
    "Relevance to my problem",
    "Credibility and proof",
    "Difference from alternatives",
    "Strength of the call to action",
    "Perceived value for the price",
    "Trust and perceived risk",
]


class CriterionScore(BaseModel):
    criterion: str
    score: int  # 0-10
    evidence: str
    gap: str


class Evaluation(BaseModel):
    scores: List[CriterionScore]
    disqualifying_issues: List[str]
    decision: bool  # tender: would shortlist; campaign: would take the next step
    decision_reason: str
    top_risks: List[str]
    verdict: str


class Fix(BaseModel):
    priority: int
    section: str
    problem: str
    fix: str


class Rewrite(BaseModel):
    section: str
    original_excerpt: str
    rewrite: str
    why: str
    facts_to_confirm: List[str]


class Synthesis(BaseModel):
    executive_summary: str
    strengths: List[str]
    fixes: List[Fix]
    rewrites: List[Rewrite]


# ------------------------------------------------------------------ privacy

REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?<!\d)\d{13}(?!\d)"), "[ID-NUMBER]"),
    (re.compile(r"(?:\+27|\b0)[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{9,12}(?!\d)"), "[NUMBER]"),
]


def redact(text: str):
    counts = {}
    for pattern, label in REDACTIONS:
        text, n = pattern.subn(label, text)
        if n:
            counts[label] = n
    return text, counts


# ------------------------------------------------------------------ prompts

def system_blocks(mode: str, document: str, context: str, criteria: List[str]):
    """The document goes last and is cached, so every evaluator call reuses it."""
    if mode == "tender":
        frame = (
            "You are a member of a South African public-sector bid evaluation committee "
            "reviewing a bidder's submission. Be strict and specific: quote or point to the part "
            "of the document behind every score. Price points and preference (specific goals) "
            "points are calculated by formula elsewhere; do not award them."
        )
    else:
        frame = (
            "You are a potential buyer reading a marketing campaign (an ad, landing page or sales "
            "email). React honestly as the person described, the way real buyers do, and point "
            "to the exact words behind each reaction."
        )
    rubric = "\n".join(f"- {c}" for c in criteria)
    return [
        {"type": "text", "text": (
            f"{frame}\n\nScore each of these criteria from 0 (absent or disqualifying) to 10 "
            f"(excellent, fully evidenced), using exactly these names:\n{rubric}\n\n"
            f"Context from the client:\n{context or '(none)'}"
        )},
        {"type": "text", "text": f"<document>\n{document}\n</document>", "cache_control": {"type": "ephemeral"}},
    ]


def persona_prompt(mode: str, role: str, description: str) -> str:
    decision = ("whether you would recommend this bid for the shortlist" if mode == "tender"
                else "whether you would take the next step (click, enquire, buy)")
    return (
        f"You are the {role}: {description}\n\n"
        f"Evaluate the document. In `decision`, say {decision}. List anything that would "
        "disqualify it outright in `disqualifying_issues` (empty if none)."
    )


SYNTHESIS_PROMPT = """You lead a stress-test of the document in the system prompt. Below are the
panel's evaluations as JSON.

1. executive_summary: 5-8 plain sentences for the client's managing director: where the
   document stands, the biggest risks, and what to fix first.
2. strengths: what to keep.
3. fixes: the changes that would most improve the panel's scores, highest impact first.
4. rewrites: rewrite the {n} weakest passages. For each, `original_excerpt` must be copied
   EXACTLY from the document (one paragraph or less) so it can be replaced. In `rewrite`
   never invent facts, numbers, names, references or qualifications: where the client must
   supply a fact, write [CLIENT TO CONFIRM: what is needed] and list it in `facts_to_confirm`.

Panel evaluations:
{evaluations}"""


# ------------------------------------------------------------------ running

class Spend:
    def __init__(self, budget_zar: float):
        self.usd = 0.0
        self.calls = 0
        self.budget_zar = budget_zar

    def add(self, response) -> None:
        self.usd += claude.usd_cost(response.model, response.usage)
        self.calls += 1

    @property
    def zar(self) -> float:
        return self.usd * Config.USD_ZAR_RATE

    def check(self) -> None:
        if self.zar > self.budget_zar:
            raise SystemExit(f"Stopped: spend R{self.zar:.2f} passed the R{self.budget_zar:.0f} budget.")


async def ask(client, spend: Spend, tier: str, system, prompt: str, output_format):
    model = Config.claude_model("report" if tier == "report" else "fast")
    kwargs = dict(
        model=model, max_tokens=16000, system=system, output_format=output_format,
        messages=[{"role": "user", "content": prompt}],
    )
    # Evaluators judge, so they get more effort than MiroFish's bulk "fast" calls.
    effort = Config.claude_effort("report") if tier == "report" else os.environ.get("STRESS_PANEL_EFFORT", "medium")
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if claude.uses_fallback(model):
        kwargs.update(betas=[claude.FALLBACK_BETA], fallbacks="default")
    response = await client.beta.messages.parse(**kwargs)
    spend.add(response)
    spend.check()
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError(f"{model} returned no usable answer (stop_reason={response.stop_reason})")
    return response.parsed_output


async def run_panel(client, spend, mode, document, context, criteria, panel, concurrency=4):
    system = system_blocks(mode, document, context, criteria)
    gate = asyncio.Semaphore(concurrency)

    async def one(role, description):
        async with gate:
            evaluation = await ask(client, spend, "panel", system, persona_prompt(mode, role, description), Evaluation)
            return role, evaluation

    # The first call writes the document to the cache; the rest read it.
    first = await one(*panel[0])
    rest = await asyncio.gather(*(one(*p) for p in panel[1:]))
    return [first, *rest]


def scorecard(results, criteria):
    """Average and spread per criterion, plus decisions."""
    table = {}
    for criterion in criteria:
        values = [
            max(0, min(10, s.score)) for _, e in results for s in e.scores
            if s.criterion.strip().lower() == criterion.lower()
        ]
        table[criterion] = (statistics.mean(values) if values else None,
                            statistics.pstdev(values) if len(values) > 1 else 0.0)
    overall = [v for v, _ in table.values() if v is not None]
    return {
        "criteria": table,
        "overall": statistics.mean(overall) if overall else 0.0,
        "decisions": sum(1 for _, e in results if e.decision),
        "panel": len(results),
        "disqualifying": sorted({i for _, e in results for i in e.disqualifying_issues if i.strip()}),
    }


def apply_rewrites(document: str, rewrites: List[Rewrite]):
    after, applied = document, []
    for r in rewrites:
        if r.original_excerpt and r.original_excerpt in after:
            after = after.replace(r.original_excerpt, r.rewrite, 1)
            applied.append(True)
        else:
            after += f"\n\n[Revised section: {r.section}]\n{r.rewrite}"
            applied.append(False)
    return after, applied


def estimate_usd(document: str, panel_size: int) -> float:
    """
    Rough upper estimate (~4 characters per token), assuming no cache hits:
    the panel reads the document twice (before and after), the report model once.
    """
    doc_tokens = len(document) / 4 + 1500
    panel_call = claude.usd_cost(Config.claude_model("fast"), {"input_tokens": doc_tokens, "output_tokens": 2500})
    report_call = claude.usd_cost(
        Config.claude_model("report"),
        {"input_tokens": doc_tokens + 2 * panel_size * 800, "output_tokens": 12000},
    )
    return 2 * panel_size * panel_call + report_call


# ------------------------------------------------------------------ report

def fmt(value):
    return "-" if value is None else f"{value:.1f}"


def render(args, mode, criteria, before, after, synthesis, rewrites_applied, spend, redactions, panel_before, panel_after):
    decision_word = "shortlist" if mode == "tender" else "act"
    lines = [
        f"# {'Evaluator' if mode == 'tender' else 'Buyer'} Stress-Test: {args.client}",
        "",
        f"Document: `{os.path.basename(args.document)}`  ",
        f"Date: {datetime.now():%d %B %Y}  ",
        f"Panel: {before['panel']} simulated {'evaluators' if mode == 'tender' else 'buyers'} "
        f"({Config.claude_model('fast')}); summary and rewrites by {Config.claude_model('report')}",
        "",
        "## Scorecard",
        "",
        "| Criterion | Before | After | Change | Panel spread (before) |",
        "|---|---:|---:|---:|---:|",
    ]
    for criterion in criteria:
        b, spread = before["criteria"][criterion]
        a = after["criteria"][criterion][0] if after else None
        change = "-" if (a is None or b is None) else f"{a - b:+.1f}"
        lines.append(f"| {criterion} | {fmt(b)} | {fmt(a)} | {change} | {spread:.1f} |")
    lines += [
        f"| **Overall (0-10)** | **{before['overall']:.1f}** | **{after['overall']:.1f}** | "
        f"**{after['overall'] - before['overall']:+.1f}** | |" if after else
        f"| **Overall (0-10)** | **{before['overall']:.1f}** | - | - | |",
        "",
        f"Panel members who would {decision_word}: **{before['decisions']} of {before['panel']}** before"
        + (f", **{after['decisions']} of {after['panel']}** after the rewrites." if after else "."),
        "",
    ]
    if before["disqualifying"]:
        lines += ["### Possible disqualifying issues (fix before anything else)", ""]
        lines += [f"- {i}" for i in before["disqualifying"]] + [""]
    lines += ["## Executive summary", "", synthesis.executive_summary, "", "## What to keep", ""]
    lines += [f"- {s}" for s in synthesis.strengths] + ["", "## Priority fixes", ""]
    lines += [f"{f.priority}. **{f.section}**: {f.problem} *Fix:* {f.fix}" for f in sorted(synthesis.fixes, key=lambda f: f.priority)]
    lines += ["", "## Before vs After rewrites", ""]
    for r, applied in zip(synthesis.rewrites, rewrites_applied):
        lines += [f"### {r.section}", "", "**Before**", "", "> " + r.original_excerpt.replace("\n", "\n> "), "",
                  "**After**", "", "> " + r.rewrite.replace("\n", "\n> "), "", f"*Why:* {r.why}", ""]
        if r.facts_to_confirm:
            lines += ["*Facts the client must confirm before using this:*", ""] + [f"- {x}" for x in r.facts_to_confirm] + [""]
        if not applied:
            lines += ["*(The original passage could not be matched exactly; the rewrite was scored as an added section.)*", ""]
    lines += ["## What each panel member said (before)", "", f"| Panel member | Would {decision_word} | Verdict |", "|---|---|---|"]
    lines += [f"| {role} | {'yes' if e.decision else 'no'} | {e.verdict.replace('|', '/')} |" for role, e in panel_before]
    if panel_after:
        lines += ["", "## What each panel member said (after)", "", f"| Panel member | Would {decision_word} | Verdict |", "|---|---|---|"]
        lines += [f"| {role} | {'yes' if e.decision else 'no'} | {e.verdict.replace('|', '/')} |" for role, e in panel_after]
    lines += [
        "", "## How to read this", "",
        "- The panel is an AI simulation of evaluators/buyers. It is designed to find gaps fast; it is not "
        "the real committee or market, and its scores do **not** predict a win or a conversion rate.",
        "- The \"after\" scores come from the same kind of panel that suggested the rewrites, so they are "
        "optimistic. Treat the change as a sign of direction, not a measurement.",
    ]
    if mode == "tender":
        lines.append("- Price and preference (specific goals) points are calculated by formula under the PPPFA "
                     "and were not assessed. Check every returnable document against the tender's own list.")
    lines += [
        "- Every [CLIENT TO CONFIRM] item must be filled with true, verifiable information before submission.",
        "",
        f"<sub>Privacy: {'personal details removed before analysis: ' + ', '.join(f'{v} {k}' for k, v in redactions.items()) if redactions else 'no personal details detected' if not args.no_redact else 'redaction switched off by operator'}. "
        f"Consent: {args.consent}. Model cost: ${spend.usd:.3f} (R{spend.zar:.2f}) over {spend.calls} calls.</sub>",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=["tender", "campaign"])
    parser.add_argument("document", help="PDF, Markdown or text file")
    parser.add_argument("--client", required=True)
    parser.add_argument("--criteria", help="file with one evaluation criterion per line (tender: the tender's functionality criteria)")
    parser.add_argument("--context", default="", help="anything the panel should know (tender number, scope summary)")
    parser.add_argument("--audience", default="", help="campaign: who the buyers are")
    parser.add_argument("--rewrites", type=int, default=3, help="how many weak passages to rewrite (0 = scorecard only)")
    parser.add_argument("--consent", default="", help="how the client's written consent to AI processing was recorded")
    parser.add_argument("--no-redact", action="store_true", help="send the document without removing personal details")
    parser.add_argument("--budget-zar", type=float, default=Config.RUN_BUDGET_ZAR)
    parser.add_argument("--out", default=os.path.join(ROOT, "sales_engine", "reports"))
    parser.add_argument("--dry-run", action="store_true", help="estimate the cost and stop")
    args = parser.parse_args(argv)

    if not FileParser.is_supported(args.document):
        raise SystemExit("Use a PDF, .md, .markdown or .txt file.")
    text = FileParser.extract_text(args.document).strip()
    if not text:
        raise SystemExit("No text found in the document (a scanned PDF needs OCR first).")
    document, redactions = (text, {}) if args.no_redact else redact(text)

    mode = args.mode
    criteria = TENDER_CRITERIA if mode == "tender" else CAMPAIGN_CRITERIA
    if args.criteria:
        with open(args.criteria, encoding="utf-8") as handle:
            criteria = [line.strip(" -*\t") for line in handle if line.strip(" -*\t\n")]
    panel = TENDER_PANEL if mode == "tender" else CAMPAIGN_PANEL
    context = args.context
    if mode == "campaign" and args.audience:
        context = f"Target buyers: {args.audience}\n{context}"

    estimate = estimate_usd(document, len(panel))
    print(f"Document: {len(document):,} characters (~{len(document) // 4:,} tokens); "
          f"{sum(redactions.values())} personal details removed.")
    print(f"Estimated cost: up to ${estimate:.2f} (R{estimate * Config.USD_ZAR_RATE:.2f}); budget R{args.budget_zar:.0f}.")
    if args.dry_run:
        return
    if not args.consent.strip():
        raise SystemExit("Refusing to send a client document to the API without --consent "
                         "(say how the client's written consent was recorded).")
    if estimate * Config.USD_ZAR_RATE > args.budget_zar:
        raise SystemExit("The estimate is over budget. Shorten the document or raise --budget-zar.")
    if Config.LLM_PROVIDER != "anthropic" or not Config.ANTHROPIC_API_KEY:
        raise SystemExit("Set LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY in .env.")

    asyncio.run(run(args, mode, document, context, criteria, panel, redactions))


async def run(args, mode, document, context, criteria, panel, redactions):
    client = claude.make_client(asynchronous=True)
    spend = Spend(args.budget_zar)

    print(f"Panel of {len(panel)} reading the document...")
    panel_before = await run_panel(client, spend, mode, document, context, criteria, panel)
    before = scorecard(panel_before, criteria)
    print(f"  before: {before['overall']:.1f}/10, {before['decisions']}/{before['panel']} positive")

    print("Summarising and rewriting...")
    evaluations = json.dumps([{"panel_member": r, **e.model_dump()} for r, e in panel_before], ensure_ascii=False)
    synthesis = await ask(
        client, spend, "report", system_blocks(mode, document, context, criteria),
        SYNTHESIS_PROMPT.format(n=args.rewrites, evaluations=evaluations), Synthesis,
    )
    synthesis.rewrites = synthesis.rewrites[: args.rewrites]

    after, panel_after, applied = None, None, []
    if synthesis.rewrites:
        revised, applied = apply_rewrites(document, synthesis.rewrites)
        print("Panel reading the revised document...")
        panel_after = await run_panel(client, spend, mode, revised, context, criteria, panel)
        after = scorecard(panel_after, criteria)
        print(f"  after:  {after['overall']:.1f}/10, {after['decisions']}/{after['panel']} positive")

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    slug = re.sub(r"[^a-z0-9]+", "-", args.client.lower()).strip("-") or "client"
    out_dir = os.path.join(args.out, f"{stamp}-{slug}")
    os.makedirs(out_dir, exist_ok=True)
    report = render(args, mode, criteria, before, after, synthesis, applied, spend, redactions, panel_before, panel_after)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(report)
    with open(os.path.join(out_dir, "panel.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "before": [{"panel_member": r, **e.model_dump()} for r, e in panel_before],
            "after": [{"panel_member": r, **e.model_dump()} for r, e in panel_after or []],
            "synthesis": synthesis.model_dump(),
            "cost_usd": round(spend.usd, 4),
        }, handle, ensure_ascii=False, indent=2)
    print(f"Report: {os.path.join(out_dir, 'report.md')}  (cost R{spend.zar:.2f}, {spend.calls} calls)")


if __name__ == "__main__":
    main()
