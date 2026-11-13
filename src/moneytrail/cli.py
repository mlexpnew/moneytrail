"""Command line.

moneytrail scan customers.csv transactions.csv --out cases.xlsx
moneytrail demo --out demo/          # write a sample book (customers + transactions)
moneytrail bench                     # run the benchmark
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .cases import build_cases, cbwtr, ctr, str_draft
from .detect import Rules, run_all
from .io import load_customers, load_transactions


def scan(C: pd.DataFrame, T: pd.DataFrame, watchlist: list[str] | None = None):
    alerts = run_all(T, C, Rules(watchlist=watchlist or []))
    return alerts, build_cases(alerts, C)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="moneytrail")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("customers")
    s.add_argument("transactions")
    s.add_argument("--watchlist", help="text file, one name per line")
    s.add_argument("--out", default="moneytrail_cases.xlsx")
    d = sub.add_parser("demo")
    d.add_argument("--out", default="demo")
    sub.add_parser("bench")
    a = ap.parse_args(argv)
    if a.cmd == "bench":
        from .evaluate import main as bench

        return bench([])
    if a.cmd == "demo":
        from .synth import dataset

        C, T, _ = dataset("dev")
        Path(a.out).mkdir(parents=True, exist_ok=True)
        C.to_csv(Path(a.out) / "customers.csv", index=False)
        T.to_csv(Path(a.out) / "transactions.csv", index=False)
        print(f"wrote {len(C):,} customers and {len(T):,} transactions to {a.out}/")
        return 0
    C, T = load_customers(a.customers), load_transactions(a.transactions)
    wl = Path(a.watchlist).read_text().splitlines() if a.watchlist else []
    alerts, cases = scan(C, T, wl)
    with pd.ExcelWriter(a.out) as xw:
        pd.DataFrame(
            [{**c.as_dict(), "typologies": ", ".join(c.typologies), "alerts": len(c.alerts)} for c in cases]
        ).to_excel(xw, sheet_name="Case queue", index=False)
        pd.DataFrame([x.as_dict() | {"txn_ids": ", ".join(x.txn_ids)} for x in alerts]).to_excel(
            xw, sheet_name="Alerts", index=False
        )
        ctr(T).to_excel(xw, sheet_name="CTR", index=False)
        cbwtr(T).to_excel(xw, sheet_name="Cross-border", index=False)
        if cases:
            pd.DataFrame({"Draft STR (top case)": str_draft(cases[0], T).splitlines()}).to_excel(
                xw, sheet_name="Draft STR", index=False
            )
    print(f"{len(T):,} transactions, {len(alerts)} alerts, {len(cases)} cases -> {a.out}")
    for c in cases[:10]:
        print(f"  {c.score:5.1f}  {c.customer_id}  {c.name:<22} {', '.join(c.typologies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
