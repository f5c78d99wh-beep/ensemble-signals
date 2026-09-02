"""
Taeglicher Signal- und Heartbeat-Job.

Laeuft in GitHub Actions, laedt die Kurse, rechnet das Ensemble fuer alle
konfigurierten Assets und schickt EINE Telegram-Nachricht — auch wenn nichts
passiert ist. Eine Nachricht, die nur bei Signalen kaeme, waere nicht von
"System tot" zu unterscheiden.

Umgebungsvariablen (GitHub Secrets):
  TELEGRAM_TOKEN    Bot-Token von @BotFather
  TELEGRAM_CHAT_ID  eigene Chat-ID
  STRATEGY_PARAMS   JSON, siehe README — enthaelt die Parameter je Ticker

Das Skript gibt die Parameter NIE aus. Bei einem oeffentlichen Repository sind
die Action-Logs oeffentlich.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import yfinance as yf

from ensemble.signals import START_DATE, evaluate, trigger_label

MAX_BAR_AGE_DAYS = 5          # aelter -> Warnung, Daten stehen still
DOWNLOAD_RETRIES = 4
TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(
        TG_API.format(token=token),
        json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
        timeout=30,
    )
    r.raise_for_status()


def download(ticker: str) -> pd.DataFrame:
    """
    Yahoo drosselt Cloud-IPs gelegentlich — deshalb mehrere Versuche mit
    wachsender Pause, bevor der Lauf als Fehler gilt.
    """
    last = None
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            df = yf.download(ticker, start=START_DATE, interval="1d",
                             progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty and {"Close", "High", "Low"} <= set(df.columns):
                return df.dropna(subset=["Close", "High", "Low"])
            last = f"leere oder unvollstaendige Antwort ({list(df.columns)})"
        except Exception as exc:                       # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Download {ticker} fehlgeschlagen: {last}")


def days_in_position(res: pd.DataFrame) -> int:
    """Wie lange ist der aktuelle Zustand schon aktiv (in Kalendertagen)?"""
    state = res["SignalState"].to_numpy()
    cur = state[-1]
    i = len(state) - 1
    while i > 0 and state[i - 1] == cur:
        i -= 1
    return (res.index[-1] - res.index[i]).days


def main() -> int:
    params_all = json.loads(os.environ["STRATEGY_PARAMS"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    actions, positions, warnings = [], [], []

    for ticker, p in params_all.items():
        label = p.get("label", ticker)
        df = download(ticker)
        res = evaluate(df, p)
        last = res.iloc[-1]
        last_date = res.index[-1]

        age = (datetime.now(timezone.utc).date() - last_date.date()).days
        if age > MAX_BAR_AGE_DAYS:
            warnings.append(f"{label}: juengster Balken {last_date.date()} ({age} Tage alt)")
        if not (last["Close"] > 0):
            warnings.append(f"{label}: unplausibler Schlusskurs")

        if bool(last["BuySignal"]):
            actions.append(
                f"  KAUF {label}\n"
                f"    Signal {last_date.date()} @ {last['Close']:,.2f}\n"
                f"    Ausloeser: {trigger_label(last, buy=True)}\n"
                f"    Groesse: {p.get('weight_pct', 25)} % der Gesamt-Equity"
            )
        elif bool(last["SellSignal"]):
            actions.append(
                f"  VERKAUF {label}\n"
                f"    Signal {last_date.date()} @ {last['Close']:,.2f}\n"
                f"    Ausloeser: {trigger_label(last, buy=False)}\n"
                f"    Position vollstaendig schliessen"
            )

        held = int(last["SignalState"]) == 1
        positions.append(
            f"  {label:<5} {'IM MARKT' if held else 'flat    '}"
            f"  seit {days_in_position(res):>3} T"
            f"  |  {last_date.date()} @ {last['Close']:,.2f}"
        )

    lines = [f"Ensemble — Lauf {today}", ""]
    if actions:
        lines += ["=== HANDELN (naechste Session) ===", ""]
        lines += [a + "\n" for a in actions]
    else:
        lines += ["Keine Signale. Nichts zu tun.", ""]
    lines += ["Positionen", *positions, ""]
    if warnings:
        lines += ["ACHTUNG", *[f"  {w}" for w in warnings], ""]
    lines += [f"Datenbasis yfinance ab {START_DATE}"]

    send_telegram("\n".join(lines))
    print(f"Nachricht gesendet. Signale: {len(actions)}, Warnungen: {len(warnings)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                   # noqa: BLE001
        tb = traceback.format_exc(limit=3)
        try:
            send_telegram(
                "Ensemble — LAUF FEHLGESCHLAGEN\n\n"
                f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n"
                f"{tb[-1200:]}\n\n"
                "Heute kamen KEINE Signale zustande. Pruefe den Workflow."
            )
        except Exception:                               # noqa: BLE001
            pass
        traceback.print_exc()
        sys.exit(1)
