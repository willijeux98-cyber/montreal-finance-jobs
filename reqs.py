"""
Read what a posting actually asks for.

The title says "Associate"; the description says "5+ years in private equity". The score has to listen to the
description. This module fetches the posting text for each candidate role (through the hiring system's own API
where there is one), pulls out the experience bar and the hard requirements, and caches the result per URL so
each posting is read once.
"""
import html
import json
import re
import time
from urllib.parse import urlparse

import requests

VERSION = 3   # bump when parse() changes: cached readings are redone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8"}


def _text(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer)\b.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h\d|tr|ul|ol)>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h).replace("\xa0", " ")
    h = re.sub(r"[ \t\r\f\v]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n", h).strip()


def _ld_description(page):
    """Most career sites embed a schema.org JobPosting: the cleanest copy of the description."""
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page):
        try:
            d = json.loads(m.group(1).strip())
        except Exception:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
            if isinstance(x, dict) and x.get("@type") == "JobPosting" and x.get("description"):
                return _text(html.unescape(x["description"]))
    return ""


def _get(url, **kw):
    r = requests.get(url, headers=kw.pop("headers", UA), timeout=30, **kw)
    r.raise_for_status()
    return r


def description(url, api=None):
    """Plain text of the posting, or "" if it can't be read."""
    if api and "greenhouse.io" in api:
        return _text(html.unescape(_get(api).json().get("content", "")))
    p = urlparse(url)
    host, path = p.netloc.lower(), p.path
    if host.endswith("myworkdayjobs.com"):
        tenant = host.split(".")[0]
        parts = [x for x in path.split("/") if x]
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts = parts[1:]
        site, rest = parts[0], "/".join(parts[1:])
        d = requests.get(f"https://{host}/wday/cxs/{tenant}/{site}/{rest}",
                         headers={**UA, "Accept": "application/json"}, timeout=30).json()
        return _text((d.get("jobPostingInfo") or {}).get("jobDescription", ""))
    m = re.match(r"/([^/]+)/jobs/(\d+)", path)
    if "greenhouse.io" in host and m:
        d = _get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}").json()
        return _text(html.unescape(d.get("content", "")))
    m = re.match(r"/([^/]+)/([0-9a-f-]{36})", path)
    if host == "jobs.lever.co" and m:
        d = _get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}").json()
        lists = "\n".join(l.get("text", "") + "\n" + _text(l.get("content", "")) for l in d.get("lists") or [])
        return (d.get("descriptionPlain") or "") + "\n" + lists + "\n" + (d.get("additionalPlain") or "")
    m = re.match(r"/([^/]+)/(\w+)", path)
    if host == "jobs.smartrecruiters.com" and m:
        d = _get(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}").json()
        sec = (d.get("jobAd") or {}).get("sections") or {}
        return "\n".join(_text((sec.get(k) or {}).get("text", "")) for k in ("jobDescription", "qualifications", "additionalInformation"))
    m = re.search(r"/jobs/view/(?:[^/]*?-)?(\d{6,})", path)
    if "linkedin.com" in host and m:
        for wait in (0, 15, 40):
            time.sleep(wait)
            r = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}", headers=UA, timeout=30)
            if r.status_code == 429:
                continue
            r.raise_for_status()
            b = re.search(r'(?is)<div[^>]+class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', r.text)
            return _text(b.group(1) if b else r.text)
        raise RuntimeError("LinkedIn 429")
    if host == "jobs.ashbyhq.com":
        page = _get(url).text
        m = re.search(r'"descriptionHtml"\s*:\s*("(?:[^"\\]|\\.)*")', page)
        if m:
            return _text(json.loads(m.group(1)))
        return _ld_description(page) or _text(page)
    page = _get(url).text
    ld = _ld_description(page)
    if len(ld) > 400:
        return ld
    m = re.search(r'(?s)<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page)
    if m:   # Rippling and other Next.js boards ship the posting as JSON
        try:
            blob = json.loads(m.group(1))
            found = []

            def walk(x):
                if isinstance(x, dict):
                    for k, v in x.items():
                        if isinstance(v, str) and len(v) > 200 and "<" in v and k.lower() in ("description", "descriptionhtml", "content", "body", "html", "role", "company"):
                            found.append(_text(v))
                        else:
                            walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)
            walk(blob)
            if found:
                return "\n".join(found)
        except Exception:
            pass
    return ld or _text(page)


# ---------------------------------------------------------------- parsing
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10}
NUM = r"(\d{1,2}(?:[.,]5)?|[.,]5|" + "|".join(WORDNUM) + r")"
# "3+ years", "3 to 5 years", "3-5 years'", "minimum of 3 years", "at least three years", "3 à 5 ans", "trois (3) années"
YEARS = re.compile(
    r"(?<![\w$.,])(up to\s+|jusqu'à\s+|maximum (?:of\s+|de\s+)?|less than\s+|fewer than\s+|no more than\s+|moins de\s+)?" + NUM + r"\s*(?:\(\s*\d{1,2}\s*\)\s*)?(\+|\s*plus)?\s*"
    r"(?:(?:-|–|—|to|à|a|or|ou)\s*" + NUM + r"\s*(?:\(\s*\d{1,2}\s*\)\s*)?\+?\s*)?"
    r"(?:full[- ]time\s+|or more\s+|ou plus\s+|\+\s*)?"
    r"(years?|yrs?|ans|années|année|an)\b",
    re.I)
EXPER = re.compile(r"experience|expérience|exp\.|work(ing)? in|track record|background|worked|in (a|an) |within|"
                   r"post[- ]?(graduate|grad|mba|undergrad)|of (relevant|related|progressive|direct|professional|investment|transaction|deal)", re.I)
NOT_REQ = re.compile(r"(company|firm|organization|organisation|history|founded|track record of|portfolio of|over the (past|last)|"
                     r"since|anniversary|more than \d+ years (of|in) (business|operation)|term|maturity|horizon|lease|fund life|"
                     r"warranty|vesting|old|âgé|age\b|plan\b|strategic plan|contract of|mandat de|duration|durée|"
                     r"retire|retraite|pension plan|tenure of our|historique|depuis)", re.I)

# What kind of experience the years have to be in, from narrowest (his count is lowest) to broadest
DOMAINS = [
    ("ops", re.compile(r"(investment|fund|portfolio|asset management|wealth|pension|retirement|retraite) operations|"
                       r"opérations (de placement|financières|de fonds)|middle[- ]office|back[- ]office|fund (administration|accounting)|"
                       r"custody|performance measurement|mesure de (la )?performance|reconciliation|business analy|analyse d'affaires", re.I)),
    ("investing", re.compile(r"invest|private equity|capital[- ]investissement|placement privé|\bPE\b|venture|buy[- ]side|"
                             r"sell[- ]side|asset management|gestion (d'actifs|de portefeuille)|portfolio management|"
                             r"equity research|recherche|securities|valeurs mobilières|courtage|brokerage|credit|crédit|underwriting|financement|financing|real estate finance|"
                             r"debt|dette|leveraged|lending|\bfund|fonds|"
                             r"capital markets|marchés des capitaux|trading|banking|banque d'investissement|bancaire|"
                             r"private markets|marchés privés|infrastructure|real estate (finance|investment|acquisitions)|"
                             r"secondar|primaries|co-?invest|LBO|asset class", re.I)),
    ("deals", re.compile(r"\bM&A\b|mergers|fusions|acquisition|transaction|corporate development|développement corporatif|"
                         r"corporate finance|financement (corporatif|d'entreprise)|due diligence|vérification diligente|"
                         r"valuation|évaluation|deal|consult|strategy|stratégie|advisory|services-conseils", re.I)),
]

INVEST_REQ = re.compile(
    r"(experience|expérience|background)[^.\n;]{0,80}?(in|within|en|dans|with|au sein)[^.\n;]{0,40}?"
    r"(private equity|capital[- ]investissement|investment banking|banque d'investissement|buy[- ]side|"
    r"(an? )?(investment|investing|placement) (firm|role|team|function|experience|environment)|"
    r"principal investing|private markets|asset management|gestion d'actifs|leveraged finance|"
    r"(infrastructure|real estate|credit|venture|growth) (investing|investment)|direct investment|"
    r"transaction(s|al)? (advisory|services)|M&A advisory)", re.I)
CFA_CHARTER = re.compile(r"(CFA (charter|designation|charterholder)|charterholder|titre de CFA|détenteur du titre CFA|"
                         r"CFA holder)(?![^.\n]{0,60}(progress|cours|asset|atout|plus|preferred|candidate|candidat|pursuing|obtention|en voie|or working|or enrol))", re.I)
CFA_ANY = re.compile(r"\bCFA\b", re.I)
CFA_PROGRESS = re.compile(r"CFA[^.\n]{0,80}(progress|cours|candidate|candidat|pursuing|en voie|level|niveau|asset|atout|"
                          r"plus|preferred|enrol|working towards|obtention)|"
                          r"(progress|candidate|pursuing|working towards|en voie|cheminement)[^.\n]{0,40}CFA", re.I)
MBA_REQ = re.compile(r"\bMBA\b(?![^.\n]{0,40}(asset|atout|plus|preferred|nice|bonus|an advantage|is a plus|considered))", re.I)
MBA_POST = re.compile(r"post[- ]?MBA|MBA (required|is required|degree required)|completed (an|your) MBA|MBA graduate", re.I)
CPA_REQ = re.compile(r"\b(CPA|chartered professional accountant|comptable professionnel agréé)\b[^.\n;]{0,50}"
                     r"(is required|required|requis|obligatoire|mandatory)|"
                     r"(must (be|hold|have)|required|requis|obligatoire)[^.\n;]{0,30}\b(CPA|comptable professionnel)", re.I)
SOFT = re.compile(r"asset|atout|plus\b|preferred|privilégié|progress|en voie|cours|pursuing|nice|bonus|considered|advantage", re.I)
OPS_SEAT = re.compile(r"middle[- ]office|back[- ]office|fund (administration|accounting)|custody|garde de valeurs|"
                      r"reconciliation|rapprochement|settlement|règlement des|trade support|NAV (production|calculation|oversight)|"
                      r"investment operations|opérations (de placement|d'investissement)|performance measurement|"
                      r"mesure de (la )?performance|data (governance|quality|management)|business analysis|systems analysis|"
                      r"analyse d.affaires|business requirements|besoins d.affaires|user stories|\bUAT\b|tests? d.acceptation|"
                      r"digital solutions|solutions numériques|system implementation|technology solutions", re.I)
# deal / investing vocabulary: what a front-office posting is full of
FRONT = re.compile(r"investment (opportunit|thesis|committee|memo|recommendation|decision)|comité d.investissement|"
                   r"thèse d.investissement|occasions? d.investissement|due diligence|vérification diligente|\bdeals?\b|"
                   r"transactions?\b|\bM&A\b|\bF&A\b|acquisitions?\b|portfolio compan|sociétés? (en|du) portefeuille|"
                   r"financial model|modèles? financiers?|modélisation financière|valuations?\b|évaluations? d.entreprise|"
                   r"underwrit|\bLBO\b|\bDCF\b|origination|term sheet|co-?invest|exits?\b|capital[- ]rais|levées? de (capitaux|fonds)|"
                   r"credit (analysis|memo|approval|risk assessment)|analyse de crédit|investment (case|proposal)|pitch book|"
                   r"financing (structure|solutions)|montages? financiers?|structuration|"
                   r"portfolio construction|asset allocation|répartition (de l.)?actifs?|security selection|"
                   r"investment (strateg|ideas)|stratégies? (de placement|d.investissement)|issuers?\b|émetteurs?\b|"
                   r"\btrad(e|es|ing)\b|négociation|\balpha\b|equity research|fixed income|revenus? fixes?|"
                   r"\bbonds?\b|obligations\b|credit spreads?|derivatives|dérivés|market (views?|analysis)|"
                   r"portfolio managers?|gestionnaires? de portefeuille|investment ideas", re.I)
# budget-and-close work: corporate FP&A, not deal work
FPA = re.compile(r"FP&A|budget|forecast|prévisions?\b|month[- ]end|fin de mois|clôture|variance|écarts|"
                 r"management reporting|reporting financier|financial reporting", re.I)
FRENCH = re.compile(r"bilingu|français|french|francais", re.I)
JUNIOR = re.compile(r"new grad|recent grad|nouveaux? diplômé|finissant|0\s*(-|–|to|à)\s*[12]\s*(years|ans)|"
                    r"entry[- ]level|débutant|early[- ]career|début de carrière|1\s*(-|–|to|à)\s*[23]\s*(years|ans)", re.I)


def _n(s):
    s = (s or "").lower().replace(",", ".")
    return WORDNUM.get(s) if s in WORDNUM else float(s) if s else None


def _sentences(text):
    for line in re.split(r"\n|(?<=[.;!?])\s+(?=[A-Z•\-–])", text):
        line = line.strip(" •-–\t*·")
        if 12 < len(line) < 600:
            yield line


def back_office(r):
    """The posting reads like operations, reporting or FP&A rather than investing or deal work."""
    if not r.get("ok"):
        return False
    ops, front = r.get("ops", 0), r.get("front", 0)
    if r.get("opsy") and ops >= 3:
        return True            # the experience it asks for is operations experience
    if ops >= 8 and ops >= front:
        return True
    support = ops + r.get("fpa", 0)
    if support >= 4 and front * 2 < support:
        return True
    return r.get("n", 0) > 1500 and front == 0   # a full posting without one word of deal or markets work


def parse(text, title=""):
    """-> dict: y (years asked for, lower bound), yh (upper), yd (domain: investing/deals/general), q (the line),
    inv (investment-type experience asked for), cfa ("charter"/"progress"/"mention"/""), mba, cpa, fr, jr, ok"""
    out = dict(ok=bool(text and len(text) > 200), y=None, yh=None, yd=[], q="", inv=False, cfa="", mba=False,
               cpa=False, fr=False, jr=False, ops=0, opsy=False, front=0, fpa=0)
    if not out["ok"]:
        return out
    if re.search(r"<(br|p|li|div)\b", text, re.I):   # some boards hand back escaped HTML
        text = _text(text)
    text = re.sub(r"\s+[•▪●◦]\s+|(?<![\d.,])\s+-\s+(?=[A-ZÉÀ])", "\n", text)
    cands = []
    for s in _sentences(text):
        for m in YEARS.finditer(s):
            lo, hi = _n(m.group(2)), _n(m.group(4))
            if m.group(1):          # "up to two years" is a ceiling, not a floor
                lo, hi = 0, lo
            if lo is None or lo > 25 or (lo < 0.5 and not m.group(1) and hi is None):
                continue
            win = s[max(0, m.start() - 70): m.end() + 110]
            after = s[m.end(): m.end() + 140]
            if not EXPER.search(win):
                continue
            if NOT_REQ.search(s[max(0, m.start() - 40): m.end() + 25]) and not re.search(r"experience|expérience", after[:40], re.I):
                continue
            clause = re.split(r";|\.\s", after)[0]
            near = clause + " " + s[max(0, m.start() - 50): m.start()]
            doms = [name for name, rx in DOMAINS if rx.search(near)] or ["general"]
            pref = bool(re.search(r"prefer|ideal|idéal|asset|atout|nice to have|bonus|an advantage|un plus", s, re.I))
            cands.append((lo, hi if hi is not None and hi >= lo else None, doms, s, pref))
    if cands:
        # one bar per posting. Several bars for a two-level title ("Analyst: 1-3 years, Senior Analyst: 3-5"):
        # the lowest is the door. Otherwise the required, domain-specific bar wins over a "preferred" or a
        # skill-specific aside ("2 years of Python").
        req = [c for c in cands if not c[4]] or cands
        multi = bool(re.search(r"/|\bor\b|\bou\b", title)) and len({c[0] for c in req}) > 1
        main = [c for c in req if c[2] != ["general"]] or req
        pick = min(main, key=lambda c: c[0]) if multi else max(main, key=lambda c: c[0])
        out["y"], out["yh"], out["yd"] = pick[0], pick[1], pick[2]
        q = pick[3]
        out["q"] = (q[:217] + "…") if len(q) > 220 else q
    out["inv"] = bool(INVEST_REQ.search(text))
    if CFA_ANY.search(text):
        m = CFA_CHARTER.search(text)
        hard = m and re.search(r"required|requis|must|obligatoire|mandatory", text[max(0, m.start() - 60): m.end() + 60], re.I)
        out["cfa"] = "progress" if CFA_PROGRESS.search(text) else "charter" if hard else "mention"
    out["mba"] = bool(MBA_POST.search(text))
    m = CPA_REQ.search(text)
    out["cpa"] = bool(m) and not SOFT.search(text[m.start(): m.end() + 40])
    out["fr"] = bool(FRENCH.search(text))
    out["jr"] = bool(JUNIOR.search(text))
    # count ops vocabulary: a real ops seat leans on it throughout, an investing seat mentions it in passing
    out["ops"] = len(OPS_SEAT.findall(text))
    out["front"] = len(FRONT.findall(text))
    out["n"] = len(text)
    out["fpa"] = len(FPA.findall(text))
    out["opsy"] = out["yd"][:1] == ["ops"]
    return out
