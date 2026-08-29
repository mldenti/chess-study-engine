#!/usr/bin/env python3
"""Lichess-method ACPL and blunder report for PGN files.

Method (knowledge/method.md):
  Clamp every evaluation to +/-1000 cp BEFORE differencing.  Mate = +/-1000
  regardless of distance.  Per-move loss = capped(before) - capped(after) from
  the mover's perspective, negatives set to 0.  Average over that player's
  moves only.  Terminal positions are special-cased: a mate delivered is a
  loss of 0, a draw is scored 0.  Without that, the winning move records a
  2000 cp error.

Two passes, on purpose:
  Screening runs every ply at one fixed depth, and ACPL comes only from that
  pass so numbers stay comparable across games.  Flagged moves are then
  re-examined deeper to get a trustworthy best line for the writeup.  The deep
  pass never feeds the ACPL.

Usage:
  python3 tools/analyze.py games/*.pgn
  python3 tools/analyze.py --screen-depth 16 --deep-depth 22 --threshold 100 g.pgn
  STOCKFISH=/path/to/stockfish python3 tools/analyze.py ...

Roughly 170 ms per ply at screening depth 16 on a 4-thread cloud session, so a
day's worth of blitz costs a few minutes.  Outputs JSON on stdout.
"""
import argparse, json, os, sys, shutil
import chess, chess.pgn, chess.engine

CAP = 1000
MITCH_NAMES = {"yepokayitsmitch", "uffishgalumpher", "gleichbleibend"}


def find_engine():
    p = os.environ.get("STOCKFISH") or shutil.which("stockfish")
    if not p:
        sys.exit("No engine.  Set STOCKFISH=/path/to/stockfish or put stockfish on PATH.")
    return p


def capped(score, pov):
    s = score.pov(pov)
    if s.is_mate():
        return CAP if s.mate() > 0 else -CAP
    return max(-CAP, min(CAP, s.score()))


def hero_color(game, requested):
    if requested in ("white", "black"):
        return chess.WHITE if requested == "white" else chess.BLACK
    if game.headers.get("White", "").lower() in MITCH_NAMES:
        return chess.WHITE
    if game.headers.get("Black", "").lower() in MITCH_NAMES:
        return chess.BLACK
    return chess.WHITE


def pv_san(board, pv, limit=6):
    out, b = [], board.copy()
    for m in pv[:limit]:
        if not b.is_legal(m):
            break
        out.append(b.san(m))
        b.push(m)
    return " ".join(out)


def analyze(eng, path, args):
    game = chess.pgn.read_game(open(path))
    if game is None:
        return {"file": os.path.basename(path), "error": "no game found"}
    hero = hero_color(game, args.hero)
    screen = chess.engine.Limit(depth=args.screen_depth)

    board = game.board()
    rows, prev, prev_pv = [], None, None
    for ply, node in enumerate(game.mainline()):
        mover = board.turn
        if prev is None:
            info = eng.analyse(board, screen)
            prev, prev_pv = capped(info["score"], mover), info.get("pv", [])
        fen_before = board.fen()
        best = board.san(prev_pv[0]) if prev_pv else None
        san = board.san(node.move)
        board.push(node.move)
        if board.is_game_over():
            w = board.outcome().winner
            after = 0 if w is None else (CAP if w == mover else -CAP)
        else:
            after = capped(eng.analyse(board, screen)["score"], mover)
        rows.append({
            "ply": ply + 1,
            "movenum": (ply // 2) + 1,
            "color": "W" if mover == chess.WHITE else "B",
            "san": san,
            "best_san": best,
            "eval_before": prev,
            "eval_after": after,
            "loss": max(0, prev - after),
            "fen_before": fen_before,
        })
        if board.is_game_over():
            break
        info = eng.analyse(board, screen)
        prev, prev_pv = capped(info["score"], board.turn), info.get("pv", [])

    tag = "W" if hero == chess.WHITE else "B"
    mine = [r for r in rows if r["color"] == tag]
    acpl = round(sum(r["loss"] for r in mine) / len(mine)) if mine else 0

    # Competitive phase: everything before the evaluation pins at +/-CAP for good.
    comp = mine
    for i, r in enumerate(mine):
        if abs(r["eval_after"]) >= CAP and all(abs(x["eval_after"]) >= CAP for x in mine[i:]):
            comp = mine[:i]
            break
    acpl_comp = round(sum(r["loss"] for r in comp) / len(comp)) if comp else acpl

    # Deep pass on flagged moves only.  Informational; never touches ACPL.
    flagged = [r for r in mine if r["loss"] >= args.threshold]
    deep = chess.engine.Limit(depth=args.deep_depth)
    for r in flagged:
        b = chess.Board(r["fen_before"])
        info = eng.analyse(b, deep)
        pv = info.get("pv", [])
        r["deep_best_san"] = b.san(pv[0]) if pv else None
        r["deep_best_line"] = pv_san(b, pv)
        r["deep_eval"] = capped(info["score"], b.turn)
        r["deep_depth"] = args.deep_depth

    return {
        "file": os.path.basename(path),
        "date": game.headers.get("Date"),
        "white": game.headers.get("White"),
        "black": game.headers.get("Black"),
        "result": game.headers.get("Result"),
        "time_control": game.headers.get("TimeControl"),
        "eco": game.headers.get("ECO"),
        "site": game.headers.get("Site"),
        "link": game.headers.get("Link") or game.headers.get("GameUrl"),
        "hero": "white" if hero == chess.WHITE else "black",
        "engine": os.path.basename(find_engine()),
        "screen_depth": args.screen_depth,
        "moves": len(mine),
        "acpl": acpl,
        "competitive_moves": len(comp),
        "acpl_competitive": acpl_comp,
        "flagged": flagged,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgns", nargs="+")
    ap.add_argument("--screen-depth", type=int, default=16,
                    help="depth for every ply; ACPL comes only from this pass")
    ap.add_argument("--deep-depth", type=int, default=22,
                    help="depth for flagged positions only; never feeds ACPL")
    ap.add_argument("--threshold", type=int, default=100,
                    help="centipawn loss at or above which a move is flagged")
    ap.add_argument("--hero", choices=["white", "black", "auto"], default="auto")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--hash", type=int, default=512)
    ap.add_argument("-o", "--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    eng = chess.engine.SimpleEngine.popen_uci(find_engine())
    eng.configure({"Threads": args.threads, "Hash": args.hash})
    try:
        results = []
        for p in args.pgns:
            print(f"  analyzing {os.path.basename(p)}", file=sys.stderr)
            results.append(analyze(eng, p, args))
    finally:
        eng.quit()

    blob = json.dumps(results, indent=1)
    if args.out:
        open(args.out, "w").write(blob + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(blob)


if __name__ == "__main__":
    main()
