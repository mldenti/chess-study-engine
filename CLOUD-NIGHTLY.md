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

Then fetch these four from the project and write them into `tools/`:

```
chess/tools/intake_state.json      required
chess/tools/games_log.jsonl        required, the cumulative per-game log
chess/tools/lichess_token.txt      optional, read only scopes, for puzzles
chess/tools/puzzle_history.json    optional, the snapshot series
```

Those four are the only project docs this job reads.  `intake_state.json` is
the one that matters: its `seen` list is how the run knows which games are
already in Mitch's folder without being able to see the folder.  **If you cannot
read it, stop.**  Fetching without it would re-import games that already exist.

`games_log.jsonl` is gitignored, so the clone does not have it and tonight's
rows are appended to whatever you put there.  Fetch it and the log stays
cumulative; skip it and the run still succeeds, writes back a file holding only
tonight's games, and the weekly silently loses every night before this one.
That is exactly what happened from 31 Aug to 2 Sep 2026.

Never print the token, never quote it in a report, never let it reach
`chess/pending/`.

**2.  Run it.**

```
nohup python3 tools/cloud_nightly.py --max-games 25 > out/run.log 2>&1 &
```

Run it detached and poll `out/run.log`, because a busy night can exceed the
shell's ten minute limit and a foreground call gets killed part way through.
On 8 Sep that happened after fourteen games had already been fetched.

One command.  It fetches, and only if there are new games does it install
Stockfish and build a venv, because on a quiet night that setup is pure waste.
Then it analyses, annotates, distils and packs.  It prints one line of JSON.

Do not install anything yourself.  Do not run the individual scripts.

**If the run does not finish, write nothing to `chess/tools/`.**  Report the
error and stop.  A killed run has already marked tonight's games as seen in its
own copy of `intake_state.json`; publishing that would retire games that were
never delivered.  The driver only stages `intake_state.json` into `out/` once
the pack has succeeded, so the rule in practice is simple: upload what is in
`out/`, and if `intake_state.json` is not there, do not go looking for it.

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
| `games_log.jsonl` | `chess/tools/games_log.jsonl` |

The last three overwrite their `chess/tools/` copies rather than going to
pending, because tomorrow's run and the weekly read them there.  **Write
whichever of them `out/` actually contains, and nothing else.**  On a completed
run that is all three; skipping the state write makes tomorrow re-import
tonight, and skipping the log write throws away every row this run produced.
On a run that died, `intake_state.json` will not be in `out/` at all, and that
absence is the safety mechanism: leave it absent.

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
id.  He should save `chess/tools/games_log.jsonl` into that directory first, so
the Mac's copy of the log picks up the rows this job appended.

Two spaces after a period.  Avoid em dashes.
