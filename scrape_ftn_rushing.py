#!/usr/bin/env python3
"""Scrape FTN team rushing stats (offense + defense) into Supabase.

Data source: the statshub API that ftnfantasy.com/nfl/stats calls itself.
Only the free/ungated fields are returned; advanced metrics (DVOA, SUC%,
YBCO/YACO, STF%, EXP%) require a paid FTN account and are not available here.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests

import ftn_tables
import nfl_game_logs

API = "https://6u5we6fbxi.execute-api.us-east-1.amazonaws.com/Statshub/statshub"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SEASON = int(os.environ.get("FTN_SEASON", 2026))
TABLE = "nfl_rushing_team_stats"
# Snapshots are keyed by date, so stamp them in the league's timezone rather
# than the runner's. A GitHub runner is UTC, which would label an evening run
# with the next day's date and split one scrape across two keys.
TZ = ZoneInfo("America/New_York")

# The page sends a literal "Bearer undefined" for unauthenticated (free) access.
AUTH = os.environ.get("FTN_AUTH", "Bearer undefined")

FILTER = {
    "alignment": [], "belowFreezing": None, "beyondLine": None, "blitz": None,
    "condition": None, "coverage": [], "coverageType": None,
    "defensivePersonnel": [], "designedRun": None, "distance": [], "dome": None,
    "downs": [], "favorite": None, "firstRead": None, "insideFive": None,
    "insideTen": None, "location": [], "motion": [], "noHuddle": None,
    "offensivePersonnel": [], "opponents": [], "option": None,
    "outOfPocket": None, "playAction": None, "ppr": 1, "precipitation": None,
    "pressure": None, "quarters": [], "quickRelease": None, "redZone": None,
    "route": [], "runConcept": [], "scramble": None, "seasonType": "reg",
    "separationType": [], "separationYards": [], "shotgun": None,
    "situation": [], "sneak": None, "stackedBox": None, "teams": [],
    "trickPlay": None, "twoMinDrill": None, "weeks": [], "wind": None,
    "yardsToEndzone": None, "year": SEASON,
}


def keychain(service):
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:
        return None


def supabase_creds():
    url = os.environ.get("SUPABASE_URL") or keychain("nfl-rushing-supabase-url")
    key = os.environ.get("SUPABASE_KEY") or keychain("nfl-rushing-supabase-key")
    if not url or not key:
        sys.exit("Missing Supabase credentials (env SUPABASE_URL/SUPABASE_KEY "
                 "or keychain nfl-rushing-supabase-url / -key)")
    return url.rstrip("/"), key


def fetch(view):
    """view: 'team' = rushing offense, 'defense' = rushing defense."""
    r = requests.post(f"{API}/rushing/{view}", json=FILTER, timeout=45, headers={
        "Content-Type": "application/json",
        "Authorization": AUTH,
        "Origin": "https://ftnfantasy.com",
        "Referer": "https://ftnfantasy.com/",
        "User-Agent": UA,
    })
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or len(data) != 32:
        raise RuntimeError(f"{view}: expected 32 team rows, got {type(data).__name__} "
                           f"len={len(data) if hasattr(data,'__len__') else '?'}")
    return data


def shape(rows, side, scraped, iq):
    """Merge statshub base volume stats with the Stats iQ advanced tables.

    NOTE: aybco + ayaco does NOT equal ypc. The statshub attempt universe and
    the Stats iQ one differ (~0.9 yds/att on average, inconsistent sign), so
    ypc is always computed from statshub attempts/yards and never derived.
    """
    adv = iq["off_rush"] if side == "offense" else iq["def_rush"]
    ovw = iq["off_ovw"] if side == "offense" else iq["def_ovw"]
    tempo = iq["tempo"] if side == "offense" else {}
    out = []
    for r in rows:
        att = r.get("attempts") or 0
        yds = r.get("rushingYards") or 0
        row = {
            "season": SEASON,
            "scraped_on": scraped.isoformat(),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "side": side,
            "team": r["team"],
            "games": r.get("games"),
            "attempts": att,
            "rushing_yards": yds,
            "ypc": round(yds / att, 4) if att else None,
            "rushing_tds": r.get("rushingTouchdowns"),
            "first_downs": r.get("firstDowns"),
            "fumbles": r.get("fumbles"),
            "fumbles_lost": r.get("fumblesLost"),
            "long_run": r.get("longRun"),
            "rushing_snaps": r.get("rushingSnaps"),
        }
        t = r["team"]
        for src in (adv.get(t, {}), ovw.get(t, {}), tempo.get(t, {})):
            for k, v in src.items():
                row.setdefault(k, v)
        if row.get("ply_gm") is None:
            # FTN publishes no defensive tempo table, but plays faced per game
            # falls out of the overview: total yards / yards-per-play / games.
            # Validated against the offense tempo table (KC 72.2 derived vs 72.5
            # published; YD/PLY is rounded to 1dp, worth ~0.4% of error).
            py, ry, ypp, g = (row.get("pass_yd"), row.get("rush_yd"),
                              row.get("yd_ply"), row.get("games"))
            if all(v for v in (py is not None and py + (ry or 0), ypp, g)):
                row["ply_gm"] = round((py + (ry or 0)) / ypp / g, 2)
                row["ply_gm_derived"] = True
        out.append(row)
    return out


def verify(off, dfn):
    """League totals must reconcile: every carry is one team's and another's allowed."""
    oa, da = sum(r["attempts"] for r in off), sum(r["attempts"] for r in dfn)
    oy, dy = sum(r["rushing_yards"] for r in off), sum(r["rushing_yards"] for r in dfn)
    if oa != da or oy != dy:
        raise RuntimeError(f"integrity check failed: attempts {oa} vs {da}, yards {oy} vs {dy}")
    return oa, oy


def normalize(rows):
    """PostgREST requires every object in a batch to carry identical keys.
    Defense rows have no tempo fields (FTN publishes no defensive tempo table),
    so pad every row to the union of keys."""
    keys = set()
    for r in rows:
        keys |= r.keys()
    return [{k: r.get(k) for k in sorted(keys)} for r in rows]


def push(url, key, rows, table=TABLE, on_conflict="season,scraped_on,side,team"):
    if not rows:
        return
    r = requests.post(
        f"{url}/rest/v1/{table}",
        params={"on_conflict": on_conflict},
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        data=json.dumps(rows), timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"supabase write to {table} failed {r.status_code}: {r.text[:400]}")


def main():
    scraped = datetime.now(TZ).date()
    iq = ftn_tables.fetch_all(SEASON)
    print(f"stats-iq tables: " + ", ".join(f"{k}={len(v)}" for k, v in iq.items()))
    off = shape(fetch("team"), "offense", scraped, iq)
    dfn = shape(fetch("defense"), "defense", scraped, iq)
    att, yds = verify(off, dfn)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] season {SEASON}: 32 offense + 32 defense rows; "
          f"league totals {att} att / {yds} yds; integrity OK")

    if "--dry-run" in sys.argv:
        print(json.dumps(off[:2] + dfn[:2], indent=2))
        return
    url, key = supabase_creds()
    push(url, key, normalize(off + dfn))
    print(f"wrote 64 rows to {TABLE} for {scraped}")

    # per-game logs come from nflverse, which carries the opponent on every row
    games, players = nfl_game_logs.build(SEASON)
    push(url, key, games, "nfl_game_logs", "season,week,team")
    push(url, key, players, "nfl_rb_game_logs", "season,week,team,player")
    weeks = sorted({g["week"] for g in games})
    print(f"wrote {len(games)} team-games and {len(players)} player-games, weeks {weeks[0]}-{weeks[-1]}")


if __name__ == "__main__":
    main()
