# chess-study-engine

Tooling for one person's chess study folder.  Fetches finished games from
Chess.com and Lichess, runs a Stockfish pass, writes the findings back into the
PGNs, and distils a session report plus puzzle candidates.

It exists in this repo for one specific reason: the nightly job runs as an
agent session, and anything the agent has to read or write costs tokens.
Keeping the toolchain in git means the shell clones it and the code never
passes through a model's context.  That change alone cut the nightly overhead
by roughly 35k tokens a run.

## Layout

| Script | Does | Needs |
|---|---|---|
| `fetch_games.py` | Pulls new games into `games/`, named by convention, deduped by game id | stdlib only |
| `analyze.py` | Lichess-method ACPL and flagged moves | python-chess, Stockfish |
| `annotate.py` | Writes findings into the PGNs as `[SF]` comments and NAGs | python-chess |
| `distill.py` | Session writeup and validated puzzle candidates | python-chess |
| `puzzles_lichess.py` | Lichess puzzle dashboard, tracked over time | stdlib, API token |
| `cloud_nightly.py` | Runs all of the above, and installs the engine only if there is work | stdlib |
| `reconcile.py` | Folds a cloud run's output into the real folder | stdlib |
| `promote_puzzles.py` | Moves reviewed candidates into the canonical archive | python-chess |

`CLOUD-NIGHTLY.md` is the runbook the scheduled session follows.
`NIGHTLY.md` is the older on-the-Mac variant, kept for a manual run.

## Configuration

Accounts default to the author's and are overridable:

```
CHESSCOM_USER=someone LICHESS_USER=someone python3 tools/fetch_games.py
```

Three files are deliberately not in this repo, and `.gitignore` keeps them out:
`lichess_token.txt`, `intake_state.json`, `puzzle_history.json`.  The first is a
credential.  The other two are mutable state that the nightly job reads and
rewrites, so they live where that job can write them.

## Method

ACPL uses the Lichess method: clamp every evaluation to plus or minus 1000
centipawns before differencing, treat mate as the clamp regardless of distance,
zero negative losses, average over one player's moves.  Terminal positions score
zero, because after a mating move the engine reports from the losing side and an
uncorrected clamp records the winning move as a 2000 centipawn error.

Screening runs every ply at one fixed depth and ACPL comes only from that pass,
so numbers stay comparable across games.  Flagged moves get a deeper look for a
trustworthy best line, and that pass never feeds the average.
