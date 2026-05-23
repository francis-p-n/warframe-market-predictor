# 📊 Warframe Market Predictor

> A lightweight Python background service that tracks real-time prices on [Warframe.market](https://warframe.market), runs statistical trend analysis, and sends a daily **WhatsApp summary** of the best items to buy, sell, or hold — completely hands-free.

---

## What it does

Warframe has a player-driven economy with thousands of tradable items. Prices fluctuate daily based on supply, demand, game updates, and player activity. This tool monitors those prices automatically and tells you when to act.

Every morning at 9 AM, you get a WhatsApp message like this:

```
📊 Warframe Market Daily — May 24, 2026

🟢 TOP BUYS (price dip, trend rising)
  • Rhino Prime Set — 145p  (30d avg 172p, -15.7%, confidence 81%)
    Price dip (-15.7% vs 30d avg) with rising 7d trend (+0.6%/day). Volume 2.1x normal.

🔴 TOP SELLS (at peak, trend falling)
  • Ignis Wraith Blueprint — 8p  (30d avg 5p, +60.0%, confidence 74%)
    Price peaked (+60.0% above 30d avg), now falling (-0.8%/day). Volume 1.3x normal.

🟡 HOLDS — WAIT (declining, low volume — likely temporary)
  • Mesa Prime Chassis — 18p  (30d avg 22p, -18.2%, confidence 67%)
    Price softening (-0.4%/day) but volume is low (0.4x 30d avg) — likely a low-activity dip.

📈 847 items scanned · 12 signals generated
```

---

## Features

- **Auto-tracks top 50 items by trading volume** — no manual setup needed
- **Custom watchlist** — pin any specific items you care about
- **5-metric trend analysis** — slope, momentum, volume trend, volatility, moving averages
- **Daily WhatsApp notifications** via Twilio (broadcast to multiple people)
- **Extremely lightweight** — ~35 MB RAM, SQLite storage, no cloud dependencies
- **Fully offline** — all data stored locally, only external calls are to Warframe.market API and Twilio
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
| Notifications | Twilio WhatsApp API |
| Trend analysis | NumPy linear regression |
| Config | python-dotenv |

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
conda install numpy          # or: pip install numpy --only-binary=:all:

# 2. Configure
copy .env.example .env       # fill in Twilio credentials & your WhatsApp number(s)

# 3. Verify notifications
python main.py --test-notify

# 4. Start the service
python main.py
```

See [README.md](README.md) for full setup guide including Twilio sandbox instructions.

---

## CLI Commands

```bash
python main.py                          # Start background service
python main.py --test-notify            # Test WhatsApp delivery
python main.py --run-report             # Send report right now
python main.py --fetch-now              # Trigger data fetch
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

Only signals above 55% confidence are included in reports (configurable).

---

## WhatsApp Group Support

WhatsApp's Business API doesn't support sending to native group chats. As a workaround, set `WHATSAPP_TO` to a comma-separated list of numbers — each person receives the daily report individually:

```env
WHATSAPP_TO=whatsapp:+601XXXXXXXXX,whatsapp:+601YYYYYYYYY
```

> Each recipient needs to join the Twilio sandbox once by sending the join code from their own WhatsApp.

---

## Disclaimer

This tool is for informational purposes only. Warframe market prices are unpredictable and no signal is guaranteed. Trade at your own risk.

---

## License

MIT
