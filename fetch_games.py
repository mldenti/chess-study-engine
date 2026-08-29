#!/usr/bin/env python3
"""Pull finished games from Chess.com and Lichess into games/ as clean PGN.

Standard library only, so it runs anywhere including the local session VM.
Needs the chess hosts on the network allowlist.

Naming follows README.md: YYYYMMDD-NN-color-result.pgn, sequence per day,
with a -daily suffix for correspondence, filed under the PGN Date (start) tag.

Dedupe is by game id, taken from two places: the files already in games/ when
that folder exists, and the seen list in the state file.  Either alone is
enough, which is what lets the same script run on the Mac beside the folder and
in a cloud session that has no folder at all.

CHESS_ROOT, CHESS_GAMES and CHESS_STATE override the paths for a cloud run.

Usage:
  python3 tools/fetch_games.py --dry-run
  python3 tools/fetch_games.py --since 2026-08-26
  python3 tools/fetch_games.py --classes rapid,daily --max 20
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CHESS_ROOT") or os.path.dirname(HERE)
GAMES = os.environ.get("CHESS_GAMES") or os.path.join(ROOT, "games")
STATE = os.environ.get("CHESS_STATE") or os.path.join(HERE, "intake_state.json")

# Overridable so the repo can be public without carrying identifiers, and so a
# second account can be pointed at without editing the script.
CHESSCOM_USER = os.environ.get("CHESSCOM_USER", "YepOkayItsMitch")
LICHESS_USER = os.environ.get("LICHESS_USER", "gleichbleibend")
UA = "chess-study-engine/1.0 (personal study tool)"

CLASS_MAP = {  # lichess speed -> chess.com time_class vocabulary
    "correspondence": "daily", "classical": "rapid", "rapid": "rapid",
    "blitz": "blitz", "bullet": "bullet", "ultraBullet": "bullet",
}


def get(url, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if accept:
        req.add_header("Accept", accept)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(8 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(3)
                continue
            raise


def tag(pgn, name):
    m = re.search(r'^\[%s "([^"]*)"\]' % name, pgn, re.M)
    return m.group(1) if m else None


def game_key(pgn):
    """Stable identity for a PGN.

    Chess.com exports the same game with two different Link shapes depending on
    where you export from, so match the numeric id rather than the whole URL.
    Falls back to the timestamp plus both names for PGNs with no link at all.
    """
    blob = " ".join(filter(None, (tag(pgn, "Link"), tag(pgn, "Site"), tag(pgn, "GameId") or "")))
    m = re.search(r"chess\.com/.*?/(?:live|daily)/(\d+)", blob)
    if m:
        return "chesscom:" + m.group(1)
    m = re.search(r"lichess\.org/([A-Za-z0-9]{8})", blob)
    if m:
        return "lichess:" + m.group(1)
    gid = tag(pgn, "GameId")
    if gid:
        return "lichess:" + gid
    stamp = (tag(pgn, "UTCDate"), tag(pgn, "UTCTime"), tag(pgn, "White"), tag(pgn, "Black"))
    return "stamp:" + "|".join(x or "?" for x in stamp)


def existing_keys(state):
    """Ids already accounted for.

    Two sources, both used.  The files in games/ are authoritative when the
    folder is present.  The seen list in the state file carries the same
    information for a run that has no folder, which is the cloud case.  Reading
    both means a lost state file costs nothing on the Mac, and a missing folder
    costs nothing in the cloud.
    """
    keys = set(state.get("seen") or [])
    if os.path.isdir(GAMES):
        for fn in os.listdir(GAMES):
            if fn.endswith(".pgn"):
                k = game_key(open(os.path.join(GAMES, fn), encoding="utf-8", errors="replace").read())
                if k:
                    keys.add(k)
    return keys


def seed_sequences():
    """Highest NN already used per date, so a dry run numbers the same as a real one."""
    seq = {}
    for fn in os.listdir(GAMES) if os.path.isdir(GAMES) else []:
        m = re.match(r"^(\d{8})-(\d{2})-", fn)
        if m:
            seq[m.group(1)] = max(seq.get(m.group(1), 0), int(m.group(2)))
    return seq


def hero_view(pgn, hero_names):
    white = (tag(pgn, "White") or "").lower()
    color = "white" if white in hero_names else "black"
    res = tag(pgn, "Result")
    if res == "1/2-1/2":
        outcome = "draw"
    elif res in ("1-0", "0-1"):
        won = (res == "1-0") == (color == "white")
        outcome = "win" if won else "loss"
    else:
        outcome = "unfinished"
    return color, outcome


def filename_for(pgn, hero_names, time_class, seq):
    datestr = (tag(pgn, "Date") or "").replace(".", "")
    if not re.fullmatch(r"\d{8}", datestr):
        return None
    color, outcome = hero_view(pgn, hero_names)
    suffix = "-daily" if time_class == "daily" else ""
    seq[datestr] = seq.get(datestr, 0) + 1
    return "%s-%02d-%s-%s%s.pgn" % (datestr, seq[datestr], color, outcome, suffix)


def fetch_chesscom(since_epoch, classes, include_unrated=False):
    """Current and previous month archives, filtered to finished games."""
    out = []
    months = get("https://api.chess.com/pub/player/%s/games/archives" % CHESSCOM_USER.lower())
    for url in json.loads(months)["archives"][-2:]:
        data = json.loads(get(url))
        for g in data.get("games", []):
            if g.get("rules") != "chess":
                continue
            # Unrated Chess.com games are mostly "Play vs Coach", which allow
            # takebacks.  Their ACPL is not comparable to a real game and was
            # quietly contaminating the daily bucket until 29 Aug 2026.  The
            # lichess branch has always passed rated=true; this is the same
            # filter, applied on the side that was missing it.
            if not include_unrated and not g.get("rated"):
                continue
            if classes and g.get("time_class") not in classes:
                continue
            if g.get("end_time", 0) <= since_epoch:
                continue
            out.append({
                "pgn": g["pgn"], "source": "chess.com",
                "time_class": g.get("time_class"), "end": g.get("end_time", 0),
                "url": g.get("url"),
            })
    return out


def fetch_lichess(since_epoch, classes):
    url = ("https://lichess.org/api/games/user/%s?since=%d&pgnInJson=true"
           "&clocks=false&evals=false&opening=true&rated=true"
           % (LICHESS_USER, since_epoch * 1000))
    body = get(url, accept="application/x-ndjson")
    out = []
    for line in body.splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        if g.get("variant") != "standard" or g.get("status") in ("created", "started"):
            continue
        tc = CLASS_MAP.get(g.get("speed"), g.get("speed"))
        if classes and tc not in classes:
            continue
        out.append({
            "pgn": g["pgn"], "source": "lichess",
            "time_class": tc, "end": int(g.get("lastMoveAt", 0) / 1000),
            "url": "https://lichess.org/%s" % g.get("id"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD; overrides the saved state")
    ap.add_argument("--classes", default="rapid,blitz,daily",
                    help="comma separated: rapid, blitz, bullet, daily.  'all' for no filter")
    ap.add_argument("--max", type=int, default=0,
                    help="process at most N games this run, oldest first; the rest wait for the next run")
    ap.add_argument("--include-unrated", action="store_true",
                    help="also take unrated games, which on Chess.com means Play vs Coach; their ACPL is not comparable because takebacks are allowed")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    classes = None if a.classes == "all" else set(a.classes.split(","))
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    if a.since:
        since = int(datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    else:
        since = int(state.get("last_end", 0)) or int(time.time()) - 86400 * 3

    games = []
    for name, fn in (("chess.com", fetch_chesscom), ("lichess", fetch_lichess)):
        try:
            got = (fetch_chesscom(since, classes, a.include_unrated)
                   if name == "chess.com" else fn(since, classes))
            print("%-10s %d new" % (name, len(got)), file=sys.stderr)
            games += got
        except Exception as e:
            print("%-10s FAILED: %s" % (name, e), file=sys.stderr)

    games.sort(key=lambda g: g["end"])
    deferred = []
    if a.max and len(games) > a.max:
        # Oldest first, so a backlog drains in order.  Taking the NEWEST n and
        # then advancing last_end past the rest would skip the older games
        # permanently, which is exactly the wrong failure on a heavy night.
        deferred = games[a.max:]
        games = games[:a.max]

    os.makedirs(GAMES, exist_ok=True)
    seen = existing_keys(state)
    seq = seed_sequences()
    hero_names = {CHESSCOM_USER.lower(), LICHESS_USER.lower(), "uffishgalumpher"}
    written, skipped = [], 0
    for g in games:
        key = game_key(g["pgn"])
        if key and key in seen:
            skipped += 1
            continue
        fn = filename_for(g["pgn"], hero_names, g["time_class"], seq)
        if not fn:
            print("  no usable Date tag, skipping %s" % g["url"], file=sys.stderr)
            continue
        path = os.path.join(GAMES, fn)
        if a.dry_run:
            print("  would write %s  (%s, %s)" % (fn, g["time_class"], g["url"]))
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(g["pgn"].rstrip() + "\n")
            print("  wrote %s" % fn)
        if key:
            seen.add(key)
        written.append({"file": fn, "url": g["url"], "time_class": g["time_class"], "end": g["end"]})

    if games and not a.dry_run:
        # Advance even when everything was a duplicate, so the window moves and
        # the archive scan does not re-offer the same games forever.  Never
        # advance past a game deferred by --max.
        cutoff = max(g["end"] for g in games)
        if deferred:
            cutoff = min(cutoff, min(g["end"] for g in deferred) - 1)
        state["last_end"] = max(int(state.get("last_end") or 0), cutoff)
        state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["seen"] = sorted(seen)
        json.dump(state, open(STATE, "w"), indent=1)

    if deferred:
        print("%d game%s left for the next run (--max %d)"
              % (len(deferred), "" if len(deferred) == 1 else "s", a.max), file=sys.stderr)

    print("\n%d written, %d already present" % (len(written), skipped), file=sys.stderr)
    print(json.dumps(written, indent=1))


if __name__ == "__main__":
    main()
