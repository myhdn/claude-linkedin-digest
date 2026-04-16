# claude-linkedin-digest

Täglicher automatischer Digest über GBTEC und BPM-Themen – aggregiert aus LinkedIn und dem Web, zusammengefasst von Claude, zugestellt per E-Mail.

## Was macht dieses Projekt?

Ein GitHub Actions Workflow läuft täglich um **09:15 Uhr MESZ** und:

1. Durchsucht LinkedIn und das Web nach relevanten Posts, Artikeln und News zu **GBTEC**, **BPM**, **GRC** und **Process Mining** via [Tavily API](https://tavily.com)
2. Lässt **Claude (claude-sonnet-4)** eine strukturierte deutsche Zusammenfassung erstellen
3. Sendet das Ergebnis als formatierte **HTML-E-Mail** an die konfigurierte Adresse

## Struktur der E-Mail

- 🏢 **GBTEC Aktuell** – Neuigkeiten direkt von/über GBTEC
- 📊 **BPM & GRC Trends** – Branchenentwicklungen
- 🌐 **Was die Welt über GBTEC schreibt** – externe Medien & Presse
- 🔗 **Top 5 Links** – die relevantesten Fundstellen

## Einrichtung

### 1. GitHub Secrets anlegen

Unter **Settings → Secrets → Actions** folgende Secrets eintragen:

| Secret | Beschreibung |
|---|---|
| `TAVILY_API_KEY` | API-Key von [tavily.com](https://tavily.com) |
| `ANTHROPIC_API_KEY` | API-Key von [console.anthropic.com](https://console.anthropic.com) |
| `EMAIL_PASSWORD` | Gmail App-Passwort (kein normales Passwort!) |

### 2. Gmail App-Passwort erstellen

1. Google-Konto → Sicherheit → 2-Faktor-Authentifizierung aktivieren
2. Dann: Sicherheit → App-Passwörter → Neues App-Passwort erstellen
3. Dieses Passwort als `EMAIL_PASSWORD` Secret eintragen

### 3. Workflow manuell testen

Im GitHub-Repository unter **Actions → Daily LinkedIn Digest → Run workflow** lässt sich der Digest jederzeit manuell auslösen.

## Lokale Ausführung

```bash
pip install -r requirements.txt
cp .env.example .env  # Werte eintragen
python digest.py
```

## Technologien

- [Tavily API](https://tavily.com) – KI-gestützte Websuche
- [Anthropic Claude API](https://console.anthropic.com) – Zusammenfassung & Analyse
- GitHub Actions – Scheduling & Ausführung
- Python / smtplib – E-Mail-Versand
