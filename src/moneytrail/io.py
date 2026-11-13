"""Read core-banking exports. Two CSV or Excel files:

customers: customer_id, name, segment, declared_income, kyc_risk, opened, last_active_before
transactions: txn_id, ts, customer_id, direction (credit/debit), amount, channel
              (UPI/IMPS/NEFT/RTGS/CASH/CARD/SWIFT), counterparty_id, counterparty_name,
              country, [narration], [self_transfer]
Common alternative column names are mapped automatically.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ALIASES = {
    "txn_id": ["transaction id", "txn id", "reference", "utr", "ref no"],
    "ts": ["timestamp", "date", "txn date", "transaction date", "value date", "datetime"],
    "customer_id": ["customer id", "cust id", "cif", "account id"],
    "direction": ["dr/cr", "type", "debit/credit", "cr/dr"],
    "amount": ["amount", "txn amount", "inr amount"],
    "channel": ["mode", "channel", "payment mode"],
    "counterparty_id": ["beneficiary account", "counterparty account", "remitter account"],
    "counterparty_name": ["beneficiary name", "remitter name", "counterparty"],
    "country": ["country", "beneficiary country"],
}


def _read(p) -> pd.DataFrame:
    if isinstance(p, pd.DataFrame):
        return p.copy()
    p = Path(p)
    return pd.read_excel(p) if p.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(p)


def load_transactions(p) -> pd.DataFrame:
    t = _read(p)
    low = {c.lower().strip(): c for c in t.columns}
    for canon, alts in ALIASES.items():
        if canon not in t.columns:
            hit = next((low[a] for a in alts if a in low), None)
            if hit:
                t = t.rename(columns={hit: canon})
    t["ts"] = pd.to_datetime(t["ts"], dayfirst=not str(t["ts"].iloc[0])[:4].isdigit())
    t["direction"] = (
        t["direction"].astype(str).str.lower().map(lambda v: "credit" if v.startswith(("c", "cr")) else "debit")
    )
    t["channel"] = t["channel"].astype(str).str.upper()
    for col, default in (
        ("country", "India"),
        ("counterparty_name", ""),
        ("narration", ""),
        ("self_transfer", False),
    ):
        if col not in t:
            t[col] = default
    return t


def load_customers(p) -> pd.DataFrame:
    c = _read(p)
    for col, default in (("segment", "salaried"), ("kyc_risk", "low"), ("declared_income", 0)):
        if col not in c:
            c[col] = default
    if "last_active_before" not in c:
        c["last_active_before"] = pd.NaT
    return c
