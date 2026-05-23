"""
notifier.py — Send WhatsApp messages via Twilio.

Uses the Twilio WhatsApp Sandbox for free development usage.
For production, replace with a verified WhatsApp Business sender.
"""

import logging
from datetime import datetime

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

import config
from analyzer import AnalysisReport, ItemSignal

log = logging.getLogger(__name__)

# Twilio client (lazy-initialised on first use)
_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    return _client


def _send_whatsapp(body: str, to: str) -> bool:
    """
    Send a WhatsApp message to a single recipient via Twilio.
    Returns True on success, False on failure.
    """
    try:
        msg = _get_client().messages.create(
            from_=config.TWILIO_WHATSAPP_FROM,
            to=to,
            body=body,
        )
        log.info("WhatsApp sent to %s. SID: %s", to, msg.sid)
        return True
    except TwilioRestException as exc:
        log.error("Twilio error sending to %s: %s", to, exc)
        return False


def _broadcast(body: str) -> bool:
    """
    Send a message to ALL configured recipients.
    Returns True only if every send succeeded.
    """
    if not config.WHATSAPP_TO:
        log.error("No recipients configured in WHATSAPP_TO.")
        return False
    results = [_send_whatsapp(body, recipient) for recipient in config.WHATSAPP_TO]
    log.info("Broadcast: %d/%d recipients succeeded.", sum(results), len(results))
    return all(results)


# ─── Message Formatting ────────────────────────────────────────────────────────

def _format_signal_line(sig: ItemSignal) -> str:
    """Format a single item signal as a compact WhatsApp-friendly line."""
    price_str = f"{sig.current_price:.0f}p"
    avg_str   = f"{sig.avg_30d:.0f}p"
    mom_sign  = "+" if sig.momentum_pct >= 0 else ""
    conf_pct  = f"{sig.confidence * 100:.0f}%"
    return (
        f"  • *{sig.item_name}* — {price_str}  "
        f"(30d avg {avg_str}, {mom_sign}{sig.momentum_pct:.1f}%,  "
        f"confidence {conf_pct})\n"
        f"    _{sig.explanation}_"
    )


def build_daily_message(report: AnalysisReport) -> str:
    """Compose the full daily summary WhatsApp message."""
    today = datetime.now().strftime("%B %d, %Y")
    lines: list[str] = []

    lines.append(f"📊 *Warframe Market Daily — {today}*")
    lines.append("")

    # ── BUYs ──────────────────────────────────────────────────────────────────
    if report.buys:
        lines.append("🟢 *TOP BUYS* _(price dip, trend rising)_")
        for sig in report.buys:
            lines.append(_format_signal_line(sig))
    else:
        lines.append("🟢 *TOP BUYS* — No strong buy signals today.")
    lines.append("")

    # ── SELLs ─────────────────────────────────────────────────────────────────
    if report.sells:
        lines.append("🔴 *TOP SELLS* _(at peak, trend falling)_")
        for sig in report.sells:
            lines.append(_format_signal_line(sig))
    else:
        lines.append("🔴 *TOP SELLS* — No strong sell signals today.")
    lines.append("")

    # ── HOLDs ─────────────────────────────────────────────────────────────────
    if report.holds:
        lines.append("🟡 *HOLDS — WAIT* _(declining but low volume — likely temporary)_")
        for sig in report.holds:
            lines.append(_format_signal_line(sig))
    else:
        lines.append("🟡 *HOLDS* — Nothing flagged as a patience play today.")
    lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append(
        f"📈 _{report.total_scanned} items scanned · "
        f"{report.total_signals} signals generated_"
    )
    lines.append("_Next report tomorrow at 9 AM. Reply STOP to unsubscribe._")

    return "\n".join(lines)


def send_daily_report(report: AnalysisReport) -> bool:
    """Build and send the daily WhatsApp summary to all recipients."""
    if report.total_scanned == 0:
        log.warning("Report skipped — no items scanned yet.")
        return False

    message = build_daily_message(report)

    # WhatsApp messages have a ~1600-char practical limit; split if needed
    chunks = _split_message(message, max_len=1500)
    success = True
    for i, chunk in enumerate(chunks):
        ok = _broadcast(chunk)
        if not ok:
            log.error("Failed to broadcast message chunk %d/%d.", i + 1, len(chunks))
            success = False

    return success


def send_test_message() -> bool:
    """Send a simple ping to ALL recipients to verify the Twilio integration."""
    body = (
        "*Warframe Market Predictor — test message*\n\n"
        "If you can read this, WhatsApp notifications are working correctly!\n\n"
        "_The daily report will arrive at the configured time each morning._"
    )
    return _broadcast(body)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _split_message(text: str, max_len: int = 1500) -> list[str]:
    """Split a long message at newline boundaries to stay under max_len."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_len and current:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)

    if current:
        chunks.append("".join(current))

    return chunks
