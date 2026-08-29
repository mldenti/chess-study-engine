#!/usr/bin/env python3
"""Fold a cloud nightly run into the real folder.  Runs on the Mac.

A scheduled task cannot reach this folder, so `cloud_nightly.py` leaves its
output in the Claude project instead.  This unpacks that output here:

  games-YYYYMMDD.pgn        split back into games/, one file per game, using
                            each game's TargetFile tag, renumbered if that name
                            is taken
  YYYYMMDD-NN-analysis.md   into sessions/, sequence bumped if the day already
                            has one
  candidates-YYYYMMDD.csv   into puzzles/, still unpromoted
  puzzles-YYYYMMDD.md       the puzzle note, into sessions/
  puzzle-activity-*.ndjson  raw attempt history, into puzzles/
  intake_state.json         merged into tools/, seen ids unioned rather than
                            replaced
  puzzle_history.json       merged into tools/, snapshots unioned by date

Safe to run twice.  Games already present are skipped by id, not by filename.

Usage:
  python3 tools/reconcile.py --pending ~/Downloads/chess-pending
  python3 tools/reconcile.py --pending ./pending --dry-run
"""
import argparse, csv, glob, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAMES = os.path.join(ROOT, "games")
SESSIONS = os.path.join(ROOT, "sessions")
PUZZLES = os.path.join(ROOT, "puzzles")
STATE = os.path.join(HERE, "intake_state.json")


def tag(pgn, name):
    m = re.search(r'^\[%s "([^"]*)"\]' % name, pgn, re.M)
    return m.group(1) if m else None


def game_key(pgn):
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


def split_pgns(text):
    """Split a concatenated PGN on the Event tag that starts each game."""
    parts, cur = [], []
    for line in text.splitlines():
        if line.startswith("[Event ") and cur and any(l.strip() for l in cur):
            parts.append("\n".join(cur).strip())
            cur = []
        cur.append(line)
    if any(l.strip() for l in cur):
        parts.append("\n".join(cur).strip())
    return [p for p in parts if p]


def existing_keys():
    keys = {}
    for fn in os.listdir(GAMES) if os.path.isdir(GAMES) else []:
        if fn.endswith(".pgn"):
            keys[game_key(open(os.path.join(GAMES, fn), encoding="utf-8", errors="replace").read())] = fn
    return keys


def free_name(name):
    """Keep the cloud's name if it is free, otherwise bump the sequence."""
    if not os.path.exists(os.path.join(GAMES, name)):
        return name
    m = re.match(r"^(\d{8})-(\d{2})-(.*)$", name)
    if not m:
        base, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(os.path.join(GAMES, "%s-%d%s" % (base, n, ext))):
            n += 1
        return "%s-%d%s" % (base, n, ext)
    date, _, rest = m.groups()
    hi = 0
    for fn in os.listdir(GAMES):
        mm = re.match(r"^%s-(\d{2})-" % date, fn)
        if mm:
            hi = max(hi, int(mm.group(1)))
    return "%s-%02d-%s" % (date, hi + 1, rest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pending", required=True, help="directory holding the cloud run's output")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    pend = os.path.expanduser(a.pending)
    if not os.path.isdir(pend):
        sys.exit("no such directory: " + pend)
    for d in (GAMES, SESSIONS, PUZZLES):
        os.makedirs(d, exist_ok=True)

    act = (lambda *x: None) if a.dry_run else None
    seen = existing_keys()
    added, skipped = [], 0

    # ---- games --------------------------------------------------------------
    for bundle in sorted(glob.glob(os.path.join(pend, "games-*.pgn"))):
        for game in split_pgns(open(bundle, encoding="utf-8", errors="replace").read()):
            k = game_key(game)
            if k in seen:
                skipped += 1
                continue
            name = tag(game, "TargetFile") or (k.replace(":", "-") + ".pgn")
            name = free_name(name)
            body = re.sub(r'^\[TargetFile "[^"]*"\]\n', "", game, count=1, flags=re.M)
            if a.dry_run:
                print("  would write games/%s" % name)
            else:
                with open(os.path.join(GAMES, name), "w", encoding="utf-8") as fh:
                    fh.write(body.rstrip() + "\n")
                print("  games/%s" % name)
            seen[k] = name
            added.append(name)

    # ---- session writeup ----------------------------------------------------
    for src in sorted(glob.glob(os.path.join(pend, "*-analysis.md"))):
        base = os.path.basename(src)
        body = open(src, encoding="utf-8", errors="replace").read()
        dup = [fn for fn in os.listdir(SESSIONS)
               if fn.endswith("-analysis.md")
               and open(os.path.join(SESSIONS, fn), encoding="utf-8", errors="replace").read() == body]
        if dup:
            print("  sessions/%s already here as %s, skipping" % (base, dup[0]))
            continue
        m = re.match(r"^(\d{8})-(\d{2})-analysis\.md$", base)
        if m:
            date = m.group(1)
            hi = 0
            for fn in os.listdir(SESSIONS):
                mm = re.match(r"^%s-(\d{2})-analysis\.md$" % date, fn)
                if mm:
                    hi = max(hi, int(mm.group(1)))
            base = "%s-%02d-analysis.md" % (date, hi + 1)
        dest = os.path.join(SESSIONS, base)
        if a.dry_run:
            print("  would write sessions/%s" % base)
        else:
            shutil.copy(src, dest)
            print("  sessions/%s" % base)

    # ---- puzzle candidates --------------------------------------------------
    for src in sorted(glob.glob(os.path.join(pend, "candidates-*.csv"))):
        dest = os.path.join(PUZZLES, os.path.basename(src))
        if os.path.exists(dest):
            # merge rather than clobber a candidates file from an earlier run today
            old = list(csv.DictReader(open(dest, newline="", encoding="utf-8")))
            new = list(csv.DictReader(open(src, newline="", encoding="utf-8")))
            have = {r["SourceId"] for r in old}
            merged = old + [r for r in new if r["SourceId"] not in have]
            if not a.dry_run:
                with open(dest, "w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(merged[0].keys()))
                    w.writeheader()
                    w.writerows(merged)
            print("  puzzles/%s (merged, %d rows)" % (os.path.basename(src), len(merged)))
        else:
            if not a.dry_run:
                shutil.copy(src, dest)
            print("  puzzles/%s" % os.path.basename(src))

    # ---- puzzle note and raw activity ---------------------------------------
    for src in sorted(glob.glob(os.path.join(pend, "puzzles-*.md"))):
        dest = os.path.join(SESSIONS, os.path.basename(src))
        if os.path.exists(dest) and open(dest, encoding="utf-8").read() == \
                open(src, encoding="utf-8").read():
            print("  sessions/%s unchanged, skipping" % os.path.basename(src))
            continue
        if not a.dry_run:
            shutil.copy(src, dest)
        print("  sessions/%s" % os.path.basename(src))

    for src in sorted(glob.glob(os.path.join(pend, "puzzle-activity-*.ndjson"))):
        dest = os.path.join(PUZZLES, os.path.basename(src))
        if not a.dry_run:
            shutil.copy(src, dest)
        print("  puzzles/%s" % os.path.basename(src))

    # ---- puzzle history -----------------------------------------------------
    src = os.path.join(pend, "puzzle_history.json")
    if os.path.exists(src):
        hpath = os.path.join(HERE, "puzzle_history.json")
        incoming = json.load(open(src))
        cur = json.load(open(hpath)) if os.path.exists(hpath) else []
        by_date = {s["date"]: s for s in cur}
        for s2 in incoming:
            by_date[s2["date"]] = s2      # newer snapshot for a date wins
        merged = [by_date[k] for k in sorted(by_date)]
        if not a.dry_run:
            json.dump(merged, open(hpath, "w"), indent=1)
        print("  tools/puzzle_history.json (%d snapshots)" % len(merged))

    # ---- state --------------------------------------------------------------
    src = os.path.join(pend, "intake_state.json")
    if os.path.exists(src):
        incoming = json.load(open(src))
        cur = json.load(open(STATE)) if os.path.exists(STATE) else {}
        merged = dict(cur)
        merged["seen"] = sorted(set(cur.get("seen") or []) | set(incoming.get("seen") or []) | set(seen))
        merged["last_end"] = max(cur.get("last_end", 0), incoming.get("last_end", 0))
        merged["last_run"] = incoming.get("last_run") or cur.get("last_run")
        if not a.dry_run:
            json.dump(merged, open(STATE, "w"), indent=1)
        print("  tools/intake_state.json (%d ids)" % len(merged["seen"]))

    print("\n%d game%s added, %d already present" %
          (len(added), "" if len(added) == 1 else "s", skipped), file=sys.stderr)


if __name__ == "__main__":
    main()
