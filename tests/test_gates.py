"""
Tests for the enquiry triage gates.

These are invariant tests, not golden-number tests. Pinning "395 deflected"
would break the moment a keyword list changed and would say nothing about
whether the agent is safe - only that it still behaves as it did last week.

The central one is test_health_complaints_survive_the_safety_gate_being_deleted.
The README claims the health guardrail is not the safety gate but the absence
of a row in approved_answers.csv: there is no approved answer for a health
complaint in any language, so gate 4 has nothing to send even when gate 1 is
switched off. That is a strong claim, and an easy one to be wrong about. It is
asserted here rather than described.

Run with:  python -m pytest -q
"""

import json

import pandas as pd
import pytest

import main
from rules import ANSWER_COL, NEEDS_ORDER, REPEAT_THRESHOLD, evaluate

VERDICTS = {"AUTO_ANSWER", "ASSIST", "CLARIFY", "ESCALATE"}


@pytest.fixture(scope="session")
def scored():
    decisions, data, ctx = main.run()
    return decisions, data, ctx


@pytest.fixture(scope="session")
def extractions():
    with open(main.EXTRACTIONS) as fh:
        return {e["enquiry_id"]: e for e in json.load(fh)}


# --- coverage -------------------------------------------------------------

def test_every_enquiry_receives_exactly_one_verdict(scored):
    decisions, data, _ = scored
    assert len(decisions) == len(data["enquiries"])
    assert decisions.enquiry_id.is_unique


def test_verdicts_come_from_the_known_set(scored):
    decisions, _, _ = scored
    assert set(decisions.verdict) <= VERDICTS


# --- the safety claim -----------------------------------------------------

def test_no_health_complaint_is_ever_auto_answered(scored):
    decisions, _, _ = scored
    health = decisions[decisions.is_health_issue]
    assert not health.empty, "no health enquiries in the set - the test proves nothing"
    assert (health.verdict != "AUTO_ANSWER").all()


def test_health_complaints_survive_the_safety_gate_being_deleted(scored, extractions):
    """
    The claim worth testing. Switch gate 1 off entirely and re-score every
    health enquiry. Not one may be auto-answered, because no approved answer
    exists for the topic in any language - gate 4 has nothing to send.

    If someone ever adds a 'Health complaint' row to approved_answers.csv,
    this test fails, and it should: the guardrail would have quietly become
    one rule deep instead of two.
    """
    _, data, ctx = scored
    unsafe = dict(ctx)
    unsafe["_disable_safety"] = True

    verdicts = []
    for _, enq in data["enquiries"].iterrows():
        ext = extractions.get(enq.enquiry_id, {})
        if ext.get("is_health_issue"):
            verdicts.append(evaluate(enq, ext, unsafe))

    assert verdicts, "no health enquiries reached the gates"
    auto = [v for v in verdicts if v["verdict"] == "AUTO_ANSWER"]
    assert not auto, (
        f"{len(auto)} health complaint(s) auto-answered with the safety gate "
        f"disabled - the guardrail is now only the gate, not the missing row"
    )


def test_the_answer_library_has_no_health_row_in_any_language(scored):
    """The structural reason the test above passes. Asserted directly."""
    _, data, _ = scored
    answers = data["approved_answers"]
    topics = set(answers.topic.str.lower())
    assert not any("health" in t for t in topics)

    text_columns = [c for c in ANSWER_COL.values() if c in answers.columns]
    assert text_columns, "no approved-answer translation columns found"


# --- nothing goes out unapproved -----------------------------------------

def test_every_auto_answer_names_the_approved_answer_it_used(scored):
    decisions, _, _ = scored
    auto = decisions[decisions.verdict == "AUTO_ANSWER"]
    assert auto.answer_id.astype(str).str.strip().ne("").all()


def test_every_auto_answer_id_exists_in_the_approved_library(scored):
    decisions, data, _ = scored
    approved = set(data["approved_answers"].answer_id)
    sent = decisions[decisions.verdict == "AUTO_ANSWER"]
    assert set(sent.answer_id) <= approved


def test_no_reply_goes_out_empty(scored):
    decisions, _, _ = scored
    sent = decisions[decisions.verdict == "AUTO_ANSWER"]
    assert sent.draft_reply.astype(str).str.strip().ne("").all()


def test_an_unclassified_enquiry_is_never_answered(scored):
    """Gate 2 asks rather than guesses. Nothing without a topic may be sent."""
    decisions, _, _ = scored
    unclear = decisions[decisions.topic.isin(["Unclassified", "Unclear"])]
    assert (unclear.verdict != "AUTO_ANSWER").all()


# --- gates that need evidence --------------------------------------------

def test_nothing_needing_an_order_reference_is_sent_without_one(scored):
    decisions, _, _ = scored
    needs = decisions[decisions.topic.isin(NEEDS_ORDER)]
    sent = needs[needs.verdict == "AUTO_ANSWER"]
    assert sent.order_id.astype(str).str.strip().ne("").all()


def test_the_third_contact_this_month_goes_to_a_human(scored):
    """
    If the previous two answers had worked, there would not be a third
    message. Repeat contact escalates regardless of how answerable it looks.
    """
    decisions, _, _ = scored
    repeat = decisions[decisions.contact_seq >= REPEAT_THRESHOLD]
    assert not repeat.empty, "no repeat contacts in the set"
    assert (repeat.verdict != "AUTO_ANSWER").all()


# --- reproducibility ------------------------------------------------------

def test_scoring_the_same_inbox_twice_gives_the_same_answer(scored):
    first, _, _ = scored
    second, _, _ = main.run()
    pd.testing.assert_frame_equal(
        first.reset_index(drop=True),
        second.reset_index(drop=True),
    )
