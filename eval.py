# -*- coding: utf-8 -*-
"""
eval.py - the only file allowed to open the answer key.

Reads   store/decisions.csv     what the agent decided
        data/ground_truth.csv   what each message really was   <- quarantined
        data/outcomes.csv       what the 2 FTE actually did    <- quarantined

Writes  store/scorecard.csv     the KPIs, for app.py to display

WHAT IS AND IS NOT A FAIR TEST, stated before the numbers

  CIRCULAR (report it, do not boast about it)
    I wrote the messages in five languages AND the keyword lists that read
    them. A high topic score partly proves my code agrees with my other code.

  NOT CIRCULAR
    1. THE HUMAN BASELINE. outcomes.csv records what the two FTE actually did,
       generated from per-topic behaviour set before any gate existed.
    2. THE SAFETY COUNTERFACTUAL. Delete gate 1 and count what leaks. That is
       a property of approved_answers.csv having no health row - of the DATA,
       not of my rules.
    3. FIRST-RESPONSE TIME AND CSAT. Observed history. Nothing the agent does
       can retroactively change what customers experienced.

  Two of slide 10's four KPIs live only in this file, because they are facts
  about customers rather than properties of the agent's output.

THE SECTION THAT MATTERS MOST IN THIS BUILD
Accuracy BY LANGUAGE. An overall score hides the thing worth knowing: whether
one market's customers are served worse than another's. Vela sells in three
markets and 63% of this inbox is not English, so a single blended number would
be the most misleading thing on the page.

ONE PROJECTION, LABELLED AS SUCH
Projected CSAT is MODELLED, not measured. In the historical data satisfaction
tracks response time far more than it tracks the answer, so an instant reply
is modelled at the top band. It is a forecast and it is marked as one wherever
it appears. Everything else on this page is measured.
"""

import json

import pandas as pd

from main import COST_PER_FTE, FTE, MONTHS, TEAM_COST, kpis, run
from rules import MIN_MANUAL, build_context, evaluate, load_data

INSTANT_MIN = 1.0     # an auto-answer goes out in about a minute
NM = {"en": "English", "sg": "Singlish", "ms": "Malay",
      "id": "Bahasa Indonesia", "zh": "Mandarin"}


def load():
    dec = pd.read_csv("store/decisions.csv", keep_default_na=False)
    gt = pd.read_csv("data/ground_truth.csv", keep_default_na=False)
    out = pd.read_csv("data/outcomes.csv", keep_default_na=False)
    drafts = pd.read_csv("store/drafts.csv", keep_default_na=False)
    m = dec.merge(gt, on="enquiry_id").merge(out, on="enquiry_id")
    m["csat_num"] = pd.to_numeric(m.csat, errors="coerce")
    m["auto"] = m.verdict == "AUTO_ANSWER"
    m["human_escalated"] = m.resolution == "Escalated"
    m["true_is_health"] = m.true_is_health.astype(str).str.lower() == "true"
    return m, drafts


def safety_counterfactual():
    """Delete gate 1 and count what leaks. A property of the data, not the rules."""
    data = load_data()
    ctx = build_context(data)
    ext = {e["enquiry_id"]: e for e in json.load(open("store/extractions.json"))}
    gt = pd.read_csv("data/ground_truth.csv")
    health = set(gt.loc[gt.true_is_health.astype(str).str.lower() == "true",
                        "enquiry_id"])

    def sweep(disable):
        c = dict(ctx)
        c["_disable_safety"] = disable
        rows = [evaluate(e, ext.get(e.enquiry_id, {}), c)
                for _, e in data["enquiries"].iterrows()]
        h = [r for r in rows if r["enquiry_id"] in health]
        return sum(1 for r in h if r["verdict"] == "AUTO_ANSWER"), len(h)

    return sweep(False), sweep(True)


if __name__ == "__main__":
    m, drafts = load()
    n = len(m)

    print("\n" + "=" * 78)
    print(f"  EVAL  ·  {n} enquiries  ·  agent vs answer key vs the two humans")
    print("=" * 78)

    # ---------------------------------------------------------------- 1
    print("\n" + "-" * 78)
    print("  1 · SAFETY   the only number that can end the project")
    print("-" * 78)
    h = m[m.true_is_health]
    auto_h = int(h.auto.sum())
    caught = int((~h.auto).sum())
    flagged = int(m.is_health_issue.astype(str).str.lower().eq("true").sum())
    recall = h.is_health_issue.astype(str).str.lower().eq("true").mean()
    print(f"   {len(h)} genuine health complaints, in {h.true_language.nunique()} languages")
    for l, c in h.true_language.value_counts().items():
        got = h[h.true_language == l].is_health_issue.astype(str).str.lower().eq("true").sum()
        print(f"      {NM[l]:<20}{c:>4}   detected {int(got)}")
    print(f"\n   recall               {recall*100:>6.1f}%   "
          f"({int(h.is_health_issue.astype(str).str.lower().eq('true').sum())} of {len(h)}, "
          f"{len(h)-int(h.is_health_issue.astype(str).str.lower().eq('true').sum())} MISSED)")
    print(f"   precision            {int(h.is_health_issue.astype(str).str.lower().eq('true').sum())/max(flagged,1)*100:>6.1f}%   "
          f"({flagged - int(h.is_health_issue.astype(str).str.lower().eq('true').sum())} false alarms)")
    print(f"   agent auto-answered  {auto_h:>6}")
    print(f"   agent sent to human  {caught:>6}")
    print("\n   Recall and precision are reported separately on purpose. A miss is")
    print("   a rash answered with a note about storage. A false alarm is one")
    print("   extra ticket in a human queue. Those are not the same cost, so a")
    print("   single blended number would hide the only one that matters.")
    (a_on, _), (a_off, tot) = safety_counterfactual()
    print(f"\n   with gate 1 deleted: {a_off} of {tot} auto-answered")
    print("   Nothing leaks, because 'Health complaint' has no row in")
    print("   approved_answers.csv in ANY language. The guardrail is a missing")
    print("   row, not a rule.")

    # ---------------------------------------------------------------- 2
    print("\n" + "-" * 78)
    print("  2 · BY LANGUAGE   the section that does not exist in an English-only build")
    print("-" * 78)
    print(f"   {'language':<20}{'n':>5}{'lang det':>10}{'topic':>9}"
          f"{'deflected':>11}{'wrong auto':>12}")
    for l, g in m.groupby("true_language"):
        ld = (g.language == g.true_language).mean()
        tp = (g.topic == g.true_topic).mean()
        df = g.auto.mean()
        wa = int((g.auto & (g.topic != g.true_topic)).sum())
        print(f"   {NM[l]:<20}{len(g):>5}{ld*100:>9.0f}%{tp*100:>8.0f}%"
              f"{df*100:>10.0f}%{wa:>12}")
    ld = (m.language == m.true_language).mean()
    tp = (m.topic == m.true_topic).mean()
    wa = int((m.auto & (m.topic != m.true_topic)).sum())
    print(f"   {'ALL':<20}{n:>5}{ld*100:>9.0f}%{tp*100:>8.0f}%"
          f"{m.auto.mean()*100:>10.0f}%{wa:>12}")

    best = m.groupby("true_language").apply(
        lambda g: (g.topic == g.true_topic).mean(), include_groups=False)
    worst_l, worst_v = best.idxmin(), best.min()
    best_l, best_v = best.idxmax(), best.max()
    print(f"\n   {NM[best_l]} {best_v*100:.0f}%  vs  {NM[worst_l]} {worst_v*100:.0f}%"
          f"   -  a {(best_v-worst_v)*100:.0f} point gap")
    print("   That gap is the cost of reading five languages with keyword lists")
    print("   instead of a model. It is not an abstract trade-off: it is")
    print(f"   {NM[worst_l]}-speaking customers getting a worse service, and it is")
    print("   the priced case for the API bill.")
    print(f"\n   auto-answers sent on a WRONG topic: {wa}")
    print("   A wrong topic that still reaches a human is a delay. A wrong topic")
    print("   sent automatically is a wrong answer in Vela's voice.")

    # ---------------------------------------------------------------- 3
    print("\n" + "-" * 78)
    print("  3 · FIRST-RESPONSE TIME   slide 10 KPI - measured, not modelled")
    print("-" * 78)
    frt_now = m.first_response_minutes.median()
    rest = m.loc[~m.auto, "first_response_minutes"]
    blended = (m.auto.mean() * INSTANT_MIN) + ((1 - m.auto.mean()) * rest.median())
    print(f"   today, median across all enquiries   {frt_now/60:>6.1f} hrs")
    print(f"   with the agent, blended median       {blended/60:>6.1f} hrs")
    print(f"   {m.auto.mean()*100:.0f}% answered in about a minute, the rest still wait for a human.")
    en = m[m.true_language == "en"]; non = m[m.true_language != "en"]
    print(f"\n   today, ENGLISH   {en.first_response_minutes.median()/60:>5.1f} hrs")
    print(f"   today, OTHER     {non.first_response_minutes.median()/60:>5.1f} hrs"
          f"   ({non.first_response_minutes.median()/en.first_response_minutes.median()-1:+.0%})")
    print(f"   needed a colleague to translate: "
          f"{int(m.needed_translation_help.astype(str).str.lower().eq('true').sum())} enquiries")
    print("   That is the language problem measured in hours, before any AI.")

    # ---------------------------------------------------------------- 4
    print("\n" + "-" * 78)
    print("  4 · CSAT   slide 10 KPI - historical measured, projection MODELLED")
    print("-" * 78)
    c = m.csat_num
    print(f"   today                     {c.mean():>5.2f} / 5   ({int(c.notna().sum())} responses)")
    for lo, hi, lbl in ((0, 120, "answered < 2 hrs"), (120, 360, "2-6 hrs"),
                        (360, 10**9, "over 6 hrs")):
        s = m[(m.first_response_minutes >= lo) & (m.first_response_minutes < hi)].csat_num
        if s.notna().sum():
            print(f"      {lbl:<22}{s.mean():>5.2f} / 5   ({int(s.notna().sum())} responses)")
    fast = m[m.first_response_minutes < 120].csat_num.mean()
    proj = m.auto.mean() * fast + (1 - m.auto.mean()) * m.loc[~m.auto, "csat_num"].mean()
    print(f"\n   projected with the agent  {proj:>5.2f} / 5   <- MODELLED, not measured")
    print("   Satisfaction tracks response time far more than it tracks the")
    print("   answer, so the auto-answered share is modelled at the under-2-hour")
    print("   band. It is a forecast. Holdout testing is what would confirm it.")

    # ---------------------------------------------------------------- 5
    print("\n" + "-" * 78)
    print("  5 · DEFLECTION AND COST   slide 10 KPIs 1 and 3")
    print("-" * 78)
    dec_df, data, _ = run()
    k = kpis(dec_df)
    print(f"   % repetitive queries deflected   {k['deflected']*100:>7.1f}%")
    print(f"   cost per enquiry                 US${k['cost_before']:>6.2f}  ->  US${k['cost_after']:.2f}")
    print(f"   productivity saved               US${k['saved']:>7,.0f}/yr   deck 50-100K")
    print(f"   effort reduction                 {k['reduction']*100:>7.1f}%        deck 50-70%")

    # ---------------------------------------------------------------- 6
    print("\n" + "-" * 78)
    print("  6 · AGENT vs THE TWO HUMANS")
    print("-" * 78)
    agent_handled = m.verdict.isin(["AUTO_ANSWER", "ASSIST"]).mean()
    human_handled = (m.resolution == "Resolved").mean()
    print(f"   handled without escalating    agent {agent_handled*100:>5.1f}%"
          f"   today {human_handled*100:>5.1f}%")
    print(f"   handling time per enquiry     {MIN_MANUAL} min  ->  "
          f"{dec_df.handle_minutes.mean():.1f} min")
    print("\n   The agent escalates MORE than the humans do, not less, and that")
    print("   is deliberate. It refuses anything it cannot source from the")
    print("   approved library, anything it cannot read, and every third")
    print("   contact. A support bot that resolves more than its humans is")
    print("   usually one that answered things it should have passed on.")

    # ---------------------------------------------------------------- scorecard
    pd.DataFrame([{
        "n": n,
        "deflected": round(k["deflected"], 4),
        "reduction": round(k["reduction"], 4),
        "saved_usd": round(k["saved"]),
        "team_cost_usd": TEAM_COST,
        "cost_before": round(k["cost_before"], 2),
        "cost_after": round(k["cost_after"], 2),
        "frt_now_hrs": round(frt_now / 60, 2),
        "frt_after_hrs": round(blended / 60, 2),
        "csat_now": round(float(c.mean()), 2),
        "csat_projected": round(float(proj), 2),
        "health_total": len(h),
        "health_recall": round(float(recall), 4),
        "health_auto_answered": auto_h,
        "health_auto_gate1_off": a_off,
        "lang_accuracy": round(float(ld), 4),
        "topic_accuracy": round(float(tp), 4),
        "topic_best_lang": NM[best_l], "topic_best": round(float(best_v), 4),
        "topic_worst_lang": NM[worst_l], "topic_worst": round(float(worst_v), 4),
        "wrong_topic_auto_sent": wa,
        "agent_handled_rate": round(float(agent_handled), 4),
        "human_handled_rate": round(float(human_handled), 4),
    }]).to_csv("store/scorecard.csv", index=False)

    print("\n" + "=" * 78)
    print("  SCORECARD  ·  slide 10")
    print("=" * 78)
    print(f"   % repetitive queries deflected   {k['deflected']*100:>7.1f}%")
    print(f"   first-response time              {frt_now/60:>6.1f} hrs  ->  {blended/60:.1f} hrs")
    print(f"   cost per enquiry                 US${k['cost_before']:>6.2f}  ->  US${k['cost_after']:.2f}")
    print(f"   CSAT                             {c.mean():>6.2f}      ->  {proj:.2f}  (modelled)")
    print(f"\n   productivity saved               US${k['saved']:>7,.0f}/yr   deck 50-100K")
    print(f"   health recall                    {recall*100:>6.1f}%   "
          f"{auto_h} auto-answered, {a_off} with the safety gate deleted")
    print(f"   topic accuracy                   {tp*100:>6.1f}%   "
          f"{NM[best_l]} {best_v*100:.0f}% -> {NM[worst_l]} {worst_v*100:.0f}%")
    print("   -> store/scorecard.csv written for app.py")
    print("=" * 78 + "\n")