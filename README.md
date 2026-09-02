# Ensemble — taegliche Signale per Telegram

Rechnet die vier Sleeves (BTC, QQQ, SPY, Gold) einmal taeglich durch und
schickt eine Telegram-Nachricht. Auch dann, wenn nichts passiert ist — eine
Nachricht, die nur bei Signalen kaeme, waere nicht von "System tot" zu
unterscheiden.

Kosten: null. Oeffentliches Repository (unbegrenzte Actions-Minuten),
Telegram-Bot gratis, kein TradingView-Abo noetig.

## Warum das Repository oeffentlich ist

Geplante Workflows feuern auf **privaten** Repositories im kostenlosen
GitHub-Plan nicht. Deshalb oeffentlich — und deshalb stehen die
Strategieparameter **nicht im Code**, sondern in einem Secret. Was hier
oeffentlich liegt, ist ein generischer Runner; EMA + MACD + Aroon ist
Allgemeingut, wertvoll ist allein die Parametrisierung.

**Niemals Parameter, Token oder Chat-ID in den Code oder in `print()` schreiben.**
Bei einem oeffentlichen Repo sind auch die Action-Logs oeffentlich.

## Einrichtung

### 1. Telegram-Bot

1. In Telegram `@BotFather` anschreiben, `/newbot`, Namen vergeben.
2. Den Token notieren (Format `123456789:AA...`).
3. Dem eigenen Bot **eine beliebige Nachricht schreiben** (sonst darf er dir
   nicht antworten).
4. `https://api.telegram.org/bot<TOKEN>/getUpdates` im Browser oeffnen und die
   `chat.id` herauslesen.

### 2. Secrets anlegen

Settings -> Secrets and variables -> Actions -> New repository secret:

| Name | Inhalt |
|---|---|
| `TELEGRAM_TOKEN` | der Bot-Token |
| `TELEGRAM_CHAT_ID` | deine Chat-ID |
| `STRATEGY_PARAMS` | das JSON unten |

```json
{
  "BTC-USD": {"e1": 0, "e2": 0, "e3": 0, "mf": 0, "ms": 0, "msig": 0, "al": 0, "label": "BTC",  "weight_pct": 25},
  "QQQ":     {"e1": 0, "e2": 0, "e3": 0, "mf": 0, "ms": 0, "msig": 0, "al": 0, "label": "QQQ",  "weight_pct": 25},
  "SPY":     {"e1": 0, "e2": 0, "e3": 0, "mf": 0, "ms": 0, "msig": 0, "al": 0, "label": "SPY",  "weight_pct": 25},
  "GLD":     {"e1": 0, "e2": 0, "e3": 0, "mf": 0, "ms": 0, "msig": 0, "al": 0, "label": "GOLD", "weight_pct": 25}
}

Die Nullen durch die eigenen Werte ersetzen. Sie stehen NUR im Secret,
niemals in einer Datei dieses Repositorys.
```

### 3. Abnahmetest — vor dem Livegang

Lokal, mit deinen Signal-CSVs:

```bash
pip install -r requirements.txt
python verify_against_csv.py /Pfad/zu/NEW-TEMPLATE/data/strategy_outputs
```

Der Test muss fuer alle vier Assets **BESTANDEN** melden. Abweichungen ganz am
Anfang der Reihe koennen von unterschiedlich langen Downloads kommen;
Abweichungen in den letzten Jahren sind ein echter Fehler. Nicht live gehen,
solange der Test nicht sauber ist.

### 4. Erst von Hand, dann automatisch

Actions -> "Ensemble Daily Signal" -> Run workflow. Wenn die Nachricht ankommt,
laeuft der Cron ab dem naechsten Tag von selbst.

## Zeitplan

`37 0 * * *` (UTC). Der BTC-Tagesbalken schliesst um 00:00 UTC, die US-Boerse
um 20:00/21:00 UTC — beide gehoeren zum selben Handelstag. UTC kennt keine
Sommerzeit, der Eintrag stimmt ganzjaehrig. Du liest morgens und handelst
tagsueber; der Backtest fuellt zum naechsten Tagesschluss.

## Was der Job selbst prueft

- Juengster Balken aelter als 5 Tage -> Warnung in der Nachricht
- Unplausible Schlusskurse -> Warnung
- Download-Fehler -> vier Versuche, danach eine explizite Fehlernachricht per
  Telegram und ein roter Lauf (GitHub schickt zusaetzlich eine E-Mail)

## Bekannte Risiken

**Yahoo drosselt Cloud-IPs.** GitHub-Runner teilen sich Adressbereiche, die
Yahoo gelegentlich limitiert. Der Job wiederholt viermal. Haeuft sich das,
ist eine eigene VM (z. B. Oracle Always Free) mit klassischem Cron die
Alternative.

**Verzoegerungen.** Geplante Actions-Laeufe koennen sich um Minuten verschieben.
Fuer eine Tagesstrategie irrelevant.

**60-Tage-Regel.** GitHub deaktiviert geplante Workflows nach 60 Tagen ohne
Repository-Aktivitaet. Der Heartbeat-Commit am Ende jedes Laufs haelt das Repo
aktiv. Trotzdem: einmal im Monat unter Actions nachsehen, ob der Workflow noch
aktiviert ist.

## Was der Job NICHT tut

Er ordert nichts und kennt deinen Depotstand nicht. Die Groessenangabe in der
Nachricht ist ein Prozentsatz der Gesamt-Equity — den Betrag rechnest du beim
Ordern selbst aus und traegst ihn ins Positions- und Slippage-Journal ein.
