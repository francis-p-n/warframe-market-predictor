"""
notifier.py — Discord webhook notifier with rich embeds.

Setup (30 seconds):
  1. Open your Discord server → pick a channel → Edit Channel
  2. Integrations → Webhooks → New Webhook → Copy URL
  3. Paste it into DISCORD_WEBHOOK_URLS in your .env

Multiple channels: comma-separate the URLs to post to several channels at once.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

import config
from analyzer import AnalysisReport, ItemSignal

log = logging.getLogger(__name__)

# Discord embed colour codes
COLORS = {
    "BUY":     0x57F287,   # green
    "SELL":    0xED4245,   # red
    "HOLD":    0xFEE75C,   # yellow
    "DEFAULT": 0x5865F2,   # blurple
    "INFO":    0x3BA55C,
}

BOT_NAME   = "Warframe Market Bot"
BOT_AVATAR = "https://warframe.market/favicon.ico"


# ─── Core HTTP ────────────────────────────────────────────────────────────────

def _post(url: str, payload: dict) -> bool:
    try:
        resp = httpx.post(url, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            log.info("Discord message delivered.")
            return True
        log.error("Discord HTTP %d: %s", resp.status_code, resp.text[:300])
        return False
    except httpx.RequestError as exc:
        log.error("Discord request failed: %s", exc)
        return False


def _broadcast(payload: dict) -> bool:
    """Send to ALL configured webhook URLs."""
    if not config.DISCORD_WEBHOOK_URLS:
        log.error("No DISCORD_WEBHOOK_URLS set in .env")
        return False
    results = [_post(url, payload) for url in config.DISCORD_WEBHOOK_URLS]
    log.info("Broadcast: %d/%d webhooks succeeded.", sum(results), len(results))
    return all(results)


# ─── Embed Builders ───────────────────────────────────────────────────────────

def _signal_field(sig: ItemSignal) -> dict:
    """
    Build a Discord embed field for one item signal.
    Shows price context and the plain-English explanation — no jargon.
    """
    mom_arrow = "▲" if sig.momentum_pct >= 0 else "▼"
    mom_sign  = "+" if sig.momentum_pct >= 0 else ""

    # Price bar: show where current price sits in the 30d range
    price_range = sig.high_30d - sig.low_30d
    if price_range > 0:
        pct_in_range = (sig.current_price - sig.low_30d) / price_range
        filled = round(pct_in_range * 10)
        bar = "█" * filled + "░" * (10 - filled)
        bar_label = f"`{sig.low_30d:.0f}p [{bar}] {sig.high_30d:.0f}p`"
    else:
        bar_label = f"`{sig.current_price:.0f}p`"

    value = (
        f"**{sig.current_price:.0f}p**  {mom_arrow} {mom_sign}{sig.momentum_pct:.1f}% vs avg  "
        f"· RSI {sig.rsi:.0f}  · vol {sig.vol_ratio:.1f}x\n"
        f"{bar_label}\n"
        f"*{sig.detail}*"
    )
    return {"name": f"{'🟢' if sig.signal=='BUY' else '🔴' if sig.signal=='SELL' else '🟡'} {sig.item_name}", "value": value, "inline": False}


def _section_embed(
    title: str,
    signals: list[ItemSignal],
    color: int,
    empty_text: str,
) -> list[dict]:
    """
    Discord allows max 25 fields per embed and max 6000 chars total.
    Split into multiple embeds if needed (10 items × ~200 chars each is fine in one).
    """
    if not signals:
        return [{"title": title, "description": f"*{empty_text}*", "color": color}]

    # Split into batches of 10 (Discord's 25-field limit is never hit at 10)
    embeds = []
    for batch_start in range(0, len(signals), 10):
        batch = signals[batch_start: batch_start + 10]
        embed: dict = {
            "color":  color,
            "fields": [_signal_field(s) for s in batch],
        }
        if batch_start == 0:
            embed["title"] = title
        embeds.append(embed)

    return embeds


# ─── Report Builder ───────────────────────────────────────────────────────────

def build_message(report: AnalysisReport) -> list[dict]:
    """Build the full list of Discord embeds for a daily report."""
    today = datetime.now().strftime("%A, %B %d")

    header = {
        "title":       f"📊 Warframe Market — {today}",
        "description": (
            f"Scanned **{report.total_scanned}** items, found **{report.total_signals}** signals today.\n"
            f"*Model: {report.model_used} · Prices in platinum (p)*"
        ),
        "color": COLORS["DEFAULT"],
        "footer": {"text": "Prices from warframe.market · Next report at 9 AM"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    embeds = [header]
    embeds += _section_embed(
        "🟢 Best Buys  —  price at or near the bottom, likely to recover",
        report.buys,
        COLORS["BUY"],
        "No clear buy opportunities today. Check back tomorrow.",
    )
    embeds += _section_embed(
        "🔴 Sell Now  —  price near peak, likely to drop",
        report.sells,
        COLORS["SELL"],
        "Nothing looks overpriced today.",
    )
    embeds += _section_embed(
        "🟡 Hold On  —  market is quiet, don't panic-sell",
        report.holds,
        COLORS["HOLD"],
        "Nothing needs patience-watching today.",
    )

    return embeds


# ─── Public API ───────────────────────────────────────────────────────────────

def send_daily_report(report: AnalysisReport) -> bool:
    if report.total_scanned == 0:
        log.warning("Report skipped — no data collected yet.")
        return False

    embeds = build_message(report)

    # Discord: max 10 embeds per webhook POST
    success = True
    for i in range(0, len(embeds), 10):
        batch   = embeds[i: i + 10]
        payload = {
            "username":   BOT_NAME,
            "avatar_url": BOT_AVATAR,
            "embeds":     batch,
        }
        if not _broadcast(payload):
            success = False

    return success


def send_test_message() -> bool:
    payload = {
        "username":   BOT_NAME,
        "avatar_url": BOT_AVATAR,
        "embeds": [{
            "title":       "✅ Warframe Market Predictor — Connected",
            "description": (
                "Push notifications are working correctly!\n"
                "The daily market report will appear in this channel at **9 AM** every morning.\n\n"
                "**What you'll see each day:**\n"
                "🟢 Best items to buy (caught at the price trough)\n"
                "🔴 Items at peak price to sell\n"
                "🟡 Items that look bad but are just in a quiet patch"
            ),
            "color": COLORS["BUY"],
            "footer": {"text": "warframe-market-predictor"},
        }],
    }
    return _broadcast(payload)
