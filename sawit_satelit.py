#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAWIT SATELIT (versi otomatis / GitHub Actions)
===============================================
Unduh 4 citra Sentinel-2 plot kebun -> simpan ke folder citra/ -> (opsional) email.
Semua rahasia dibaca dari environment variables (GitHub Secrets), TIDAK ditulis di file.

ENV yang dibaca:
  WAJIB : SH_CLIENT_ID, SH_CLIENT_SECRET
  Lokasi (opsional, ada default): PLOT_LAT, PLOT_LON, BOX_HALF_M
  Email (opsional): MAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
"""

import datetime as dt
import json
import math
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

# --------- Lokasi plot (default = plot HS, Rawang Air Putih) ---------
LAT = float(os.environ.get("PLOT_LAT", "0.81500"))
LON = float(os.environ.get("PLOT_LON", "101.96617"))
BOX_HALF_M = float(os.environ.get("BOX_HALF_M", "600"))
IMG_PX = int(os.environ.get("IMG_PX", "1024"))
LATEST_DAYS = 14
CLOUDFREE_DAYS = 45

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

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


def get_token():
    cid = os.environ.get("SH_CLIENT_ID", "").strip()
    csec = os.environ.get("SH_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        sys.exit("[!] SH_CLIENT_ID / SH_CLIENT_SECRET belum di-set (GitHub Secrets).")
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": csec,
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


def fetch(token, evalscript, days, mosaicking, out_path):
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
            "width": IMG_PX, "height": IMG_PX,
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
    print("    [ok] %s (%d KB)" % (os.path.basename(out_path), len(img) // 1024))
    return out_path


def send_email(paths):
    to = os.environ.get("MAIL_TO", "").strip()
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not (to and user and pw):
        print("(email dilewati: MAIL_TO/SMTP_USER/SMTP_PASS belum lengkap)")
        return
    msg = EmailMessage()
    msg["Subject"] = "Citra Satelit Kebun Sawit — " + dt.date.today().isoformat()
    msg["From"] = user
    msg["To"] = to
    msg.set_content(
        "Terlampir 4 citra Sentinel-2 plot kebun minggu ini:\n"
        "1. Warna asli (terbaru)\n2. NDVI (terbaru)\n"
        "3. Warna asli (bebas awan)\n4. NDVI (bebas awan)\n\n"
        "NDVI: hijau tua = sehat/rimbun, kuning = lemah, merah = stres/gundul.")
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
    stamp = dt.date.today().isoformat()
    out_dir = os.path.join("citra", stamp)
    os.makedirs(out_dir, exist_ok=True)
    print("Plot %.5f, %.5f | area ~%.1f km" % (LAT, LON, BOX_HALF_M * 2 / 1000.0))
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
        paths.append(fetch(token, ev, days, mos, os.path.join(out_dir, name)))
    ok = len([p for p in paths if p])
    print("Tersimpan %d/4 di %s" % (ok, out_dir))
    try:
        send_email(paths)
    except Exception as e:
        print("(email gagal: %s)" % e)


if __name__ == "__main__":
    main()
