import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from tavily import TavilyClient
import anthropic

# --- Config ---
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_FROM = "mr.m.heyden@gmail.com"
EMAIL_TO = "mr.m.heyden@gmail.com"

tavily = TavilyClient(api_key=TAVILY_API_KEY)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# --- Suche ---
queries = [
    {"query": "GBTEC BPM BIC Platform news", "include_domains": ["linkedin.com"], "search_depth": "advanced", "max_results": 5},
    {"query": "GBTEC GRC Process Mining update", "include_domains": ["linkedin.com"], "search_depth": "advanced", "max_results": 5},
    {"query": "GBTEC BIC Process Design linkedin", "search_depth": "advanced", "max_results": 5},
    {"query": "Business Process Management BPM trends 2026", "include_domains": ["linkedin.com"], "search_depth": "advanced", "max_results": 5},
    {"query": "GBTEC Bochum news", "exclude_domains": ["linkedin.com"], "search_depth": "basic", "max_results": 5},
]

results_raw = []
seen_urls = set()

for q in queries:
    try:
        resp = tavily.search(**q)
        for r in resp.get("results", []):
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                results_raw.append(r)
    except Exception as e:
        print(f"Fehler bei Query '{q['query']}': {e}")

if not results_raw:
    print("Keine Ergebnisse gefunden. Abbruch.")
    exit(0)

# --- Zusammenfassung via Claude ---
results_text = "\n\n".join(
    f"Titel: {r.get('title', 'n/a')}\nURL: {r['url']}\nInhalt: {r.get('content', 'n/a')[:500]}"
    for r in results_raw
)

prompt = f"""Du bist ein Assistent, der wöchentliche LinkedIn-Digests auf Deutsch erstellt.

Hier sind die aktuellen Suchergebnisse zu GBTEC und BPM:

{results_text}

Erstelle eine strukturierte HTML-Zusammenfassung mit folgenden Abschnitten:
1. 🏢 GBTEC Aktuell – Was hat GBTEC diese Woche kommuniziert?
2. 📊 BPM & GRC Trends – Welche Branchenthemen sind relevant?
3. 🌐 Was die Welt über GBTEC schreibt – Externe Erwähnungen
4. 🔗 Top 5 Links – Die wichtigsten Links als klickbare HTML-Liste

Schreibe prägnant, professionell und auf Deutsch. Nutze einfaches HTML-Formatting (h2, p, ul, li, a).
Kein <!DOCTYPE>, kein <html>/<body>-Tag – nur den Inhaltsbereich."""

response = claude.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1500,
    messages=[{"role": "user", "content": prompt}]
)

html_body = response.content[0].text

# --- E-Mail ---
date_str = datetime.now().strftime("%d.%m.%Y")
subject = f"LinkedIn Digest – GBTEC & BPM – KW {datetime.now().isocalendar()[1]} ({date_str})"

full_html = f"""
<html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: auto; padding: 20px;">
<h1 style="color: #0077b5;">🔗 LinkedIn Digest – GBTEC & BPM</h1>
<p style="color: #666;">Woche {datetime.now().isocalendar()[1]} | {date_str}</p>
<hr/>
{html_body}
<hr/>
<p style="color: #aaa; font-size: 12px;">Automatisch generiert von claude-linkedin-digest via GitHub Actions</p>
</body></html>
"""

msg = MIMEMultipart("alternative")
msg["Subject"] = subject
msg["From"] = EMAIL_FROM
msg["To"] = EMAIL_TO
msg.attach(MIMEText(full_html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(EMAIL_FROM, EMAIL_PASSWORD)
    server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

print(f"Digest erfolgreich gesendet: {subject}")
