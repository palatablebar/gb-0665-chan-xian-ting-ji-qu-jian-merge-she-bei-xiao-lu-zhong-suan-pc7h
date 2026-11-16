import json,sqlite3,time
from contextlib import contextmanager
from app.config import data_dir
from app.errors import reject
from app.versioning import shift_keys,scope_of,changes,source_records
ACTIVE="现用";PENDING="待生效";REPLACED="已替换";WITHDRAWN="已撤回";ARCHIVED=(REPLACED,WITHDRAWN)
SCHEMA=(
 "CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,run_id TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核',state TEXT NOT NULL,created_at TEXT NOT NULL,adopted_at TEXT,keys TEXT NOT NULL DEFAULT '[]',UNIQUE(scope,run_id))",
 "CREATE UNIQUE INDEX IF NOT EXISTS versions_active ON versions(scope) WHERE state='现用'",
 "CREATE UNIQUE INDEX IF NOT EXISTS versions_pending ON versions(scope) WHERE state='待生效'",
)
# 同一组班次的后续提交才并入既有版本谱系：与已有版本按班次键比较，重合度达到半数（Jaccard）。
# 仅覆盖少量班次的文件另立一组，不会被误当成整批修订。
OVERLAP=0.5
def now():return time.strftime("%Y-%m-%dT%H:%M:%S%z")
def _columns(c,table):return {x["name"] for x in c.execute(f"PRAGMA table_info({table})")}
def _migrate(c):
    # 旧库的 runs 直接复用：先补列，再按内容归组为现用版本，最后移除旧的内联版本字段。
    columns=_columns(c,"runs")
    if not columns:
        c.execute("CREATE TABLE runs (id TEXT PRIMARY KEY,digest TEXT UNIQUE,body TEXT NOT NULL,created_at TEXT)")
        columns=_columns(c,"runs")
    if "created_at" not in columns:c.execute("ALTER TABLE runs ADD COLUMN created_at TEXT")
    if "keys" not in _columns(c,"versions"):c.execute("ALTER TABLE versions ADD COLUMN keys TEXT NOT NULL DEFAULT '[]'")
    if {"revision","decision"}<=columns:
        for row in c.execute("SELECT id,body,revision,decision FROM runs ORDER BY rowid").fetchall():
            if c.execute("SELECT 1 FROM versions WHERE run_id=?",(row["id"],)).fetchone():continue
            result=json.loads(row["body"]);scope=scope_of(result);created=result.get("manifest",{}).get("created_at") or now()
            c.execute("UPDATE versions SET state=? WHERE scope=? AND state=?",(REPLACED,scope,ACTIVE))
            c.execute("INSERT OR IGNORE INTO versions(scope,run_id,revision,decision,state,created_at,adopted_at,keys) VALUES(?,?,?,?,?,?,?,?)",(scope,row["id"],row["revision"],row["decision"],ACTIVE,created,created,json.dumps(sorted(shift_keys(result)),ensure_ascii=False)))
        try:c.execute("ALTER TABLE runs DROP COLUMN revision");c.execute("ALTER TABLE runs DROP COLUMN decision")
        except sqlite3.Error:pass
    c.execute("UPDATE runs SET created_at=(SELECT created_at FROM versions WHERE versions.run_id=runs.id) WHERE created_at IS NULL")
_READY=set()
def _prepare(c,path):
    """建表与旧库迁移只做一次，且自成事务，避免与业务写入交错。"""
    if path in _READY:return
    c.execute("BEGIN IMMEDIATE")
    try:
        for statement in SCHEMA:c.execute(statement)
        _migrate(c)
        c.commit()
    except Exception:
        c.rollback();raise
    _READY.add(path)
@contextmanager
def connect(write=False):
    d=data_dir();d.mkdir(parents=True,exist_ok=True)
    path=str(d/"records.sqlite")
    c=sqlite3.connect(path,timeout=20,isolation_level=None)
    c.row_factory=sqlite3.Row
    _prepare(c,path)
    # 写事务先行加锁：登记、复核与切换互斥，避免并发下出现双现用或双待生效。
    # 读事务锁定同一快照，页面不会读到切换进行中的半新半旧状态。
    c.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield c
        if c.in_transaction:c.commit()
    except Exception:
        if c.in_transaction:c.rollback()
        raise
    finally:c.close()
def _summary(row,c=None):
    if row is None:return None
    summary={"run_id":row["run_id"],"scope":row["scope"],"revision":row["revision"],"decision":row["decision"],"state":row["state"],"created_at":row["created_at"],"adopted_at":row["adopted_at"]}
    if c is not None:
        digest=c.execute("SELECT digest FROM runs WHERE id=?",(row["run_id"],)).fetchone()
        summary["sha256"]=digest["digest"] if digest else None
    return summary
def _body(c,run_id):
    row=c.execute("SELECT body FROM runs WHERE id=?",(run_id,)).fetchone()
    return json.loads(row["body"]) if row else None
def _lineage(c,scope):
    return [_summary(x,c) | {"id":x["run_id"]} for x in c.execute("SELECT * FROM versions WHERE scope=? ORDER BY id DESC",(scope,))]
def _resolve_scope(c,result):
    """同一组班次的后续提交并入既有谱系；无法归并时才另立一组。"""
    keys=set(shift_keys(result));own=scope_of(result)
    if c.execute("SELECT 1 FROM versions WHERE scope=?",(own,)).fetchone():return own,keys
    best=None;best_ratio=0.0
    for row in c.execute("SELECT scope,keys FROM versions GROUP BY scope"):
        known={tuple(x) for x in json.loads(row["keys"] or "[]")}
        if not known or not keys:continue
        union=len(keys|known);ratio=len(keys&known)/union if union else 0.0
        if ratio>=OVERLAP and ratio>best_ratio:best,best_ratio=row["scope"],ratio
    return (best or own),keys
def _fetch(c,run_id):
    body=_body(c,run_id)
    if body is None:reject("NOT_FOUND","运行不存在")
    version=c.execute("SELECT * FROM versions WHERE run_id=?",(run_id,)).fetchone()
    if version is None:body.update(revision=1,decision="待复核",state=None,scope=None,version_created_at=None,adopted_at=None)
    else:body.update(revision=version["revision"],decision=version["decision"],state=version["state"],scope=version["scope"],version_created_at=version["created_at"],adopted_at=version["adopted_at"])
    return body
def save(result):
    """登记一次运行。首次出现的班次组立即现用；同组后续内容一律登记为待生效，绝不改写已有版本。"""
    m=result["manifest"];stamp=now()
    with connect(write=True) as c:
        c.execute("INSERT OR IGNORE INTO runs(id,digest,body,created_at) VALUES(?,?,?,?)",(m["run_id"],m["sha256"],json.dumps(result,ensure_ascii=False),m.get("created_at") or stamp))
        if c.execute("SELECT 1 FROM versions WHERE run_id=?",(m["run_id"],)).fetchone():
            # 已登记的版本原样返回：查看或重跑相同内容不得复活失效版本，也不得新增重复版本。
            return _fetch(c,m["run_id"])
        scope,keys=_resolve_scope(c,result)
        if not c.execute("SELECT 1 FROM versions WHERE scope=? AND state=?",(scope,ACTIVE)).fetchone():
            c.execute("INSERT INTO versions(scope,run_id,revision,decision,state,created_at,adopted_at,keys) VALUES(?,?,1,'待复核',?,?,?,?)",(scope,m["run_id"],ACTIVE,stamp,stamp,json.dumps(sorted(keys),ensure_ascii=False)))
        else:
            c.execute("UPDATE versions SET state=? WHERE scope=? AND state=?",(WITHDRAWN,scope,PENDING))
            c.execute("INSERT INTO versions(scope,run_id,revision,decision,state,created_at,keys) VALUES(?,?,1,'待复核',?,?,?)",(scope,m["run_id"],PENDING,stamp,json.dumps(sorted(keys),ensure_ascii=False)))
        return _fetch(c,m["run_id"])
def fetch(run_id):
    with connect() as c:return _fetch(c,run_id)
def history():
    with connect() as c:return [_summary(x,c) | {"id":x["run_id"]} for x in c.execute("SELECT * FROM versions ORDER BY id DESC LIMIT 100")]
def lineage(run_id):
    with connect() as c:
        row=c.execute("SELECT scope FROM versions WHERE run_id=?",(run_id,)).fetchone()
        return _lineage(c,row["scope"]) if row else []
def latest_adopted():
    """跨班次组最近生效的版本，供工作台默认打开时定位，无需为浏览写入新版本。"""
    with connect() as c:
        row=c.execute("SELECT run_id FROM versions WHERE state=? ORDER BY adopted_at DESC,id DESC LIMIT 1",(ACTIVE,)).fetchone()
        return row["run_id"] if row else None
def overview(run_id):
    with connect() as c:
        row=c.execute("SELECT * FROM versions WHERE run_id=?",(run_id,)).fetchone()
        if row is None:return {"scope":None,"lineage":[],"adopted":None,"pending":None,"changes":None}
        scope=row["scope"];items=_lineage(c,scope)
        adopted=c.execute("SELECT * FROM versions WHERE scope=? AND state=?",(scope,ACTIVE)).fetchone()
        pending=c.execute("SELECT * FROM versions WHERE scope=? AND state=?",(scope,PENDING)).fetchone()
        delta=None
        if adopted and pending:
            before,after=_body(c,adopted["run_id"]),_body(c,pending["run_id"])
            if before and after:delta=changes(before,after)
        records=source_records(_body(c,adopted["run_id"]) or {}) if adopted else []
        return {"scope":scope,"lineage":items,"adopted":_summary(adopted,c),"pending":_summary(pending,c),"changes":delta,"adopted_records":records}
def adopt(run_id,expect=None,revision=None):
    """原子切换版本为现用。失败整体回滚，旧现用原样保留；重复提交按已达成返回，不新增版本。"""
    with connect(write=True) as c:
        target=c.execute("SELECT * FROM versions WHERE run_id=?",(run_id,)).fetchone()
        if target is None:reject("NOT_FOUND","运行不存在")
        if target["state"]==ACTIVE:return _fetch(c,run_id)
        if target["state"]!=PENDING:reject("STATE","仅待生效版本可切换，已替换/已撤回版本保持归档")
        if revision is not None and revision!=target["revision"]:reject("STALE_VERSION","数据已更新，请重新载入")
        if target["decision"]!="通过":reject("APPROVAL","待生效版本须复核通过后才能切换")
        active=c.execute("SELECT * FROM versions WHERE scope=? AND state=?",(target["scope"],ACTIVE)).fetchone()
        if expect is not None and (active is None or expect!=active["run_id"]):reject("STALE_VERSION","现用版本已变化，请重新载入")
        if active is not None:
            # 切换不得让现用覆盖的班次凭空消失：缺班的修订必须补全后重新提交。
            lost={tuple(x) for x in json.loads(active["keys"] or "[]")}-{tuple(x) for x in json.loads(target["keys"] or "[]")}
            if lost:reject("COVERAGE",f"该版本缺少 {len(lost)} 个现用班次（{'、'.join(f'{a} {b}' for a,b in sorted(lost)[:5])}），切换会丢失记录，未切换")
            c.execute("UPDATE versions SET state=? WHERE id=?",(REPLACED,active["id"]))
        c.execute("UPDATE versions SET state=?,adopted_at=? WHERE id=?",(ACTIVE,now(),target["id"]))
        return _fetch(c,run_id)
def review(run_id,revision,decision):
    if not isinstance(revision,int) or isinstance(revision,bool) or revision<1:reject("VERSION","修订号须为正整数")
    if decision not in ("通过","退回"):reject("DECISION","复核状态无效")
    with connect(write=True) as c:
        row=c.execute("SELECT * FROM versions WHERE run_id=?",(run_id,)).fetchone()
        if row is None:reject("NOT_FOUND","运行不存在")
        if row["state"] in ARCHIVED:reject("LOCKED","该版本已归档，原始依据不可改写")
        changed=c.execute("UPDATE versions SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,row["id"],revision)).rowcount
        if not changed:reject("STALE_VERSION","数据已更新，请重新载入")
        return _fetch(c,run_id)
