"""
The Syracuse desk: every professional posting around Syracuse, NY, scored for a second profile.

The profile is a software engineer (about three and a half years of Java / Spring / Angular full-stack work on an
agile team, with requirements and sprint-planning duties) who now runs fleet and event operations (about a year
and a half leading a team of 25+). Computer science and math degree, a college teaching-assistant stint, English
and French. Nothing personal lives in this file: the repo and the page are public.

Sources: the area's big employers read straight from their hiring systems (Micron, Carrier, Lockheed Martin, SRC,
JMA Wireless, Amazon, M&T, KeyBank, Le Moyne, Terakeet, New York State), then LinkedIn's public job search around
Syracuse for everyone else. Roles are sorted into families (software, operations and logistics, tech-business,
everything else professional), scored 0-10, and the posting itself is read for the experience it asks for.
"""
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import time

import requests

import reqs
from sources import _wd_days

ROOT = os.path.dirname(os.path.abspath(__file__))
REQS_PATH = os.path.join(ROOT, "data", "syr_reqs.json")
SEEN_PATH = os.path.join(ROOT, "data", "syr_seen.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
try:
    from zoneinfo import ZoneInfo
    TODAY = dt.datetime.now(ZoneInfo("America/New_York")).date()
except Exception:
    TODAY = dt.date.today()

# Syracuse and everything within a reasonable daily drive of North Syracuse
AREA = re.compile(r"syracuse|liverpool|\bclay\b|cicero|dewitt|de witt|fayetteville|manlius|camillus|baldwinsville|"
                  r"\bsalina\b|solvay|jamesville|onondaga|brewerton|minoa|kirkville|skaneateles|marcellus|cazenovia|"
                  r"auburn, ny|auburn, new york|\bfulton\b|oswego|cortland|chittenango|canastota|\bphoenix, ny|lafayette, ny|"
                  r"\btully\b|mattydale|east syracuse|north syracuse|bridgeport, ny|lysander|van buren|geddes|elbridge|"
                  r"pompey|dewitt|hancock", re.I)
OTHER_STATE = re.compile(r",\s*(?!NY\b|New York\b)([A-Z]{2}|Indiana|Utah|Kansas|Nebraska|Ohio|Missouri|Utah)\b")

# PROFILE: years of experience by family. Edit as it changes.
PROFILE = dict(software=3.5, ops=1.5, techbiz=3.5, edu=2, other=4.5)

# ---------------------------------------------------------------- families
SOFTWARE = re.compile(
    r"software|developer|développeur|programmer|full[- ]?stack|back[- ]?end|front[- ]?end|\bjava\b|spring(?!\s*(20)?\d{2}\b|\s+(semester|term|session|break|cleaning))|angular|"
    r"\breact\b|\.net\b|\bweb (engineer|developer|application)|application (developer|engineer)|devops|\bsre\b|"
    r"site reliability|cloud (engineer|developer|architect)|platform engineer|(data|software automation|test automation|qa|"
    r"security|cyber|embedded|firmware|ai|ml|machine learning|computer|it) engineer|"
    r"engineer,? (software|data|cloud|devops|platform)|sdet|\bswe\b|coder|technical lead", re.I)
# engineering disciplines that aren't software, unless the title says software outright
ENG_OTHER = re.compile(r"mechanical|electrical|chemical|civil|structural|\bprocess\b|manufacturing|quality|refrigeration|"
                       r"hvac|water|\bgas\b|construction|environmental|industrial|materials?\b|\brf\b|antenna|hardware|"
                       r"optical|packaging|facilit|field service|procurement|thermal|compression|\blab\b|product engineer|"
                       r"radar|power|electronics|test engineer|integration (&|and) test|operations engineer", re.I)
MECH = re.compile(r"mechanical|electrical|chemical|civil|structural|\bprocess\b|manufacturing|quality|refrigeration|hvac|"
                  r"water|\bgas\b|construction|environmental|industrial|materials?\b|thermal|compression|\blab\b|power|"
                  r"packaging|facilit|optical|hardware|antenna|\brf\b|electronics|product engineer", re.I)
SOFT_WORD = re.compile(r"software|developer|full[- ]?stack|programmer|devops|cloud|\bdata\b|\bai\b|\bml\b|machine learning|"
                       r"cyber|\bweb\b|application|embedded software", re.I)
OPS = re.compile(
    r"logistics|fleet|transportation|dispatch|supply chain|distribution|warehouse|fulfillment|delivery station|"
    r"station manager|area manager|operations (manager|director|supervisor|lead|coordinator|leader)|"
    r"(director|head|vp|vice president|manager|supervisor) of operations|director,? operations|general manager|"
    r"site (manager|lead|leader)|plant manager|shift manager|event (manager|coordinator|operations|planner|director)|"
    r"events? (manager|coordinator)|inventory (manager|control|planner)|material(s)? (manager|planner)|"
    r"procurement|purchasing|buyer|(production|material|supply|demand|logistics|transportation|inventory|capacity|"
    r"master) (planner|scheduler)|operations\b", re.I)
TECHBIZ = re.compile(
    r"business analyst|systems analyst|business systems|technical project|project manager|program manager|"
    r"product (manager|owner|analyst)|scrum|agile|implementation|solutions? (engineer|consultant|architect|analyst)|"
    r"technical (account|consultant|specialist|support engineer)|\bit (manager|director|project|analyst|specialist|"
    r"coordinator|consultant)|information technology|data analyst|data (scientist|engineer)|analytics|"
    r"business intelligence|\bbi (developer|analyst)|process improvement|continuous improvement|lean|six sigma|"
    r"operations analyst|erp|sap\b|salesforce|crm|database|dba|network (engineer|administrator)|systems administrator|"
    r"technology (consultant|analyst|manager)|consultant|pmo|project coordinator|project engineer", re.I)
EDU = re.compile(r"instructor|lecturer|teaching|tutor|adjunct|professor|faculty|curriculum|teacher", re.I)
FAMILY_NAME = {"software": "Software engineering", "ops": "Operations & logistics", "techbiz": "Tech & business",
               "edu": "Teaching", "other": "Other professional"}
FAMILY_BASE = {"software": 6, "ops": 7, "techbiz": 5, "edu": 4, "other": 4}

# Hourly, clinical, trades, retail floor, driving: not this profile
HARD = re.compile(
    r"\b(nurse|rn\b|lpn|cna\b|nursing|physician|surgeon|pharmac|therapist|dental|dentist|hygienist|medical assistant|"
    r"phlebotom|radiolog|sonograph|technologist|patient|clinical|clinician|psychiatr|psycholog|counselor|social worker|"
    r"caregiver|home health|direct support|aide\b|cook\b|chef|dishwasher|server\b|bartender|barista|host/hostess|"
    r"housekeep|room attendant|janitor|custodian|cleaner|crew member|cashier|teller|sales associate|retail associate|"
    r"store associate|stocker|merchandiser|package handler|warehouse associate|picker|packer|forklift|material handler|"
    r"cdl|truck driver|delivery driver|driver\b|courier|mechanic|technician|welder|electrician|plumber|hvac|"
    r"carpenter|laborer|labourer|painter|landscap|groundskeeper|machinist|assembler|production (operator|worker|associate)|"
    r"operator\b|security officer|security guard|lifeguard|crossing guard|correction officer|police|firefighter|"
    r"veterinar|groomer|kennel|daycare|child care|childcare|nanny|babysit|substitute|paraprofessional|teacher aide|"
    r"receptionist|front desk|call center|customer service representative|bus driver|valet|attendant|"
    r"pathologist|anesthes|midwife|optometr|audiolog|dietitian|food service|cafeteria|stylist|barber|massage|"
    r"crna|np\b|nurse practitioner|physician assistant|\bpa-c|resident\b|fellowship|chaplain|"
    r"customer service associate|service associate|banker\b|representative|universal banker|loan officer|"
    r"mortgage|insurance agent|sales consultant|retail|store manager|assistant store|shift lead|"
    r"warehouse worker|fulfillment associate|associate, dsl|delivery associate|seasonal|secretary|office assistant|"
    r"clerk|administrative assistant|keyboarding|typist|data entry|operations assistant|maintenance assistant)", re.I)
STUDENT = re.compile(r"intern\b|internship|co-?op\b|student|summer 20|graduate assistant|work study|apprentice", re.I)
SENIOR = re.compile(r"\bsenior\b|\bsr\.?\b|\blead\b|\biii\b|\biv\b|level (3|4|iii|iv)|e3\b|\bl3\b", re.I)
STAFF = re.compile(r"\bstaff\b|\bstf\b|principal|architect|distinguished|fellow\b|e4\b|e5\b|level 5|\bl4\b|\bl5\b", re.I)
EXEC = re.compile(r"vice president|\bvp\b|chief|\bcto\b|\bcio\b|\bcoo\b|head of|executive director|president\b", re.I)
MANAGER = re.compile(r"manager|director|supervisor|superintendent", re.I)
JUNIOR = re.compile(r"junior|\bjr\.?\b|entry[- ]level|associate\b|\bi\b|level (1|i)\b|early career|new grad|e1\b|e2\b|asc\b", re.I)
STACK = re.compile(r"\bjava\b|spring(?!\s*(20)?\d{2}\b|\s+(semester|term|session|break|cleaning))|angular|full[- ]?stack|j2ee|microservices", re.I)
FRENCH = re.compile(r"french|bilingual|francophone", re.I)

PITCH = {
    "software": "Lead with three and a half years shipping Java, Spring and Angular features for public and private clients on an agile team. Mention the 50% faster requirements turnaround and the 30% better on-time delivery from running sprint planning.",
    "ops": "Lead with running fleet scheduling and routing for 20+ corporate events a year and supervising 25+ staff. The routing redesign is the headline result. The software background is the edge: you can fix the tools, not just use them.",
    "techbiz": "This is the bridge role: three and a half years turning client requirements into designs and acceptance criteria (50% faster turnaround), sprint planning (+30% on-time delivery), plus real operations leadership since.",
    "edu": "Lead with the computer science teaching-assistant work (labs and tutoring for 50+ students) and the CS + math degree.",
    "other": "Lead with the mix: an engineer's problem solving, operations leadership of 25+ staff, and full English and French.",
}


CAP = {"other": 5, "edu": 6}   # an unrelated role never outranks a related one


def family(t):
    if re.search(r"\bcnc\b|\bplc\b|numerical control|robot integrator|machin", t, re.I):
        return "other"          # shop-floor programming, not software engineering
    if ENG_OTHER.search(t) and not SOFT_WORD.search(t):
        if MECH.search(t):
            return "other"      # mechanical, electrical, process, plant... engineering: not his field
        return "techbiz" if re.search(r"systems engineer|test engineer|integration", t, re.I) else "other"
    if SOFTWARE.search(t) and not re.search(r"sales|recruit|account executive", t, re.I):
        return "software"
    if re.search(r"systems engineer", t, re.I):
        return "techbiz"
    if OPS.search(t):
        return "ops"
    if TECHBIZ.search(t):
        return "techbiz"
    if EDU.search(t) and re.search(r"computer|programming|math|software|coding|stem|technology|data", t, re.I):
        return "edu"
    return "other"


def level(t, fam):
    """-> (label, score change) from the title alone."""
    if STUDENT.search(t):
        return "student", -6
    if EXEC.search(t):
        return "exec", -4
    if fam == "ops":
        if re.search(r"director|general manager|plant manager", t, re.I):
            return "director", 1          # he runs a logistics operation today
        if MANAGER.search(t) or re.search(r"\blead\b", t, re.I):
            return "manager", 1
        if re.search(r"coordinator|planner|scheduler|analyst|specialist|buyer", t, re.I):
            return "coordinator", -1
        return "unclear", 0
    if STAFF.search(t):
        return "staff", -3
    if fam in ("software", "techbiz") and re.search(r"(engineering|development|software|it) manager|director", t, re.I):
        return "eng manager", -2
    if SENIOR.search(t):
        return "senior", -1
    if JUNIOR.search(t):
        return "junior", 0
    if MANAGER.search(t):
        return "manager", -1
    return "mid", 1


def score(j):
    t = j["t"]
    if not t or HARD.search(t):
        return None
    fam = family(t)
    s = FAMILY_BASE[fam]
    if fam == "software" and STACK.search(t):
        s += 2              # his exact stack in the title
    lv, adj = level(t, fam)
    s += adj
    if FRENCH.search(t):
        s += 1
    a = j.get("age")
    if a is not None:
        if a <= 7:
            s += 1
        elif a > 45 and a != 31:
            s -= 1
    j.update(fam=fam, lv=lv, _raw=s, _ladj=adj)
    j["s"] = max(0, min(CAP.get(fam, 10), s))
    return j if j["s"] >= 3 else None


HIS_STACK = {"java", "spring", "spring boot", "angular", "sql", "python", "aws", "docker", "microservices", "c#", "react", "typescript"}
CLEAR = re.compile(r"security clearance|secret clearance|ts/sci|top secret|clearance (is )?required|active clearance|"
                   r"ability to obtain (and maintain )?a (u\.s\. )?(government )?(security )?clearance|"
                   r"u\.?s\.? citizenship (is )?required|must be a u\.?s\.? citizen", re.I)


def apply_reqs(j, rq, text_flags):
    j["r"] = None
    if not rq or not rq.get("ok"):
        return
    have = PROFILE[j["fam"]]
    gap = None
    if rq.get("y") is not None:
        gap = round(rq["y"] - have, 1)
    elif rq.get("jr"):
        gap = -1.0
    s = j["_raw"]
    if gap is not None:
        fit = 1 if gap <= 0 else 0 if gap <= 1 else -1 if gap <= 2 else -2 if gap <= 3 else -3
        if j["lv"] in ("student", "exec", "staff"):
            fit = min(fit, j["_ladj"])
        elif j["lv"] in ("coordinator", "junior"):
            fit = min(fit, 0)   # meeting a junior bar is no reason to rank it above his level
        s = s - j["_ladj"] + fit
    hit = [x for x in (text_flags.get("stack") or []) if x in HIS_STACK]
    if j["fam"] == "software":
        if not STACK.search(j["t"]):          # the title didn't already name his stack
            if any(x in ("java", "spring", "spring boot", "angular") for x in hit):
                s += 2      # the posting asks for Java / Spring / Angular
            elif len(hit) >= 2:
                s += 1      # some overlap
        if text_flags.get("cs") is False:
            s -= 2          # electrical / controls work under a software-sounding title
    j["s"] = max(0, min(CAP.get(j["fam"], 10), s))
    j["r"] = dict(y=rq.get("y"), yh=rq.get("yh"), q=rq.get("q") or "", h=have, gap=gap, jr=bool(rq.get("jr")), cs=text_flags.get("cs"),
                  fr=bool(text_flags.get("fr")), cl=bool(text_flags.get("cl")), stack=text_flags.get("stack") or [])


# ---------------------------------------------------------------- sources
def _get(url, **kw):
    r = requests.get(url, headers=kw.pop("headers", UA), timeout=kw.pop("timeout", 40), **kw)
    r.raise_for_status()
    return r


def row(c, t, l, u, age, src):
    return dict(c=c, t=html.unescape((t or "").strip()), l=html.unescape((l or "").strip()), u=u, age=age, src=src)


def workday(name, host, tenant, site, terms=("Syracuse", "Liverpool", "East Syracuse", "Clay, NY")):
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    hdr = {**UA, "Content-Type": "application/json", "Accept": "application/json"}
    out, seen = [], set()
    for q in terms:
        off, total = 0, 1
        while off < min(total, 600):
            d = requests.post(api, json={"limit": 20, "offset": off, "searchText": q, "appliedFacets": {}}, headers=hdr, timeout=40).json()
            total = d.get("total", 0) or 0
            for p in d.get("jobPostings", []):
                path = p.get("externalPath", "")
                if path in seen:
                    continue
                seen.add(path)
                r = row(name, p.get("title"), p.get("locationsText"), f"https://{host}/{site}{path}", _wd_days(p.get("postedOn")), name)
                r["hint"] = q != ""
                out.append(r)
            off += 20
    return out


def lever(name, tok):
    return [row(name, j.get("text"), (j.get("categories") or {}).get("location") or ", ".join((j.get("categories") or {}).get("allLocations") or []),
                j.get("hostedUrl"), None if not j.get("createdAt") else (TODAY - dt.date.fromtimestamp(j["createdAt"] / 1000)).days, name)
            for j in _get(f"https://api.lever.co/v0/postings/{tok}?mode=json").json()]


def greenhouse(name, tok):
    out = []
    for j in _get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs").json().get("jobs", []):
        r = row(name, j["title"], (j.get("location") or {}).get("name"), j["absolute_url"], None, name)
        r["api"] = f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{j.get('id')}"
        out.append(r)
    return out


def jobvite(name, tok):
    t = _get(f"https://jobs.jobvite.com/{tok}/jobs/positions", headers={**UA, "Accept": "text/html"}).text
    out = []
    for href, inner in re.findall(r'<a[^>]+href="(/' + re.escape(tok) + r'/job/[^"]+)"[^>]*>(.*?)</a>', t, re.S):
        parts = [x.strip() for x in re.split(r"<[^>]+>", inner) if x.strip()]
        out.append(row(name, parts[0] if parts else "", parts[-1] if len(parts) > 1 else "Syracuse, NY", "https://jobs.jobvite.com" + href, None, name))
    return out


def amazon():
    out, off, hits = [], 0, 1
    while off < min(hits, 1000):
        d = _get("https://www.amazon.jobs/en/search.json", params={"loc_query": "Syracuse, NY", "latitude": 43.0481, "longitude": -76.1474,
                                                                    "radius": "40km", "result_limit": 100, "offset": off, "sort": "recent"}).json()
        hits = d.get("hits", 0) or 0
        for j in d.get("jobs", []):
            loc = j.get("normalized_location") or j.get("location") or ""
            age = None
            try:
                age = (TODAY - dt.datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").date()).days
            except ValueError:
                pass
            out.append(row("Amazon", j.get("title"), loc, "https://www.amazon.jobs" + j.get("job_path", ""), age, "Amazon"))
        off += 100
        if not d.get("jobs"):
            break
    return out


def lockheed():
    url = "https://lockheedmartin.eightfold.ai/api/pcsx/search"
    hdr = {**UA, "Accept": "application/json"}
    first = _get(url, params={"domain": "lockheedmartin.com", "query": "", "location": "Syracuse, NY", "start": 0, "num": 10,
                              "sort_by": "timestamp"}, headers=hdr).json()["data"]
    pages = [first]
    total = min(first.get("count", 0) or 0, 600)

    def page(start):
        return _get(url, params={"domain": "lockheedmartin.com", "query": "", "location": "Syracuse, NY", "start": start, "num": 10,
                                 "sort_by": "timestamp"}, headers=hdr).json()["data"]
    with cf.ThreadPoolExecutor(4) as ex:
        pages += list(ex.map(page, range(10, total, 10)))
    out = []
    for d in pages:
        for p in d.get("positions", []):
            locs = p.get("locations") or []
            here = [x for x in locs if AREA.search(x)]
            remote_ny = [x for x in locs if re.match(r"virtual \w+, ny", x, re.I)]
            if not here and not remote_ny:
                continue
            age = (TODAY - dt.date.fromtimestamp(p["postedTs"])).days if p.get("postedTs") else None
            out.append(row("Lockheed Martin", p.get("name"), (here or ["Remote (New York)"])[0],
                           f"https://lockheedmartin.eightfold.ai/careers/job/{p.get('id')}", age, "Lockheed Martin"))
    return out


NY_COUNTIES = {"Onondaga", "Oswego", "Cayuga", "Madison", "Cortland"}


def statejobs():
    t = _get("https://statejobs.ny.gov/public/vacancyTable.cfm", timeout=60).text
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        m = re.search(r"vacancyDetailsView\.cfm\?id=(\d+)", r)
        if not m or len(cells) < 6 or cells[-1] not in NY_COUNTIES:
            continue
        age = None
        try:
            age = (TODAY - dt.datetime.strptime(cells[3], "%m/%d/%y").date()).days
        except (ValueError, IndexError):
            pass
        out.append(row("New York State · " + cells[5][:60].split(",")[0], cells[1], cells[-1] + " County, NY",
                       f"https://statejobs.ny.gov/public/vacancyDetailsView.cfm?id={m.group(1)}", age, "New York State"))
    return out


LI_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_QUERIES = [
    "software engineer", "software developer", "java developer", "full stack developer", "angular", "spring boot",
    "backend engineer", "frontend developer", "web developer", "application developer", ".net developer",
    "devops engineer", "cloud engineer", "data engineer", "systems engineer", "test engineer", "automation engineer",
    "business analyst", "systems analyst", "data analyst", "technical project manager", "project manager",
    "program manager", "product manager", "product owner", "scrum master", "implementation specialist",
    "solutions engineer", "IT manager", "IT project", "technical consultant",
    "logistics manager", "logistics coordinator", "transportation manager", "fleet manager", "dispatch",
    "operations manager", "director of operations", "supply chain", "distribution center", "warehouse manager",
    "operations supervisor", "area manager", "event manager", "event coordinator", "process improvement",
    "operations analyst", "general manager", "bilingual french", "computer science instructor",
]
LI_STATS = dict(requests=0, limited=0, cards=0, unique=0)


def linkedin(budget=720):
    """LinkedIn's public job search within 25 miles of Syracuse, last 30 days: the targeted queries, then broad
    sweeps by seniority (associate, mid-senior, director) for anything the queries didn't name."""
    out, seen = [], set()
    time.sleep(60)          # let LinkedIn cool off after the Montreal sweep that ran just before
    t0 = time.time()
    s = requests.Session()
    s.headers.update(UA)
    plan = [(q, {}, 100) for q in LI_QUERIES] + [("", {"f_E": e}, 1000) for e in ("4", "3", "5", "2")]
    for q, extra, depth in plan:
        for start in range(0, depth, 10):
            if time.time() - t0 > budget:
                LI_STATS["unique"] = len(out)
                return out
            r = None
            for wait in (0, 30):
                time.sleep(wait)
                LI_STATS["requests"] += 1
                r = s.get(LI_URL, params={"keywords": q, "location": "Syracuse, New York, United States", "distance": 25,
                                          "f_TPR": "r2592000", "start": start, **extra}, timeout=40)
                if r.status_code != 429:
                    break
                LI_STATS["limited"] += 1
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
                LI_STATS["cards"] += 1
                if urn.group(1) in seen:
                    continue
                seen.add(urn.group(1))
                fresh += 1
                clean = lambda x: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()
                age = None
                if when:
                    try:
                        age = (TODAY - dt.date.fromisoformat(when.group(1))).days
                    except ValueError:
                        pass
                rw = row(clean(comp.group(1)), clean(title.group(1)), clean(loc.group(1) if loc else ""),
                         f"https://www.linkedin.com/jobs/view/{urn.group(1)}/", age, "LinkedIn")
                rw["net"] = "LinkedIn"
                out.append(rw)
            if len(cards) < 10 or not fresh:
                break
            time.sleep(2.5)
        time.sleep(1.5)
    LI_STATS["unique"] = len(out)
    return out


BOARDS = [
    (lambda: workday("Micron", "micron.wd1.myworkdayjobs.com", "micron", "External"), "Micron"),
    (lambda: workday("Carrier", "carrier.wd5.myworkdayjobs.com", "carrier", "jobs"), "Carrier"),
    (lambda: workday("M&T Bank", "mtb.wd5.myworkdayjobs.com", "mtb", "MTB"), "M&T Bank"),
    (lambda: workday("KeyBank", "keybank.wd5.myworkdayjobs.com", "keybank", "External_Career_Site"), "KeyBank"),
    (lambda: workday("Le Moyne College", "agilitas.wd503.myworkdayjobs.com", "agilitas", "LMC", terms=("",)), "Le Moyne College"),
    (lambda: lever("JMA Wireless", "jmawireless"), "JMA Wireless"),
    (lambda: greenhouse("Terakeet", "terakeet"), "Terakeet"),
    (lambda: jobvite("SRC Inc.", "src-inc"), "SRC Inc."),
    (amazon, "Amazon"),
    (lockheed, "Lockheed Martin"),
    (statejobs, "New York State"),
]
ALIASES = {"src": "SRC Inc.", "src inc": "SRC Inc.", "jma": "JMA Wireless", "jma wireless": "JMA Wireless",
           "micron": "Micron", "micron technology": "Micron", "carrier": "Carrier", "lockheed martin": "Lockheed Martin",
           "amazon": "Amazon", "m&t bank": "M&T Bank", "keybank": "KeyBank", "le moyne college": "Le Moyne College",
           "terakeet": "Terakeet"}
RECRUITERS = re.compile(r"robert half|insight global|teksystems|kforce|randstad|adecco|aerotek|actalent|manpower|"
                        r"apex systems|cybercoders|jobot|dice|staffing|recruit|talent|hire|search group|"
                        r"lensa|jobs via|clickjob|hiring|careers?\b|motion recruitment|kelly services|express employment|ssi people|axelon|"
                        r"people\b|consulting group|solutions inc|tech mahindra|infosys|cognizant|programmers\.io|brightpath", re.I)


def norm(c):
    c = re.sub(r"[^a-z0-9& ]+", " ", (c or "").lower())
    c = re.sub(r"\b(inc|llc|corp|corporation|co|company|ltd|the|usa|us)\b", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def in_area(j):
    l = j.get("l") or ""
    if AREA.search(l) or AREA.search(j["t"]):
        return True
    if re.search(r"remote", l, re.I) and re.search(r"new york|\bny\b", l, re.I):
        j["remote"] = True
        return True
    if j.get("hint") and (re.match(r"^\d+ locations", l, re.I) or not l):
        return True
    return False


def read_reqs(cands):
    try:
        cache = json.load(open(REQS_PATH, encoding="utf-8"))
    except Exception:
        cache = {}
    if cache.get("_v") != reqs.VERSION:
        cache = {}
    todo = [j for j in cands if j["u"] not in cache]
    stats = dict(read=0, cached=len(cands) - len(todo), failed=0)
    limited = [0]

    def one(j):
        try:
            text = reqs.description(j["u"], j.get("api"))
        except Exception as e:
            stats["failed"] += 1
            if "429" in str(e):
                limited[0] += 1
            return j["u"], None
        stats["read"] += 1
        r = reqs.parse(text, j["t"])
        r["fr"] = bool(re.search(r"\bfrench\b|bilingual \(?english", text, re.I))
        r["cl"] = bool(CLEAR.search(text))
        r["cs"] = bool(re.search(r"software|computer science|programming|\bcode\b|coding|developer|java|python|c\+\+|javascript|"
                                 r"typescript|\.net|c#|sql|git\b|api|cloud|devops|agile", text, re.I))
        r["stack"] = sorted({m.lower() for m in re.findall(r"\b(Java|Spring Boot|Spring|Angular|React|TypeScript|SQL|Python|AWS|Docker|"
                                                            r"Kubernetes|Microservices|C#|\.NET|Azure)\b", text)})[:8]
        return j["u"], r
    li = [j for j in todo if "linkedin.com" in j["u"]]
    rest = [j for j in todo if "linkedin.com" not in j["u"]]
    with cf.ThreadPoolExecutor(8) as ex:
        for u, r in ex.map(one, rest):
            if r is not None and r.get("ok"):
                cache[u] = r
    for j in li:
        if limited[0] >= 3:
            break
        u, r = one(j)
        if r is not None and r.get("ok"):
            cache[u] = r
        time.sleep(1.2)
    live = {j["u"] for j in cands}
    cache = {u: r for u, r in cache.items() if u in live}
    os.makedirs(os.path.dirname(REQS_PATH), exist_ok=True)
    json.dump(dict(cache, _v=reqs.VERSION), open(REQS_PATH, "w", encoding="utf-8"), indent=0, sort_keys=True, ensure_ascii=False)
    return cache, stats


MIN_SHOW = 4


def build(li_budget=720):
    raw, errors, got = [], [], {}
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(fn): label for fn, label in BOARDS}
        futs[ex.submit(linkedin, li_budget)] = "LinkedIn sweep"
        for f in cf.as_completed(futs):
            label = futs[f]
            try:
                rows = f.result()
                if label != "LinkedIn sweep":
                    got[label] = len([r for r in rows if in_area(dict(r))])
                raw.extend(rows)
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}")
                print(f"  ! syracuse {label} failed: {e}")
    boards = {norm(k): k for k in got}
    boards.update({k: v for k, v in ALIASES.items()})
    kept, dedupe, dropped = [], {}, 0
    for j in raw:
        j["t"] = re.sub(r"\s+", " ", j["t"] or "").strip()
        if not j["t"] or not re.match(r"https?://", j["u"] or ""):
            continue
        if not in_area(j):
            continue
        if j.get("net"):
            if RECRUITERS.search(j["c"] or ""):
                dropped += 1
                continue
            firm = boards.get(norm(j["c"]))
            if firm and got.get(firm, 0) > 0:
                dropped += 1
                continue   # read from the firm's own board already
        if not score(j):
            continue
        key = norm(j["c"]) + ":" + re.sub(r"[^a-z0-9]+", " ", j["t"].lower()).strip() + ":" + re.sub(r"[^a-z]+", "", (j["l"] or "").lower())[:12]
        prev = dedupe.get(key)
        if prev is None or (prev.get("net") and not j.get("net")):
            dedupe[key] = j
    kept = list(dedupe.values())

    cands = [j for j in kept if j["s"] >= 5]
    found, rstats = read_reqs(cands)
    for j in cands:
        rq = found.get(j["u"])
        apply_reqs(j, rq, rq or {})

    try:
        seen = json.load(open(SEEN_PATH, encoding="utf-8"))
    except Exception:
        seen = {}
    first_run = not seen
    for j in kept:
        seen.setdefault(j["u"], TODAY.isoformat())
        fs = dt.date.fromisoformat(seen[j["u"]])
        j["new"] = (not first_run) and fs == TODAY and (j["age"] is None or j["age"] <= 2)
        if j["age"] is None and not first_run:
            j["age"] = (TODAY - fs).days
    live = {j["u"] for j in kept}
    seen = {u: d for u, d in seen.items() if u in live or (TODAY - dt.date.fromisoformat(d)).days < 60}
    json.dump(seen, open(SEEN_PATH, "w", encoding="utf-8"), indent=0, sort_keys=True)

    kept.sort(key=lambda j: (-j["s"], j["age"] if j["age"] is not None else 999))
    jobs = [dict(s=j["s"], c=j["c"], cat=j["fam"], t=j["t"], l=j["l"] or ("Remote (New York)" if j.get("remote") else "Syracuse area"),
                 u=j["u"], a=j["age"], n=j["new"], m=not j.get("remote"), o=j.get("net") or "", g=FAMILY_NAME[j["fam"]],
                 lv=j["lv"], k=j["fam"], ad=PITCH[j["fam"]], r=j.get("r"), rm=bool(j.get("remote")))
            for j in kept if j["s"] >= MIN_SHOW]
    meta = dict(boards=len([b for b in got if b]), board_rows=sum(got.values()), errors=errors, net=dict(dropped=dropped, **LI_STATS),
                reqs=rstats, min=MIN_SHOW, profile=PROFILE, firms=len({j["c"] for j in jobs}), scanned=len(raw))
    print(f"syracuse: {len(raw)} rows read, {len(kept)} scored, {len(jobs)} shown; boards {got}; linkedin {LI_STATS}; reqs {rstats}")
    return dict(meta=meta, jobs=jobs, alive=sorted(live))


if __name__ == "__main__":
    import sys
    d = build(li_budget=int(sys.argv[1]) if len(sys.argv) > 1 else 600)
    from collections import Counter
    print(Counter(j["s"] for j in d["jobs"]), Counter(j["cat"] for j in d["jobs"]))
    for j in d["jobs"][:60]:
        r = j.get("r") or {}
        print(j["s"], "|", j["c"][:24].ljust(24), "|", j["t"][:62].ljust(62), "|", j["l"][:22], "| bar", r.get("y"), r.get("gap"))
