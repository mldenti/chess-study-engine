#!/usr/bin/env python3
"""Promote reviewed puzzle candidates into the canonical archive.

`distill.py` writes dated candidate files.  This is the deliberate step that
moves chosen rows into `puzzles/puzzle_archive.csv`, assigning the next
`mitch-NNNN` from the running counter.  Nothing else should ever append to the
archive.

Every line is revalidated with python-chess before it lands, and any row whose
FEN or solution does not replay cleanly is refused, not silently dropped.

Usage:
  python3 tools/promote_puzzles.py puzzles/candidates-20260828.csv --list
  python3 tools/promote_puzzles.py puzzles/candidates-20260828.csv --rows 1,3,7
  python3 tools/promote_puzzles.py puzzles/candidates-20260828.csv --all --rating 1200
"""
import argparse, csv, os, re, shutil, sys
import chess

ARCHIVE_FIELDS = ["PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation",
                  "Popularity", "NbPlays", "Themes", "GameUrl", "OpeningTags", "SourceId"]


def next_id(archive):
    hi = 0
    if os.path.exists(archive):
        with open(archive, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                m = re.fullmatch(r"mitch-(\d{4})", row.get("PuzzleId", "") or "")
                if m:
                    hi = max(hi, int(m.group(1)))
    return hi + 1


def validate(row):
    try:
        b = chess.Board(row["FEN"])
    except ValueError as e:
        return "bad FEN: %s" % e
    for u in row["Moves"].split():
        try:
            m = chess.Move.from_uci(u)
        except ValueError:
            return "unparseable move %s" % u
        if m not in b.legal_moves:
            return "illegal move %s at %s" % (u, b.fen())
        b.push(m)
    if len(row["Moves"].split()) % 2 == 0:
        return "line ends on the opponent's move"
    return None


def existing_sources(archive):
    if not os.path.exists(archive):
        return set()
    with open(archive, newline="", encoding="utf-8") as fh:
        return {r.get("SourceId", "") for r in csv.DictReader(fh) if r.get("SourceId")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--archive", default="puzzles/puzzle_archive.csv")
    ap.add_argument("--rows", help="1-based row numbers to promote, comma separated")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true", help="show the candidates and stop")
    ap.add_argument("--rating", default="1200", help="rating to stamp on promoted rows")
    ap.add_argument("--deviation", default="80")
    a = ap.parse_args()

    with open(a.candidates, newline="", encoding="utf-8") as fh:
        cands = list(csv.DictReader(fh))
    if not cands:
        sys.exit("no candidates in %s" % a.candidates)

    if a.list or not (a.rows or a.all):
        for i, r in enumerate(cands, 1):
            bad = validate(r)
            print("%2d  %-46s %s%s" % (i, r["Themes"][:46], r["SourceId"],
                                       "   INVALID: " + bad if bad else ""))
        if not (a.rows or a.all):
            print("\nNothing promoted.  Choose with --rows 1,3 or --all.", file=sys.stderr)
        return

    picked = cands if a.all else [cands[int(n) - 1] for n in a.rows.split(",")]
    seen = existing_sources(a.archive)
    nid = next_id(a.archive)

    out = []
    for r in picked:
        bad = validate(r)
        if bad:
            sys.exit("refusing to promote %s: %s" % (r["SourceId"], bad))
        if r["SourceId"] in seen:
            print("  already in the archive, skipping %s" % r["SourceId"], file=sys.stderr)
            continue
        row = {k: r.get(k, "") for k in ARCHIVE_FIELDS}
        row["PuzzleId"] = "mitch-%04d" % nid
        row["Rating"] = row["Rating"] or a.rating
        row["RatingDeviation"] = row["RatingDeviation"] or a.deviation
        row["Popularity"] = row["Popularity"] or "100"
        row["NbPlays"] = row["NbPlays"] or "0"
        out.append(row)
        nid += 1

    if not out:
        print("nothing to add", file=sys.stderr)
        return

    shutil.copy(a.archive, a.archive + ".bak")
    with open(a.archive, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=ARCHIVE_FIELDS).writerows(out)
    for row in out:
        print("  %s  %s" % (row["PuzzleId"], row["Themes"]))
    print("%d appended to %s (previous copy at %s.bak)" % (len(out), a.archive, a.archive),
          file=sys.stderr)


if __name__ == "__main__":
    main()
