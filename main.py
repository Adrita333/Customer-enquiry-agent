# -*- coding: utf-8 -*-
"""
main.py - the driver. Runs all 900 enquiries and reports against deck slide 10.

Reads nothing new. It wires extraction to rules, loops, and totals.

THE TWO KPIs THIS FILE CAN PRODUCE
Slide 10 lists four:
    % repetitive queries deflected   <- computed here
    cost per enquiry                 <- computed here
    first-response time              <- HISTORY. eval.py, from outcomes.csv
    CSAT / NPS                       <- HISTORY. eval.py, from outcomes.csv
The last two are properties of what customers experienced, not of what the
agent decided. Only outcomes.csv knows them, and outcomes.csv is quarantined
to eval.py. A KPI you cannot compute from your own output is not yours to print.

THE EFFORT MODEL, stated openly because every dollar depends on it
    2 FTE x US$60,000                 = US$120,000/yr   deck says 100-140K
    900 enquiries/month               = 10,800/yr
    16 min by hand, 6 min assisted, 1 min to spot-check an auto-answer
    reduction    = 1 - (actual minutes / (10,800 x 16 min))
    effort saved = US$120,000 x reduction
NOTE there is no "bandwidth" factor here. Invoice checking needed one because
KAMs only spend 70% of their time on claims. Slide 10 applies the automation
rate to the whole FTE cost, because these two people do nothing else.
"""

import json
import os

import pandas as pd

from rules import (MIN_ASSIST, MIN_AUTO, MIN_MANUAL, build_context, evaluate,
                   load_data)

EXTRACTIONS = "store/extractions.json"

# --- the cost model. Every US$ number traces back to these three lines. ---
FTE = 2
COST_PER_FTE = 60_000
TEAM_COST = FTE * COST_PER_FTE
MONTHS = 12


def run():
    """Score every enquiry. Returns a DataFrame, one row per enquiry."""
    data = load_data()
    ctx = build_context(data)
    ext = {e["enquiry_id"]: e for e in json.load(open(EXTRACTIONS))}
    rows = [evaluate(e, ext.get(e.enquiry_id, {}), ctx)
            for _, e in data["enquiries"].iterrows()]
    return pd.DataFrame(rows), data, ctx


def kpis(dec):
    n = len(dec)
    annual = n * MONTHS
    deflected = (dec.verdict == "AUTO_ANSWER").mean()
    minutes_now = n * MIN_MANUAL
    minutes_after = dec.handle_minutes.sum()
    reduction = 1 - minutes_after / minutes_now
    return {
        "n": n, "annual": annual,
        "deflected": deflected,
        "reduction": reduction,
        "saved": TEAM_COST * reduction,
        "cost_before": TEAM_COST / annual,
        "cost_after": TEAM_COST * (1 - reduction) / annual,
        "hours_now": minutes_now * MONTHS / 60,
        "hours_after": minutes_after * MONTHS / 60,
    }


def band(v, lo, hi, unit=""):
    return "inside" if lo <= v <= hi else f"OUTSIDE {lo}-{hi}{unit}"


if __name__ == "__main__":
    dec, data, ctx = run()
    k = kpis(dec)
    n = k["n"]

    print("\n" + "=" * 74)
    print(f"  VELA  ·  CUSTOMER ENQUIRY AGENT  ·  {n} enquiries scored")
    print(f"  one month at the post-diaper-launch run rate = {k['annual']:,}/yr")
    print("=" * 74)

    print("\nVERDICTS")
    for v in ("AUTO_ANSWER", "ASSIST", "CLARIFY", "ESCALATE"):
        c = int((dec.verdict == v).sum())
        print(f"   {v:<13}{c:>5}   {c/n*100:>5.1f}%")

    print("\nWHICH GATE DECIDED")
    for g, c in dec.gate.value_counts().sort_index().items():
        mins = int(dec.loc[dec.gate == g, "handle_minutes"].sum())
        print(f"   {g:<18}{c:>5}   {mins:>6,} min/month")

    print("\n" + "-" * 74)
    print("  KPIs  ·  slide 10 of the deck")
    print("-" * 74)
    print(f"   % repetitive queries deflected   {k['deflected']*100:>7.1f}%")
    print(f"   cost per enquiry                 US${k['cost_before']:>6.2f}"
          f"  ->  US${k['cost_after']:.2f}")
    print(f"   first-response time                   see eval.py"
          f"   - needs outcomes.csv (quarantined)")
    print(f"   CSAT                                  see eval.py"
          f"   - needs outcomes.csv (quarantined)")
    print(f"\n   productivity saved               US${k['saved']:>7,.0f}/yr"
          f"   deck 50-100K   {band(k['saved']/1000, 50, 100, 'K')}")
    print(f"      via effort reduction          {k['reduction']*100:>7.1f}%"
          f"        deck 50-70%    {band(k['reduction']*100, 50, 70, '%')}")
    print(f"      {k['hours_now']:,.0f} h/yr by hand  ->  {k['hours_after']:,.0f} h/yr with the agent")

    print("\n" + "-" * 74)
    print("  RECONCILIATION  ·  every dollar traced")
    print("-" * 74)
    print(f"   {FTE} FTE x US${COST_PER_FTE:,}        = US${TEAM_COST:>8,}/yr   deck 100-140K")
    print(f"   x {k['reduction']*100:.1f}% effort reduction = US${k['saved']:>8,.0f}/yr   deck  50-100K")
    print("   no bandwidth factor - slide 10 applies the rate to the whole")
    print("   FTE cost, because these two people do nothing but handle enquiries.")

    # ------------------------------------------------------------------
    # THE LANGUAGE VIEW. This build's headline, and it does not exist in a
    # single-language version of this agent.
    # ------------------------------------------------------------------
    print("\n" + "-" * 74)
    print("  BY LANGUAGE  ·  63% of this inbox is not English")
    print("-" * 74)
    NM = {"en": "English", "sg": "Singlish", "ms": "Malay",
          "id": "Bahasa Indonesia", "zh": "Mandarin"}
    print(f"   {'language':<20}{'n':>6}{'deflected':>12}{'escalated':>12}")
    for l, g in dec.groupby("language"):
        d = (g.verdict == "AUTO_ANSWER").mean()
        e = (g.verdict == "ESCALATE").mean()
        print(f"   {NM.get(l, l):<20}{len(g):>6}{d*100:>11.0f}%{e*100:>11.0f}%")
    print(f"   {'ALL':<20}{n:>6}{k['deflected']*100:>11.0f}%"
          f"{(dec.verdict=='ESCALATE').mean()*100:>11.0f}%")
    print("\n   A gap between the top and bottom rows is not a curiosity. It is")
    print("   one market's customers getting a worse service than another's,")
    print("   and eval.py prices it against the answer key.")

    print("\n" + "-" * 74)
    print("  WHY HALF OF THEM STILL NEED A HUMAN  ·  the coverage gap")
    print("-" * 74)
    held = dec[dec.verdict != "AUTO_ANSWER"]
    reasons = {
        "5-evidence": ("the customer never quoted an order number",
                       "ask for it in the contact form - one field"),
        "6-authority": ("policy says a human must send refunds, damages, ingredients",
                        "a policy decision, not a capability gap"),
        "3-third-strike": ("third contact this month - earlier answers failed",
                           "fix the answer that did not work the first time"),
        "2-clarity": ("the message had no recoverable topic",
                      "a topic picker in the form, or a reader that handles it"),
        "1-safety": ("a physical reaction was described",
                     "must stay human. This one is not a gap, it is the design"),
        "4-coverage": ("no approved answer exists for the topic",
                       "write one - or decide it should never be automated"),
    }
    for g, c in held.gate.value_counts().items():
        why, fix = reasons.get(g, ("?", "?"))
        mins = int(held.loc[held.gate == g, "handle_minutes"].sum()) * MONTHS / 60
        print(f"\n   {g}   {c} enquiries   {mins:,.0f} h/yr")
        print(f"      because : {why}")
        print(f"      fix     : {fix}")

    # Biggest by HOURS and cheapest to FIX are two different rows. Saying
    # "biggest lever" without which measure is how a slide gets challenged.
    by_hours = held.groupby("gate").handle_minutes.sum().sort_values(ascending=False)
    top, top_h = by_hours.index[0], by_hours.iloc[0] * MONTHS / 60
    ev = int((held.gate == "5-evidence").sum())
    ev_h = held.loc[held.gate == "5-evidence", "handle_minutes"].sum() * MONTHS / 60
    print(f"\n   BIGGEST BY HOURS   {top}   {top_h:,.0f} h/yr")
    print(f"\n   CHEAPEST TO FIX    5-evidence   {ev} enquiries   {ev_h:,.0f} h/yr")
    print("      Stuck only because the customer never typed an order number.")
    print("      That is one field on a contact form, not a better reader.")
    print("\n   Neither of the two biggest levers is AI. That is the finding.")
    print("=" * 74 + "\n")