import pandas as pd

from workbridge.cases import build_cases, cbwtr, ctr, str_draft
from workbridge.detect import (
    Rules,
    ctr_avoidance,
    dormant,
    high_risk_geo,
    income_mismatch,
    mule,
    name_score,
    round_trip,
    structuring,
    watchlist,
)
from workbridge.io import load_transactions

COLS = [
    "txn_id",
    "ts",
    "customer_id",
    "direction",
    "amount",
    "channel",
    "counterparty_id",
    "counterparty_name",
    "country",
    "narration",
    "self_transfer",
]


def tx(rows):
    t = pd.DataFrame(
        [(f"T{i}", pd.Timestamp(r[0]), *r[1:], *([""] * (10 - len(r)))) for i, r in enumerate(rows)],
        columns=COLS,
    )
    t["country"] = t["country"].replace("", "India")
    t["self_transfer"] = t["self_transfer"].map(lambda v: v is True)
    return t


CUST = pd.DataFrame(
    [
        {
            "customer_id": c,
            "name": n,
            "segment": s,
            "declared_income": i,
            "kyc_risk": "low",
            "opened": "2023-01-01",
            "last_active_before": la,
        }
        for c, n, s, i, la in [
            ("A", "Asha Rao", "salaried", 6e5, "2025-04-25"),
            ("B", "Bala Iyer", "business", 2e7, "2025-04-25"),
            ("C", "Chitra Das", "trader", 1e6, "2025-04-25"),
            ("D", "Dev Nair", "retired", 3e5, "2023-01-01"),
        ]
    ]
)


def test_structuring_needs_several_deposits_under_50k():
    t = tx(
        [
            ("2025-06-01", "A", "credit", 49_000, "CASH"),
            ("2025-06-03", "A", "credit", 48_500, "CASH"),
            ("2025-06-05", "A", "credit", 47_000, "CASH"),
            ("2025-06-01", "B", "credit", 49_000, "CASH"),
        ]
    )
    al = structuring(t, Rules())
    assert [a.customer_id for a in al] == ["A"] and len(al[0].txn_ids) == 3


def test_ctr_avoidance_only_when_unusual_for_customer():
    rows = [(f"2025-0{m}-0{d}", "C", "credit", 2.3e5, "CASH") for m in (6, 7, 8) for d in (1, 3, 5, 7)]
    rows += [
        ("2025-09-01", "A", "credit", 2.4e5, "CASH"),
        ("2025-09-02", "A", "credit", 2.4e5, "CASH"),
        ("2025-09-03", "A", "credit", 2.4e5, "CASH"),
        ("2025-09-04", "A", "credit", 2.3e5, "CASH"),
    ]
    al = ctr_avoidance(tx(rows), Rules())
    assert [a.customer_id for a in al] == ["A"]  # the shop at ₹9.2 lakh every month is not flagged


def test_mule_pass_through_with_ordinary_upi_spend():
    rows = [(f"2025-07-01 {h:02d}:00", "A", "credit", 9_000, "UPI", f"S{h}") for h in range(10)]
    rows += [("2025-07-01 20:00", "A", "debit", 80_000, "IMPS", "H1")]
    rows += [(f"2025-07-01 {h:02d}:30", "A", "debit", 300, "UPI", f"M{h}") for h in range(5)]
    al = mule(tx(rows), Rules())
    assert len(al) == 1 and "10 senders" in al[0].reason


def test_round_trip_and_dormant_and_mismatch_and_geo():
    t = tx(
        [
            ("2025-06-01", "A", "debit", 5e5, "RTGS", "B"),
            ("2025-06-02", "B", "debit", 4.9e5, "RTGS", "C"),
            ("2025-06-03", "C", "debit", 4.8e5, "RTGS", "A"),
            ("2025-06-10", "D", "credit", 3e5, "NEFT", "X1"),
            ("2025-07-01", "A", "credit", 6e5, "NEFT", "Q1"),
            ("2025-07-15", "A", "credit", 5e5, "NEFT", "Q2"),
            ("2025-08-01", "D", "credit", 2e5, "NEFT", "FD", "FD", "India", "", True),
            ("2025-08-02", "B", "debit", 2e5, "SWIFT", "F1", "Co", "Iran"),
        ]
    )
    assert {a.customer_id for a in round_trip(t, Rules(), set("ABCD"))} == {"A", "B", "C"}
    assert [a.customer_id for a in dormant(t, CUST, Rules())] == ["D"]
    im = {a.customer_id: a for a in income_mismatch(t, CUST, Rules())}
    assert "A" in im and "C" not in im
    fd = t[t.counterparty_id == "FD"].txn_id.item()
    assert all(fd not in a.txn_ids for a in im.values())  # D's own fixed deposit is not income
    assert [a.customer_id for a in high_risk_geo(t, Rules())] == ["B"]


def test_names():
    w = "Mohammed Arif Khan"
    assert name_score("Mohd. Arif Khan", w) == 1 and name_score("Khan Mohammed Arif", w) == 1
    assert name_score("M Arif Khan", w) >= 0.9
    assert name_score("Mohammed Arif Khanna", w) == 0 and name_score("Arif Khan", w) == 0
    assert name_score("Narayanlal Meena", "Narayan Lal Meena") == 1
    t = tx([("2025-06-01", "A", "debit", 1e4, "IMPS", "W", "Mr. Mohd Arif Khan")])
    assert len(watchlist(t, Rules(watchlist=[w]))) == 1


def test_cases_reports_and_str():
    t = tx(
        [
            ("2025-06-01", "A", "credit", 6e5, "CASH"),
            ("2025-06-20", "A", "credit", 5e5, "CASH"),
            ("2025-06-21", "B", "debit", 7e5, "SWIFT", "F1", "Co", "Iran"),
        ]
    )
    al = high_risk_geo(t, Rules())
    cases = build_cases(al, CUST)
    assert cases[0].customer_id == "B"
    rep = ctr(t)
    assert rep.customer_id.tolist() == ["A"] and str(rep.due_by.iloc[0].date()) == "2025-07-15"
    assert cbwtr(t).customer_id.tolist() == ["B"]
    assert "Grounds of suspicion" in str_draft(cases[0], t)


def test_io_maps_bank_columns():
    raw = pd.DataFrame(
        {
            "UTR": ["U1"],
            "Txn Date": ["05/06/2025"],
            "CIF": ["A"],
            "Dr/Cr": ["Cr"],
            "Amount": [100.0],
            "Mode": ["upi"],
        }
    )
    t = load_transactions(raw)
    assert t.ts.iloc[0].month == 6 and t.direction.iloc[0] == "credit" and t.channel.iloc[0] == "UPI"
