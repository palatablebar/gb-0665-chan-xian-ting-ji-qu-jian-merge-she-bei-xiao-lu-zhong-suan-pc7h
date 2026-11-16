import csv,io,json
from app.errors import reject
def validate(options):
    if set(options)-{"sample","text","params"}:reject("PARAMETER","存在未知运行参数")
    if options.get("sample","dirty") not in {"dirty","clean","gb18030"}:reject("SAMPLE","样例不存在")
    if "text" in options and not isinstance(options["text"],str):reject("CONTENT","文件内容须为文本")
    if not isinstance(options.get("params",{}),dict):reject("PARAMETER","参数须为对象")
    if options.get("params"):reject("PARAMETER","该项目无可调计算参数")
    return options
def csv_evidence(result):
    buffer=io.StringIO();writer=csv.writer(buffer)
    writer.writerow(["运行号","版本状态","修订","来源行","类别","记录号","原因码","原值"])
    rid=result["manifest"]["run_id"];state=result.get("state") or "";revision=result.get("revision") or ""
    for row in result.get("quarantine",[]):writer.writerow([rid,state,revision,row.get("line"),"隔离",row.get("raw",{}).get("record_id",""),row.get("code"),json.dumps(row.get("raw",{}),ensure_ascii=False)])
    for row in result.get("results",[]):writer.writerow([rid,state,revision,row.get("line",""),"结论",row.get("record_id",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    return "﻿"+buffer.getvalue()
