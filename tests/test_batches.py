import csv,io,pytest
from app.modules.m7_batches.service import run
from app.modules.m7_batches.rules import csv_evidence
from app.store import review,fetch,history,adopt,overview
from app.errors import DomainError
from app.versioning import changes

def revised(sample="dirty",record_id="S0601",fields=None,drop=()):
    raw=open(f"sample_data/{sample}.csv","rb").read()
    try:text=raw.decode("utf-8-sig")
    except UnicodeDecodeError:text=raw.decode("gb18030")
    lines=text.splitlines();header=next(csv.reader([lines[0]]));kept=[lines[0]]
    for line in lines[1:]:
        cells=next(csv.reader([line]))
        if cells[0] in drop:continue
        if cells[0]==record_id:
            for key,value in (fields or {}).items():cells[header.index(key)]=value
            buffer=io.StringIO();csv.writer(buffer).writerow(cells);line=buffer.getvalue().strip()
        kept.append(line)
    return {"text":"\n".join(kept)}

def test_idempotent(dirty):a=run(dirty);b=run(dirty);assert a["manifest"]["run_id"]==b["manifest"]["run_id"];assert len(history())==1
def test_sample_key(clean,dirty):assert run(clean)["manifest"]["run_id"]!=run(dirty)["manifest"]["run_id"]
def test_review(clean):a=run(clean);assert review(a["manifest"]["run_id"],1,"通过")["revision"]==2
def test_stale(dirty): # TRAP-26
    a=run(dirty);rid=a["manifest"]["run_id"];review(rid,1,"通过")
    with pytest.raises(DomainError):review(rid,1,"退回")
def test_export(dirty):assert "COUNT" in csv_evidence(run(dirty))
def test_exact_saved(clean):a=run(clean);assert fetch(a["manifest"]["run_id"])["reconciliation"]["good"]=="10260"
def test_invalid():
    with pytest.raises(DomainError):run({"unknown":1})

def test_review_rejects_structured_parameters(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"]
    with pytest.raises(DomainError):review(rid,[],"通过")
    with pytest.raises(DomainError):review(rid,1,[])

def test_revision_does_not_replace_active(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"]
    b=run(revised(fields={"total":"310","good":"295"}));bid=b["manifest"]["run_id"]
    assert bid!=rid
    assert b["state"]=="待生效"
    assert fetch(a["manifest"]["run_id"])["state"]=="现用"
    assert fetch(a["manifest"]["run_id"])["reconciliation"]["good"]=="10260"
    assert b["versions"]["adopted"]["run_id"]==rid
    assert b["versions"]["pending"]["run_id"]==bid

def test_original_evidence_immutable_after_adoption(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"];origin=fetch(rid)["reconciliation"]["good"]
    review(rid,1,"通过")
    bid=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"];review(bid,1,"通过")
    adopt(bid,expect=rid,revision=2)
    old=fetch(rid)
    assert old["state"]=="已替换"
    assert old["reconciliation"]["good"]==origin
    assert old["manifest"]["sha256"]==fetch(rid)["manifest"]["sha256"]

def test_adoption_requires_approval(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"]
    b=run(revised(fields={"total":"310","good":"295"}));bid=b["manifest"]["run_id"]
    with pytest.raises(DomainError) as info:adopt(bid,expect=rid)
    assert info.value.code=="APPROVAL"
    assert fetch(rid)["state"]=="现用" and fetch(bid)["state"]=="待生效"

def test_failed_adoption_keeps_old_and_retry_is_idempotent(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"]
    bid=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"];review(bid,1,"通过")
    with pytest.raises(DomainError) as info:adopt(bid,expect="wrong-run")
    assert info.value.code=="STALE_VERSION"
    assert fetch(rid)["state"]=="现用" and fetch(bid)["state"]=="待生效"
    first=adopt(bid,expect=rid,revision=2);assert first["state"]=="现用"
    before=len(history())
    again=adopt(bid,expect=rid,revision=2);assert again["state"]=="现用"
    assert len(history())==before
    assert [x["run_id"] for x in history()].count(bid)==1

def test_new_revision_withdraws_previous_pending(dirty):
    run(dirty)
    first=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"]
    second=run(revised(fields={"total":"311","good":"296"}))
    states={x["run_id"]:x["state"] for x in second["versions"]["lineage"]}
    assert states[first]=="已撤回"
    assert second["versions"]["pending"]["run_id"]==second["manifest"]["run_id"]
    assert len([x for x in second["versions"]["lineage"] if x["state"]=="待生效"])==1

def test_archived_version_cannot_be_reviewed(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"];review(rid,1,"通过")
    bid=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"];review(bid,1,"通过");adopt(bid,expect=rid,revision=2)
    with pytest.raises(DomainError) as info:review(rid,1,"退回")
    assert info.value.code=="LOCKED"

def test_rerun_same_content_does_not_revive_archived(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"];review(rid,1,"通过")
    bid=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"];review(bid,1,"通过");adopt(bid,expect=rid,revision=2)
    again=run(dirty)
    assert again["manifest"]["run_id"]==rid
    assert again["state"]=="已替换"
    assert overview(bid)["pending"] is None

def test_adoption_rejects_missing_shifts(dirty):
    a=run(dirty);rid=a["manifest"]["run_id"];review(rid,1,"通过")
    b=run(revised(drop=("S0602","S0603","S0604","S0605","S0606")));bid=b["manifest"]["run_id"];review(bid,1,"通过")
    with pytest.raises(DomainError) as info:adopt(bid,expect=rid)
    assert info.value.code=="COVERAGE"
    assert fetch(rid)["state"]=="现用" and fetch(bid)["state"]=="待生效"

def test_changes_report_original_values(dirty):
    a=run(dirty);b=run(revised(fields={"total":"310","good":"295"}))
    delta=changes(fetch(a["manifest"]["run_id"]),fetch(b["manifest"]["run_id"]))
    assert delta["identical"] is False
    totals={x["name"]:(x["before"],x["after"]) for x in delta["totals"]}
    assert totals["良品 / 件"]==("10260","10270")
    assert {x["field"] for x in delta["rows"]}=={"total","good"}

def test_adoption_rolls_back_on_midway_failure(dirty,monkeypatch):
    import app.store as store
    a=run(dirty);rid=a["manifest"]["run_id"];review(rid,1,"通过")
    bid=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"];review(bid,1,"通过")
    original=store._fetch
    def explode(*args,**kwargs):raise RuntimeError("boom")
    monkeypatch.setattr(store,"_fetch",explode)
    with pytest.raises(RuntimeError):store.adopt(bid,expect=rid,revision=2)
    monkeypatch.setattr(store,"_fetch",original)
    assert fetch(rid)["state"]=="现用" and fetch(bid)["state"]=="待生效"
    assert fetch(rid)["reconciliation"]["good"]=="10260"

def test_archived_body_bytes_unchanged(dirty):
    import os,sqlite3,json
    from app.config import data_dir
    a=run(dirty);rid=a["manifest"]["run_id"];review(rid,1,"通过")
    before=sqlite3.connect(os.path.join(data_dir(),"records.sqlite")).execute("SELECT body FROM runs WHERE id=?",(rid,)).fetchone()[0]
    bid=run(revised(fields={"total":"310","good":"295"}))["manifest"]["run_id"];review(bid,1,"通过")
    adopt(bid,expect=rid,revision=2)
    after=sqlite3.connect(os.path.join(data_dir(),"records.sqlite")).execute("SELECT body FROM runs WHERE id=?",(rid,)).fetchone()[0]
    assert before==after
    assert json.loads(after)["reconciliation"]["good"]=="10260"
