#!/usr/bin/env python3
"""Write engine findings back into the PGN as comments and NAGs.

Takes the JSON from analyze.py and the game files it describes, and edits each
PGN in place so the game carries its own analysis and opens annotated in any
viewer.  Only moves that analyze.py flagged get touched.

Idempotent: every comment this writes is prefixed [SF], and existing [SF]
comments are stripped before new ones go in, so re-running after a deeper
analysis replaces the old notes rather than stacking them.

Usage:
  python3 tools/annotate.py analysis.json --games-dir games
  python3 tools/annotate.py analysis.json --dry-run
"""
import argparse, json, os, re, sys
import chess, chess.pgn

# python-chess NAG constants, chosen by size of the error
NAG_INACCURACY, NAG_MISTAKE, NAG_BLUNDER = 6, 2, 4


def nag_for(loss):
    if loss >= 300:
        return NAG_BLUNDER
    if loss >= 150:
        return NAG_MISTAKE
    return NAG_INACCURACY


def fmt_eval(cp):
    return ("#" if abs(cp) >= 1000 else "") + ("%+.2f" % (cp / 100.0))


def annotate_file(path, entry, dry_run):
    game = chess.pgn.read_game(open(path, encoding="utf-8", errors="replace"))
    if game is None:
        return 0
    by_ply = {f["ply"]: f for f in entry.get("flagged", [])}
    if not by_ply:
        return 0

    node, ply, touched = game, 0, 0
    while node.variations:
        node = node.variations[0]
        ply += 1
        # clear any note this script wrote before
        if node.comment:
            node.comment = re.sub(r"\[SF\][^\]]*?(?=$|\s\[)", "", node.comment).strip()
            node.nags = {n for n in node.nags if n not in (NAG_INACCURACY, NAG_MISTAKE, NAG_BLUNDER)}
        f = by_ply.get(ply)
        if not f:
            continue
        best = f.get("deep_best_san") or f.get("best_san")
        line = f.get("deep_best_line")
        parts = ["[SF] -%d cp" % f["loss"]]
        if best:
            parts.append("better was %s" % best)
        if line and line != best:
            parts.append("(%s)" % line)
        parts.append("eval %s to %s" % (fmt_eval(f["eval_before"]), fmt_eval(f["eval_after"])))
        node.comment = (node.comment + " " if node.comment else "") + ", ".join(parts)
        node.nags.add(nag_for(f["loss"]))
        touched += 1

    header = "ACPL %d over %d moves (competitive %d over %d), Stockfish depth %d" % (
        entry["acpl"], entry["moves"], entry["acpl_competitive"],
        entry["competitive_moves"], entry["screen_depth"])
    game.headers["Annotator"] = "chess-study-engine"
    game.comment = "[SF] " + header

    if dry_run:
        print("  %s: %d moves would be annotated (%s)" % (os.path.basename(path), touched, header))
    else:
        with open(path, "w", encoding="utf-8") as fh:
            print(game, file=fh, end="\n\n")
        print("  %s: %d moves annotated" % (os.path.basename(path), touched))
    return touched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_json")
    ap.add_argument("--games-dir", default="games")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    data = json.load(open(a.analysis_json))
    total = 0
    for entry in data:
        if "error" in entry:
            continue
        path = os.path.join(a.games_dir, entry["file"])
        if not os.path.exists(path):
            print("  missing %s, skipping" % entry["file"], file=sys.stderr)
            continue
        total += annotate_file(path, entry, a.dry_run)
    print("%d moves annotated across %d games" % (total, len(data)), file=sys.stderr)


if __name__ == "__main__":
    main()
