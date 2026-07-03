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

LAYER_KEYS = ["1_warna_asli_terbaru.png", "2_ndvi_terbaru.png",
              "3_warna_asli_bebas_awan.png", "4_ndvi_bebas_awan.png"]


def nice_date(iso):
    try:
        y, m, dd = iso.split("-")
        return "%d %s %s" % (int(dd), MONTHS[int(m)], y)
    except Exception:
        return iso


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


def scene_info(token, days, mode):
    """Ambil tanggal asli & tutupan awan citra dari Copernicus Catalog (STAC).
    mode="mostRecent" -> scene terbaru; selain itu -> scene paling sedikit awan."""
    to_d = dt.date.today()
    from_d = to_d - dt.timedelta(days=days)
    body = {
        "bbox": bbox_from_center(LAT, LON, BOX_HALF_M),
        "datetime": from_d.isoformat() + "T00:00:00Z/" + to_d.isoformat() + "T23:59:59Z",
        "collections": ["sentinel-2-l2a"],
        "limit": 100,
    }
    req = urllib.request.Request(
        CATALOG_URL, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json", "Accept": "application/geo+json, application/json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            feats = json.load(r).get("features", [])
    except Exception as e:
        body_txt = ""
        try:
            body_txt = e.read().decode()[:200]
        except Exception:
            pass
        print("    (catalog gagal: %s %s)" % (e, body_txt))
        return None, None
    if not feats:
        print("    (catalog: tidak ada scene dalam rentang)")
        return None, None

    def cc_of(f):
        v = f.get("properties", {}).get("eo:cloud_cover")
        return 999.0 if v is None else v

    def dt_of(f):
        return f.get("properties", {}).get("datetime", "")

    if mode == "mostRecent":
        f = max(feats, key=dt_of)
    else:
        f = min(feats, key=cc_of)

    p = f.get("properties", {})
    d = (p.get("datetime") or "")[:10]
    label = None
    if len(d) == 10 and d.count("-") == 2:
        y, m, day = d.split("-")
        label = "%d %s %s" % (int(day), MONTHS[int(m)], y)
    cc = p.get("eo:cloud_cover")
    return label, (round(cc) if cc is not None else None)


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


def finalize(path, lines, factor):
    """Perbesar tajam (nearest) + cap beberapa baris tanggal di pojok kiri-bawah."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.resize((w * factor, h * factor), Image.NEAREST)
    W, H = im.size
    d = ImageDraw.Draw(im)
    fs = max(15, W // 34)
    font = load_font(fs)
    pad = fs // 2
    gap = max(3, int(fs * 0.3))
    widths = []
    for ln in lines:
        try:
            widths.append(int(d.textlength(ln, font=font)))
        except Exception:
            widths.append(fs * len(ln) // 2)
    n = len(lines)
    box_w = max(widths) + 2 * pad
    box_h = n * fs + (n - 1) * gap + 2 * pad
    d.rectangle([0, H - box_h, box_w, H], fill=(0, 0, 0))
    y = H - box_h + pad
    for ln in lines:
        d.text((pad, y), ln, fill=(255, 255, 255), font=font)
        y += fs + gap
    im.save(path)


def build_viewer(paths, metas, stamp, ver, out_dir, day):
    os.makedirs("latest", exist_ok=True)
    for p in paths:
        if p:
            shutil.copyfile(p, os.path.join("latest", os.path.basename(p)))
    meta_obj = {"date": day, "stamp": stamp}
    meta_obj["images"] = {}
    for name, m in metas.items():
        meta_obj["images"][name] = {"sat": m.get("sat"), "cloud": m.get("cloud")}
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta_obj, f, ensure_ascii=False)
    snaps = []
    base = "citra"
    if os.path.isdir(base):
        for d in sorted(os.listdir(base), reverse=True):
            ddir = os.path.join(base, d)
            if not os.path.isdir(ddir):
                continue
            saved = {}
            mp = os.path.join(ddir, "meta.json")
            if os.path.exists(mp):
                try:
                    saved = json.load(open(mp, encoding="utf-8")).get("images", {})
                except Exception:
                    saved = {}
            imgs = {}
            for key in LAYER_KEYS:
                if os.path.exists(os.path.join(ddir, key)):
                    info = saved.get(key, {})
                    imgs[key] = {"sat": info.get("sat"), "cloud": info.get("cloud")}
            if imgs:
                snaps.append({"date": d, "label": nice_date(d), "dir": "citra/" + d, "images": imgs})
    data = {
        "updated": stamp,
        "plot": "Rawang Air Putih (%.5f, %.5f)" % (LAT, LON),
        "ver": ver,
        "layers": [{"key": k, "title": TITLES[k]} for k in LAYER_KEYS],
        "snapshots": snaps,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(HTML_TEMPLATE)
    with open("manifest.json", "w", encoding="utf-8") as f:
        f.write(MANIFEST)
    print("Dashboard diperbarui (%d snapshot)." % len(snaps))


def send_email(paths):
    to = os.environ.get("MAIL_TO", "").strip()
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port_raw = os.environ.get("SMTP_PORT", "587").strip()
    port = int(port_raw) if port_raw.isdigit() else 587
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not (to and user and pw):
        print("(email dilewati: MAIL_TO/SMTP_USER/SMTP_PASS belum diisi)")
        return
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
    today_lbl = "%d %s %d" % (now.day, MONTHS[now.month], now.year)
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
    metas = {}
    for name, ev, days, mos in jobs:
        print("  -> " + name)
        date_lbl, cc = scene_info(token, days, mos)
        p = fetch(token, ev, days, mos, os.path.join(out_dir, name), native_px)
        if p:
            cap = "Satelit: " + (date_lbl or "?")
            if cc is not None:
                cap += " (awan %d%%)" % cc
            proc = "Diproses: " + today_lbl
            finalize(p, [cap, proc], factor)
            metas[name] = {"sat": date_lbl, "cloud": cc}
            print("    [ok] %s (%s | %s)" % (name, cap, proc))
        paths.append(p)
    ok = len([p for p in paths if p])
    print("Tersimpan %d/4 di %s" % (ok, out_dir))
    build_viewer(paths, metas, stamp, ver, out_dir, day)
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
header { padding:14px 16px; background:#1b5e20; }
header h1 { margin:0; font-size:16px; }
header p { margin:4px 0 0; font-size:12px; opacity:.85; }
nav { display:flex; background:#144024; position:sticky; top:0; z-index:5; }
nav button { flex:1; padding:13px 6px; background:none; border:none; color:#cfe8cf; font-size:14px; border-bottom:3px solid transparent; cursor:pointer; }
nav button.active { color:#fff; border-bottom-color:#7ed957; font-weight:600; }
.card { margin:14px; background:#15321f; border-radius:14px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.35); }
.card h2 { font-size:15px; margin:0; padding:12px 14px 2px; }
.cap { font-size:12px; opacity:.8; padding:0 14px 8px; }
.card img, #h-view img, .compare img { width:100%; display:block; image-rendering:pixelated; }
.controls { display:flex; gap:8px; flex-wrap:wrap; padding:14px; }
.controls select { flex:1; min-width:120px; padding:10px; border-radius:10px; border:none; background:#0f2417; color:#eaf5ea; font-size:14px; }
#h-view { margin:0 14px 14px; background:#15321f; border-radius:14px; overflow:hidden; }
#h-view .cap { padding:12px 14px; }
.compare { display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:0 14px 14px; }
.compare > div { background:#15321f; border-radius:12px; overflow:hidden; }
.compare .cap { padding:8px 10px 2px; font-weight:600; opacity:1; }
.compare .sub { font-size:11px; opacity:.75; padding:0 10px 8px; }
.legend { margin:14px; padding:14px; background:#15321f; border-radius:14px; font-size:13px; line-height:1.8; }
.sw { display:inline-block; width:13px; height:13px; border-radius:3px; margin-right:7px; vertical-align:middle; }
footer { text-align:center; font-size:12px; opacity:.6; padding:20px; }
</style>
</head>
<body>
<header>
<h1>🛰️ Kebun Sawit — Rawang Air Putih</h1>
<p><span id="plot"></span> · diperbarui: <span id="updated"></span></p>
</header>
<nav>
<button id="btn-latest" class="active">Terbaru</button>
<button id="btn-history">Riwayat</button>
<button id="btn-compare">Banding</button>
</nav>
<main>
<section id="tab-latest"><div id="latest-cards"></div></section>
<section id="tab-history" hidden>
<div class="controls">
<select id="h-layer"></select>
<select id="h-date"></select>
</div>
<div id="h-view"></div>
</section>
<section id="tab-compare" hidden>
<div class="controls">
<select id="c-layer"></select>
<select id="c-date-a"></select>
<select id="c-date-b"></select>
</div>
<div class="compare"><div id="c-a"></div><div id="c-b"></div></div>
</section>
</main>
<div class="legend">
<b>Cara baca NDVI:</b><br>
<span class="sw" style="background:#00591a"></span> Hijau tua — rimbun / sehat<br>
<span class="sw" style="background:#4caf50"></span> Hijau muda — sedang<br>
<span class="sw" style="background:#f2c032"></span> Kuning — lemah<br>
<span class="sw" style="background:#d93521"></span> Merah — stres / gundul<br>
<span class="sw" style="background:#bfbfbf"></span> Abu — air / tanah basah
</div>
<footer>Otomatis dari Sentinel-2 · Copernicus · tap gambar untuk perbesar</footer>
<script>
var DATA=null;
function q(s){ return document.querySelector(s); }
function ver(){ return (DATA && DATA.ver) ? DATA.ver : ''; }
function src(snap,key){ return snap.dir + '/' + key + '?v=' + ver(); }
function capOf(snap,key){
  var i = snap.images[key] || {};
  var t = 'Satelit: ' + (i.sat || '?');
  if(i.cloud != null){ t += ' (awan ' + i.cloud + '%)'; }
  return t;
}
function mkOpt(sel,val,txt){
  var o = document.createElement('option');
  o.value = val; o.textContent = txt; sel.appendChild(o);
}
function imgLink(snap,key){
  var a = document.createElement('a');
  a.href = src(snap,key); a.target = '_blank';
  var im = document.createElement('img'); im.src = src(snap,key); im.alt = key;
  a.appendChild(im); return a;
}
function showTab(name){
  ['latest','history','compare'].forEach(function(t){
    q('#tab-'+t).hidden = (t !== name);
    q('#btn-'+t).classList.toggle('active', t === name);
  });
}
function findSnap(date){
  for(var i=0;i<DATA.snapshots.length;i++){ if(DATA.snapshots[i].date === date){ return DATA.snapshots[i]; } }
  return null;
}
function renderLatest(){
  var wrap = q('#latest-cards'); wrap.innerHTML = '';
  if(!DATA.snapshots.length){ wrap.textContent = 'Belum ada citra.'; return; }
  var snap = DATA.snapshots[0];
  DATA.layers.forEach(function(L){
    if(!snap.images[L.key]){ return; }
    var card = document.createElement('div'); card.className = 'card';
    var h = document.createElement('h2'); h.textContent = L.title; card.appendChild(h);
    var c = document.createElement('div'); c.className = 'cap'; c.textContent = capOf(snap,L.key); card.appendChild(c);
    card.appendChild(imgLink(snap,L.key));
    wrap.appendChild(card);
  });
}
function renderHistory(){
  var layer = q('#h-layer').value, date = q('#h-date').value;
  var snap = findSnap(date); var box = q('#h-view'); box.innerHTML = '';
  if(!snap){ return; }
  if(!snap.images[layer]){ box.textContent = 'Tidak ada gambar ini pada tanggal tsb.'; return; }
  var c = document.createElement('div'); c.className = 'cap';
  c.textContent = snap.label + ' — ' + capOf(snap,layer); box.appendChild(c);
  box.appendChild(imgLink(snap,layer));
}
function renderCompare(){
  var layer = q('#c-layer').value;
  ['a','b'].forEach(function(side){
    var date = q('#c-date-'+side).value; var snap = findSnap(date);
    var box = q('#c-'+side); box.innerHTML = '';
    if(!snap || !snap.images[layer]){ box.textContent = '—'; return; }
    var c = document.createElement('div'); c.className = 'cap'; c.textContent = snap.label; box.appendChild(c);
    box.appendChild(imgLink(snap,layer));
    var s2 = document.createElement('div'); s2.className = 'sub'; s2.textContent = capOf(snap,layer); box.appendChild(s2);
  });
}
function fillControls(){
  [q('#h-layer'), q('#c-layer')].forEach(function(sel){
    DATA.layers.forEach(function(L){ mkOpt(sel, L.key, L.title); });
  });
  [q('#h-date'), q('#c-date-a'), q('#c-date-b')].forEach(function(sel){
    DATA.snapshots.forEach(function(s){ mkOpt(sel, s.date, s.label); });
  });
  if(DATA.snapshots.length > 1){ q('#c-date-a').selectedIndex = 1; }
  q('#c-date-b').selectedIndex = 0;
}
function init(){
  q('#updated').textContent = DATA.updated || '';
  q('#plot').textContent = DATA.plot || '';
  fillControls();
  renderLatest(); renderHistory(); renderCompare();
  q('#btn-latest').onclick = function(){ showTab('latest'); };
  q('#btn-history').onclick = function(){ showTab('history'); };
  q('#btn-compare').onclick = function(){ showTab('compare'); };
  q('#h-layer').onchange = renderHistory; q('#h-date').onchange = renderHistory;
  q('#c-layer').onchange = renderCompare;
  q('#c-date-a').onchange = renderCompare; q('#c-date-b').onchange = renderCompare;
}
fetch('data.json?t=' + Date.now()).then(function(r){ return r.json(); }).then(function(d){ DATA = d; init(); }).catch(function(e){ document.body.insertAdjacentHTML('beforeend', '<p style="padding:16px">Gagal memuat data.json: ' + e + '</p>'); });
</script>
</body>
</html>
"""

MANIFEST = '{"name":"Kebun Sawit","short_name":"Sawit","start_url":".","display":"standalone","background_color":"#0f2417","theme_color":"#1b5e20","icons":[]}'


if __name__ == "__main__":
    main()
