#!/usr/bin/env python3
"""Forbruksvakt for Prisradar i Claude Code. Bruker kun standardbiblioteket.

Claude Code sender en JSON-melding til statuslinjen med kontoens ukeforbruk
(rate_limits.seven_day.used_percentage). Skriptet noterer hvor mye prosenten stiger mens en
Prisradar-økt er aktiv og summerer det per forbruksuke. Resultatet ligger i
.claude/usage/ledger.json, som git ignorerer.

Kommandoer:
  statusline  leser JSON fra stdin, oppdaterer loggen og skriver statuslinjen
  gate        brukes som hook; stopper (exit 2) når Prisradar har nådd grensen
  report      skriver en kort rapport (brukes av agenten forbruksvakt)

Grensen settes med PRISRADAR_USAGE_LIMIT (standard 20, i prosent av ukeforbruket).
For å overstyre grensen midlertidig: lag filen .claude/usage/override.
Begrensning: kjører andre Claude-økter samtidig, telles deres forbruk også med.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

USAGE_DIR = Path(__file__).resolve().parent.parent / "usage"
LEDGER = USAGE_DIR / "ledger.json"
OVERRIDE = USAGE_DIR / "override"
WARN_SHARE = 0.75  # varsle når 75 % av grensen er brukt


def limit_pct():
    try:
        return float(os.environ.get("PRISRADAR_USAGE_LIMIT", "20"))
    except ValueError:
        return 20.0


def load():
    try:
        return json.loads(LEDGER.read_text())
    except (OSError, ValueError):
        return {}


def save(ledger):
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2))
    tmp.replace(LEDGER)


def week_key(resets_at):
    """Normaliser reset-tidspunkt (epoch eller ISO) til hel time, så små variasjoner ikke starter ny uke."""
    if resets_at is None:
        return None
    try:
        ts = float(resets_at)
    except (TypeError, ValueError):
        try:
            ts = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return str(resets_at)
    if ts > 1e12:  # millisekunder
        ts /= 1000
    return str(int(round(ts / 3600) * 3600))


def update(ledger, session_id, pct, resets_at):
    key = week_key(resets_at)
    if key and ledger.get("week") != key:
        history = ledger.get("history", [])
        if ledger.get("week"):
            history.append({"week": ledger["week"], "project_pct": round(ledger.get("project_pct", 0.0), 2)})
        ledger = {"week": key, "project_pct": 0.0, "sessions": {}, "history": history[-8:]}
    sessions = ledger.setdefault("sessions", {})
    last = sessions.get(session_id)
    if last is not None and pct > last:
        ledger["project_pct"] = ledger.get("project_pct", 0.0) + (pct - last)
    sessions[session_id] = pct
    ledger["account_pct"] = pct
    ledger["resets_at"] = resets_at
    ledger["updated"] = int(time.time())
    return ledger


def fmt_reset(resets_at):
    key = week_key(resets_at)
    try:
        return datetime.fromtimestamp(int(key)).strftime("%a %H:%M")
    except (TypeError, ValueError):
        return "?"


def cmd_statusline():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    week = ((data.get("rate_limits") or {}).get("seven_day")) or {}
    pct = week.get("used_percentage")
    if pct is None:
        print("Prisradar · ukeforbruk ukjent")
        return
    ledger = update(load(), data.get("session_id", "ukjent"), float(pct), week.get("resets_at"))
    save(ledger)
    used, lim = ledger["project_pct"], limit_pct()
    flag = " ⛔" if used >= lim else (" ⚠️" if used >= lim * WARN_SHARE else "")
    print(f"Prisradar {used:.1f}%/{lim:.0f}% av uka{flag} · konto {float(pct):.0f}% · nullstilles {fmt_reset(week.get('resets_at'))}")


def cmd_gate():
    ledger = load()
    used, lim = ledger.get("project_pct", 0.0), limit_pct()
    if used >= lim and not OVERRIDE.exists():
        sys.stderr.write(
            f"Prisradar har brukt {used:.1f} % av ukeforbruket (grense {lim:.0f} %). "
            "Arbeidet stopper til uka nullstilles. Overstyr med: touch .claude/usage/override\n"
        )
        sys.exit(2)
    if used >= lim * WARN_SHARE:
        print(
            f"FORBRUKSVARSEL: Prisradar har brukt {used:.1f} av {lim:.0f} prosentpoeng denne uka. "
            "Fullfør og commit pågående oppgave, ikke start nye, og bruk billigste modell som holder."
        )


def cmd_report():
    ledger = load()
    lim = limit_pct()
    if not ledger:
        print("Ingen forbruksdata ennå. Statuslinjen må ha kjørt minst én gang i en Prisradar-økt.")
        return
    used = ledger.get("project_pct", 0.0)
    print(f"Prisradar denne uka: {used:.2f} av {lim:.0f} prosentpoeng ({used / lim * 100:.0f} % av budsjettet)")
    print(f"Kontoens ukeforbruk totalt: {ledger.get('account_pct', 0):.0f} %")
    print(f"Uka nullstilles: {fmt_reset(ledger.get('resets_at'))}")
    print(f"Sist oppdatert: {datetime.fromtimestamp(ledger.get('updated', 0)):%Y-%m-%d %H:%M}")
    print(f"Overstyring aktiv: {'ja' if OVERRIDE.exists() else 'nei'}")
    for h in ledger.get("history", [])[-4:]:
        print(f"  tidligere uke {fmt_reset(h['week'])}: {h['project_pct']:.1f} %")


if __name__ == "__main__":
    {"statusline": cmd_statusline, "gate": cmd_gate, "report": cmd_report}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit("bruk: statusline | gate | report")
    )()
