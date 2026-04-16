import csv
import os
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_FROM = "mr.m.heyden@gmail.com"
EMAIL_TO = "mr.m.heyden@gmail.com"

DB_FILE = "seen_articles.csv"
DB_FIELDS = ["url", "title", "snippet", "query", "first_seen"]

tavily = TavilyClient(api_key=TAVILY_API_KEY)
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# Artikel-Datenbank (CSV)
# ---------------------------------------------------------------------------

def load_db() -> dict:
    """Lädt die CSV-Datenbank und gibt ein Dict {url: row} zurück."""
    db = {}
    if not Path(DB_FILE).exists():
        return db
    with open(DB_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db[row["url"]] = row
    return db


def save_new_articles(new_articles: list):
    """Hängt neue Artikel an die CSV-Datenbank an (oder erstellt sie)."""
    file_exists = Path(DB_FILE).exists()
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_FIELDS)
        if not file_exists:
            writer.writeheader()
        for a in new_articles:
            writer.writerow(a)


# ---------------------------------------------------------------------------
# Suche
# ---------------------------------------------------------------------------

def run_searches() -> list:
    queries = [
        # GBTEC & BIC Platform
        dict(query="GBTEC BPM BIC Platform news", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="GBTEC GRC Process Mining update", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="GBTEC BPM site:linkedin.com/pulse", search_depth="advanced", max_results=5),
        # BIC Produkte
        dict(query="BIC Process Design GBTEC", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="BIC EAM Enterprise Architecture Management", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="BIC Process Executing workflow automation", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="BIC GRC Governance Risk Compliance", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        # BPM & Process Mining Trends
        dict(query="Process Mining trends 2025 2026", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="Business Process Management BPM trends 2025 2026", include_domains=["linkedin.com/pulse"], search_depth="advanced", max_results=5),
        # Externe News über GBTEC
        dict(query="GBTEC", exclude_domains=["linkedin.com"], search_depth="basic", max_results=5),
    ]

    seen_urls_this_run = set()
    results_by_query = []

    for q in queries:
        try:
            response = tavily.search(**q)
            unique_results = []
            for r in response.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls_this_run:
                    seen_urls_this_run.add(url)
                    unique_results.append(r)
            results_by_query.append({"query": q["query"], "results": unique_results})
        except Exception as e:
            print(f"  Fehler bei Query '{q['query']}': {e}")
            results_by_query.append({"query": q["query"], "results": [], "error": str(e)})

    return results_by_query


def filter_new_articles(results_by_query: list, db: dict) -> tuple[list, list]:
    """
    Gibt zurück:
      - new_articles: Liste von DB-Zeilen (zum Speichern)
      - new_results_by_query: gefilterte results_by_query (nur neue Artikel)
    """
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    new_articles = []
    new_results_by_query = []

    for group in results_by_query:
        new_results = []
        for r in group["results"]:
            url = r.get("url", "")
            if url and url not in db:
                new_results.append(r)
                new_articles.append({
                    "url": url,
                    "title": r.get("title", "")[:200],
                    "snippet": r.get("content", "")[:300].replace("\n", " "),
                    "query": group["query"],
                    "first_seen": today_str,
                })
        if new_results:
            new_results_by_query.append({"query": group["query"], "results": new_results})

    return new_articles, new_results_by_query


# ---------------------------------------------------------------------------
# Ausgabe aufbauen
# ---------------------------------------------------------------------------

def build_context(results_by_query: list) -> str:
    lines = []
    for group in results_by_query:
        lines.append(f"\n### Suchanfrage: {group['query']}")
        for r in group["results"]:
            title = r.get("title", "Kein Titel")
            url = r.get("url", "")
            content = r.get("content", "")[:500]
            lines.append(f"  - TITLE: {title}\n    URL: {url}\n    SNIPPET: {content}")
    return "\n".join(lines)


def build_sources_html(results_by_query: list) -> str:
    rows = []
    seen_urls = set()
    for group in results_by_query:
        for r in group["results"]:
            url = r.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = r.get("title", url)
            snippet = r.get("content", "")[:200].strip()
            if snippet and not snippet.endswith("…"):
                snippet += "…"
            rows.append(f"""
        <tr>
          <td style="padding:8px 6px; border-bottom:1px solid #eee; vertical-align:top;">
            <a href="{url}" style="color:#0a66c2; font-weight:bold;">{title}</a><br>
            <span style="font-size:12px; color:#666;">{snippet}</span>
          </td>
        </tr>""")

    if not rows:
        return ""

    return f"""
  <h2>📂 Alle neuen Quellen ({len(rows)} Treffer)</h2>
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    {''.join(rows)}
  </table>"""


def summarize_with_claude(context: str) -> str:
    prompt = f"""Du bist ein Business-Intelligence-Assistent für einen Sales-Experten im Bereich Finance-Software und BPM.
Analysiere die folgenden NEUEN Suchergebnisse (heute zum ersten Mal gefunden) und erstelle eine kompakte, deutsche Zusammenfassung in HTML.

Strukturiere die Ausgabe mit diesen vier Abschnitten (als HTML mit passenden Tags, kein Markdown):
1. <h2>🏢 GBTEC Aktuell</h2> – Neuigkeiten, Posts, Ankündigungen direkt von oder über GBTEC
2. <h2>📊 BPM & GRC Trends</h2> – Branchentrends, neue Entwicklungen in BPM, GRC, Process Mining, BIC-Produkten
3. <h2>🌐 Was die Welt über GBTEC schreibt</h2> – Externe Medien, Blogs, Presse über GBTEC
4. <h2>🔗 Top 5 Links</h2> – Die 5 relevantesten Links als klickbare HTML-Liste mit <a href="URL">Titel</a>

Wichtig: Verlinke in deiner Zusammenfassung relevante Aussagen direkt mit der jeweiligen Quell-URL als <a href="...">.
Schreibe präzise, professionell und auf Deutsch. Hebe besonders relevante Signale für Sales-Opportunities hervor.

Neue Suchergebnisse:
{context}
"""
    response = anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# E-Mail
# ---------------------------------------------------------------------------

def send_email(summary_html: str, sources_html: str, new_count: int):
    today = date.today().strftime("%d.%m.%Y")
    subject = f"LinkedIn Digest – GBTEC & BPM – {today} ({new_count} neue Artikel)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    html_full = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; max-width: 750px; margin: auto; padding: 20px; }}
    h2 {{ color: #0a66c2; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 28px; }}
    a {{ color: #0a66c2; }}
    .badge {{ background:#0a66c2; color:#fff; border-radius:4px; padding:2px 8px; font-size:12px; }}
    .footer {{ margin-top: 30px; font-size: 11px; color: #999; border-top: 1px solid #eee; padding-top: 10px; }}
  </style>
</head>
<body>
  <h1 style="color:#333;">📋 Täglicher Digest – GBTEC & BPM</h1>
  <p style="color:#666;">{today} | <span class="badge">{new_count} neue Artikel</span> | Automatisch erstellt via GitHub Actions + Claude</p>
  <hr>

  {summary_html}

  <hr style="margin-top:30px;">
  {sources_html}

  <div class="footer">Nur neue Artikel – bereits bekannte Quellen werden nicht erneut angezeigt.<br>
  Automatisch generiert via Tavily + Claude.</div>
</body>
</html>"""

    msg.attach(MIMEText(html_full, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

    print(f"E-Mail gesendet: '{subject}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Lade Artikel-Datenbank...")
    db = load_db()
    print(f"  {len(db)} bekannte Artikel in der Datenbank.")

    print("Starte Tavily-Suche...")
    results_by_query = run_searches()

    print("Filtere bereits bekannte Artikel heraus...")
    new_articles, new_results_by_query = filter_new_articles(results_by_query, db)
    print(f"  {len(new_articles)} neue Artikel gefunden.")

    if not new_articles:
        print("Keine neuen Artikel – kein E-Mail-Versand, kein Commit.")
        return

    print("Speichere neue Artikel in Datenbank...")
    save_new_articles(new_articles)

    print("Baue Kontext auf...")
    context = build_context(new_results_by_query)

    print("Erstelle Claude-Zusammenfassung...")
    summary_html = summarize_with_claude(context)

    print("Baue Quellenabschnitt...")
    sources_html = build_sources_html(new_results_by_query)

    print("Sende E-Mail...")
    send_email(summary_html, sources_html, len(new_articles))

    print("Fertig.")


if __name__ == "__main__":
    main()
