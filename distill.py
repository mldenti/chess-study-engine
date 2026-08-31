#!/usr/bin/env python3
"""Turn analyze.py output into a session writeup and puzzle candidates.

Two products:

  sessions/YYYYMMDD-NN-analysis.md   the dated writeup, per MAINTENANCE.md
  puzzles/candidates-YYYYMMDD.csv    Lichess-schema rows, not yet promoted

The candidates file is deliberately not the archive.  puzzle_archive.csv is
canonical and gets a running mitch-NNNN id, so promotion stays a decision, not
a side effect of a nightly job.  Candidates are built in true Lichess format:
FEN is the position before the opponent's move, the first move in Moves is the
opponent's, and the solver plays from there.

Every candidate's solution line is replayed with python-chess before it is
written.  Anything that does not validate is dropped.

Motif tags are computed, not guessed, and use the Lichess theme vocabulary so
the archive and the puzzle database speak the same language.

Usage:
  python3 tools/distill.py analysis.json --root . --seq 01
"""
import argparse, csv, json, os, re, sys
from collections import Counter, defaultdict
import chess, chess.pgn

MOTIF_TAGS = {"missedCapture", "missedCheck", "missedCaptureWithCheck", "missedMate",
              "checkedInsteadOfCaptured", "leftHanging", "wrongCapture", "wrongCheck",
              "quietMove"}

VALUE = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
         chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}


def hanging_gain(board):
    """Best net material the side to move can win with a single capture.

    A cheap stand-in for static exchange evaluation: take the captured piece,
    give back the capturing piece if the square is defended.
    """
    best = 0
    for m in board.legal_moves:
        if not board.is_capture(m):
            continue
        victim = board.piece_at(m.to_square)
        gain = VALUE[chess.PAWN] if board.is_en_passant(m) else VALUE[victim.piece_type]
        attacker = board.piece_at(m.from_square)
        board.push(m)
        defended = board.is_attacked_by(board.turn, m.to_square)
        board.pop()
        if defended:
            gain -= VALUE[attacker.piece_type]
        best = max(best, gain)
    return best


def phase_of(board):
    men = len(board.piece_map())
    if men <= 10:
        return "endgame"
    if board.fullmove_number <= 10:
        return "opening"
    return "middlegame"


def motifs(fen_before, played_san, best_san, loss):
    """Lichess-vocabulary tags for one mistake."""
    tags = set()
    b = chess.Board(fen_before)
    tags.add(phase_of(b))
    try:
        played = b.parse_san(played_san)
    except ValueError:
        played = None
    try:
        best = b.parse_san(best_san) if best_san else None
    except ValueError:
        best = None

    if best is not None:
        if b.is_capture(best) and (played is None or not b.is_capture(played)):
            tags.add("missedCapture")
        if b.gives_check(best) and (played is None or not b.gives_check(played)):
            tags.add("missedCheck")
        if b.is_capture(best) and b.gives_check(best):
            tags.add("missedCaptureWithCheck")
        b.push(best)
        if b.is_checkmate():
            tags.add("missedMate")
        b.pop()

    if played is not None:
        if b.gives_check(played) and best is not None and b.is_capture(best) \
                and not b.is_capture(played):
            # the check-before-capture habit already written up in endgames.md
            tags.add("checkedInsteadOfCaptured")
        b.push(played)
        if hanging_gain(b) >= 200:
            tags.add("leftHanging")
        b.pop()

    tags.add("blunder" if loss >= 300 else ("mistake" if loss >= 150 else "inaccuracy"))
    return sorted(tags)


def positions_by_ply(path):
    """FEN before every ply, plus the SAN played, so we can back up one move."""
    game = chess.pgn.read_game(open(path, encoding="utf-8", errors="replace"))
    board = game.board()
    out = {}
    for ply, node in enumerate(game.mainline(), start=1):
        out[ply] = {"fen": board.fen(), "san": board.san(node.move),
                    "uci": node.move.uci()}
        board.push(node.move)
    return out


def validate_line(fen, ucis):
    b = chess.Board(fen)
    for u in ucis:
        m = chess.Move.from_uci(u)
        if m not in b.legal_moves:
            return False
        b.push(m)
    return True


def build_candidate(entry, flagged, plies, games_dir):
    """One Lichess-format puzzle row, or None if it does not hold up."""
    ply = flagged["ply"]
    if ply < 2:
        return None
    setup = plies.get(ply - 1)          # the opponent's move
    mine = plies.get(ply)               # the position where the mistake happened
    if not setup or not mine:
        return None

    line_san = (flagged.get("deep_best_line") or flagged.get("deep_best_san")
                or flagged.get("best_san") or "")
    if not line_san:
        return None
    b = chess.Board(mine["fen"])
    ucis = [setup["uci"]]
    for san in line_san.split():
        try:
            m = b.parse_san(san)
        except ValueError:
            break
        ucis.append(m.uci())
        b.push(m)
    if len(ucis) < 3:                   # setup + at least one full solver reply
        return None
    if len(ucis) % 2 == 0:              # end on the solver's move
        ucis = ucis[:-1]
    if not validate_line(setup["fen"], ucis):
        return None

    themes = motifs(mine["fen"], flagged["san"], flagged.get("deep_best_san")
                    or flagged.get("best_san"), flagged["loss"])
    return {
        "PuzzleId": "",
        "FEN": setup["fen"],
        "Moves": " ".join(ucis),
        "Rating": "",
        "RatingDeviation": "",
        "Popularity": "",
        "NbPlays": "0",
        "Themes": " ".join(themes),
        "GameUrl": entry.get("link") or entry.get("site") or "",
        "OpeningTags": entry.get("eco") or "",
        "SourceId": "%s#%d" % (entry["file"], ply),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_json")
    ap.add_argument("--root", default=".")
    ap.add_argument("--seq", default="01", help="sequence number for the session filename")
    ap.add_argument("--date", help="YYYYMMDD; defaults to today")
    ap.add_argument("--max-candidates", type=int, default=30,
                    help="keep only the N biggest misses; a backfill should not "
                         "produce hundreds of candidates nobody will review")
    ap.add_argument("--min-loss", type=int, default=150,
                    help="minimum centipawn loss for a puzzle candidate")
    ap.add_argument("--log", help="append one JSON line per game here, for trend tracking")
    a = ap.parse_args()

    data = [e for e in json.load(open(a.analysis_json)) if "error" not in e]
    if not data:
        sys.exit("nothing to distill")
    from datetime import date
    datestr = a.date or date.today().strftime("%Y%m%d")
    games_dir = os.path.join(a.root, "games")

    # ---- puzzle candidates -------------------------------------------------
    rows, all_flagged = [], []
    for e in data:
        path = os.path.join(games_dir, e["file"])
        plies = positions_by_ply(path) if os.path.exists(path) else {}
        for f in e["flagged"]:
            f["_game"] = e
            f["_themes"] = motifs(f["fen_before"], f["san"],
                                  f.get("deep_best_san") or f.get("best_san"), f["loss"])
            all_flagged.append(f)
            if f["loss"] >= a.min_loss and plies:
                c = build_candidate(e, f, plies, games_dir)
                if c:
                    c["_loss"] = f["loss"]
                    rows.append(c)

    rows.sort(key=lambda r: -r.get("_loss", 0))
    rows = rows[:a.max_candidates]
    for r in rows:
        r.pop("_loss", None)

    cand_path = os.path.join(a.root, "puzzles", "candidates-%s.csv" % datestr)
    os.makedirs(os.path.dirname(cand_path), exist_ok=True)
    if rows:
        with open(cand_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # ---- session writeup ---------------------------------------------------
    def time_class(tc, filename=""):
        """Chess.com and Lichess disagree about TimeControl, hand exports write
        things like '3 days per move', and Chess.com daily games often carry a
        bare '-', so parse defensively and trust the filename suffix."""
        if filename.endswith("-daily.pgn"):
            return "daily"
        tc = (tc or "").strip()
        if not tc or tc == "-":
            return "unknown"
        if "/" in tc or "day" in tc.lower():
            return "daily"
        base = tc.split("+")[0]
        if not base.isdigit():
            return "unknown"
        secs = int(base)
        return "blitz" if secs < 600 else "rapid"

    by_class = defaultdict(list)
    for e in data:
        by_class[time_class(e.get("time_control"), e["file"])].append(e)
    theme_counts = Counter(t for f in all_flagged for t in f["_themes"]
                           if t not in ("opening", "middlegame", "endgame",
                                        "inaccuracy", "mistake", "blunder"))

    L = []
    A = L.append
    def med(v):
        v = sorted(v)
        n = len(v)
        return 0 if not n else (v[n // 2] if n % 2 else round((v[n // 2 - 1] + v[n // 2]) / 2))

    A("# Analysis %s-%s" % (datestr, a.seq))
    A("")
    A("Automated pass over %d game%s.  Engine %s, screening depth %d, deep pass on flagged moves only."
      % (len(data), "" if len(data) == 1 else "s",
         data[0].get("engine", "stockfish"), data[0].get("screen_depth", 16)))
    A("Generated by `tools/distill.py`.  Read it, keep what is true, fold the durable part into `knowledge/`.")
    A("")
    A("## By time control")
    A("")
    A("| Class | Games | Median ACPL | Mean | Median competitive | Under 40 | Over 100 |")
    A("|---|---|---|---|---|---|---|")
    for label in ("blitz", "rapid", "daily", "unknown"):
        games = by_class.get(label)
        if not games:
            continue
        v = [g["acpl"] for g in games]
        c = [g["acpl_competitive"] for g in games]
        A("| %s | %d | %d | %d | %d | %d%% | %d%% |" % (
            label, len(v), med(v), round(sum(v) / len(v)), med(c),
            round(100 * sum(1 for x in v if x < 40) / len(v)),
            round(100 * sum(1 for x in v if x > 100) / len(v))))
    A("")
    A("Median is the number to read.  The mean is dragged around by single blowouts,")
    A("and at this level one collapsed game is not the same evidence as a habit.")
    A("")
    A("## Games")
    A("")
    A("| Game | Result | ACPL | Competitive | Flagged |")
    A("|---|---|---|---|---|")
    for e in sorted(data, key=lambda x: x["file"]):
        A("| `%s` | %s | %d over %d | %d over %d | %d |" % (
            e["file"], e["result"], e["acpl"], e["moves"],
            e["acpl_competitive"], e["competitive_moves"], len(e["flagged"])))
    A("")
    A("## Recurring motifs")
    A("")
    if theme_counts:
        for t, n in theme_counts.most_common():
            A("- `%s` x%d" % (t, n))
        A("")
        A("Check these against `knowledge/tactics.md`.  A motif that appears here and is")
        A("already written down means the trigger is not firing at the board, which is a")
        A("different problem from not knowing the pattern.")
    else:
        A("None above the flag threshold.")
    A("")
    A("## The mistakes")
    A("")
    for f in sorted(all_flagged, key=lambda x: -x["loss"])[:20]:
        e = f["_game"]
        A("### %s move %d, %s  (-%d)" % (e["file"], f["movenum"], f["san"], f["loss"]))
        A("")
        A("- Better: **%s**%s" % (f.get("deep_best_san") or f.get("best_san") or "?",
                                  "  line: %s" % f["deep_best_line"] if f.get("deep_best_line") else ""))
        A("- Eval %+.2f to %+.2f" % (f["eval_before"] / 100.0, f["eval_after"] / 100.0))
        A("- Tags: %s" % ", ".join(f["_themes"]))
        A("- FEN: `%s`" % f["fen_before"])
        A("- Board: https://lichess.org/analysis/%s" % f["fen_before"].replace(" ", "_"))
        A("")
    A("## Puzzle candidates")
    A("")
    if rows:
        A("%d candidate%s written to `puzzles/candidates-%s.csv`, validated with python-chess."
          % (len(rows), "" if len(rows) == 1 else "s", datestr))
        A("Not promoted.  Promoting means assigning the next `mitch-NNNN` and appending to")
        A("`puzzles/puzzle_archive.csv`, which stays a decision rather than a side effect.")
    else:
        A("None met the threshold.")
    A("")

    # ---- per-game log ------------------------------------------------------
    # One line per game, so the weekly pass can trend numerically instead of
    # parsing prose out of these writeups.  Append only; the weekly never
    # rewrites it.
    if a.log:
        seen_ids = set()
        if os.path.exists(a.log):
            for line in open(a.log, encoding="utf-8"):
                try:
                    seen_ids.add(json.loads(line)["id"])
                except (ValueError, KeyError):
                    pass
        with open(a.log, "a", encoding="utf-8") as fh:
            for e in sorted(data, key=lambda x: x["file"]):
                gid = e.get("link") or e["file"]
                if gid in seen_ids:
                    continue
                # Play vs Coach games allow takebacks, so their ACPL is not
                # comparable.  Logged but flagged, so the weekly can exclude
                # them without the row silently disappearing.
                ev = ""
                gp = os.path.join(games_dir, e["file"])
                if os.path.exists(gp):
                    for line in open(gp, encoding="utf-8", errors="replace"):
                        if line.startswith("[Event "):
                            ev = line.split('"')[1]
                            break
                mine = [f for f in e["flagged"]]
                row = {
                    "id": gid,
                    "file": e["file"],
                    "date": (e.get("date") or "").replace(".", "-"),
                    "class": time_class(e.get("time_control"), e["file"]),
                    "hero": e.get("hero"),
                    "result": e.get("result"),
                    "eco": e.get("eco"),
                    "acpl": e["acpl"],
                    "moves": e["moves"],
                    "acpl_competitive": e["acpl_competitive"],
                    "competitive_moves": e["competitive_moves"],
                    "flagged": len(mine),
                    "motifs": sorted({t for f in mine for t in (f.get("_themes") or [])
                                      if t in MOTIF_TAGS}),
                    "rated": "Coach" not in ev and "Coach-" not in (e.get("black") or ""),
                    "engine_depth": e.get("screen_depth"),
                    "logged": datestr,
                }
                fh.write(json.dumps(row) + "\n")

    sess_path = os.path.join(a.root, "sessions", "%s-%s-analysis.md" % (datestr, a.seq))
    os.makedirs(os.path.dirname(sess_path), exist_ok=True)
    open(sess_path, "w", encoding="utf-8").write("\n".join(L))
    print(sess_path)
    if rows:
        print(cand_path)


if __name__ == "__main__":
    main()
