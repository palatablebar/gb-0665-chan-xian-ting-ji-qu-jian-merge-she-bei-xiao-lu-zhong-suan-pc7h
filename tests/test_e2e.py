from fastapi.testclient import TestClient
from app.main import app
from app.config import MODULES

def test_pages():
    with TestClient(app) as c:
        for slug,label in MODULES:assert c.get("/"+slug).status_code==200
def test_api_and_export():
    with TestClient(app) as c:
        a=c.post("/api/runs",json={"sample":"dirty"}).json();rid=a["manifest"]["run_id"]
        assert c.get(f"/api/runs/{rid}/evidence.csv").status_code==200
        assert a["reconciliation"]["time_ok"] is True
def test_wrong_csv():
    with TestClient(app) as c:assert c.post("/api/runs",json={"text":"a,b\n1,2"}).status_code==422

def test_percentages_in_page():
    with TestClient(app) as c:
        page=c.get("/calculate").text
        assert "83.33%" in page and "63.33%" in page
        assert "0.833333333333" not in page.split("title=",1)[0]

def revised_text():
    import csv,io
    text=open("sample_data/dirty.csv","rb").read().decode("utf-8-sig");lines=text.splitlines();kept=[lines[0]]
    for line in lines[1:]:
        cells=next(csv.reader([line]))
        if cells[0]=="S0601":
            cells[4],cells[5]="310","295"
            buffer=io.StringIO();csv.writer(buffer).writerow(cells);line=buffer.getvalue().strip()
        kept.append(line)
    return "\n".join(kept)

def test_workbench_shows_adopted_and_pending():
    with TestClient(app) as c:
        a=c.post("/api/runs",json={"sample":"dirty"}).json();rid=a["manifest"]["run_id"]
        c.post(f"/api/runs/{rid}/review",json={"revision":1,"decision":"通过"})
        b=c.post("/api/runs",json={"text":revised_text()}).json();bid=b["manifest"]["run_id"]
        assert b["state"]=="待生效"
        page=c.get("/calculate?run_id="+bid).text
        assert "待生效" in page and "RUN "+rid in page
        assert 'id="adopt"' not in page
        c.post(f"/api/runs/{bid}/review",json={"revision":1,"decision":"通过"})
        assert 'id="adopt"' in c.get("/calculate?run_id="+bid).text

def test_adopt_endpoint_keeps_old_on_failure_then_switches():
    with TestClient(app) as c:
        a=c.post("/api/runs",json={"sample":"dirty"}).json();rid=a["manifest"]["run_id"]
        c.post(f"/api/runs/{rid}/review",json={"revision":1,"decision":"通过"})
        bid=c.post("/api/runs",json={"text":revised_text()}).json()["manifest"]["run_id"]
        c.post(f"/api/runs/{bid}/review",json={"revision":1,"decision":"通过"})
        failed=c.post(f"/api/runs/{bid}/adopt",json={"adopted_run_id":"stale"})
        assert failed.status_code==409 and failed.json()["detail"]["code"]=="STALE_VERSION"
        active=c.get("/calculate?run_id="+rid).text
        assert "现用" in active and "待生效" in active  # 现用页同时提示待生效修订
        error=c.get("/api/batches").json()["history"]
        assert {x["run_id"]:x["state"] for x in error}[rid]=="现用"
        assert {x["run_id"]:x["state"] for x in error}[bid]=="待生效"
        ok=c.post(f"/api/runs/{bid}/adopt",json={"adopted_run_id":rid,"revision":2})
        assert ok.status_code==200 and ok.json()["state"]=="现用"
        old=c.get("/calculate?run_id="+rid).text
        assert "归档" in old and 'id="review"' not in old
        assert c.post(f"/api/runs/{bid}/adopt",json={"adopted_run_id":rid,"revision":2}).status_code==200
        history=c.get("/api/batches").json()["history"]
        assert [x["state"] for x in history if x["run_id"]==bid]==["现用"]
