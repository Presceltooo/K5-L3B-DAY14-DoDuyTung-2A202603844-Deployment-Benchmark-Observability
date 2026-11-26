"""
Cost guard (tiêu chí 8).

Yêu cầu:
  • Cộng dồn chi phí LLM (tính theo token) vào Redis
  • Tổng chi phí vượt DAILY_BUDGET_USD (hoặc MONTHLY_BUDGET_USD) → HTTP 402
"""
from datetime import date
import logging

from fastapi import HTTPException
import redis

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _budget_key() -> str:
    return f"cost_guard:{date.today().isoformat()}:usd"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    if r is None:
        return

    try:
        raw = r.get(_budget_key())
        spent = float(raw) if raw is not None else 0.0
    except (redis.RedisError, ValueError) as exc:
        logger.warning("Redis error in check_budget: %s", exc)
        return

    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="Daily budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K

    if r is None:
        return cost

    key = _budget_key()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, 86400 * 2)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("Redis error in record_cost: %s", exc)

    return cost
