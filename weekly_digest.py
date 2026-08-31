#!/usr/bin/env python3
"""The weekly thinking pass, minus the thinking.

The nightly job is deliberately mechanical.  This is where trends get looked at.
It does the arithmetic and states what moved; judging whether any of it
contradicts `knowledge/` is left to the session running it, because that needs
reading the actual claims and this script should not pretend to.

Its main job is refusing to manufacture trends.  At roughly twenty games a week
a median swing of a few centipawns is noise, so nothing is reported as movement
unless it clears both a minimum sample and a minimum size.  A quiet week should
produce a short digest that says little, and that is a correct outcome.

Inputs:
  tools/games_log.jsonl      one row per analysed game, appended by distill.py
  tools/puzzle_history.json  dated puzzle dashboard snapshots

Outputs:
  out/weekly-YYYYMMDD.md     the digest
  stdout                     JSON summary, including facts worth checking
                             against knowledge/

Usage:
  python3 tools/weekly_digest.py --weeks 6
"""
import argparse, json, os, statistics as st, sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CHESS_WORKROOT") or os.path.dirname(HERE)

# How much movement is worth mentioning.  Below these it is noise and saying so
# would train the reader to ignore the digest.
MIN_GAMES_PER_BUCKET = 6
MIN_ACPL_SWING = 8
MIN_MOTIF_RATE_SWING = 0.15
MIN_PUZZLE_SWING = 25

MOTIF_LABEL = {
    "missedCapture": "missed a capture",
    "missedCheck": "missed a check",
    "missedCaptureWithCheck": "missed capture with check",
    "missedMate": "missed mate",
    "checkedInsteadOfCaptured": "checked instead of captured",
    "leftHanging": "left something hanging",
    "wrongCapture": "took the wrong thing",
    "wrongCheck": "gave the wrong check",
    "quietMove": "quiet move, nothing forcing",
}


def load_log(path):
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("rated") is False:
            continue                      # coach games, takebacks allowed
        try:
            r["_d"] = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        rows.append(r)
    return rows


def med(v):
    return int(st.median(v)) if v else None


def bucket_weeks(rows, weeks, today):
    """Split into week-long buckets ending today, most recent first."""
    out = []
    for i in range(weeks):
        hi = today - timedelta(days=7 * i)
        lo = hi - timedelta(days=7)
        out.append({"start": lo, "end": hi,
                    "rows": [r for r in rows if lo < r["_d"] <= hi]})
    return out


def acpl_lines(this, prior):
    """Per class: this week, the trailing baseline, and whether it really moved."""
    lines = []
    for cls in ("blitz", "rapid", "daily"):
        t = [r["acpl"] for r in this if r["class"] == cls]
        p = [r["acpl"] for r in prior if r["class"] == cls]
        if not t:
            continue
        entry = {"class": cls, "n": len(t), "median": med(t),
                 "baseline_n": len(p), "baseline_median": med(p),
                 "moved": None, "direction": None}
        if len(t) >= MIN_GAMES_PER_BUCKET and len(p) >= MIN_GAMES_PER_BUCKET:
            d = entry["median"] - entry["baseline_median"]
            if abs(d) >= MIN_ACPL_SWING:
                entry["moved"] = d
                entry["direction"] = "worse" if d > 0 else "better"
        lines.append(entry)
    return lines


def motif_rates(rows):
    """Motif occurrences per game, so weeks of different length compare."""
    if not rows:
        return {}
    c = Counter(m for r in rows for m in (r.get("motifs") or []))
    return {k: v / len(rows) for k, v in c.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=6, help="how much history to use as baseline")
    ap.add_argument("--out", default=None)
    ap.add_argument("--date", help="YYYY-MM-DD, treat this as today")
    a = ap.parse_args()

    today = (datetime.strptime(a.date, "%Y-%m-%d").date() if a.date
             else datetime.now(timezone.utc).astimezone().date())
    log = os.path.join(HERE, "games_log.jsonl")
    rows = load_log(log)
    out = a.out or os.path.join(ROOT, "out")
    os.makedirs(out, exist_ok=True)
    datestr = today.strftime("%Y%m%d")

    buckets = bucket_weeks(rows, a.weeks, today)
    this = buckets[0]["rows"]
    prior = [r for b in buckets[1:] for r in b["rows"]]

    acpl = acpl_lines(this, prior)
    tr, pr = motif_rates(this), motif_rates(prior)
    motif_moves = []
    if len(this) >= MIN_GAMES_PER_BUCKET and len(prior) >= MIN_GAMES_PER_BUCKET:
        for k in set(tr) | set(pr):
            d = tr.get(k, 0) - pr.get(k, 0)
            if abs(d) >= MIN_MOTIF_RATE_SWING:
                motif_moves.append({"motif": k, "now": round(tr.get(k, 0), 2),
                                    "before": round(pr.get(k, 0), 2), "delta": round(d, 2)})
        motif_moves.sort(key=lambda x: -abs(x["delta"]))

    # puzzles
    puzzle_moves, puzzle_now = [], None
    hpath = os.path.join(HERE, "puzzle_history.json")
    if os.path.exists(hpath):
        try:
            hist = json.load(open(hpath))
        except ValueError:
            hist = []
        if hist:
            puzzle_now = hist[-1]
            older = [h for h in hist
                     if (today - datetime.strptime(h["date"], "%Y-%m-%d").date()).days >= 7]
            if older:
                was = older[-1]
                for k, v in puzzle_now.get("themes", {}).items():
                    w = was.get("themes", {}).get(k)
                    if not w or not v.get("performance") or not w.get("performance"):
                        continue
                    if v["nb"] <= w["nb"]:
                        continue          # no new attempts, so the window slid
                    d = v["performance"] - w["performance"]
                    if abs(d) >= MIN_PUZZLE_SWING:
                        puzzle_moves.append({"theme": k, "delta": d,
                                             "new_attempts": v["nb"] - w["nb"],
                                             "performance": v["performance"]})
                puzzle_moves.sort(key=lambda x: -abs(x["delta"]))

    # worst openings this week, only if there is enough of one to mean anything
    eco = defaultdict(list)
    for r in this:
        if r.get("eco"):
            eco[r["eco"]].append(r["acpl"])
    eco_worst = sorted(((k, len(v), med(v)) for k, v in eco.items() if len(v) >= 3),
                       key=lambda x: -x[2])[:3]

    # ---- digest -------------------------------------------------------------
    L, A = [], lambda s: L.append(s)
    A("# Week to %s" % today.isoformat())
    A("")
    if not this:
        A("No games logged this week.")
        A("")
        A("Nothing to trend.  This is a normal outcome, not a failure.")
    else:
        A("%d game%s: %s." % (len(this), "" if len(this) == 1 else "s",
                              ", ".join("%d %s" % (sum(1 for r in this if r["class"] == c), c)
                                        for c in ("blitz", "rapid", "daily")
                                        if any(r["class"] == c for r in this))))
        A("Baseline is the %d games in the %d weeks before." % (len(prior), a.weeks - 1))
        A("")
        A("## Accuracy")
        A("")
        A("| Class | Games | Median ACPL | Baseline | Moved |")
        A("|---|---|---|---|---|")
        for e in acpl:
            # Higher ACPL is worse, so a bare signed number reads backwards.
            moved = "no"
            if e["moved"] is not None:
                moved = ("**worse by %d**" % e["moved"] if e["moved"] > 0
                         else "**better by %d**" % -e["moved"])
            A("| %s | %d | %s | %s over %d | %s |" % (
                e["class"], e["n"], e["median"],
                e["baseline_median"] if e["baseline_median"] is not None else "-",
                e["baseline_n"], moved))
        A("")
        A("\"Moved\" is blank unless both samples reach %d games and the swing is at"
          % MIN_GAMES_PER_BUCKET)
        A("least %d centipawns.  Below that it is noise and reporting it would be"
          % MIN_ACPL_SWING)
        A("worse than saying nothing.")
        A("")
        A("## Mistakes")
        A("")
        if motif_moves:
            A("Per game, against the baseline:")
            A("")
            for m in motif_moves:
                A("- **%s** %.2f per game, was %.2f (%+.2f)"
                  % (MOTIF_LABEL.get(m["motif"], m["motif"]), m["now"], m["before"], m["delta"]))
        else:
            A("Nothing moved enough to report.  The mix of mistakes this week looks like")
            A("the mix in the weeks before it.")
        A("")
        top = Counter(m for r in this for m in (r.get("motifs") or [])).most_common(4)
        if top:
            A("Most common this week: " +
              ", ".join("%s (%d)" % (MOTIF_LABEL.get(k, k), v) for k, v in top) + ".")
            A("")
        if eco_worst:
            A("## Openings")
            A("")
            for code, n, m in eco_worst:
                A("- `%s`: %d games, median ACPL %d" % (code, n, m))
            A("")
            A("Only openings with three or more games this week are listed.")
            A("")

    A("## Puzzles")
    A("")
    if puzzle_now:
        A("%d puzzles in the trailing window, performance %s."
          % (puzzle_now.get("nb", 0), puzzle_now.get("performance")))
        if puzzle_moves:
            A("")
            for p in puzzle_moves:
                A("- `%s` %+d to %d, over %d new attempt%s"
                  % (p["theme"], p["delta"], p["performance"], p["new_attempts"],
                     "" if p["new_attempts"] == 1 else "s"))
            A("")
            A("Only themes with new attempts are shown.  A theme that moves without")
            A("new attempts moved because the 90 day window slid.")
        else:
            A("")
            A("No theme moved by %d or more on new attempts." % MIN_PUZZLE_SWING)
    else:
        A("No puzzle history yet.")
    A("")
    A("## For the reader")
    A("")
    A("Everything above is arithmetic.  The judgement is whether any of it")
    A("contradicts what `knowledge/` currently claims, and that is the reason this")
    A("digest exists.  Read it against `lessons.md` in particular, and fold in only")
    A("what survives.  A week that changes nothing should change nothing.")
    A("")

    path = os.path.join(out, "weekly-%s.md" % datestr)
    open(path, "w", encoding="utf-8").write("\n".join(L))

    print(json.dumps({
        "status": "ok",
        "week_ending": today.isoformat(),
        "games_this_week": len(this),
        "games_baseline": len(prior),
        "acpl": acpl,
        "motif_moves": motif_moves,
        "puzzle_moves": puzzle_moves,
        "note": os.path.basename(path),
        "anything_moved": bool([e for e in acpl if e["moved"] is not None]
                               or motif_moves or puzzle_moves),
    }, indent=1))


if __name__ == "__main__":
    main()
