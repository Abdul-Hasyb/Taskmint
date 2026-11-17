import base64  # turn the script's fingerprint into text for the CSP header
import hashlib  # make a fingerprint (SHA-256) of our page's script
import ipaddress  # check that a value really is an IP address
import logging  # notes for the server log
import os  # read settings from the environment (.env)
import re  # find the <script> part of index.html
import threading  # a lock, so two requests can't count at the same moment
import time  # the clock the rate limiter uses
from collections import defaultdict, deque  # a dictionary of queues (one queue of timestamps per key)
from pathlib import Path  # file paths
from typing import Annotated  # attach rules to a type

from fastapi import FastAPI, HTTPException, Path as PathParam, Request, status  # FastAPI tools
from fastapi.responses import JSONResponse  # a JSON reply we build ourselves

logger = logging.getLogger("taskmint.guard")  # our notes show up as "taskmint.guard" in the log

MAX_ID = 2_147_483_647  # the biggest number PostgreSQL's INTEGER can hold; bigger ids crashed the server (500)
PathId = Annotated[int, PathParam(ge=1, le=MAX_ID)]  # use as the type of /tasks/{task_id}: 0, negative or huge = 422, not a crash
MAX_BODY_BYTES = 1_000_000  # 1 MB: no request is ever bigger than this (a whole message is at most 4,000 characters)
API_PREFIXES = ("/auth", "/tasks", "/clients", "/planner", "/reminders")  # the parts of the site that hit the database


# ---------------------------------------------------------------- rate limiting

class RateLimiter:  # "at most N times per M seconds" for any key (an IP, an email, a user...)
    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)  # key -> times of its recent hits
        self.lock = threading.Lock()  # FastAPI runs requests in parallel threads

    def hit(self, key: str, limit: int, window: float) -> bool:  # count one hit; True = allowed, False = too many
        now = time.monotonic()  # a clock that never jumps (unlike the wall clock)
        with self.lock:
            queue = self.hits[key]
            while queue and queue[0] <= now - window:  # forget hits older than the window
                queue.popleft()
            if len(queue) >= limit:  # already at the limit
                return False
            queue.append(now)
            if len(self.hits) > 50_000:  # never let memory grow forever: drop keys with no recent hits
                for old in [k for k, q in self.hits.items() if not q]:
                    del self.hits[old]
            return True

    def clear(self, key: str) -> None:  # forget ONE key (e.g. unlock an account's logins after a password reset)
        with self.lock:
            self.hits.pop(key, None)

    def reset(self) -> None:  # tests start with a clean slate
        with self.lock:
            self.hits.clear()


limiter = RateLimiter()  # one shared limiter for the whole server


def client_ip(request: Request) -> str:  # who is calling (their IP address)
    header = os.getenv("CLIENT_IP_HEADER", "").strip()  # live on Render: "True-Client-IP" (set by Cloudflare, which sits in front of Render)
    if header:  # only trust a header when we said so (locally anyone could type any header)
        value = request.headers.get(header, "").strip()[:64]  # the real visitor's IP, as Cloudflare saw it
        try:
            return str(ipaddress.ip_address(value))  # only a real IP address counts; junk is ignored
        except ValueError:
            pass  # missing or not an IP: fall back below
    # NOT X-Forwarded-For: Render only adds to it, so a visitor could write a fake IP there and dodge our limits
    return request.client.host if request.client else "unknown"  # the address that connected to us


def limit(key: str, times: int, seconds: float, message: str = "Too many requests. Please wait a bit and try again.") -> None:
    if not limiter.hit(key, times, seconds):  # over the limit?
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=message, headers={"Retry-After": str(int(seconds))})


# ---------------------------------------------------------------- security headers

_hash_cache: dict[str, tuple[float, str]] = {}  # file -> (when it last changed, its script fingerprint)


def page_script_hash(static_dir: Path) -> str:  # the fingerprint of the <script> in index.html, so the CSP allows ONLY that script
    try:
        changed = (static_dir / "index.html").stat().st_mtime  # re-read only when the file changes (no restart needed after edits)
        cached = _hash_cache.get(str(static_dir))
        if cached and cached[0] == changed:
            return cached[1]
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)  # the exact text between the tags
        fingerprint = "'sha256-" + base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode() + "'"
        _hash_cache[str(static_dir)] = (changed, fingerprint)
        return fingerprint
    except (OSError, AttributeError):  # no page or no script: allow no inline script at all
        return "'none'"


def install(app: FastAPI, static_dir: Path) -> None:  # plug all the guards into the app
    def csp() -> str:  # Content-Security-Policy: what the page is allowed to load and run
        return "; ".join([
        "default-src 'self'",  # by default, only things from Taskmint itself
        f"script-src {page_script_hash(static_dir)}",  # only OUR script runs: an injected <script> would be blocked by the browser
        "style-src 'self' 'unsafe-inline'",  # our inline styles
        "img-src 'self' data:",  # our images + the leaf logo drawn in code
        "connect-src 'self'",  # the page may only talk to our own API
        "object-src 'none'", "base-uri 'none'", "form-action 'self'",
        "frame-ancestors 'none'",  # nobody can put Taskmint inside their site (clickjacking)
        ])

    @app.middleware("http")
    async def guard(request: Request, call_next):  # runs around EVERY request
        size = request.headers.get("content-length", "0")
        if not size.isdigit() or int(size) > MAX_BODY_BYTES:  # too big (or nonsense size): refuse before reading it
            return JSONResponse({"detail": "Request too large"}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        if request.url.path.startswith(API_PREFIXES) and not limiter.hit(f"api:{client_ip(request)}", 300, 60):  # 300 API calls a minute per IP
            return JSONResponse({"detail": "Too many requests. Please slow down."}, status_code=status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": "60"})
        response = await call_next(request)  # the normal work
        response.headers["X-Content-Type-Options"] = "nosniff"  # the browser must trust our file types, not guess
        response.headers["X-Frame-Options"] = "DENY"  # older browsers: never inside a frame
        response.headers["Referrer-Policy"] = "no-referrer"  # don't leak our URLs to other sites
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"  # we never need these
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith(("/docs", "/openapi.json")):  # /docs loads its own scripts from a CDN, so it gets no CSP
            response.headers["Content-Security-Policy"] = csp()
        if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":  # once live on HTTPS: always use HTTPS
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(Exception)
    async def crash(request: Request, error: Exception):  # any unexpected error: log it, but show the user nothing internal
        logger.exception("Unexpected error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)


def docs_enabled() -> bool:  # /docs on (default, handy now) or off (set ENABLE_DOCS=0 when live)
    return os.getenv("ENABLE_DOCS", "1") != "0"
