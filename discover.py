"""Find each firm's real job board by reading its website and careers pages.
Writes data/boards.json. Re-run occasionally to pick up firms that change systems."""
import json, re, sys, concurrent.futures as cf
from urllib.parse import urljoin, urlparse
import requests
sys.path.insert(0, ".")
from firms_seed import SEED

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8"}
ATS = [
    ("workday", r"https?://([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("bamboohr", r"([a-z0-9-]+)\.bamboohr\.com"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com"),
    ("teamtailor", r"([a-z0-9-]+)\.teamtailor\.com"),
    ("rippling", r"ats\.rippling\.com/([A-Za-z0-9_-]+)"),
    ("jobvite", r"jobs\.jobvite\.com/([A-Za-z0-9_-]+)"),
    ("breezy", r"([a-z0-9-]+)\.breezy\.hr"),
    ("pinpoint", r"([a-z0-9-]+)\.pinpointhq\.com"),
    ("dayforce", r"jobs\.dayforcehcm\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("ultipro", r"recruiting2?\.ultipro(?:\.ca)?\.com/([A-Z0-9]+)/JobBoard/([0-9a-f-]{36})"),
    ("icims", r"(careers-[a-z0-9-]+\.icims\.com)"),
    ("taleo", r"([a-z0-9-]+\.taleo\.net)"),
    ("successfactors", r"(career\d*\.successfactors\.(?:com|eu))"),
    ("avature", r"([a-z0-9-]+\.avature\.net)"),
]
BAD_TOKENS = {"embed", "api", "v1", "js", "jobs", "www", "careers", "job_board", "static", "assets", "images", "app", "cdn"}
CAREER_HINT = re.compile(r"career|carri|emploi|jobs|join|recrut|work-with-us|work-at|opportunit|talent|nous-joindre|joignez", re.I)


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=12, allow_redirects=True)
        return r.url, r.text if r.status_code < 400 else ""
    except Exception:
        return url, ""


def scan(text):
    found = []
    for kind, pat in ATS:
        for m in re.finditer(pat, text):
            g = m.groups()
            key = g if len(g) > 1 else g[0]
            if isinstance(key, str) and key.lower() in BAD_TOKENS:
                continue
            found.append((kind, key))
    return found


def discover(firm):
    name, domain, cat = firm
    base = "https://" + (domain if domain.count(".") > 1 and not domain.startswith("www.") else "www." + domain)
    pages, found, careers = [], [], None
    final, home = get(base)
    if not home:
        final, home = get("https://" + domain)
    pages.append((final, home))
    found += scan(home)
    # career-ish links on the homepage, plus common paths
    links = set()
    for href in re.findall(r'href=["\']([^"\'#]+)["\']', home):
        if CAREER_HINT.search(href):
            links.add(urljoin(final, href))
    for path in ["/careers", "/en/careers", "/carrieres", "/fr/carrieres", "/careers/", "/jobs", "/emplois", "/en/about/careers", "/join-us"]:
        links.add(urljoin(final, path))
    for u in list(links)[:14]:
        if urlparse(u).netloc and urlparse(u).netloc.split(".")[-2] not in urlparse(final).netloc and "careers" not in urlparse(u).netloc:
            # external career link: scan the URL itself (often the ATS)
            found += scan(u)
        fu, t = get(u)
        if t:
            f2 = scan(t) + scan(fu)
            found += f2
            if careers is None and CAREER_HINT.search(fu) and len(t) > 2000:
                careers = fu
    uniq = []
    for f in found:
        if f not in uniq:
            uniq.append(f)
    return {"name": name, "domain": domain, "cat": cat, "boards": uniq, "careers": careers}


def main():
    firms = list(SEED)
    try:
        for base, name, dom, cl in json.load(open("data/rc_sites.json", encoding="utf-8")):
            if dom and not any(dom == f[1] for f in firms):
                firms.append((name, dom, "pe_vc"))
    except FileNotFoundError:
        pass
    with cf.ThreadPoolExecutor(16) as ex:
        res = list(ex.map(discover, firms))
    json.dump(res, open("data/boards.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    hit = [r for r in res if r["boards"]]
    print(f"{len(res)} firms scanned, {len(hit)} with a detectable job board, "
          f"{sum(1 for r in res if not r['boards'] and r['careers'])} with a careers page only")


if __name__ == "__main__":
    main()
