"""Streamlit front end on the Gold layer: KPIs, data quality, architecture and the documentation assistant.

    streamlit run app.py      (after python run.py)
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from lakehouse.rag import Assistant

ROOT = Path(__file__).resolve().parent
EXPORT = ROOT / "powerbi" / "export"
CHANNELS = ["web_ch", "web_eu", "store_geneve", "store_lausanne", "store_zurich"]
COLORS = ["#2a78d6", "#8fb8ea", "#eb6834", "#eda100", "#1baf7a"]
INK, INK2, LINE = "#0b0b0b", "#6b6862", "#e4e3df"

st.set_page_config(page_title="Alpina lakehouse", page_icon="◆", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1280px;}
[data-baseweb="tag"] {background-color: #eef4fc !important; color: #1f5fae !important;}
[data-baseweb="tag"] span {color: #1f5fae !important;}
.hero {background: linear-gradient(90deg, #f6e3d3 0%, #e7eaee 50%, #f8edc8 100%); border-radius: 14px;
       padding: 18px 22px; margin-bottom: 14px;}
h1 {font-weight: 750; letter-spacing: -0.02em; margin-bottom: 0;}
.sub {color: #6b6862; margin: 0.2rem 0 1.2rem 0;}
.tiles {display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 1rem;}
.tile {border: 1px solid #e4e3df; border-radius: 12px; padding: 14px 16px; background: #fcfcfb;}
.tile .k {font-size: 0.78rem; color: #6b6862; text-transform: uppercase; letter-spacing: 0.04em;}
.tile .v {font-size: 1.6rem; font-weight: 700; color: #0b0b0b; margin-top: 2px;}
.tile .n {font-size: 0.8rem; color: #1baf7a;}
.layer {display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 0.75rem; font-weight: 600;}
.src {border-left: 3px solid #c9a227; padding: 6px 12px; background: #faf8f1; border-radius: 6px; margin: 6px 0;
      font-size: 0.9rem; color: #3a3935;}
@media (max-width: 900px) {.tiles {grid-template-columns: repeat(2, 1fr);}}
</style>""", unsafe_allow_html=True)


@st.cache_data
def load():
    t = {f.stem: pd.read_csv(f) for f in EXPORT.glob("*.csv")}
    t["kpi_daily_channel"]["date"] = pd.to_datetime(t["kpi_daily_channel"]["date_key"].astype(str))
    t["dq_daily"]["day"] = pd.to_datetime(t["dq_daily"]["day"])
    return t, json.loads((ROOT / "results" / "summary.json").read_text())


@st.cache_resource
def assistant():
    return Assistant()


if not (ROOT / "results" / "summary.json").exists():
    st.error("Run `python run.py` first: it builds the lake and the Gold export this app reads.")
    st.stop()
t, s = load()
kpi = t["kpi_daily_channel"]

st.markdown("<div class='hero'><h1>Horlogerie Alpina · Lakehouse</h1>"
            f"<p class='sub' style='margin-bottom:0'>Bronze → Silver → Gold in PySpark · {s['days']} days · "
            f"{s['bronze_rows']:,} order lines received · 5 channels · fictional data</p></div>",
            unsafe_allow_html=True)

channels = st.multiselect("Channels", CHANNELS, CHANNELS, label_visibility="collapsed")
k = kpi[kpi["channel"].isin(channels)]
rev, orders = k["revenue_chf"].sum(), k["orders"].sum()
returns = k["returned_orders"].sum() / max(k["all_orders"].sum(), 1)
funnel = t["kpi_web_funnel"]
conv = funnel["web_orders"].sum() / funnel["page_view"].sum()
rec = s["gold"]["reconciliation"]
tiles = [("Revenue", f"CHF {rev / 1e6:,.2f} M", ""), ("Completed orders", f"{orders:,}", ""),
         ("Average order", f"CHF {rev / max(orders, 1):,.0f}", ""), ("Return rate", f"{returns:.1%}", ""),
         ("Gold vs Silver", f"{abs(rec['difference_chf']):.2f} CHF", "difference, reconciled to the centime")]
st.markdown("<div class='tiles'>" + "".join(
    f"<div class='tile'><div class='k'>{a}</div><div class='v'>{b}</div><div class='n'>{c}</div></div>"
    for a, b, c in tiles) + "</div>", unsafe_allow_html=True)

overview, quality, arch, ask = st.tabs(["Sales", "Data quality", "Architecture", "Ask the documentation"])
scale = alt.Scale(domain=CHANNELS, range=COLORS)

with overview:
    c1, c2 = st.columns([2.2, 1])
    bars = alt.Chart(k).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
        x=alt.X("yearmonthdate(date):T", title=None), y=alt.Y("sum(revenue_chf):Q", title="revenue (CHF)"),
        color=alt.Color("channel:N", scale=scale, legend=alt.Legend(orient="top", title=None)),
        tooltip=["channel", alt.Tooltip("date:T"), alt.Tooltip("revenue_chf:Q", format=",.0f")]).properties(height=320)
    c1.markdown("**Daily revenue by channel**"); c1.altair_chart(bars, use_container_width=True)
    steps = ["page_view", "product_view", "add_to_cart", "checkout", "web_orders"]
    f = pd.DataFrame({"step": steps, "sessions": [funnel[x].sum() for x in steps]})
    fch = alt.Chart(f).mark_bar(color="#2a78d6", cornerRadiusEnd=3).encode(
        y=alt.Y("step:N", sort=steps, title=None), x=alt.X("sessions:Q", title=None),
        tooltip=["step", alt.Tooltip("sessions:Q", format=",")]).properties(height=320)
    c2.markdown(f"**Web funnel** · conversion {conv:.1%}"); c2.altair_chart(fch, use_container_width=True)
    c3, c4 = st.columns(2)
    cat = t["kpi_category_month"]
    cch = alt.Chart(cat).mark_bar().encode(
        x=alt.X("sum(revenue_chf):Q", title="revenue (CHF)"), y=alt.Y("category:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
        color=alt.Color("channel_type:N", scale=alt.Scale(range=["#eb6834", "#2a78d6"]),
                        legend=alt.Legend(orient="top", title=None))).properties(height=240)
    c3.markdown("**Revenue by category**"); c3.altair_chart(cch, use_container_width=True)
    cust = t["kpi_customers_daily"].copy()
    cust["date"] = pd.to_datetime(cust["date_key"].astype(str))
    cl = cust.melt("date", ["new_customers", "returning_customers"], "type", "customers")
    lch = alt.Chart(cl).mark_area(opacity=0.85).encode(
        x=alt.X("date:T", title=None), y=alt.Y("customers:Q", stack=True, title="customers"),
        color=alt.Color("type:N", scale=alt.Scale(range=["#1baf7a", "#a7dcc6"]),
                        legend=alt.Legend(orient="top", title=None))).properties(height=220)
    c4.markdown("**New and returning customers**"); c4.altair_chart(lch, use_container_width=True)

with quality:
    q = s["quality"]
    rows = [("Duplicate lines", q["duplicates"]["injected"], q["duplicates"]["removed"], "removed in Silver"),
            ("Missing customer", q["missing_customer"]["injected"], q["missing_customer"]["caught"], "quarantined"),
            ("Zero quantity", q["zero_quantity"]["injected"], q["zero_quantity"]["caught"], "quarantined"),
            ("Price in centimes", q["price_in_cents"]["injected"], q["price_in_cents"]["caught"], "quarantined"),
            ("Unknown product", q["unknown_product"]["injected"], q["unknown_product"]["caught"], "quarantined"),
            ("Swiss date format", q["swiss_date_format"]["injected"], q["swiss_date_format"]["parsed"], "parsed"),
            ("Late arrival", q["late_arrival"]["injected"], q["late_arrival"]["merged_into_order_day"],
             "merged into the order day")]
    c1, c2 = st.columns([1, 1.3])
    c1.markdown("**Injected defects and how Silver handled them**")
    c1.dataframe(pd.DataFrame(rows, columns=["defect", "injected", "handled", "how"]), hide_index=True,
                 use_container_width=True)
    c1.caption("The one late line not merged also had no customer: it is in quarantine, as it should be.")
    dq = t["dq_daily"]
    rules = [c for c in dq.columns if c.startswith("rule_")]
    dl = dq.melt("day", rules, "rule", "lines")
    dl["rule"] = dl["rule"].str.replace("rule_", "")
    dch = alt.Chart(dl).mark_bar().encode(
        x=alt.X("yearmonthdate(day):T", title=None), y=alt.Y("sum(lines):Q", title="lines quarantined"),
        color=alt.Color("rule:N", scale=alt.Scale(scheme="tableau10"), legend=alt.Legend(orient="top", title=None)),
        tooltip=["rule", "day:T", "lines"]).properties(height=300)
    c2.markdown("**Quarantine per day and rule**"); c2.altair_chart(dch, use_container_width=True)
    a, b, c = st.columns(3)
    a.metric("Lines in Silver", f"{s['silver_rows']:,}")
    b.metric("Lines in quarantine", f"{s['quarantined_rows']:,}")
    c.metric("Replay of a day", "no change" if s["idempotent_replay"]["gold_unchanged"] else "CHANGED")

with arch:
    st.image(str(ROOT / "docs" / "figures" / "architecture.png"), use_container_width=True)
    c1, c2 = st.columns([1.2, 1])
    c1.image(str(ROOT / "docs" / "figures" / "star_schema.png"), use_container_width=True)
    c2.markdown("**Gold tables**")
    c2.dataframe(pd.DataFrame(s["gold"]["rows"].items(), columns=["table", "rows"]), hide_index=True,
                 use_container_width=True)

with ask:
    st.markdown("Answers come only from `docs/knowledge`. If the documentation does not cover the question, "
                "the assistant says so instead of guessing.")
    examples = ["How is revenue defined in the reports?", "A line arrived in the next day's file, which day does it "
                "count for?", "Are customer emails stored in the Gold layer?", "What is the salary of the store "
                "manager in Geneva?"]
    pick = st.radio("Examples", examples, horizontal=False, label_visibility="collapsed")
    question = st.text_input("Your question", pick)
    res = assistant().answer(question)
    if res["refused"]:
        st.warning(res["answer"])
    else:
        st.markdown(f"<div class='src'>{res['answer']}<br><span style='color:#6b6862;font-size:0.8rem'>"
                    f"source: {', '.join(res['sources'])}</span></div>", unsafe_allow_html=True)
    r1, r2 = s["rag"], s["rag_heldout"]
    st.markdown("**Evaluation**")
    st.dataframe(pd.DataFrame({
        "set": ["tuning (26 questions)", "held out (15 questions)"],
        "right source in top 3": [f"{r1['hit@3']:.0%}", f"{r2['hit@3']:.0%}"],
        "answers when it can": [f"{r1['answered_when_answerable']:.0%}", f"{r2['answered_when_answerable']:.0%}"],
        "refuses out of scope": [f"{r1['refused_when_out_of_scope']:.0%}", f"{r2['refused_when_out_of_scope']:.0%}"],
    }), hide_index=True, use_container_width=True)
