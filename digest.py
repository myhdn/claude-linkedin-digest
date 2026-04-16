import csv
import os
import smtplib
import time
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

TAVILY_API_KEY  = os.environ["TAVILY_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]
APOFY_TOKEN     = os.environ.get("APIFY_TOKEN", "")   # optional – wird übersprungen wenn leer
EMAIL_FROM = "mr.m.heyden@gmail.com"
EMAIL_TO   = "mr.m.heyden@gmail.com"

DB_FILE   = "seen_articles.csv"
DB_FIELDS = ["url", "title", "snippet", "source", "query", "first_seen"]

# ---------------------------------------------------------------------------
# Relevanzkontext – was "BPM", "GRC" etc. für uns bedeutet
# ---------------------------------------------------------------------------
RELEVANCE_CONTEXT = """
Relevante Themen (NUR diese sollen behalten werden):
- Business Process Management (BPM) im Unternehmenskontext
- GBTEC, BIC Platform, BIC Process Design, BIC EAM, BIC Process Executing, BIC GRC
- Process Mining, Process Automation, Prozessoptimierung
- Governance, Risk & Compliance (GRC) im Enterprise-Bereich
- Enterprise Architecture Management (EAM)
- Digitale Transformation von Unternehmensprozessen
- Finance-Software, ERP-Integration mit BPM

NICHT relevant – diese sollen herausgefiltert werden:
- BPM = Beats Per Minute (Musik, Sport, Fitness)
- BPM = Brand & Product Management (Marketing)
- GRC = Gaming, Grafikkarten, unrelated tech
- Allgemeine HR-, Marketing- oder Sales-Posts ohne BPM-Bezug
- Posts die nur zufällig ein Keyword enthalten ohne inhaltlichen Bezug
"""

tavily   = TavilyClient(api_key=TAVILY_API_KEY)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# Artikel-Datenbank (CSV)
# ---------------------------------------------------------------------------

def load_db() -> dict:
    db = {}
    if not Path(DB_FILE).exists():
        return db
    with open(DB_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db[row["url"]] = row
    return db


def save_new_articles(new_articles: list):
    file_exists = Path(DB_FILE).exists()
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_FIELDS)
        if not file_exists:
            writer.writeheader()
        for a in new_articles:
            writer.writerow(a)


# ---------------------------------------------------------------------------
# Quelle 1: Tavily-Suche (Web + LinkedIn-Artikel)
# ---------------------------------------------------------------------------

TAVILY_QUERIES = [
    # GBTEC direkt – präzise, kein Rauschen
    dict(query='GBTEC "BIC Platform" OR "BIC Process" OR "BPM"',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='GBTEC "Process Mining" OR "GRC" OR "EAM"',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='GBTEC site:linkedin.com/pulse',
         search_depth="advanced", max_results=5),
    # BIC Produkte – immer mit GBTEC verankert
    dict(query='"BIC Process Design" GBTEC',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"BIC EAM" OR "Enterprise Architecture Management" GBTEC',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"BIC Process Executing" OR "BIC GRC" GBTEC',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    # BPM/GRC Trends – immer mit "business process" ausgeschrieben
    dict(query='"business process management" software trends 2025 2026',
         include_domains=["linkedin.com/pulse"], search_depth="advanced", max_results=5),
    dict(query='"Process Mining" enterprise software 2025 2026',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"Governance Risk Compliance" enterprise software trends',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    # Externe News über GBTEC
    dict(query='GBTEC',
         exclude_domains=["linkedin.com"], search_depth="basic", max_results=5),
]


def run_tavily_searches() -> list:
    seen_urls = set()
    results = []
    for q in TAVILY_QUERIES:
        try:
            resp = tavily.search(**q)
            for r in resp.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        "url":     url,
                        "title":   r.get("title", ""),
                        "content": r.get("content", ""),
                        "source":  "tavily",
                        "query":   q["query"],
                    })
        except Exception as e:
            print(f"  Tavily-Fehler bei '{q['query']}': {e}")
    print(f"  Tavily: {len(results)} Rohergebnisse")
    return results


# ---------------------------------------------------------------------------
# Quelle 2: Apify – LinkedIn Post Search (echte Posts + Kommentare)
# ---------------------------------------------------------------------------

# Präzise Keyword-Kombinationen – kein nacktes "BPM" oder "GRC"
APOFY_QUERIES = [
    {"keywords": "GBTEC BIC Platform",              "sortBy": "date_posted", "datePosted": "past-week", "maxPosts": 20},
    {"keywords": "GBTEC \"business process management\"","sortBy": "date_posted", "datePosted": "past-week", "maxPosts": 15},
    {"keywords": "GBTEC Process Mining",             "sortBy": "date_posted", "datePosted": "past-week", "maxPosts": 15},
    {"keywords": "GBTEC GRC Compliance",             "sortBy": "date_posted", "datePosted": "past-week", "maxPosts": 15},
    {"keywords": "\"BIC Process Design\"",            "sortBy": "date_posted", "datePosted": "past-month", "maxPosts": 10},
    {"keywords": "\"BIC Platform\" workflow",         "sortBy": "date_posted", "datePosted": "past-month", "maxPosts": 10},
    {"keywords": "\"business process management\" software enterprise 2025", "sortBy": "date_posted", "datePosted": "past-week", "maxPosts": 15},
    {"keywords": "\"Process Mining\" enterprise automation","sortBy": "date_posted", "datePosted": "past-week", "maxPosts": 15},
]

APOFY_ACTOR = "apimaestro/linkedin-posts-search-scraper-no-cookies"
APOFY_RUN_URL = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"


def run_apify_searches() -> list:
    if not APOFY_TOKEN:
        print("  Apify-Token nicht gesetzt – Apify-Suche übersprungen.")
        return []

    seen_urls: set = set()
    results   = []

    for q in APOFY_QUERIES:
        try:
            resp = requests.post(
                APIFY_RUN_URL,
                params={"token": APOFY_TOKEN},
                json=q,
                timeout=120,
            )
            if resp.status_code != 200:
                print(f"  Apify HTTP {resp.status_code} bei '{q['keywords']}'")
                continue

            for post in resp.json():
                url = post.get("linkedinUrl") or post.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                author_name = ""
                author = post.get("actor") or post.get("author") or {}
                if isinstance(author, dict):
                    author_name = author.get("actor_name") or author.get("name", "")

                content = post.get("content") or post.get("text", "")
                results.append({
                    "url":     url,
                    "title":   f"[LinkedIn Post] {author_name}".strip(),
                    "content": content[:600],
                    "source":  "apify",
                    "query":   q["keywords"],
                })

            time.sleep(2)   # kurze Pause zwischen Runs

        except Exception as e:
            print(f"  Apify-Fehler bei '{q['keywords']}': {e}")

    print(f"  Apify: {len(results)} LinkedIn-Posts gefunden")
    return results


# ---------------------------------------------------------------------------
# Relevanz-Filter via Claude
# ---------------------------------------------------------------------------

def filter_by_relevance(raw_items: list) -> list:
    """
    Schickt alle Rohergebnisse in einem einzigen Claude-Call.
    Claude gibt eine JSON-Liste der relevanten Indizes zurück.
    """
    if not raw_items:
        return []

    # Kompakte Darstellung für den Prompt
    items_text = ""
    for i, item in enumerate(raw_items):
        snippet = (item.get("content") or "")[:300].replace("\n", " ")
        items_text += f"[{i}] TITLE: {item['title']}\n    SNIPPET: {snippet}\n\n"

    prompt = f"""Du bist ein strenger Relevanz-Filter für einen BPM/GRC-Software-Experten.

{RELEVANCE_CONTEXT}

Unten sind nummerierte Eintraege (Index in eckigen Klammern).
Gib NUR eine JSON-Liste der Indizes zurueck, die WIRKLICH relevant sind.
Beispiel-Antwort: [0, 2, 5, 7]
Keine Erklaerung, kein Text ausserhalb der JSON-Liste.

Eintraege:
{items_text}"""

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Sicherheits-Parse: extrahiere die erste [...]-Liste
        import re, json
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if not match:
            print("  Relevanz-Filter: keine gueltige JSON-Liste – behalte alle")
            return raw_items
        indices = json.loads(match.group())
        filtered = [raw_items[i] for i in indices if 0 <= i < len(raw_items)]
        print(f"  Relevanz-Filter: {len(raw_items)} → {len(filtered)} relevante Eintraege")
        return filtered
    except Exception as e:
        print(f"  Relevanz-Filter Fehler: {e} – behalte alle")
        return raw_items


# ---------------------------------------------------------------------------
# Deduplizierung gegen Datenbank
# ---------------------------------------------------------------------------

def filter_new(items: list, db: dict) -> tuple[list, list]:
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    new_db_rows = []
    new_items   = []
    for item in items:
        url = item["url"]
        if url not in db:
            new_items.append(item)
            new_db_rows.append({
                "url":        url,
                "title":      item["title"][:200],
                "snippet":    (item.get("content") or "")[:300].replace("\n", " "),
                "source":     item.get("source", ""),
                "query":      item.get("query", ""),
                "first_seen": today_str,
            })
    return new_db_rows, new_items


# ---------------------------------------------------------------------------
# E-Mail aufbauen
# ---------------------------------------------------------------------------

def build_sources_html(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for item in items:
        url     = item["url"]
        title   = item["title"] or url
        snippet = (item.get("content") or "")[:200].strip()
        if snippet and not snippet.endswith("…"):
            snippet += "…"
        source_badge = "🔵 LinkedIn" if item.get("source") == "apify" else "🌐 Web"
        rows += f"""
        <tr>
          <td style="padding:8px 6px; border-bottom:1px solid #eee; vertical-align:top;">
            <span style="font-size:11px; color:#888;">{source_badge}</span><br>
            <a href="{url}" style="color:#0a66c2; font-weight:bold;">{title}</a><br>
            <span style="font-size:12px; color:#666;">{snippet}</span>
          </td>
        </tr>"""
    return f"""
  <h2>📂 Alle neuen Quellen ({len(items)} Treffer)</h2>
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    {rows}
  </table>"""


def summarize_with_claude(items: list) -> str:
    # Kontext für Claude aufbauen
    context = ""
    for item in items:
        source  = "LinkedIn Post" if item.get("source") == "apify" else "Web/Artikel"
        snippet = (item.get("content") or "")[:500]
        context += f"SOURCE: {source}\nTITLE: {item['title']}\nURL: {item['url']}\nSNIPPET: {snippet}\n\n"

    prompt = f"""Du bist ein Business-Intelligence-Assistent fuer einen Sales-Experten im Bereich Finance-Software und BPM (Business Process Management).

Alle unten stehenden Eintraege sind bereits auf Relevanz geprueft und beziehen sich ausschliesslich auf:
- Business Process Management (BPM), Process Mining, GRC, EAM
- GBTEC und deren Produkte (BIC Platform, BIC Process Design, BIC GRC, BIC EAM etc.)

Erstelle eine kompakte, deutsche Zusammenfassung in HTML mit diesen vier Abschnitten:

1. <h2>🏢 GBTEC Aktuell</h2> – Neuigkeiten, Posts, Ankuendigungen direkt von oder ueber GBTEC
2. <h2>📊 BPM & GRC Trends</h2> – Branchentrends, neue Entwicklungen in BPM, GRC, Process Mining
3. <h2>🌐 Was die Welt ueber GBTEC schreibt</h2> – Externe Medien, Blogs, Presse ueber GBTEC
4. <h2>🔗 Top 5 Links</h2> – Die 5 relevantesten Links als <a href="URL">Titel</a>-Liste

Wichtig:
- Verlinke Aussagen direkt mit der Quell-URL als <a href="...">Text</a>
- Hebe Sales-Opportunities hervor (z.B. Unternehmen die BPM-Tools evaluieren, Probleme die GBTEC loesen koennte)
- Schreibe praesize und professionell auf Deutsch
- Kein Markdown, nur HTML-Tags

Eintraege:
{context}"""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def send_email(summary_html: str, sources_html: str, counts: dict):
    today   = date.today().strftime("%d.%m.%Y")
    total   = counts["total"]
    subject = f"LinkedIn Digest – GBTEC & BPM – {today} ({total} neue Treffer)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    html_full = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; max-width: 750px; margin: auto; padding: 20px; }}
    h2 {{ color: #0a66c2; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 28px; }}
    a {{ color: #0a66c2; }}
    .badge {{ background:#0a66c2; color:#fff; border-radius:4px; padding:2px 8px; font-size:11px; margin-right:4px; }}
    .badge-li {{ background:#00a0dc; }}
    .footer {{ margin-top: 30px; font-size: 11px; color: #999; border-top: 1px solid #eee; padding-top: 10px; }}
  </style>
</head>
<body>
  <h1 style="color:#333;">📋 Täglicher Digest – GBTEC & BPM</h1>
  <p style="color:#666;">
    {today} &nbsp;
    <span class="badge">{counts['tavily']} Web-Artikel</span>
    <span class="badge badge-li">{counts['apify']} LinkedIn-Posts</span>
  </p>
  <hr>

  {summary_html}

  <hr style="margin-top:30px;">
  {sources_html}

  <div class="footer">
    Nur neue Treffer – bereits bekannte Quellen werden nicht erneut angezeigt.<br>
    Alle Ergebnisse wurden auf BPM/GRC-Relevanz gefiltert (kein Musik-BPM, kein Marketing-GRC).<br>
    Quellen: Tavily Web-Suche + Apify LinkedIn Scraper + Claude Relevanz-Filter
  </div>
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
    print(f"  {len(db)} bekannte Eintraege in der Datenbank.")

    # --- Suchen ---
    print("\n[1/4] Tavily Web-Suche...")
    tavily_raw = run_tavily_searches()

    print("\n[2/4] Apify LinkedIn-Suche...")
    apify_raw = run_apify_searches()

    all_raw = tavily_raw + apify_raw
    print(f"\n  Gesamt roh: {len(all_raw)} Eintraege")

    # --- Relevanz-Filter ---
    print("\n[3/4] Claude Relevanz-Filter...")
    relevant_items = filter_by_relevance(all_raw)

    # --- Deduplizierung gegen DB ---
    print("\n[4/4] Abgleich mit Datenbank...")
    new_db_rows, new_items = filter_new(relevant_items, db)

    tavily_new = sum(1 for i in new_items if i.get("source") != "apify")
    apify_new  = sum(1 for i in new_items if i.get("source") == "apify")
    print(f"  Neu: {tavily_new} Web-Artikel, {apify_new} LinkedIn-Posts")

    if not new_items:
        print("\nKeine neuen relevanten Treffer – kein E-Mail-Versand.")
        return

    print("\nSpeichere neue Eintraege in Datenbank...")
    save_new_articles(new_db_rows)

    print("Erstelle Claude-Zusammenfassung...")
    summary_html = summarize_with_claude(new_items)

    print("Baue Quellenabschnitt...")
    sources_html = build_sources_html(new_items)

    print("Sende E-Mail...")
    send_email(summary_html, sources_html, {
        "total":  len(new_items),
        "tavily": tavily_new,
        "apify":  apify_new,
    })

    print("\nFertig.")


if __name__ == "__main__":
    main()
