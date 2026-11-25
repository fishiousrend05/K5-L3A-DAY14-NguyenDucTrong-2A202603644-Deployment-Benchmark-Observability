"""
Production AI Agent — Part 6 Final Project.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import sys
import time
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    _SKIP_FIELDS = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in self._SKIP_FIELDS and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        extra={"environment": settings.environment, "port": settings.port},
    )
    yield
    logger.info("shutdown", extra={"environment": settings.environment})
    close_redis()


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_exception",
        extra={"path": request.url.path, "method": request.method, "error": str(exc)},
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": elapsed_ms,
        },
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    if not redis_healthy():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "redis": "disconnected"},
        )
    return {"status": "ready", "redis": "connected"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    raw_result = llm_ask(body.question)
    if isinstance(raw_result, dict):
        answer = raw_result.get("answer") or raw_result.get("response") or str(raw_result)
        input_tokens = int(raw_result.get("input_tokens") or _estimate_tokens(body.question))
        output_tokens = int(raw_result.get("output_tokens") or _estimate_tokens(answer))
    else:
        answer = str(raw_result)
        input_tokens = _estimate_tokens(body.question)
        output_tokens = _estimate_tokens(answer)

    cost = record_cost(input_tokens, output_tokens)
    logger.info(
        "ask_completed",
        extra={
            "user_id": body.user_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        },
    )
    return {
        "question": body.question,
        "answer": answer,
        "cost_usd": round(cost, 6),
    }