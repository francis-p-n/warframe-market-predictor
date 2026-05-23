"""
notifier.py — Send push notifications via ntfy.sh (free, forever).

ntfy.sh requires zero account creation. You pick a secret topic name,
subscribe to it in the ntfy app on your phone, and that's it.

App download:
  Android: https://play.google.com/store/apps/details?id=io.heckel.ntfy
  iOS:     https://apps.apple.com/app/ntfy/id1625396347
  Web:     https://ntfy.sh/<your-topic>

Multiple recipients: share your topic name with anyone — they subscribe
in their own ntfy app and instantly receive the same notifications.
"""

import logging
from datetime import datetime

import httpx

import config
from analyzer import AnalysisReport, ItemSignal

log = logging.getLogger(__name__)

# ntfy.sh public server — you can also self-host
NTFY_BASE_URL = "https://ntfy.sh"


# ─── Core Send ────────────────────────────────────────────────────────────────

def _send(
    title: str,
    body: str,
    priority: str = "default",
    tags: list[str] | None = None,
) -> bool:
    """
    POST a notification to ntfy.sh.
    Returns True on success, False on failure.

    priority: "min" | "low" | "default" | "high" | "urgent"
    tags:     emoji shortcodes shown as notification icon, e.g. ["chart_with_upwards_trend"]
              Full list: https://docs.ntfy.sh/emojis/
    """
    url = f"{NTFY_BASE_URL}/{config.NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Markdown": "yes",
        "Content-Type": "text/plain; charset=utf-8",
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        resp = httpx.post(
            url,
            content=body.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            log.info("ntfy notification sent to topic '%s'.", config.NTFY_TOPIC)
            return True
        log.error("ntfy returned HTTP %d: %s", resp.status_code, resp.text[:200])
        return False
    except httpx.RequestError as exc:
        log.error("ntfy request failed: %s", exc)
        return False


# ─── Message Formatting ───────────────────────────────────────────────────────

def _format_signal_line(sig: ItemSignal) -> str:
    """Format a single item signal as a Markdown line for ntfy."""
    mom_sign = "+" if sig.momentum_pct >= 0 else ""
    conf_pct = f"{sig.confidence * 100:.0f}%"
    return (
        f"**{sig.item_name}** — {sig.current_price:.0f}p  "
        f"*(30d avg {sig.avg_30d:.0f}p, {mom_sign}{sig.momentum_pct:.1f}%, "
        f"conf {conf_pct})*\n"
        f"  {sig.explanation}"
    )


def build_daily_message(report: AnalysisReport) -> str:
    """Compose the full daily summary as Markdown for ntfy."""
    lines: list[str] = []

    # ── BUYs ──────────────────────────────────────────────────────────────────
    if report.buys:
        lines.append("## Buy Signals")
        for sig in report.buys:
            lines.append(_format_signal_line(sig))
    else:
        lines.append("## Buy Signals\n*No strong buy signals today.*")
    lines.append("")

    # ── SELLs ─────────────────────────────────────────────────────────────────
    if report.sells:
        lines.append("## Sell Signals")
        for sig in report.sells:
            lines.append(_format_signal_line(sig))
    else:
        lines.append("## Sell Signals\n*No strong sell signals today.*")
    lines.append("")

    # ── HOLDs ─────────────────────────────────────────────────────────────────
    if report.holds:
        lines.append("## Hold — Wait")
        for sig in report.holds:
            lines.append(_format_signal_line(sig))
    else:
        lines.append("## Hold — Wait\n*Nothing flagged as a patience play today.*")
    lines.append("")

    lines.append(
        f"*{report.total_scanned} items scanned — "
        f"{report.total_signals} signals generated*"
    )

    return "\n".join(lines)


def _make_title(report: AnalysisReport) -> str:
    today = datetime.now().strftime("%b %d")
    b = len(report.buys)
    s = len(report.sells)
    h = len(report.holds)
    parts = []
    if b:
        parts.append(f"{b} buy{'s' if b > 1 else ''}")
    if s:
        parts.append(f"{s} sell{'s' if s > 1 else ''}")
    if h:
        parts.append(f"{h} hold{'s' if h > 1 else ''}")
    summary = ", ".join(parts) if parts else "no signals"
    return f"Warframe Market {today} — {summary}"


def _pick_priority(report: AnalysisReport) -> str:
    """Use high priority when there are strong signals, default otherwise."""
    if report.buys or report.sells:
        return "high"
    return "default"


def _pick_tags(report: AnalysisReport) -> list[str]:
    tags = ["chart_with_upwards_trend"]
    if report.buys:
        tags.append("green_circle")
    if report.sells:
        tags.append("red_circle")
    return tags


# ─── Public API ───────────────────────────────────────────────────────────────

def send_daily_report(report: AnalysisReport) -> bool:
    """Build and send the daily push notification. Returns True on success."""
    if report.total_scanned == 0:
        log.warning("Report skipped — no items scanned yet.")
        return False

    body  = build_daily_message(report)
    title = _make_title(report)
    priority = _pick_priority(report)
    tags = _pick_tags(report)

    # ntfy supports up to 4096 bytes per message; split if needed
    chunks = _split_message(body, max_bytes=3800)
    success = True
    for i, chunk in enumerate(chunks):
        chunk_title = title if i == 0 else f"{title} (cont.)"
        ok = _send(chunk_title, chunk, priority=priority, tags=tags if i == 0 else None)
        if not ok:
            log.error("Failed to send notification chunk %d/%d.", i + 1, len(chunks))
            success = False

    return success


def send_test_message() -> bool:
    """Send a test ping to verify ntfy is configured correctly."""
    return _send(
        title="Warframe Market Predictor — test",
        body=(
            "If you can read this, push notifications are working!\n\n"
            "Your daily market report will arrive at "
            f"**{config.REPORT_TIME}** every morning."
        ),
        priority="high",
        tags=["white_check_mark", "chart_with_upwards_trend"],
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _split_message(text: str, max_bytes: int = 3800) -> list[str]:
    """Split a long message at paragraph boundaries to stay under max_bytes."""
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_size = 0

    for line in text.splitlines(keepends=True):
        line_size = len(line.encode("utf-8"))
        if current_size + line_size > max_bytes and current_lines:
            chunks.append("".join(current_lines))
            current_lines = []
            current_size = 0
        current_lines.append(line)
        current_size += line_size

    if current_lines:
        chunks.append("".join(current_lines))

    return chunks
