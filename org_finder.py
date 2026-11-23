#!/usr/bin/env python3
"""
UT Org Finder: finds the official Instagram account of each UT Austin fraternity, sorority and big
student org in orgs.csv, then pulls the officers each org PUBLICLY names on its own account
(social chair, events, external VP, PR, president...) so you know who to contact.

Pipeline
  1. Find handles  - Instagram account search per org ("sigma chi ut austin", then "texas sigma chi"...),
                     scored on name match + UT/Texas/Austin signals, other schools/nationals/alumni penalized.
                     Fill in instagram_handle in orgs.csv yourself to skip the search for that org.
  2. Profiles      - follower count, bio, link, recent posts for every matched account
  3. Officers      - @handles the org names next to a role in its bio or posts ("social chair @x",
                     "meet our exec board" posts, "inquiries: @x"), plus any email in the bio
  4. Deeper posts  - for orgs with no social/events/external contact yet, checks more of their posts
  5. Spreadsheet   - one row per org (sorted by followers), one row per officer, tracking columns

Usage
  python org_finder.py               full run
  python org_finder.py --no-deep     skip step 4 (cheaper)
  python org_finder.py --from-cache  rebuild the spreadsheet from saved data, no Apify cost
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
API = "https://api.apify.com/v2"
IG_ACTOR = "apify~instagram-scraper"
PROFILE_ACTOR = "apify~instagram-profile-scraper"


# ------------------------------------------------------------------- apify ----

def load_token() -> str:
    token = os.environ.get("APIFY_TOKEN")
    env = HERE / ".env"
    if not token and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("APIFY_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        sys.exit("No Apify token found. Delete .env and run RUN_ME.bat again.")
    return token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}   # header, so the token never appears in URLs or errors


def run_actor(token, actor, actor_input, label, quiet=False) -> list:
    if not quiet:
        print(f"  Apify: {label}")
    for attempt in range(6):
        r = requests.post(f"{API}/acts/{actor}/runs", headers=_auth(token), json=actor_input, timeout=60)
        if r.status_code == 402 and "memory" in r.text.lower():      # too many runs at once: wait and retry
            time.sleep(20)
            continue
        break
    if r.status_code == 401:
        sys.exit("Apify rejected the token (401). Delete the .env file and run again with your current token.")
    if r.status_code in (402, 403):
        sys.exit(f"Apify refused the run ({r.status_code}): credit or usage limit reached. Raise it in Billing. "
                 "Everything collected so far is saved; RESCORE_FREE.bat builds a spreadsheet from it.")
    if r.status_code >= 400:
        sys.exit(f"Apify error {r.status_code}: {r.text[:300]}")
    run = r.json()["data"]
    status = run["status"]
    while status in ("READY", "RUNNING"):
        time.sleep(8)
        status = requests.get(f"{API}/actor-runs/{run['id']}", headers=_auth(token), timeout=30).json()["data"]["status"]
    items = requests.get(f"{API}/datasets/{run['defaultDatasetId']}/items", headers=_auth(token),
                         params={"clean": "true", "format": "json"}, timeout=180).json()
    items = [i for i in (items if isinstance(items, list) else []) if isinstance(i, dict) and not i.get("error")]
    if not quiet:
        print(f"    {status}: {len(items)} items")
    return items


def run_many(token, jobs, workers=5, label="searches") -> dict:
    """jobs: {key: (actor, input)} -> {key: items}. Runs a few at a time."""
    out, done = {}, 0
    print(f"  Apify: {len(jobs)} {label} ({workers} at a time)")

    def one(k):
        actor, inp = jobs[k]
        try:
            return k, run_actor(token, actor, inp, k, quiet=True)
        except SystemExit:
            raise
        except Exception as e:                      # one failed search shouldn't kill the run
            print(f"    ! {k}: {e.__class__.__name__}")
            return k, []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, items in ex.map(one, list(jobs)):
            out[k] = items
            done += 1
            print(f"    {done}/{len(jobs)} done", end="\r")
    print()
    return out


def cached(name, fn, from_cache):
    path = CACHE / f"{name}.json"
    if from_cache:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if path.exists() and time.time() - path.stat().st_mtime < 12 * 3600:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data:
            print(f"  (reusing {name} collected {int((time.time() - path.stat().st_mtime) / 60)} min ago)")
            return data
    data = fn()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


# --------------------------------------------------------------- org list ----

GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
         "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
         "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω"}


def compact(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def load_orgs(path):
    orgs = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = (r.get("org") or "").strip()
            if not name:
                continue
            aliases = [a.strip() for a in (r.get("aliases") or "").split(";") if a.strip()]
            words = name.lower().split()
            greek = "".join(GREEK[w] for w in words) if words and all(w in GREEK for w in words) else ""
            orgs.append({"org": name, "type": (r.get("type") or "").strip(), "chapter": (r.get("chapter") or "").strip(),
                         "aliases": aliases, "greek": greek,
                         "handle": (r.get("instagram_handle") or "").strip().lstrip("@").lower()})
    return orgs


def queries(o):
    n = o["org"]
    qs = [f"{n} ut austin", f"texas {n}"]
    if o["aliases"]:
        qs.append(f"{o['aliases'][0]} texas")
    qs.append(f"{n} utexas")
    return qs


# ---------------------------------------------------------------- scoring ----

OTHER_SCHOOLS = re.compile(r"\b(texas a&m|tamu|aggies?|baylor|tcu|smu|texas state|txst|texas tech|ttu|utsa|ut dallas|utd|utep|"
                           r"ut arlington|uta|ut tyler|utrgv|rio grande|u of h|uh|university of houston|rice university|unt|"
                           r"north texas|sam houston|stephen f\.? austin|sfa|oklahoma|ou|lsu|alabama|arkansas|ole miss|georgia|"
                           r"florida|michigan|usc|ucla|texas southern|prairie view|tarleton|lamar|incarnate word|"
                           r"st\.? edward'?s|huston[- ]tillotson|acc|austin community college)\b")
UT_SIGNALS = re.compile(r"(ut austin|utaustin|\but\b|u\.t\.|utexas|university of texas|\btexas\b|austin|longhorn|hook ?em|"
                        r"🤘|forty acres|40 acres|west campus)")
NATIONAL = re.compile(r"(national|headquarters|\bhq\b|international|alumni|alumnae|foundation|\bihq\b|"
                      r"housing corp|mothers'? club|parents)")


ALL_NAMES: list[str] = []      # compact names of every org in the list (filled in main)


def score_candidate(o, prof) -> tuple[int, list]:
    user = (prof.get("username") or "").lower()
    full = (prof.get("fullName") or "").lower()
    bio = (prof.get("biography") or "").lower()
    text = f"{full} {bio}"
    why, s = [], 0
    names = [compact(o["org"])] + [compact(a) for a in o["aliases"] if len(compact(a)) >= 3]
    if any(n and (n in compact(user) or n in compact(full)) for n in names):
        s += 4
        why.append("name match")
    elif o["greek"] and o["greek"] in (full + bio).replace(" ", ""):
        s += 4
        why.append("Greek letters match")
    elif compact(o["org"])[:6] and compact(o["org"])[:6] in compact(user + full + bio):
        s += 1
        why.append("partial name")
    if UT_SIGNALS.search(text) or re.search(r"(ut|texas|tx|austin|longhorn)", user):
        s += 3
        why.append("UT/Texas/Austin")
    if o["chapter"] and len(o["chapter"]) > 3 and o["chapter"].lower() in text:
        s += 2
        why.append(f"chapter name ({o['chapter']})")
    if OTHER_SCHOOLS.search(text) or re.search(r"(tamu|baylor|tcu|smu|txst|ttu|utsa|utd|unt|uh)", user):
        s -= 5
        why.append("mentions another school")
    if NATIONAL.search(text) or re.search(r"(hq|national|alumni|alum)", user):
        s -= 3
        why.append("national/alumni account")
    mine = compact(o["org"])
    parts = [compact(user), compact(full)]
    if any(len(n) > len(mine) and mine in n and any(n in x for x in parts) for n in ALL_NAMES):
        s -= 6                                       # e.g. an Alpha Phi Alpha account when looking for Alpha Phi
        why.append("belongs to a similarly named org")
    if (prof.get("followersCount") or 0) >= 300:
        s += 1
    return s, why


def confidence(score):
    return "High" if score >= 8 else "Medium" if score >= 6 else "Low" if score >= 4 else ""


# --------------------------------------------------------------- officers ----

ROLES = [   # (label, priority: lower = better person to pitch a party to, regex). Role words are required:
            # "our social with @zetatexas" or "📸 @photographer" must NOT count as officers.
    ("Social chair", 1, r"\bsocial\s*(chair(s|man|woman|person)?|director|vp|v\.p\.|coordinator|committee|exec|officer|"
                        r"head|lead)\b|\bsocial\s*[:\-–—]\s*(?=@)|\b(vp|vice[- ]president|director)\s*(of\s*)?social\b"),
    ("Events", 2, r"\b(events?|programming|party|parties|mixers?|activities)\s*(chair|director|vp|coordinator|lead|manager|head)\b|"
                  r"\b(vp|director)\s*(of\s*)?(events|programming)\b"),
    ("External / partnerships", 2, r"\bexternal\s*(vp|vice[- ]president|relations|affairs|director|chair)\b|\bvp\s*(of\s*)?external\b|"
                                   r"\b(partnerships?|sponsorships?|corporate relations)\s*(chair|director|vp|manager|lead|coordinator)\b|"
                                   r"\b(business\s*)?inquir(y|ies)\b|\bcontact\s*[:\-–—]?\s*(?=@)|\bdm\s*(?=@)"),
    ("PR / marketing", 3, r"\b(social media|public relations|pr|marketing|communications?|media)\s*(chair|director|vp|manager|lead|"
                          r"coordinator|officer)\b|\bvp\s*(of\s*)?(pr|marketing|communications?)\b|\bpr\s*[:\-–—]\s*(?=@)"),
    ("President", 4, r"(?<!vice\s)(?<!vice-)\bpres(ident)?\b"),
    ("Recruitment / rush", 5, r"\b(rush|recruitment|membership|new member)\s*(chair|director|vp|educator|coordinator|lead)\b|"
                              r"\bvp\s*(of\s*)?(recruitment|membership)\b|\b(rush|recruitment)\s*[:\-–—]\s*(?=@)"),
    ("Vice president", 6, r"\b(vice[- ]president|vp)\b"),
]
ROLE_RX = [(lab, pri, re.compile(rx, re.I)) for lab, pri, rx in ROLES]
HANDLE_RX = re.compile(r"@([A-Za-z0-9_.]{2,30})")
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def find_officers(text: str, own: str, source: str) -> list[dict]:
    """Pair each @handle with the closest role words around it in the same line."""
    found = []
    text = EMAIL_RX.sub(" ", text or "")
    for line in re.split(r"[\n•|]+", text):
        roles = [(m.start(), m.end(), lab, pri) for lab, pri, rx in ROLE_RX for m in rx.finditer(line)]
        if not roles:
            continue
        for hm in HANDLE_RX.finditer(line):
            h = hm.group(1).rstrip(".").lower()
            if h == own or len(h) < 2:
                continue
            best = None
            for st, en, lab, pri in roles:
                if en <= hm.start():
                    dist, ok = hm.start() - en, hm.start() - en <= 120      # "social chair: @x"
                else:
                    dist, ok = st - hm.end() + 15, 0 <= st - hm.end() <= 25  # "@x (social chair)"
                # the closest role wins (not the "best" role), so "President @a, Social chair @b" pairs correctly
                if ok and (best is None or (dist, pri) < (best[2], best[1])):
                    best = (lab, pri, dist)
            if best:
                found.append({"handle": h, "role": best[0], "priority": best[1], "source": source,
                              "context": line.strip()[:160]})
    return found


def posts_of(prof):
    return [p for p in (prof.get("latestPosts") or []) if isinstance(p, dict)]


# ------------------------------------------------------------------ main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orgs", default=str(HERE / "orgs.csv"))
    ap.add_argument("--from-cache", action="store_true")
    ap.add_argument("--no-deep", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    CACHE.mkdir(exist_ok=True)
    orgs = load_orgs(args.orgs)
    ALL_NAMES.extend(compact(o["org"]) for o in orgs)
    token = None if args.from_cache else load_token()
    print(f"{len(orgs)} orgs in {Path(args.orgs).name}")

    # 1. find handles: up to N search rounds, only for orgs still unmatched
    cands: dict[str, dict] = {}          # org -> {username: profile}
    for rnd in range(cfg["search_rounds"]):
        todo = {}
        for o in orgs:
            if o["handle"]:
                continue
            best = max((score_candidate(o, p)[0] for p in cands.get(o["org"], {}).values()), default=-99)
            qs = queries(o)
            if best < cfg["good_enough_score"] and rnd < len(qs):
                todo[f"{o['org']}||{qs[rnd]}"] = (IG_ACTOR, {"search": qs[rnd], "searchType": "user",
                                                             "searchLimit": cfg["results_per_search"],
                                                             "resultsType": "details", "resultsLimit": 1})
        if not todo:
            break
        print(f"Step 1: account search, round {rnd + 1} ({len(todo)} orgs)")
        res = cached(f"search_round{rnd + 1}", lambda: run_many(token, todo, cfg["parallel_runs"]) if todo else {},
                     args.from_cache)
        empty = sum(1 for v in res.values() if not v)
        if rnd == 0 and len(res) >= 8 and empty / len(res) > 0.8 and not args.from_cache:
            sys.exit(f"{empty} of {len(res)} Instagram searches came back empty, so something is off with the search "
                     "(Instagram may be blocking it right now). Stopping before spending more. Send Claude this message; "
                     "you can also fill instagram_handle in orgs.csv for the orgs you know and run again.")
        for key, items in res.items():
            org = key.split("||")[0]
            for p in items:
                if p.get("username"):
                    cands.setdefault(org, {})[p["username"].lower()] = p

    # pick best account per org
    picks = {}
    for o in orgs:
        if o["handle"]:
            picks[o["org"]] = {"handle": o["handle"], "conf": "Given", "why": "you provided it", "others": ""}
            continue
        scored = sorted(((score_candidate(o, p), u) for u, p in cands.get(o["org"], {}).items()),
                        key=lambda x: -x[0][0])
        if scored and confidence(scored[0][0][0]):
            (s, why), u = scored[0]
            others = [x[1] for x in scored[1:4] if x[0][0] >= 4]
            picks[o["org"]] = {"handle": u, "conf": confidence(s), "why": ", ".join(why), "others": ", ".join("@" + x for x in others)}
        else:
            picks[o["org"]] = {"handle": "", "conf": "Not found", "why": "", "others": ", ".join("@" + x[1] for x in scored[:3])}

    owner: dict[str, tuple[int, str]] = {}
    for o in orgs:
        pk = picks[o["org"]]
        if pk["handle"] and pk["conf"] != "Given":
            sc = score_candidate(o, cands[o["org"]][pk["handle"]])[0]
            prev = owner.get(pk["handle"])
            if prev and prev[0] >= sc:
                picks[o["org"]] = {"handle": "", "conf": "Not found", "why": "", "others": f"@{pk['handle']} (matched {prev[1]})"}
                continue
            if prev:
                picks[prev[1]] = {"handle": "", "conf": "Not found", "why": "", "others": f"@{pk['handle']} (matched {o['org']})"}
            owner[pk["handle"]] = (sc, o["org"])

    # 2. full profiles (bio, followers, ~12 latest posts) for every matched handle
    handles = sorted({p["handle"] for p in picks.values() if p["handle"]})
    print(f"Step 2: reading {len(handles)} org profiles")
    praw = cached("profiles", lambda: run_actor(token, PROFILE_ACTOR, {"usernames": handles}, f"{len(handles)} profiles")
                  if handles else [], args.from_cache)
    profiles = {(p.get("username") or "").lower(): p for p in (praw if isinstance(praw, list) else [])}
    for u, p in [(u, p) for c in cands.values() for u, p in c.items()]:
        profiles.setdefault(u, p)

    # 3. officers from bio + recent posts
    officers: dict[str, list] = {}
    for o in orgs:
        h = picks[o["org"]]["handle"]
        prof = profiles.get(h) or {}
        found = find_officers(prof.get("biography") or "", h, "bio")
        for p in posts_of(prof):
            found += find_officers(p.get("caption") or "", h, p.get("url") or "post")
        officers[o["org"]] = found

    # 4. deeper posts for orgs with no social/events/external contact
    if not args.no_deep:
        need = [o for o in orgs if picks[o["org"]]["handle"] and not any(f["priority"] <= 2 for f in officers[o["org"]])]
        jobs = {o["org"]: (IG_ACTOR, {"directUrls": [f"https://www.instagram.com/{picks[o['org']]['handle']}/"],
                                      "resultsType": "posts", "resultsLimit": cfg["deep_posts_per_org"]}) for o in need}
        print(f"Step 3: checking older posts of {len(jobs)} orgs with no social/events contact yet")
        deep = cached("deep_posts", lambda: run_many(token, jobs, cfg["parallel_runs"], "post pulls") if jobs else {},
                      args.from_cache)
        for org, items in deep.items():
            h = picks.get(org, {}).get("handle", "")
            for p in items:
                officers.setdefault(org, []).extend(find_officers(p.get("caption") or "", h, p.get("url") or "post"))

    # 5. spreadsheet
    print("Step 4: writing spreadsheet")
    out = Path(args.out) if args.out else HERE / f"ut_orgs_{datetime.now():%Y-%m-%d}.xlsx"
    write_excel(orgs, picks, profiles, officers, out)
    print(f"\nDone. Spreadsheet: {out}")


# ------------------------------------------------------------------ output ----

TRACK = {"DMed org?": "", "DMed contact?": "", "Replied?": "", "Offer": "", "Est. RSVPs": "", "Notes": ""}


def write_excel(orgs, picks, profiles, officers, out):
    rows, people = [], []
    for o in orgs:
        pk = picks[o["org"]]
        h = pk["handle"]
        prof = profiles.get(h) or {}
        bio = (prof.get("biography") or "").replace("\n", " ").strip()
        # dedupe officers: keep best role per handle
        best: dict[str, dict] = {}
        for f in officers.get(o["org"], []):
            if f["handle"] not in best or f["priority"] < best[f["handle"]]["priority"]:
                best[f["handle"]] = f
        offs = sorted(best.values(), key=lambda f: f["priority"])
        by_role = {}
        for f in offs:
            by_role.setdefault(f["role"], []).append("@" + f["handle"])
        top = offs[0] if offs else None
        emails = sorted(set(EMAIL_RX.findall(prof.get("biography") or "")))
        rows.append({
            "Org": o["org"], "Type": o["type"],
            "Instagram": f"@{h}" if h else "", "Followers": prof.get("followersCount") or "",
            "Match confidence": pk["conf"],
            "Best contact": f"@{top['handle']} ({top['role']})" if top else "",
            "Social chair": ", ".join(by_role.get("Social chair", [])[:3]),
            "Events / external": ", ".join((by_role.get("Events", []) + by_role.get("External / partnerships", []))[:3]),
            "PR / marketing": ", ".join(by_role.get("PR / marketing", [])[:3]),
            "President": ", ".join(by_role.get("President", [])[:2]),
            "Recruitment": ", ".join(by_role.get("Recruitment / rush", [])[:2]),
            "Email in bio": ", ".join(emails),
            "Link in bio": prof.get("externalUrl") or "",
            "Bio": bio,
            "Profile": f"https://www.instagram.com/{h}/" if h else "",
            "Why matched": pk["why"],
            "Other possible accounts": pk["others"],
            "Private": "yes" if (prof.get("private") or prof.get("isPrivate")) else "",
            **TRACK,
        })
        for f in offs:
            people.append({"Org": o["org"], "Type": o["type"], "Role": f["role"], "Handle": "@" + f["handle"],
                           "Profile": f"https://www.instagram.com/{f['handle']}/",
                           "Where the org named them": "bio" if f["source"] == "bio" else f["source"],
                           "Context": f["context"], **TRACK})

    df = pd.DataFrame(rows)
    df["_f"] = pd.to_numeric(df["Followers"], errors="coerce").fillna(-1)
    found = df[df["Instagram"] != ""].sort_values("_f", ascending=False).drop(columns="_f")
    missing = df[df["Instagram"] == ""].drop(columns="_f")
    pdf = pd.DataFrame(people)
    n_contact = int((found["Best contact"] != "").sum())

    summary = pd.DataFrame({"": [
        "Orgs in list", "Instagram account found", "…with a named contact (social chair, events, etc.)", "Officer handles found",
        "Not found", "", "Run date", "How contacts are found", "Match confidence", "Offer ideas"], "Value": [
        len(df), len(found), n_contact, len(pdf), len(missing), "", datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Only @handles the org itself lists next to a role in its own bio or posts (e.g. 'social chair: @x', "
        "exec-board intro posts, 'inquiries @x'). Check the Context column before messaging.",
        "High/Medium = name + UT signals match. Low = check the profile before DMing. Given = you filled it in orgs.csv.",
        "Pitch the org account and the social chair together. Tie the offer to verified RSVPs (e.g. a table or comp tab "
        "at 25+ RSVPs on your Posh link). Bottles/comp tabs only for 21+ members."]})

    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        found.to_excel(xw, sheet_name="Orgs", index=False)
        (pdf if not pdf.empty else pd.DataFrame(columns=["Org", "Role", "Handle"])).to_excel(
            xw, sheet_name="Contacts", index=False)
        missing.to_excel(xw, sheet_name="Not found", index=False)
        _format(xw)


def _format(xw):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    fill = PatternFill("solid", fgColor="BF5700")
    widths = {"Bio": 50, "Context": 60, "Value": 100, "": 42, "Why matched": 30, "Other possible accounts": 30, "Org": 28}
    for ws in xw.book.worksheets:
        if ws.title != "Summary":
            ws.freeze_panes = "B2"
        heads = [c.value for c in ws[1]]
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = fill
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for i, h in enumerate(heads, 1):
            col = get_column_letter(i)
            w = widths.get(h)
            if w is None:
                lens = [len(str(c.value)) for c in ws[col][:80] if c.value is not None]
                w = min(max(lens + [len(str(h))]) + 2, 34)
            ws.column_dimensions[col].width = w
            link = h in ("Profile", "Link in bio", "Where the org named them")
            for cell in ws[col][1:]:
                if h == "Followers":
                    cell.number_format = "#,##0"
                if link and isinstance(cell.value, str) and cell.value.startswith("http"):
                    cell.hyperlink = cell.value
                    cell.font = Font(color="0563C1", underline="single")
                if ws.title == "Summary":
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        if ws.max_row > 1 and ws.title != "Summary":
            ws.auto_filter.ref = ws.dimensions


if __name__ == "__main__":
    main()
