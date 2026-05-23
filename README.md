# 📊 Warframe Market Predictor

> A lightweight Python background service that tracks real-time prices on [Warframe.market](https://warframe.market), runs statistical trend analysis, and sends a daily **push notification** (via [ntfy.sh](https://ntfy.sh) — free, forever) with the best items to buy, sell, or hold.

---

## What it does

Warframe has a player-driven economy with thousands of tradable items. Prices fluctuate daily based on supply, demand, game updates, and player activity. This tool monitors those prices automatically and tells you when to act.

Every morning at 9 AM, you get a push notification on your phone:

```
Warframe Market May 24 — 2 buys, 1 sell, 1 hold

## Buy Signals
**Rhino Prime Set** — 145p  *(30d avg 172p, -15.7%, conf 81%)*
  Price dip (-15.7% vs 30d avg) with rising 7d trend (+0.6%/day). Volume 2.1x normal.

## Sell Signals
**Ignis Wraith Blueprint** — 8p  *(30d avg 5p, +60.0%, conf 74%)*
  Price peaked (+60.0% above 30d avg), now falling (-0.8%/day). Volume 1.3x normal.

## Hold — Wait
**Mesa Prime Chassis** — 18p  *(30d avg 22p, -18.2%, conf 67%)*
  Price softening (-0.4%/day) but volume is low (0.4x 30d avg) — likely a temp dip.

*847 items scanned — 12 signals generated*
```

---

## Features

- **Free forever** — uses [ntfy.sh](https://ntfy.sh), zero accounts or API keys needed
- **Share with friends** — anyone who subscribes to your topic name gets the same alerts
- **Auto-tracks top 50 items by trading volume** — no manual setup needed
- **Custom watchlist** — pin any specific items you care about
- **5-metric trend analysis** — slope, momentum, volume trend, volatility, moving averages
- **Extremely lightweight** — ~35 MB RAM, SQLite storage, no cloud dependencies
- **Rate-limited API access** — stays well within warframe.market limits (2 req/s)
- **Auto-recovers** — coalesces missed jobs if your PC was asleep

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Storage | SQLite (WAL mode) |
| Scheduler | APScheduler |
| HTTP client | httpx |
| Notifications | ntfy.sh (free push notifications) |
| Trend analysis | NumPy linear regression |
| Config | python-dotenv |

---

## Quick Start

### 1. Install the ntfy app

- **Android**: [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
- **iOS**: [App Store](https://apps.apple.com/app/ntfy/id1625396347)
- **Web**: `https://ntfy.sh/<your-topic>`

### 2. Choose a secret topic name

Pick something hard to guess — it's your notification "password":
```
warframe-predictor-k9x2mq7p
```
In the ntfy app, tap **+** and subscribe to it.

### 3. Install dependencies

```bash
pip install -r requirements.txt
conda install numpy          # or: pip install numpy --only-binary=:all:
```

### 4. Configure

```bash
copy .env.example .env
```

Edit `.env` — set your topic name:
```env
NTFY_TOPIC=warframe-predictor-k9x2mq7p
```

### 5. Test and run

```bash
python main.py --test-notify    # push notification should appear on your phone
python main.py                  # start the background service
```

---

## Sharing with friends (group notifications)

ntfy works like a private channel — anyone who subscribes to your topic receives all notifications. Just share your `NTFY_TOPIC` value with friends and have them subscribe in the ntfy app. No accounts, no invites, completely free.

---

## CLI Commands

```bash
python main.py                          # Start background service
python main.py --test-notify            # Test push notification
python main.py --run-report             # Send report right now
python main.py --fetch-now              # Trigger data fetch
python main.py --refresh-items          # Re-download full item list
python main.py --search "rhino prime"   # Find items by name
python main.py --watchlist-add "Adaptation"   # Add to watchlist
python main.py --watchlist              # View watchlist
python main.py --status                 # Database stats
```

---

## How Signals Work

| Signal | Condition |
|---|---|
| 🟢 **BUY** | 7-day slope > +0.3%/day AND price > 3% below 30-day MA |
| 🔴 **SELL** | 7-day slope < -0.3%/day AND price > 3% above 30-day MA AND volume ≥ 70% of normal |
| 🟡 **HOLD** | Slope negative AND volume < 60% of normal (low-activity dip, not a crash) |

Only signals above **55% confidence** are included in reports (configurable via `MIN_SIGNAL_CONFIDENCE`).

---

## Running as a Background Service (Windows)

**Task Scheduler (built-in):**
1. Open Task Scheduler → Create Basic Task
2. Trigger: **At log on**
3. Action: `python` with argument path to `main.py`

**NSSM (recommended — always-on service):**
```bash
# Download nssm from https://nssm.cc/
nssm install WarframePredictor python "C:\path\to\main.py"
nssm start WarframePredictor
```

---

## Resource Usage

| Resource | Usage |
|---|---|
| RAM | ~35–60 MB (idle) |
| CPU | < 0.1% between fetch cycles |
| Disk | ~5–20 MB per month |
| Network | ~2–4 MB per fetch cycle (every 4h) |

---

## Data & Privacy

All data is stored **locally** in `data/warframe_prices.db` (SQLite).
ntfy notifications are sent over HTTPS. Your topic name acts as a private token.
For full privacy, you can [self-host ntfy](https://docs.ntfy.sh/install/) and set `NTFY_SERVER` in `.env`.

---

## License

MIT
