"""
Montreal high-finance job desk.

Pulls postings straight from each employer's hiring system (never from job
sites), keeps the Montreal buy-side / investment banking / markets seats,
ranks them against William's resume, and writes docs/index.html.

Run:  python fetch.py
"""
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(ROOT, "data", "seen.json")
TEMPLATE = os.path.join(ROOT, "template.html")
OUT = os.path.join(ROOT, "docs", "index.html")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "application/json"}
TODAY = dt.date.today()

# ---------------------------------------------------------------- sources
# (display name, category, hq_montreal)
# category: pension | pe_vc | hedge | am | ib | markets | insurer
WORKDAY = [
    # name, tenant, wd#, site, category, hq_montreal
    ("CDPQ", "cdpq", 10, "CDPQ", "pension", True),
    ("PSP Investments", "investpsp", 3, "psp_careers", "pension", True),
    ("Fiera Capital", "fieracapital", 3, "Career", "am", True),
    ("Desjardins", "desjardins", 10, "Desjardins", "ib", True),
    ("OMERS", "omers", 3, "OMERS_External", "pension", False),
    ("Brookfield", "brookfield", 5, "brookfield", "pe_vc", False),
    ("Blackstone", "blackstone", 1, "Blackstone_Careers", "pe_vc", False),
    ("Carlyle", "carlyle", 1, "Carlyle", "pe_vc", False),
    ("BlackRock", "blackrock", 1, "BlackRock_Professional", "am", False),
    ("State Street", "statestreet", 1, "Global", "am", False),
    ("BMO", "bmo", 3, "External", "ib", False),
    ("CIBC", "cibc", 3, "search", "ib", False),
    ("TD", "td", 3, "TD_Bank_Careers", "ib", False),
    ("Raymond James", "raymondjames", 1, "RaymondJamesCareers", "ib", False),
    ("TMX Group", "tmx", 3, "TMX_Careers", "markets", False),
    ("Manulife", "manulife", 3, "MFCJH_Jobs", "insurer", False),
    ("Sun Life", "sunlife", 3, "Experienced-Jobs", "insurer", False),
]
GREENHOUSE = [
    ("Squarepoint", "squarepointcapital", "hedge"),
    ("DRW", "drweng", "hedge"),
    ("Point72", "point72", "hedge"),
    ("Schonfeld", "schonfeld", "hedge"),
    ("AQR", "aqr", "hedge"),
    ("Man Group", "mangroup", "hedge"),
    ("Tower Research", "towerresearchcapital", "hedge"),
    ("Jump Trading", "jumptrading", "hedge"),
    ("Jane Street", "janestreet", "hedge"),
    ("IMC", "imc", "hedge"),
    ("Virtu", "virtu", "hedge"),
    ("WorldQuant", "worldquant", "hedge"),
    ("Flow Traders", "flowtraders", "hedge"),
    ("ExodusPoint", "exoduspoint", "hedge"),
    ("StepStone", "stepstone", "pe_vc"),
]
ASHBY = [
    ("Georgian", "georgian", "pe_vc"),
    ("Inovia Capital", "inoviacapital", "pe_vc"),
    ("PineBridge", "pinebridge", "am"),
]
RIPPLING = [("Novacap", "novacap", "pe_vc", True)]
BAMBOO = [("Picton Mahoney", "pictonmahoney", "am", False)]

# ---------------------------------------------------------------- filters
MTL = re.compile(r"montr[eé]al|laval|longueuil|brossard|boucherville|pointe-claire", re.I)
MULTI = re.compile(r"^\s*\d+\s+(locations|lieux|possible locations|lieux possibles)", re.I)

EXCLUDE = re.compile(
    r"develop|développ|engineer|ingénieur|software|logiciel|devops|cyber|sécurité|security|"
    r"technolog|\bIT\b|\bTI\b|cloud|network|réseau|system admin|administrat(or|eur) syst|"
    r"help ?desk|support|soutien|assistant|adjoint|réception|receptionist|"
    r"human resources|ressources humaines|\bHR\b|\bRH\b|talent|recrut|recruit|payroll|paie|"
    r"legal|juridique|counsel|avocat|lawyer|notaire|paralegal|"
    r"marketing|communications|designer|\bUX\b|\bUI\b|graphi|"
    r"customer service|service (à|a) la client|call cent|centre d.appel|contact cent|"
    r"teller|caissi|mortgage|hypoth|financial planner|planificat|branch|succursale|"
    r"personal financ|finances personnelles|wealth advis|conseiller en gestion de patrimoine|"
    r"banking advis|conseiller bancaire|relationship manager, small|"
    r"facilit|nurse|infirm|driver|chauffeur|claims|réclamation|sinistre|actuar|"
    r"fraud|fraude|\bAML\b|anti-money|blanchiment|compliance|conformité|"
    r"internal audit|audit interne|accountant|comptab|accounting|payable|tax\b|fiscal|"
    r"procurement|approvisionnement|scrum|agile coach|product owner|"
    r"data engineer|machine learning engineer|site reliab|administrative|"
    r"insurance advisor|conseiller en assurance|sales representative|représentant|"
    r"platform|applications? specialist|infrastructure specialist|analytics infrastructure|ULL|colo|"
    r"architect|scientist|personal banker|banquier|investment advisor|conseiller en placement|"
    r"investorline|regional sales|sales manager|wealth|patrimoine|nesbitt|wood gundy|"
    r"investment and financing|placement et financement|credit card|cartes? de crédit|"
    r"representative|retirement specialist|investment and retirement|"
    r"solutions delivery|interface utilisateur|bases de données|database|solutions numériques|digital solutions",
    re.I)

# front-office investment / deal / markets work
STRONG = [
    (r"private equity|capital[- ]investissement|buyout", "private equity"),
    (r"venture|capital de risque|growth equity|croissance", "venture / growth"),
    (r"investment banking|banque d.investissement|financement corporatif|corporate finance|"
     r"\bM&A\b|mergers|fusions|acquisitions|leveraged finance|debt capital|equity capital|\bDCM\b|\bECM\b",
     "investment banking"),
    (r"private credit|crédit privé|credit invest|investissements? en crédit|direct lending",
     "private credit"),
    (r"infrastructure invest|investissements? en infrastructure|infrastructures?\b(?!.*technolog)",
     "infrastructure investing"),
    (r"real estate invest|placements? immobili|investissements? immobili|immobilier",
     "real estate investing"),
    (r"natural resources|ressources naturelles", "natural resources investing"),
    (r"equity research|recherche (sur les )?actions|research analyst|analyste.{0,12}recherche|"
     r"fundamental research", "research"),
    (r"sales (&|and) trading|trading|trader|négoci|execution|exécution", "trading"),
    (r"derivatives|dérivés|fixed income|revenus? fixes?|rates|taux|structured|structurés|"
     r"securiti[sz]ation|titrisation", "markets"),
    (r"portfolio manag|gestion de portefeuille|gestionnaire de portefeuille|asset allocation|"
     r"répartition de l.actif|total fund|public markets|marchés publics|multi-asset|multiactifs",
     "portfolio management"),
    (r"capital markets|marchés des capitaux|global markets|marchés mondiaux", "capital markets"),
    (r"invest|placement|co-invest|alpha|hedge fund|fund investment|fonds", "investments"),
]
MEDIUM = [
    (r"valuation|évaluation", "valuation"),
    (r"middle office|back office|settlement|règlement", "markets operations"),
    (r"performance", "performance measurement"),
    (r"risk|risque", "investment risk"),
    (r"due diligence|diligence", "due diligence"),
    (r"strateg", "strategy"),
    (r"analytics|analytique|data|données", "analytics"),
    (r"treasury|trésorerie", "treasury"),
]
LEVEL_UP = re.compile(r"\b(analyst|analyste|associate|associé|junior|entry|early career)\b", re.I)
LEVEL_SENIOR_ANALYST = re.compile(r"senior analyst|analyste (principal|senior|sénior)|sr\.? analyst", re.I)
LEVEL_DOWN = re.compile(
    r"\b(manager|gestionnaire|director|directeur|directrice|vice[- ]president|\bVP\b|"
    r"head of|chef|principal\b(?!e?\s*\)?,)|partner|lead\b|managing|senior advisor|"
    r"conseill(er|ère) (principal|senior|sénior)|premier\(?-?è?r?e?\)? conseill|expert)\b",
    re.I)
STUDENT = re.compile(r"intern|stage|stagiaire|co-?op|student|étudiant|summer|été 20", re.I)
TEMP = re.compile(r"temporary|temporaire|contract|contrat|\d+\s*(months|mois)", re.I)

CAT_BASE = {"pension": 6, "pe_vc": 6, "hedge": 6, "am": 5, "ib": 5, "markets": 5, "insurer": 4}
CAT_WORDS = {
    "pension": "a Montreal pension investor",
    "pe_vc": "a private-markets investor",
    "hedge": "a trading / hedge fund shop",
    "am": "an asset manager",
    "ib": "a bank's markets and advisory side",
    "markets": "the exchange operator",
    "insurer": "an insurer's investment arm",
}
ANGLE = {
    "private equity": "Lead with the $20B merger diligence and your break-even and cost-volume models.",
    "venture / growth": "Lead with the $20B merger diligence and the fact you've built and shipped products at Manulife.",
    "investment banking": "Lead with the $20B merger diligence. That's M&A work, and bankers will recognize it.",
    "private credit": "Lead with the modelling and your insurance background. Credit is about pricing downside.",
    "infrastructure investing": "Lead with the merger diligence and the cost modelling. Infra underwriting rewards operational detail.",
    "real estate investing": "Lead with break-even and scenario modelling. Real estate underwriting is exactly that.",
    "natural resources investing": "Lead with the modelling and diligence. The sector is learnable, the seat is the point.",
    "research": "Come in with a stock or a sector you can actually talk about. Research seats test that.",
    "trading": "Lead with Bocconi derivatives, CFA Level I and your Python and SQL.",
    "markets": "Lead with Bocconi derivatives and capital markets coursework plus CFA Level I.",
    "portfolio management": "Lead with CFA Level I, Bocconi investment management and your data skills.",
    "capital markets": "Lead with Bocconi capital markets, CFA Level I, and that you're fully bilingual.",
    "investments": "Lead with CFA Level I and the $20B merger diligence.",
    "quant": "Only if you're ready for a stats and coding test. Your Python is real, the bar is high.",
    "valuation": "Lead with your break-even and scenario modelling and CFA Level I.",
    "markets operations": "A real way onto the markets side. Lead with your process work and CFA Level I.",
    "performance measurement": "Measuring how portfolios actually did. Lead with your data work and CFA Level I.",
    "investment risk": "Lead with the modelling and your insurance background.",
    "due diligence": "This is literally what you did at Beneva. Say so.",
    "strategy": "Same function as your Beneva seat, at a finance shop. Use it as the way in.",
    "analytics": "Your Manulife skill set at a finance shop. A foot in the door, not an investment seat.",
    "treasury": "Corporate treasury. Finance-heavy, not deal work.",
    None: "A foot in the door at a finance shop. Not an investment seat.",
}


QUANT = re.compile(r"quant|quantitativ", re.I)
BARE = re.compile(r"^\s*(senior\s+)?(analyst|associate|analyste|associé)(\s*/\s*(senior\s+)?(analyst|associate))?\s*$", re.I)
STRONG_MEDIUM = {"valuation", "markets operations", "performance measurement", "investment risk", "due diligence"}


def classify(title, cat=None):
    if QUANT.search(title):
        return "quant", "quant"
    if cat in ("pe_vc", "pension") and BARE.search(title):
        return "strong", "investments"
    for pat, name in STRONG:
        if re.search(pat, title, re.I):
            return "strong", name
    for pat, name in MEDIUM:
        if re.search(pat, title, re.I):
            return "medium", name
    return "none", None


LVL_EXEC = re.compile(r"director|directeur|directrice|vice[- ]president|VP|head of|managing|partner|"
                      r"chief|chef|senior director", re.I)
LVL_MGR = re.compile(r"manager|gestionnaire|lead|principal|senior advisor|conseill(er|ère)\(?-?è?r?e?\)? "
                     r"(principal|senior|sénior)|premier\(?-?è?r?e?\)? conseill|expert", re.I)
OPS = re.compile(r"operations|opérations|administration|settlement|règlement|control|contrôle|"
                 r"servicing|integration|intégration", re.I)
LVL_ADV = re.compile(r"advisor|conseill|specialist|spécialiste", re.I)


def level_of(t):
    if STUDENT.search(t):
        return "student", -4
    up = LEVEL_UP.search(t)
    if LEVEL_SENIOR_ANALYST.search(t) and not re.search(r"analyst\s*/|/\s*senior", t, re.I):
        return "senior analyst", 0
    if up:
        return "fit", 1
    if LVL_EXEC.search(t):
        return "exec", -5
    if LVL_MGR.search(t):
        return "senior", -3
    if LVL_ADV.search(t):
        return "advisor", -1
    return "unclear", -1


def score(job):
    t = job["t"]
    cat = job["cat"]
    kind, sig = classify(t, cat)
    if cat == "ib" and re.search(r"investment associate", t, re.I):
        return None  # wealth-desk assistant seat at a bank
    # banks are huge: only keep their front-office seats
    if cat in ("ib", "insurer", "markets") and kind not in ("strong", "quant"):
        if not (cat == "ib" and sig in STRONG_MEDIUM):
            return None
    s = CAT_BASE[cat]
    if kind == "strong":
        s += 3
    elif kind == "quant":
        s += 0
    elif kind == "medium":
        s += 1 if sig in STRONG_MEDIUM else 0
    else:
        s -= 2
    level, adj = level_of(t)
    s += adj
    if kind == "quant" and re.search(r"research", t, re.I):
        s = min(s, 5)
    if kind == "strong" and OPS.search(t):
        s -= 2; sig = "markets operations"  # investment word, but an operations seat
    if TEMP.search(t):
        s -= 1
    if not job["mtl_explicit"]:
        s -= 1
    s = max(0, min(10, s))
    if s < 4:
        return None
    job["s"] = s
    job["sig"] = sig or ""
    job["why"] = why(job, kind, sig, level)
    return job


def why(job, kind, sig, level):
    lvl = {"fit": "At your level", "senior analyst": "Senior-analyst level, in reach at two years in",
           "advisor": "Advisor title, usually a step above analyst",
           "senior": "Titled above you, so it's a stretch", "exec": "Well above your level",
           "student": "Student / intern seat, below where you are",
           "unclear": "Level isn't clear from the title"}[level]
    what = f"{sig} at {CAT_WORDS[job['cat']]}" if sig else f"a non-investment seat at {CAT_WORDS[job['cat']]}"
    extra = " It's a fixed-term contract." if TEMP.search(job["t"]) else ""
    if not job["mtl_explicit"]:
        extra += " Posted across several cities, so check Montreal is one of them."
    return f"{lvl}: {what}.{extra} {ANGLE.get(sig, ANGLE[None])}"


# ---------------------------------------------------------------- fetchers
def get(url, headers=None):
    r = requests.get(url, headers=headers or UA, timeout=40)
    r.raise_for_status()
    return r


def days_from_workday(txt):
    t = (txt or "").lower()
    if "today" in t or "aujourd" in t:
        return 0
    if "yesterday" in t or "hier" in t:
        return 1
    m = re.search(r"(\d+)\+?", t)
    return int(m.group(1)) if m else None


def fetch_workday(src):
    name, tenant, n, site, cat, hq = src
    base = f"https://{tenant}.wd{n}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    hdr = {**UA, "Content-Type": "application/json"}
    first = requests.post(api, json={"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}},
                          headers=hdr, timeout=40)
    first.raise_for_status()
    data = first.json()
    total = data.get("total", 0)
    posts = list(data.get("jobPostings", []))

    def page(off):
        r = requests.post(api, json={"limit": 20, "offset": off, "searchText": "", "appliedFacets": {}},
                          headers=hdr, timeout=40)
        r.raise_for_status()
        return r.json().get("jobPostings", [])

    with cf.ThreadPoolExecutor(6) as ex:
        for chunk in ex.map(page, range(20, total, 20)):
            posts.extend(chunk)
    out = []
    for p in posts:
        loc = p.get("locationsText", "") or ""
        out.append(dict(c=name, cat=cat, t=p.get("title", ""), l=loc,
                        u=f"{base}/{site}{p.get('externalPath', '')}",
                        age=days_from_workday(p.get("postedOn")), hq=hq))
    return out, total


def iso_age(s):
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return (TODAY - d).days
    except Exception:
        return None


def fetch_greenhouse(src):
    name, tok, cat = src
    jobs = get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs").json().get("jobs", [])
    return [dict(c=name, cat=cat, t=j["title"], l=(j.get("location") or {}).get("name", ""),
                 u=j["absolute_url"], age=iso_age(j.get("first_published") or j.get("updated_at", "")), hq=False)
            for j in jobs], len(jobs)


def fetch_ashby(src):
    name, tok, cat = src
    jobs = get(f"https://api.ashbyhq.com/posting-api/job-board/{tok}").json().get("jobs", [])
    return [dict(c=name, cat=cat, t=j["title"], l=j.get("location", ""), u=j["jobUrl"],
                 age=iso_age(j.get("publishedAt", "")), hq=False) for j in jobs], len(jobs)


def fetch_rippling(src):
    name, tok, cat, hq = src
    items = get(f"https://ats.rippling.com/api/v2/board/{tok}/jobs").json().get("items", [])
    out = []
    for j in items:
        locs = j.get("locations") or j.get("workLocations") or []
        loc = ", ".join((x.get("name") if isinstance(x, dict) else str(x)) for x in locs) or "Montreal area"
        out.append(dict(c=name, cat=cat, t=j.get("name", ""), l=loc, u=j.get("url", ""), age=None, hq=hq))
    return out, len(items)


def fetch_bamboo(src):
    name, tok, cat, hq = src
    res = get(f"https://{tok}.bamboohr.com/careers/list").json().get("result", [])
    out = []
    for j in res:
        loc = j.get("location") or {}
        city = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x)
        out.append(dict(c=name, cat=cat, t=j.get("jobOpeningName", ""), l=city,
                        u=f"https://{tok}.bamboohr.com/careers/{j.get('id')}", age=None, hq=hq))
    return out, len(res)


NBC_ROW = re.compile(
    r'data-map="job-detail-link"\s+href="([^"]+)"\s+title="([^"]*)".*?</th>\s*<td>\s*(.*?)\s*</td>', re.S)


def fetch_nbc(_src=None):
    out, off, seen = [], 0, set()
    while off < 1000:
        t = get(f"https://emplois.bnc.ca/en_CA/careers/SearchJobs/?jobOffset={off}",
                headers={**UA, "Accept": "text/html"}).text
        rows = NBC_ROW.findall(t)
        new = [r for r in rows if r[0] not in seen]
        if not new:
            break
        for u, title, loc in new:
            seen.add(u)
            out.append(dict(c="National Bank", cat="ib", t=html.unescape(title).strip(),
                            l=html.unescape(re.sub(r"\s+", " ", loc)).strip(), u=u, age=None, hq=True))
        off += 20
    return out, len(out)


SOURCES = ([(fetch_workday, s, s[0]) for s in WORKDAY] +
           [(fetch_greenhouse, s, s[0]) for s in GREENHOUSE] +
           [(fetch_ashby, s, s[0]) for s in ASHBY] +
           [(fetch_rippling, s, s[0]) for s in RIPPLING] +
           [(fetch_bamboo, s, s[0]) for s in BAMBOO] +
           [(fetch_nbc, None, "National Bank")])


# ---------------------------------------------------------------- pipeline
def keep_location(j):
    loc = j["l"] or ""
    if MTL.search(loc):
        j["mtl_explicit"] = True
        return True
    if j["hq"] and (MULTI.search(loc) or not loc.strip() or re.search(r"canada|qu[eé]bec", loc, re.I)):
        j["mtl_explicit"] = False
        return True
    return False


def with_retry(fn, src, tries=3):
    import time
    for i in range(tries):
        try:
            return fn(src)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))


def main():
    raw, errors, scanned = [], [], 0
    with cf.ThreadPoolExecutor(10) as ex:
        futs = {ex.submit(with_retry, fn, src): label for fn, src, label in SOURCES}
        for f in cf.as_completed(futs):
            label = futs[f]
            try:
                jobs, n = f.result()
                raw.extend(jobs)
                scanned += n
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}")
                print(f"  ! {label} failed: {e}", file=sys.stderr)

    kept, dedupe = [], set()
    for j in raw:
        if not j["t"] or EXCLUDE.search(j["t"]):
            continue
        if not keep_location(j):
            continue
        key = (j["c"], j["t"].lower(), j["u"])
        if key in dedupe:
            continue
        dedupe.add(key)
        if score(j):
            kept.append(j)

    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    try:
        seen = json.load(open(SEEN_PATH, encoding="utf-8"))
    except Exception:
        seen = {}
    # "new" = first spotted today, on a day when older postings were already on file
    baseline = min((dt.date.fromisoformat(d) for d in seen.values()), default=TODAY)
    first_run = not seen
    for j in kept:
        seen.setdefault(j["u"], TODAY.isoformat())
        fs = dt.date.fromisoformat(seen[j["u"]])
        j["new"] = fs == TODAY and baseline < TODAY
        if j["age"] is None:
            j["age"] = (TODAY - fs).days if not first_run else None
    # forget postings gone for 60+ days so the file stays small
    live = {j["u"] for j in kept}
    seen = {u: d for u, d in seen.items()
            if u in live or (TODAY - dt.date.fromisoformat(d)).days < 60}
    json.dump(seen, open(SEEN_PATH, "w", encoding="utf-8"), indent=0, sort_keys=True)

    kept.sort(key=lambda j: (-j["s"], j["age"] if j["age"] is not None else 999))
    jobs = [dict(s=j["s"], c=j["c"], cat=j["cat"], t=j["t"], l=j["l"], u=j["u"],
                 a=j["age"], n=j["new"], m=j["mtl_explicit"], w=j["why"]) for j in kept]
    meta = dict(run=TODAY.strftime("%a %d %b %Y"), boards=len(SOURCES) - len(errors),
                scanned=scanned, errors=errors)

    page = open(TEMPLATE, encoding="utf-8").read()
    payload = json.dumps({"meta": meta, "jobs": jobs}, ensure_ascii=True).replace("</", "<\\/")
    page = page.replace("/*__DATA__*/null", payload)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)

    print(f"{scanned} postings read from {meta['boards']} boards -> {len(jobs)} kept, "
          f"{sum(j['n'] for j in jobs)} new, {sum(j['s'] >= 8 for j in jobs)} scored 8+")
    if errors:
        print("Board failures:", ", ".join(errors))


if __name__ == "__main__":
    main()
