#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAWIT SATELIT (otomatis / GitHub Actions)
=========================================
- Ambil 4 citra Sentinel-2 plot kebun pada resolusi ASLI (10 m/piksel) => detail maksimum.
- Perbesar tajam (nearest) + cap tanggal pengambilan citra di pojok.
- Simpan ke citra/<tanggal>/ dan latest/, buat index.html, (opsional) email.

ENV:
  WAJIB : SH_CLIENT_ID, SH_CLIENT_SECRET
  Lokasi: PLOT_LAT, PLOT_LON, BOX_HALF_M
  Email : MAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
"""

import datetime as dt
import json
import math
import os
import shutil
import smtplib
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

# --- pastikan Pillow tersedia (auto-install di runner) ---
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pillow"], check=True)
    from PIL import Image, ImageDraw, ImageFont

LAT = float(os.environ.get("PLOT_LAT", "0.81500"))
LON = float(os.environ.get("PLOT_LON", "101.96617"))
BOX_HALF_M = float(os.environ.get("BOX_HALF_M", "600"))
RES_M = 10.0  # resolusi asli Sentinel-2 (band tampak) = 10 meter/piksel
LATEST_DAYS = 20
CLOUDFREE_DAYS = 60

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
CATALOG_URL = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"

EVAL_TRUECOLOR = """//VERSION=3
function setup(){return {input:["B02","B03","B04"],output:{bands:3}};}
function evaluatePixel(s){return [2.5*s.B04, 2.5*s.B03, 2.5*s.B02];}
"""

EVAL_NDVI = """//VERSION=3
function setup(){return {input:["B04","B08"],output:{bands:3}};}
function evaluatePixel(s){
  let ndvi=(s.B08-s.B04)/(s.B08+s.B04);
  if(ndvi<0.0)      return [0.75,0.75,0.75];
  else if(ndvi<0.2) return [0.85,0.20,0.13];
  else if(ndvi<0.4) return [0.95,0.75,0.20];
  else if(ndvi<0.6) return [0.60,0.85,0.20];
  else if(ndvi<0.8) return [0.20,0.65,0.15];
  else              return [0.00,0.35,0.05];
}
"""

TITLES = {
    "1_warna_asli_terbaru.png": "Warna Asli — Terbaru",
    "2_ndvi_terbaru.png": "NDVI (Kesehatan) — Terbaru",
    "3_warna_asli_bebas_awan.png": "Warna Asli — Bebas Awan",
    "4_ndvi_bebas_awan.png": "NDVI (Kesehatan) — Bebas Awan",
}
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
          "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def get_token():
    cid = os.environ.get("SH_CLIENT_ID", "").strip()
    csec = os.environ.get("SH_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        sys.exit("[!] SH_CLIENT_ID / SH_CLIENT_SECRET belum di-set.")
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cid, "client_secret": csec,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit("[!] Gagal login: %s %s" % (e.code, e.read().decode("utf-8", "ignore")))


def bbox_from_center(lat, lon, half_m):
    dlat = half_m / 111320.0
    dlon = half_m / (111320.0 * math.cos(math.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def scene_info(token, days, mosaicking):
    """Cari tanggal & tutupan awan citra yang dipakai (via Catalog/STAC)."""
    to_d = dt.date.today()
    from_d = to_d - dt.timedelta(days=days)
    field = "properties.datetime" if mosaicking == "mostRecent" else "properties.eo:cloud_cover"
    direction = "desc" if mosaicking == "mostRecent" else "asc"
    body = {
        "bbox": bbox_from_center(LAT, LON, BOX_HALF_M),
        "datetime": from_d.isoformat() + "T00:00:00Z/" + to_d.isoformat() + "T23:59:59Z",
        "collections": ["sentinel-2-l2a"],
        "limit": 1,
        "sortby": [{"field": field, "direction": direction}],
    }
    req = urllib.request.Request(
        CATALOG_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            feats = json.load(r).get("features", [])
        if not feats:
            return None, None
        p = feats[0]["properties"]
        d = p["datetime"][:10]
        y, m, day = d.split("-")
        label = "%s %s %s" % (int(day), MONTHS[int(m)], y)
        cc = p.get("eo:cloud_cover")
        return label, (round(cc) if cc is not None else None)
    except Exception as e:
        print("    (catalog gagal: %s)" % e)
        return None, None


def fetch(token, evalscript, days, mosaicking, out_path, px):
    to_d = dt.date.today()
    from_d = to_d - dt.timedelta(days=days)
    body = {
        "input": {
            "bounds": {
                "bbox": bbox_from_center(LAT, LON, BOX_HALF_M),
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": from_d.isoformat() + "T00:00:00Z",
                        "to": to_d.isoformat() + "T23:59:59Z",
                    },
                    "mosaickingOrder": mosaicking,
                },
            }],
        },
        "output": {
            "width": px, "height": px,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
    }
    req = urllib.request.Request(
        PROCESS_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json", "Accept": "image/png"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            img = r.read()
    except urllib.error.HTTPError as e:
        print("    [x] %s %s" % (e.code, e.read().decode("utf-8", "ignore")[:300]))
        return None
    with open(out_path, "wb") as f:
        f.write(img)
    return out_path


def load_font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def finalize(path, label, factor):
    """Perbesar tajam (nearest = tanpa blur palsu) + cap tanggal di pojok."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.resize((w * factor, h * factor), Image.NEAREST)
    W, H = im.size
    d = ImageDraw.Draw(im)
    fs = max(16, W // 30)
    font = load_font(fs)
    pad = fs // 2
    try:
        tw = int(d.textlength(label, font=font))
    except Exception:
        tw = fs * len(label) // 2
    d.rectangle([0, H - fs - 2 * pad, tw + 2 * pad, H], fill=(0, 0, 0))
    d.text((pad, H - fs - int(pad * 1.2)), label, fill=(255, 255, 255), font=font)
    im.save(path)


def build_viewer(paths, stamp, ver):
    os.makedirs("latest", exist_ok=True)
    cards = ""
    for p in paths:
        if not p:
            continue
        name = os.path.basename(p)
        shutil.copyfile(p, os.path.join("latest", name))
        title = TITLES.get(name, name)
        cards += ('<div class="card"><h2>' + title + '</h2>'
                  '<a href="latest/' + name + '?v=' + ver + '" target="_blank">'
                  '<img src="latest/' + name + '?v=' + ver + '" alt="' + title + '"></a></div>\n')
    html = HTML_TEMPLATE.replace("__DATE__", stamp).replace("__CARDS__", cards)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open("manifest.json", "w", encoding="utf-8") as f:
        f.write(MANIFEST)
    print("index.html diperbarui.")


def send_email(paths):
    to = os.environ.get("MAIL_TO", "").strip()
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not (to and user and pw):
        print("(email dilewati: secret email belum lengkap)")
        return
    msg = EmailMessage()
    msg["Subject"] = "Citra Satelit Kebun Sawit — " + dt.date.today().isoformat()
    msg["From"] = user
    msg["To"] = to
    msg.set_content("Terlampir 4 citra Sentinel-2 plot kebun.\n"
                    "NDVI: hijau tua = sehat, kuning = lemah, merah = stres/gundul.")
    for p in paths:
        if not p:
            continue
        with open(p, "rb") as f:
            msg.add_attachment(f.read(), maintype="image", subtype="png",
                               filename=os.path.basename(p))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=60) as s:
        s.starttls(context=ctx)
        s.login(user, pw)
        s.send_message(msg)
    print("Email terkirim ke %s" % to)


def main():
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)
    stamp = now.strftime("%d %b %Y, %H:%M WIB")
    ver = now.strftime("%Y%m%d%H%M")
    day = dt.date.today().isoformat()
    out_dir = os.path.join("citra", day)
    os.makedirs(out_dir, exist_ok=True)

    native_px = max(48, round(2 * BOX_HALF_M / RES_M))  # resolusi asli 10 m
    factor = max(4, round(1000 / native_px))            # perbesar tajam utk dilihat
    print("Plot %.5f, %.5f | area ~%.2f km | native %dpx x%d" %
          (LAT, LON, BOX_HALF_M * 2 / 1000.0, native_px, factor))

    token = get_token()
    jobs = [
        ("1_warna_asli_terbaru.png",    EVAL_TRUECOLOR, LATEST_DAYS,    "mostRecent"),
        ("2_ndvi_terbaru.png",          EVAL_NDVI,      LATEST_DAYS,    "mostRecent"),
        ("3_warna_asli_bebas_awan.png", EVAL_TRUECOLOR, CLOUDFREE_DAYS, "leastCC"),
        ("4_ndvi_bebas_awan.png",       EVAL_NDVI,      CLOUDFREE_DAYS, "leastCC"),
    ]
    paths = []
    for name, ev, days, mos in jobs:
        print("  -> " + name)
        date_lbl, cc = scene_info(token, days, mos)
        p = fetch(token, ev, days, mos, os.path.join(out_dir, name), native_px)
        if p:
            tag = "S2 · " + (date_lbl or day)
            if cc is not None:
                tag += " · awan %d%%" % cc
            finalize(p, tag, factor)
            print("    [ok] %s (%s)" % (name, tag))
        paths.append(p)
    ok = len([p for p in paths if p])
    print("Tersimpan %d/4 di %s" % (ok, out_dir))
    build_viewer(paths, stamp, ver)
    try:
        send_email(paths)
    except Exception as e:
        print("(email gagal: %s)" % e)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Citra Kebun Sawit</title>
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#1b5e20">
<style>
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:#0f2417; color:#eaf5ea; }
header { padding:16px; text-align:center; background:#1b5e20; position:sticky; top:0; z-index:5; }
header h1 { margin:0; font-size:17px; }
header p { margin:5px 0 0; font-size:13px; opacity:.85; }
.card { margin:14px; background:#15321f; border-radius:14px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.35); }
.card h2 { font-size:15px; margin:0; padding:12px 14px 8px; }
.card img { width:100%; display:block; image-rendering:pixelated; }
.legend { margin:14px; padding:14px; background:#15321f; border-radius:14px; font-size:13px; line-height:1.8; }
.sw { display:inline-block; width:13px; height:13px; border-radius:3px; margin-right:7px; vertical-align:middle; }
footer { text-align:center; font-size:12px; opacity:.6; padding:20px; }
</style>
</head>
<body>
<header>
<h1>🛰️ Kebun Sawit — Rawang Air Putih</h1>
<p>Diperbarui: __DATE__</p>
</header>
__CARDS__
<div class="legend">
<b>Cara baca NDVI:</b><br>
<span class="sw" style="background:#00591a"></span> Hijau tua — rimbun / sehat<br>
<span class="sw" style="background:#4caf50"></span> Hijau muda — sedang<br>
<span class="sw" style="background:#f2c032"></span> Kuning — lemah<br>
<span class="sw" style="background:#d93521"></span> Merah — stres / gundul<br>
<span class="sw" style="background:#bfbfbf"></span> Abu — air / tanah basah
</div>
<footer>Otomatis dari Sentinel-2 · Copernicus · tap gambar untuk perbesar</footer>
</body>
</html>
"""

MANIFEST = '{"name":"Kebun Sawit","short_name":"Sawit","start_url":".","display":"standalone","background_color":"#0f2417","theme_color":"#1b5e20","icons":[]}'


if __name__ == "__main__":
    main()
