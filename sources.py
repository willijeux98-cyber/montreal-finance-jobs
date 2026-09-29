"""
Job-board fetchers for every hiring system the discovery scan finds.

Each fetcher returns (postings, count_read). A posting is a dict:
  c (company), cat, t (title), l (location text), u (url), age (days or None), hq (Montreal HQ?)
"""
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import xml.etree.ElementTree as ET

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "application/json, text/html;q=0.9",
      "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8"}
TODAY = dt.date.today()

# Firms whose head office (or main office) is in Montreal: "N locations" postings are kept for them.
MTL_HQ = {
    "CDPQ", "PSP Investments", "Ivanhoe Cambridge", "Fonds de solidarite FTQ", "Fondaction", "Investissement Quebec",
    "BDC", "Teralys Capital", "Power Corporation", "Sagard", "Power Sustainable", "Claridge", "Desjardins Capital",
    "Novacap", "Walter Capital Partners", "Champlain Financial", "XPND Capital", "Seafort Capital", "Inovia Capital",
    "Real Ventures", "Panache Ventures", "White Star Capital", "Amplitude Ventures", "Lumira Ventures", "Cycle Capital",
    "Diagram Ventures", "Luge Capital", "Tactico", "Front Row Ventures", "Anges Quebec", "Boreal Ventures", "Evolem",
    "Emerillon Capital", "Idealist Capital", "Fiera Capital", "Jarislowsky Fraser", "Letko Brosseau", "Van Berkom",
    "Montrusco Bolton", "Triasima", "Claret Asset Management", "Pembroke Management", "Addenda Capital",
    "AlphaFixe Capital", "Optimum Asset Management", "Formula Growth", "iA Financial Group", "Beneva", "Desjardins",
    "National Bank", "Laurentian Bank", "Couche-Tard", "CGI", "CAE", "WSP", "BRP", "Saputo", "Metro", "Dollarama",
    "Air Canada", "CN", "CN Investment Division", "Bombardier", "Lightspeed", "Nuvei", "Hydro-Quebec", "Gildan",
    "Stella-Jones", "Boralex", "Innergex", "Pomerleau", "Cogeco", "Quebecor", "TFI International",
    "Raymond Chabot Grant Thornton", "Richter",
}


def _get(url, **kw):
    r = requests.get(url, headers=kw.pop("headers", UA), timeout=40, **kw)
    r.raise_for_status()
    return r


def _iso_age(s):
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
        return (TODAY - d).days
    except Exception:
        return None


def _ms_age(ms):
    try:
        return (TODAY - dt.datetime.utcfromtimestamp(int(ms) / 1000).date()).days
    except Exception:
        return None


def _p(c, cat, t, l, u, age, hq):
    return dict(c=c, cat=cat, t=(t or "").strip(), l=(l or "").strip(), u=u, age=age, hq=hq)


# ---------------------------------------------------------------- Workday
def _wd_days(txt):
    t = (txt or "").lower()
    if "today" in t or "aujourd" in t:
        return 0
    if "yesterday" in t or "hier" in t:
        return 1
    m = re.search(r"(\d+)(\+?)", t)
    return (int(m.group(1)) + (1 if m.group(2) else 0)) if m else None


def workday(name, cat, hq, tenant, n, site, lang=None):
    base = f"https://{tenant}.wd{n}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    hdr = {**UA, "Content-Type": "application/json", "Accept": "application/json"}
    if lang:
        hdr["Accept-Language"] = lang

    def page(off, text=""):
        r = requests.post(api, json={"limit": 20, "offset": off, "searchText": text, "appliedFacets": {}},
                          headers=hdr, timeout=40)
        r.raise_for_status()
        return r.json()

    first = page(0)
    total = first.get("total", 0) or 0
    posts = list(first.get("jobPostings", []))
    queries = [("", total)]
    if total > 2000:  # very large global boards: only pull what mentions Montreal
        posts = []
        queries = []
        for q in ("Montreal", "Montréal"):
            d = page(0, q)
            posts += d.get("jobPostings", [])
            queries.append((q, d.get("total", 0) or 0))
    for q, tot in queries:
        with cf.ThreadPoolExecutor(6) as ex:
            for d in ex.map(lambda o: page(o, q), range(20, min(tot, 2000), 20)):
                posts += d.get("jobPostings", [])
    hinted = set()
    if total > 2000:
        hinted = {p.get("externalPath") for p in posts}
    elif not hq:
        try:
            d = page(0, "Montreal")
            extra = list(d.get("jobPostings", []))
            for off in range(20, min(d.get("total", 0) or 0, 400), 20):
                extra += page(off, "Montreal").get("jobPostings", [])
            hinted = {p.get("externalPath") for p in extra}
        except Exception:
            pass
    out, seen = [], set()
    for p in posts:
        u = f"{base}/{site}{p.get('externalPath', '')}"
        if u in seen:
            continue
        seen.add(u)
        row = _p(name, cat, p.get("title"), p.get("locationsText"), u, _wd_days(p.get("postedOn")), hq)
        row["hint"] = p.get("externalPath") in hinted   # the board's own search says Montreal is involved
        out.append(row)
    return out, total


# ---------------------------------------------------------------- JSON ATS
def greenhouse(name, cat, hq, tok):
    jobs = _get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs").json().get("jobs", [])
    return [_p(name, cat, j["title"], (j.get("location") or {}).get("name"), j["absolute_url"],
               _iso_age(j.get("first_published") or j.get("updated_at")), hq) for j in jobs], len(jobs)


def lever(name, cat, hq, tok):
    jobs = _get(f"https://api.lever.co/v0/postings/{tok}?mode=json").json()
    return [_p(name, cat, j.get("text"), (j.get("categories") or {}).get("location") or
               ", ".join((j.get("categories") or {}).get("allLocations") or []),
               j.get("hostedUrl"), _ms_age(j.get("createdAt")), hq) for j in jobs], len(jobs)


def ashby(name, cat, hq, tok):
    jobs = _get(f"https://api.ashbyhq.com/posting-api/job-board/{tok}").json().get("jobs", [])
    out = []
    for j in jobs:
        loc = j.get("location") or ""
        sec = ", ".join(x.get("location", "") for x in (j.get("secondaryLocations") or []) if isinstance(x, dict))
        out.append(_p(name, cat, j.get("title"), ", ".join(x for x in (loc, sec) if x), j.get("jobUrl"),
                      _iso_age(j.get("publishedAt")), hq))
    return out, len(jobs)


def smartrecruiters(name, cat, hq, tok):
    out, off, total = [], 0, 0
    while True:
        d = _get(f"https://api.smartrecruiters.com/v1/companies/{tok}/postings", params={"limit": 100, "offset": off}).json()
        total = d.get("totalFound", 0)
        for j in d.get("content", []):
            loc = j.get("location") or {}
            out.append(_p(name, cat, j.get("name"), ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                          f"https://jobs.smartrecruiters.com/{tok}/{j.get('id')}", _iso_age(j.get("releasedDate")), hq))
        off += 100
        if off >= total or off >= 1000:
            break
    return out, total


def bamboohr(name, cat, hq, sub):
    res = _get(f"https://{sub}.bamboohr.com/careers/list").json().get("result", [])
    out = []
    for j in res:
        loc = j.get("location") or {}
        out.append(_p(name, cat, j.get("jobOpeningName"), ", ".join(x for x in (loc.get("city"), loc.get("state")) if x),
                      f"https://{sub}.bamboohr.com/careers/{j.get('id')}", None, hq))
    return out, len(res)




def recruitee(name, cat, hq, sub):
    res = _get(f"https://{sub}.recruitee.com/api/offers/").json().get("offers", [])
    return [_p(name, cat, j.get("title"), j.get("location") or j.get("city"), j.get("careers_url"),
               _iso_age(j.get("published_at") or j.get("created_at")), hq) for j in res], len(res)


def rippling(name, cat, hq, tok):
    items = _get(f"https://ats.rippling.com/api/v2/board/{tok}/jobs").json().get("items", [])
    out = []
    for j in items:
        locs = j.get("locations") or j.get("workLocations") or []
        loc = ", ".join((x.get("name") if isinstance(x, dict) else str(x)) for x in locs)
        out.append(_p(name, cat, j.get("name"), loc, j.get("url"), None, hq))
    return out, len(items)


def breezy(name, cat, hq, sub):
    res = _get(f"https://{sub}.breezy.hr/json").json()
    out = []
    for j in res:
        loc = j.get("location") or {}
        out.append(_p(name, cat, j.get("name"), loc.get("name") if isinstance(loc, dict) else str(loc), j.get("url"),
                      _iso_age(j.get("published_date")), hq))
    return out, len(res)


def pinpoint(name, cat, hq, sub):
    res = _get(f"https://{sub}.pinpointhq.com/postings.json").json().get("data", [])
    out = []
    for j in res:
        loc = j.get("location") or {}
        out.append(_p(name, cat, j.get("title"), loc.get("name") if isinstance(loc, dict) else "", j.get("url"), None, hq))
    return out, len(res)


def teamtailor(name, cat, hq, sub):
    t = _get(f"https://{sub}.teamtailor.com/jobs.rss", headers={**UA, "Accept": "application/rss+xml"}).text
    root = ET.fromstring(t)
    out = []
    for it in root.iter("item"):
        title = it.findtext("title")
        link = it.findtext("link")
        loc = " ".join((e.text or "") for e in it if e.tag.endswith("location") or e.tag.endswith("city"))
        out.append(_p(name, cat, title, loc, link, None, hq))
    return out, len(out)




MTL_RX = re.compile(r"montr[eé]al|laval|longueuil|brossard|saint-laurent|st-laurent|dorval", re.I)


def workable(name, cat, hq, tok):
    url, out, nxt = f"https://apply.workable.com/api/v3/accounts/{tok}/jobs", [], None
    for _ in range(30):
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if nxt:
            body["token"] = nxt
        r = requests.post(url, json=body, headers={**UA, "Content-Type": "application/json"}, timeout=40)
        r.raise_for_status()
        d = r.json()
        for j in d.get("results", []):
            locs = [l.get("city") for l in (j.get("locations") or []) if l.get("city")] or [(j.get("location") or {}).get("city", "")]
            mt = [l for l in locs if MTL_RX.search(l or "")]
            out.append(_p(name, cat, j.get("title"), ", ".join(mt) if mt else ", ".join(x for x in locs if x),
                          f"https://apply.workable.com/{tok}/j/{j.get('shortcode')}/", _iso_age(j.get("published")), hq))
        nxt = d.get("nextPage")
        if not nxt:
            break
    return out, len(out)


def jobvite(name, cat, hq, tok):
    t = _get(f"https://jobs.jobvite.com/{tok}/jobs/positions", headers={**UA, "Accept": "text/html"}).text
    out = []
    for href, inner in re.findall(r'<a[^>]+href="(/' + re.escape(tok) + r'/job/[^"]+)"[^>]*>(.*?)</a>', t, re.S):
        parts = [x.strip() for x in re.split(r"<[^>]+>", inner) if x.strip()]
        title = html.unescape(parts[0]) if parts else ""
        loc = html.unescape(parts[-1]) if len(parts) > 1 else ""
        out.append(_p(name, cat, title, loc, "https://jobs.jobvite.com" + href, None, hq))
    return out, len(out)


def ultipro(name, cat, hq, company, board, host="recruiting.ultipro.com"):
    base, out, skip = f"https://{host}/{company}/JobBoard/{board}", [], 0
    for _ in range(20):
        r = requests.post(f"{base}/JobBoardView/LoadSearchResults",
                          json={"opportunitySearch": {"Top": 100, "Skip": skip, "QueryString": "", "OrderBy": [], "Filters": []}},
                          headers={**UA, "Content-Type": "application/json"}, timeout=40)
        r.raise_for_status()
        d = r.json()
        res = d.get("opportunities", [])
        for j in res:
            loc = ", ".join(((x.get("Address") or {}).get("City") or "") for x in (j.get("Locations") or []) if isinstance(x, dict))
            out.append(_p(name, cat, j.get("Title"), loc, f"{base}/OpportunityDetail?opportunityId={j.get('Id')}",
                          _iso_age(j.get("PostedDate")), hq))
        skip += 100
        if not res or skip >= d.get("totalCount", 0):
            break
    return out, len(out)


def rmk(name, cat, hq, base):
    """SAP SuccessFactors career sites publish every job in /sitemap.xml."""
    r = requests.get(base.rstrip("/") + "/sitemap.xml", headers=UA, timeout=90)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    items = list(root.iter("item"))
    if items:
        for it in items:
            t = it.findtext("title") or ""
            m = re.match(r"(.*)\s+\(([^()]*)\)\s*$", t)
            out.append(_p(name, cat, m.group(1) if m else t, m.group(2) if m else "", it.findtext("link"), None, hq))
    else:
        ns = "{http://www.google.com/schemas/sitemap/0.9}"
        for loc in root.iter(ns + "loc"):
            u = loc.text or ""
            m = re.search(r"/job/([^/]+)/\d+/?$", u)
            if not m:
                continue
            slug = requests.utils.unquote(m.group(1)).replace("-", " ")
            city = slug.split(" ")[0]
            out.append(_p(name, cat, slug[len(city):].strip() or slug, city, u, None, hq))
    return out, len(out)


def jibe(name, cat, hq, base):
    """Jibe career sites (KPMG): JSON API. Only a User-Agent header, or it returns nothing."""
    out, page = [], 1
    while page <= 20:
        r = requests.get(f"{base}/api/jobs", params={"location": "Montreal", "limit": 100, "page": page},
                         headers={"User-Agent": UA["User-Agent"]}, timeout=40)
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
        for j in jobs:
            x = j.get("data", {})
            out.append(_p(name, cat, x.get("title"), x.get("full_location") or x.get("city"),
                          f"{base}/professionals/jobs/{x.get('slug')}", _iso_age(x.get("posted_date")), hq))
        if len(jobs) < 100:
            break
        page += 1
    return out, len(out)


def wprss(name, cat, hq, feed):
    """WordPress job feed (BNP Paribas Canada)."""
    out = []
    for p in range(1, 11):
        r = requests.get(feed, params={"paged": p}, headers=UA, timeout=40)
        items = re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>", r.text, re.S)
        if r.status_code != 200 or not items:
            break
        for t, l in items:
            out.append(_p(name, cat, html.unescape(t).replace("\u200b", ""), "Montreal", l.strip(), None, hq))
    return out, len(out)


def phenom(name, cat, hq, base, prefix, locale, country):
    """Phenom career sites (Air Canada, BRP, Bell): the page's own search widget endpoint."""
    page = requests.get(base + prefix + "/search-results", headers=UA, timeout=40).text
    m = re.search(r'"pageId"\s*:\s*"([^"]+)"', page)
    page_id = m.group(1) if m else "page11"
    out, frm, total = [], 0, 1
    while frm < min(total, 2000):
        body = {"lang": locale, "deviceType": "desktop", "country": country, "pageName": "search-results",
                "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": frm, "jobs": True, "counts": True,
                "all_fields": ["category", "city"], "size": 100, "clearAll": False, "jdsource": "facets",
                "isSliderEnable": False, "pageId": page_id, "siteType": "external", "keywords": "", "global": True,
                "selected_fields": {}, "locationData": {}}
        r = requests.post(base + "/widgets", json=body, headers={**UA, "Content-Type": "application/json"}, timeout=40)
        r.raise_for_status()
        d = r.json().get("refineSearch", {})
        total = d.get("totalHits") or 0
        jobs = (d.get("data") or {}).get("jobs") or []
        if not jobs:
            break
        for j in jobs:
            loc = j.get("location") or ", ".join(x for x in (j.get("city"), j.get("state")) if x)
            out.append(_p(name, cat, j.get("title"), loc, f"{base}{prefix}/job/{j.get('jobId')}",
                          _iso_age(j.get("postedDate")), hq))
        frm += len(jobs)
    return out, total


def lbc(name, cat, hq, base):
    """Laurentian Bank's Next.js career site: CSRF token, then its search API."""
    s = requests.Session()
    s.headers.update(UA)
    sf = {"Referer": base + "/fr", "Origin": base, "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Accept": "*/*"}
    s.get(base + "/fr", timeout=40)
    tok = s.get(base + "/api/csrf", headers=sf, timeout=40).json()["token"]
    out, off = [], 0
    while off < 1000:
        body = {"index_name": "rs-lbc-index-fr-prod", "search_value": "", "offset": off, "limit": 100,
                "facets": ["locations", "jobtype", "jobcategories"],
                "query": {"filter_query": {"must": []}, "sort_query": [{"field": "postedon", "order": "desc"}], "search": ""},
                "search_fields": ["title", "locations", "jobcategories", "jobtype"]}
        r = s.post(base + "/api/jobs", json=body, headers={**sf, "x-csrf-token": tok, "accept": "application/json",
                                                         "accept-language": "fr"}, timeout=40)
        r.raise_for_status()
        vals = r.json().get("value", [])
        for j in vals:
            out.append(_p(name, cat, j.get("title"), ", ".join(j.get("locations") or j.get("city") or []),
                          base + "/fr/job-detail" + (j.get("joburl") or ""), _iso_age(j.get("postedon")), hq))
        if len(vals) < 100:
            break
        off += 100
    return out, len(out)


# ---------------------------------------------------------------- National Bank (Avature HTML)
NBC_ROW = re.compile(r'data-map="job-detail-link"\s+href="([^"]+)"\s+title="([^"]*)".*?</th>\s*<td>\s*(.*?)\s*</td>', re.S)


def nbc(name="National Bank", cat="ib", hq=True):
    out, off, seen = [], 0, set()
    while off < 1200:
        t = _get(f"https://emplois.bnc.ca/en_CA/careers/SearchJobs/?jobOffset={off}", headers={**UA, "Accept": "text/html"}).text
        new = [r for r in NBC_ROW.findall(t) if r[0] not in seen]
        if not new:
            break
        for u, title, loc in new:
            seen.add(u)
            out.append(_p(name, cat, html.unescape(title), html.unescape(re.sub(r"\s+", " ", loc)), u, None, hq))
        off += 20
    return out, len(out)


# ---------------------------------------------------------------- careers-page watcher (no job system)
JOBISH = re.compile(r"\b(analyst|analyste|associate|associ[ée]e?|intern|internship|stagiaire|stage|vice[- ]pr[ée]sidente?|"
                    r"director|directeur|directrice|manager|gestionnaire|conseill[eè]re?|advisor|controller|contr[ôo]leur|"
                    r"specialist|sp[ée]cialiste|coordinator|coordonnat\w*|officer|trader|comptable|accountant|principal)\b", re.I)
NOT_JOB = re.compile(r"^(our|nos|notre|meet|voir|see|view|read|lire|about|à propos)\b|team|[ée]quipe|portfolio compan|"
                     r"entreprises en portefeuille|discover more|open jobs|conseil d.administration|board of|newsletter|annual report|rapport annuel|"
                     r"press release|communiqu|podcast|webinar|event|[ée]v[ée]nement|linkedin|cookie", re.I)
NAVISH = re.compile(r"^(careers?|carri[eè]res?|jobs?|emplois?|join us|contact|login|apply|postuler|learn more|"
                    r"en savoir plus|home|accueil|privacy)$", re.I)


def careers_page(name, cat, hq, url):
    t = _get(url, headers={**UA, "Accept": "text/html"}).text
    body = re.sub(r"<(script|style|nav|footer|header)\b.*?</\1>", " ", t, flags=re.S | re.I)
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', body, re.S | re.I):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        text = re.sub(r"^\d{4}-\d{2}-\d{2}\s*", "", text)
        if re.search(r"open jobs|\d{1,3}(,\d{3})+|discover more|view & apply|voir l.offre", text, re.I):
            text = re.split(r"\s{0,1}(view & apply|→|\d{1,3}(?:,\d{3})+)", text)[0].strip()
            if re.search(r"jobs$|discover more", text, re.I):
                continue
        if not (8 <= len(text) <= 110) or NAVISH.match(text) or NOT_JOB.search(text) or not JOBISH.search(text):
            continue
        link = requests.compat.urljoin(url, href)
        if not re.match(r"https?://", link, re.I):
            continue
        if link.rstrip("/") == url.rstrip("/"):
            link = url + "#" + re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        if link in seen or text.lower() in seen:
            continue
        seen.add(link); seen.add(text.lower())
        oc = OTHER_CITY.search(text)
        out.append(_p(name, cat, text, oc.group(0) if oc else ("Montreal (head office)" if hq else "Location not stated"), link, None, hq))
    for h in re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", body, re.S | re.I):  # jobs listed as headings, no link
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
        text = re.sub(r"^\d{4}-\d{2}-\d{2}\s*", "", text)
        if 8 <= len(text) <= 110 and JOBISH.search(text) and not NOT_JOB.search(text) and text.lower() not in seen:
            seen.add(text.lower())
            oc = OTHER_CITY.search(text)
            out.append(_p(name, cat, text, oc.group(0) if oc else ("Montreal (head office)" if hq else "Location not stated"),
                          url + "#" + re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-"), None, hq))
    return out, len(out)


# ---------------------------------------------------------------- registry
FETCHERS = {
    "workday": lambda n, c, h, k: workday(n, c, h, k[0], int(k[1]), k[2]),
    "greenhouse": lambda n, c, h, k: greenhouse(n, c, h, k),
    "lever": lambda n, c, h, k: lever(n, c, h, k),
    "ashby": lambda n, c, h, k: ashby(n, c, h, k),
    "smartrecruiters": lambda n, c, h, k: smartrecruiters(n, c, h, k),
    "bamboohr": lambda n, c, h, k: bamboohr(n, c, h, k),
    "workable": lambda n, c, h, k: workable(n, c, h, k),
    "recruitee": lambda n, c, h, k: recruitee(n, c, h, k),
    "rippling": lambda n, c, h, k: rippling(n, c, h, k),
    "breezy": lambda n, c, h, k: breezy(n, c, h, k),
    "pinpoint": lambda n, c, h, k: pinpoint(n, c, h, k),
    "teamtailor": lambda n, c, h, k: teamtailor(n, c, h, k),
    "ultipro": lambda n, c, h, k: ultipro(n, c, h, *k),
    "rmk": lambda n, c, h, k: rmk(n, c, h, k),
    "workday_fr": lambda n, c, h, k: workday(n, c, h, k[0], int(k[1]), k[2], lang="fr-CA"),
    "phenom": lambda n, c, h, k: phenom(n, c, h, *k),
    "lbc": lambda n, c, h, k: lbc(n, c, h, k),
    "jibe": lambda n, c, h, k: jibe(n, c, h, k),
    "wprss": lambda n, c, h, k: wprss(n, c, h, k),
    "jobvite": lambda n, c, h, k: jobvite(n, c, h, k),
    "careers": lambda n, c, h, k: careers_page(n, c, h, k),
}

# Boards that discovery can't find on its own (verified by hand). kind, key, name, cat
MANUAL = [
    ("workday", ["cdpq", 10, "CDPQ"], "CDPQ", "pension"),
    ("workday", ["investpsp", 3, "psp_careers"], "PSP Investments", "pension"),
    ("workday", ["fieracapital", 3, "Career"], "Fiera Capital", "am"),
    ("workday", ["desjardins", 10, "Desjardins"], "Desjardins", "ib"),
    ("workday", ["ardian", 103, "ArdianCareers"], "Ardian", "pe_vc"),
    ("workday", ["omers", 3, "OMERS_External"], "OMERS", "pension"),
    ("workday", ["brookfield", 5, "brookfield"], "Brookfield", "pe_vc"),
    ("workday", ["blackstone", 1, "Blackstone_Careers"], "Blackstone", "pe_vc"),
    ("workday", ["carlyle", 1, "Carlyle"], "Carlyle", "pe_vc"),
    ("workday", ["blackrock", 1, "BlackRock_Professional"], "BlackRock", "am"),
    ("workday", ["statestreet", 1, "Global"], "State Street", "am"),
    ("workday", ["bmo", 3, "External"], "BMO", "ib"),
    ("workday", ["cibc", 3, "search"], "CIBC", "ib"),
    ("workday", ["td", 3, "TD_Bank_Careers"], "TD", "ib"),
    ("workday", ["raymondjames", 1, "RaymondJamesCareers"], "Raymond James", "ib"),
    ("workday", ["tmx", 3, "TMX_Careers"], "TMX Group", "markets"),
    ("workday", ["manulife", 3, "MFCJH_Jobs"], "Manulife", "insurer"),
    ("workday", ["sunlife", 3, "Experienced-Jobs"], "Sun Life", "insurer"),
    ("greenhouse", "squarepointcapital", "Squarepoint", "hedge"),
    ("greenhouse", "drweng", "DRW", "hedge"),
    ("greenhouse", "point72", "Point72", "hedge"),
    ("greenhouse", "schonfeld", "Schonfeld", "hedge"),
    ("greenhouse", "aqr", "AQR", "hedge"),
    ("greenhouse", "mangroup", "Man Group", "hedge"),
    ("greenhouse", "towerresearchcapital", "Tower Research", "hedge"),
    ("greenhouse", "jumptrading", "Jump Trading", "hedge"),
    ("greenhouse", "janestreet", "Jane Street", "hedge"),
    ("greenhouse", "imc", "IMC", "hedge"),
    ("greenhouse", "virtu", "Virtu", "hedge"),
    ("greenhouse", "worldquant", "WorldQuant", "hedge"),
    ("greenhouse", "flowtraders", "Flow Traders", "hedge"),
    ("greenhouse", "exoduspoint", "ExodusPoint", "hedge"),
    ("greenhouse", "stepstone", "StepStone", "pe_vc"),
    ("ashby", "georgian", "Georgian", "pe_vc"),
    ("ashby", "inoviacapital", "Inovia Capital", "pe_vc"),
    ("ashby", "pinebridge", "PineBridge", "am"),
    ("rippling", "novacap", "Novacap", "pe_vc"),
    ("bamboohr", "pictonmahoney", "Picton Mahoney", "am"),
    # added after the 28 Sep coverage audit (each endpoint verified to return postings)
    ("workday", ["bdc", 10, "BDC_Careers"], "BDC", "pe_vc"),
    ("workday", ["intactfc", 3, "intactfc"], "Intact", "insurer"),
    ("workday", ["cogeco", 3, "Cogeco_Careers"], "Cogeco", "corpdev"),
    ("workday", ["cgf", 10, "CG"], "Canaccord Genuity", "ib"),
    ("workday", ["rbc", 3, "RBCGLOBAL1"], "RBC", "ib"),
    ("workday", ["rbc", 3, "RBCEARLYTALENT1"], "RBC", "ib"),
    ("workday", ["pwc", 3, "Global_Experienced_Careers"], "PwC", "advisory"),
    ("workday", ["pwc", 3, "Global_Campus_Careers"], "PwC", "advisory"),
    ("greenhouse", "canadainfrastructurebank", "Canada Infrastructure Bank", "pension"),
    ("workable", "export-development-canada", "EDC", "insurer"),
    ("jobvite", "addendacapital-fr", "Addenda Capital", "am"),
    ("ultipro", ["MNP5000MNPL", "062c8fba-7371-4cd7-9e8a-94a0b8019ffc", "recruiting.ultipro.ca"], "MNP", "advisory"),
    ("rmk", "https://careers.deloitte.ca", "Deloitte", "advisory"),
    ("rmk", "https://careers.ey.com", "EY", "advisory"),
    ("rmk", "https://jobs.scotiabank.com", "Scotiabank", "ib"),
    ("rmk", "https://careers.cn.ca", "CN", "corpdev"),
    ("rmk", "https://jobs.bombardier.com", "Bombardier", "corpdev"),
    ("rmk", "https://emploi.hydroquebec.com", "Hydro-Quebec", "corpdev"),
    ("jibe", "https://careers.kpmg.ca", "KPMG", "advisory"),
    ("wprss", "https://www.bnpparibas.ca/en/jobs/feed/", "BNP Paribas", "ib"),
    ("careers", "https://valnetconcept.applytojob.com/apply", "Valnet", "pe_vc"),
    ("careers", "https://www.boralex.com/fr/nous-rejoindre/nos-offres-demploi", "Boralex", "corpdev"),
    # JavaScript-only career sites, read through the feeds their pages use
    ("lbc", "https://jobs.banquelaurentienne.ca", "Laurentian Bank", "ib"),
    ("phenom", ["https://careers.aircanada.com", "/ca/en", "en_ca", "ca"], "Air Canada", "corpdev"),
    ("phenom", ["https://careers.brp.com", "/global/en", "en_global", "global"], "BRP", "corpdev"),
    ("phenom", ["https://jobs.bell.ca", "/ca/en", "en_ca", "ca"], "Bell", "corpdev"),
    ("smartrecruiters", "Videotron", "Quebecor", "corpdev"),
    # Desjardins again in French: some titles only exist in French and would be missed in English
    ("workday_fr", ["desjardins", 10, "Desjardins"], "Desjardins", "ib"),
    ("workday_fr", ["cdpq", 10, "CDPQ"], "CDPQ", "pension"),
]


try:
    from firms_seed import SEED
    SEED_NAMES = {x[0] for x in SEED}
except Exception:
    SEED_NAMES = set()

OTHER_CITY = re.compile(r"\b(toronto|vancouver|calgary|edmonton|ottawa|winnipeg|halifax|waterloo|mississauga|"
                        r"new york|boston|chicago|houston|san francisco|london|paris|madrid|milan|frankfurt|"
                        r"zurich|luxembourg|singapore|hong kong|tokyo|sydney|dubai)\b", re.I)


MANUAL_NAMES = {m[2] for m in MANUAL} | {"National Bank"}
BASE_HQ = set(MTL_HQ) | {"Valnet", "Canada Infrastructure Bank", "Bell"}
MTL_HQ |= {"Valnet", "Addenda Capital", "Bell"}


def build_sources():
    """Merge hand-verified boards with data/boards.json from discover.py. Returns [(callable, label)]."""
    seen, srcs, owner = set(), [], {}

    def add(kind, key, name, cat):
        key = [str(x) for x in key] if isinstance(key, list) else key
        k = (kind, json.dumps(key, sort_keys=True).lower())
        tenant = (kind, (key[0] if isinstance(key, list) else key).lower())
        if k in seen or kind not in FETCHERS:
            return
        if kind != "careers" and owner.get(tenant, name) != name:
            return  # e.g. Desjardins' own board listed again under "Desjardins Capital"
        owner.setdefault(tenant, name)
        seen.add(k)
        hq = name in (MTL_HQ if kind == "careers" else BASE_HQ)
        srcs.append((lambda kind=kind, key=key, name=name, cat=cat, hq=hq: FETCHERS[kind](name, cat, hq, key), name))

    for kind, key, name, cat in MANUAL:
        add(kind, key, name, cat)
    srcs.append((nbc, "National Bank"))
    seen.add(("nbc", "nbc"))
    try:
        found = json.load(open(os.path.join(ROOT, "data", "boards.json"), encoding="utf-8"))
    except FileNotFoundError:
        found = []
    for f in found:
        name, cat = f["name"], f["cat"]
        rc = f.get("rc", False) and name not in SEED_NAMES  # directory firms we know nothing else about
        if rc:
            MTL_HQ.add(name)
        if f["boards"]:
            for kind, key in f["boards"]:
                add(kind, key, name, cat)
        elif f.get("careers") and (name in MTL_HQ or rc) and name not in MANUAL_NAMES:
            host = re.sub(r"^https?://", "", f["careers"]).split("/")[0].lower()
            if cat == "pe_vc" and re.match(r"(careers|jobs|talent)\.", host):
                continue  # VC "careers." sites are portfolio-company talent boards, not the fund's own jobs
            add("careers", f["careers"], name, cat)
    return srcs
