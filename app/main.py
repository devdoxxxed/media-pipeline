from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.database import Base, engine
from app.logging_config import setup_logging
from app.worker import start_worker
from app.routes import upload, results

logger = setup_logging()

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Intelligent Media Processing Pipeline",
    description="Async image intake + analysis service for vehicle photo uploads.",
    version="1.0.0",
)

app.include_router(upload.router, tags=["upload"])
app.include_router(results.router, tags=["results"])


@app.on_event("startup")
def on_startup():
    start_worker()
    logger.info("Application startup complete")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    return {"status": "ok"}
