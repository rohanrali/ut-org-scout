# UT Org Scout

An entity-resolution tool that maps ~100 UT Austin student organizations (all six Greek councils plus spirit groups, business fraternities, cultural orgs and club sports) to their **official Instagram accounts**. It then extracts the officers each org **publicly names** on its own account (social chair, events, external VP, PR, president) so partnership pitches reach the right person.

## The problem

Searching "sigma chi" on Instagram returns national chapters, other schools, alumni pages and fan accounts. Picking the right one by hand for 100+ orgs is slow and error-prone, and officer contacts are buried in bios and exec-board posts.

## How it works

1. **Candidate search.** Runs several query variants per org (e.g. "sigma chi ut austin", "texas sigma chi", plus aliases from `orgs.csv`) in parallel.
2. **Match scoring.** Each candidate account is scored on name similarity plus UT/Texas/Austin signals. Accounts from other schools, nationals and alumni groups are penalized. Each pick gets a **High / Medium / Low confidence** label.
3. **Profile pull.** Gets follower count, bio, link and recent posts for every matched account.
4. **Officer extraction.** Regex-based parsing pulls `@handles` that appear next to a role in bios and posts ("social chair: @x", "meet our exec board", "inquiries @x"), plus any email in the bio.
5. **Deeper pass.** For orgs with no contact found yet, checks older posts.
6. **Report.** An Excel workbook with *Summary*, *Orgs* (one row per org, ranked by followers, best contact first), *Contacts* (each officer with the source post and exact text for verification) and *Not found* (with alternate candidates seen).

## Engineering notes

- Parallel API runs (`ThreadPoolExecutor`) cut wall-clock time across hundreds of account searches.
- Every step is cached. `--from-cache` rebuilds the report for free, and reruns within 12 hours skip completed steps.
- `orgs.csv` is the editable input: add orgs and aliases, or hard-code a known handle to skip its search.

## Tech

Python · pandas · requests · openpyxl · concurrent.futures · Apify REST API

## Quick start

```bash
pip install -r requirements.txt
echo APIFY_TOKEN=your_token_here > .env
python org_finder.py              # full run
python org_finder.py --no-deep    # skip the deeper post pass (cheaper)
python org_finder.py --from-cache # rebuild from saved data, no API cost
```

On Windows, double-click `RUN_ME.bat`. More detail is in [`USAGE.md`](USAGE.md).

## Data and privacy

Contacts come only from what each organization publishes on its own public account. Scraped data and outputs are git-ignored.
