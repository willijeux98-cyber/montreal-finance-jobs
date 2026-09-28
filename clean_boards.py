"""Post-process data/boards.json: drop portfolio-company boards, junk tokens and law firms; flag Quebec firms."""
import json, re

JUNK = {"staticfe", "resources", "stage", "hrttalentcommunity", "embed", "jobs", "careers", "static"}
NOT_BUYSIDE = re.compile(r"dentons|norton rose|fasken|mccarthy|osler|stikeman|borden ladner|\bblg\b|davies|lavery|"
                         r"gowling|torys|blake|langlois|miller thomson|de grandpr|robinson sheppard|\bbcf\b|"
                         r"chambre|montr[ée]al international|test\b|marsh\b", re.I)


CORP = (r"capital|ventures?|partners|fund|fonds|group|groupe|inc\b|invest|gestion|management|holdings?|"
        r"bank|banque|financ|equity|asset|placement|soci[ée]t[ée]|corporation|advis|conseil|labs?|studio|\bvc\b")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def related(token, name, domain):
    t = norm(token)
    hay = norm(name) + " " + norm(domain.split(".")[0])
    if not t:
        return False
    for w in re.findall(r"[a-z0-9]{4,}", re.sub(r"[^a-z0-9 ]", " ", (name + " " + domain.split(".")[0]).lower())):
        if w in t or t[:5] in w:
            return True
    return t[:4] in hay


def clean(path="data/boards.json", rc_path="data/rc_sites.json"):
    rows = json.load(open(path, encoding="utf-8"))
    try:
        members = {n for base, n, d, cl in json.load(open(rc_path, encoding="utf-8")) if base == "membre"}
    except FileNotFoundError:
        members = set()
    out = []
    for r in rows:
        if NOT_BUYSIDE.search(r["name"]) or re.search(r"safelinks|outlook|protection\.", r["domain"] or "", re.I):
            continue
        if (r["name"] in members and not re.search(CORP, r["name"], re.I) and len(r["name"].split()) <= 4
                and norm(r["domain"].split(".")[0]) not in norm(r["name"])):
            root = r["domain"].split(".")[0]
            r["name"] = root.upper() if len(root) <= 4 else root.title()  # "Patrick Michetti (EDC)" -> "EDC"
        keep = []
        for kind, key in r["boards"]:
            tok = key[0] if isinstance(key, list) else key
            if kind in ("icims", "taleo", "successfactors", "avature", "dayforce"):
                continue  # not machine-readable here; fall back to the careers page
            if norm(str(tok)) in JUNK or not related(str(tok), r["name"], r["domain"]):
                continue
            if kind == "workday" and re.fullmatch(r"[a-z]{2}-[a-z]{2}", str(key[2]).lower()):
                continue  # captured a locale instead of the site name
            if [kind, key] not in keep:
                keep.append([kind, key])
        r["boards"] = keep
        r["rc"] = r["name"] in members
        out.append(r)
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return out


if __name__ == "__main__":
    out = clean()
    print(len(out), "firms kept;", sum(1 for r in out if r["boards"]), "with boards;",
          sum(1 for r in out if not r["boards"] and r.get("careers")), "careers-page only")
    for r in out:
        if r["boards"]:
            print(f'  {r["name"][:34]:34} {r["boards"]}')
