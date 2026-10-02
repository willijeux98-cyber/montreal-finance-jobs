"""
The safety net: sweeps of public job searches (LinkedIn's logged-out job search and the Government of Canada's
Job Bank) for Montreal investment roles. They catch firms that aren't on the board list at all. fetch.py drops
any row from a firm whose own board already returned postings, so the net only ever adds what the boards missed.
"""
import datetime as dt
import html
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8"}

QUERIES = [
    "investment analyst", "investment associate", "private equity", "venture capital", "private credit",
    "infrastructure investment", "real estate investment", "real estate acquisitions", "portfolio manager",
    "asset management analyst", "equity research", "investment banking", "mergers and acquisitions",
    "corporate development", "valuation analyst", "fund investments", "capital markets analyst", "credit analyst",
    "analyste placements", "analyste investissement", "capital de risque", "capital-investissement",
    "gestion de portefeuille", "financement immobilier", "fusions et acquisitions",
    "family office", "trading analyst", "acquisitions analyst", "analyste financement", "pension fund investments",
    "investment strategy", "infrastructure", "private markets",
]
LI_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
TODAY = dt.date.today()


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def nice(t):
    """Job Bank titles arrive in lower case: 'investment analyst' -> 'Investment Analyst'."""
    if t and t == t.lower():
        small = {"and", "of", "in", "en", "de", "des", "du", "et", "la", "le", "les", "a"}
        return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(t.split()))
    return t


def _age(iso):
    try:
        return (TODAY - dt.date.fromisoformat(iso)).days
    except Exception:
        return None


def linkedin():
    """LinkedIn's public (logged-out) job search, last 30 days, Montreal. Polite: one request at a time."""
    out, seen, read, blocked = [], set(), 0, 0
    s = requests.Session()
    s.headers.update(UA)
    for q in QUERIES:
        for start in (0, 25, 50):
            r = s.get(LI_URL, params={"keywords": q, "location": "Montreal, Quebec, Canada", "f_TPR": "r2592000",
                                      "start": start}, timeout=40)
            if r.status_code == 429:
                blocked += 1
                if blocked > 2:
                    if not out:
                        raise RuntimeError("LinkedIn rate-limited the sweep")
                    return out, read
                time.sleep(25)
                continue
            if r.status_code != 200:
                break
            cards = re.split(r"<li>\s*<div", r.text)[1:]
            for c in cards:
                urn = re.search(r"jobPosting:(\d+)", c)
                title = re.search(r'base-search-card__title">(.*?)</h3>', c, re.S)
                comp = re.search(r'base-search-card__subtitle">(.*?)</h4>', c, re.S)
                loc = re.search(r'job-search-card__location">(.*?)</span>', c, re.S)
                when = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', c)
                if not (urn and title and comp):
                    continue
                read += 1
                jid = urn.group(1)
                if jid in seen:
                    continue
                seen.add(jid)
                out.append(dict(c=_text(comp.group(1)), cat=None, t=_text(title.group(1)), l=_text(loc.group(1) if loc else ""),
                                u=f"https://www.linkedin.com/jobs/view/{jid}/", age=_age(when.group(1)) if when else None,
                                hq=False, net="LinkedIn"))
            if len(cards) < 10:
                break
            time.sleep(1.2)
    return out, read


JB_URL = "https://www.jobbank.gc.ca/jobsearch/jobsearch"
JB_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def jobbank():
    """Government of Canada Job Bank: newest postings first, Montreal area."""
    out, seen, read = [], set(), 0
    for q in QUERIES[:12] + ["analyste financier placements", "investment manager", "analyste financier investissements"]:
        r = requests.get(JB_URL, params={"searchstring": q, "locationstring": "Montréal, QC", "sort": "D"}, headers=UA, timeout=40)
        r.raise_for_status()
        for jid, body in re.findall(r'<article id="article-(\d+)"(.*?)</article>', r.text, re.S):
            read += 1
            if jid in seen:
                continue
            seen.add(jid)
            title = re.search(r'class="noctitle">(.*?)</span>', body, re.S)
            biz = re.search(r'class="business">(.*?)</li>', body, re.S)
            loc = re.search(r'class="location">(.*?)</li>', body, re.S)
            dte = re.search(r'class="date">(.*?)</li>', body, re.S)
            age = None
            if dte and JB_DATE.search(_text(dte.group(1))):
                try:
                    age = (TODAY - dt.datetime.strptime(JB_DATE.search(_text(dte.group(1))).group(1), "%B %d, %Y").date()).days
                except ValueError:
                    pass
            loc_t = re.sub(r"^Location\s*", "", _text(loc.group(1) if loc else ""))
            out.append(dict(c=_text(biz.group(1) if biz else ""), cat=None, t=nice(_text(title.group(1) if title else "")),
                            l=loc_t, u=f"https://www.jobbank.gc.ca/jobsearch/jobposting/{jid}", age=age, hq=False, net="Job Bank"))
        time.sleep(0.8)
    return out, read
