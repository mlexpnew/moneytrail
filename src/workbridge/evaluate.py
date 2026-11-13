"""Benchmark WorkBridge against threshold rules (what this repo used to do).

    python -m workbridge.evaluate --gate

Threshold rules: alert on any transaction over ₹1 lakh and any transfer with a high-risk
country. WorkBridge: typology detectors, one case per customer, ranked by risk.
Scored per customer: suspicious customers caught (with the right reason), honest customers
flagged, alerts an analyst must open, and how many real cases sit in the top of the queue.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from .cases import build_cases, cbwtr, ctr
from .detect import Rules, run_all
from .synth import HIGH_RISK, WATCHLIST, dataset

TOP = 50


def threshold_rules(T: pd.DataFrame) -> tuple[int, list[str]]:
    hit = T[(T.amount > 100_000) | T.country.astype(str).isin(HIGH_RISK)]
    order = hit.groupby("customer_id").agg(n=("txn_id", "count"), amt=("amount", "sum"))
    order = order.sort_values(["n", "amt"], ascending=False)
    return len(hit), order.index.tolist()


def run(which: str) -> dict:
    C, T, truth = dataset(which)
    t0 = time.perf_counter()
    alerts = run_all(T, C, Rules(watchlist=WATCHLIST))
    cases = build_cases(alerts, C)
    secs = time.perf_counter() - t0
    flagged = [c.customer_id for c in cases]
    sus = set(truth)
    right = {c.customer_id for c in cases if c.customer_id in sus and truth[c.customer_id] in c.typologies}
    by_typ = {}
    for typ in sorted(set(truth.values())):
        members = {c for c, t in truth.items() if t == typ}
        by_typ[typ] = {"planted": len(members), "caught_right_reason": len(members & right)}
    fp = Counter(t for c in cases if c.customer_id not in sus for t in c.typologies)
    n_alerts_base, base_order = threshold_rules(T)
    watch_hits = [a for a in alerts if a.typology == "watchlist"]
    return {
        "customers": len(C),
        "transactions": len(T),
        "suspicious_planted": len(sus),
        "workbridge": {
            "alerts": len(alerts),
            "customers_flagged": len(flagged),
            "suspicious_caught": len(sus & set(flagged)),
            "caught_with_right_reason": len(right),
            "honest_flagged": len(set(flagged) - sus),
            "precision": round(len(sus & set(flagged)) / max(len(flagged), 1), 4),
            f"top_{TOP}_real_cases": len(set(flagged[:TOP]) & sus),
            "honest_flagged_by_typology": dict(fp),
            "seconds": round(secs, 1),
        },
        "threshold_rules": {
            "alerts": n_alerts_base,
            "customers_flagged": len(base_order),
            "suspicious_caught": len(sus & set(base_order)),
            "honest_flagged": len(set(base_order) - sus),
            "precision": round(len(sus & set(base_order)) / max(len(base_order), 1), 4),
            f"top_{TOP}_real_cases": len(set(base_order[:TOP]) & sus),
        },
        "by_typology": by_typ,
        "watchlist": {
            "planted": sum(1 for t in truth.values() if t == "watchlist"),
            "true_matches": len({a.customer_id for a in watch_hits if truth.get(a.customer_id) == "watchlist"}),
            "false_matches": len(
                {a.customer_id for a in watch_hits if truth.get(a.customer_id) != "watchlist"}
            ),
        },
        "reports": {"ctr_rows": len(ctr(T)), "cbwtr_rows": len(cbwtr(T))},
    }


def report(r: dict) -> str:
    d, h = r["dev"], r["held_out"]
    rows = []
    for key, label in (
        ("threshold_rules", "Threshold rules (old repo)"),
        ("workbridge", "**WorkBridge**"),
    ):
        a, b = d[key], h[key]
        rows.append(
            f"| {label} | {a['alerts']:,} / {b['alerts']:,} | {a['customers_flagged']:,} / "
            f"{b['customers_flagged']:,} | {a['suspicious_caught']}/{d['suspicious_planted']} / "
            f"{b['suspicious_caught']}/{h['suspicious_planted']} | {a['honest_flagged']:,} / "
            f"{b['honest_flagged']:,} | {a[f'top_{TOP}_real_cases']} / {b[f'top_{TOP}_real_cases']} |"
        )
    typ = [
        "| Typology | Dev: caught (right reason) | Held-out: caught (right reason) |",
        "|---|---|---|",
    ]
    for k in d["by_typology"]:
        a, b = (
            d["by_typology"][k],
            h["by_typology"].get(k, {"planted": 0, "caught_right_reason": 0}),
        )
        typ.append(
            f"| {k.replace('_', ' ')} | {a['caught_right_reason']}/{a['planted']} | "
            f"{b['caught_right_reason']}/{b['planted']} |"
        )
    return (
        "\n".join(
            [
                f"{d['customers']:,} customers, {d['transactions']:,} / {h['transactions']:,} transactions "
                "(dev / held-out), 6 months.",
                "",
                f"| dev / held-out | Alerts to review | Customers flagged | Suspicious caught | "
                f"Honest customers flagged | Real cases in top {TOP} |",
                "|---|---|---|---|---|---|",
                *rows,
                "",
                *typ,
                "",
                f"Watchlist: dev {d['watchlist']['true_matches']}/{d['watchlist']['planted']} matched, "
                f"{d['watchlist']['false_matches']} false; held-out {h['watchlist']['true_matches']}/"
                f"{h['watchlist']['planted']}, {h['watchlist']['false_matches']} false.",
            ]
        )
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark WorkBridge")
    p.add_argument("--out", default="eval_results")
    p.add_argument("--gate", action="store_true")
    a = p.parse_args(argv)
    r = {"dev": run("dev"), "held_out": run("held_out")}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(r, indent=2, default=str))
    md = report(r)
    (out / "report.md").write_text(md)
    print(md)
    if a.gate:
        m = r["dev"]["workbridge"]
        if m["caught_with_right_reason"] < r["dev"]["suspicious_planted"] or m["precision"] < 0.5:
            print("gate failed", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
