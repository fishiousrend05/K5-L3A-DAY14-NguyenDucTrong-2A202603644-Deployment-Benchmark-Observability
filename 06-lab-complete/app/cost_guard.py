"""
Cost guard (tiêu chí 8) — theo dõi ngân sách LLM trên Redis.
"""
import logging
from datetime import date

from fastapi import HTTPException, status
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_local_spend: dict[str, float] = {}


def _budget_key() -> str:
    return f"cost:daily:{date.today().isoformat()}"


def get_current_spend() -> float:
    key = _budget_key()
    if r is not None:
        try:
            val = r.get(key)
            return float(val) if val is not None else 0.0
        except RedisError as exc:
            logger.warning("redis_cost_read_fallback", extra={"error": str(exc)})
    return _local_spend.get(key, 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    current = get_current_spend()
    if current >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Daily budget exceeded (${current:.6f} / ${settings.daily_budget_usd:.6f})",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    key = _budget_key()
    if r is not None:
        try:
            r.incrbyfloat(key, cost)
            r.expire(key, 86400 * 2)
            return cost
        except RedisError as exc:
            logger.warning("redis_cost_write_fallback", extra={"error": str(exc)})
    _local_spend[key] = _local_spend.get(key, 0.0) + cost
    return cost