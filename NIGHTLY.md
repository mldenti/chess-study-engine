# Nightly runbook

What the scheduled nightly session does, in order.  Written for a fresh chat
with no memory of anything.  Read `README.md` and `knowledge/method.md` first.

The Chess folder lives on Mitch's Mac and is reached through the device bridge.
Stockfish does not build inside the local session VM, so the engine pass runs in
the cloud session and the results are committed back.  PGNs are small; moving
them costs nothing.

## 1.  Fetch

Run on the Mac, so new games land straight in `games/`:

```
python3 tools/fetch_games.py --dry-run          # look first
python3 tools/fetch_games.py                    # then write
```

Defaults to the last three days if `tools/intake_state.json` is missing, and to
rapid, blitz and daily.  Dedupe is by game id read from the files already in
`games/`, so re-running is safe.  If it writes nothing, stop here and say so.

## 2.  Analyze

Engine work happens in the cloud session.  Stage the new PGNs, install
Stockfish and python-chess, run the analyzer:

```
apt-get download stockfish && dpkg -x stockfish_*.deb sfx    # ~30 seconds
python3 -m venv .venv && .venv/bin/pip install chess
STOCKFISH=$PWD/sfx/usr/games/stockfish .venv/bin/python tools/analyze.py \
    games/NEW*.pgn -o analysis.json
```

Screening depth 16 gives roughly 170 ms per ply, so twenty blitz games is a few
minutes.  ACPL comes only from the screening pass; the deep pass on flagged
moves is for the writeup and never feeds the number.

**Cap the work.**  More than 25 new games means something unusual happened.
Analyze the most recent 25, say so in the writeup, and leave the rest.

## 3.  Annotate

```
python3 tools/annotate.py analysis.json --games-dir games
```

Edits the PGNs in place, comments prefixed `[SF]`, idempotent.

## 4.  Distill

```
python3 tools/distill.py analysis.json --root . --seq NN
```

Writes `sessions/YYYYMMDD-NN-analysis.md` and, when anything qualifies,
`puzzles/candidates-YYYYMMDD.csv`.  Sequence per day, so check what is already
in `sessions/` for today before choosing `NN`.

## 5.  Commit and fold

Write the annotated PGNs, the session file and the candidates file back to the
Mac.  Then do the step MAINTENANCE.md says never to skip: read the session file
and fold anything durable into `knowledge/`.  Be strict about it.  A motif that
appears once is a note in the session file.  A motif that appears in the session
file and is **already written up in `knowledge/tactics.md`** is the interesting
case, because it means the trigger is not firing at the board, and that belongs
in `knowledge/lessons.md` as a recurrence count, not as a new pattern.

Do not promote puzzle candidates into `puzzle_archive.csv` automatically.  That
stays a decision.

## 6.  Report

One short message: how many games, ACPL range, the motifs that recurred, and
anything that contradicts what `knowledge/` currently claims.  A contradiction
is the most valuable thing this job can find, so lead with it.

If nothing new was fetched, say that in one line and stop.


## Two things that will waste your time if you do not know them

**Overwriting a file that already exists in the folder.**  The mount does not
allow unlink, so `tar -x` over existing files fails with "Cannot open: File
exists", and anything that writes via a temp file and a rename fails too.
Truncate-writes are fine.  Use `device_commit_files` to send a file back, or
`cat new > existing` from a scratch copy outside `mnt/`.  Do not conclude the
folder is read only.

**Background jobs on the Mac's session VM.**  Each shell call there is its own
sandbox with its own network namespace, so anything started with `&` or `nohup`
dies when the call returns.  Long work goes in the cloud session, split into
steps under the call timeout.

## Guardrails

- Never edit a `sessions/` file from an earlier date.
- Never write a second puzzle CSV alongside `puzzle_archive.csv`; candidates
  files are dated and separate on purpose.
- Never hardcode a rating in `knowledge/`.
- Two spaces after a period.  Avoid em dashes.
