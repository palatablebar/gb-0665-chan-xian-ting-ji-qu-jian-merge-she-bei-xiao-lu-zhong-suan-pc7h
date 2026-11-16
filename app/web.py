from fastapi import APIRouter,Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.config import TITLE,MODULES,RULE_VERSION
from app.modules.m7_batches.service import run
from app.store import fetch,overview,latest_adopted
from app.versioning import source_records
router=APIRouter();templates=Jinja2Templates(directory="app/templates")
@router.get("/")
def home():return RedirectResponse("/calculate")
def page(request,slug,run_id):
    if run_id:data=fetch(run_id)
    else:
        adopted=latest_adopted()
        data=fetch(adopted) if adopted else run({"sample":"dirty"})
    data["versions"]=overview(data["manifest"]["run_id"])
    data["source_records"]=source_records(data)
    return templates.TemplateResponse(request=request,name=slug+".html",context={"data":data,"title":TITLE,"modules":MODULES,"slug":slug,"page_title":dict(MODULES)[slug],"version":RULE_VERSION})
for slug,label in MODULES:
    def view(request:Request,run_id:str|None=None,_slug=slug):return page(request,_slug,run_id)
    router.add_api_route("/"+slug,view,methods=["GET"],include_in_schema=False)
