#!/usr/bin/env python3
"""Refresh nfl_injury_impact on its own, more often than the stats scrape.

Runs every two hours (.github/workflows/injuries.yml) because statuses move
daily -- Wednesday practice reports, Friday game designations, weekend
upgrades -- while the team stats only change after games.

Each run replaces today's snapshot rather than merging into it: an upsert
would leave a player who was upgraded since the last run still listed as
missing. One snapshot per day is kept for back-testing.
"""
import sys
from datetime import datetime

import requests

import injuries
import nfl_game_logs
from scrape_ftn_rushing import SEASON, TZ, push, supabase_creds

TABLE = "nfl_injury_impact"


def main():
    scraped = datetime.now(TZ).date()
    _, players = nfl_game_logs.build(SEASON)          # read-only: RB carry shares
    rows = injuries.build(SEASON, scraped, players)   # raises before any delete if ESPN is empty
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M} ET] {len(rows)} injured players with a share")
    if "--dry-run" in sys.argv:
        return

    url, key = supabase_creds()
    r = requests.delete(f"{url}/rest/v1/{TABLE}",
                        params={"season": f"eq.{SEASON}", "scraped_on": f"eq.{scraped.isoformat()}"},
                        headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"clearing today's snapshot failed {r.status_code}: {r.text[:400]}")
    push(url, key, rows, TABLE, "season,scraped_on,team,unit,player")
    print(f"replaced {scraped} snapshot in {TABLE}")


if __name__ == "__main__":
    main()
