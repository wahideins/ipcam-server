# Akses dari luar jaringan dengan tunnel

Tunnel membuat alamat HTTPS publik yang meneruskan lalu lintas ke server Django di komputer Anda,
tanpa membuka port di router (dan bisa dipakai walau ISP memakai CGNAT).

```
HP / browser --HTTPS--> Penyedia tunnel --terowongan--> cloudflared di komputer --> Django (127.0.0.1:8000)
```

Karena alamatnya publik, **siapa pun di internet bisa membuka halaman login-nya**. Lapisan pengamannya:
HTTPS dari tunnel, halaman login + cookie bertanda tangan, token Bearer untuk aplikasi,
pembatas percobaan gagal per IP, dan CSRF/CSP/header keamanan.

## 1. Siapkan server

Di `.env`:

```dotenv
DJANGO_SECRET_KEY=...            # wajib, acak panjang
STREAM_TOKEN=...                 # untuk aplikasi
WEB_PASSWORD=...                 # untuk browser, min. 12 karakter
TRUST_PROXY=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,cam.contoh.com
CSRF_TRUSTED_ORIGINS=https://cam.contoh.com
```

Ganti `cam.contoh.com` dengan alamat publik dari tunnel. Jalankan server hanya di localhost
supaya satu-satunya jalan masuk adalah lewat tunnel:

```bash
waitress-serve --listen=127.0.0.1:8000 --threads=16 config.wsgi:application
```

## 2a. Cloudflare Tunnel

**Uji cepat (tanpa akun dan domain):**

```bash
cloudflared tunnel --url http://localhost:8000
```

Perintah ini mencetak alamat acak `https://xxxx.trycloudflare.com`. Masukkan alamat itu ke
`DJANGO_ALLOWED_HOSTS` dan `CSRF_TRUSTED_ORIGINS`, restart server, lalu buka di browser. Alamat berubah setiap tunnel dimulai ulang.

**Permanen (butuh domain yang dikelola Cloudflare):**

```bash
cloudflared tunnel login
cloudflared tunnel create ipcam
cloudflared tunnel route dns ipcam cam.contoh.com
```

Buat `config.yml` (di Windows: `%USERPROFILE%\.cloudflared\config.yml`):

```yaml
tunnel: ipcam
credentials-file: C:\Users\ANDA\.cloudflared\<ID-TUNNEL>.json
ingress:
  - hostname: cam.contoh.com
    service: http://localhost:8000
  - service: http_status:404
```

Jalankan dengan `cloudflared tunnel run ipcam`, atau pasang sebagai layanan Windows agar otomatis jalan
(`cloudflared service install`).

Catatan: ketentuan layanan Cloudflare membatasi penyajian video/berkas besar lewat layanan gratis mereka.
Untuk penggunaan pribadi dengan resolusi kecil biasanya tidak bermasalah, tetapi periksa ketentuan terbaru.
Jika khawatir, pakai alternatif di bawah.

## 2b. Alternatif

- **Tailscale Funnel**: `tailscale funnel 8000` memberi alamat HTTPS publik `*.ts.net` tanpa domain sendiri.
- **ngrok**: `ngrok http 8000` (akun gratis memberi alamat acak, domain tetap berbayar).

Untuk semuanya, pastikan tunnel mengirim IP asli klien lewat header `CF-Connecting-IP` (Cloudflare)
atau `X-Forwarded-For` (lainnya). Jika tidak, semua pengunjung dianggap satu IP sehingga pembatas
percobaan akan mengunci semua orang sekaligus.

## 3. Memakai

- **Browser:** buka alamat publik, masukkan `WEB_PASSWORD`, lalu stream tampil. Sesi berlaku `AUTH_SESSION_DAYS` hari.
- **Aplikasi Android:** di Pengaturan isi alamat `https://cam.contoh.com` dan `STREAM_TOKEN`. Aplikasi mengirim token
  lewat header, jadi tidak melewati halaman login.

## 4. Keamanan: hal yang perlu diingat

- Pakai kata sandi dan token yang **panjang dan acak**. Pembatas percobaan memperlambat tebakan, tetapi kekuatan utama tetap pada panjang rahasianya.
- Setelah 5 kali salah (bawaan), sebuah IP dikunci 15 menit. Pembatas disimpan di memori, jadi hilang saat server restart.
- Mengganti `WEB_PASSWORD` atau `STREAM_TOKEN` otomatis mengeluarkan semua sesi browser yang sedang login.
- Jangan membuka port server (8000) atau kamera (554, 80) di router. Kamera tetap hanya boleh diakses komputer ini.
- Jangan membagikan `.env`. Ganti password kamera dengan yang kuat.
- Video kamera adalah data sensitif; batasi siapa yang tahu alamat dan kata sandinya.
