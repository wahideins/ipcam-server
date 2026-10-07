# Server IP Cam (Django)

Mengambil video dari IP camera lewat **RTSP over TCP** (satu koneksi ke kamera, dibagi ke banyak klien)
dan menyajikannya lewat HTTP, dengan halaman login dan pembatasan percobaan.

```
IP Cam --RTSP/TCP--> Django (thread pembaca) --HTTP(S)--> Browser / Aplikasi Android
```

## Endpoint

| Endpoint | Fungsi | Cara masuk |
|---|---|---|
| `GET /` | Halaman live di browser | Login (cookie sesi) |
| `GET /login`, `POST /login` | Halaman masuk dengan kata sandi | - |
| `POST /logout` | Keluar | Cookie sesi |
| `GET /snapshot.jpg` | Satu gambar JPEG terbaru | Cookie sesi **atau** header Bearer |
| `GET /stream.mjpg` | Stream MJPEG (live) | Cookie sesi **atau** header Bearer |
| `GET /health` | Status koneksi kamera (JSON) | Cookie sesi **atau** header Bearer |

## Keamanan

- **Browser:** buka `/`, masukkan `WEB_PASSWORD`. Server memberi cookie bertanda tangan
  (HttpOnly, SameSite=Lax, Secure di HTTPS) yang berlaku `AUTH_SESSION_DAYS` hari.
- **Aplikasi:** kirim header `Authorization: Bearer <STREAM_TOKEN>`.
- **Token lewat URL (`?token=...`) tidak lagi didukung** karena mudah bocor lewat log dan riwayat.
- **Pembatas percobaan:** 5 kali salah (kata sandi atau token) dari satu IP, IP itu dikunci 15 menit (`429`).
- Form login dilindungi CSRF; halaman memakai CSP ketat, `X-Frame-Options: DENY`, dan `nosniff`.
- Mengganti `WEB_PASSWORD` atau `STREAM_TOKEN` otomatis mengeluarkan semua sesi browser.

## Menjalankan

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Isi `.env` minimal: `DJANGO_SECRET_KEY`, `RTSP_URL`, `STREAM_TOKEN`, `WEB_PASSWORD`, dan `DJANGO_ALLOWED_HOSTS`.

Jaringan lokal:

```bash
python manage.py runserver 0.0.0.0:8000
```

Untuk uji lewat `http://` biasa tanpa tunnel, biarkan `TRUST_PROXY=false`.
Jika kemudian login terlihat tidak menyimpan sesi, pastikan `COOKIE_SECURE` tidak bernilai `true` pada koneksi HTTP.

Lebih stabil (multi-thread, tanpa auto-reload):

```bash
waitress-serve --listen=0.0.0.0:8000 --threads=16 config.wsgi:application
```

Uji dari terminal:

```bash
curl -H "Authorization: Bearer TOKEN" -o tes.jpg http://localhost:8000/snapshot.jpg
```

## Akses dari luar jaringan

Lihat **[TUNNEL.md](TUNNEL.md)** untuk memasang tunnel HTTPS (Cloudflare Tunnel, Tailscale Funnel, ngrok)
beserta pengaturan `.env` untuk mode tunnel (`TRUST_PROXY`, `CSRF_TRUSTED_ORIGINS`, dan lain-lain).

## Catatan

- Gunakan **sub-stream** kamera (resolusi rendah) agar ringan.
- Setiap klien stream memakai satu thread server; sesuaikan `--threads` dengan jumlah klien.
- Koneksi ke kamera otomatis ditutup setelah `IDLE_TIMEOUT` detik tanpa klien dan dibuka lagi saat ada request.
- Ini tahap pengambilan gambar. Langkah berikutnya: sisipkan model deteksi (mis. YOLO) di `camera.py`
  setelah frame dibaca, sehingga stream yang disajikan sudah beranotasi.
- Jangan membuka port kamera atau server langsung ke internet; gunakan tunnel atau VPN.
