"""Autentikasi dan pembatasan percobaan.

Dua cara masuk:
  1. Browser: halaman /login dengan kata sandi (WEB_PASSWORD). Setelah benar,
     server memberi cookie bertanda tangan (HttpOnly, SameSite=Lax, Secure di HTTPS).
  2. Aplikasi: header `Authorization: Bearer <STREAM_TOKEN>`.

Token lewat query string (?token=) sengaja TIDAK didukung lagi karena mudah
bocor lewat log, riwayat browser, dan header Referer.

Percobaan gagal (kata sandi atau token salah) dihitung per IP klien. Setelah
LOGIN_MAX_ATTEMPTS kali gagal, IP itu dikunci selama LOGIN_LOCKOUT_SECONDS.
"""
import hmac
import threading
import time
from functools import wraps

from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.crypto import salted_hmac
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

COOKIE_NAME = "ipcam_auth"
_SALT = "ipcam.auth.cookie.v1"


# --------------------------------------------------------------- IP klien
def client_ip(request):
    """IP klien. Header proxy hanya dipercaya jika TRUST_PROXY=true (server di belakang tunnel)."""
    if settings.TRUST_PROXY:
        for header in ("CF-Connecting-IP", "X-Forwarded-For"):
            value = request.headers.get(header)
            if value:
                return value.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


# ------------------------------------------------------ pembatas percobaan
class AttemptLimiter:
    """Penghitung percobaan gagal per IP, disimpan di memori proses."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}  # ip -> {"count", "first", "locked_until"}

    def locked_for(self, ip):
        """Sisa detik penguncian (0 jika tidak terkunci)."""
        now = time.time()
        with self._lock:
            st = self._state.get(ip)
            if not st:
                return 0
            remaining = st["locked_until"] - now
            return int(remaining) + 1 if remaining > 0 else 0

    def record_failure(self, ip):
        now = time.time()
        with self._lock:
            if len(self._state) > 10000:
                self._prune(now)
            st = self._state.get(ip)
            window_over = st is not None and (now - st["first"] > settings.LOGIN_WINDOW_SECONDS)
            if st is None or (window_over and st["locked_until"] <= now):
                st = {"count": 0, "first": now, "locked_until": 0.0}
                self._state[ip] = st
            st["count"] += 1
            if st["count"] >= settings.LOGIN_MAX_ATTEMPTS:
                st["locked_until"] = now + settings.LOGIN_LOCKOUT_SECONDS
                st["count"] = 0
                st["first"] = now

    def reset(self, ip):
        with self._lock:
            self._state.pop(ip, None)

    def _prune(self, now):
        cutoff = now - max(settings.LOGIN_WINDOW_SECONDS, settings.LOGIN_LOCKOUT_SECONDS)
        stale = [k for k, v in self._state.items() if v["locked_until"] <= now and v["first"] < cutoff]
        for k in stale:
            del self._state[k]


limiter = AttemptLimiter()


def too_many_response(wait_seconds):
    resp = JsonResponse(
        {"detail": "Terlalu banyak percobaan gagal. Coba lagi nanti."}, status=429
    )
    resp["Retry-After"] = str(wait_seconds)
    return resp


# ------------------------------------------------------------ rahasia/sesi
def secret_matches(provided, expected):
    """Bandingkan dalam waktu konstan; rahasia kosong tidak pernah cocok."""
    return bool(expected) and hmac.compare_digest(provided.encode(), expected.encode())


def _fingerprint():
    # Mengganti WEB_PASSWORD atau STREAM_TOKEN otomatis membatalkan semua sesi lama.
    material = f"{settings.WEB_PASSWORD}|{settings.STREAM_TOKEN}"
    return salted_hmac("ipcam.auth.fingerprint", material).hexdigest()[:20]


def make_session_value():
    return signing.TimestampSigner(salt=_SALT).sign(_fingerprint())


def session_ok(request):
    raw = request.COOKIES.get(COOKIE_NAME)
    if not raw:
        return False
    try:
        value = signing.TimestampSigner(salt=_SALT).unsign(
            raw, max_age=settings.AUTH_COOKIE_MAX_AGE
        )
    except signing.BadSignature:  # termasuk SignatureExpired
        return False
    return hmac.compare_digest(value, _fingerprint())


def bearer_token(request):
    """Token dari header Authorization, atau None jika header tidak dikirim."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def authenticate(request):
    """Return (diizinkan, respons_penolakan_atau_None)."""
    if session_ok(request):
        return True, None

    ip = client_ip(request)
    wait = limiter.locked_for(ip)
    if wait:
        return False, too_many_response(wait)

    supplied = bearer_token(request)
    if supplied is not None:
        if secret_matches(supplied, settings.STREAM_TOKEN):
            return True, None
        limiter.record_failure(ip)
        return False, JsonResponse({"detail": "Unauthorized"}, status=401)

    return False, None


# --------------------------------------------------------------- dekorator
def api_auth(view):
    """Untuk endpoint data (snapshot, stream, health): jawab 401/429 dalam JSON."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        ok, response = authenticate(request)
        if ok:
            return view(request, *args, **kwargs)
        return response or JsonResponse({"detail": "Unauthorized"}, status=401)

    return wrapper


def page_auth(view):
    """Untuk halaman web: arahkan ke /login jika belum masuk."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        ok, response = authenticate(request)
        if ok:
            return view(request, *args, **kwargs)
        if response is not None and response.status_code == 429:
            return response
        query = urlencode({"next": request.get_full_path()})
        return HttpResponseRedirect(f"/login?{query}")

    return wrapper


def safe_next(request, candidate):
    """Cegah open redirect: hanya terima alamat pada host yang sama."""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return "/"
