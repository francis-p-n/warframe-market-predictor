# 📊 Warframe Market Predictor

A lightweight Python background service that monitors [Warframe.market](https://warframe.market) prices, runs trend analysis, and sends you a **daily WhatsApp summary** with the best buys, sells, and holds.

- 🟢 **BUY** — price dip with a rising trend (oversold, good entry point)
- 🔴 **SELL** — price peaked and falling (overbought, time to unload)
- 🟡 **HOLD** — price falling but volume is low (likely a temp dip, be patient)

---

## Requirements

- Python 3.11+
- A free [Twilio](https://twilio.com) account
- A WhatsApp account on your phone

---

## Setup (5 minutes)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up Twilio WhatsApp Sandbox (free)

1. Sign up at [twilio.com](https://twilio.com) — no credit card required for the sandbox
2. Go to **Console → Messaging → Try it out → Send a WhatsApp message**
3. Follow the instructions to join the sandbox by sending a code from your phone to Twilio's WhatsApp number (`+1 415 523 8886`)
4. Copy your **Account SID** and **Auth Token** from the Console dashboard

### 3. Configure `.env`

```bash
copy .env.example .env
```

Edit `.env` and fill in:
```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+60XXXXXXXXXX    # Your number, intl format
```

> **Malaysia example:** `whatsapp:+601XXXXXXXXX`  
> **USA example:** `whatsapp:+1XXXXXXXXXX`

### 4. Test your setup

```bash
python main.py --test-notify
```

You should receive a WhatsApp message within seconds.

### 5. Run the service

```bash
python main.py
```

On first launch it will automatically download the full Warframe item list (~3,000 items), then start collecting price data. The first daily report will arrive at 9 AM the next morning.

---

## Daily Commands

| Command | What it does |
|---|---|
| `python main.py` | Start the background service |
| `python main.py --test-notify` | Send a test WhatsApp message |
| `python main.py --run-report` | Run analysis + send report right now |
| `python main.py --fetch-now` | Trigger a data fetch immediately |
| `python main.py --refresh-items` | Re-download full item list |
| `python main.py --status` | Show database stats |

## Watchlist Commands

The service auto-tracks the top 50 items by trading volume. You can also pin specific items:

```bash
# Search for an item
python main.py --search "rhino prime"

# Add to your watchlist
python main.py --watchlist-add "Rhino Prime Set"

# View your watchlist
python main.py --watchlist

# Remove from watchlist
python main.py --watchlist-remove "Rhino Prime Set"
```

---

## How the Analysis Works

For each item, the service computes:

| Metric | Description |
|---|---|
| **Short slope** | 7-day linear regression slope (% per day) |
| **Long slope** | 30-day linear regression slope |
| **Momentum** | Current price vs 30-day moving average (% deviation) |
| **Volume trend** | Recent 7d volume vs 30d average (ratio) |
| **Volatility** | Coefficient of variation over 14 days |

**Signal rules:**
- 🟢 **BUY**: Short slope > +0.3%/day AND price > 3% below 30d average
- 🔴 **SELL**: Short slope < -0.3%/day AND price > 3% above 30d average AND volume ≥ 70% of normal
- 🟡 **HOLD**: Slope negative AND volume < 60% of normal (low-activity dip)

All signals include a **confidence score** (0–100%). Only signals above 55% confidence are reported. Tune `MIN_SIGNAL_CONFIDENCE` in `.env` to be stricter or more permissive.

---

## Running as a Background Service (Windows)

To keep it running after closing the terminal, create a scheduled task or use NSSM:

### Option A: Task Scheduler (built-in)
1. Open **Task Scheduler** → Create Basic Task
2. Set trigger: **At log on**
3. Action: **Start a program** → `python` with argument `"C:\path\to\main.py"` in the project directory

### Option B: NSSM (recommended for always-on)
```bash
# Download nssm from https://nssm.cc/
nssm install WarframePredictor python "C:\path\to\main.py"
nssm start WarframePredictor
```

---

## Resource Usage

- **RAM**: ~35–60 MB when idle
- **CPU**: Negligible (< 0.1% between fetch cycles)
- **Disk**: ~5–20 MB per month of price history
- **Network**: ~2–4 MB per fetch cycle (every 4 hours)

---

## Upgrading to Production WhatsApp

The Twilio sandbox requires you to re-join periodically. For a permanent setup:

1. Apply for a [Twilio WhatsApp Business number](https://www.twilio.com/whatsapp) (~$5/month)
2. Get Meta approval (usually takes 2–5 business days)
3. Update `TWILIO_WHATSAPP_FROM` in `.env` to your approved number

---

## Data & Privacy

All data is stored **locally** in `data/warframe_prices.db` (SQLite).  
No personal data is collected. Only public Warframe.market pricing data is fetched.

---

## License

MIT — do whatever you like with it.
