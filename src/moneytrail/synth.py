"""Synthetic book of an Indian NBFC / payments company with planted money-laundering patterns.

Real customer transactions cannot be published, so the benchmark simulates six months for
~2,500 customers. Most are honest and some look alarming to simple rules: high earners
whose salary is over ₹1 lakh, home buyers paying by RTGS, shops paid by dozens of UPI
customers a day, exporters wiring money abroad. A known set of customers follow real
laundering typologies (FATF / FIU-IND red flags). Truth is recorded per customer.
The held-out profile is stealthier and was fixed before any detector was written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

START, END = pd.Timestamp("2025-05-01"), pd.Timestamp("2025-10-31 23:59")
FIRST = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Ishaan",
    "Rohan",
    "Priya",
    "Ananya",
    "Diya",
    "Kavya",
    "Sneha",
    "Rahul",
    "Amit",
    "Suresh",
    "Lakshmi",
    "Meera",
    "Arjun",
    "Farhan",
    "Imran",
    "Ayesha",
    "Zoya",
    "Harpreet",
    "Gurpreet",
    "Joseph",
    "Mary",
    "Kiran",
    "Deepak",
    "Pooja",
    "Nikhil",
    "Sanjay",
    "Neha",
    "Vikram",
    "Anil",
    "Ritu",
    "Sunita",
    "Manoj",
]
LAST = [
    "Sharma",
    "Verma",
    "Gupta",
    "Iyer",
    "Nair",
    "Reddy",
    "Patel",
    "Shah",
    "Khan",
    "Singh",
    "Das",
    "Mukherjee",
    "Joshi",
    "Kulkarni",
    "Menon",
    "Pillai",
    "Fernandes",
    "Chopra",
    "Malhotra",
    "Agarwal",
    "Banerjee",
    "Rao",
    "Yadav",
    "Mishra",
    "Sheikh",
]
SEGMENTS = {"salaried": 0.52, "student": 0.10, "trader": 0.14, "business": 0.12, "retired": 0.12}
INCOME = {
    "salaried": (4e5, 3.6e6),
    "student": (0, 1e5),
    "trader": (5e5, 3e6),
    "business": (3e6, 3e7),
    "retired": (2e5, 9e5),
}
# Example list for the benchmark only; production must load the current FATF statements.
HIGH_RISK = ["Iran", "North Korea", "Myanmar"]
NORMAL_ABROAD = [
    "United Arab Emirates",
    "Singapore",
    "United States",
    "United Kingdom",
    "Germany",
    "Saudi Arabia",
]
WATCHLIST = [
    "Mohammed Arif Khan",
    "Rajesh Kumar Tiwari",
    "Abdul Rahman Siddiqui",
    "Sunil Baburao Pawar",
    "Yusuf Ibrahim Merchant",
    "Narayan Lal Meena",
]


@dataclass
class Profile:
    customers: int = 2500
    struct_band: tuple = (45_000, 49_900)
    struct_n: tuple = (3, 6)
    mule_senders: tuple = (10, 30)
    mule_out_share: tuple = (0.85, 0.98)
    mule_hours: int = 30
    ring_size: int = 3
    dormant_gap: tuple = (400, 900)
    mismatch_x: tuple = (5, 10)
    watch_variants: dict = field(
        default_factory=lambda: {
            "Mohammed Arif Khan": "Mohd. Arif Khan",
            "Rajesh Kumar Tiwari": "Rajesh K Tiwari",
            "Abdul Rahman Siddiqui": "Abdul Rehman Siddiqui",
            "Sunil Baburao Pawar": "Sunil B. Pawar",
            "Yusuf Ibrahim Merchant": "Yusuf Ibrahim Merchant",
            "Narayan Lal Meena": "Narayan Lal Meena",
        }
    )
    counts: dict = field(
        default_factory=lambda: {
            "structuring": 8,
            "ctr_avoidance": 5,
            "mule": 10,
            "round_trip": 3,
            "dormant": 5,
            "income_mismatch": 6,
            "high_risk_geo": 4,
            "watchlist": 5,
        }
    )


def held_out_profile() -> Profile:
    return Profile(
        customers=2500,
        struct_band=(42_000, 49_500),
        struct_n=(3, 4),
        mule_senders=(8, 18),
        mule_out_share=(0.80, 0.92),
        mule_hours=40,
        ring_size=4,
        dormant_gap=(370, 600),
        mismatch_x=(4, 7),
        watch_variants={
            "Mohammed Arif Khan": "Mohamad Arif Khan",
            "Rajesh Kumar Tiwari": "Tiwari Rajesh Kumar",
            "Abdul Rahman Siddiqui": "Abdul Rahman Siddiqi",
            "Sunil Baburao Pawar": "Sunil Baburao Powar",
            "Yusuf Ibrahim Merchant": "Md Yusuf Ibrahim Merchant",
            "Narayan Lal Meena": "Narayanlal Meena",
        },
        counts={
            "structuring": 7,
            "ctr_avoidance": 4,
            "mule": 9,
            "round_trip": 2,
            "dormant": 4,
            "income_mismatch": 6,
            "high_risk_geo": 3,
            "watchlist": 6,
        },
    )


class _Book:
    def __init__(self, rng):
        self.rng = rng
        self.rows: list[tuple] = []
        self.n = 0

    def add(
        self,
        ts,
        cust,
        direction,
        amount,
        channel,
        cp_id,
        cp_name,
        country="India",
        narration="",
        self_transfer=False,
    ):
        self.n += 1
        self.rows.append(
            (
                f"T{self.n:07d}",
                ts,
                cust,
                direction,
                round(float(amount), 2),
                channel,
                cp_id,
                cp_name,
                country,
                narration,
                self_transfer,
            )
        )

    def when(self, lo=START, hi=END):
        return lo + pd.Timedelta(seconds=int(self.rng.integers(0, int((hi - lo).total_seconds()))))


def _name(rng) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _months():
    return pd.date_range(START, END, freq="MS")


def generate(profile: Profile | None = None, seed: int = 7):
    """Returns (customers DataFrame, transactions DataFrame, truth dict customer_id -> typology)."""
    p = profile or Profile()
    rng = np.random.default_rng(seed)
    segs = rng.choice(list(SEGMENTS), p=list(SEGMENTS.values()), size=p.customers)
    cust = []
    for i, s in enumerate(segs):
        lo, hi = INCOME[s]
        opened = START - pd.Timedelta(days=int(rng.integers(30, 1800)))
        cust.append(
            {
                "customer_id": f"C{i:05d}",
                "name": _name(rng),
                "segment": s,
                "declared_income": round(float(rng.uniform(lo, hi)), -3),
                "kyc_risk": "medium" if s == "business" else ("high" if rng.random() < 0.02 else "low"),
                "opened": opened.date(),
                "last_active_before": (START - pd.Timedelta(days=int(rng.integers(1, 20)))).date(),
            }
        )
    C = pd.DataFrame(cust)
    b = _Book(rng)
    ids = C.customer_id.tolist()

    # ---- planted customers (disjoint) ------------------------------------------------
    truth: dict[str, str] = {}
    pool = [c for c in ids]
    rng.shuffle(pool)

    def take(n, segs_ok=None):
        out = []
        for c in list(pool):
            if len(out) == n:
                break
            if segs_ok and C.loc[C.customer_id == c, "segment"].item() not in segs_ok:
                continue
            out.append(c)
            pool.remove(c)
        return out

    planted = {
        "structuring": take(p.counts["structuring"], {"salaried", "trader", "retired"}),
        "ctr_avoidance": take(p.counts["ctr_avoidance"], {"trader", "salaried"}),
        "mule": take(p.counts["mule"], {"student", "salaried", "retired"}),
        "round_trip": take(p.counts["round_trip"] * p.ring_size, {"business", "trader", "salaried"}),
        "dormant": take(p.counts["dormant"], {"salaried", "retired", "trader"}),
        "income_mismatch": take(p.counts["income_mismatch"], {"salaried", "student"}),
        "high_risk_geo": take(p.counts["high_risk_geo"], {"business", "trader", "salaried"}),
        "watchlist": take(p.counts["watchlist"]),
    }
    for typ, cs in planted.items():
        for c in cs:
            truth[c] = typ
    # mule and dormant accounts look like it in KYC too: new or long inactive
    for c in planted["mule"]:
        C.loc[C.customer_id == c, "opened"] = (START + pd.Timedelta(days=int(rng.integers(0, 60)))).date()
    for c in planted["dormant"]:
        gap = int(rng.integers(*p.dormant_gap))
        C.loc[C.customer_id == c, "last_active_before"] = (START - pd.Timedelta(days=gap - 30)).date()
        C.loc[C.customer_id == c, "opened"] = (START - pd.Timedelta(days=gap + 400)).date()

    seg = dict(zip(C.customer_id, C.segment, strict=True))
    inc = dict(zip(C.customer_id, C.declared_income, strict=True))
    opened = dict(zip(C.customer_id, pd.to_datetime(C.opened), strict=True))

    # ---- normal behaviour ------------------------------------------------------------
    for c in ids:
        if truth.get(c) == "dormant":
            continue
        s, y = seg[c], inc[c]
        start = max(START, opened[c])
        for m in _months():
            if m < start.normalize() - pd.Timedelta(days=31):
                continue
            mend = m + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23)
            if s == "salaried":
                b.add(
                    m + pd.Timedelta(days=int(rng.integers(0, 3)), hours=10),
                    c,
                    "credit",
                    y / 12 * rng.uniform(0.95, 1.05),
                    "NEFT",
                    "EMP",
                    "Employer Pvt Ltd",
                    narration="salary",
                )
                for _ in range(int(rng.integers(8, 25))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "debit",
                        rng.uniform(80, 6000),
                        "UPI",
                        f"M{int(rng.integers(1e5))}",
                        "merchant",
                    )
                b.add(
                    m + pd.Timedelta(days=5),
                    c,
                    "debit",
                    y / 12 * rng.uniform(0.2, 0.35),
                    "NEFT",
                    "LANDLORD",
                    "rent / EMI",
                )
                if rng.random() < 0.3:
                    b.add(
                        b.when(m, mend),
                        c,
                        "debit",
                        round(rng.uniform(2e3, 2e4), -2),
                        "CASH",
                        "ATM",
                        "ATM",
                    )
            elif s == "student":
                for _ in range(int(rng.integers(1, 4))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "credit",
                        rng.uniform(2e3, 1.5e4),
                        "UPI",
                        f"P{c}",
                        "Parent",
                    )
                for _ in range(int(rng.integers(5, 20))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "debit",
                        rng.uniform(50, 2500),
                        "UPI",
                        f"M{int(rng.integers(1e5))}",
                        "merchant",
                    )
            elif s == "trader":
                direct_upi = int(c[1:]) % 4 == 0  # a quarter are shops collecting UPI directly
                days = pd.date_range(m, mend.normalize())
                for d in days:
                    if direct_upi:
                        for _ in range(int(rng.integers(5, 13))):
                            b.add(
                                d + pd.Timedelta(hours=float(rng.uniform(9, 21))),
                                c,
                                "credit",
                                rng.uniform(60, 2500),
                                "UPI",
                                f"X{int(rng.integers(1e6))}",
                                "customer",
                            )
                    elif rng.random() < 0.9:
                        b.add(
                            d + pd.Timedelta(hours=23),
                            c,
                            "credit",
                            y / 365 * rng.uniform(1.5, 4),
                            "NEFT",
                            "PA",
                            "PA settlement",
                        )
                for _ in range(int(rng.integers(2, 6))):  # weekly cash from the counter
                    b.add(
                        b.when(m, mend),
                        c,
                        "credit",
                        round(rng.uniform(1.5e4, 3.5e5), -2),
                        "CASH",
                        "BRANCH",
                        "cash deposit",
                    )
                for _ in range(int(rng.integers(3, 8))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "debit",
                        y / 12 * rng.uniform(0.15, 0.4),
                        "NEFT",
                        f"S{int(rng.integers(500))}",
                        "supplier",
                    )
            elif s == "business":
                for _ in range(int(rng.integers(4, 15))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "credit",
                        y / 12 * rng.uniform(0.05, 0.25),
                        rng.choice(["NEFT", "RTGS"]),
                        f"B{int(rng.integers(3000))}",
                        "client payment",
                    )
                for _ in range(int(rng.integers(5, 15))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "debit",
                        y / 12 * rng.uniform(0.03, 0.15),
                        rng.choice(["NEFT", "RTGS"]),
                        f"V{int(rng.integers(3000))}",
                        "vendor",
                    )
                if int(c[1:]) % 3 == 0 and rng.random() < 0.7:  # importers / exporters
                    b.add(
                        b.when(m, mend),
                        c,
                        rng.choice(["debit", "credit"]),
                        y / 12 * rng.uniform(0.1, 0.6),
                        "SWIFT",
                        f"F{int(rng.integers(500))}",
                        "overseas trade partner",
                        str(rng.choice(NORMAL_ABROAD)),
                    )
            else:  # retired
                b.add(
                    m + pd.Timedelta(days=1, hours=9),
                    c,
                    "credit",
                    y / 12,
                    "NEFT",
                    "PENSION",
                    "pension",
                )
                for _ in range(int(rng.integers(4, 12))):
                    b.add(
                        b.when(m, mend),
                        c,
                        "debit",
                        rng.uniform(100, 5000),
                        "UPI",
                        f"M{int(rng.integers(1e5))}",
                        "merchant",
                    )
                if rng.random() < 0.15:
                    b.add(
                        b.when(m, mend),
                        c,
                        "credit",
                        rng.uniform(2e4, 3e5),
                        "NEFT",
                        "FD",
                        "FD maturity",
                        self_transfer=True,
                    )
        if rng.random() < 0.04:  # one-off big legitimate events
            if s in ("salaried", "business"):
                b.add(
                    b.when(),
                    c,
                    "debit",
                    rng.uniform(1e6, 6e6),
                    "RTGS",
                    "BUILDER",
                    "property purchase",
                )
            else:
                b.add(b.when(), c, "credit", rng.uniform(2e5, 1.5e6), "NEFT", "FAMILY", "family gift")
        if s == "salaried" and rng.random() < 0.03:  # a relative sends money from abroad
            b.add(
                b.when(),
                c,
                "credit",
                rng.uniform(5e4, 6e5),
                "SWIFT",
                "REL",
                "family remittance",
                str(rng.choice(NORMAL_ABROAD)),
            )

    # ---- planted typologies ----------------------------------------------------------
    for c in planted["structuring"]:
        for _ in range(int(rng.integers(1, 4))):
            t0 = b.when(START, END - pd.Timedelta(days=8))
            for _ in range(int(rng.integers(p.struct_n[0], p.struct_n[1] + 1))):
                b.add(
                    t0 + pd.Timedelta(hours=float(rng.uniform(0, 6 * 24))),
                    c,
                    "credit",
                    round(rng.uniform(*p.struct_band), -2),
                    "CASH",
                    "BRANCH",
                    "cash deposit",
                )
    for c in planted["ctr_avoidance"]:
        m = _months()[int(rng.integers(0, 6))]
        target = rng.uniform(9.0e5, 9.9e5)
        n = int(rng.integers(5, 9))
        parts = rng.dirichlet(np.ones(n)) * target
        for amt in parts:
            b.add(
                b.when(m, m + pd.Timedelta(days=27)),
                c,
                "credit",
                round(amt, -2),
                "CASH",
                "BRANCH",
                "cash deposit",
            )
    for c in planted["mule"]:
        for _ in range(int(rng.integers(2, 5))):
            t0 = b.when(START + pd.Timedelta(days=30), END - pd.Timedelta(days=3))
            n = int(rng.integers(*p.mule_senders))
            total = 0.0
            for _ in range(n):
                amt = rng.uniform(2e3, 2.5e4)
                total += amt
                b.add(
                    t0 + pd.Timedelta(hours=float(rng.uniform(0, p.mule_hours * 0.6))),
                    c,
                    "credit",
                    amt,
                    rng.choice(["UPI", "IMPS"]),
                    f"V{int(rng.integers(1e7))}",
                    _name(rng),
                )
            outs = int(rng.integers(1, 3))
            share = rng.uniform(*p.mule_out_share)
            for k in range(outs):
                b.add(
                    t0 + pd.Timedelta(hours=p.mule_hours * 0.6 + float(rng.uniform(1, p.mule_hours * 0.4))),
                    c,
                    "debit",
                    total * share / outs,
                    "IMPS",
                    f"H{c}{k}",
                    _name(rng),
                )
    ring_members = planted["round_trip"]
    for r in range(p.counts["round_trip"]):
        ring = ring_members[r * p.ring_size : (r + 1) * p.ring_size]
        for _ in range(2):
            t = b.when(START, END - pd.Timedelta(days=8))
            amt = rng.uniform(5e5, 1.5e6)
            for k, a in enumerate(ring):
                nxt = ring[(k + 1) % len(ring)]
                t = t + pd.Timedelta(hours=float(rng.uniform(6, 30)))
                b.add(
                    t,
                    a,
                    "debit",
                    amt,
                    "RTGS",
                    nxt,
                    C.loc[C.customer_id == nxt, "name"].item(),
                    narration="advance",
                )
                b.add(
                    t,
                    nxt,
                    "credit",
                    amt,
                    "RTGS",
                    a,
                    C.loc[C.customer_id == a, "name"].item(),
                    narration="advance",
                )
                amt *= rng.uniform(0.95, 0.995)
    for c in planted["dormant"]:
        t0 = b.when(START + pd.Timedelta(days=20), END - pd.Timedelta(days=30))
        for _ in range(int(rng.integers(2, 5))):
            b.add(
                t0 + pd.Timedelta(days=float(rng.uniform(0, 18))),
                c,
                "credit",
                rng.uniform(1e5, 3.5e5),
                rng.choice(["IMPS", "NEFT"]),
                f"D{int(rng.integers(1e6))}",
                _name(rng),
            )
        b.add(
            t0 + pd.Timedelta(days=21),
            c,
            "debit",
            rng.uniform(2e5, 6e5),
            "CASH",
            "BRANCH",
            "cash withdrawal",
        )
    for c in planted["income_mismatch"]:
        quarterly = max(inc[c], 1.2e5) / 4
        total = quarterly * rng.uniform(*p.mismatch_x)
        n = int(rng.integers(4, 10))
        t0 = b.when(START, END - pd.Timedelta(days=80))
        for part in rng.dirichlet(np.ones(n)) * total:
            b.add(
                t0 + pd.Timedelta(days=float(rng.uniform(0, 75))),
                c,
                "credit",
                part,
                "NEFT",
                f"Q{int(rng.integers(1e6))}",
                _name(rng),
            )
    for c in planted["high_risk_geo"]:
        for _ in range(int(rng.integers(1, 3))):
            b.add(
                b.when(),
                c,
                "debit",
                rng.uniform(1.5e5, 2.5e6),
                "SWIFT",
                f"F{int(rng.integers(1e5))}",
                "Trading LLC",
                str(rng.choice(HIGH_RISK)),
            )
    variants = list(p.watch_variants.values())
    for k, c in enumerate(planted["watchlist"]):
        b.add(
            b.when(),
            c,
            str(rng.choice(["debit", "credit"])),
            rng.uniform(2e4, 5e5),
            "IMPS",
            f"W{k}",
            variants[k % len(variants)],
        )
    # honest look-alike names (must NOT match)
    for name in [
        "Mohammed Arif Khanna",
        "Rajesh Kumar Tripathi",
        "Abdul Rahman",
        "Sunil Pawar",
        "Yusuf Merchant Traders",
        "Narayan Meena",
    ]:
        c = str(rng.choice([x for x in ids if x not in truth]))
        b.add(b.when(), c, "debit", rng.uniform(5e3, 8e4), "UPI", f"L{name[:3]}", name)

    T = pd.DataFrame(
        b.rows,
        columns=[
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
        ],
    )
    T = T[(T.ts >= START) & (T.ts <= END)].sort_values("ts").reset_index(drop=True)
    return C, T, truth


def dataset(which: str = "dev"):
    if which == "dev":
        return generate(Profile(), seed=7)
    return generate(held_out_profile(), seed=8)
