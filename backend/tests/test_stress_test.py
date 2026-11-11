import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sales_engine import stress_test as st  # noqa: E402


def test_redact_removes_personal_details_but_keeps_text():
    text, counts = st.redact(
        "Contact Thabo on 082 123 4567 or thabo@abc.co.za. ID 8001015009087. Account 62123456789. Grade 7CE."
    )
    assert "082" not in text and "thabo@" not in text and "8001015009087" not in text and "62123456789" not in text
    assert "Grade 7CE" in text
    assert counts == {"[EMAIL]": 1, "[ID-NUMBER]": 1, "[PHONE]": 1, "[NUMBER]": 1}


def test_apply_rewrites_replaces_exact_passages_and_appends_others():
    doc = "Intro.\nWe have done many projects.\nEnd."
    rewrites = [
        st.Rewrite(section="Experience", original_excerpt="We have done many projects.",
                   rewrite="We completed [CLIENT TO CONFIRM: number] road projects.", why="vague", facts_to_confirm=["number"]),
        st.Rewrite(section="Plan", original_excerpt="not in the document", rewrite="A 12-week plan.", why="missing", facts_to_confirm=[]),
    ]
    after, applied = st.apply_rewrites(doc, rewrites)
    assert "We have done many projects." not in after and "[CLIENT TO CONFIRM: number]" in after
    assert after.endswith("[Revised section: Plan]\nA 12-week plan.")
    assert applied == [True, False]


def _evaluation(score, decision):
    return st.Evaluation(
        scores=[st.CriterionScore(criterion=c, score=score, evidence="p.2", gap="none") for c in st.TENDER_CRITERIA],
        disqualifying_issues=[] if decision else ["No tax compliance PIN"],
        decision=decision, decision_reason="r", top_risks=["risk"], verdict="ok",
    )


class FakeAsyncClient:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    async def _parse(self, **kwargs):
        self.calls.append(kwargs)
        revised = "Revised" in kwargs["system"][1]["text"] or "[CLIENT TO CONFIRM" in kwargs["system"][1]["text"]
        if kwargs["output_format"] is st.Synthesis:
            parsed = st.Synthesis(executive_summary="Summary.", strengths=["Clear scope"],
                                  fixes=[st.Fix(priority=1, section="Compliance", problem="PIN missing", fix="Attach PIN")],
                                  rewrites=[st.Rewrite(section="Experience", original_excerpt="We have done many projects.",
                                                       rewrite="We completed [CLIENT TO CONFIRM: number] projects.",
                                                       why="vague", facts_to_confirm=["number"])])
        else:
            parsed = _evaluation(8 if revised else 5, revised)
        return SimpleNamespace(model=kwargs["model"], stop_reason="end_turn", parsed_output=parsed,
                               usage={"input_tokens": 5000, "output_tokens": 800})


def test_full_run_writes_before_and_after_report(tmp_path, monkeypatch):
    doc = tmp_path / "bid.md"
    doc.write_text("Bid for road maintenance.\nWe have done many projects.\nCall 0821234567.")
    fake = FakeAsyncClient()
    monkeypatch.setattr(st.claude, "make_client", lambda asynchronous=False: fake)
    monkeypatch.setattr(st.Config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(st.Config, "ANTHROPIC_API_KEY", "test")

    st.main(["tender", str(doc), "--client", "ABC Civils", "--consent", "signed form 12 Nov", "--out", str(tmp_path / "out")])

    report = next((tmp_path / "out").glob("*-abc-civils")) / "report.md"
    text = report.read_text()
    assert "| **Overall (0-10)** | **5.0** | **8.0** | **+3.0** |" in text
    assert "0 of 7** before, **7 of 7** after" in text
    assert "No tax compliance PIN" in text
    assert "do **not** predict a win" in text
    assert "1 [PHONE]" in text
    # evaluators on the fast model, the summary on the report model with the refusal fallback
    models = [c["model"] for c in fake.calls]
    assert models.count(st.Config.claude_model("fast")) == 14 and models.count(st.Config.claude_model("report")) == 1
    report_call = next(c for c in fake.calls if c["output_format"] is st.Synthesis)
    assert report_call.get("fallbacks") == "default"
    # no client phone number reached the API
    assert all("0821234567" not in str(c["system"]) for c in fake.calls)


def test_refuses_without_consent(tmp_path):
    doc = tmp_path / "bid.txt"
    doc.write_text("A bid.")
    with pytest.raises(SystemExit, match="consent"):
        st.main(["tender", str(doc), "--client", "X"])
