"""
Fetches Fantasy Premier League data server-side (no CORS, no browser
involved) and writes two small files the "10 and Done" app reads directly,
same-origin, with no proxy required:

  players.json — id, name, and team for every player (powers the search box)
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

    # ---------- players.json: trimmed player + team list ----------
    players_out = {
        "elements": [
            {
                "id": e["id"],
                "first_name": e["first_name"],
                "second_name": e["second_name"],
                "web_name": e["web_name"],
                "team": e["team"],
            }
            for e in boot["elements"]
        ],
        "teams": [{"id": t["id"], "short_name": t["short_name"]} for t in boot["teams"]],
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
