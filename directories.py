"""Refresh the national industry directories -> data/cvca.json and data/pmac.json.

CVCA  (Canadian Venture Capital & Private Equity Association): every member firm with its website, city and type.
      Covers the small and mid-size PE, VC, family-office, private-debt and M&A-boutique shops across Canada.
PMAC  (Portfolio Management Association of Canada): every member portfolio-management firm. Names only (the
      directory publishes no websites), used to recognise small asset managers when they turn up on LinkedIn.

Réseau Capital (Quebec) is still read by rc_directory.py."""
import html
import json
import os
import re

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# CVCA member type -> our firm category. Types not listed (law firms, accountants, accelerators, NGOs) are skipped.
CVCA_CAT = {
    "Investor - Private Equity": "pe_vc",
    "Investor - Venture Capital": "pe_vc",
    "Investor - Corporate Venture Capital": "pe_vc",
    "Investor - Family Offices": "pe_vc",
    "Investor - Debt Provider": "pe_vc",
    "Investor - Investor": "pe_vc",
    "Investor - Corporate Investor": "pe_vc",
    "LP Investor - Fund of Funds": "pe_vc",
    "LP Investor - Limited Partners": "pension",
    "LP Investor - Public Pension": "pension",
    "LP Investor - Endowment/Foundation/Trust": "pension",
    "Investor - Asset Management/Mutual Fund": "am",
    "Service Provider - Financial Advisor": "advisory",   # M&A and capital-raising boutiques
}
PROV = {"ON": "ON", "QC": "QC", "BC": "BC", "AB": "AB", "MB": "MB", "SK": "SK", "NS": "NS", "NB": "NB", "NL": "NL", "PE": "PE"}


def cvca():
    s = requests.Session()
    s.headers.update(UA)
    page = s.get("https://www.cvca.ca/member-directory/", timeout=60).text
    nonce = re.search(r'"security":"([a-f0-9]+)"', page).group(1)
    r = s.post("https://www.cvca.ca/wp-admin/admin-ajax.php", timeout=120,
               data={"action": "handle_members_search_ajax", "security": nonce, "query": "cvcaMember=true"})
    r.raise_for_status()
    items = r.json()["data"]["items"]
    out = []
    for x in items:
        cat = CVCA_CAT.get(x.get("type"))
        if not cat or x.get("status") in ("Inactive", "Acquired") or x.get("hidden") == "True":
            continue
        if re.search(r"fund services|investor services|fund administration|administrat", x.get("name") or "", re.I):
            continue   # fund administrators: back-office employers, not front-office seats
        site = (x.get("website") or "").strip()
        dom = re.sub(r"^https?://", "", site).split("/")[0].lower().replace("www.", "") if site else ""
        out.append(dict(name=html.unescape(x["name"]).strip(), domain=dom or None, cat=cat, city=x.get("city") or "",
                        prov=PROV.get(x.get("region") or "", x.get("region") or ""), country=x.get("country") or "",
                        type=x.get("type"), staff=x.get("employeeCount") or ""))
    return out


def pmac():
    out, page = [], 1
    while True:
        r = requests.get("https://pmac.org/wp-json/wp/v2/firms", params={"per_page": 100, "page": page, "_fields": "title"},
                         headers=UA, timeout=60)
        if r.status_code != 200 or not r.json():
            break
        out += [html.unescape(x["title"]["rendered"]).strip() for x in r.json()]
        if page >= int(r.headers.get("X-WP-TotalPages", page)):
            break
        page += 1
    return sorted(set(out))


def main():
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    for name, fn in (("cvca", cvca), ("pmac", pmac)):
        path = os.path.join(ROOT, "data", name + ".json")
        try:
            rows = fn()
        except Exception as e:   # keep last week's copy if a directory is down
            print(f"{name} directory failed, keeping the previous copy: {e}")
            continue
        if len(rows) < 50 and os.path.exists(path):
            print(f"{name} returned only {len(rows)} rows, keeping the previous copy")
            continue
        json.dump(rows, open(path, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
        print(f"{name}: {len(rows)} firms")


if __name__ == "__main__":
    main()
