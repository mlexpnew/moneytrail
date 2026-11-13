from pathlib import Path

import pytest

from moneytrail.evaluate import run


def test_dev_benchmark():
    r = run("dev")
    m, b = r["moneytrail"], r["threshold_rules"]
    assert m["caught_with_right_reason"] == r["suspicious_planted"]
    assert m["alerts"] < b["alerts"] / 100 and m["precision"] > 10 * b["precision"]


def test_api(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    from moneytrail.api import app
    from moneytrail.synth import WATCHLIST, dataset

    C, T, _ = dataset("dev")
    c = TestClient(app)
    files = {
        "customers": ("c.csv", C.to_csv(index=False)),
        "transactions": ("t.csv", T.to_csv(index=False)),
        "watchlist": ("w.txt", "\n".join(WATCHLIST)),
    }
    r = c.post("/v1/scan", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    top = body["cases"][0]["customer_id"]
    assert c.get(f"/v1/scan/{body['id']}/str/{top}").json()["draft"].startswith("Customer:")
    assert len(c.get(f"/v1/scan/{body['id']}/ctr").json()) == body["ctr_rows"]


def test_dashboard():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=180).run()
    assert not at.exception
