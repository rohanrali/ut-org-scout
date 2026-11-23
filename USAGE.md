# UT Org Finder

Finds the official Instagram account for every UT Austin fraternity, sorority (all six councils) and a set of big student orgs: spirit groups, business frats, cultural orgs and club sports. Then it finds the officers each org publicly names on its own account, like social chair, events, external VP, PR or president, so you can pitch the org page and the right person together.

## Run it (Windows)
2. Double-click **RUN_ME.bat** and paste your Apify token when asked.
3. It takes 30–45 minutes. `ut_orgs_<date>.xlsx` opens at the end.

**Cost:** roughly $6–9 of Apify credit (about 1,000 account-search results, ~100 profiles, and older posts for orgs with no contact found yet). For a cheaper run, open Command Prompt in this folder and run `py org_finder.py --no-deep`.

**RESCORE_FREE.bat** rebuilds the spreadsheet from saved data for free.

## The spreadsheet
| Tab | What |
|---|---|
| **Summary** | counts, how it works, offer ideas |
| **Orgs** | one row per org, biggest first: Instagram, followers, match confidence, **best contact**, social chair, events/external, PR, president, recruitment, email in bio, tracking columns |
| **Contacts** | one row per officer handle, with the post or bio where the org named them and the exact text, so you can double-check |
| **Not found** | orgs with no confident account match; "Other possible accounts" lists what it saw |

**Match confidence:** High/Medium means the name matched plus UT/Texas/Austin signals, and accounts from other schools, nationals and alumni were filtered out. Low means check the profile before DMing.

## Adding or fixing orgs (orgs.csv)
Open `orgs.csv` in Excel. Each row is an org:
- add a row to include another org (name, type, chapter, aliases like `SigEp;Sig Ep`);
- type the handle in **instagram_handle** if you already know it, which skips the search for that org and makes it more accurate;
- delete rows for orgs you don't care about, which also saves credit.
Save it as CSV and run again. Steps already done in the last 12 hours are reused, not re-paid.

## Notes
- Contacts come only from the org's own public bio and posts (exec-board posts, "social chair: @x", "inquiries @x"). Some orgs don't list officers. For those, DM the org page and ask who handles socials.
- Greek list based on UT's councils (IFC, Panhellenic, NPHC, MGC, LPHC, TAPC). A few chapters may have changed status, and if so the tool just won't find an account.
- Bottles and comp tabs are for 21+ members only. For whole orgs, tie the offer to RSVPs, e.g. a reserved section or comp tab at 25+ RSVPs on your Posh link.
