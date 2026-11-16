import hashlib,json
from collections import Counter

# 版本谱系：同一组班次（产线+班次日期）的多次提交互为版本。
# 修订先登记为待生效版本，只有显式切换才会改变现用结果。
CHANGE_FIELDS=("line_id","start","end","total","good","ideal_seconds","downtime","breaks")
TOTAL_FIELDS=(("planned","计划 / min"),("runtime","运行 / min"),("downtime","停机 / min"),("total","总产 / 件"),("good","良品 / 件"),("scrap","废品 / 件"))

def shift_keys(result):
    return {(str(row.get("line_id","")),str(row.get("start",""))[:10]) for row in result.get("rows",[])}

def scope_of(result):
    keys=sorted(shift_keys(result))
    material=json.dumps({"shifts":[list(key) for key in keys]},ensure_ascii=False,separators=(",",":"))
    return "G"+hashlib.sha256(material.encode()).hexdigest()[:15]

def source_records(result):
    return [{"record_id":x.get("record_id"),"line_id":x.get("line_id"),"line":x.get("line"),"start":x.get("start"),"end":x.get("end"),"total":x.get("total"),"good":x.get("good"),"ideal_seconds":x.get("ideal_seconds")} for x in result.get("rows",[])]

def _text(value):
    return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(",",":"))

def _text_or_none(value):
    return None if value is None else _text(value)

def changes(adopted,candidate):
    """对比现用版本与待生效版本，只报告变化，不修改任何一侧。"""
    left={str(x.get("record_id")):x for x in adopted.get("rows",[])}
    right={str(x.get("record_id")):x for x in candidate.get("rows",[])}
    changed=[];rows=[]
    for record_id in sorted(set(left)&set(right)):
        fields=[{"name":key,"from":_text(left[record_id].get(key)),"to":_text(right[record_id].get(key))} for key in CHANGE_FIELDS if left[record_id].get(key)!=right[record_id].get(key)]
        if fields:
            changed.append({"record_id":record_id,"fields":fields})
            rows.extend({"record_id":record_id,"field":x["name"],"before":x["from"],"after":x["to"]} for x in fields)
    before_totals=adopted.get("reconciliation") or {}
    after_totals=candidate.get("reconciliation") or {}
    totals=[{"name":label,"before":_text_or_none(before_totals.get(key)),"after":_text_or_none(after_totals.get(key))} for key,label in TOTAL_FIELDS if before_totals.get(key)!=after_totals.get(key)]
    before_reasons=Counter(str(x.get("code")) for x in adopted.get("quarantine",[]))
    after_reasons=Counter(str(x.get("code")) for x in candidate.get("quarantine",[]))
    reasons=[{"code":code,"before":before_reasons.get(code,0),"after":after_reasons.get(code,0)} for code in sorted(set(before_reasons)|set(after_reasons)) if before_reasons.get(code,0)!=after_reasons.get(code,0)]
    return {"changed":changed,"rows":rows,"totals":totals,"reasons":reasons,"missing":sorted(set(left)-set(right)),"added":sorted(set(right)-set(left)),
            "identical":not changed and not totals and not reasons and not (set(left)^set(right))}
