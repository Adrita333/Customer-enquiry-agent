# -*- coding: utf-8 -*-
"""
extract.py - the ONLY file that reads a customer's words.

    python extract.py

No model. No API key. No network. Runs in under a second and gives the same
answer every time.

WHY NOT A LANGUAGE MODEL
I built the Gemini version first. It worked, and then the free tier stopped it:
20 requests per day, per model. Reading 900 messages needs 15 calls at 60 per
batch, so one full re-run costs three quarters of a day's allowance and any
iteration at all is impossible. A demo that depends on somebody else's rate
limit is not a demo.

So this reads the same 900 messages with keyword lists - one set per language.
That is a real engineering answer, not a retreat: it is free, it is instant, it
is identical on every run, and it can be audited line by line. What it costs is
maintenance, and eval.py measures exactly how much.

FIVE LANGUAGES, FIVE KEYWORD SETS
63% of Blood's inbox is not English:

    en  "My order is already 6 days late"
    sg  "my order still never come leh, so long already"
    ms  "Pesanan dah lewat seminggu. Bila nak sampai ni?"
    id  "Kok belum ada update ya? Udah seminggu lebih nih."
    zh  "说好周一到，到现在都没有消息。"

One English keyword list reads the first two and none of the rest. So there are
five, and language is detected first because it decides which list to use.

THE HONEST TRADE, WHICH eval.py PRICES
A keyword list per language is five lists to maintain, and every new phrasing a
customer invents is a code change, a review and a deploy. A model absorbs new
phrasing for free. The question is not which is better in the abstract - it is
whether the accuracy gap is worth the API bill and the rate limit, and that is
a number, not an opinion.

WHAT CROSSES THE BOUNDARY - eight fields, nothing else
    language · topic · is_health_issue · sentiment
    order_id · requested_action · urgency · confidence

TWO DISCIPLINES
  REPORT, NEVER DECIDE.  is_health_issue is an observation. "Escalate" is a
                         decision, and decisions belong to rules.py.
  NEVER GUESS.           No keyword match means topic None, which sends the
                         enquiry to the clarity gate to be asked about. A held
                         enquiry is a delay; a guessed one is a wrong answer in
                         Blood's voice.
"""

import json
import os
import re

import pandas as pd

OUT = "store/extractions.json"

# ------------------------------------------------------------------ language
# Checked in order. Script first (Mandarin is unmistakable), then function words
# that only appear in one language, then Singlish particles, then English.
CJK = re.compile(r"[一-鿿]")
MS_ONLY = ("nak ", "tak ", "boleh", "macam mana", "kat ", "saya nak", "dah ",
           "sepatutnya", "patut", "berapa kerap", "sesuai", "jumpa", "kedai",
           "tolong", "pesanan", "penghantaran", "salam", "ni?", "ya?")
ID_ONLY = ("nggak", "gimana", "banget", "udah", "kok ", "ya?", "aja", "nih",
           "mau tanya", "bisa", "gimana ya", "dong", "sudah sampai", "kapan",
           "mohon", "sebaiknya", "cocok", "toko", "harusnya", "gara-gara")
SG_ONLY = (" ah?", " ah ", " leh", " lah", " liao", " anot", "or not", "damn ",
           "eh ", "wah ", "cannot like that", "quite big size", "how ah")


def detect_language(t):
    if CJK.search(t):
        return "zh"
    low = " " + t.lower() + " "
    ms = sum(k in low for k in MS_ONLY)
    idn = sum(k in low for k in ID_ONLY)
    sg = sum(k in low for k in SG_ONLY)
    # Malay and Indonesian share vocabulary, so the winner needs a clear lead.
    if max(ms, idn) > 0 and max(ms, idn) >= sg:
        return "ms" if ms > idn else "id"
    if sg > 0:
        return "sg"
    return "en"


# ------------------------------------------------------------------ health
# CHECKED FIRST AND SEPARATELY, in every language, before any topic lookup.
# A rash on a newborn misread as "Product usage" gets an automated note about
# storing pads in a cool dry place. Nothing else this file does matters if that
# happens once, so recall here is the only number that can stop the project.
HEALTH = (
    # en / sg
    "rash", "rashes", "blister", "blistered", "burning", "burnt", "irritat",
    "itchy", "itching", "swollen", "swelling", "allergic", "allergy", "sore",
    "skin react", "red all over", "bleeding",
    # ms
    "ruam", "melecet", "gatal", "pedih", "bengkak", "alahan", "kulit saya",
    "kulit baby",
    # id
    "melepuh", "perih", "iritasi", "bentol", "kulit saya", "kulit bayi",
    # zh
    "红疹", "疹子", "起疹", "水泡", "灼痛", "过敏", "发红", "红肿", "刺痛",
)

# ------------------------------------------------------------------ topics
# Order matters: the first list that matches wins, so the SPECIFIC lists come
# before the general ones.
#
# Subscription sits above Product usage because of one Malay collision found by
# running this and checking: "Boleh tukar langganan jadi setiap 6 minggu tak?"
# means "change my subscription to every 6 weeks". "tukar" (change) is a Product
# usage word - "tukar setiap 3-4 jam", change every 3-4 hours. Both lists match
# one keyword, so whichever is checked first wins, and Product usage was winning
# six times. "langganan" is unambiguous where "tukar" is not, so the unambiguous
# list goes first. This is what maintaining a keyword list per language costs.
TOPIC_KEYWORDS = [
    ("Damaged item", (
        "damaged", "crushed", "torn", "squash", "spoil", "box wet", "wet",
        "penyek", "koyak", "rosak", "sobek", "kardus", "kotak",
        "破", "压扁", "受损", "湿")),
    ("Refund/return", (
        "refund", "return", "wrong size", "unopened", "money back",
        "pulangkan", "tersalah pesan", "retur", "salah pesan", "kembalikan",
        "退货", "退款", "订错")),
    ("Delivery delay", (
        "late", "delay", "still never come", "supposed to arrive", "not arrived",
        "lewat", "tertunda", "belum sampai", "telat", "harusnya sampai",
        "belum ada kabar", "延迟", "延误", "还没有消息", "没到")),
    ("Order status", (
        "where is my order", "check status", "status of", "any update",
        "still says preparing", "how ah", "where my order", "track",
        "semak status", "status pesanan", "sampai mana", "belum ada update",
        "订单", "到哪里", "查一下", "准备中")),
    ("Sizing", (
        "size", "kg", "which size", "newborn size", "chubby",
        "saiz", "berisi", "ukuran", "gemuk", "尺码", "码", "公斤")),
    ("Ingredients", (
        "chlorine", "ingredient", "material", "fragrance", "sensitive skin",
        "top sheet", "what material",
        "klorin", "bahan", "sensitif", "lapisan atas", "wangian", "pewangi",
        "无氯", "成分", "材质", "香精", "敏感")),
    ("Subscription", (
        "subscription", "subscribe", "pause", "every 6 weeks", "cancel my",
        "langganan", "jeda", "batalkan", "订阅", "暂停", "续订")),
    ("Product usage", (
        "how often", "change every", "how long", "flush", "store", "8 hours",
        "berapa kerap", "tukar", "simpan", "tandas", "kloset", "diganti",
        "多久换", "保存", "冲马桶", "几个小时")),
    ("Where to buy", (
        "guardian", "watsons", "pharmacy", "in store", "where can i buy",
        "offline", "stockist", "sell in", "got sell",
        "kedai", "beli", "apotek", "jual", "屈臣氏", "哪里买", "有卖", "门店")),
]

# ------------------------------------------------------------------ the rest
ORDER_RE = re.compile(r"\bORD-\d{5}\b", re.I)
ANGRY = ("respond now", "not okay", "not acceptable", "urgent", "damn",
         "tak boleh diterima", "tidak bisa dibiarkan", "mohon segera",
         "tolong balas cepat", "不能接受", "尽快")
FRUSTRATED = ("still", "again", "already", "so long", "how can like that",
              "sampai sekarang", "dah seminggu", "udah seminggu", "belum",
              "到现在", "还是")
ACTION = {"Refund/return": "Refund", "Damaged item": "Replace",
          "Order status": "Track", "Delivery delay": "Track",
          "Subscription": "Cancel"}


def extract(text, eid):
    t = (text or "").strip()
    low = t.lower()
    lang = detect_language(t)

    # GATE ZERO of the whole system: is anyone hurt? Asked before anything else.
    health = any(k in low for k in HEALTH)

    topic, hits = None, 0
    if health:
        topic, hits = "Health complaint", 1
    else:
        for name, keys in TOPIC_KEYWORDS:
            n = sum(k in low for k in keys)
            if n > hits:
                topic, hits = name, n
    if topic is None and len(t) < 25:
        topic = "Unclear"

    m = ORDER_RE.search(t)

    if any(k in low for k in ANGRY) or (t.isupper() and len(t) > 12):
        sent = "Angry"
    elif any(k in low for k in FRUSTRATED):
        sent = "Frustrated"
    else:
        sent = "Neutral"

    return {
        "enquiry_id": eid,
        "language": lang,
        "topic": topic,
        "is_health_issue": health,
        "sentiment": sent,
        "order_id": m.group(0).upper() if m else None,
        "order_id_model": None,
        "requested_action": ("Escalate" if health else
                             ACTION.get(topic, "Answer" if topic else "Unclear")),
        "urgency": "High" if (health or sent == "Angry") else "Normal",
        # Not a probability. It is how many keywords matched, which is the only
        # honest confidence a keyword list can offer.
        "confidence": round(min(1.0, 0.55 + 0.15 * hits), 2) if topic else None,
        "method": "keywords",
    }


if __name__ == "__main__":
    enq = pd.read_csv("data/enquiries.csv", keep_default_na=False)
    ext = [extract(r.Raw_Message, r.enquiry_id) for _, r in enq.iterrows()]

    os.makedirs("store", exist_ok=True)
    json.dump(ext, open(OUT, "w"), indent=1, ensure_ascii=False)

    E = pd.DataFrame(ext)
    n = len(E)
    print("\n" + "=" * 74)
    print(f"  EXTRACTION  ·  {n} messages  ·  keyword lists, five languages")
    print("=" * 74)
    print("\n  LANGUAGE DETECTED")
    for l, c in E.language.value_counts(dropna=False).items():
        print(f"     {str(l):<6}{c:>5}")
    print("\n  TOPIC")
    for t, c in E.topic.value_counts(dropna=False).items():
        print(f"     {str(t):<20}{c:>5}")
    print(f"\n  FLAGGED AS A PHYSICAL REACTION   {int(E.is_health_issue.sum())}")
    f = int(E.order_id.notna().sum())
    print(f"  ORDER REFERENCE IN THE TEXT      {f} of {n}   ({n-f} never mention one)")
    print(f"  NO TOPIC COULD BE READ           {int(E.topic.isna().sum())}"
          "   -> these go to the clarity gate")

    print("\n" + "-" * 74)
    print("  Accuracy is NOT reported here. ground_truth.csv is quarantined to")
    print("  eval.py, and a file that grades its own homework is not a test.")
    print(f"  -> {OUT}")
    print("=" * 74 + "\n")
    