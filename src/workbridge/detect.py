"""Typology detectors. Each alert names the pattern, the customer, the window and the exact
transactions behind it, so an analyst can confirm or close it in minutes.

Typologies follow common FIU-IND and FATF red flags; thresholds live in `Rules`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np
import pandas as pd


@dataclass
class Rules:
    struct_band: tuple = (40_000, 50_000)  # cash just under the ₹50,000 PAN requirement
    struct_min: int = 3
    struct_days: int = 7
    ctr_limit: float = 1_000_000  # CTR: cash of ₹10 lakh or more in a month
    ctr_near: float = 0.85  # monthly cash between 85% and 100% of the limit ...
    ctr_min_deposits: int = 4  # ... spread over several deposits
    mule_hours: int = 48
    mule_senders: int = 8
    mule_min_in: float = 50_000
    mule_out_share: float = 0.75
    mule_max_receivers: int = 3
    ring_min: float = 100_000
    ring_days: int = 10
    ring_tolerance: float = 0.15
    dormant_days: int = 365
    dormant_min_credit: float = 200_000
    mismatch_days: int = 90
    mismatch_x: float = 3.0
    mismatch_min: float = 200_000
    high_risk: list = field(default_factory=lambda: ["Iran", "North Korea", "Myanmar"])
    watchlist: list = field(default_factory=list)
    watch_score: float = 0.86


@dataclass
class Alert:
    typology: str
    customer_id: str
    start: str
    end: str
    amount: float
    txn_ids: list[str]
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__


def _alert(typ, cid, rows: pd.DataFrame, reason) -> Alert:
    return Alert(
        typ,
        cid,
        str(rows.ts.min()),
        str(rows.ts.max()),
        round(float(rows.amount.sum()), 2),
        rows.txn_id.tolist(),
        reason,
    )


def inr(x: float) -> str:
    return f"₹{x / 1e5:.1f} lakh" if x >= 1e5 else f"₹{x:,.0f}"


# -- cash ------------------------------------------------------------------------------
def structuring(T: pd.DataFrame, r: Rules) -> list[Alert]:
    lo, hi = r.struct_band
    cash = T[(T.channel == "CASH") & (T.direction == "credit") & (T.amount >= lo) & (T.amount < hi)]
    out = []
    for cid, g in cash.groupby("customer_id"):
        g = g.sort_values("ts")
        ts = g.ts.to_numpy()
        i, used = 0, set()
        for j in range(len(g)):
            while ts[j] - ts[i] > np.timedelta64(r.struct_days, "D"):
                i += 1
            win = g.iloc[i : j + 1]
            if len(win) >= r.struct_min and not used & set(win.txn_id):
                used |= set(win.txn_id)
                out.append(
                    _alert(
                        "structuring",
                        cid,
                        win,
                        f"{len(win)} cash deposits of {inr(lo)} to {inr(hi)} within "
                        f"{r.struct_days} days, just under the ₹50,000 PAN requirement",
                    )
                )
    return out


def ctr_avoidance(T: pd.DataFrame, r: Rules) -> list[Alert]:
    """A month of cash just under the CTR limit that is unusual for this customer: at least
    three times their usual monthly cash. A shop that deposits ₹9 lakh every month is not
    hiding anything."""
    cash = T[(T.channel == "CASH") & (T.direction == "credit")].copy()
    cash["month"] = cash.ts.dt.to_period("M")
    monthly = cash.groupby(["customer_id", "month"]).amount.agg(["sum", "count"]).reset_index()
    out = []
    for cid, g in monthly.groupby("customer_id"):
        for row in g.itertuples():
            if not (r.ctr_near * r.ctr_limit <= row.sum < r.ctr_limit and row.count >= r.ctr_min_deposits):
                continue
            others = g[g.month != row.month]["sum"]
            usual = float(others.median()) if len(others) else 0.0
            if row.sum >= 3 * usual:
                rows = cash[(cash.customer_id == cid) & (cash.month == row.month)]
                out.append(
                    _alert(
                        "ctr_avoidance",
                        cid,
                        rows,
                        f"{row.count} cash deposits totalling {inr(row.sum)} in {row.month}, "
                        f"just under the ₹10 lakh cash transaction report limit; usual month "
                        f"{inr(usual)}",
                    )
                )
    return out


# -- flows -----------------------------------------------------------------------------
def mule(T: pd.DataFrame, r: Rules) -> list[Alert]:
    """Many unrelated senders in, most of it out to a few accounts within hours."""
    fast = T[T.channel.isin(["UPI", "IMPS", "NEFT"])]
    out = []
    win = np.timedelta64(r.mule_hours, "h")
    extra = np.timedelta64(24, "h")
    for cid, g in fast.groupby("customer_id"):
        ins = g[g.direction == "credit"].sort_values("ts")
        outs = g[g.direction == "debit"].sort_values("ts")
        if outs.empty or ins.counterparty_id.nunique() < r.mule_senders:
            continue
        ti, ai = ins.ts.to_numpy(), ins.amount.to_numpy()
        to, ao = outs.ts.to_numpy(), outs.amount.to_numpy()
        ci, co = np.concatenate([[0], np.cumsum(ai)]), np.concatenate([[0], np.cumsum(ao)])
        senders = ins.counterparty_id.to_numpy()
        i, n = 0, len(ti)
        while i < n:
            j = np.searchsorted(ti, ti[i] + win)
            got = ci[j] - ci[i]
            a, b = np.searchsorted(to, ti[i]), np.searchsorted(to, ti[i] + win + extra)
            left = co[b] - co[a]
            if (
                j - i >= r.mule_senders
                and got >= r.mule_min_in
                and left >= r.mule_out_share * got
                and len(set(senders[i:j])) >= r.mule_senders
            ):
                w_out = outs.iloc[a:b]
                per = w_out.groupby("counterparty_id").amount.sum().sort_values(ascending=False)
                top = per.head(r.mule_max_receivers)
                if top.sum() >= r.mule_out_share * got:  # a few accounts took most of it
                    w_out = w_out[w_out.counterparty_id.isin(top.index)]
                    rows = pd.concat([ins.iloc[i:j], w_out])
                    out.append(
                        _alert(
                            "mule",
                            cid,
                            rows,
                            f"{len(set(senders[i:j]))} senders paid in {inr(got)}; "
                            f"{top.sum() / got:.0%} left for {len(top)} "
                            f"account(s) within hours",
                        )
                    )
                    i = j
                    continue
            i += 1
    return out


def round_trip(T: pd.DataFrame, r: Rules, customers: set[str]) -> list[Alert]:
    """Money that travels through other customers of ours and comes back (A→B→C→A)."""
    edges = T[(T.direction == "debit") & (T.amount >= r.ring_min) & T.counterparty_id.isin(customers)]
    by_src: dict[str, list] = {}
    for row in edges.itertuples():
        by_src.setdefault(row.customer_id, []).append(row)
    out, seen = [], set()
    limit = pd.Timedelta(days=r.ring_days)

    def walk(origin, node, path, t_last, t_first, amt0):
        for e in by_src.get(node, []):
            if e.ts <= t_last or e.ts - t_first > limit:
                continue
            if abs(e.amount / amt0 - 1) > r.ring_tolerance:
                continue
            if e.counterparty_id == origin and len(path) >= 2:
                key = frozenset(x.txn_id for x in path + [e])
                if key not in seen:
                    seen.add(key)
                    yield path + [e]
            elif e.counterparty_id not in {x.customer_id for x in path} and len(path) < 4:
                yield from walk(origin, e.counterparty_id, path + [e], e.ts, t_first, amt0)

    for src, es in by_src.items():
        for e in es:
            for cycle in walk(src, e.counterparty_id, [e], e.ts, e.ts, e.amount):
                rows = edges[edges.txn_id.isin([x.txn_id for x in cycle])]
                names = " → ".join([cycle[0].customer_id] + [x.counterparty_id for x in cycle])
                for member in {x.customer_id for x in cycle}:
                    out.append(
                        _alert(
                            "round_trip",
                            member,
                            rows,
                            f"funds of about {inr(e.amount)} went round {names} within {r.ring_days} days",
                        )
                    )
    return out


# -- profile ---------------------------------------------------------------------------
def dormant(T: pd.DataFrame, C: pd.DataFrame, r: Rules) -> list[Alert]:
    last = dict(zip(C.customer_id, pd.to_datetime(C.last_active_before), strict=True))
    out = []
    for cid, g in T.groupby("customer_id"):
        first = g.ts.min()
        if cid in last and (first - last[cid]).days >= r.dormant_days:
            cr = g[(g.direction == "credit") & (g.ts < first + pd.Timedelta(days=30))]
            if cr.amount.sum() >= r.dormant_min_credit:
                out.append(
                    _alert(
                        "dormant",
                        cid,
                        cr,
                        f"inactive for {(first - last[cid]).days} days, then "
                        f"{inr(cr.amount.sum())} credited within 30 days",
                    )
                )
    return out


def income_mismatch(T: pd.DataFrame, C: pd.DataFrame, r: Rules) -> list[Alert]:
    inc = dict(zip(C.customer_id, C.declared_income, strict=True))
    seg = dict(zip(C.customer_id, C.segment, strict=True))
    cr = T[(T.direction == "credit") & (T.channel != "CASH")].copy()
    if "self_transfer" in cr:  # own fixed deposits and own accounts are not income
        cr = cr[~cr.self_transfer.astype(bool)]
    out = []
    for cid, g in cr.groupby("customer_id"):
        if seg.get(cid) in ("business", "trader"):
            continue  # turnover is not income for business and shop accounts
        expected = max(inc.get(cid, 0), 120_000) * r.mismatch_days / 365
        s = g.set_index("ts").amount.rolling(f"{r.mismatch_days}D").sum()
        if s.empty or s.max() < max(r.mismatch_min, r.mismatch_x * expected):
            continue
        end = s.idxmax()
        rows = g[(g.ts > end - pd.Timedelta(days=r.mismatch_days)) & (g.ts <= end)]
        out.append(
            _alert(
                "income_mismatch",
                cid,
                rows,
                f"{inr(s.max())} credited in {r.mismatch_days} days, "
                f"{s.max() / expected:.1f}x what the declared income of "
                f"{inr(inc.get(cid, 0))} a year suggests",
            )
        )
    return out


def high_risk_geo(T: pd.DataFrame, r: Rules) -> list[Alert]:
    x = T[T.country.isin(r.high_risk)]
    return [
        _alert(
            "high_risk_geo",
            cid,
            g,
            f"{len(g)} transfer(s) of {inr(g.amount.sum())} with "
            f"{', '.join(sorted(set(g.country)))} (FATF high-risk list)",
        )
        for cid, g in x.groupby("customer_id")
    ]


# -- names -----------------------------------------------------------------------------
ALIASES = {
    "mohd": "mohammed",
    "md": "mohammed",
    "mohammad": "mohammed",
    "muhammad": "mohammed",
    "rehman": "rahman",
}  # common transliterations
HONORIFIC = {"mr", "mrs", "ms", "dr", "shri", "smt", "sri"}


def norm_name(s: str) -> list[str]:
    toks = re.findall(r"[a-z]+", str(s).lower())
    return [ALIASES.get(t, t) for t in toks if t not in HONORIFIC]


def _tok(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:  # an initial
        return 0.9 if a[0] == b[0] else 0.0
    return SequenceMatcher(None, a, b).ratio()


def name_score(candidate: str, listed: str, token_min: float = 0.85) -> float:
    """Every token of the listed name must be found in the candidate (any order; initials
    and joined names such as 'Narayanlal' allowed; at most one extra candidate token).
    A missing or clearly different token (Khan vs Khanna) means no match."""
    c, w = norm_name(candidate), norm_name(listed)
    if not c or not w:
        return 0.0
    for k in range(len(w) - 1):  # joined form of two listed tokens
        joined = w[k] + w[k + 1]
        if joined in c:
            c = [t for t in c if t != joined] + [w[k], w[k + 1]]
    if len(c) > len(w) + 1:
        return 0.0
    used, scores = set(), []
    for t in w:
        best, idx = 0.0, None
        for i, x in enumerate(c):
            if i not in used and _tok(t, x) > best:
                best, idx = _tok(t, x), i
        if best < token_min:
            return 0.0
        used.add(idx)
        scores.append(best)
    return sum(scores) / len(scores)


def watchlist(T: pd.DataFrame, r: Rules) -> list[Alert]:
    if not r.watchlist:
        return []
    out = []
    names = T[["counterparty_name"]].drop_duplicates()
    for name in names.counterparty_name:
        best = max(r.watchlist, key=lambda w: name_score(name, w))
        sc = name_score(name, best)
        if sc >= r.watch_score:
            for cid, g in T[T.counterparty_name == name].groupby("customer_id"):
                out.append(
                    _alert(
                        "watchlist",
                        cid,
                        g,
                        f"counterparty '{name}' matches watchlist entry '{best}' ({sc:.0%})",
                    )
                )
    return out


def run_all(T: pd.DataFrame, C: pd.DataFrame, r: Rules | None = None) -> list[Alert]:
    r = r or Rules()
    T = T.copy()
    T["ts"] = pd.to_datetime(T.ts)
    T["channel"] = T.channel.astype(str)
    T["country"] = T.country.astype(str)
    return (
        structuring(T, r)
        + ctr_avoidance(T, r)
        + mule(T, r)
        + round_trip(T, r, set(C.customer_id))
        + dormant(T, C, r)
        + income_mismatch(T, C, r)
        + high_risk_geo(T, r)
        + watchlist(T, r)
    )
