"""
Montreal high-finance job desk.

Pulls postings straight from each employer's hiring system, then sweeps public job
searches (LinkedIn, Job Bank) for Montreal investment roles at firms the boards don't
cover. Keeps the Montreal buy-side / investment banking / markets seats, ranks them
against the owner's profile, and writes docs/index.html.

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
try:
    from zoneinfo import ZoneInfo
    _NOW = dt.datetime.now(ZoneInfo("America/Toronto"))
except Exception:   # no tz database on this machine: the workflow sets TZ=America/Toronto anyway
    _NOW = dt.datetime.now()
TODAY = _NOW.date()

from sources import build_sources  # noqa: E402  (all job boards live in sources.py / data/boards.json)

# ---------------------------------------------------------------- filters
MTL = re.compile(r"montr[eé]al|laval|longueuil|brossard|boucherville|pointe[- ]claire|saint-laurent|st-laurent|dorval|"
                 r"mont-royal|westmount|verdun|lasalle|lachine|anjou|kirkland|terrebonne|boisbriand|blainville|repentigny", re.I)
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
    r"insurance advisor|conseiller en assurance|sales representative|représentant|investment specialist|"
    r"crime|investigat|conciliat|technical analyst|service desk|sourcing|help desk|"
    r"platform|applications? specialist|infrastructure specialist|analytics infrastructure|\bULL\b|colo\b|"
    r"architect|scientist|personal banker|banquier|investment advisor|conseiller en placement|"
    r"investorline|regional sales|sales manager|wealth|patrimoine|nesbitt|wood gundy|"
    r"investment and financing|placement et financement|credit card|cartes? de crédit|"
    r"representative|retirement specialist|investment and retirement|"
    r"solutions delivery|interface utilisateur|bases de données|database|solutions numériques|digital solutions",
    re.I)

# front-office investment / deal / markets work
STRONG = [
    (r"\bdeals?\b|transaction diligence|contrôle préalable|stratégie de transaction|services? transactionnels?|value creation|"
     r"création de valeur|financement d.entreprises|[ée]valuation d.entreprise", "deal advisory"),
    (r"corporate debt|private debt|dette privée|dette (corporative|subordonnée)|mezzanine|leveraged|credit opportunit|"
     r"structured credit|financement structuré|asset[- ]based lend", "private credit"),
    (r"\bF&A\b|corporate banking|services bancaires aux (grandes )?entreprises|project financ|financement de projets",
     "investment banking"),
    (r"recherche fondamentale|fundamental research", "research"),
    (r"secondar|primaries|primary fund|funds? of funds|fonds de fonds|fund investments?|co-?invest|private markets|"
     r"marchés privés|placements privés", "fund investing"),
    (r"corporate development|développement corporatif|corp\.? dev", "corporate development"),
    (r"transaction advisory|deal advisory|transaction services|financial due diligence|business valuation|"
     r"évaluation d.entreprise|valuations? (&|and) (modeling|modelling|advisory)|restructuring", "deal advisory"),
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
    (r"portfolio manag|gestion de portefeuille|gestionnaire de portefeuille|asset allocation|march[ée]s liquides|"
     r"liquid markets|portfolio analyst|analyste de portefeuille|"
     r"répartition de l.actif|total fund|public markets|marchés publics|multi-asset|multiactifs",
     "portfolio management"),
    (r"capital markets|marchés des capitaux|global markets|marchés mondiaux", "capital markets"),
    (r"acquisitions? (analyst|associate|manager)|analyste.{0,20}acquisitions?|financing analyst|"
     r"analyste.{0,20}financement|asset management analyst|analyste.{0,20}gestion d.actifs", "real estate investing"),
    (r"\binvest(?!igat)|placement|co-invest|\balpha\b|hedge fund|fund investment|\bfonds\b", "investments"),
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
# Hard excludes always apply. The rest of EXCLUDE is skipped when the title is plainly a deal / investment seat
# ("Corporate Development" contains "develop", "Fundamental Research Platform" contains "platform").
HARD = re.compile(r"legal|juridique|counsel|avocat|lawyer|notaire|paralegal|law clerk|assistant|adjoint|administrative|réception|"
                  r"recrut|recruit|talent|\bHR\b|\bRH\b|payroll|paie|developer|développeu|software|logiciel|engineer|ingénieur|"
                  r"comptab|accounting|accountant|\btax\b|fiscal|marketing|designer|scientist|architect|personal bank|banquier|"
                  r"services bancaires aux particuliers|m365|microsoft|sharepoint|syst[eè]mes? d.information|information systems|salesforce|servicenow|financial advisor|conseill[eè]re? financi|itrade|mcleod|attorney|technicien|technician|scientifique|investment and retirement|investment and financing|placement et financement|retirement specialist|investment specialist|investment advisor|conseill[eè]re? en placement|financial planner|planificat|mortgage|hypoth|succursale|\bbranch\b|teller|caissi|personal financ|finances personnelles|\bIT\b|"
                  r"forensic|juricomptab|cyber|documentation negotiat|parajuriste|\bjuriste|soci[ée]taire|"
                  r"portefeuille de projets|project portfolio|programs? portfolio|program/portfolio|project/program portfolio|"
                  r"portfolio of projects|gestionnaire immobili|property manag|gestion immobili|building manag", re.I)
OVERRIDE = re.compile(r"corporate development|développement corporatif|\bM&A\b|\bF&A\b|mergers|fusions|investment banking|"
                      r"private equity|placements? privés|capital[- ]investissement|venture|capital de risque|equity research|"
                      r"fundamental research|recherche fondamentale|transaction (services|diligence|advisory)|deal advisory|\bdeals?\b|"
                      r"valuations?\b|[ée]valuation d.entreprise|infrastructure invest|investissements? en infrastructure|"
                      r"real estate invest|investissements? immobili|private (credit|debt)|dette privée|ventes institutionnelles|"
                      r"institutional sales|"
                      r"\binvest(ment|ments|ing|issement|issements)\b", re.I)


# Big mixed institutions: only clearly investment / deal titles count (a "Senior Analyst, Operational Risk" doesn't)
STRICT = {"BDC", "EDC", "Intact", "Manulife", "Sun Life", "iA Financial Group", "Hydro-Quebec", "CN", "Bombardier"}


def clean_title(t):
    t = re.sub(r"\s*\((?:Montr[ée]al|Toronto|Ottawa)\)\s*Qu[ée]b\w*\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\s*$", "", t)
    t = re.sub(r"\s+Qu[ée]b\w*\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def excluded(t):
    if HARD.search(t):
        return True
    if OVERRIDE.search(t):
        return False
    return bool(EXCLUDE.search(t))


LEVEL_UP = re.compile(r"\b(analyst|analyste|associate|associé|junior|entry|early career)\b", re.I)
LEVEL_SENIOR_ANALYST = re.compile(r"senior analyst|analyste (principal|senior|sénior)|sr\.? analyst", re.I)
LEVEL_DOWN = re.compile(
    r"\b(manager|gestionnaire|director|directeur|directrice|vice[- ]president|\bVP\b|"
    r"head of|chef|principal\b(?!e?\s*\)?,)|partner|lead\b|managing|senior advisor|"
    r"conseill(er|ère) (principal|senior|sénior)|premier\(?-?è?r?e?\)? conseill|expert)\b",
    re.I)
STUDENT = re.compile(r"intern|stage|stagiaire|co-?op|student|étudiant|summer|été 20", re.I)
TEMP = re.compile(r"temporary|temporaire|contract|contrat|\d+\s*(months|mois)", re.I)

CAT_BASE = {"pension": 6, "pe_vc": 6, "hedge": 6, "am": 5, "ib": 5, "markets": 5, "insurer": 4,
            "advisory": 5, "corpdev": 5, "re": 5, "open": 4}
CAT_WORDS = {
    "pension": "a Montreal pension investor",
    "pe_vc": "a private-markets investor",
    "hedge": "a trading / hedge fund shop",
    "am": "an asset manager",
    "ib": "a bank's markets and advisory side",
    "markets": "the exchange operator",
    "insurer": "an insurer's investment arm",
    "advisory": "a deal-advisory / valuation team",
    "corpdev": "a Montreal company's M&A team",
    "re": "a real estate investor or developer",
    "open": "a firm outside the usual list",
}
ANGLE = {
    "fund investing": "Lead with CFA Level I, fund mechanics (GP/LP, NAV, DPI/TVPI, the J-curve) and the large-merger diligence.",
    "corporate development": "Buy-side M&A from inside a company: lead with the large merger and your integration modelling.",
    "deal advisory": "Transaction services and valuation are the classic bridge into PE. Lead with the merger diligence.",
    "private equity": "Lead with the large-merger diligence and your break-even and cost-volume models.",
    "venture / growth": "Lead with the large-merger diligence and the fact you've built and shipped products in your current role.",
    "investment banking": "Lead with the large-merger diligence. That's M&A work, and bankers will recognize it.",
    "private credit": "Lead with the modelling and your insurance background. Credit is about pricing downside.",
    "infrastructure investing": "Lead with the merger diligence and the cost modelling. Infra underwriting rewards operational detail.",
    "real estate investing": "Lead with break-even and scenario modelling. Real estate underwriting is exactly that.",
    "natural resources investing": "Lead with the modelling and diligence. The sector is learnable, the seat is the point.",
    "research": "Come in with a stock or a sector you can actually talk about. Research seats test that.",
    "trading": "Lead with derivatives, CFA Level I and your Python and SQL.",
    "markets": "Lead with derivatives and capital markets coursework plus CFA Level I.",
    "portfolio management": "Lead with CFA Level I, investment management and your data skills.",
    "capital markets": "Lead with capital markets, CFA Level I, and that you're fully bilingual.",
    "investments": "Lead with CFA Level I and the large-merger diligence.",
    "quant": "Only if you're ready for a stats and coding test. Your Python is real, the bar is high.",
    "valuation": "Lead with your break-even and scenario modelling and CFA Level I.",
    "markets operations": "A real way onto the markets side. Lead with your process work and CFA Level I.",
    "performance measurement": "Measuring how portfolios actually did. Lead with your data work and CFA Level I.",
    "investment risk": "Lead with the modelling and your insurance background.",
    "due diligence": "This is literally what you did in the merger diligence. Say so.",
    "strategy": "Strategy work at a finance shop: the same muscles as your current role. Use it as the way in.",
    "analytics": "Your current skill set at a finance shop. A foot in the door, not an investment seat.",
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


LVL_EXEC = re.compile(r"director|directeur|directrice|vice[- ]pr[ée]sident|\bVP\b|head of|managing|partner|"
                      r"chief|\bchef\b|senior director", re.I)
LVL_MGR = re.compile(r"manager|gestionnaire|\blead\b|principal\b|senior advisor|conseill(er|ère)\(?-?è?r?e?\)? "
                     r"(principal|senior|sénior)|premier\(?-?è?r?e?\)? conseill|expert", re.I)
OPS = re.compile(r"operations|opérations|administration|settlement|règlement|control\b|contrôle|oversight|"
                 r"autoris|adjudicat|"
                 r"servicing|integration|intégration", re.I)
LVL_ADV = re.compile(r"advisor|conseill|specialist|spécialiste", re.I)


def level_of(t):
    if STUDENT.search(t):
        return "student", -4
    if re.search(r"associate director|directeur associ|directrice associ", t, re.I):
        return "senior", -3
    up = LEVEL_UP.search(t)
    if up and (LVL_EXEC.search(t) or (LVL_MGR.search(t) and not LEVEL_SENIOR_ANALYST.search(t)) or re.search(r"senior associate|associ[ée]\(?e?\)? principal", t, re.I)):
        return "mixed", -1
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
    if cat == "ib" and re.search(r"investment associate|associ\w* en (investissement|placements)", t, re.I):
        return None  # wealth-desk assistant seat at a bank
    # banks are huge: only keep their front-office seats
    if (cat in ("ib", "insurer", "markets", "advisory", "corpdev", "re", "open") or job["c"] in STRICT) and kind not in ("strong", "quant"):
        if not (cat in ("ib", "advisory") and sig in ("valuation", "markets operations", "due diligence")):
            return None
    if cat == "corpdev" and sig not in ("corporate development", "investment banking", "deal advisory", "fund investing"):
        return None  # at an operating company only the M&A / corp-dev seats count
    if cat == "advisory" and sig not in ("deal advisory", "investment banking", "valuation", "due diligence"):
        return None
    if kind == "none" and job["c"] not in CORE:
        return None  # a non-investment seat is only worth showing at a core buy-side firm
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
    a = job.get("age")
    job["fresh"] = ""
    if a is not None:
        if a <= 7:
            s += 1
        elif a > 180:
            s -= 2; job["fresh"] = "evergreen"   # posted for months or years: a resume pipeline, not a live seat
        elif a > 45 and a != 31:                 # Workday only ever says "30+" (stored as 31): don't penalise that
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
           "mixed": "Posted at two levels, and you'd be the junior one",
           "senior": "Titled above you, so it's a stretch", "exec": "Well above your level",
           "student": "Student / intern seat, below where you are",
           "unclear": "Level isn't clear from the title"}[level]
    what = f"{sig} at {CAT_WORDS[job['cat']]}" if sig else f"a non-investment seat at {CAT_WORDS[job['cat']]}"
    extra = " It's a fixed-term contract." if TEMP.search(job["t"]) else ""
    if not job["mtl_explicit"]:
        extra += " Posted across several cities, so check Montreal is one of them."
    if job.get("fresh") == "evergreen":
        extra += " It has been posted for months: likely an always-open pipeline rather than a live seat."
    return f"{lvl}: {what}.{extra} {ANGLE.get(sig, ANGLE[None])}"


SOURCES = [(lambda _s, f=f: f(), None, label) for f, label in build_sources()]
# Firms where even a non-investment seat is a real foot in the door
CORE = {"CDPQ", "PSP Investments", "Ardian", "Novacap", "Sagard", "Power Corporation", "Fiera Capital",
        "Investissement Quebec", "Fonds de solidarite FTQ", "Fondaction", "Desjardins Capital", "Ivanhoe Cambridge",
        "Inovia Capital", "Walter Capital Partners", "Claridge", "Squarepoint", "DRW", "Teralys Capital",
        "Letko Brosseau", "Jarislowsky Fraser", "Van Berkom", "Addenda Capital", "Montrusco Bolton"}


# ---------------------------------------------------------------- the net: who is this firm?
def fold(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower()


CO_STOP = re.compile(r"\b(inc|corp|corporation|ltd|ltee|limited|limitee|llc|lp|l\.p|senc|s\.e\.n\.c|group|groupe|the|le|la|les|de|du|des|"
                     r"of|canada|canadian|co|company|compagnie)\b")


def norm_co(s):
    s = fold(s).split("|")[0]
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    return re.sub(r"\s+", " ", CO_STOP.sub(" ", s)).strip()


ALIASES = {
    "investissements psp": "PSP Investments", "psp investments": "PSP Investments", "caisse": "CDPQ",
    "caisse depot et placement quebec": "CDPQ", "cdpq": "CDPQ", "national bank": "National Bank", "banque nationale": "National Bank",
    "bmo financial": "BMO", "bmo": "BMO", "royal bank": "RBC", "rbc": "RBC", "td": "TD", "td bank": "TD", "scotiabank": "Scotiabank",
    "cibc": "CIBC", "intact financial": "Intact", "intact": "Intact", "desjardins": "Desjardins", "mouvement desjardins": "Desjardins",
    "hydro quebec": "Hydro-Quebec", "sun life": "Sun Life", "manulife": "Manulife", "ia financial": "iA Financial Group",
    "ia groupe financier": "iA Financial Group", "industrielle alliance": "iA Financial Group", "beneva": "Beneva",
    "business development bank": "BDC", "banque developpement": "BDC", "bdc": "BDC", "export development": "EDC", "edc": "EDC",
    "power corporation": "Power Corporation", "laurentian bank": "Laurentian Bank", "banque laurentienne": "Laurentian Bank",
    "infrastructure bank": "Canada Infrastructure Bank", "banque infrastructure": "Canada Infrastructure Bank",
    "fonds solidarite ftq": "Fonds de solidarite FTQ", "ivanhoe cambridge": "Ivanhoe Cambridge", "ivanhoe": "Ivanhoe Cambridge",
    "investissement quebec": "Investissement Quebec", "jarislowsky fraser": "Jarislowsky Fraser", "fiera": "Fiera Capital",
    "couche tard": "Couche-Tard", "alimentation couche tard": "Couche-Tard", "cn": "CN", "canadian national railway": "CN",
    "bmo financier": "BMO", "bmo groupe financier": "BMO", "rbc banque royale": "RBC", "banque royale": "RBC",
    "banque scotia": "Scotiabank", "groupe financier banque td": "TD", "kpmg": "KPMG", "deloitte": "Deloitte", "ey": "EY", "ernst & young": "EY", "pwc": "PwC", "pricewaterhousecoopers": "PwC",
}


def firm_index(names):
    idx = {norm_co(n): n for n in names if norm_co(n)}
    idx.update(ALIASES)
    return idx


def match_firm(company, idx):
    k = norm_co(company)
    if not k:
        return None
    if k in idx:
        return idx[k]
    words = k.split()
    for n in range(len(words), 0, -1):   # "fiera capital private debt" -> "fiera capital" -> "fiera"
        head = " ".join(words[:n])
        if head in idx and (n > 1 or len(head) >= 4 or head in ALIASES):
            return idx[head]
    return None


# Law firms, staffing agencies and job sites post "investment" titles that aren't investment seats
NOT_A_FIRM = re.compile(r"\bllp\b|s\.?e\.?n\.?c\.?r\.?l|avocats|lawyers|\blaw\b|osler|stikeman|mccarthy|fasken|borden ladner|"
                        r"norton rose|davies ward|lavery|langlois|blakes|torys|dentons|gowling|miller thomson|mcmillan|"
                        r"\bacca careers\b|jobillico|talent\.com|indeed|workopolis|eluta|\brecrutement\b|staffing|placement de personnel", re.I)


def guess_cat(company):
    c = fold(company)
    if re.search(r"deloitte|kpmg|pwc|\bey\b|ernst|grant thornton|raymond chabot|\bmnp\b|\bbdo\b|richter|accuracy|valuation|evaluation|"
                 r"transaction advis|alvarez|fti consulting", c):
        return "advisory"
    if re.search(r"\bbank\b|banque|securities|valeurs mobili|capital markets|merchant bank", c):
        return "ib"
    if re.search(r"asset management|gestion d.actifs|gestion de placements|investment management|gestion de portefeuille|"
                 r"wealth|patrimoine|investment counsel|conseillers en placement", c):
        return "am"
    if re.search(r"immobili|real estate|realty|properties|proprietes|developpement|developments|construction|\breit\b|\bfpi\b|"
                 r"habitations|residences", c):
        return "re"
    if re.search(r"capital|partners|partenaires|ventures|equity|private|invest|fonds|\bfund|holding|family office|"
                 r"pension|retraite|endowment|fondation", c):
        return "pe_vc"
    return "open"


# ---------------------------------------------------------------- pipeline
OTHER = re.compile(r"toronto|vancouver|calgary|edmonton|ottawa|winnipeg|halifax|waterloo|mississauga|new york|"
                   r"boston|chicago|houston|london|paris|madrid|singapore|hong kong|qu[eé]bec city|ville de qu[eé]bec|"
                   r"\bl[eé]vis\b|sherbrooke|gatineau", re.I)


def keep_location(j):
    loc = "" if (j["l"] or "").startswith("Location not stated") else (j["l"] or "")
    if MTL.search(loc) or MTL.search(j["t"]):
        j["mtl_explicit"] = True
        return True
    if OTHER.search(loc) or OTHER.search(j["t"]):
        return False
    if (j["hq"] or j.get("hint")) and (MULTI.search(loc) or not loc.strip() or re.search(r"canada|qu[eé]bec", loc, re.I)):
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
    raw, errors, scanned, empty, got, netraw, netread = [], [], 0, [], {}, [], 0
    with cf.ThreadPoolExecutor(10) as ex:
        futs = {ex.submit(with_retry, fn, src): label for fn, src, label in SOURCES}
        for f in cf.as_completed(futs):
            label = futs[f]
            try:
                jobs, n = f.result()
                for j in jobs:
                    j["src"] = label
                if label.endswith(" sweep"):
                    netraw.extend(jobs)
                    netread += n
                    continue
                raw.extend(jobs)
                scanned += n
                got[label] = got.get(label, 0) + n
                if n == 0:
                    empty.append(label)
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}")
                print(f"  ! {label} failed: {e}", file=sys.stderr)

    # Jarislowsky Fraser posts through Scotiabank's board: give those seats their real name
    for j in raw:
        if j["c"] == "Scotiabank" and re.search(r"jarislowsky|\bSJF\b", j["t"] or "", re.I):
            j["c"], j["cat"], j["hq"] = "Jarislowsky Fraser", "am", True

    # The net: keep a row only if its firm's own board didn't already give us postings
    from sources import MTL_HQ
    try:
        boards = json.load(open(os.path.join(ROOT, "data", "boards.json"), encoding="utf-8"))
    except Exception:
        boards = []
    cats = {b["name"]: b["cat"] for b in boards}
    for _, _, label in SOURCES:
        cats.setdefault(label, None)
    for j in raw:
        cats[j["c"]] = j["cat"]
    idx = firm_index(list(cats) + list(MTL_HQ))
    netkept, netdrop = 0, 0
    for j in netraw:
        if NOT_A_FIRM.search(j["c"] or ""):
            netdrop += 1
            continue
        firm = match_firm(j["c"], idx)
        if firm and got.get(firm, 0) > 0:
            netdrop += 1
            continue   # that firm's own board is read directly
        if firm:
            j["c"], j["cat"], j["hq"] = firm, cats.get(firm) or guess_cat(firm), firm in MTL_HQ
        else:
            j["cat"] = guess_cat(j["c"])
        netkept += 1
        raw.append(j)

    kept, dedupe = [], {}
    for j in raw:
        j["t"] = clean_title(j["t"] or "")
        j["l"] = re.sub(r"\s+", " ", j["l"] or "").strip()
        if not j["t"] or excluded(j["t"]):
            continue
        if not keep_location(j):
            continue
        if not re.match(r"https?://", j["u"] or "", re.I):
            continue
        key = j["u"].split("?")[0].rstrip("/")
        if j.get("net"):   # the same seat often shows up on both sweeps (and twice on LinkedIn)
            key = "net:" + norm_co(j["c"]) + ":" + re.sub(r"[^a-z0-9]+", " ", fold(j["t"])).strip()
        wd = re.search(r"//([^/]+\.myworkdayjobs\.com)/.*_([A-Za-z]{0,4}-?\d[\w-]*)$", key)
        if wd:
            key = wd.group(1) + ":" + wd.group(2)  # same requisition in English and French = one job
        if score(j):
            prev = dedupe.get(key)
            if prev is None or j["s"] > prev["s"]:
                dedupe[key] = j
    kept = list(dedupe.values())

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
        j["new"] = fs == TODAY and baseline < TODAY and (j["age"] is None or j["age"] <= 2)
        if j["age"] is None:
            j["age"] = (TODAY - fs).days if not first_run else None
    # forget postings gone for 60+ days so the file stays small
    live = {j["u"] for j in kept}
    seen = {u: d for u, d in seen.items()
            if u in live or (TODAY - dt.date.fromisoformat(d)).days < 60}
    json.dump(seen, open(SEEN_PATH, "w", encoding="utf-8"), indent=0, sort_keys=True)

    kept.sort(key=lambda j: (-j["s"], j["age"] if j["age"] is not None else 999))
    jobs = [dict(s=j["s"], c=j["c"], cat=j["cat"], t=j["t"], l=j["l"], u=j["u"],
                 a=j["age"], n=j["new"], m=j["mtl_explicit"], w=j["why"], o=j.get("net") or "", g=j.get("sig") or "")
            for j in kept]
    if len(errors) > len(SOURCES) / 3:
        raise SystemExit(f"{len(errors)} of {len(SOURCES)} boards failed; keeping yesterday's page. {errors[:10]}")
    # boards that failed today: keep yesterday's rows for them so the book doesn't flicker
    failed = {e.split(":")[0] for e in errors}
    if failed & {"LinkedIn sweep", "Job Bank sweep"}:
        failed |= {x for x, lab in (("LinkedIn", "LinkedIn sweep"), ("Job Bank", "Job Bank sweep")) if lab in failed}
    if failed and os.path.exists(OUT):
        try:
            prev = open(OUT, encoding="utf-8").read()
            i = prev.index("const DATA = ") + len("const DATA = ")
            old_jobs = json.loads(prev[i:prev.index(";\nconst JOBS")].replace("\\u003c", "<"))["jobs"]
            have = {j["u"] for j in jobs}
            jobs += [dict(j, n=False) for j in old_jobs if (j["c"] in failed or j.get("o") in failed) and j["u"] not in have]
        except Exception as e:
            print("could not carry over yesterday's rows:", e)
    direct = [l for _, _, l in SOURCES if not l.endswith(" sweep")]
    meta = dict(run=TODAY.strftime("%a %d %b %Y"), iso=TODAY.isoformat(), at=_NOW.strftime("%H:%M"),
                boards=len([l for l in direct if l not in failed]), scanned=scanned, errors=errors,
                empty=len(empty), net=dict(read=netread, kept=netkept, dropped=netdrop, **__import__("net").STATS),
                firms=len({j["c"] for j in jobs}))

    page = open(TEMPLATE, encoding="utf-8").read()
    payload = json.dumps({"meta": meta, "jobs": jobs}, ensure_ascii=True).replace("<", "\\u003c")
    page = page.replace("/*__DATA__*/null", payload)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)

    print(f"net: {netread} read, {netkept} from firms the boards miss, {netdrop} already covered")
    print(f"{scanned} postings read from {meta['boards']} boards -> {len(jobs)} kept, "
          f"{sum(j['n'] for j in jobs)} new, {sum(j['s'] >= 8 for j in jobs)} scored 8+")
    if errors:
        print("Board failures:", ", ".join(errors))
    if empty:
        print(f"{len(empty)} boards returned no postings:", ", ".join(sorted(set(empty))))


if __name__ == "__main__":
    main()
