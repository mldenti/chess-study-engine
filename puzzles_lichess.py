#!/usr/bin/env python3
"""Pull Lichess puzzle performance and track it over time.

Unlike everything else in the pipeline this needs a personal API token with
`puzzle:read`.  The token is read from, in order:

  $LICHESS_TOKEN
  the path in $LICHESS_TOKEN_FILE
  tools/lichess_token.txt

and is never printed, not even in an error.  If no token is found the script
exits 0 with {"status":"no_token"} so a nightly run can carry on without it.

Two products:

  tools/puzzle_history.json    append-only snapshots, one per run date, so
                               theme performance can be tracked over months
  out/puzzles-YYYYMMDD.md      a short note, written only when something moved

The history file is the point.  A single dashboard reading says which themes
are weak; a series says whether studying them worked.

Usage:
  python3 tools/puzzles_lichess.py --days 90
  python3 tools/puzzles_lichess.py --min-attempts 8 --out out
"""
import argparse, json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CHESS_ROOT") or os.path.dirname(HERE)
HISTORY = os.environ.get("PUZZLE_HISTORY") or os.path.join(HERE, "puzzle_history.json")
UA = "chess-study-engine/1.0 (personal study tool)"


def read_token():
    t = os.environ.get("LICHESS_TOKEN")
    if t and t.strip():
        return t.strip()
    for path in (os.environ.get("LICHESS_TOKEN_FILE"),
                 os.path.join(HERE, "lichess_token.txt")):
        if path and os.path.exists(path):
            t = open(path).read().strip()
            if t:
                return t
    return None


def get(url, token, accept=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Authorization": "Bearer " + token})
    if accept:
        req.add_header("Accept", accept)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # never echo the token, and never echo a body that might contain it
        sys.exit("lichess API returned %d for %s" % (e.code, url.split("?")[0]))


def snapshot(token, days):
    d = json.loads(get("https://lichess.org/api/puzzle/dashboard/%d" % days, token))
    g = d.get("global") or {}
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "days": days,
        "nb": g.get("nb", 0),
        "first_wins": g.get("firstWins", 0),
        "performance": g.get("performance"),
        "themes": {k: {"nb": v["results"]["nb"],
                       "first_wins": v["results"]["firstWins"],
                       "performance": v["results"].get("performance")}
                   for k, v in (d.get("themes") or {}).items()},
    }


def load_history():
    if os.path.exists(HISTORY):
        try:
            return json.load(open(HISTORY))
        except ValueError:
            return []
    return []


def rate(t):
    return round(100 * t["first_wins"] / t["nb"]) if t["nb"] else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-attempts", type=int, default=8,
                    help="ignore themes with fewer attempts; below this the numbers are noise")
    ap.add_argument("--activity", type=int, default=0,
                    help="also save the last N puzzle attempts as raw ndjson")
    ap.add_argument("--out", default=None, help="directory for the note and raw data")
    a = ap.parse_args()

    token = read_token()
    if not token:
        print(json.dumps({"status": "no_token"}))
        return

    snap = snapshot(token, a.days)
    hist = load_history()
    prev = hist[-1] if hist else None
    if prev and prev.get("date") == snap["date"]:
        hist[-1] = snap          # same day, replace rather than duplicate
    else:
        hist.append(snap)
    json.dump(hist, open(HISTORY, "w"), indent=1)

    out = a.out or os.path.join(ROOT, "out")
    os.makedirs(out, exist_ok=True)

    if a.activity:
        raw = get("https://lichess.org/api/puzzle/activity?max=%d" % a.activity, token)
        open(os.path.join(out, "puzzle-activity-%s.ndjson"
                          % snap["date"].replace("-", "")), "w").write(raw)

    # weakest themes with enough attempts to mean anything
    themes = {k: v for k, v in snap["themes"].items() if v["nb"] >= a.min_attempts}
    weak = sorted(themes.items(), key=lambda kv: kv[1]["performance"] or 0)[:6]

    # what moved since the previous snapshot
    moved = []
    if prev and prev.get("date") != snap["date"]:
        for k, v in themes.items():
            p = prev["themes"].get(k)
            if not p or not p.get("performance") or not v.get("performance"):
                continue
            delta = v["performance"] - p["performance"]
            if abs(delta) >= 25 and v["nb"] > p["nb"]:
                moved.append((k, delta, v["nb"] - p["nb"]))
        moved.sort(key=lambda x: -abs(x[1]))

    note = None
    if moved or not prev:
        L = ["# Puzzle performance %s" % snap["date"], "",
             "%d puzzles in the last %d days, %d%% first try, performance %s."
             % (snap["nb"], snap["days"],
                round(100 * snap["first_wins"] / snap["nb"]) if snap["nb"] else 0,
                snap["performance"]), ""]
        L += ["## Weakest themes", "",
              "| Theme | Attempts | First try | Performance |", "|---|---|---|---|"]
        for k, v in weak:
            L.append("| `%s` | %d | %d%% | %s |" % (k, v["nb"], rate(v), v["performance"]))
        L.append("")
        L.append("Overall performance is %s, so read these against that, not against"
                 % snap["performance"])
        L.append("each other.  A theme needs %d attempts before it appears here."
                 % a.min_attempts)
        if moved:
            L += ["", "## Moved since %s" % prev["date"], ""]
            for k, delta, n in moved:
                L.append("- `%s` %+d performance over %d new attempt%s"
                         % (k, delta, n, "" if n == 1 else "s"))
            L += ["", "Only themes with new attempts and a swing of 25 or more are listed.",
                  "A theme that moved without new attempts moved because the 90 day",
                  "window slid, not because anything changed."]
        L.append("")
        note = os.path.join(out, "puzzles-%s.md" % snap["date"].replace("-", ""))
        open(note, "w").write("\n".join(L))

    print(json.dumps({
        "status": "ok",
        "date": snap["date"],
        "puzzles": snap["nb"],
        "performance": snap["performance"],
        "first_try_pct": round(100 * snap["first_wins"] / snap["nb"]) if snap["nb"] else 0,
        "weakest": [{"theme": k, "nb": v["nb"], "rate": rate(v),
                     "performance": v["performance"]} for k, v in weak],
        "moved": [{"theme": k, "delta": d, "new_attempts": n} for k, d, n in moved],
        "snapshots": len(hist),
        "note": os.path.basename(note) if note else None,
    }, indent=1))


if __name__ == "__main__":
    main()
