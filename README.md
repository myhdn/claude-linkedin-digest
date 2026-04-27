# 📊 Claude LinkedIn Digest – GBTEC & BPM

Wöchentlicher automatischer LinkedIn-Digest zu **GBTEC** und **Business Process Management (BPM)**.

## Was macht dieses Tool?
- Durchsucht LinkedIn jeden Montag nach aktuellen Inhalten zu GBTEC, BIC Platform, GRC und BPM-Trends
- Fasst die Ergebnisse mit Claude (Anthropic) auf Deutsch zusammen
- Sendet den Digest als formatierte HTML-E-Mail

## Zeitplan
Jeden **Montag um 07:00 Uhr** (MESZ) / 06:00 Uhr (MEZ)

## Setup
1. Repository forken oder klonen
2. Folgende **GitHub Secrets** eintragen (Settings → Secrets → Actions):
   - `TAVILY_API_KEY` – API-Key von [tavily.com](https://tavily.com)
   - `ANTHROPIC_API_KEY` – API-Key von [anthropic.com](https://anthropic.com)
   - `EMAIL_PASSWORD` – Gmail App-Passwort
3. Workflow läuft automatisch jeden Montag

## Manueller Start
Unter Actions → "Weekly LinkedIn Digest" → "Run workflow"

## Verwandtes Projekt
- [claude-reddit-digest](https://github.com/myhdn/claude-reddit-digest) – Täglicher Reddit-Digest
