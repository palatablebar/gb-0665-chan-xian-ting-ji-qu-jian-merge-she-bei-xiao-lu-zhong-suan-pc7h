from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.config import TITLE
from app.errors import DomainError,status_for
from app.web import router as pages
from app.modules.m7_batches.service import run
from app.store import history
@asynccontextmanager
async def lifespan(app):
    # 仅在空库时装入演示样例；已登记版本的重启不得改写现用或复活归档版本。
    if not history():run({"sample":"dirty"})
    yield
app=FastAPI(title=TITLE,lifespan=lifespan)
app.mount("/static",StaticFiles(directory="app/static"),name="static")
app.include_router(pages)
@app.exception_handler(DomainError)
async def error(request,exc):
    return JSONResponse({"code":exc.code,"message":str(exc)},status_code=status_for(exc.code))
@app.get("/health")
def health():return {"status":"ok"}
from app.modules.m1_intake.handler import router as route1
app.include_router(route1)
from app.modules.m2_contract.handler import router as route2
app.include_router(route2)
from app.modules.m3_model.handler import router as route3
app.include_router(route3)
from app.modules.m4_calculate.handler import router as route4
app.include_router(route4)
from app.modules.m5_quarantine.handler import router as route5
app.include_router(route5)
from app.modules.m6_reconcile.handler import router as route6
app.include_router(route6)
from app.modules.m7_batches.handler import router as route7
app.include_router(route7)
