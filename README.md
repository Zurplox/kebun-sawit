# 🛰️ Kebun Sawit — Satellite Monitoring System

Automated daily satellite monitoring system for palm plantations using **Sentinel-2 imagery** from Copernicus Dataspace. Tracks vegetation health, moisture content, and nutrient levels with interactive web dashboard.

**Live monitoring:** [GitHub Pages Dashboard](https://Zurplox.github.io/kebun-sawit/) | **Plot:** Rawang Air Putih (0.81573°N, 101.96621°E)

---

## Features

📊 **6-Layer Satellite Analysis**
- **True Color** — Natural RGB imagery at 10m resolution
- **NDVI** — Normalized Difference Vegetation Index (plant health)
- **NDMI** — Normalized Difference Moisture Index (water content)
- **NDRE** — Normalized Difference Red Edge Index (nutrient status)
- Cloud-free variants for consistent analysis

🔄 **Automated Daily Updates**
- Runs daily via GitHub Actions (00:00 UTC+8)
- Pulls latest 4 Sentinel-2 scene types for your plot
- Auto-commits imagery and metadata to repository
- Backfills historical data for analysis

🎬 **Timelapse Animations**
- GIF animations tracking vegetation changes over time
- Separate tracks for color and NDVI data
- Up to 120 frames per animation

📱 **Interactive Web Dashboard**
- View latest captures with metadata (acquisition date, cloud %)
- Browse complete historical archive
- Compare two dates side-by-side
- Watch animated timelapse
- Health alerts when vegetation shows significant decline
- PWA (Progressive Web App) support

📈 **Health Monitoring**
- Tracks average NDVI over time
- Alerts on NDVI drops ≥0.08 from 3-observation average
- 12-month rolling health history (JSON format)

🌧️ **Weather Integration**
- 10-day rainfall totals from Open-Meteo API
- Correlate vegetation stress with precipitation patterns

---

## Repository Structure

```
.
├── sawit_satelit.py          # Main Python processor
├── .github/workflows/sawit.yml # Daily scheduler (GitHub Actions)
├── index.html                # Web dashboard (auto-generated)
├── data.json                 # Dashboard data + metadata (auto-generated)
├── manifest.json             # PWA manifest
├── citra/                    # Historical satellite images
│   ├── YYYY-MM-DD/           # Date-organized folders
│   │   ├── 1_warna_asli_terbaru.png
│   │   ├── 2_ndvi_terbaru.png
│   │   ├── 3_warna_asli_bebas_awan.png
│   │   ├── 4_ndvi_bebas_awan.png
│   │   ├── 5_ndmi_terbaru.png
│   │   ├── 6_ndre_terbaru.png
│   │   ├── meta.json         # Metadata (date, cloud %, rainfall)
│   │   └── .geo              # Geolocation signature (anti-drift)
│   └── ...
├── latest/                   # Symlinked copies of latest images
├── timelapse_warna.gif       # True color timelapse
├── timelapse_ndvi.gif        # NDVI timelapse
├── ndvi_history.json         # Health tracking (rolling 12 months)
└── README.md
```

---

## Quick Start

### 1. **Clone the Repository**

```bash
git clone https://github.com/Zurplox/kebun-sawit.git
cd kebun-sawit
```

### 2. **Set Up Secrets** (GitHub Repository Settings)

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description | Source |
|--------|-------------|--------|
| `SH_CLIENT_ID` | Sentinel Hub client ID | [Register at Copernicus Dataspace](https://dataspace.copernicus.eu/) |
| `SH_CLIENT_SECRET` | Sentinel Hub client secret | ↑ same |
| `MAIL_TO` *(optional)* | Email recipient | Your email address |
| `SMTP_HOST` *(optional)* | SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` *(optional)* | SMTP port | `587` |
| `SMTP_USER` *(optional)* | SMTP username | Gmail address |
| `SMTP_PASS` *(optional)* | SMTP app password | [Generate here](https://myaccount.google.com/apppasswords) |

### 3. **Configure Your Plot** (`.github/workflows/sawit.yml`)

Edit the environment variables in the workflow file:

```yaml
env:
  PLOT_LAT: "0.81573"      # Your plot's latitude
  PLOT_LON: "101.96621"    # Your plot's longitude
  BOX_HALF_M: "750"        # Search radius in meters (750m = 1.5km box)
```

### 4. **Enable GitHub Pages** (Optional)

1. Go to **Settings → Pages**
2. Set source to `Deploy from a branch`
3. Select `main` branch, `/root` folder
4. Save
5. Dashboard will be live at `https://<username>.github.io/kebun-sawit/`

### 5. **Run Manually** (First Time)

Go to **Actions** tab → **Citra Sawit Harian** → **Run workflow** (test run)

Or via CLI:
```bash
export SH_CLIENT_ID=your_id
export SH_CLIENT_SECRET=your_secret
export PLOT_LAT=0.81573
export PLOT_LON=101.96621
export BOX_HALF_M=750
python sawit_satelit.py
```

---

## How It Works

### Daily Workflow (`sawit.yml`)

1. **Checkout** repository
2. **Setup Python 3.12** + Pillow
3. **Authenticate** with Sentinel Hub (Copernicus Dataspace)
4. **Query Catalog** for available Sentinel-2 scenes in last 20 days
5. **Process 6 layers:**
   - Latest + cloud-free true color (RGB)
   - Latest + cloud-free NDVI (vegetation)
   - Cloud-free NDMI & NDRE (advanced analysis)
6. **Generate metadata:** acquisition date, cloud %, rainfall
7. **Create dashboard:** update `data.json`, `index.html`
8. **Build animations:** GIF timelapses (warna + ndvi)
9. **Commit & push** all changes
10. *(Optional)* **Email 4 images** if configured

### Image Processing (`sawit_satelit.py`)

- **Resolution:** Native 10m/pixel (Sentinel-2 VIS bands)
- **Enlargement:** 4× upscaling (nearest-neighbor) for visibility
- **Overlays:** Date, cloud %, rainfall stamped at bottom-left
- **NDVI calculation:** `(NIR - Red) / (NIR + Red)` with color-coded output
- **Index-specific bands:**
  - NDVI: B04 (red), B08 (NIR)
  - NDMI: B08 (NIR), B11 (SWIR)
  - NDRE: B05 (red edge), B08 (NIR)

### Health Alerting (`ndvi_history.json`)

Tracks NDVI average and flags drops:
- **Baseline:** Mean of last 3 valid NDVI observations
- **Alert threshold:** Drop ≥ 0.08 from baseline
- **Format:** JSON array with `date`, `ndvi`, `alert` (if triggered)

---

## Dashboard Navigation

| Tab | Purpose |
|-----|---------|
| **Terbaru** (Latest) | 6 most recent satellite images with metadata |
| **Riwayat** (History) | Browse any layer across all recorded dates |
| **Banding** (Compare) | Side-by-side comparison of two dates |
| **Animasi** (Animation) | GIF timelapse loops (true color & NDVI) |

**Legend:**
- 🟢 Dark Green (NDVI >0.8) — Healthy, dense vegetation
- 🟢 Light Green (NDVI 0.6–0.8) — Good condition
- 🟡 Yellow (NDVI 0.4–0.6) — Moderate stress
- 🔴 Red (NDVI 0.2–0.4) — Significant stress
- ⚫ Gray (NDVI <0) — Water, bare soil, or clouds

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PLOT_LAT` | 0.81500 | Plot latitude (WGS84) |
| `PLOT_LON` | 101.96617 | Plot longitude (WGS84) |
| `BOX_HALF_M` | 600 | Search radius in meters |
| `LATEST_DAYS` | 20 | Days to search for latest imagery |
| `CLOUDFREE_DAYS` | 60 | Days to search for cloud-free scenes |
| `NDVI_ALERT_DROP` | 0.08 | NDVI drop threshold for alerts |
| `TIMELAPSE_MAX_FRAMES` | 120 | Max frames per GIF animation |

### Constants in Code

- **Native resolution:** 10 m/pixel
- **Output scaling:** 4× (40 m/pixel final)
- **Imagery source:** Sentinel-2 L2A (bottom-of-atmosphere)
- **Authentication:** OAuth 2.0 (Copernicus Identity)

---

## Example Output

### Latest Snapshot (Terbaru Tab)

```
Warna Asli — Terbaru
Satelit: 4 Jul 2026 (awan 12%)

NDVI (Kesehatan) — Terbaru
Satelit: 4 Jul 2026 (awan 12%)
Hujan 10hr: 42 mm
Diproses: 4 Jul 2026

...+ 4 more layers
```

### Health Alert

```
⚠️ NDVI turun 0.095 (0.712 → 0.617) sejak 2026-07-02
```

or if stable:

```
✅ NDVI rata-rata plot: 0.693 (stabil)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Workflow fails: "Gagal login"** | Check `SH_CLIENT_ID`, `SH_CLIENT_SECRET` are correct and secrets are properly set in GitHub Settings |
| **No scenes found** | Sentinel-2 revisit is 5 days. Adjust `LATEST_DAYS` or `CLOUDFREE_DAYS` if your area is cloudy |
| **Images very cloudy** | This is inherent to optical satellites. NDMI/NDRE layers use cloud-free filter; true color shows latest available |
| **Dashboard not updating** | Check **Actions** tab for workflow run logs. Verify `SH_CLIENT_SECRET` doesn't have trailing spaces |
| **Email not sending** | Enable "Less secure apps" or use Gmail app password (not account password). Check `SMTP_PORT` (usually 587 for TLS) |
| **Geolocation drifting** | System stores `.geo` signature per date folder to prevent shifts. If coordinates change, old folders marked for refresh |

---

## API & Data Format

### `data.json` Schema

```json
{
  "updated": "04 Jul 2026, 08:30 WIB",
  "plot": "Rawang Air Putih (0.81573, 101.96621)",
  "ver": "202607040830",
  "layers": [
    { "key": "1_warna_asli_terbaru.png", "title": "Warna Asli — Terbaru" },
    ...
  ],
  "snapshots": [
    {
      "date": "2026-07-04",
      "label": "4 Jul 2026",
      "dir": "citra/2026-07-04",
      "images": {
        "1_warna_asli_terbaru.png": {
          "sat": "4 Jul 2026",
          "cloud": 12,
          "rain": 42
        },
        ...
      }
    },
    ...
  ],
  "health": {
    "current": 0.693,
    "series": [
      { "date": "2026-06-20", "ndvi": 0.701 },
      ...
    ],
    "alert": null
  },
  "timelapse": {
    "warna": "timelapse_warna.gif?v=202607040830",
    "ndvi": "timelapse_ndvi.gif?v=202607040830"
  }
}
```

### `ndvi_history.json` Schema

```json
[
  { "date": "2026-06-20", "ndvi": 0.701 },
  { "date": "2026-06-22", "ndvi": 0.695 },
  { "date": "2026-06-24", "ndvi": 0.708 },
  { "date": "2026-07-04", "ndvi": 0.693 }
]
```

---

## Performance & Costs

| Factor | Notes |
|--------|-------|
| **Sentinel-2 imagery** | Free (ESA/Copernicus) |
| **Sentinel Hub API** | Free tier available (1000 req/month) |
| **GitHub Actions** | Free (Linux runner, 2000 min/month for public repos) |
| **GitHub Pages hosting** | Free |
| **Open-Meteo weather** | Free (no key required) |
| **Email (optional)** | Free with Gmail |

**Storage:** ~30 MB/image × 4-6 new images/month = ~150 MB/month

---

## Changelog

### v1.0.0 (2026-07-04)

- ✅ Initial release
- ✅ Daily Sentinel-2 monitoring
- ✅ 6-layer spectral analysis (RGB, NDVI, NDMI, NDRE)
- ✅ Interactive web dashboard with history & compare
- ✅ Timelapse animations
- ✅ Health tracking with alerts
- ✅ Weather integration (rainfall)
- ✅ Email notifications (optional)

---

## Contributing

Pull requests welcome! Areas for enhancement:

- [ ] Multi-plot support
- [ ] Crop stress early warning system
- [ ] Machine learning classification (ripe vs. unripe fruit)
- [ ] Mobile app (React Native)
- [ ] WebGL tile viewer
- [ ] Export to GeoTIFF format

---

## License

MIT License — See LICENSE file

---

## Resources

- [Sentinel Hub Documentation](https://docs.sentinel-hub.com/)
- [Copernicus Dataspace](https://dataspace.copernicus.eu/)
- [Sentinel-2 Band Info](https://en.wikipedia.org/wiki/Copernicus_Programme#Sentinel-2)
- [NDVI Guide](https://en.wikipedia.org/wiki/Normalized_difference_vegetation_index)
- [Open-Meteo Free Weather API](https://open-meteo.com/)

---

**Built with ❤️ by HS for agricultural monitoring** — Automated via GitHub Actions, visualized with vanilla JS, powered by Copernicus satellite data.
