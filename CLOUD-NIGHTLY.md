# Cloud nightly runbook

You are a scheduled session with **no access to Mitch's Mac**.  There is no
device bridge in a scheduled run; the tools do not exist in the session at all.
That is expected.  Do not look for them and do not report their absence.

**Read this whole file before doing anything, then follow it literally.**  It is
short on purpose.  Every extra thing you read, write or think about in this job
costs real money on a task that usually has nothing to report.

## The one rule

**Move as little through your context as possible.**  The shell can fetch, run
and write things far more cheaply than you can.  Concretely:

- Clone the toolchain.  Do not read the scripts.  You never need to see them.
- When writing a file into the project, always pass `local_path`.  Never paste
  file contents inline.  A busy night's PGN bundle is 30KB, and inlining it
  costs more than the entire rest of the job.
- Do not read `chess/knowledge/chess-lessons-and-method.md`.  It is 40KB and
  nothing in this job needs it.  Contradiction-hunting is a weekly task, not a
  nightly one.

## Steps

**1.  Get the toolchain and the state.**

```
git clone --depth 1 https://github.com/mldenti/chess-study-engine.git tools
```

Public repo, no credentials needed.  **Do not read the files it contains.**  You
never need to see that code; running it is the whole point.

If the clone fails, report the error and stop.  Do not reconstruct the toolchain
by hand and do not look for the scripts in the project; they are deliberately
not there any more, because a session that reads them costs more than a missed
night.

Then fetch these three from the project and write them into `tools/`:

```
chess/tools/intake_state.json      required
chess/tools/lichess_token.txt      optional, read only scopes, for puzzles
chess/tools/puzzle_history.json    optional, the snapshot series
```

Those three are the only project docs this job reads.  `intake_state.json` is
the one that matters: its `seen` list is how the run knows which games are
already in Mitch's folder without being able to see the folder.  **If you cannot
read it, stop.**  Fetching without it would re-import games that already exist.

Never print the token, never quote it in a report, never let it reach
`chess/pending/`.

**2.  Run it.**

```
python3 tools/cloud_nightly.py --max-games 25
```

One command.  It fetches, and only if there are new games does it install
Stockfish and build a venv, because on a quiet night that setup is pure waste.
Then it analyses, annotates, distils and packs.  It prints one line of JSON.

Do not install anything yourself.  Do not run the individual scripts.  If this
command fails, report the error and stop; do not improvise a workaround.

**3.  Write the results back.**

Everything it produced is in `out/`.  Write each file with `local_path`:

| From `out/` | To |
|---|---|
| `games-*.pgn` | `chess/pending/` same name |
| `*-analysis.md` | `chess/pending/` same name |
| `candidates-*.csv` | `chess/pending/` same name |
| `puzzles-*.md` | `chess/pending/` same name |
| `puzzle-activity-*.ndjson` | `chess/pending/` same name |
| `intake_state.json` | `chess/tools/intake_state.json` |
| `puzzle_history.json` | `chess/tools/puzzle_history.json` |

The last two overwrite their `chess/tools/` copies rather than going to pending,
because tomorrow's run reads them.  **Write both every time, including on a
quiet night.**  Skipping the state write makes tomorrow re-import tonight.

Leave anything already sitting in `chess/pending/` alone.  It accumulates until
Mitch reconciles it, and clearing it would lose nights he has not folded in yet.

**4.  Report, in two or three sentences.**

`{"status":"nothing_new"}` means no new games.  Say so in one line and stop.
Do not write a session file for a day with no games.

Otherwise: how many games, the ACPL median and range, and the `puzzles_moved`
list if it is not empty.  That last one is the only thing here that can show
whether studying a weak theme worked, so it earns its line.

Do not summarise the games individually.  Do not quote the writeup back.  Do not
analyse trends, hunt for contradictions, or give advice.  The writeup is already
in `chess/pending/` and Mitch reads it there.  Your report exists so he knows
the job ran and whether to go look.

End with one line saying results are in `chess/pending/` and have not reached
the Mac folder yet.

## What you must not do

- Do not edit `chess/knowledge/chess-lessons-and-method.md`.  It mirrors the Mac
  folder and would be overwritten by the next sync.
- Do not promote puzzle candidates into any archive.  That stays a human call.
- Do not invent a workaround for the missing Mac.  If a step needs the folder,
  this run cannot do it.
- Do not use WebFetch for the chess hosts.  It declines them on robots rules,
  which says nothing about the scripts; they use `urllib` from the container on
  the account's egress allowlist and they work.  A WebFetch refusal is not
  evidence of a missing fetch path.

## On the other side

When Mitch next opens a desktop session, `tools/reconcile.py --pending <dir>`
splits the bundled PGN back into `games/`, files the writeups, merges the
candidates and unions both state files.  Safe to run twice; it dedupes by game
id.

Two spaces after a period.  Avoid em dashes.
