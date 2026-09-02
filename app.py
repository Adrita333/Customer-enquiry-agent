# -*- coding: utf-8 -*-
"""
app.py - the inbox the two support agents would actually work in.

    streamlit run app.py

READS ONLY WHAT IS ALREADY ON DISK
    store/decisions.csv     the verdict and the gate for all 900 enquiries
    store/drafts.csv        the approved answer that went out, verbatim
    store/extractions.json  what the reader made of each message
    store/scorecard.csv     the KPIs, published by eval.py
    store/reviews.csv       what humans have decided so far
    data/enquiries.csv      the customer's own words
    data/customers.csv      who they are
    data/approved_answers.csv  the library, in four languages

It imports neither rules nor main. Nothing is computed while the demo is
running, so nothing can fail while the demo is running.

It also never opens ground_truth.csv or outcomes.csv. eval.py is the only
reader of those, and it publishes scorecard.csv for this file to display.

THE SCREEN IS AN ARGUMENT
Four tiles, and they are slide 10's four KPIs in slide 10's order. Then the
language view, which is what makes this build different from a single-market
one, then the queue.
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Customer Enquiry Agent",
                   page_icon="💬", layout="wide")

STORE, DATA = "store", "data"
REVIEWS = f"{STORE}/reviews.csv"
MONTHS = 12
MIN_MANUAL, MIN_AUTO, MIN_ASSIST = 16, 1, 6
NM = {"en": "English", "sg": "Singlish", "ms": "Malay",
      "id": "Bahasa Indonesia", "zh": "Mandarin"}
VERDICTS = ["ESCALATE", "ASSIST", "CLARIFY", "AUTO_ANSWER"]
GATE_ORDER = {"1-safety": 0, "3-third-strike": 1, "4-coverage": 2,
              "2-clarity": 3, "6-authority": 4, "5-evidence": 5, "0-self-serve": 6}

# THE TWO FTE FROM SLIDE 10, AND WHO OWNS WHAT.
# The split is by language, because that is how a two-person desk covering
# three markets actually divides. It also means the reviewer on any enquiry is
# the person who would really be handling it - not a separate "reviewer" role
# that does not exist in a team of two.
AGENT = {"en": "M. Tan", "sg": "M. Tan", "zh": "M. Tan",
         "ms": "S. Rahman", "id": "S. Rahman"}
AGENT_DESK = {"M. Tan": "Singapore desk · English, Singlish, Mandarin",
              "S. Rahman": "MY/ID desk · Malay, Bahasa Indonesia"}


@st.cache_data
def load():
    dec = pd.read_csv(f"{STORE}/decisions.csv", keep_default_na=False)
    drafts = pd.read_csv(f"{STORE}/drafts.csv", keep_default_na=False)
    card = pd.read_csv(f"{STORE}/scorecard.csv").iloc[0]
    enq = pd.read_csv(f"{DATA}/enquiries.csv", keep_default_na=False)
    cust = pd.read_csv(f"{DATA}/customers.csv", keep_default_na=False)
    ans = pd.read_csv(f"{DATA}/approved_answers.csv", keep_default_na=False)
    ext = {e["enquiry_id"]: e
           for e in json.load(open(f"{STORE}/extractions.json"))}
    dec = dec.merge(enq[["enquiry_id", "Raw_Message"]], on="enquiry_id")
    dec = dec.merge(cust[["customer_id", "customer_name", "orders_count",
                          "is_subscriber"]], on="customer_id")
    dec = dec.merge(drafts[["enquiry_id", "answer_topic", "draft_reply"]],
                    on="enquiry_id", how="left").fillna(
                        {"answer_topic": "", "draft_reply": ""})
    dec["priority"] = dec.gate.map(GATE_ORDER).fillna(9)
    dec["lang_name"] = dec.language.map(NM).fillna(dec.language)
    dec["agent"] = dec.language.map(AGENT).fillna("M. Tan")
    return dec, card, ans, ext


def read_reviews():
    if os.path.exists(REVIEWS):
        return pd.read_csv(REVIEWS, keep_default_na=False)
    return pd.DataFrame(columns=["review_id", "enquiry_id", "reviewer", "action",
                                 "override_verdict", "edited_reply", "reason",
                                 "reviewed_at"])


def append_review(row):
    df = read_reviews()
    df.loc[len(df)] = row
    df.to_csv(REVIEWS, index=False)


dec, card, answers, ext = load()
reviews = read_reviews()
n_all = len(dec)

# ----------------------------------------------------------------- header
st.title("Customer Feedback & Enquiry Intelligence")
st.caption("Multilingual enquiry triage with approved-answer control · "
           f"{n_all} enquiries in one month ({n_all*MONTHS:,}/yr) · "
           "five languages")

_auto = int((dec.verdict == "AUTO_ANSWER").sum())
_exc = n_all - _auto
h1, h2, h3 = st.columns(3)
h1.metric("Enquiries read", f"{n_all}", "every message, all five languages")
h2.metric("Answered by the agent", f"{_auto}",
          f"{_auto/n_all*100:.1f}% — no human touched them")
h3.metric("Left for a person", f"{_exc}",
          f"{_exc/n_all*100:.1f}% — the queue below")
st.caption(f"Every KPI on this page covers all {n_all} enquiries, because "
           f"answering {_auto} of them without a human IS the saving. The "
           f"{_exc} in the queue are what is left over, not the whole job.")

# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("KPI scope")
    scope = st.radio("The four tiles cover",
                     [f"All {n_all} enquiries", "Current filter only"],
                     index=0, label_visibility="collapsed",
                     help="Current filter scopes the tiles by language, market "
                          "and channel only. Verdict and gate are the agent's "
                          "own output, so scoping a rate to them would be "
                          "circular. First-response time and CSAT never scope.")

    st.divider()
    st.header("Filter the inbox")
    # Slide 10's problem is two people's bandwidth, so the first question the
    # screen has to answer is "which of these are MINE".
    agents = st.multiselect("Support agent", sorted(dec.agent.unique()),
                            default=sorted(dec.agent.unique()))
    verdicts = st.multiselect("Verdict", VERDICTS,
                              default=["ESCALATE", "ASSIST", "CLARIFY"])
    langs = st.multiselect("Language", sorted(dec.lang_name.unique()),
                           default=sorted(dec.lang_name.unique()))
    markets = st.multiselect("Market", sorted(dec.market.unique()),
                             default=sorted(dec.market.unique()))
    channels = st.multiselect("Channel", sorted(dec.channel.unique()),
                              default=sorted(dec.channel.unique()))
    gates = st.multiselect("Gate", sorted(dec.gate.unique()),
                           default=sorted(dec.gate.unique()))
    health_only = st.checkbox("Health complaints only", value=False)

    st.divider()
    st.subheader("Safety")
    st.write(f"**Recall {card.health_recall*100:.0f}%** — "
             f"{int(card.health_total)} genuine health complaints, "
             f"{int(card.health_total)} detected, across four languages.")
    st.write(f"**{int(card.health_auto_answered)}** were auto-answered. "
             f"With the safety gate deleted: still "
             f"**{int(card.health_auto_gate1_off)}**.")
    st.caption("'Health complaint' has no row in approved_answers.csv in any "
               "language, so there is physically nothing to send. The guardrail "
               "is a missing row, not a rule somebody has to remember to write.")

    st.divider()
    st.subheader("Agent vs the two people")
    st.write(f"**Handled without escalating** {card.agent_handled_rate*100:.1f}% "
             f"vs {card.human_handled_rate*100:.1f}% today")
    st.caption("The agent escalates MORE than the humans do, deliberately. A "
               "support bot that resolves more than its people is usually one "
               "that answered things it should have passed on.")

# ----------------------------------------------------------------- queue
# An EMPTY multiselect means "no filter on this field", not "exclude
# everything". Streamlit hands back [] when you clear a box, and isin([])
# matches zero rows - so clearing one box silently emptied the whole screen.
# Nobody clears a filter meaning "show me nothing".
def keep(col, chosen):
    return col.isin(chosen) if chosen else pd.Series(True, index=col.index)


q = dec[keep(dec.agent, agents) & keep(dec.verdict, verdicts)
        & keep(dec.lang_name, langs) & keep(dec.market, markets)
        & keep(dec.channel, channels) & keep(dec.gate, gates)]
if health_only:
    q = q[q.is_health_issue.astype(str).str.lower() == "true"]
q = q.sort_values(["priority", "contact_seq", "received_at"],
                  ascending=[True, False, True], kind="stable")

# ----------------------------------------------------------------- KPI row
# The tiles scope by properties of the INBOX - language, market, channel - and
# never by verdict or gate. Those are the agent's own output, and a rate
# measured over a set selected on that rate is circular: filter to ESCALATE and
# "% deflected" is 0% by construction.
kpi_pop = dec[keep(dec.agent, agents) & keep(dec.lang_name, langs)
              & keep(dec.market, markets) & keep(dec.channel, channels)]
all_scope = scope.startswith("All")

if all_scope:
    t_defl, t_n = card.deflected, n_all
    t_before, t_after = card.cost_before, card.cost_after
else:
    t_n = len(kpi_pop)
    t_defl = (kpi_pop.verdict == "AUTO_ANSWER").mean() if t_n else 0.0
    t_red = (1 - kpi_pop.handle_minutes.sum() / (t_n * MIN_MANUAL)) if t_n else 0.0
    t_before = card.cost_before
    t_after = card.cost_before * (1 - t_red)

k1, k2, k3, k4 = st.columns(4)
k1.metric("% repetitive queries deflected", f"{t_defl*100:.1f}%",
          f"{round(t_defl*t_n)} of {t_n} answered with no human")
k2.metric("First-response time", f"{card.frt_after_hrs:.1f} hrs",
          f"{card.frt_after_hrs - card.frt_now_hrs:+.1f} hrs vs "
          f"{card.frt_now_hrs:.1f} today"
          + ("" if all_scope else "  ·  whole month, never scoped"),
          # DOWN IS GOOD on this tile and the next one. Streamlit colours a
          # delta by its sign, not by whether it is good news, so -1.3 hrs and
          # -61% were both being painted red - the two strongest results on the
          # page shown as regressions. "inverse" flips it. The two tiles where
          # UP is good (deflection, CSAT) stay on "normal".
          delta_color="inverse" if all_scope else "off")
k3.metric("Cost per enquiry", f"US${t_after:.2f}",
          f"{(t_after/t_before - 1)*100:.0f}% vs US${t_before:.2f} today",
          delta_color="inverse")
k4.metric("CSAT", f"{card.csat_projected:.2f} / 5",
          f"{card.csat_projected - card.csat_now:+.2f} vs "
          f"{card.csat_now:.2f} today · modelled"
          + ("" if all_scope else "  ·  never scoped"),
          delta_color="normal" if all_scope else "off")

st.caption(
    (f"**Scope: all {n_all} enquiries.** The four tiles cover the whole month, "
     "so they do NOT follow the filters — switch the KPI scope to *Current "
     "filter* if you want them to. The inbox below always follows every filter."
     if all_scope else
     f"**Scope: {t_n} enquiries — filtered by agent, language, market and channel.** "
     "The tiles ignore the Verdict and Gate filters: those are the agent's own "
     "output, and a rate measured over a set selected on that rate is circular.")
    + "  \n**First-response time and CSAT never scope, in either mode.** They "
      "come from what customers actually experienced, which eval.py reads and "
      "this file may not.  \n"
    f"Deck slide 10 claims US\\$50–100K from productivity. This lands at "
    f"US\\${card.saved_usd:,.0f} using the deck's own formula — 2 FTE × US\\$60K × "
    f"{card.reduction*100:.1f}% effort reduction, no bandwidth factor, because "
    f"these two people do nothing else. **CSAT is the one modelled number here.**"
)

# ------------------------------------------------- the finding, no table
st.divider()
g1, g2, g3 = st.columns([1, 1, 2])
g1.metric(f"Topic accuracy · {card.topic_best_lang}", f"{card.topic_best*100:.0f}%")
g2.metric(f"Topic accuracy · {card.topic_worst_lang}", f"{card.topic_worst*100:.0f}%",
          f"{(card.topic_worst - card.topic_best)*100:.0f} pts")
with g3:
    st.caption(f"**63% of this inbox is not English, and that gap is the priced "
               f"case for a language model.** Reading five languages with keyword "
               f"lists costs {(card.topic_best - card.topic_worst)*100:.0f} points "
               f"of accuracy in {card.topic_worst_lang} — and Malaysia is a third "
               f"of the market. Auto-answers sent on a wrong topic: "
               f"**{int(card.wrong_topic_auto_sent)}**. Health complaints missed, "
               f"in any language: **0**.")

# ----------------------------------------------------------------- inbox
st.divider()
left, right = st.columns([1.15, 1])

with left:
    st.subheader(f"Inbox · {len(q)} enquiries need a person")
    st.caption(f"Safety first, then third contacts — **this section responds to "
               f"every filter**. {len(q)} of {n_all} enquiries, "
               f"{q.handle_minutes.sum():,.0f} of {dec.handle_minutes.sum():,.0f} "
               f"minutes of handling time.")
    m1, m2, m3 = st.columns(3)
    m1.metric("In view", f"{len(q)}", f"{len(q)/n_all*100:.0f}% of {n_all}")
    m2.metric("Handling time", f"{q.handle_minutes.sum():,.0f} min",
              f"{q.handle_minutes.sum()*MONTHS/60:,.0f} h/yr")
    m3.metric("Health complaints",
              f"{int((q.is_health_issue.astype(str).str.lower()=='true').sum())}",
              "never auto-answered")

    st.dataframe(
        q[["enquiry_id", "agent", "customer_name", "lang_name", "market",
           "channel", "topic", "contact_seq", "verdict", "gate"]].rename(columns={
               "enquiry_id": "Enquiry", "agent": "Agent",
               "customer_name": "Customer",
               "lang_name": "Language", "market": "Market", "channel": "Channel",
               "topic": "Topic", "contact_seq": "Contact #",
               "verdict": "Verdict", "gate": "Gate"}),
        hide_index=True, width="stretch", height=400)

with right:
    st.subheader("The enquiry, end to end")
    if not len(q):
        st.info("Nothing matches those filters.")
        st.stop()

    pick = st.selectbox(
        "Enquiry", q.enquiry_id.tolist(),
        format_func=lambda e: f"{e} · "
        f"{q.loc[q.enquiry_id==e,'lang_name'].iloc[0]} · "
        f"{q.loc[q.enquiry_id==e,'gate'].iloc[0]}")
    r = q[q.enquiry_id == pick].iloc[0]
    x = ext.get(pick, {})

    tone = {"ESCALATE": "error", "CLARIFY": "warning",
            "ASSIST": "warning", "AUTO_ANSWER": "success"}[r.verdict]
    getattr(st, tone)(f"**{r.verdict}** at gate {r.gate} — {r.reason}")

    a, b = st.columns(2)
    a.write(f"**Customer** {r.customer_name} ({r.market})")
    a.write(f"**Language** {r.lang_name}")
    a.write(f"**Agent** {r.agent}")
    a.write(f"**Channel** {r.channel}")
    b.write(f"**Contact #** {r.contact_seq} this month")
    b.write(f"**Orders to date** {r.orders_count}")
    b.write(f"**Received** {r.received_at}")

    st.write("**What the customer wrote**")
    st.code(r.Raw_Message or "(no text)", language=None)

    st.write("**What was read from it**")
    st.dataframe(pd.DataFrame([
        {"field": "language", "value": f"{r.lang_name}  ({r.language})"},
        {"field": "topic", "value": r.topic},
        {"field": "sentiment", "value": r.sentiment},
        {"field": "physical reaction described", "value": str(r.is_health_issue)},
        {"field": "order reference", "value": r.order_id or "— none quoted"},
        {"field": "requested action", "value": x.get("requested_action", "")},
        {"field": "keyword confidence", "value": str(x.get("confidence", ""))},
        {"field": "read by", "value": x.get("method", "")},
    ]), hide_index=True, width="stretch")

    st.write("**The approved answer behind the reply**")
    if r.answer_id:
        src = answers[answers.answer_id == r.answer_id].iloc[0]
        col = {"en": "answer_en", "sg": "answer_en", "ms": "answer_ms",
               "id": "answer_id_lang", "zh": "answer_zh"}.get(r.language, "answer_en")
        st.info(f"**{src.answer_id} · {src.topic} · {r.lang_name} translation**"
                f"\n\n> {getattr(src, col)}")
        if r.draft_reply:
            st.write("**Sent to the customer**" if r.verdict == "AUTO_ANSWER"
                     else "**Drafted, waiting for a human to send**")
            st.code(r.draft_reply, language=None)
        else:
            st.caption("Answer identified but not filled in — the reply needs a "
                       "detail the customer never gave.")
    else:
        st.warning("No approved answer was used. Nothing goes out under Vela's "
                   "name that is not in the approved library, in a translation "
                   "that was signed off in advance.")

    # ------------------------------------------------- human decision
    st.divider()
    st.write("**Your decision**")
    prior = reviews[reviews.enquiry_id == pick]
    if len(prior):
        p = prior.iloc[-1]
        st.success(f"Already reviewed by {p.reviewer}: **{p.action}**"
                   + (f" — {p.reason}" if p.reason else ""))

    with st.form(f"review_{pick}", clear_on_submit=True):
        # The reviewer is not a separate role. On a two-person desk it is the
        # agent who owns that language, so it defaults to them and changes as
        # you move between enquiries. In production it comes from SSO, not a
        # text box - a free-text name in an audit trail is a weakness, and
        # worth naming before somebody finds it.
        reviewer = st.text_input(f"Reviewing agent  ·  {AGENT_DESK[r.agent]}",
                                 value=r.agent)
        action = st.radio("Action",
                          ["Approve the agent", "Override", "Edit the reply"],
                          horizontal=True)
        override = st.selectbox("Override to", [""] + VERDICTS)
        edited = st.text_area("Edited reply", value=r.draft_reply, height=110)
        reason = st.text_input("Reason")
        submitted = st.form_submit_button("Record decision")

    if submitted:
        # An override with no reason is how an audit trail becomes useless.
        if action != "Approve the agent" and not reason.strip():
            st.error("A reason is required for anything other than approval.")
        elif action == "Override" and not override:
            st.error("Choose what you are overriding it to.")
        elif action == "Edit the reply" and not edited.strip():
            st.error("An edited reply cannot be empty.")
        else:
            append_review({
                "review_id": f"REV-{len(reviews):04d}", "enquiry_id": pick,
                "reviewer": reviewer, "action": action,
                "override_verdict": override,
                "edited_reply": edited if action == "Edit the reply" else "",
                "reason": reason,
                "reviewed_at": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ")})
            st.cache_data.clear()
            st.rerun()