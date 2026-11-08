"""
The safety net: sweeps of public job searches for Canadian high-finance roles at firms the board list doesn't read
directly (boutique hedge funds, search funds, small PE and VC shops that only post on LinkedIn).

  LinkedIn            logged-out job search, all of Canada, entry and associate level, last 30 days
  Job Bank            Government of Canada job bank, all of Canada, newest first
  eFinancialCareers   the finance job board's own search API, Toronto / Montreal / Vancouver / Calgary

fetch.py drops any row from a firm whose own board already returned postings, so the net only adds what the
boards missed.
"""
import datetime as dt
import html
import os
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8"}

QUERIES = [
    # buy side
    "private equity", "venture capital", "growth equity", "hedge fund", "investment analyst", "investment associate",
    "portfolio analyst", "asset management analyst", "pension fund investments", "fund investments", "secondaries",
    "co-investment", "family office", "private credit", "infrastructure investment", "real estate investment",
    "real estate acquisitions", "search fund",
    # sell side and advisory
    "investment banking", "mergers and acquisitions", "M&A analyst", "leveraged finance", "equity research",
    "sales and trading", "trading analyst", "fixed income analyst", "capital markets analyst", "restructuring analyst",
    "valuation analyst", "transaction advisory", "corporate development",
    # quant and investment risk
    "quantitative analyst", "quantitative researcher", "investment risk", "market risk analyst",
    # French
    "analyste placements", "analyste investissement", "capital de risque", "capital-investissement",
    "fusions et acquisitions", "gestion de portefeuille", "analyste financement",
]
LI_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
TODAY = dt.date.today()
QUICK = os.environ.get("PB_QUICK") == "1"   # local test runs: a short sweep


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
        return (TODAY - dt.date.fromisoformat(str(iso)[:10])).days
    except Exception:
        return None


STATS = {"li_requests": 0, "li_limited": 0, "li_cards": 0, "li_unique": 0, "jb_requests": 0, "jb_cards": 0,
         "efc_requests": 0, "efc_cards": 0}


def linkedin(budget=None):
    """LinkedIn's public (logged-out) job search: all of Canada, entry and associate level (f_E=2,3), last 30 days.
    10 results a page; one request at a time, with patient retries when LinkedIn asks us to slow down. Stops after
    `budget` seconds whatever happens."""
    budget = budget or (120 if QUICK else 1500)
    out, seen, read = [], set(), 0
    t0 = time.time()
    s = requests.Session()
    s.headers.update(UA)
    for q in QUERIES[:6] if QUICK else QUERIES:
        for start in range(0, 250, 10):
            if time.time() - t0 > budget:
                STATS["li_unique"] = len(out)
                return out, read
            r = None
            for wait in (0, 20, 45):
                time.sleep(wait)
                STATS["li_requests"] += 1
                r = s.get(LI_URL, params={"keywords": q, "location": "Canada", "f_TPR": "r2592000", "f_E": "2,3",
                                          "start": start}, timeout=40)
                if r.status_code != 429:
                    break
                STATS["li_limited"] += 1
            if r is None or r.status_code != 200:
                break
            cards = re.split(r"<li>\s*<div", r.text)[1:]
            fresh = 0
            for c in cards:
                urn = re.search(r"jobPosting:(\d+)", c)
                title = re.search(r'base-search-card__title">(.*?)</h3>', c, re.S)
                comp = re.search(r'base-search-card__subtitle">(.*?)</h4>', c, re.S)
                loc = re.search(r'job-search-card__location">(.*?)</span>', c, re.S)
                when = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', c)
                if not (urn and title and comp):
                    continue
                read += 1
                STATS["li_cards"] += 1
                jid = urn.group(1)
                if jid in seen:
                    continue
                seen.add(jid)
                fresh += 1
                out.append(dict(c=_text(comp.group(1)), cat=None, t=_text(title.group(1)), l=_text(loc.group(1) if loc else ""),
                                u=f"https://www.linkedin.com/jobs/view/{jid}/", age=_age(when.group(1)) if when else None,
                                hq=False, net="LinkedIn"))
            if len(cards) < 10 or not fresh:
                break
            time.sleep(1.5)
    STATS["li_unique"] = len(out)
    if not out and STATS["li_limited"]:
        raise RuntimeError("LinkedIn rate-limited the sweep")
    return out, read


JB_URL = "https://www.jobbank.gc.ca/jobsearch/jobsearch"
JB_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def jobbank():
    """Government of Canada Job Bank: newest postings first, all of Canada."""
    out, seen, read = [], set(), 0
    qs = QUERIES[:20] + ["analyste financier placements", "investment manager", "analyste financier investissements"]
    for q in qs[:4] if QUICK else qs:
        STATS["jb_requests"] += 1
        r = requests.get(JB_URL, params={"searchstring": q, "sort": "D"}, headers=UA, timeout=40)
        r.raise_for_status()
        for jid, body in re.findall(r'<article id="article-(\d+)"(.*?)</article>', r.text, re.S):
            read += 1
            STATS["jb_cards"] += 1
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


EFC_URL = "https://job-search-api.efinancialcareers.com/v1/efc/jobs/search"
EFC_CITIES = [("Toronto, Ontario, Canada", 43.6532, -79.3832), ("Montreal, Quebec, Canada", 45.5019, -73.5674),
              ("Vancouver, British Columbia, Canada", 49.2827, -123.1207), ("Calgary, Alberta, Canada", 51.0447, -114.0719)]
EFC_QUERIES = ["analyst", "associate", "investment", "private equity", "trading", "portfolio", "quantitative",
               "research", "credit", "banking"]


def efc():
    """eFinancialCareers' own search API, city by city (its country filter returns nothing for Canada)."""
    out, seen, read = [], set(), 0
    for name, lat, lng in EFC_CITIES[:1] if QUICK else EFC_CITIES:
        for q in EFC_QUERIES[:3] if QUICK else EFC_QUERIES:
            for page in range(1, 6):
                STATS["efc_requests"] += 1
                r = requests.get(EFC_URL, params={"q": q, "location": name, "latitude": lat, "longitude": lng,
                                                  "locationPrecision": "City", "radius": 50, "radiusUnit": "km",
                                                  "countryCode2": "CA", "page": page, "pageSize": 100,
                                                  "currencyCode": "CAD", "language": "en"}, headers=UA, timeout=40)
                r.raise_for_status()
                d = r.json()
                rows = d.get("data") or []
                for x in rows:
                    read += 1
                    STATS["efc_cards"] += 1
                    if x.get("id") in seen:
                        continue
                    seen.add(x.get("id"))
                    loc = x.get("jobLocation") or {}
                    if loc.get("country") and loc.get("country") != "Canada":
                        continue
                    out.append(dict(c=(x.get("companyName") or x.get("clientBrandName") or "").strip(), cat=None,
                                    t=(x.get("title") or "").strip(), l=loc.get("displayName") or "",
                                    u="https://www.efinancialcareers.ca" + (x.get("detailsPageUrl") or ""),
                                    age=_age(x.get("postedDate")), hq=False, net="eFinancialCareers"))
                if len(rows) < 100:
                    break
                time.sleep(0.5)
    return out, read
