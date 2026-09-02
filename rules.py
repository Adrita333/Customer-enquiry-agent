# -*- coding: utf-8 -*-
"""
rules.py - the decision engine. Six gates, in severity order.

    EXTRACTION supplies what the customer SAID.
    VELA'S RECORDS supply what is TRUE.
    CODE decides. Nothing else issues a verdict.

There is no retrieval layer and that absence is deliberate. One support policy
applies to every customer, so nothing conflicts by entity and there is nothing
to disambiguate. approved_answers.csv is a lookup by topic, not a corpus.
Adding RAG would be machinery with nothing to do.

What WOULD change that: market-specific policies. If Indonesia needs a different
returns window from Singapore, you are back to "which document governs this
customer" and retrieval earns its place.

GATES, in order. First one to fire wins.

  1  SAFETY        a physical reaction described  -> ESCALATE   never automated
  2  CLARITY       no topic could be established  -> CLARIFY    ask, don't guess
  3  THIRD STRIKE  3rd+ contact this month        -> ESCALATE   relationship risk
  4  COVERAGE      no approved answer for it      -> ESCALATE   nothing to send
  5  EVIDENCE      order reference missing        -> ASSIST     can't look it up
  6  AUTHORITY     answer requires a human sender -> ASSIST     policy, not skill
                   passed all six                 -> AUTO_ANSWER

WHY SAFETY IS FIRST AND UNCONDITIONAL
A rash on a newborn misread as "Product usage" gets an automated note about
storing pads in a cool dry place. Nothing else the engine does matters if that
happens once. So gate 1 runs before any lookup, cannot be overridden by a later
gate, and does not care how confident the extractor was.

WHY THE GUARDRAIL LIVES IN THE DATA
"Health complaint" has NO row in approved_answers.csv, in any language. Even if
gate 1 were deleted tomorrow, gate 4 would still catch it, because there is
physically nothing to send. A guardrail somebody has to remember to write is
weaker than a guardrail that is a missing row.

THE LANGUAGE RULE, and it is new in this version
A reply goes out in the language the customer wrote in, from a PRE-APPROVED
translation. Nothing is machine-translated at run time. A femcare and
infant-care brand does not improvise in a language its legal team has not read.
Singlish is answered in English - it is what a Singaporean advisor would do.
"""

import json
import re
from collections import defaultdict

import pandas as pd

DATA = "data"

# Topics whose approved answer quotes an order. Without a reference the agent
# has nothing to look up, so it drafts and a human finishes.
NEEDS_ORDER = ("Order status", "Delivery delay", "Refund/return", "Damaged item")

REPEAT_THRESHOLD = 3        # 3rd contact in a calendar month escalates

# Which approved translation to send. Singlish gets the English one.
ANSWER_COL = {"en": "answer_en", "sg": "answer_en", "ms": "answer_ms",
              "id": "answer_id_lang", "zh": "answer_zh"}

# --- the effort model. Every US$ number traces back to these three lines. ---
MIN_MANUAL = 16      # what one enquiry costs a human today, end to end
MIN_AUTO = 1         # spot-checking an auto-answered one
MIN_ASSIST = 6       # editing and sending a draft
MIN_ESCALATE = MIN_MANUAL


def load_data(d=DATA):
    r = {n: pd.read_csv(f"{d}/{n}.csv", keep_default_na=False)
         for n in ["enquiries", "customers", "orders", "products",
                   "approved_answers"]}
    r["approved_answers"]["requires_human_send"] = (
        r["approved_answers"].requires_human_send.astype(str).str.lower() == "true")
    return r


def build_context(data):
    """
    Everything a gate needs, resolved once.

    contact_seq is the one fact NO extractor could ever recover: how many times
    this customer has written this month. It comes from the ticket log, in
    arrival order, which is why enquiries are sorted by timestamp first.
    """
    seq, seen = {}, defaultdict(int)
    for _, e in data["enquiries"].sort_values("received_at").iterrows():
        seen[e.customer_id] += 1
        seq[e.enquiry_id] = seen[e.customer_id]

    return {
        "answers": {a.topic: a for _, a in data["approved_answers"].iterrows()},
        "cust": {c.customer_id: c for _, c in data["customers"].iterrows()},
        "orders": {o.order_id: o for _, o in data["orders"].iterrows()},
        "contact_seq": seq,
    }


def evaluate(enq, ext, ctx):
    """Run the gates in order. First to fire decides. Always returns a dict."""
    cust = ctx["cust"].get(enq.customer_id)
    seq = ctx["contact_seq"].get(enq.enquiry_id, 1)
    topic = ext.get("topic")
    lang = ext.get("language") or "en"
    order_id = ext.get("order_id") or ""

    def out(verdict, gate, reason, answer_id="", draft="", minutes=None):
        return {
            "enquiry_id": enq.enquiry_id, "customer_id": enq.customer_id,
            "received_at": enq.received_at, "channel": enq.channel,
            "market": cust.market if cust is not None else "",
            "language": lang,
            "topic": topic or "Unclassified",
            "sentiment": ext.get("sentiment", ""),
            "is_health_issue": bool(ext.get("is_health_issue")),
            "contact_seq": seq, "order_id": order_id,
            "verdict": verdict, "gate": gate, "reason": reason,
            "answer_id": answer_id, "draft_reply": draft,
            "handle_minutes": minutes,
        }

    # --- GATE 1: SAFETY. Unconditional, and it runs before any lookup. ----
    if ext.get("is_health_issue") and not ctx.get("_disable_safety"):
        return out("ESCALATE", "1-safety",
                   "customer describes a physical reaction - never auto-answered",
                   minutes=MIN_ESCALATE)

    # --- GATE 2: CLARITY. Ask, don't guess. --------------------------------
    if not topic or topic == "Unclear":
        return out("CLARIFY", "2-clarity",
                   "no topic could be established from the message",
                   minutes=MIN_ESCALATE)

    # --- GATE 3: THIRD STRIKE ----------------------------------------------
    if seq >= REPEAT_THRESHOLD:
        return out("ESCALATE", "3-third-strike",
                   f"contact #{seq} from this customer this month - "
                   "the previous answers did not work",
                   minutes=MIN_ESCALATE)

    # --- GATE 4: COVERAGE. No approved answer means nothing to send. -------
    ans = ctx["answers"].get(topic)
    if ans is None:
        return out("ESCALATE", "4-coverage",
                   f"no approved answer exists for '{topic}'",
                   minutes=MIN_ESCALATE)

    # --- GATE 5: EVIDENCE ---------------------------------------------------
    if topic in NEEDS_ORDER and not order_id:
        return out("ASSIST", "5-evidence",
                   "the reply needs an order reference and none was quoted",
                   answer_id=ans.answer_id, minutes=MIN_ASSIST)

    # Build the reply from the PRE-APPROVED translation for this language.
    order = ctx["orders"].get(order_id)
    template = getattr(ans, ANSWER_COL.get(lang, "answer_en"))
    draft = template.format(
        order=order_id or "your order",
        status=(order.status if order is not None else "in progress").lower(),
        market=cust.market if cust is not None else "your market")

    # --- GATE 6: AUTHORITY. Policy, not capability. -------------------------
    if ans.requires_human_send:
        return out("ASSIST", "6-authority",
                   "approved answer is drafted but policy requires a human to send",
                   answer_id=ans.answer_id, draft=draft, minutes=MIN_ASSIST)

    return out("AUTO_ANSWER", "0-self-serve",
               f"approved answer sent in {lang}, no human touched it",
               answer_id=ans.answer_id, draft=draft, minutes=MIN_AUTO)


if __name__ == "__main__":
    data = load_data()
    ctx = build_context(data)
    ext = {e["enquiry_id"]: e for e in json.load(open("store/extractions.json"))}

    print("=" * 74)
    print("  THRESHOLDS  (constants, not retrieved - there is no corpus here)")
    print("=" * 74)
    print(f"   third strike at contact #{REPEAT_THRESHOLD}")
    print(f"   topics needing an order reference: {', '.join(NEEDS_ORDER)}")
    print(f"   effort: {MIN_MANUAL} min by hand · {MIN_ASSIST} min assisted · "
          f"{MIN_AUTO} min spot-check")
    print(f"   approved answers on file: {len(data['approved_answers'])} topics, "
          "4 languages each")
    print("   NO approved answer for: Health complaint, Unclear")

    print("\n" + "=" * 74)
    print("  ONE ENQUIRY PER GATE, END TO END")
    print("=" * 74)
    shown = set()
    for _, e in data["enquiries"].iterrows():
        d = evaluate(e, ext.get(e.enquiry_id, {}), ctx)
        if d["gate"] in shown:
            continue
        shown.add(d["gate"])
        print(f"\n  {d['enquiry_id']}  {d['channel']}  {d['market']}  "
              f"[{d['language']}]  contact #{d['contact_seq']}")
        print(f"     said  : \"{e.Raw_Message[:64]}\"")
        print(f"     read  : topic={d['topic']}  sentiment={d['sentiment']}"
              f"  health={d['is_health_issue']}")
        print(f"     {d['verdict']:<12} gate {d['gate']}  ({d['handle_minutes']} min)")
        print(f"     because: {d['reason']}")
        if d["draft_reply"]:
            print(f"     sends : \"{d['draft_reply'][:70]}...\"")

    # ------------------------------------------------------------------
    # DEFENCE IN DEPTH. Gate 4 never fires in a normal run - gate 1 gets
    # there first. That is not a dead gate, it is the backstop. Delete
    # gate 1 and see what happens.
    # ------------------------------------------------------------------
    gt = pd.read_csv("data/ground_truth.csv")
    health = set(gt.loc[gt.true_is_health, "enquiry_id"])

    def sweep(disable):
        c = dict(ctx); c["_disable_safety"] = disable
        rows = [evaluate(e, ext.get(e.enquiry_id, {}), c)
                for _, e in data["enquiries"].iterrows()]
        h = [r for r in rows if r["enquiry_id"] in health]
        return pd.DataFrame(rows), h

    normal, hn = sweep(False)
    broken, hb = sweep(True)

    print("\n" + "=" * 74)
    print("  DEFENCE IN DEPTH  ·  what happens if gate 1 is deleted")
    print("=" * 74)
    print(f"   {len(health)} genuine health complaints in the data\n")
    for label, h in (("gate 1 ON ", hn), ("gate 1 OFF", hb)):
        auto = sum(1 for r in h if r["verdict"] == "AUTO_ANSWER")
        gates = pd.Series([r["gate"] for r in h]).value_counts().to_dict()
        print(f"   {label}   auto-answered: {auto}   caught by: {gates}")
    print("\n   Gate 4 never fires in a normal run because gate 1 gets there")
    print("   first. It is not dead code - it is the backstop. 'Health complaint'")
    print("   has no row in approved_answers.csv in ANY language, so even with")
    print("   the safety rule deleted there is physically nothing to send.")

    print("\n" + "=" * 74)
    print("  REPLIES GO OUT IN THE CUSTOMER'S LANGUAGE")
    print("=" * 74)
    auto = normal[normal.verdict == "AUTO_ANSWER"]
    print(f"   {len(auto)} auto-answers, by language:")
    for l, c in auto.language.value_counts().items():
        print(f"      {l:<6}{c:>5}")
    for l in ("ms", "id", "zh"):
        s = auto[auto.language == l]
        if len(s):
            print(f"\n   [{l}] {s.iloc[0].draft_reply[:100]}...")
    print("\n   Every one of those is a pre-approved translation from")
    print("   approved_answers.csv. Nothing is translated at run time.")
    print("=" * 74)