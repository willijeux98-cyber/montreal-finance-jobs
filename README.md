# Position Book

Montreal buy-side, banking and markets openings, pulled from each firm's own hiring system and ranked every morning.

- `fetch.py` pulls, filters and scores postings, then writes `docs/index.html`.
- `template.html` is the page design.
- `data/seen.json` remembers when each posting first appeared, so new ones get flagged.
- `.github/workflows/daily.yml` runs it every day at 6 am Montreal time.

## Coverage
- `firms_seed.py`: hand-picked Montreal buy-side employers (pensions, PE, VC, secondaries, asset managers, banks, deal advisory, corporate M&A).
- `rc_directory.py`: every Réseau Capital member and investor with a website.
- `discover.py` + `clean_boards.py`: read each firm's site and careers pages, find its real job board (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, BambooHR, Workable, Recruitee, Rippling, Jobvite, Teamtailor, UKG...), drop portfolio-company boards. Firms with no job system get their careers page watched directly.
- `.github/workflows/weekly-discover.yml` re-runs discovery every Monday.
