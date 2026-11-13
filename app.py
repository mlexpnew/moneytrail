"""MoneyTrail dashboard.  streamlit run app.py"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from moneytrail.cases import build_cases, cbwtr, ctr, str_draft
from moneytrail.detect import Rules, run_all
from moneytrail.io import load_customers, load_transactions
from moneytrail.synth import WATCHLIST, dataset

st.set_page_config(page_title="MoneyTrail", page_icon="🔎", layout="wide")
st.title("MoneyTrail")
st.caption(
    "AML transaction monitoring: explainable alerts, one ranked case per customer, "
    "CTR and cross-border reports, draft STRs for analyst review."
)

cu = st.sidebar.file_uploader("Customers (CSV)", type="csv")
tx = st.sidebar.file_uploader("Transactions (CSV)", type="csv")


@st.cache_data(show_spinner="Scanning six months of transactions...")
def sample():
    C, T, truth = dataset("dev")
    return C, T


@st.cache_data(show_spinner="Scanning...")
def scan(C, T, wl):
    alerts = run_all(T, C, Rules(watchlist=list(wl)))
    return alerts, build_cases(alerts, C)


if cu and tx:
    C, T, wl = load_customers(cu), load_transactions(tx), ()
else:
    st.info("No files uploaded: showing a sample book of 2,500 customers and 6 months of transactions.")
    C, T = sample()
    wl = tuple(WATCHLIST)
alerts, cases = scan(C, T, wl)

k = st.columns(4)
k[0].metric("Transactions", f"{len(T):,}")
k[1].metric("Alerts", f"{len(alerts):,}")
k[2].metric("Cases", f"{len(cases):,}")
k[3].metric("CTR rows", f"{len(ctr(T)):,}")

queue, detail, reports = st.tabs(["Case queue", "Case detail", "Reports"])
with queue:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "score": round(c.score, 1),
                    "customer": c.customer_id,
                    "name": c.name,
                    "segment": c.segment,
                    "KYC risk": c.kyc_risk,
                    "patterns": ", ".join(c.typologies),
                    "alerts": len(c.alerts),
                }
                for c in cases
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
with detail:
    if cases:
        pick = st.selectbox(
            "Case",
            range(len(cases)),
            format_func=lambda i: (
                f"{cases[i].customer_id} · {cases[i].name} · {', '.join(cases[i].typologies)}"
            ),
        )
        c = cases[pick]
        for a in c.alerts:
            st.warning(f"**{a.typology.replace('_', ' ')}**: {a.reason}")
        st.dataframe(
            T[T.txn_id.isin({t for a in c.alerts for t in a.txn_ids})].sort_values("ts"),
            hide_index=True,
            use_container_width=True,
        )
        st.subheader("Draft STR")
        st.code(str_draft(c, T), language=None)
        st.caption(
            "A draft for the reviewing officer. File within 7 working days of concluding it is suspicious."
        )
with reports:
    st.subheader("Cash Transaction Report (₹10 lakh or more in a month), due by the 15th")
    st.dataframe(ctr(T), hide_index=True, use_container_width=True)
    st.subheader("Cross-border wire transfers above ₹5 lakh")
    st.dataframe(cbwtr(T), hide_index=True, use_container_width=True)
