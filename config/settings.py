"""Pengaturan Django untuk server IP cam.

Semua nilai sensitif dibaca dari environment variable atau file .env
(di folder yang sama dengan manage.py). Lihat .env.example.
"""
import os
import secrets
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Pemuat .env sederhana (KEY=VALUE per baris); tidak menimpa env yang sudah ada."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def _env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# ------------------------------------------------------------------ Django
_secret = os.environ.get("DJANGO_SECRET_KEY", "")
if not _secret:
    warnings.warn(
        "DJANGO_SECRET_KEY belum diisi: kunci acak dibuat setiap start, sehingga semua "
        "sesi login hilang setiap server di-restart. Isi di .env."
    )
SECRET_KEY = _secret or secrets.token_urlsafe(50)
DEBUG = _env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "streamer",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = []
DATABASES = {}  # tidak memakai database

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# ------------------------------------------------------------------ IP cam
# Contoh: rtsp://user:pass@192.168.1.10:554/stream2  (pakai sub-stream resolusi rendah)
RTSP_URL = os.environ.get("RTSP_URL", "")

JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "75"))
MAX_FPS = float(os.environ.get("MAX_FPS", "15"))            # 0 = tanpa batas
FRAME_WIDTH = int(os.environ.get("FRAME_WIDTH", "960"))      # perkecil jika lebih lebar; 0 = asli
IDLE_TIMEOUT = float(os.environ.get("IDLE_TIMEOUT", "30"))   # detik tanpa klien sebelum koneksi ke kamera ditutup

# -------------------------------------------------------------- keamanan
# Token untuk aplikasi (header Authorization: Bearer ...). Wajib diisi.
STREAM_TOKEN = os.environ.get("STREAM_TOKEN", "")

# Kata sandi untuk halaman login di browser. Jika kosong, memakai STREAM_TOKEN.
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "") or STREAM_TOKEN

# Aktifkan jika server berada di belakang tunnel/reverse proxy HTTPS.
# Efek: IP klien dibaca dari header proxy, cookie ditandai Secure.
TRUST_PROXY = _env_bool("TRUST_PROXY", False)

# Cookie hanya dikirim lewat HTTPS. Matikan (false) hanya untuk uji lewat http:// tanpa tunnel.
COOKIE_SECURE = _env_bool("COOKIE_SECURE", TRUST_PROXY)

# Lama sesi login (hari).
AUTH_COOKIE_MAX_AGE = int(float(os.environ.get("AUTH_SESSION_DAYS", "7")) * 86400)

# Pembatas percobaan gagal per IP.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "900"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))

# Alamat publik (dengan https://), contoh: https://cam.contoh.com
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS")
CSRF_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True

if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Setelah HTTPS terbukti berjalan, isi mis. 31536000 agar browser selalu memakai HTTPS.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))

if not RTSP_URL:
    warnings.warn("RTSP_URL belum diisi (lihat .env.example).")
if not STREAM_TOKEN:
    warnings.warn("STREAM_TOKEN belum diisi: login dan akses aplikasi akan selalu ditolak.")
if WEB_PASSWORD and len(WEB_PASSWORD) < 12:
    warnings.warn("Kata sandi/token pendek (< 12 karakter). Untuk akses publik pakai yang panjang dan acak.")
