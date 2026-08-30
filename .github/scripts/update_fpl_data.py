"""
Fetches Fantasy Premier League data server-side (no CORS, no browser
involved) and writes two small files the "10 and Done" app reads directly,
same-origin, with no proxy required:

  players.json — every player's identity + season-to-date stats (position,
                 team, price, points, goals, assists, defensive contribution,
                 clean sheets, goals conceded, cards, saves) — powers both
                 the search box and the Player Data helper table
  goals.json   — every player's goals, broken down by calendar month,
                 computed from their match-by-match history

Run by the "Update FPL data" GitHub Action, on a schedule and on demand.
"""

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

BASE = "https://fantasy.premierleague.com/api"


def fetch_json(path, timeout=20):
    r = requests.get(f"{BASE}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_player_goals(pid):
    """Returns (pid, {month: goals}) for one player, or (pid, None) on failure."""
    try:
        data = fetch_json(f"/element-summary/{pid}/")
        months = defaultdict(int)
        for h in data.get("history", []):
            month = (h.get("kickoff_time") or "")[:7]  # "YYYY-MM"
            if len(month) == 7:
                months[month] += h.get("goals_scored", 0) or 0
        return pid, dict(months)
    except Exception:
        return pid, None


def main():
    boot = fetch_json("/bootstrap-static/")

    # ---------- players.json: player identity + season-to-date stats ----------
    players_out = {
        "elements": [
            {
                "id": e["id"],
                "first_name": e["first_name"],
                "second_name": e["second_name"],
                "web_name": e["web_name"],
                "team": e["team"],
                "position": e.get("element_type"),
                "price": e.get("now_cost", 0),  # tenths of a million, e.g. 95 = £9.5m
                "points": e.get("total_points", 0),
                "goals": e.get("goals_scored", 0),
                "assists": e.get("assists", 0),
                "defcon": e.get("defensive_contribution", 0),
                "clean_sheets": e.get("clean_sheets", 0),
                "goals_conceded": e.get("goals_conceded", 0),
                "yellow_cards": e.get("yellow_cards", 0),
                "red_cards": e.get("red_cards", 0),
                "saves": e.get("saves", 0),
            }
            for e in boot["elements"]
        ],
        "teams": [{"id": t["id"], "short_name": t["short_name"]} for t in boot["teams"]],
        "positions": [
            {"id": p["id"], "short_name": p["singular_name_short"]} for p in boot["element_types"]
        ],
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    with open("players.json", "w") as f:
        json.dump(players_out, f, separators=(",", ":"))
    print(f"Wrote players.json with {len(players_out['elements'])} players")

    # ---------- goals.json: monthly goals per player ----------
    player_ids = [e["id"] for e in boot["elements"]]
    goals = {}
    errors = []

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(fetch_player_goals, pid): pid for pid in player_ids}
        for future in as_completed(futures):
            pid, months = future.result()
            if months is not None:
                goals[str(pid)] = months
            else:
                errors.append(pid)

    goals_out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "player_count": len(goals),
        "errors": errors,
        "players": goals,
    }
    with open("goals.json", "w") as f:
        json.dump(goals_out, f, separators=(",", ":"))
    print(f"Wrote goals.json with {len(goals)} players, {len(errors)} fetch errors")


if __name__ == "__main__":
    main()
