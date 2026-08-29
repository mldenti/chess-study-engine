# Cloud nightly runbook

You are a scheduled session.  **You have no access to Mitch's Mac.**  There is
no device bridge in a scheduled run, so the Chess folder, its scripts and its
games are all invisible to you.  This was tested on 28 Aug 2026 and confirmed:
the `mcp__remote-devices__*` tools are not merely denied, they do not exist in
the session.  Do not look for them and do not wait for them.

Everything you need is in this project.  Everything you produce goes back into
this project, and the next desktop session folds it into the folder.

## What you can and cannot reach

**Can:** the project docs, via the Projects tool.  The open internet from the
container shell, including `api.chess.com` and `lichess.org`, which are on the
account's network allowlist.  A Stockfish binary, via apt.  python-chess, via
pip.

**Cannot:** the Mac, in any form.

One trap worth naming, because a previous run fell into it.  The **WebFetch
tool** declines both chess hosts on robots rules.  That says nothing about
whether the scripts can reach them.  `fetch_games.py` uses `urllib` from the
container, which is ordinary program network access governed by the account's
egress allowlist, and it works.  Do not conclude from a WebFetch refusal that
there is no fetch path, and do not use WebFetch to pull games.

## Steps

**1.  Pull the toolchain out of the project.**

Read these and write them to disk under `tools/`:

```
chess/tools/fetch_games.py
chess/tools/analyze.py
chess/tools/annotate.py
chess/tools/distill.py
chess/tools/cloud_nightly.py
chess/tools/puzzles_lichess.py
chess/tools/intake_state.json
chess/tools/lichess_token.txt
chess/tools/puzzle_history.json
```

`intake_state.json` is the one that matters.  Its `seen` list is how the run
knows which games are already in Mitch's folder without being able to see the
folder.  If you cannot read it, **stop**: fetching without it would re-import
games that already exist.

`lichess_token.txt` is a personal API token with read-only scopes, used for the
puzzle step and nothing else.  **Never print it, never paste it into a report,
never put it in a session writeup or any file that goes to `chess/pending/`.**
If it is missing the puzzle step skips itself and the games work is unaffected.

`puzzle_history.json` is the append-only series of puzzle snapshots.  Without it
the run still works but cannot say what moved since last time.

**2.  Set up the engine.**

```
apt-get download stockfish && dpkg -x stockfish_*.deb sfx
python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip setuptools wheel && .venv/bin/pip install -q chess
```

The system pip cannot build python-chess on this image, so use the venv.

**3.  Run the driver.**

```
STOCKFISH=$PWD/sfx/usr/games/stockfish .venv/bin/python tools/cloud_nightly.py --max-games 25
```

It pulls puzzle stats, then fetches, analyses, annotates and distils, and
prints a JSON summary.

The puzzle step runs first and is independent of games, so **a `nothing_new`
result still has output worth writing back**: the puzzle note, the raw activity,
and the two `chess/tools/` files.  `nothing_new` means only that no new *games*
were found.  Say so in one line and do not manufacture a session file for a day
with no games, but do write back what the puzzle step produced.

Budget roughly 170 ms per ply at screening depth 16, so twenty games is a few
minutes.  `--max-games` caps the night at N games, **oldest first**, and leaves
the rest for tomorrow.  The state's `last_end` never advances past a deferred
game, so a backlog drains in order over several nights and nothing is skipped.
The driver's stderr says how many were left behind.

**4.  Put the output back in the project.**

Everything in `out/` goes to `chess/pending/`, same filenames:

```
chess/pending/games-YYYYMMDD.pgn
chess/pending/YYYYMMDD-NN-analysis.md
chess/pending/candidates-YYYYMMDD.csv
chess/pending/puzzles-YYYYMMDD.md
chess/pending/puzzle-activity-YYYYMMDD.ndjson
chess/tools/intake_state.json        <- overwrite, do not put this in pending
chess/tools/puzzle_history.json      <- overwrite, do not put this in pending
```

Two files are exceptions and must be written back over their `chess/tools/`
copies rather than into pending, because tomorrow's run reads them:
`intake_state.json`, which is how it knows what has already been fetched, and
`puzzle_history.json`, which is the snapshot series.  **If you skip the state
write, tomorrow's run re-imports tonight's games.**  Write both even if you
write nothing else.  A nothing_new night still updates both.

Leave anything already in `chess/pending/` alone.  It accumulates until Mitch
runs the reconcile, and clearing it would lose nights he has not folded in yet.

**5.  Report.**

Short.  How many games, the ACPL range and median, which motifs recurred, and
anything that contradicts what the knowledge doc currently claims.  Lead with
the contradiction.  Say plainly that the results are in `chess/pending/` and
have not reached the folder yet.

Include the puzzle step's `moved` list if it is not empty.  That is the only
thing in this job that can show whether studying a weak theme worked, so it is
worth a line even on a quiet night.  Do not repeat the weakest-theme table every
night; it barely changes and it is already in the note.

## What you must not do

- Do not edit `chess/knowledge/chess-lessons-and-method.md`.  That doc mirrors
  the Mac folder, and an edit here would be silently overwritten by the next
  sync.  A correction goes in your session writeup, which Mitch folds in.
- Do not promote puzzle candidates into any archive.  Candidates stay
  candidates until a person picks them.
- Do not invent a workaround for the missing Mac.  If a step needs the folder,
  the answer is that this run cannot do it.

## On the other side

When Mitch next opens a desktop session, `tools/reconcile.py --pending <dir>`
splits the bundled PGN back into `games/`, files the session writeup, merges
the candidates and unions the state.  It is safe to run twice and dedupes by
game id, so nothing doubles up.

Two spaces after a period.  Avoid em dashes.
