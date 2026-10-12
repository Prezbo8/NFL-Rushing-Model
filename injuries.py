"""Who is missing this week, and how much of their unit's production they carried.

One row per injured player whose absence moves a grade. `share` is that
player's season-to-date slice of his unit, so the page can shrink the grade
toward league average by the total missing:

  defense  share of the team's run stuffs + run disruptions   (FTN Stats iQ)
  OL       share of the team's offensive-line snaps           (nflverse snaps)
  RB       share of the team's running-back carries           (nflverse weekly)

Shares are season-to-date, so a player who has already missed games carries a
smaller share: the team stats partly reflect his absence already.

Status comes from ESPN's league-wide injury feed, which is current to the hour.
nflverse's injury file lags a week, which is why it is not used here.
Only Out, Doubtful and any Reserve list count; Questionable is ignored.
"""
import csv
import io
import re
from collections import defaultdict

import requests

import ftn_tables
from nfl_game_logs import ftn

ESPN = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
SNAPS = ("https://github.com/nflverse/nflverse-data/releases/download/"
         "snap_counts/snap_counts_{season}.csv")
OL_POS = {"T", "G", "C", "OL", "OT", "OG"}
RB_POS = {"RB", "FB", "HB"}
DEF_POS = {"DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "MLB", "CB", "DB", "S", "SAF", "FS", "SS"}


def missing(status):
    return status in ("Out", "Doubtful") or status.startswith(("Injured Reserve", "Reserve"))


def key(name):
    """'Will Anderson Jr.' -> 'will anderson' so FTN, ESPN and nflverse agree."""
    n = re.sub(r"[.'’]", "", name.lower())
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.replace("-", " ").split())


def espn_out():
    r = requests.get(ESPN, timeout=45, headers={"User-Agent": ftn_tables.UA})
    r.raise_for_status()
    out = []
    for t in r.json()["injuries"]:
        team = ftn_tables.TEAMS.get(t["displayName"])
        if not team:
            raise RuntimeError(f"espn: unmapped team {t['displayName']!r}")
        for x in t["injuries"]:
            if missing(x["status"]):
                a = x["athlete"]
                out.append((team, a["displayName"], a.get("position", {}).get("abbreviation", ""),
                            x["status"]))
    if not out:
        raise RuntimeError("espn: no Out/Doubtful/IR players listed at all")
    return out


def defense_shares(season):
    """(team, name key) -> share of team run stuffs + disruptions."""
    rows = {}
    for table, col in (("overview", "STF"), ("efficiency", "DISC")):
        r = requests.get(f"{ftn_tables.BFF}/rush-defense/tables/{table}/export.csv",
                         params={"season": season, "seasonType": "REG"},
                         headers={"User-Agent": ftn_tables.UA}, timeout=45)
        r.raise_for_status()
        for x in csv.DictReader(io.StringIO(r.text)):
            k = (ftn_tables.TEAMS[x["Team"]], key(x["Player"]))
            rows[k] = rows.get(k, 0) + (ftn_tables.num(x[col]) or 0)
    tot = defaultdict(float)
    for (team, _), v in rows.items():
        tot[team] += v
    return {k: v / tot[k[0]] for k, v in rows.items() if tot[k[0]]}


def ol_shares(season):
    """(team, name key) -> share of the team's offensive-line snaps (a starter ~0.2)."""
    r = requests.get(SNAPS.format(season=season), timeout=90)
    r.raise_for_status()
    snaps = defaultdict(float)
    for x in csv.DictReader(io.StringIO(r.text)):
        if x["game_type"] == "REG" and x["position"] in OL_POS:
            snaps[(ftn(x["team"]), key(x["player"]))] += float(x["offense_snaps"] or 0)
    tot = defaultdict(float)
    for (team, _), v in snaps.items():
        tot[team] += v
    return {k: v / tot[k[0]] for k, v in snaps.items() if tot[k[0]]}


def rb_shares(players):
    """(team, name key) -> share of the team's RB carries, from nfl_game_logs rows.
    QB and receiver runs are left out: the model is about running backs only."""
    car, tot = defaultdict(int), defaultdict(int)
    for p in players:
        if p["position"] in RB_POS:
            tot[p["team"]] += p["carries"]
            car[(p["team"], key(p["player"]))] += p["carries"]
    return {k: v / tot[k[0]] for k, v in car.items() if tot[k[0]]}


def build(season, scraped, players):
    hurt = espn_out()
    sources = (("defense", defense_shares(season), DEF_POS),
               ("ol", ol_shares(season), OL_POS),
               ("rb", rb_shares(players), RB_POS))
    out = []
    for team, name, pos, status in hurt:
        for unit, shares, positions in sources:
            s = shares.get((team, key(name)))
            if s and pos in positions:
                out.append({"season": season, "scraped_on": scraped.isoformat(),
                            "team": team, "unit": unit, "player": name, "position": pos,
                            "status": status, "share": round(s, 4)})
    return out


if __name__ == "__main__":
    import json
    from datetime import date
    import nfl_game_logs
    _, players = nfl_game_logs.build(2026)
    rows = build(2026, date.today(), players)
    rows.sort(key=lambda r: -r["share"])
    print(f"{len(rows)} injured players with a share")
    for r in rows[:25]:
        print(f"  {r['team']:4} {r['unit']:8} {r['share']:6.1%}  {r['player']} ({r['position']}) {r['status']}")
