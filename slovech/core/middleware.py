import logging
import time
import uuid
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("http")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; base-uri 'self'; object-src 'none'",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        if request.url.path.startswith(("/api/", "/audio/")):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request id=%s method=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Bounded per-process limiter. Production runs exactly one API worker."""

    def __init__(self, app, max_requests=120, window_seconds=60, max_clients=10000):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window_seconds
        self.max_clients = max_clients
        self.clients = OrderedDict()

    async def dispatch(self, request, call_next):
        if request.url.path in {"/health", "/ready"} or request.url.path.startswith("/static/"):
            return await call_next(request)
        # Uvicorn accepts forwarding headers ONLY from the configured Caddy address.
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        start, count = self.clients.pop(ip, (now, 0))
        if now - start >= self.window:
            start, count = now, 0
        self.clients[ip] = (start, count + 1)
        if len(self.clients) > self.max_clients:
            self.clients.popitem(last=False)
        if count >= self.max_requests:
            return JSONResponse(
                {"detail": "Слишком много запросов"},
                429,
                headers={"Retry-After": str(max(1, int(self.window - now + start)))},
            )
        return await call_next(request)
