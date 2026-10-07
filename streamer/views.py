import html
import time

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .camera import get_camera
from .security import (
    COOKIE_NAME,
    api_auth,
    client_ip,
    limiter,
    make_session_value,
    page_auth,
    safe_next,
    secret_matches,
)

BOUNDARY = "frame"

# Halaman HTML tidak memakai skrip, jadi CSP bisa dibuat sangat ketat.
_PAGE_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)

_STYLE = """
body{margin:0;background:#111;color:#eee;font-family:system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:16px;text-align:center}
img.stream{max-width:100%;height:auto;background:#000}
form.login{max-width:320px;margin:15vh auto;padding:24px;background:#1c1c1c;border-radius:12px;text-align:left}
label{display:block;margin-bottom:6px;font-size:14px}
input[type=password]{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #444;background:#111;color:#eee;font-size:16px}
button,a.btn{display:inline-block;margin-top:14px;padding:10px 16px;border:0;border-radius:8px;background:#1e9e8e;color:#fff;font-size:15px;text-decoration:none;cursor:pointer}
button.alt{background:#333}
.err{color:#ff8080;margin:0 0 12px;font-size:14px}
.bar{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
"""


def _html_response(body, status=200):
    resp = HttpResponse(body, status=status, content_type="text/html; charset=utf-8")
    resp["Content-Security-Policy"] = _PAGE_CSP
    resp["Cache-Control"] = "no-store"
    resp["Referrer-Policy"] = "same-origin"
    return resp


# ------------------------------------------------------------------ login
def _login_page(request, next_url, error="", status=200):
    csrf = html.escape(get_token(request))
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Masuk - IP Cam</title><style>{_STYLE}</style></head>
<body><form class="login" method="post" action="/login">
<h3 style="margin-top:0">IP Cam</h3>{err}
<input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
<input type="hidden" name="next" value="{html.escape(next_url)}">
<label for="pw">Kata sandi</label>
<input id="pw" type="password" name="password" autocomplete="current-password" autofocus required>
<button type="submit">Masuk</button>
</form></body></html>"""
    return _html_response(body, status)


@require_http_methods(["GET", "POST"])
def login_view(request):
    next_url = safe_next(request, request.POST.get("next") or request.GET.get("next") or "/")

    if request.method == "GET":
        return _login_page(request, next_url)

    ip = client_ip(request)
    wait = limiter.locked_for(ip)
    if wait:
        minutes = max(1, wait // 60)
        return _login_page(
            request, next_url,
            f"Terlalu banyak percobaan gagal. Coba lagi sekitar {minutes} menit lagi.",
            status=429,
        )

    password = request.POST.get("password", "")
    if secret_matches(password, settings.WEB_PASSWORD):
        limiter.reset(ip)
        resp = HttpResponseRedirect(next_url)
        resp.set_cookie(
            COOKIE_NAME,
            make_session_value(),
            max_age=settings.AUTH_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="Lax",
        )
        return resp

    limiter.record_failure(ip)
    return _login_page(request, next_url, "Kata sandi salah.", status=401)


@require_POST
def logout_view(request):
    resp = HttpResponseRedirect("/login")
    resp.delete_cookie(COOKIE_NAME, samesite="Lax")
    return resp


# --------------------------------------------------------------- halaman
@require_GET
@page_auth
def index(request):
    csrf = html.escape(get_token(request))
    body = f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IP Cam</title><style>{_STYLE}</style></head>
<body><main>
<h3>IP Cam (live)</h3>
<img class="stream" src="/stream.mjpg" alt="stream">
<div class="bar">
<a class="btn" href="/snapshot.jpg" download="snapshot.jpg">Ambil snapshot</a>
<form method="post" action="/logout">
<input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
<button class="alt" type="submit">Keluar</button>
</form>
</div></main></body></html>"""
    return _html_response(body)


# ------------------------------------------------------------- endpoint data
@require_GET
@api_auth
def health(request):
    cam = get_camera()
    cam.touch()
    return JsonResponse(cam.status())


@require_GET
@api_auth
def snapshot(request):
    """Satu gambar JPEG terbaru dari kamera."""
    cam = get_camera()
    frame_id, frame = cam.wait_for_frame(-1, timeout=10.0)
    if frame is None:
        return JsonResponse({"detail": "Kamera belum menghasilkan frame", **cam.status()}, status=503)
    jpeg = cam.encode_jpeg(frame_id, frame)
    if jpeg is None:
        return JsonResponse({"detail": "Gagal encode JPEG"}, status=500)
    resp = HttpResponse(jpeg, content_type="image/jpeg")
    resp["Cache-Control"] = "no-store"
    return resp


def _mjpeg_generator():
    cam = get_camera()
    min_interval = 1.0 / settings.MAX_FPS if settings.MAX_FPS > 0 else 0.0
    last_id = 0
    last_sent = 0.0
    try:
        while True:
            frame_id, frame = cam.wait_for_frame(last_id, timeout=10.0)
            if frame is None:
                # Tidak ada frame baru dalam 10 detik: akhiri, klien bisa menyambung ulang.
                return
            last_id = frame_id

            wait = min_interval - (time.time() - last_sent)
            if wait > 0:
                continue  # lewati frame (batasi FPS), ambil yang terbaru berikutnya

            jpeg = cam.encode_jpeg(frame_id, frame)
            if jpeg is None:
                continue
            last_sent = time.time()
            yield (
                b"--" + BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
    except GeneratorExit:
        return


@require_GET
@api_auth
def stream(request):
    """Stream MJPEG (multipart/x-mixed-replace) dari kamera."""
    resp = StreamingHttpResponse(
        _mjpeg_generator(),
        content_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
    )
    resp["Cache-Control"] = "no-store"
    resp["X-Accel-Buffering"] = "no"  # matikan buffering jika di belakang Nginx
    return resp
