# -*- coding: utf-8 -*-
"""
store.py - the audit trail. Three files.

    store/decisions.csv   what the agent decided, and why          900 rows
    store/drafts.csv      WHICH APPROVED ANSWER was used, verbatim
    store/reviews.csv     what a human did about it   empty until app.py

WHY drafts.csv IS A SEPARATE FILE
It is this build's equivalent of the invoice agent's citations.csv. There the
question was "which clause justified this rejection?" Here it is "which
approved answer went out under Blood's name, in which language, and did a human
see it first?"

For a femcare and infant-care brand that second question is the whole
governance story. Product advice sent automatically, in Blood's voice, in
Bahasa Indonesia, to a mother asking about her newborn - that is not a log
line, it is a published claim in a language most of the team cannot read.
drafts.csv is the record of every one of them.

THREE HARD RULES. This file exits non-zero if any is broken.

  1  NOTHING IS SENT WITHOUT AN APPROVED SOURCE
     Every AUTO_ANSWER must carry an answer_id and the text that went out.
     An auto-answer with no approved source is a reader improvising in
     Blood's voice, which is exactly what must never happen.

  2  NO HEALTH COMPLAINT IS EVER AUTO-ANSWERED
     Checked here as well as in rules.py, on purpose. A safety property
     asserted in one place is a safety property one careless edit away from
     being gone.

  3  NOTHING GOES OUT IN A LANGUAGE WE DID NOT APPROVE
     New in this version, and it only exists because the inbox is multilingual.
     Every draft must match a pre-approved translation in approved_answers.csv,
     character for character after the order number is filled in. If a reply
     ever gets machine-translated at run time, this rule catches it.

WHY reviews.csv IS WRITTEN EMPTY
It is the shape of the human's answer, created before there is an answer. In
production it becomes the training label - every approve, edit and override is
a datapoint the backtest could never give you. It is only created if it does
not already exist, so a re-run never wipes a reviewer's work.
"""

import os
import re
from datetime import datetime, timezone

import pandas as pd

from rules import ANSWER_COL

STORE = "store"


def write_all(dec, data, store=STORE):
    os.makedirs(store, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---------------- 1. decisions.csv ----------------
    decisions = dec.copy()
    decisions["decided_at"] = stamp
    decisions = decisions[[
        "enquiry_id", "customer_id", "received_at", "channel", "market",
        "language", "topic", "sentiment", "is_health_issue", "contact_seq",
        "order_id", "verdict", "gate", "reason", "answer_id", "handle_minutes",
        "decided_at"]]
    decisions.to_csv(f"{store}/decisions.csv", index=False)

    # ---------------- 2. drafts.csv ----------------
    ans_topic = {a.answer_id: a.topic
                 for _, a in data["approved_answers"].iterrows()}
    d = dec[dec.answer_id != ""].copy()
    drafts = pd.DataFrame({
        "enquiry_id": d.enquiry_id,
        "customer_id": d.customer_id,
        "market": d.market,
        "language": d.language,
        "verdict": d.verdict,
        "gate": d.gate,
        "answer_id": d.answer_id,
        "answer_topic": d.answer_id.map(ans_topic),
        "sent_without_human": d.verdict == "AUTO_ANSWER",
        "draft_reply": d.draft_reply,
        "decided_at": stamp,
    })
    drafts.to_csv(f"{store}/drafts.csv", index=False)

    # ---------------- 3. reviews.csv (empty, schema only) ----------------
    rp = f"{store}/reviews.csv"
    if not os.path.exists(rp):
        pd.DataFrame(columns=[
            "review_id", "enquiry_id", "reviewer", "action",
            "override_verdict", "edited_reply", "reason", "reviewed_at"
        ]).to_csv(rp, index=False)

    # ---------------- the three hard rules ----------------
    auto = dec[dec.verdict == "AUTO_ANSWER"]
    unsourced = auto[(auto.answer_id == "") | (auto.draft_reply == "")]
    health_auto = auto[auto.is_health_issue]

    # rule 3: every draft must be a pre-approved translation, not a run-time one
    approved = {(a.answer_id, col): getattr(a, col)
                for _, a in data["approved_answers"].iterrows()
                for col in set(ANSWER_COL.values())}
    bad_lang = []
    for _, r in dec[dec.draft_reply != ""].iterrows():
        tmpl = approved.get((r.answer_id, ANSWER_COL.get(r.language, "answer_en")))
        if tmpl is None:
            bad_lang.append((r.enquiry_id, "no approved text for that language"))
            continue
        # rebuild the template's shape and compare - {order}/{status}/{market}
        # are the only things allowed to differ.
        pattern = re.escape(tmpl)
        for ph in ("\\{order\\}", "\\{status\\}", "\\{market\\}"):
            pattern = pattern.replace(ph, ".+?")
        if not re.fullmatch(pattern, r.draft_reply, flags=re.S):
            bad_lang.append((r.enquiry_id, "draft does not match the approved text"))

    return decisions, drafts, auto, unsourced, health_auto, bad_lang


if __name__ == "__main__":
    from main import run

    dec, data, ctx = run()
    decisions, drafts, auto, unsourced, health_auto, bad_lang = write_all(dec, data)

    print("\n" + "=" * 74)
    print("  STORE WRITTEN")
    print("=" * 74)
    print(f"   store/decisions.csv   {len(decisions):>4} rows   every enquiry, every reason")
    print(f"   store/drafts.csv      {len(drafts):>4} rows   every reply, approved source")
    print(f"   store/reviews.csv        0 rows   waiting for a human")

    print("\n" + "-" * 74)
    print("  RULE 1  ·  nothing is sent without an approved source")
    print("-" * 74)
    print(f"   {len(auto)} auto-answers, {len(auto) - len(unsourced)} carry an approved answer_id")
    if len(unsourced):
        print(f"\n   FAIL - {len(unsourced)} auto-answer(s) with no approved source:")
        for e in unsourced.enquiry_id.tolist()[:10]:
            print(f"      {e}")
        raise SystemExit("unsourced auto-answer - fix before shipping")
    print("   PASS - every automated reply came from the approved library.")

    print("\n" + "-" * 74)
    print("  RULE 2  ·  no health complaint is ever auto-answered")
    print("-" * 74)
    print(f"   {int(dec.is_health_issue.sum())} enquiries flagged as a physical reaction")
    if len(health_auto):
        print(f"\n   FAIL - {len(health_auto)} auto-answered:")
        for e in health_auto.enquiry_id.tolist()[:10]:
            print(f"      {e}")
        raise SystemExit("health complaint auto-answered - stop")
    print("   PASS - every one went to a human.")

    print("\n" + "-" * 74)
    print("  RULE 3  ·  nothing goes out in a language we did not approve")
    print("-" * 74)
    print(f"   {len(drafts)} drafts checked against approved_answers.csv")
    if bad_lang:
        print(f"\n   FAIL - {len(bad_lang)}:")
        for e, why in bad_lang[:10]:
            print(f"      {e}  {why}")
        raise SystemExit("unapproved wording - stop")
    print("   PASS - every draft is a pre-approved translation with only the")
    print("   order number, status and market filled in. Nothing was translated")
    print("   at run time.")

    print("\n" + "-" * 74)
    print("  WHAT WENT OUT, BY LANGUAGE")
    print("-" * 74)
    NM = {"en": "English", "sg": "Singlish", "ms": "Malay",
          "id": "Bahasa Indonesia", "zh": "Mandarin"}
    g = drafts.groupby("language").agg(
        drafted=("enquiry_id", "size"),
        auto_sent=("sent_without_human", "sum")).sort_values("drafted", ascending=False)
    print(f"   {'language':<20}{'drafted':>9}{'auto-sent':>11}{'human-sent':>12}")
    for l, r in g.iterrows():
        print(f"   {NM.get(l, l):<20}{int(r.drafted):>9}{int(r.auto_sent):>11}"
              f"{int(r.drafted - r.auto_sent):>12}")

    print("\n" + "-" * 74)
    print("  WHICH APPROVED ANSWER IS DOING THE WORK")
    print("-" * 74)
    g2 = drafts.groupby("answer_topic").agg(
        used=("enquiry_id", "size"),
        auto=("sent_without_human", "sum")).sort_values("used", ascending=False)
    print(f"   {'topic':<24}{'used':>6}{'auto-sent':>11}{'human-sent':>12}")
    for t, r in g2.iterrows():
        print(f"   {t:<24}{int(r.used):>6}{int(r.auto):>11}{int(r.used - r.auto):>12}")

    print("\n" + "-" * 74)
    print("  ONE AUTO-ANSWER IN A LANGUAGE NOBODY ON THE TEAM READS")
    print("-" * 74)
    non_en = drafts[drafts.sent_without_human & (drafts.language.isin(["id", "ms", "zh"]))]
    ex = non_en.iloc[0] if len(non_en) else drafts[drafts.sent_without_human].iloc[0]
    src = decisions[decisions.enquiry_id == ex.enquiry_id].iloc[0]
    raw = data["enquiries"].loc[
        data["enquiries"].enquiry_id == ex.enquiry_id, "Raw_Message"].iloc[0]
    print(f"   enquiry   {ex.enquiry_id}   {src.channel}   {ex.market}"
          f"   [{ex.language}]   contact #{src.contact_seq}")
    print(f"   they said \"{raw}\"")
    print(f"   read as   topic={src.topic}  sentiment={src.sentiment}")
    print(f"   source    {ex.answer_id} ({ex.answer_topic}), approved library, "
          f"{ex.language} translation")
    print(f"   sent      \"{ex.draft_reply}\"")
    print(f"   human     none - {src.gate}")
    print("\n   No human read that before it went out, and most of the team")
    print("   could not have read it if they tried. That is exactly why rule 3")
    print("   exists and why the translation was approved in advance.")
    print("=" * 74 + "\n")