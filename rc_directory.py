"""Refresh the Reseau Capital (Quebec PE/VC association) directory -> data/rc_sites.json.
Pulls every member and investor profile and finds each firm's website."""
import concurrent.futures as cf
import html
import json
import re
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
SKIP_NATURE = ("cabinet-juridique", "firme-comptable", "consultants-et-courtiers", "recrutement")
BAD = (r"reseaucapital|facebook|linkedin|twitter|instagram|youtube|google|cookiedatabase|mylittlebigweb|x\.com|vimeo|"
       r"wordpress|gravatar|w\.org|schema\.org|gstatic|cloudflare|jquery|wp\.com|apple\.com|mailto")


def all_posts(base):
    out, page = [], 1
    while True:
        r = requests.get(f"https://reseaucapital.com/wp-json/wp/v2/{base}", params={"per_page": 100, "page": page},
                         headers=UA, timeout=40)
        if r.status_code != 200 or not r.json():
            break
        out += r.json()
        if len(r.json()) < 100:
            break
        page += 1
    return out


def website(row):
    base, name, link = row
    try:
        t = requests.get(link, headers=UA, timeout=30).text.split("<footer")[0]
        for l in re.findall(r'href="(https?://[^"#]+)"', t):
            if not re.search(BAD, l, re.I):
                return [base, name, urlparse(l).netloc.lower().replace("www.", ""), ""]
    except Exception:
        pass
    return [base, name, None, ""]


def main():
    rows = []
    for base in ("membre", "investors"):
        for x in all_posts(base):
            if any(s in " ".join(x["class_list"]) for s in SKIP_NATURE):
                continue
            rows.append((base, html.unescape(x["title"]["rendered"]).strip(), x["link"]))
    with cf.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(website, rows))
    json.dump(res, open("data/rc_sites.json", "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print(len(res), "directory firms,", sum(1 for r in res if r[2]), "with a website")


if __name__ == "__main__":
    main()
