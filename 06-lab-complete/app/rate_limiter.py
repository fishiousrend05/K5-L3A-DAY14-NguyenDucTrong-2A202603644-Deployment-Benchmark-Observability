"""
Rate limiting (tiêu chí 7) — sliding window 60s lưu trên Redis.
"""
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 60

# Fallback chỉ dùng khi chạy standalone không có Redis
_local_windows: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{key}"

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, current_count = pipe.execute()

            if current_count >= limit:
                oldest = r.zrange(redis_key, 0, 0, withscores=True)
                retry_after = WINDOW_SECONDS
                if oldest:
                    retry_after = max(1, int(WINDOW_SECONDS - (now - oldest[0][1])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()
            return
        except HTTPException:
            raise
        except RedisError as exc:
            logger.warning("redis_rate_limit_fallback", extra={"error": str(exc)})

    # Fallback local khi Redis không kết nối được
    dq = _local_windows[key]
    while dq and dq[0] <= window_start:
        dq.popleft()
    if len(dq) >= limit:
        retry_after = max(1, int(WINDOW_SECONDS - (now - dq[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    dq.append(now)