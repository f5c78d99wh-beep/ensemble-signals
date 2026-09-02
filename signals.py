"""
Kernlogik des Ensembles — EMA-Tripel + MACD + Aroon, ODER-verknuepft.

Dieses Modul ist die EINZIGE Stelle, an der die Signallogik steht. Sowohl das
Notebook als auch der taegliche Telegram-Job importieren es. Zwei getrennte
Implementierungen wuerden frueher oder spaeter auseinanderlaufen, und das faellt
erst auf, wenn ein Signal fehlt.

Die Funktionen sind 1:1 aus "new-template-beta-optuna <TICKER>.ipynb"
uebernommen (Cell 36, 52, 67).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Muss mit dem START_DATE der Notebooks uebereinstimmen. Die EMAs werden mit
# ewm(adjust=False) auf dem ERSTEN Kurswert der Reihe initialisiert — ein
# anderes Startdatum ergibt andere EMA-Werte und damit andere Signale.
START_DATE = "2016-01-01"


# ── Bausteine ────────────────────────────────────────────────────────────────
def ema(series: pd.Series, span: int) -> pd.Series:
    """EWM-EMA wie vectorbt (span, adjust=False)."""
    return series.ewm(span=span, adjust=False).mean()


def crossover(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a kreuzt b von unten. NaN-Vergleiche ergeben False."""
    above = a > b
    prev = np.concatenate([[False], above[:-1]])
    return above & ~prev


def crossunder(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    below = a < b
    prev = np.concatenate([[False], below[:-1]])
    return below & ~prev


def shift1(arr: np.ndarray) -> np.ndarray:
    """1-Bar-Verschiebung — verhindert Lookahead."""
    out = np.empty_like(arr, dtype=bool)
    out[0] = False
    out[1:] = arr[:-1]
    return out


def aroon_arrays(high_s: pd.Series, low_s: pd.Series, length: int):
    """
    Aroon Upper/Lower, skaliert auf 0..10.
    10 = das Extrem wurde auf dem aktuellen Bar gemacht, 0 = am Fensterrand.
    """
    win = length + 1
    u = high_s.rolling(win).apply(np.argmax, raw=True).to_numpy()
    l = low_s.rolling(win).apply(np.argmin, raw=True).to_numpy()
    return (10.0 * u / length), (10.0 * l / length)


# ── Rohsignale (Crossover-Tag, ungeshiftet) ──────────────────────────────────
def raw_signals(close_s, high_s, low_s, e1, e2, e3, mf, ms, msig, al):
    """
    Die fuenf Bedingungen, ODER-verknuepft, auf dem Bar des Crossovers.
    Gibt zusaetzlich zurueck, welche Indikatorfamilie ausgeloest hat.
    """
    m1 = ema(close_s, e1).to_numpy()
    m2 = ema(close_s, e2).to_numpy()
    m3 = ema(close_s, e3).to_numpy()
    ema_up = crossover(m1, m2) | crossover(m1, m3) | crossover(m2, m3)
    ema_dn = crossunder(m1, m2) | crossunder(m1, m3) | crossunder(m2, m3)

    # Delta = MACD-Linie minus Signallinie (das Histogramm). Dessen Nulldurch-
    # gang ist identisch mit dem Kreuzen beider Linien.
    macd_line = ema(close_s, mf) - ema(close_s, ms)
    delta = (macd_line - ema(macd_line, msig)).to_numpy()
    zero = np.zeros_like(delta)
    macd_up, macd_dn = crossover(delta, zero), crossunder(delta, zero)

    u, l = aroon_arrays(high_s, low_s, al)
    aro_up, aro_dn = crossover(u, l), crossunder(u, l)

    return {
        "ent": ema_up | macd_up | aro_up,
        "exi": ema_dn | macd_dn | aro_dn,
        "ema_up": ema_up, "ema_dn": ema_dn,
        "macd_up": macd_up, "macd_dn": macd_dn,
        "aroon_up": aro_up, "aroon_dn": aro_dn,
    }


# ── Zustandsmaschine ─────────────────────────────────────────────────────────
def signal_state(ent: np.ndarray, exi: np.ndarray) -> np.ndarray:
    """
    Long/flat-Zustand aus den Rohsignalen.

    Bildet exakt das Verhalten von vectorbt.Portfolio.from_signals nach:
      - wiederholte Entries waehrend einer offenen Position werden ignoriert
      - feuern Entry und Exit auf demselben Bar, passiert NICHTS
    """
    n = len(ent)
    state = np.zeros(n, dtype=np.int8)
    in_pos = False
    for i in range(n):
        e, x = bool(ent[i]), bool(exi[i])
        if e and x:
            pass                       # Konflikt
        elif e and not in_pos:
            in_pos = True
        elif x and in_pos:
            in_pos = False
        state[i] = 1 if in_pos else 0
    return state


def executed_position(state: np.ndarray) -> np.ndarray:
    """
    Die tatsaechlich gehaltene Position — der Signalzustand um einen Bar
    verschoben (_shift1). Das ist die Spalte `Position` der Signal-CSVs.
    """
    pos = np.zeros_like(state)
    pos[1:] = state[:-1]
    return pos


def evaluate(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Erwartet einen DataFrame mit den Spalten Close/High/Low und gibt eine
    Tabelle mit Signalzustand, ausgefuehrter Position und Ausloeser zurueck.
    """
    close_s = df["Close"].astype(float)
    high_s = df["High"].astype(float)
    low_s = df["Low"].astype(float)

    sig = raw_signals(
        close_s, high_s, low_s,
        params["e1"], params["e2"], params["e3"],
        params["mf"], params["ms"], params["msig"], params["al"],
    )
    state = signal_state(sig["ent"], sig["exi"])
    out = pd.DataFrame(index=df.index)
    out["Close"] = close_s
    out["SignalState"] = state
    out["Position"] = executed_position(state)
    # Nur echte Zustandswechsel sind handelbare Signale
    prev = np.concatenate([[0], state[:-1]])
    out["BuySignal"] = (state == 1) & (prev == 0)
    out["SellSignal"] = (state == 0) & (prev == 1)
    for k in ("ema_up", "ema_dn", "macd_up", "macd_dn", "aroon_up", "aroon_dn"):
        out[k] = sig[k]
    return out


def trigger_label(row: pd.Series, buy: bool) -> str:
    """Welche Indikatorfamilie hat ausgeloest — fuer die Nachricht."""
    keys = ("ema_up", "macd_up", "aroon_up") if buy else ("ema_dn", "macd_dn", "aroon_dn")
    names = ("EMA", "MACD", "Aroon")
    hit = [n for k, n in zip(keys, names) if bool(row[k])]
    return " + ".join(hit) if hit else "?"
