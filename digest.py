import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from anthropic import Anthropic
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_FROM = "mr.m.heyden@gmail.com"
EMAIL_TO = "mr.m.heyden@gmail.com"

tavily = TavilyClient(api_key=TAVILY_API_KEY)
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)


def run_searches():
    queries = [
        dict(query="GBTEC BPM BIC Platform news", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="GBTEC GRC Process Mining update", include_domains=["linkedin.com"], search_depth="advanced", max_results=5),
        dict(query="GBTEC BPM site:linkedin.com/pulse", search_depth="advanced", max_results=5),
        dict(query="Business Process Management BPM trends 2025 2026", include_domains=["linkedin.com/pulse"], search_depth="advanced", max_results=5),
        dict(query="GBTEC", exclude_domains=["linkedin.com"], search_depth="basic", max_results=5),
    ]

    seen_urls = set()
    results_by_query = []

    for q in queries:
        try:
            response = tavily.search(**q)
            unique_results = []
            for r in response.get("results", []):
                url = r.get("url", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique_results.append(r)
            results_by_query.append({"query": q["query"], "results": unique_results})
        except Exception as e:
            results_by_query.append({"query": q["query"], "results": [], "error": str(e)})

    return results_by_query


def build_context(results_by_query):
    lines = []
    for group in results_by_query:
        lines.append(f"\n### Suchanfrage: {group['query']}")
        if not group["results"]:
            lines.append("  (Keine Ergebnisse)")
            continue
        for r in group["results"]:
            title = r.get("title", "Kein Titel")
            url = r.get("url", "")
            content = r.get("content", "")[:400]
            lines.append(f"  - [{title}]({url})\n    {content}")
    return "\n".join(lines)


def summarize_with_claude(context):
    prompt = f"""Du bist ein Business-Intelligence-Assistent für einen Sales-Experten im Bereich Finance-Software und BPM.
Analysiere die folgenden Suchergebnisse und erstelle eine kompakte, deutsche Zusammenfassung in HTML.

Strukturiere die Ausgabe mit diesen vier Abschnitten (als HTML mit passenden Tags, kein Markdown):
1. <h2>🏢 GBTEC Aktuell</h2> – Neuigkeiten, Posts, Ankündigungen direkt von oder über GBTEC
2. <h2>📊 BPM & GRC Trends</h2> – Branchentrends, neue Entwicklungen in BPM, GRC, Process Mining
3. <h2>🌐 Was die Welt über GBTEC schreibt</h2> – Externe Medien, Blogs, Presse über GBTEC
4. <h2>🔗 Top 5 Links</h2> – Die 5 relevantesten Links als klickbare HTML-Liste

Schreibe präzise, professionell und auf Deutsch. Hebe besonders relevante Signale für Sales-Opportunities hervor.

Suchergebnisse:
{context}
"""
    response = anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def send_email(html_body):
    today = date.today().strftime("%d.%m.%Y")
    subject = f"LinkedIn Digest – GBTEC & BPM – {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    html_full = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; max-width: 700px; margin: auto; padding: 20px; }}
    h2 {{ color: #0a66c2; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
    a {{ color: #0a66c2; }}
    .footer {{ margin-top: 30px; font-size: 11px; color: #999; }}
  </style>
</head>
<body>
  <h1 style="color:#333;">📋 Täglicher Digest – GBTEC & BPM</h1>
  <p style="color:#666;">{today} | Automatisch erstellt via GitHub Actions + Claude</p>
  <hr>
  {html_body}
  <div class="footer">Automatisch generiert. Quellen: LinkedIn (via Tavily), externe Medien.</div>
</body>
</html>"""

    msg.attach(MIMEText(html_full, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

    print(f"E-Mail erfolgreich gesendet an {EMAIL_TO}")


def main():
    print("Starte Tavily-Suche...")
    results = run_searches()

    print("Baue Kontext auf...")
    context = build_context(results)

    print("Erstelle Claude-Zusammenfassung...")
    summary_html = summarize_with_claude(context)

    print("Sende E-Mail...")
    send_email(summary_html)

    print("Fertig.")


if __name__ == "__main__":
    main()
