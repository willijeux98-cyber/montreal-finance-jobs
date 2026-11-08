"""
Canadian high-finance job desk.

Pulls postings straight from each employer's hiring system, then sweeps public job
searches (LinkedIn, Job Bank, eFinancialCareers) for investment roles across Canada at
firms the boards don't cover. Keeps buy-side, investment banking, markets, quant and
investment-risk seats at analyst level, places each one in a Canadian city, ranks them
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
import reqs  # noqa: E402  (reads what each posting actually asks for)

# ---------------------------------------------------------------- filters
# Canadian cities, each with the suburbs and spellings hiring systems use. A posting is placed in the first one it names.
CITIES = [
    ("Toronto", "ON", r"toronto|mississauga|oakville|markham|vaughan|richmond hill|north york|etobicoke|scarborough|brampton|"
                      r"thornhill|pickering|newmarket|greater toronto|\bGTA\b|(burlington|aurora|concord|ajax),\s*(on|ontario)\b"),
    ("Montréal", "QC", r"montr[eé]al|\blaval\b|longueuil|brossard|boucherville|pointe[- ]claire|saint-laurent|st-laurent|dorval|"
                       r"mont-royal|westmount|verdun|lasalle|lachine|anjou|kirkland|terrebonne|boisbriand|blainville|repentigny"),
    ("Vancouver", "BC", r"vancouver|burnaby|coquitlam|new westminster|port moody|(surrey|richmond|langley),\s*(bc|b\.c\.|british)"),
    ("Calgary", "AB", r"calgary"),
    ("Ottawa", "ON", r"ottawa|kanata|gatineau"),
    ("Edmonton", "AB", r"edmonton"),
    ("Québec City", "QC", r"qu[eé]bec city|ville de qu[eé]bec|\bl[eé]vis\b|sainte-foy|qu[eé]bec,\s*(qc|qu[eé]bec)\b|qu[eé]bec \((qc|qu[eé]bec)\)"),
    ("Winnipeg", "MB", r"winnipeg"),
    ("Halifax", "NS", r"halifax|dartmouth"),
    ("Waterloo Region", "ON", r"waterloo|kitchener|guelph|cambridge,\s*(on|ontario)\b"),
    ("Victoria", "BC", r"victoria,\s*(bc|b\.c\.|british)|victoria \(bc\)"),
    ("Regina", "SK", r"\bregina\b"),
    ("Saskatoon", "SK", r"saskatoon"),
    ("London, ON", "ON", r"london,\s*(on|ontario|canada)\b"),
    ("Hamilton", "ON", r"hamilton,\s*(on|ontario|canada)\b|hamilton \((on|ontario)\)|\(hamilton\)"),
    ("Fredericton", "NB", r"fredericton"),
    ("Moncton", "NB", r"moncton"),
    ("St. John's", "NL", r"st\.? john'?s"),
    ("Sherbrooke", "QC", r"sherbrooke"),
    ("Kelowna", "BC", r"kelowna"),
    ("Charlottetown", "PE", r"charlottetown"),
]
CITY_RX = [(name, prov, re.compile(rx, re.I)) for name, prov, rx in CITIES]
CITY_PROV = {name: prov for name, prov, _ in CITIES}
CANADA = re.compile(r"canada|ontario|qu[eé]bec|british columbia|colombie-britannique|alberta|manitoba|saskatchewan|"
                    r"nova scotia|nouvelle-[eé]cosse|new brunswick|nouveau-brunswick|newfoundland|prince edward", re.I)
CA_ABBR = re.compile(r"\b(ON|QC|BC|AB|MB|SK|NS|NB|NL|PE)\b")
FOREIGN = re.compile(r"united states|\bUSA\b|\bU\.S\.|new york|boston|chicago|houston|dallas|san francisco|los angeles|seattle|"
                     r"miami|greenwich|stamford|philadelphia|atlanta|denver|charlotte|austin|jersey city|london(?!,\s*(on|ontario))|"
                     r"united kingdom|\bUK\b|england|scotland|ireland|dublin|paris|france|madrid|milan|frankfurt|munich|zurich|"
                     r"geneva|luxembourg|amsterdam|stockholm|singapore|hong kong|tokyo|seoul|sydney|melbourne|dubai|abu dhabi|"
                     r"riyadh|doha|mumbai|bangalore|bengaluru|india|mexico|brazil|s[aã]o paulo|bermuda|cayman|grand rapids|"
                     r"st\.? petersburg|charlotte(?!town)|minneapolis|nashville|salt lake|phoenix|san diego|pittsburgh|"
                     r"cleveland|detroit|baltimore|washington,? d\.?c|mclean|richmond, va", re.I)
US_STATE = re.compile(r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|"
                      r"ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b")
MULTI = re.compile(r"^\s*\d+\s+(locations|lieux|possible locations|lieux possibles)", re.I)
REMOTE = re.compile(r"remote|t[ée]l[ée]travail|[àa] distance|work from home", re.I)

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
    (r"\bF&A\b|project financ|financement de projets", "investment banking"),
    (r"gestion des transactions|transaction management|deal management|strat[ée]gie et ex[ée]cution|"
     r"strategy (and|&) (transaction )?execution|transaction execution", "deal advisory"),
    (r"syndicat|loan structuring|structuration de pr[êe]ts", "private credit"),
    (r"credit research|high[- ]yield|distressed|special situations|leveraged loans?|syndicated loans?|loan syndication",
     "private credit"),
    (r"search fund", "private equity"),
    (r"equity analyst|investment research|buy[- ]side analyst|long/short|long-short", "research"),
    (r"institutional (equity |fixed income |equities )?sales|ventes institutionnelles", "trading"),
    (r"recherche fondamentale|fundamental research", "research"),
    (r"secondar|primaries|primary fund|funds? of funds|fonds de fonds|fund investments?|co-?invest|private markets|"
     r"marchés privés|placements privés", "fund investing"),
    (r"corporate development|développement corporatif|corp\.? dev", "corporate development"),
    (r"transaction advisory|deal advisory|transaction services|financial due diligence|business valuation|"
     r"évaluation d.entreprise|valuations? (&|and) (modeling|modelling|advisory)|restructuring", "deal advisory"),
    (r"private equity|private capital|capital[- ]investissement|buyout", "private equity"),
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
                  r"portfolio of projects|gestionnaire immobili|property manag|gestion immobili|building manag|"
                  r"g[ée]nie|\bCPI\b|charg[ée]e? (ou charg[ée] )?de projets?|infrastructures? (urbaines|municipales)|"
                  r"quantity surveyor|arpenteur|m[ée]dia|\bbudget|courtier immobilier|real estate broker(?!age)|"
                  r"contr[ôo]leur|controller|capex|capital projects?|projets? d.investissement|commercialisation|"
                  r"product portfolio|account manager(?!.*restructur)|\bcommercial (manager|insights|director)|"
                  r"financial services representative|représentant\w* (en|aux) services financiers", re.I)
OVERRIDE = re.compile(r"corporate development|développement corporatif|\bM&A\b|\bF&A\b|mergers|fusions|investment banking|"
                      r"private equity|placements? privés|capital[- ]investissement|venture|capital de risque|equity research|"
                      r"fundamental research|recherche fondamentale|transaction (services|diligence|advisory)|deal advisory|\bdeals?\b|"
                      r"valuations?\b|[ée]valuation d.entreprise|infrastructure invest|investissements? en infrastructure|"
                      r"real estate invest|investissements? immobili|private (credit|debt)|dette privée|ventes institutionnelles|"
                      r"institutional sales|"
                      r"\binvest(ment|ments|ing|issement|issements)\b", re.I)


# Big mixed institutions: only clearly investment / deal titles count (a "Senior Analyst, Operational Risk" doesn't)
STRICT = {"BDC", "EDC", "Intact", "Manulife", "Sun Life", "iA Financial Group", "Hydro-Quebec", "CN", "Bombardier"}


# Seats that are never high finance, whatever investment words the title also carries
NEVER = re.compile(r"business analyst|analyste d.affaires|investor relations|relations (avec les )?investisseurs|"
                   r"financial planning|FP&A|planification financi|deal technology|technology in deals|"
                   r"revenue coordinator|\badministrat(or|rice|eur)\b|wholesaler|grossiste|"
                   r"future opportunit|general application|expression of interest|talent (pool|community)|"
                   r"candidature spontan|opportunit[ée]s futures|"
                   # retail and wealth seats that borrow investment words
                   r"digital investing|smartfolio|tangerine|investorline|customer care|client experience|fee[- ]based|"
                   r"advsior|funds? advisor|[ée]valuat(eur|rice) de biens|appraiser|"
                   # support seats
                   r"investment platforms?\b|enablement|database|working capital|(diligence|execution)\W+technology|"
                   r"technology (due )?diligence|client (group|solutions|relationship|service|portfolio manager)", re.I)
# Corporate and commercial banking (lending relationships), unless it's the investment-banking side
CORP_BANK = re.compile(r"corporate banking|commercial banking|services bancaires aux (grandes )?entreprises|"
                       r"services bancaires commerciaux|commercial (portfolio|credit|lending|account)", re.I)
IB_WORDS = re.compile(r"investment banking|banque d.investissement|\bM&A\b|mergers", re.I)
POSTCODE = re.compile(r"\s*\(?\b(?:ON|QC|BC|AB|MB|SK|NS|NB|NL|PE|Qu[ée]b\w*|Ont\w*|Brit\w*|Alb\w*)\)?\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\s*$")
TAIL_CITY = re.compile(r"\s*[-–|,]?\s*\(?(?:Toronto|Montr[ée]al|Vancouver|Calgary|Ottawa|Edmonton|Winnipeg|Halifax)"
                       r"(?:,\s*(?:Ontario|ON|Qu[ée]bec|QC|British Columbia|BC|Alberta|AB|Manitoba|MB|Nova Scotia|NS))?\)?,?\s*$", re.I)


def clean_title(t):
    t = re.sub(r"\s*\((?:Montr[ée]al|Toronto|Ottawa)\)\s*Qu[ée]b\w*\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\s*$", "", t)
    t = POSTCODE.sub("", t)                 # "... ON M5H 0B3", "... (Vancouver) Brit V6E 4E5"
    t = re.sub(r"\s+", " ", t).strip()
    stripped = TAIL_CITY.sub("", t)          # "Associate, Corporate Development Toronto, Ontario" (the city is shown anyway)
    if len(stripped) >= 12 and stripped != t and stripped.count("(") == stripped.count(")"):   # never split "(Toronto, Calgary)"
        t = stripped
    return re.sub(r"\s+", " ", t).strip(" -–,|")


# A front-office seat named with the sector it covers ("Investment Banking - Software", "Equity Research - Media"):
# the sector words must not trip the filters that keep developers and marketers out.
FRONT_TITLE = re.compile(r"investment banking|banque d.investissement|equity research|recherche (sur les )?actions|"
                         r"research (associate|analyst)|\bM&A\b|mergers|fusions|leveraged finance|private equity|"
                         r"capital markets|march[ée]s des capitaux|corporate finance|financement corporatif|coverage|"
                         r"investments?\b|investissements?\b|placements?\b|credit research", re.I)
SECTORS = re.compile(r"software|technolog\w*|\btech\b|m[ée]dias?|telecom\w*|communications?|semiconductor\w*|memory|"
                     r"interconnect|equipment|manufacturing|health ?care|life sciences|biotech\w*|pharma\w*|energy|power|"
                     r"utilities|mining|metals|industrials?|consumer|retail|gaming|financial institutions|\bFIG\b|"
                     r"diversified|natural resources|oil|gas|internet|digital|data cent\w*|infrastructure|transportation|"
                     r"aerospace|defen[cs]e|agri\w*|chemicals?|cannabis|fintech|sports?|entertainment", re.I)


# ...but when those words name the job itself, it stays out ("Media Relations Advisor", "Technology Analyst")
ROLE_FN = re.compile(r"media relations|relations? (avec les )?m[ée]dias|communications? (advisor|specialist|manager|officer|"
                     r"coordinator|lead|associate|conseill)|conseill\w* en communication|(technology|technologie|IT) "
                     r"(analyst|analyste|associate|specialist|lead|manager|consultant|platform)|platform (analyst|engineer)|"
                     r"marketing|developer|d[ée]veloppeu|engineer(?!ing (investment|sector|coverage))|ing[ée]nieur|\bapplications?\b", re.I)


def excluded(t):
    if ROLE_FN.search(t):
        return True
    core = SECTORS.sub(" ", t) if FRONT_TITLE.search(t) else t
    if HARD.search(core) or NEVER.search(t):   # NEVER reads the whole title: its phrases are never coverage sectors
        return True
    if CORP_BANK.search(t) and not IB_WORDS.search(t):
        return True
    if OVERRIDE.search(t):
        return False
    return bool(EXCLUDE.search(core))


LEVEL_UP = re.compile(r"\b(analyst|analyste|associate|associé|junior|entry|early career)\b", re.I)
LEVEL_SENIOR_ANALYST = re.compile(r"senior analyst|analyste (principal|senior|sénior)|sr\.? analyst", re.I)
LEVEL_DOWN = re.compile(
    r"\b(manager|gestionnaire|director|directeur|directrice|vice[- ]president|\bVP\b|"
    r"head of|chef|principal\b(?!e?\s*\)?,)|partner|lead\b|managing|senior advisor|"
    r"conseill(er|ère) (principal|senior|sénior)|premier\(?-?è?r?e?\)? conseill|expert)\b",
    re.I)
STUDENT = re.compile(r"intern|stage|stagiaire|co-?op|student|étudiant|summer|été 20|winter (analyst|associate|20)|"
                     r"fall (analyst|associate|20)|off[- ]cycle|hiver 20|automne 20|new grad program", re.I)
TEMP = re.compile(r"temporary|temporaire|contract|contrat|\d+\s*(months|mois)", re.I)

CAT_BASE = {"pension": 6, "pe_vc": 6, "hedge": 6, "am": 5, "ib": 5, "markets": 5, "insurer": 4,
            "advisory": 5, "corpdev": 5, "re": 5, "open": 4}
CAT_WORDS = {
    "pension": "a pension or institutional investor",
    "pe_vc": "a private-markets investor",
    "hedge": "a trading / hedge fund shop",
    "am": "an asset manager",
    "ib": "a bank's markets and advisory side",
    "markets": "the exchange operator",
    "insurer": "an insurer's investment arm",
    "advisory": "a deal-advisory / valuation team",
    "corpdev": "a company's M&A team",
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
    "quant": "Lead with your Python and SQL, CFA Level I and any model you've built end to end. Expect a stats and coding test.",
    "valuation": "Lead with your break-even and scenario modelling and CFA Level I.",
    "markets operations": "A real way onto the markets side. Lead with your process work and CFA Level I.",
    "performance measurement": "Measuring how portfolios actually did. Lead with your data work and CFA Level I.",
    "investment risk": "Buy-side risk sits next to the portfolio managers. Lead with the modelling, CFA Level I and your insurance background.",
    "due diligence": "This is literally what you did in the merger diligence. Say so.",
    "strategy": "Strategy work at a finance shop: the same muscles as your current role. Use it as the way in.",
    "analytics": "Your current skill set at a finance shop. A foot in the door, not an investment seat.",
    "treasury": "Corporate treasury. Finance-heavy, not deal work.",
    None: "A foot in the door at a finance shop. Not an investment seat.",
}


QUANT = re.compile(r"quant|quantitativ", re.I)
# buy-side and trading-desk risk: the seat next to the portfolio managers. Operational, enterprise, model-validation,
# compliance and retail-credit risk are support functions and stay out.
INV_RISK = re.compile(r"investment risk|risques? (de |d.)(placement|investissement)|market risk|risques? de march[ée]|"
                      r"portfolio risk|risques? de portefeuille|risk analytics|total (fund|portfolio) risk|trading risk|"
                      r"risk (&|and) (quant|analytics)", re.I)
RISK_BAD = re.compile(r"operational|op[ée]rationnel|enterprise risk|risques? d.entreprise|model (risk|validation)|validation|"
                      r"technolog|cyber|third[- ]party|vendor|conduct|compliance|conformit|regulatory|r[ée]glementaire|"
                      r"adjudicat|retail|fraud|insurance risk|actuar|basel|IFRS|climate|ESG|reporting|governance|gouvernance|"
                      r"audit|non-financial|liquidity|treasury|capital management|stress test|credit risk|risque de cr[ée]dit", re.I)
GENERIC_RISK = re.compile(r"\brisk\b|\brisques?\b", re.I)
RISK_HOME = {"pension", "am", "hedge", "pe_vc"}   # where a bare "Risk Analyst" title is an investment-risk seat
BARE = re.compile(r"^\s*(senior\s+)?(analyst|associate|analyste|associé)(\s*/\s*(senior\s+)?(analyst|associate))?\s*$", re.I)
STRONG_MEDIUM = {"valuation", "markets operations", "performance measurement", "investment risk", "due diligence"}


# Words that only mean an investing seat at a buy-side firm (a pension's "Analyst, Credit" or "Analyst, Real Estate";
# at a bank the same words are lending or property management)
BUY_SIDE = {"pension", "pe_vc", "am", "hedge", "insurer"}
BS_QUANT = re.compile(r"data scien|modell?ing|mod[ée]lisation|systematic|syst[ée]matique", re.I)
BS_SEATS = [
    (r"external (manag|strateg|portfolio)|gestion externe|gestionnaires? externes?|strat[ée]gies? alternatives?|"
     r"alternative (strateg|invest)|manager (selection|research)|s[ée]lection de gestionnaires|absolute return|"
     r"hedge funds? (invest|allocat|portfolio)|fund of hedge", "fund investing"),
    (r"\bcredit\b|\bcr[ée]dit\b", "private credit"),
    (r"real estate|immobili", "real estate investing"),
    (r"asset management|gestion d.actifs|portfolio strateg|strat[ée]gie de portefeuille|portfolio construction|"
     r"[ée]tablissement de portefeuille|fundamental|fondamental", "portfolio management"),
    (r"market intelligence|veille (des )?march[ée]s?", "research"),
]


def classify(title, cat=None):
    if QUANT.search(title) and not RISK_BAD.search(title):
        return "quant", "quant"
    if cat in BUY_SIDE and BS_QUANT.search(title) and not RISK_BAD.search(title):
        return "quant", "quant"
    if INV_RISK.search(title) and not RISK_BAD.search(title):
        return "quant", "investment risk"
    if cat in RISK_HOME and GENERIC_RISK.search(title) and not RISK_BAD.search(title):
        return "quant", "investment risk"
    if cat in ("pe_vc", "pension") and BARE.search(title):
        return "strong", "investments"
    if cat in BUY_SIDE:
        for pat, name in BS_SEATS:
            if re.search(pat, title, re.I):
                return "strong", name
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
# support seats that borrow an investment word: "Investment Operations", "Trading Risk", "Fund Reporting"
OPS = re.compile(r"operations|operational|opérations|opérationnel|due diligence officer|\bKYC\b|know your client|administration|settlement|règlement|controls?\b|contrôle|oversight|production|"
                 r"autoris|adjudicat|servicing|integration|intégration|\brisk|risque|performance|analytics|analytique|"
                 r"reporting|\bdata\b|données|compliance|conformité|middle office|back office|fund accounting|"
                 r"information financière|financial information", re.I)
# the same list without the words a quant or risk seat legitimately carries in its title
OPS_CORE = re.compile(r"operations|operational|opérations|opérationnel|due diligence officer|\bKYC\b|know your client|administration|"
                      r"settlement|règlement|control\b|contrôle|oversight|autoris|adjudicat|servicing|integration|intégration|"
                      r"reporting|compliance|conformité|middle office|back office|fund accounting|information financière", re.I)
DEAL_CORE = re.compile(r"restructur|transaction diligence|due diligence|transaction services|valuations?\b|"
                       r"\bM&A (advisory|transaction|diligence)|deal advisory|fusions et acquisitions", re.I)
PORTFOLIO_SEAT = re.compile(r"portfolio (strateg|construction)|strat[ée]gie de portefeuille|total (fund|portfolio)", re.I)
FRONT_MEDIUM = {"valuation", "due diligence"}   # the only "medium" seats that still lead to deal work
LVL_ADV = re.compile(r"advisor|conseill|specialist|spécialiste", re.I)


def level_of(t):
    if re.search(r"\b(associate|assistant) vice[- ]president|\bAVP\b|vice-pr[ée]sident(e)? adjoint", t, re.I):
        return "senior", -3
    if re.search(r"associate portfolio manager|gestionnaire de portefeuille associ|assistant portfolio manager", t, re.I):
        return "mixed", -1
    t = re.sub(r"principal invest\w*|investissements? principaux|principal (finance|credit|capital)", " ", t, flags=re.I)   # a seat, not a rank
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
    job["_trk"] = kind != "none"   # tracked for "still posted" even when it isn't shown
    if cat == "ib" and re.search(r"investment associate|associ\w* en (investissement|placements)", t, re.I):
        return None  # wealth-desk assistant seat at a bank
    # banks are huge: only keep their front-office seats
    if (cat in ("ib", "insurer", "markets", "advisory", "corpdev", "re", "open") or job["c"] in STRICT) and kind not in ("strong", "quant"):
        if not ((cat in ("ib", "advisory") and sig in ("valuation", "markets operations", "due diligence")) or
                (job["c"] in STRICT and sig in ("valuation", "due diligence"))):
            return None
    if cat == "ib" and re.search(r"asset[- ]based lend|pr[êe]ts? (adoss|garantis par des actifs)", t, re.I):
        return None  # a bank's asset-based lending desk is corporate lending (at a credit fund it's private credit)
    if cat == "corpdev" and sig not in ("corporate development", "investment banking", "deal advisory", "fund investing"):
        return None  # at an operating company only the M&A / corp-dev seats count
    if cat == "advisory" and sig not in ("deal advisory", "investment banking", "valuation", "due diligence"):
        return None
    if kind == "none":
        return None  # only investing, deal, markets and corporate-finance seats
    if kind == "medium" and sig not in FRONT_MEDIUM:
        return None  # risk, performance, analytics, strategy, treasury: support seats, not the target path
    if (kind in ("strong", "medium") and OPS.search(t) and not (PORTFOLIO_SEAT.search(t) and not OPS_CORE.search(t))
            and not DEAL_CORE.search(t)):
        return None  # investment word, support seat (model risk, operational due diligence, KYC...)
    if kind == "quant" and OPS_CORE.search(t):
        return None
    if cat in ("open", "corpdev") and sig == "real estate investing" and not re.search(
            r"acqui|invest|placement|financement|financing|capital|transaction", t, re.I):
        return None  # a retailer's or operator's own real estate team: leasing and sites, not investing
    s = CAT_BASE[cat]
    if kind == "strong":
        s += 3
    elif kind == "quant":
        s += 2 if sig == "quant" else 1
    elif kind == "medium":
        s += 1 if sig in STRONG_MEDIUM else 0
    else:
        s -= 2
    level, adj = level_of(t)
    s += adj
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
    if not job["m"]:
        s -= 1   # the posting doesn't name its city
    job["_raw"], job["_ladj"] = s, adj   # kept so the posting's own requirements can replace the title's guess
    s = max(0, min(10, s))
    if s < 4:
        return None
    job["s"] = s
    job["sig"] = sig or ""
    job["why"] = why(job, kind, sig, level)
    job["lv"], job["k"] = level, kind
    job["ad"] = ANGLE.get(sig or None, ANGLE[None])
    job["tm"] = bool(TEMP.search(t))
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
    if not job["m"]:
        extra += " The posting doesn't pin down the city, so check which office it sits in."
    if job.get("fresh") == "evergreen":
        extra += " It has been posted for months: likely an always-open pipeline rather than a live seat."
    return f"{lvl}: {what}.{extra} {ANGLE.get(sig, ANGLE[None])}"


# ---------------------------------------------------------------- fit: what the posting asks for vs where he is
# About two years of full-time work, roughly one of it on M&A / corporate-strategy work, none in an investment seat.
# CFA Level I passed, Level II candidate. Edit these three numbers as that changes.
PROFILE = dict(general=2, ops=2, deals=1, investing=0)
REQS_PATH = os.path.join(ROOT, "data", "reqs.json")
REQS_STATS = dict(read=0, cached=0, failed=0, linkedin_limited=0, linkedin_deferred=0)
LI_READ_BUDGET = 60 if os.environ.get("PB_QUICK") == "1" else 600


TOP = {"advisory": 9, "corpdev": 9, "re": 9, "open": 9, "insurer": 9, "markets": 9}


def have_years(domains):
    """His years for the kind of experience asked for. A list of alternatives ("IB, PE or consulting") counts the best."""
    return max(PROFILE.get(d, PROFILE["general"]) for d in (domains or ["general"]))


def gap_adj(gap):
    """Years short of the bar -> score change. At or past the bar is a plus; three years short is a long shot."""
    if gap <= 0:
        return 1
    if gap <= 1:
        return 0
    if gap <= 2:
        return -2
    if gap <= 3:
        return -3
    if gap <= 4:
        return -4
    return -5


def apply_reqs(j, rq):
    """Re-rank a role on what its posting asks for. False = the posting shows a support seat, drop it."""
    j["r"] = None
    if not rq or not rq.get("ok"):
        return True
    if reqs.back_office(rq) and not (j.get("sig") in ("quant", "investment risk") and not rq.get("opsy")):
        return False
    have = have_years(rq.get("yd"))
    gap = None
    if rq.get("y") is not None:
        gap = round(rq["y"] - have, 1)
    elif rq.get("jr"):
        gap = -1.0
    s = j["_raw"] - j["_ladj"]            # take the title's guess at the level back out
    if gap is None:
        s += j["_ladj"] - (1 if rq.get("inv") and j["_ladj"] > 0 else 0)   # no bar stated: keep the title's read
    else:
        fit = gap_adj(gap)
        if j.get("lv") in ("exec", "senior", "student"):
            fit = min(fit, j["_ladj"])    # a manager or intern title still caps it
        s += fit
    if rq.get("cfa") == "charter":
        s -= 1
    if rq.get("mba"):
        s -= 2
    if rq.get("cpa"):
        s -= 1
    j["s"] = max(0, min(TOP.get(j["cat"], 10), s))
    j["r"] = dict(y=rq.get("y"), yh=rq.get("yh"), d=rq.get("yd") or [], q=rq.get("q") or "", h=have, gap=gap,
                  cfa=rq.get("cfa") or "", mba=bool(rq.get("mba")), cpa=bool(rq.get("cpa")), fr=bool(rq.get("fr")),
                  jr=bool(rq.get("jr")), inv=bool(rq.get("inv")))
    return j["s"] >= 4


def read_reqs(cands):
    """Posting requirements for each candidate, read once per posting and cached in data/reqs.json."""
    import time
    try:
        cache = json.load(open(REQS_PATH, encoding="utf-8"))
    except Exception:
        cache = {}
    if cache.get("_v") != reqs.VERSION:
        cache = {}
    todo = [j for j in cands if j["u"] not in cache]
    REQS_STATS["cached"] = len(cands) - len(todo)

    def one(j):
        try:
            text = reqs.description(j["u"], j.get("api"))
        except Exception as e:
            REQS_STATS["failed"] += 1
            if "429" in str(e):
                REQS_STATS["linkedin_limited"] += 1
            return j["u"], None
        REQS_STATS["read"] += 1
        r = reqs.parse(text, j["t"])
        r["d"] = TODAY.isoformat()
        return j["u"], r
    live = {j["u"] for j in cands}

    def keep():
        os.makedirs(os.path.dirname(REQS_PATH), exist_ok=True)
        json.dump(dict({u: r for u, r in cache.items() if u in live}, _v=reqs.VERSION),
                  open(REQS_PATH, "w", encoding="utf-8"), indent=0, sort_keys=True, ensure_ascii=False)

    li = sorted((j for j in todo if "linkedin.com" in j["u"]), key=lambda j: -j["s"])   # best candidates first
    rest = [j for j in todo if "linkedin.com" not in j["u"]]
    with cf.ThreadPoolExecutor(12) as ex:
        for u, r in ex.map(one, rest):
            if r is not None and r.get("ok"):
                cache[u] = r
    keep()   # the boards' readings are safe even if the LinkedIn pass is cut short
    # LinkedIn's public pages: one at a time, stop if it pushes back, and never more than LI_READ_BUDGET seconds a night.
    # Readings are cached, so whatever isn't read tonight is read on a later night.
    t0 = time.time()
    for j in li:
        if REQS_STATS["linkedin_limited"] >= 3 or time.time() - t0 > LI_READ_BUDGET:
            REQS_STATS["linkedin_deferred"] = len(li) - li.index(j)
            break
        u, r = one(j)
        if r is not None and r.get("ok"):
            cache[u] = r
        time.sleep(1.2)
    keep()
    return {u: r for u, r in cache.items() if u in live}


SOURCES = [(lambda _s, f=f: f(), None, label) for f, label in build_sources()]
MIN_SHOW = 6   # shown from 6 up (6 = "long shot"); every investment-titled posting is still tracked so Applied can tell "still posted"


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
    "banque scotia": "Scotiabank", "groupe financier banque td": "TD", "ia financier": "iA Financial Group", "financier banque td": "TD", "caisse depot et placement quebec": "CDPQ", "kpmg": "KPMG", "deloitte": "Deloitte", "ey": "EY", "ernst & young": "EY", "pwc": "PwC", "pricewaterhousecoopers": "PwC",
    "agf": "AGF", "agf investments": "AGF", "alberta investment management": "AIMCo", "aimco": "AIMCo",
    "ontario teachers pension plan": "Ontario Teachers", "ontario teachers": "Ontario Teachers", "otpp": "Ontario Teachers",
    "cpp investments": "CPP Investments", "canada pension plan investment board": "CPP Investments", "cppib": "CPP Investments",
    "healthcare ontario pension plan": "HOOPP", "hoopp": "HOOPP", "investment management corporation ontario": "IMCO",
    "imco": "IMCO", "british columbia investment management": "BCI", "bci": "BCI", "connor clark lunn": "Connor Clark & Lunn",
    "omers": "OMERS", "la caisse": "CDPQ", "brookfield asset management": "Brookfield", "rbc capital markets": "RBC",
    "td securities": "TD", "bmo capital markets": "BMO", "cibc capital markets": "CIBC", "scotia capital": "Scotiabank",
    "national bank financial": "National Bank", "financiere banque nationale": "National Bank",
    "purpose": "Purpose Investments", "purpose unlimited": "Purpose Investments", "purpose investments": "Purpose Investments",
}


def tidy_co(name):
    """Display name: 'Gold Investment Management Ltd.' -> 'Gold Investment Management'."""
    n = re.sub(r"\s*\((formerly|anciennement).*$", "", str(name or "").strip(), flags=re.I)
    for _ in range(3):
        n = re.sub(r"\s*\(([A-Z0-9&.\- ]{2,8}|canada)\)\s*$", "", n.strip(), flags=re.I)
        n = re.sub(r",?\s+(inc|ltd|ltée|limited|limitée|corp|llc|l\.?p|s\.?e\.?n\.?c)\.?$", "", n.strip(), flags=re.I)
    return n.strip() or str(name or "").strip()


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
                        r"\bacca careers\b|jobillico|talent\.com|indeed|workopolis|eluta|\brecrutement\b|staffing|placement de personnel|"
                        r"hunter bond|anson mccade|robert half|\bhays\b|michael page|page group|randstad|adecco|kforce|"
                        r"morgan mckinley|selby jennings|harnham|venatus|teksystems|\bbaro\s?rh\b|dialectica|fed finance|"
                        r"recruit|executive search|search partners|talent partners|\bPER\b|private equity recruitment|"
                        r"ziprecruiter|jooble|glassdoor|monster|careerbuilder|korn ferry|heidrick|spencer stuart|"
                        r"russell reynolds|odgers|caldwell partners|walker hamill|oxford knight|options group|dartmouth partners|"
                        r"bay street search|cooper fitch|bruin|jobs for humanity|confidential|crossover|mercor|joblet|"
                        r"jobgether|lensa|dice\b|hirequest|careerjet|simplyhired", re.I)


def guess_cat(company):
    c = fold(company)
    if re.search(r"hedge|multi[- ]strateg|\balpha\b|quantitative", c):
        return "hedge"
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


# ---------------------------------------------------------------- where in Canada?
def city_of(text):
    """First Canadian city a location string names -> (city, province) or None."""
    best = None
    for name, prov, rx in CITY_RX:
        m = rx.search(text or "")
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name, prov)
    return best and best[1:]


def keep_location(j):
    """Place the posting in Canada, or drop it. Sets ct (city), pv (province), m (the posting itself names the city)."""
    loc = "" if (j["l"] or "").startswith("Location not stated") else (j["l"] or "")
    home = "head office" in loc
    title = j.get("t0") or j["t"]
    hit = city_of(loc) or city_of(title)
    if hit:
        j["ct"], j["pv"] = hit
        j["m"] = not home   # "Toronto (head office)" is our inference from a careers page, not the posting's word
        return True
    if FOREIGN.search(loc) or FOREIGN.search(title) or US_STATE.search(loc) or US_STATE.search(title):
        return False
    j["m"], j["pv"] = False, ""
    if CANADA.search(loc) or CA_ABBR.search(loc):
        j["ct"] = "Remote" if REMOTE.search(loc + " " + title) else "Canada"
        return True
    if MULTI.search(loc) and (j["hq"] or j.get("hint")):
        j["ct"] = "Multiple cities"
        return True
    if j["hq"]:
        if not loc.strip():
            from sources import FIRM_CITY
            c = FIRM_CITY.get(j["c"])
            j["ct"], j["pv"] = (c, CITY_PROV.get(c, "")) if c else ("Canada", "")
            return True
    return False


# ---------------------------------------------------------------- the filter: analyst-level seats only
def analyst_level(j):
    """Analyst-level seats (0-3 years): no manager / director / VP titles, no internships, and nothing whose posting
    asks for more than three years of experience."""
    if j.get("lv") in ("exec", "senior", "student"):
        return False
    r = j.get("r")
    return not (r and r.get("y") is not None and r["y"] > 3)


# seat key for the page's filters
SEAT = {"private equity": "pe", "venture / growth": "pe", "fund investing": "pe", "investment banking": "ib",
        "deal advisory": "deals", "valuation": "deals", "due diligence": "deals", "corporate development": "deals",
        "private credit": "credit", "research": "research", "trading": "st", "markets": "st", "capital markets": "st",
        "portfolio management": "am", "infrastructure investing": "real", "real estate investing": "real",
        "natural resources investing": "real", "quant": "quant", "investment risk": "quant"}
BY_FIRM = {"pe_vc": "pe", "pension": "am", "am": "am", "insurer": "am", "hedge": "hf", "re": "real", "ib": "ib",
           "markets": "st", "advisory": "deals", "corpdev": "deals", "open": "am"}
HEDGE_WORDS = re.compile(r"hedge fund|long/short|multi[- ]strateg|multi[- ]manager|\bpod\b", re.I)


def seat_of(j):
    sig, cat = j.get("sig") or "", j["cat"]
    if (cat == "hedge" or HEDGE_WORDS.search(j["t"])) and sig not in ("quant", "investment risk", "real estate investing",
                                                                      "infrastructure investing", "private equity"):
        return "hf"
    if sig == "private credit" and cat == "ib":
        return "ib"   # leveraged finance and loan syndication at a bank
    return SEAT.get(sig) or BY_FIRM.get(cat, "am")


def directory_firms():
    """CVCA and PMAC member names -> category, so a small firm found on LinkedIn is recognised for what it is."""
    out = {}
    try:
        for x in json.load(open(os.path.join(ROOT, "data", "cvca.json"), encoding="utf-8")):
            out[x["name"]] = x["cat"]
    except Exception:
        pass
    try:
        for n in json.load(open(os.path.join(ROOT, "data", "pmac.json"), encoding="utf-8")):
            out.setdefault(n, "am")
    except Exception:
        pass
    return out


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
    from sources import CA_HQ
    try:
        boards = json.load(open(os.path.join(ROOT, "data", "boards.json"), encoding="utf-8"))
    except Exception:
        boards = []
    cats = {b["name"]: b["cat"] for b in boards}
    for _, _, label in SOURCES:
        cats.setdefault(label, None)
    for j in raw:
        cats[j["c"]] = j["cat"]
    dirs = directory_firms()
    # two passes: the firms we read directly first ("Northleaf Capital Partners" is Northleaf Capital, whose board we
    # read), then the CVCA / PMAC directories for small firms we only meet on job sites
    idx = firm_index(list(cats) + list(CA_HQ))
    didx = {norm_co(n): n for n in dirs if norm_co(n)}
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
            j["c"], j["cat"], j["hq"] = firm, cats.get(firm) or dirs.get(firm) or guess_cat(firm), firm in CA_HQ
        elif match_firm(j["c"], didx):
            d = match_firm(j["c"], didx)
            j["c"], j["cat"], j["hq"] = tidy_co(d), dirs[d], True
        else:
            j["c"] = tidy_co(j["c"])
            j["cat"] = guess_cat(j["c"])
        netkept += 1
        raw.append(j)

    kept, dedupe, trk = [], {}, set()
    for j in raw:
        j["t0"] = j["t"] or ""            # the title as posted: the city reader still needs "Analyst - Toronto"
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
        ok = score(j)
        if j.get("_trk"):
            trk.add(j["u"])
        if ok:
            prev = dedupe.get(key)
            if prev is None or j["s"] > prev["s"]:
                dedupe[key] = j
    kept = list(dedupe.values())

    # read what each serious candidate actually asks for, and re-rank on it
    cands = [j for j in kept if j["s"] >= MIN_SHOW - 2]
    found = read_reqs(cands)
    dropped_support = 0
    final = []
    for j in kept:
        if j["s"] >= MIN_SHOW - 2 and not apply_reqs(j, found.get(j["u"])):
            dropped_support += 1
            continue
        final.append(j)
    kept = final
    print(f"requirements: {REQS_STATS['read']} read, {REQS_STATS['cached']} cached, {REQS_STATS['failed']} failed, "
          f"{REQS_STATS['linkedin_deferred']} LinkedIn postings left for a later night; {dropped_support} support seats dropped")

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
    alive = sorted({j["u"] for j in kept} | trk)
    # the same seat under two spellings of one firm ("Purpose" / "Purpose Investments", from two job sites): keep one
    best = {}
    for j in sorted(kept, key=lambda j: (bool(j.get("net")), -j["s"])):   # the firm's own board first, then the higher score
        head = (norm_co(j["c"]).split() or [""])[0]
        k = (head if len(head) >= 4 else norm_co(j["c"]), re.sub(r"[^a-z0-9]+", " ", fold(j["t"])).strip(), j.get("ct"))
        best.setdefault(k, j)
    kept = sorted(best.values(), key=lambda j: (-j["s"], j["age"] if j["age"] is not None else 999))
    above = [j for j in kept if j["s"] >= MIN_SHOW]
    shown = [j for j in above if analyst_level(j)]
    print(f"analyst gate: {len(above) - len(shown)} senior or 3+ year seats dropped, {len(shown)} kept")
    jobs = [dict(s=j["s"], c=j["c"], cat=j["cat"], t=j["t"], l=j["l"], u=j["u"],
                 a=j["age"], n=j["new"], m=j["m"], w=j["why"], o=j.get("net") or "", g=j.get("sig") or "",
                 lv=j.get("lv"), k=j.get("k"), ad=j.get("ad"), tm=j.get("tm", False), ev=j.get("fresh") == "evergreen",
                 r=j.get("r"), ct=j.get("ct") or "Canada", pv=j.get("pv") or "", st=seat_of(j))
            for j in shown]
    if len(errors) > len(SOURCES) / 3:
        raise SystemExit(f"{len(errors)} of {len(SOURCES)} boards failed; keeping yesterday's page. {errors[:10]}")
    # boards that failed today: keep yesterday's rows for them so the book doesn't flicker
    failed = {e.split(":")[0] for e in errors}
    sweeps = (("LinkedIn", "LinkedIn sweep"), ("Job Bank", "Job Bank sweep"), ("eFinancialCareers", "eFinancialCareers sweep"))
    failed |= {x for x, lab in sweeps if lab in failed}
    if failed and os.path.exists(OUT):
        try:
            prev = open(OUT, encoding="utf-8").read()
            i = prev.index("const DATA = ") + len("const DATA = ")
            old_jobs = json.loads(prev[i:prev.index(";\nconst JOBS")].replace("\\u003c", "<"))["jobs"]
            have = {j["u"] for j in jobs}
            carried = [dict(j, n=False) for j in old_jobs
                       if (j["c"] in failed or j.get("o") in failed) and j["u"] not in have and j.get("s", 0) >= MIN_SHOW
                       and j.get("ct")]   # rows from before the Canada-wide build have no city: let them go
            jobs += carried
            alive = sorted(set(alive) | {j["u"] for j in carried})
        except Exception as e:
            print("could not carry over yesterday's rows:", e)
    direct = [l for _, _, l in SOURCES if not l.endswith(" sweep")]
    edition = "morning" if _NOW.hour < 11 else "midday" if _NOW.hour < 17 else "evening"
    meta = dict(run=TODAY.strftime("%a %d %b %Y"), iso=TODAY.isoformat(), at=_NOW.strftime("%H:%M"),
                slot=os.environ.get("PB_SLOT") or f"{TODAY.isoformat()}-{edition}", edition=edition,
                boards=len([l for l in direct if l not in failed]), scanned=scanned, errors=errors,
                empty=len(empty), net=dict(read=netread, kept=netkept, dropped=netdrop, **__import__("net").STATS),
                firms=len({j["c"] for j in jobs}), min=MIN_SHOW, tracked=len(alive), reqs=dict(REQS_STATS),
                profile=PROFILE)

    page = open(TEMPLATE, encoding="utf-8").read()
    payload = json.dumps({"meta": meta, "jobs": jobs, "alive": alive}, ensure_ascii=True).replace("<", "\\u003c")
    page = page.replace("/*__DATA__*/null", payload)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(page)

    print(f"net: {netread} read, {netkept} from firms the boards miss, {netdrop} already covered")
    print(f"{scanned} postings read from {meta['boards']} boards -> {len(jobs)} kept, "
          f"{sum(j['n'] for j in jobs)} new, {sum(j['s'] >= 9 for j in jobs)} scored 9+")
    if errors:
        print("Board failures:", ", ".join(errors))
    if empty:
        print(f"{len(empty)} boards returned no postings:", ", ".join(sorted(set(empty))))


if __name__ == "__main__":
    main()
