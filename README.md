# Position Book

Every analyst-level seat in Canadian high finance, pulled from each firm's own hiring system, placed in its city, scored against one profile and ranked three times a day.

- `fetch.py` pulls, filters and scores postings, then writes `docs/index.html`.
- `template.html` is the page design (light, one page: hero, city picker, seat filters, the list, the firm map, the pipeline).
- `data/seen.json` remembers when each posting first appeared, so new ones get flagged.
- `.github/workflows/daily.yml` runs it three times a day (morning, midday and evening editions, Montreal time).

## What makes the book
- **Seats:** private equity and VC, hedge funds, asset and pension investing, investment banking, sales and trading, credit, research, real assets, corporate development and deal advisory, quant and investment risk. Corporate and retail banking, operations, compliance and other support seats are dropped.
- **Level:** analyst level only. No manager, director or VP titles, no internships, and nothing whose posting asks for more than three years of experience.
- **Where:** anywhere in Canada. Each role gets a city (Toronto, Montréal, Vancouver, Calgary, Ottawa and every other city that turns up), or "multi-city / remote". Roles outside Canada are dropped.
- **Score:** out of 10, from the firm, the seat and what the posting itself asks for against the profile in `fetch.py` (`PROFILE`). 7 and above are listed.

## Coverage
- `firms_seed.py`: hand-picked Canadian employers with their head-office city (pensions, PE, VC, hedge funds, asset managers, banks and dealers, M&A boutiques, deal advisory, real estate investors, corporate M&A teams).
- `directories.py`: every CVCA member (PE, VC, family offices, private debt, M&A boutiques, with website and city) and every PMAC member firm (portfolio managers, used to recognise small asset managers).
- `rc_directory.py`: every Réseau Capital member and investor with a website.
- `discover.py` + `clean_boards.py`: read each firm's site and careers pages, find its real job board (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, BambooHR, Workable, Recruitee, Rippling, Jobvite, Teamtailor, UKG...), drop portfolio-company boards. Firms with no job system get their careers page watched directly.
- `net.py`: LinkedIn (entry and associate level, all of Canada), eFinancialCareers and the federal Job Bank, for firms the boards don't cover.
- `.github/workflows/weekly-discover.yml` refreshes the directories and re-runs discovery every Monday.

## Run it locally
```
pip install -r requirements.txt
python fetch.py            # a full build
PB_QUICK=1 python fetch.py # a short LinkedIn / eFinancialCareers / Job Bank sweep, for testing
```
