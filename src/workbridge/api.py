"""HTTP API: upload a day's (or month's) book, get the ranked case queue and reports.

uvicorn workbridge.api:app        # set WORKBRIDGE_API_KEYS to require X-API-Key
"""

from __future__ import annotations

import io
import os
import uuid

import pandas as pd
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

from .cases import build_cases, cbwtr, ctr, str_draft
from .detect import Rules, run_all
from .io import load_customers, load_transactions

app = FastAPI(
    title="WorkBridge",
    version="1.0.0",
    description="AML transaction monitoring with explainable alerts and a ranked case queue.",
)
RUNS: dict[str, dict] = {}


def auth(x_api_key: str | None = Header(default=None)):
    keys = {k.strip() for k in os.getenv("WORKBRIDGE_API_KEYS", "").split(",") if k.strip()}
    if keys and x_api_key not in keys:
        raise HTTPException(401, "missing or invalid X-API-Key")


@app.get("/health")
def health():
    return {"status": "ok", "runs_in_memory": len(RUNS)}


@app.post("/v1/scan", dependencies=[Depends(auth)])
async def scan(
    customers: UploadFile = File(...),
    transactions: UploadFile = File(...),
    watchlist: UploadFile | None = File(None),
):
    try:
        C = load_customers(pd.read_csv(io.BytesIO(await customers.read())))
        T = load_transactions(pd.read_csv(io.BytesIO(await transactions.read())))
        wl = (await watchlist.read()).decode().splitlines() if watchlist else []
    except Exception as e:
        raise HTTPException(422, f"could not read the files: {e}") from e
    alerts = run_all(T, C, Rules(watchlist=[w for w in wl if w.strip()]))
    cases = build_cases(alerts, C)
    rid = uuid.uuid4().hex[:12]
    RUNS[rid] = {"T": T, "cases": cases}
    while len(RUNS) > 20:
        RUNS.pop(next(iter(RUNS)))
    return {
        "id": rid,
        "transactions": len(T),
        "alerts": len(alerts),
        "cases": [c.as_dict() for c in cases[:200]],
        "ctr_rows": len(ctr(T)),
        "cross_border_rows": len(cbwtr(T)),
    }


@app.get("/v1/scan/{rid}/str/{customer_id}", dependencies=[Depends(auth)])
def draft(rid: str, customer_id: str):
    run = RUNS.get(rid)
    case = next((c for c in run["cases"] if c.customer_id == customer_id), None) if run else None
    if case is None:
        raise HTTPException(404, "unknown run or customer")
    return {
        "customer_id": customer_id,
        "draft": str_draft(case, run["T"]),
        "note": "Draft for analyst review; file the STR within 7 working days of concluding it is suspicious.",
    }


@app.get("/v1/scan/{rid}/ctr", dependencies=[Depends(auth)])
def ctr_report(rid: str):
    run = RUNS.get(rid)
    if run is None:
        raise HTTPException(404, "unknown run")
    df = ctr(run["T"])
    df["due_by"] = df["due_by"].astype(str)
    return df.to_dict(orient="records")
