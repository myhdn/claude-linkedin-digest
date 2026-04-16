import csv
import json
import os
import re
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

TAVILY_API_KEY    = os.environ["TAVILY_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_PASSWORD    = os.environ["EMAIL_PASSWORD"]
APIFY_TOKEN       = os.environ.get("APIFY_TOKEN", "")
EMAIL_FROM = "mr.m.heyden@gmail.com"
EMAIL_TO   = "mr.m.heyden@gmail.com"

DB_FILE   = "seen_articles.csv"
DB_FIELDS = ["url", "title", "snippet", "source", "query", "topics", "first_seen"]

tavily           = TavilyClient(api_key=TAVILY_API_KEY)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# Themen-Erkennung
# ---------------------------------------------------------------------------

TOPIC_RULES = [
    ("GBTEC",                 ["gbtec"]),
    ("BIC Platform",          ["bic platform"]),
    ("BIC Process Design",    ["bic process design"]),
    ("BIC EAM",               ["bic eam"]),
    ("BIC GRC",               ["bic grc"]),
    ("BIC Process Execution", ["bic process execut"]),
    ("Apromore",              ["apromore"]),
    ("BPM",                   ["business process management", "bpm"]),
    ("Process Mining",        ["process mining"]),
    ("GRC",                   ["governance, risk", "governance risk", " grc "]),
    ("EAM",                   ["enterprise architecture"]),
    ("SAP S/4HANA",           ["s/4hana", "s4hana"]),
    ("SAP Signavio",          ["signavio"]),
    ("Celonis",               ["celonis"]),
    ("LeanIX",                ["leanix"]),
    ("ARIS",                  [" aris "]),
    ("Camunda",               ["camunda"]),
    ("DORA",                  [" dora "]),
    ("NIS2",                  ["nis2", "nis 2"]),
    ("MaRisk",                ["marisk"]),
    ("CSRD",                  ["csrd"]),
    ("ESG",                   [" esg "]),
    ("ISO 27001",             ["iso 27001"]),
    ("No-Code/Low-Code",      ["no code", "no-code", "low code", "low-code"]),
    ("Workflow Automation",   ["workflow automation"]),
    ("Process Excellence",    ["process excellence"]),
    ("Digital Transformation",["digital transformation"]),
    ("Finance/Insurance",     ["finance", "insurance", "banking", "versicherung"]),
    ("Manufacturing",         ["manufacturing", "automotive", "fertigung"]),
    ("Energy",                ["energy", "utilities", "energie"]),
    ("Healthcare",            ["healthcare", "gesundheit"]),
    ("Compliance",            ["compliance"]),
    ("Risk Management",       ["risk management", "risikomanagement"]),
]


def extract_topics(title: str, snippet: str, query: str = "") -> str:
    text = " ".join([title, snippet, query]).lower()
    found, seen = [], set()
    for label, keywords in TOPIC_RULES:
        if label not in seen and any(kw in text for kw in keywords):
            found.append(label)
            seen.add(label)
    return ", ".join(found) if found else "Sonstige"


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

def load_db() -> dict:
    db = {}
    if not Path(DB_FILE).exists():
        return db
    with open(DB_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db[row["url"]] = row
    return db


def migrate_db_if_needed(db: dict) -> bool:
    if not any("topics" not in row for row in db.values()):
        return False
    print("  Migration: fuege 'topics'-Spalte hinzu...")
    for row in db.values():
        if "topics" not in row or not row["topics"]:
            row["topics"] = extract_topics(
                row.get("title", ""), row.get("snippet", ""), row.get("query", "")
            )
    with open(DB_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_FIELDS)
        writer.writeheader()
        for row in db.values():
            writer.writerow({field: row.get(field, "") for field in DB_FIELDS})
    print(f"  Migration: {len(db)} Eintraege aktualisiert.")
    return True


def save_new_articles(new_articles: list):
    file_exists = Path(DB_FILE).exists()
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_FIELDS)
        if not file_exists:
            writer.writeheader()
        for a in new_articles:
            writer.writerow(a)


# ---------------------------------------------------------------------------
# Relevanzkontext
# ---------------------------------------------------------------------------
RELEVANCE_CONTEXT = """
Du filterst Ergebnisse fuer einen Sales-Berater, der GBTEC-Software (BIC Platform) verkauft.

BEHALTEN - Posts/Artikel die eines dieser Signale zeigen:
  Produkt-Signale:
    - GBTEC, BIC Platform, BIC Process Design, BIC EAM, BIC GRC, BIC Process Execution, Apromore
    - Konkurrenten: SAP Signavio, Celonis, LeanIX, Nintex, ARIS, Software AG, Camunda
    - Vergleiche: Signavio vs, Celonis vs, LeanIX vs, best BPM tool, BPM software evaluation

  Kaufsignal-Themen (Unternehmen haben ein Problem das GBTEC loest):
    - SAP S/4HANA Migration/Transformation/Einfuehrung
    - Prozesstransparenz fehlt, Prozessdokumentation, Prozessmodellierung
    - Workflow-Automatisierung, No-Code/Low-Code, Citizen Developer
    - Enterprise Architecture, IT-Rationalisierung, Application Portfolio Management
    - DORA, NIS2, MaRisk, ISO 27001, CSRD, ESG-Reporting, Compliance-Druck
    - Process Mining, Prozessanalyse, Bottleneck-Erkennung
    - Digitale Transformation als Projekt/Initiative angekuendigt
    - Neue Rolle: CDO, CIO, Head of Process Excellence, Chief Risk Officer

  Branchen-Signale (GBTEC-Zielbranchen):
    - Finance & Insurance, Banking, Versicherung
    - Manufacturing, Automotive, Logistik
    - Energy & Utilities, Healthcare, Pharma
    - Oeffentliche Verwaltung, Public Sector

HERAUSFILTERN:
  - BPM = Beats Per Minute, Sport, Fitness, Musik
  - GRC = Gaming, Grafikkarten
  - Allgemeine Marketing-, HR- oder Sales-Posts ohne Prozess/Compliance-Bezug
  - Jobangebote ohne inhaltlichen Kontext
  - Posts die ein Keyword nur zufaellig erwaehnen
"""


# ---------------------------------------------------------------------------
# Quelle 1: Tavily
# ---------------------------------------------------------------------------

TAVILY_QUERIES = [
    dict(query='GBTEC "BIC Platform" OR "BIC Process Design" OR "BIC EAM"',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='GBTEC "Process Mining" OR "BIC GRC" OR "Apromore"',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='GBTEC site:linkedin.com/pulse',
         search_depth="advanced", max_results=5),
    dict(query='GBTEC news 2025 2026',
         exclude_domains=["linkedin.com"], search_depth="basic", max_results=5),
    dict(query='"SAP Signavio" OR "Celonis" OR "LeanIX" alternative comparison',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"BPM software" OR "process management tool" evaluation 2025 2026',
         include_domains=["linkedin.com/pulse"], search_depth="advanced", max_results=5),
    dict(query='"SAP S/4HANA" transformation "process documentation" OR "process management"',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"S/4HANA" migration "business process" 2025 2026',
         include_domains=["linkedin.com/pulse"], search_depth="advanced", max_results=5),
    dict(query='DORA NIS2 "compliance management" OR "risk management" software',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='MaRisk "internal control" OR "GRC software" Banken Versicherung',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='CSRD ESG "sustainability reporting" software enterprise',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"Process Mining" enterprise "inefficiency" OR "bottleneck" OR "optimization"',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"workflow automation" "no code" OR "low code" enterprise 2025',
         include_domains=["linkedin.com/pulse"], search_depth="advanced", max_results=5),
    dict(query='"enterprise architecture" "IT rationalization" OR "application portfolio" 2025 2026',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"business process management" finance insurance banking 2025',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
    dict(query='"process excellence" OR "digital transformation" manufacturing automotive 2025',
         include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
]


def run_tavily_searches() -> list:
    seen_urls, results = set(), []
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
# Quelle 2: Apify
# ---------------------------------------------------------------------------

APIFY_QUERIES = [
    {"keywords": "GBTEC BIC Platform",                                        "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 20},
    {"keywords": "GBTEC Process Mining Apromore",                             "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": "GBTEC GRC Compliance",                                      "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": '"BIC Process Design"',                                      "sortBy": "date_posted", "datePosted": "past-month", "maxPosts": 10},
    {"keywords": '"BIC EAM" enterprise architecture',                         "sortBy": "date_posted", "datePosted": "past-month", "maxPosts": 10},
    {"keywords": '"S/4HANA" "process management" OR "process documentation"', "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 20},
    {"keywords": "DORA NIS2 compliance software",                             "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": 'MaRisk "internal control system"',                          "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 10},
    {"keywords": "CSRD ESG reporting enterprise software",                    "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 10},
    {"keywords": '"SAP Signavio" OR "Celonis" alternative',                   "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": '"LeanIX" OR "ARIS" OR "Camunda" alternative',              "sortBy": "date_posted", "datePosted": "past-month", "maxPosts": 10},
    {"keywords": '"process inefficiency" OR "lack of process transparency"',  "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": '"workflow automation" "no code" enterprise 2025',           "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": '"business process management" finance banking insurance',   "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 15},
    {"keywords": '"process excellence" manufacturing automotive 2025',        "sortBy": "date_posted", "datePosted": "past-week",  "maxPosts": 10},
]

APIFY_ACTOR   = "apimaestro/linkedin-posts-search-scraper-no-cookies"
APIFY_RUN_URL = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"


def run_apify_searches() -> list:
    if not APIFY_TOKEN:
        print("  Apify-Token nicht gesetzt - Apify-Suche uebersprungen.")
        return []
    seen_urls: set = set()
    results = []
    for q in APIFY_QUERIES:
        try:
            resp = requests.post(
                APIFY_RUN_URL, params={"token": APIFY_TOKEN}, json=q, timeout=120
            )
            if resp.status_code != 200:
                print(f"  Apify HTTP {resp.status_code} bei '{q['keywords']}'")
                continue
            for post in resp.json():
                url = post.get("linkedinUrl") or post.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                author = post.get("actor") or post.get("author") or {}
                author_name = (
                    (author.get("actor_name") or author.get("name", ""))
                    if isinstance(author, dict) else ""
                )
                content = post.get("content") or post.get("text", "")
                results.append({
                    "url":     url,
                    "title":   f"[LinkedIn Post] {author_name}".strip(),
                    "content": content[:600],
                    "source":  "apify",
                    "query":   q["keywords"],
                })
            time.sleep(2)
        except Exception as e:
            print(f"  Apify-Fehler bei '{q['keywords']}': {e}")
    print(f"  Apify: {len(results)} LinkedIn-Posts gefunden")
    return results


# ---------------------------------------------------------------------------
# Relevanz-Filter
# ---------------------------------------------------------------------------

def filter_by_relevance(raw_items: list) -> list:
    if not raw_items:
        return []
    items_text = ""
    for i, item in enumerate(raw_items):
        snippet = (item.get("content") or "")[:300].replace("\n", " ")
        items_text += f"[{i}] TITLE: {item['title']}\n    SNIPPET: {snippet}\n\n"
    prompt = (
        "Du bist ein strenger Relevanz-Filter fuer einen GBTEC-Software-Berater.\n\n"
        + RELEVANCE_CONTEXT
        + "\n\nUnten sind nummerierte Eintraege.\n"
        "Gib NUR eine JSON-Liste der relevanten Indizes zurueck. Beispiel: [0, 2, 5]\n"
        "Kein Text ausserhalb der JSON-Liste.\n\nEintraege:\n"
        + items_text
    )
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6", max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if not match:
            return raw_items
        indices = json.loads(match.group())
        filtered = [raw_items[i] for i in indices if 0 <= i < len(raw_items)]
        print(f"  Relevanz-Filter: {len(raw_items)} -> {len(filtered)} relevante Eintraege")
        return filtered
    except Exception as e:
        print(f"  Relevanz-Filter Fehler: {e} - behalte alle")
        return raw_items


# ---------------------------------------------------------------------------
# Deduplizierung
# ---------------------------------------------------------------------------

def filter_new(items: list, db: dict) -> tuple[list, list]:
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    new_db_rows, new_items = [], []
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
                "topics":     extract_topics(
                    item.get("title", ""), item.get("content", ""), item.get("query", "")
                ),
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
        if snippet and not snippet.endswith("..."):
            snippet += "..."
        topics = extract_topics(
            item.get("title", ""), item.get("content", ""), item.get("query", "")
        )
        badge = "&#128309; LinkedIn-Post" if item.get("source") == "apify" else "&#127760; Web/Artikel"
        topic_tags = " ".join(
            '<span style="background:#e8f0fe;color:#1a56db;font-size:10px;'
            'padding:1px 5px;border-radius:3px;margin-right:2px;">' + t + '</span>'
            for t in topics.split(", ") if t
        )
        rows += (
            "\n        <tr>"
            '\n          <td style="padding:8px 6px; border-bottom:1px solid #eee; vertical-align:top;">'
            f'\n            <span style="font-size:11px; color:#888;">{badge}</span>&nbsp;{topic_tags}<br>'
            f'\n            <a href="{url}" style="color:#0a66c2; font-weight:bold;">{title}</a><br>'
            f'\n            <span style="font-size:12px; color:#666;">{snippet}</span>'
            "\n          </td>"
            "\n        </tr>"
        )
    return (
        f'\n  <h2>&#128194; Alle neuen Quellen ({len(items)} Treffer)</h2>'
        '\n  <table style="width:100%; border-collapse:collapse; font-size:13px;">'
        + rows
        + "\n  </table>"
    )


def sanitize_claude_html(html: str) -> str:
    """Entfernt background-color/color-Styles und mark-Tags aus Claude-Output."""
    html = re.sub(r'background(?:-color)?\s*:[^;"\'>]+', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<mark[^>]*>(.*?)</mark>', r'\1', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'\s*style\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s*style\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    return html


def summarize_with_claude(items: list) -> str:
    context = ""
    for item in items:
        source  = "LinkedIn Post" if item.get("source") == "apify" else "Web/Artikel"
        topics  = extract_topics(
            item.get("title", ""), item.get("content", ""), item.get("query", "")
        )
        snippet = (item.get("content") or "")[:500]
        context += (
            f"SOURCE: {source}\nTOPICS: {topics}\n"
            f"TITLE: {item['title']}\nURL: {item['url']}\nSNIPPET: {snippet}\n\n"
        )

    prompt = (
        "Du bist ein Sales-Intelligence-Assistent fuer einen Berater, "
        "der GBTEC-Software (BIC Platform) verkauft.\n\n"
        "GBTEC-Produktportfolio:\n"
        "- BIC Process Design: BPM, Prozessmodellierung, SAP S/4HANA-Integration\n"
        "- BIC EAM: Enterprise Architecture, IT-Rationalisierung, Application Portfolio\n"
        "- BIC Process Execution: Workflow-Automatisierung, No-Code/Low-Code\n"
        "- BIC GRC: Risikomanagement, Compliance, DORA/NIS2/MaRisk/CSRD\n"
        "- Apromore Process Mining: Prozessanalyse, Bottleneck-Erkennung\n"
        "Zielbranchen: Finance/Insurance, Manufacturing, Automotive, Energy, Healthcare\n\n"
        "Erstelle eine strukturierte HTML-Zusammenfassung mit GENAU diesen vier "
        "Abschnitten in GENAU dieser Reihenfolge:\n\n"
        "<h2>&#128293; Kaufsignale - Unternehmen mit konkretem Bedarf</h2>\n"
        "Posts/Artikel wo Firmen oder Personen ueber Probleme schreiben, die GBTEC loest.\n"
        "Fuer jeden Treffer: Firmenname/Autor fett, beschriebenes Problem, "
        "passendes GBTEC-Produkt, verlinkter Titel.\n\n"
        "<h2>&#127970; GBTEC & BIC Platform - Neuigkeiten</h2>\n"
        "Direkte Neuigkeiten, Posts, Ankuendigungen von/ueber GBTEC.\n\n"
        "<h2>&#128202; Markt & Wettbewerb</h2>\n"
        "Branchentrends, Wettbewerber-Erwaehnung, Marktentwicklungen.\n\n"
        "<h2>&#128279; Top 5 Anknuepfungspunkte</h2>\n"
        "Die 5 vielversprechendsten Links fuer einen Sales-Kommentar.\n"
        'Format: <a href="URL">Titel</a> - Ein-Satz-Erklaerung.\n\n'
        "HTML-Regeln (strikt einhalten):\n"
        "- Erlaubte Tags: h2, p, ul, li, a, strong, br\n"
        "- KEIN style-Attribut, KEIN background-color, KEIN color-Attribut, KEIN mark-Tag\n"
        "- KEINE farbigen Hintergruende oder Hervorhebungen\n"
        '- Links als <a href="URL">Text</a>, Firmennamen als <strong>Name</strong>\n'
        "- Auf Deutsch\n\n"
        "Eintraege:\n"
        + context
    )

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return sanitize_claude_html(response.content[0].text)


def send_email(summary_html: str, sources_html: str, counts: dict):
    today   = date.today().strftime("%d.%m.%Y")
    subject = f"Sales Digest - GBTEC BIC Platform - {today} ({counts['total']} neue Signale)"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    html_full = (
        '<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><style>'
        "body{font-family:Arial,sans-serif;font-size:14px;color:#333;"
        "max-width:750px;margin:auto;padding:20px}"
        "h2{color:#0a66c2;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:28px}"
        "p,li{line-height:1.6}"
        "a{color:#0a66c2}"
        "strong{font-weight:bold}"
        ".badge{background:#0a66c2;color:#fff;border-radius:4px;"
        "padding:2px 8px;font-size:11px;margin-right:4px}"
        ".badge-li{background:#00a0dc}"
        ".badge-hot{background:#e03e2d}"
        ".footer{margin-top:30px;font-size:11px;color:#999;"
        "border-top:1px solid #eee;padding-top:10px}"
        "</style></head><body>"
        '<h1 style="color:#333;">&#127919; Taeglicher Sales Digest - GBTEC BIC Platform</h1>'
        f'<p style="color:#666;">{today}&nbsp;'
        f'<span class="badge">{counts["tavily"]} Web</span>'
        f'<span class="badge badge-li">{counts["apify"]} LinkedIn-Posts</span>'
        f'<span class="badge badge-hot">{counts["total"]} neue Signale</span></p>'
        "<hr>"
        + summary_html
        + '<hr style="margin-top:30px;">'
        + sources_html
        + '<div class="footer">Themen-Tags basierend auf Keyword-Analyse.<br>'
        "Quellen: Tavily + Apify + Claude Sales-Intelligence-Filter</div>"
        "</body></html>"
    )

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
    print(f"  {len(db)} bekannte Eintraege.")

    migrated = migrate_db_if_needed(db)
    if migrated:
        db = load_db()

    print("\n[1/4] Tavily Web-Suche...")
    tavily_raw = run_tavily_searches()

    print("\n[2/4] Apify LinkedIn-Suche...")
    apify_raw = run_apify_searches()

    all_raw = tavily_raw + apify_raw
    print(f"\n  Gesamt roh: {len(all_raw)} Eintraege")

    print("\n[3/4] Claude Relevanz-Filter...")
    relevant_items = filter_by_relevance(all_raw)

    print("\n[4/4] Abgleich mit Datenbank...")
    new_db_rows, new_items = filter_new(relevant_items, db)

    tavily_new = sum(1 for i in new_items if i.get("source") != "apify")
    apify_new  = sum(1 for i in new_items if i.get("source") == "apify")
    print(f"  Neu: {tavily_new} Web, {apify_new} LinkedIn-Posts")

    if not new_items:
        print("\nKeine neuen Kaufsignale - kein E-Mail-Versand.")
        return

    print("\nSpeichere neue Eintraege...")
    save_new_articles(new_db_rows)

    print("Erstelle Claude Sales-Zusammenfassung...")
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
