# Position Book

Montreal buy-side, banking and markets openings, pulled from each firm's own hiring system and ranked every morning.

- `fetch.py` pulls, filters and scores postings, then writes `docs/index.html`.
- `template.html` is the page design.
- `data/seen.json` remembers when each posting first appeared, so new ones get flagged.
- `.github/workflows/daily.yml` runs it every day at 6 am Montreal time.
