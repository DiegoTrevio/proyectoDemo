"""Rate Limiter — Redis-based sliding window rate limiting per tenant.

Applies rate limits per API key/tenant on ingest and dashboard endpoints.
Returns 429 Too Many Requests when limit exceeded.
"""

import logging
import time

import redis.asyncio as aioredis
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import settings

logger = logging.getLogger("agentos.middleware.rate_limiter")

# Default rate limits (requests per minute)
RATE_LIMITS = {
    "/api/v1/ingest": 1000,
    "/api/v1/dashboard": 100,
    "/api/v1/keys": 30,
}

# Paths that are exempt from rate limiting
EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/api/v1/health/ingest"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter using Redis."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip exempt paths
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # Find matching rate limit
        limit = None
        for prefix, max_requests in RATE_LIMITS.items():
            if path.startswith(prefix):
                limit = max_requests
                break

        if limit is None:
            return await call_next(request)

        # Extract identifier (API key from Authorization header, or IP)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            identifier = auth[7:][:16]  # Use first 16 chars of key as identifier
        else:
            identifier = request.client.host if request.client else "unknown"

        # Check rate limit
        allowed, remaining, retry_after = await self._check_rate(identifier, path, limit)

        if not allowed:
            logger.warning(
                "Rate limit exceeded: %s on %s (%d/%d per minute)",
                identifier[:8], path, 0, limit,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": f"Rate limit of {limit} requests per minute exceeded",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    async def _check_rate(
        self,
        identifier: str,
        path_prefix: str,
        limit: int,
        window: int = 60,
    ) -> tuple[bool, int, int]:
        """Check rate limit using Redis sliding window.

        Returns (allowed, remaining, retry_after_seconds).
        """
        try:
            r = aioredis.from_url(settings.redis_url)
            try:
                now = time.time()
                key = f"ratelimit:{identifier}:{path_prefix}"

                pipe = r.pipeline()
                # Remove entries outside the window
                pipe.zremrangebyscore(key, 0, now - window)
                # Count current entries
                pipe.zcard(key)
                # Add current request
                pipe.zadd(key, {f"{now}": now})
                # Set TTL on the key
                pipe.expire(key, window + 10)
                results = await pipe.execute()

                current_count = results[1]

                if current_count >= limit:
                    # Calculate retry-after
                    oldest = await r.zrange(key, 0, 0, withscores=True)
                    if oldest:
                        retry_after = int(window - (now - oldest[0][1])) + 1
                    else:
                        retry_after = window
                    return False, 0, max(1, retry_after)

                remaining = limit - current_count - 1
                return True, max(0, remaining), 0
            finally:
                await r.close()
        except Exception as e:
            # If Redis is down, allow the request (fail open)
            logger.error("Rate limiter Redis error: %s — allowing request", e)
            return True, limit, 0
