"""Alerts -> one case per customer, ranked so analysts start with the riskiest; regulatory
reports (CTR, cross-border wire report) and a draft STR for analyst review."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .detect import Alert, inr

WEIGHT = {
    "watchlist": 90,
    "round_trip": 80,
    "mule": 80,
    "high_risk_geo": 70,
    "structuring": 70,
    "ctr_avoidance": 65,
    "dormant": 60,
    "income_mismatch": 50,
}
KYC_BONUS = {"high": 10, "medium": 3, "low": 0}


@dataclass
class Case:
    customer_id: str
    name: str
    segment: str
    kyc_risk: str
    score: float
    alerts: list[Alert] = field(default_factory=list)

    @property
    def typologies(self) -> list[str]:
        return sorted({a.typology for a in self.alerts})

    def as_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "segment": self.segment,
            "kyc_risk": self.kyc_risk,
            "score": round(self.score, 1),
            "typologies": self.typologies,
            "alerts": [a.as_dict() for a in self.alerts],
        }


def build_cases(alerts: list[Alert], C: pd.DataFrame) -> list[Case]:
    info = C.set_index("customer_id")
    by: dict[str, list[Alert]] = {}
    for a in alerts:
        by.setdefault(a.customer_id, []).append(a)
    cases = []
    for cid, al in by.items():
        row = info.loc[cid] if cid in info.index else None
        base = max(WEIGHT.get(a.typology, 40) for a in al)
        extra = 10 * (len({a.typology for a in al}) - 1) + 3 * min(len(al) - 1, 5)
        money = 4 * math.log10(max(sum(a.amount for a in al), 1e4) / 1e4)
        kyc = KYC_BONUS.get(row.kyc_risk if row is not None else "low", 0)
        cases.append(
            Case(
                cid,
                row["name"] if row is not None else "",
                row.segment if row is not None else "",
                row.kyc_risk if row is not None else "",
                base + extra + money + kyc,
                al,
            )
        )
    return sorted(cases, key=lambda c: -c.score)


# -- reports ---------------------------------------------------------------------------
def ctr(T: pd.DataFrame) -> pd.DataFrame:
    """Cash Transaction Report: customers with cash of ₹10 lakh or more in a month (deposits and
    withdrawals counted separately per direction, as linked cash transactions)."""
    cash = T[T.channel.astype(str) == "CASH"].copy()
    cash["month"] = pd.to_datetime(cash.ts).dt.to_period("M").astype(str)
    g = (
        cash.groupby(["customer_id", "month", "direction"])
        .agg(total=("amount", "sum"), transactions=("txn_id", "count"))
        .reset_index()
    )
    g = g[g.total >= 1_000_000].copy()
    g["due_by"] = (pd.PeriodIndex(g.month, freq="M") + 1).to_timestamp() + pd.Timedelta(days=14)
    return g.sort_values(["month", "total"], ascending=[True, False]).reset_index(drop=True)


def cbwtr(T: pd.DataFrame) -> pd.DataFrame:
    """Cross Border Wire Transfer Report: transfers above ₹5 lakh to or from abroad."""
    x = T[(T.country.astype(str) != "India") & (T.amount > 500_000)].copy()
    x["month"] = pd.to_datetime(x.ts).dt.to_period("M").astype(str)
    return x[["month", "txn_id", "customer_id", "direction", "amount", "country", "counterparty_name"]]


def str_draft(case: Case, T: pd.DataFrame) -> str:
    """A draft Suspicious Transaction Report narrative. An analyst must review and decide; under
    PMLA the STR is due within 7 working days of concluding the activity is suspicious."""
    ids = {t for a in case.alerts for t in a.txn_ids}
    rows = T[T.txn_id.isin(ids)]
    lines = [
        f"Customer: {case.name} ({case.customer_id}), segment {case.segment}, KYC risk {case.kyc_risk}.",
        f"Period: {rows.ts.min()} to {rows.ts.max()}; {len(rows)} transactions totalling "
        f"{inr(rows.amount.sum())}.",
        "Grounds of suspicion:",
        *[f"- {a.typology.replace('_', ' ')}: {a.reason}." for a in case.alerts],
        "Counterparties involved: " + ", ".join(sorted(set(rows.counterparty_name.astype(str)))[:12]) + ".",
        "Analyst assessment: [to be completed by the reviewing officer before filing].",
    ]
    return "\n".join(lines)
