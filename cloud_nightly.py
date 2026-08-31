#!/usr/bin/env python3
"""The whole nightly pass, as one command.

A scheduled task gets no device bridge, so the Chess folder is invisible to it.
This does the work against a scratch directory and leaves a small set of files
for the next desktop session to fold into the folder.

Design note, because this was got wrong once and it was expensive.  A scheduled
run is an agent session, and anything the agent has to read or write costs
tokens.  So this script does everything the shell can do, and the agent's only
jobs are: fetch two small state files, run this, write the results back.  The
toolchain itself lives in a git repo precisely so it never passes through the
model's context.

It also sets itself up.  Stockfish and python-chess are installed **only after**
a fetch confirms there are new games, because on a quiet night that setup is
pure waste.

Needs beside it in tools/:  fetch_games.py  analyze.py  annotate.py
                            distill.py  puzzles_lichess.py
Needs from the project:     intake_state.json  lichess_token.txt (optional)
                            puzzle_history.json (optional)

Produces in out/:
  games-YYYYMMDD.pgn          annotated, concatenated, TargetFile tag per game
  YYYYMMDD-NN-analysis.md     session writeup
  candidates-YYYYMMDD.csv     puzzle candidates, when any qualify
  puzzles-YYYYMMDD.md         puzzle note, only when a theme moved
  puzzle-activity-*.ndjson    raw attempt history
  intake_state.json           updated
  puzzle_history.json         updated
  games_log.jsonl             one row per game, appended, for the weekly pass

Usage:
  python3 tools/cloud_nightly.py --max-games 25
"""
import argparse, glob, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CHESS_WORKROOT") or os.path.dirname(HERE)


def run(cmd, env=None, quiet=False, check=True):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, env=e, capture_output=True, text=True)
    if p.returncode != 0 and check:
        sys.stderr.write((p.stdout or "") + "\n" + (p.stderr or "") + "\n")
        sys.exit("step failed: " + " ".join(cmd))
    if not quiet and p.stderr.strip():
        sys.stderr.write(p.stderr)
    return p.stdout


def ensure_engine():
    """Install Stockfish and python-chess.  Called only when there is work."""
    sf = os.environ.get("STOCKFISH")
    if sf and os.path.exists(sf):
        pass
    else:
        sf = os.path.join(ROOT, "sfx", "usr", "games", "stockfish")
        if not os.path.exists(sf):
            found = shutil.which("stockfish")
            if found:
                sf = found
            else:
                sys.stderr.write("installing stockfish\n")
                run(["bash", "-c",
                     "cd %s && apt-get download stockfish >/dev/null 2>&1 && "
                     "dpkg -x stockfish_*.deb sfx" % ROOT])
    if not os.path.exists(sf) and not shutil.which(os.path.basename(sf)):
        sys.exit("could not obtain a stockfish binary")

    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    if not os.path.exists(venv_py):
        sys.stderr.write("creating venv with python-chess\n")
        run(["bash", "-c",
             "cd %s && python3 -m venv .venv && "
             ".venv/bin/pip install -q --upgrade pip setuptools wheel && "
             ".venv/bin/pip install -q chess" % ROOT])
    return sf, venv_py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-games", type=int, default=25,
                    help="engine budget; the rest wait for the next run, oldest first")
    ap.add_argument("--classes", default="rapid,blitz,daily")
    ap.add_argument("--since", help="YYYY-MM-DD, overrides the saved state")
    ap.add_argument("--screen-depth", type=int, default=16)
    ap.add_argument("--min-loss", type=int, default=200)
    ap.add_argument("--skip-puzzles", action="store_true")
    a = ap.parse_args()

    work = os.path.join(ROOT, "work")
    newg = os.path.join(work, "games")
    out = os.path.join(ROOT, "out")
    for d in (work, newg, out):
        os.makedirs(d, exist_ok=True)
    state_path = os.path.join(HERE, "intake_state.json")
    if not os.path.exists(state_path):
        sys.exit("no tools/intake_state.json; fetch it from the project first")

    env = {"CHESS_ROOT": work, "CHESS_GAMES": newg, "CHESS_STATE": state_path}
    result = {}

    # ---- 1. fetch -----------------------------------------------------------
    # Standard library only and no engine needed, so this is the cheap check
    # that decides whether the rest of the night is worth setting up for.
    cmd = [sys.executable, os.path.join(HERE, "fetch_games.py"), "--classes", a.classes]
    if a.since:
        cmd += ["--since", a.since]
    if a.max_games:
        cmd += ["--max", str(a.max_games)]
    run(cmd, env)
    pgns = sorted(glob.glob(os.path.join(newg, "*.pgn")))

    # ---- 2. puzzles ---------------------------------------------------------
    # Also stdlib, also cheap, and independent of games.
    puzzles = {"status": "skipped"}
    pz = os.path.join(HERE, "puzzles_lichess.py")
    if not a.skip_puzzles and os.path.exists(pz):
        try:
            puzzles = json.loads(run([sys.executable, pz, "--days", "90",
                                      "--activity", "200", "--out", out],
                                     env, quiet=True))
        except SystemExit:
            puzzles = {"status": "failed"}
        except ValueError:
            puzzles = {"status": "unparseable"}

    shutil.copy(state_path, os.path.join(out, "intake_state.json"))
    hist = os.path.join(HERE, "puzzle_history.json")
    if os.path.exists(hist):
        shutil.copy(hist, os.path.join(out, "puzzle_history.json"))

    if not pgns:
        print(json.dumps({"status": "nothing_new", "games": 0,
                          "puzzles_moved": puzzles.get("moved", []),
                          "out": sorted(os.listdir(out))}))
        return

    # ---- 3. engine, only now ------------------------------------------------
    sf, py = ensure_engine()
    env["STOCKFISH"] = sf

    analysis = os.path.join(work, "analysis.json")
    run([py, os.path.join(HERE, "analyze.py")] + pgns +
        ["--screen-depth", str(a.screen_depth), "-o", analysis], env)
    run([py, os.path.join(HERE, "annotate.py"), analysis, "--games-dir", newg], env)

    datestr = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
    os.makedirs(os.path.join(work, "sessions"), exist_ok=True)
    os.makedirs(os.path.join(work, "puzzles"), exist_ok=True)
    run([py, os.path.join(HERE, "distill.py"), analysis, "--root", work,
         "--date", datestr, "--seq", "01", "--min-loss", str(a.min_loss),
         "--log", os.path.join(HERE, "games_log.jsonl")], env)

    # ---- 4. pack ------------------------------------------------------------
    bundle = os.path.join(out, "games-%s.pgn" % datestr)
    with open(bundle, "w", encoding="utf-8") as fh:
        for p in pgns:
            text = open(p, encoding="utf-8", errors="replace").read().rstrip()
            if "[TargetFile " not in text:
                text = re.sub(r"(\[Event [^\]]*\]\n)",
                              r'\1[TargetFile "%s"]\n' % os.path.basename(p),
                              text, count=1)
            fh.write(text + "\n\n")

    for src in (os.path.join(work, "sessions", "%s-01-analysis.md" % datestr),
                os.path.join(work, "puzzles", "candidates-%s.csv" % datestr),
                os.path.join(HERE, "games_log.jsonl")):
        if os.path.exists(src):
            shutil.copy(src, os.path.join(out, os.path.basename(src)))
    shutil.copy(state_path, os.path.join(out, "intake_state.json"))

    data = json.load(open(analysis))
    acpls = sorted(g["acpl"] for g in data if "acpl" in g)
    from collections import Counter
    motifs = Counter()
    for g in data:
        for f in g.get("flagged", []):
            for t in f.get("_themes", []) or []:
                motifs[t] += 1

    result = {
        "status": "ok",
        "games": len(pgns),
        "acpl_min": acpls[0] if acpls else None,
        "acpl_median": acpls[len(acpls) // 2] if acpls else None,
        "acpl_max": acpls[-1] if acpls else None,
        "flagged": sum(len(g.get("flagged", [])) for g in data),
        "puzzles_moved": puzzles.get("moved", []),
        "out": sorted(os.listdir(out)),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
