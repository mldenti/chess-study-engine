# Weekly runbook

You are a scheduled session with no access to Mitch's Mac.  Expected.  Do not
look for the device tools.

This is the counterpart to the nightly.  The nightly is deliberately mechanical
and thinks about nothing.  **This job is where the thinking happens**, and it is
the only thing standing between the folder and a slow pile of writeups nobody
ever folds in.

But thinking is expensive, so it is rationed: the arithmetic runs first, and you
only read the knowledge doc if the arithmetic found something worth checking it
against.

## Steps

**1.  Toolchain and state.**

```
git clone --depth 1 https://github.com/mldenti/chess-study-engine.git tools
```

Do not read the scripts.  Then fetch these two from the project into `tools/`:

```
chess/tools/games_log.jsonl        one row per analysed game
chess/tools/puzzle_history.json    dated puzzle snapshots
```

If `games_log.jsonl` is missing, report that and stop.  It is the only trend
source; without it there is nothing to say.

**2.  Run the arithmetic.**

```
python3 tools/weekly_digest.py --weeks 6
```

It writes `out/weekly-YYYYMMDD.md` and prints a JSON summary.  Note the
`anything_moved` field; the next step depends on it.

**3.  Branch on whether anything moved.**

**If `anything_moved` is false:** write the digest to `chess/pending/`, report in
one line that the week was flat, and **stop**.  Do not read the knowledge doc.
Do not go looking for something to say.  A quiet week that produces a quiet
report is the system working, not failing.

**If `anything_moved` is true:** now read
`chess/knowledge/chess-lessons-and-method.md`, and only now.  Compare what moved
against what that document claims.  You are looking for exactly one thing:

> Does anything in this week's numbers contradict a claim the knowledge files
> currently make?

Some worked examples of what counts, so the bar is clear.

- `lessons.md` ranks the two-step scan first because `leftHanging` and
  `missedCapture` dominate.  If those two have faded and something else has
  taken over, the ranking is stale.
- `lessons.md` says daily accuracy beats rapid, on eight games.  More daily
  games either firm that up or break it.  Either is worth saying.
- `endgames.md` and `tactics.md` name specific triggers.  A motif that is
  written up there and still recurring means the trigger is not firing at the
  board, which is a different problem from not knowing the pattern, and belongs
  in `lessons.md` as a recurrence rather than as a new pattern.
- A puzzle theme that improved after being named a weak spot is the one piece of
  evidence in this whole system that studying something worked.  Say so.

What does not count: a number moving inside the noise thresholds, a single bad
game, a rating change, or anything you had to squint at.  The script already
filtered for size and sample; do not reintroduce what it screened out.

**4.  Write it back.**

| From | To |
|---|---|
| `out/weekly-*.md` | `chess/pending/` same name |

Use `local_path`.  If you found contradictions, append a section to that file
headed `## Proposed knowledge changes`, and for each one give the file, the
claim as it currently stands, and the replacement you would write.  Be specific
enough that applying it is mechanical.

**Do not edit `chess/knowledge/chess-lessons-and-method.md` yourself.**  It
mirrors the Mac folder and the next sync would overwrite you.  Propose; Mitch
applies.

**5.  Report.**

If nothing moved: one line.

If something did: lead with the contradiction, then the numbers behind it, then
what you propose changing.  Three or four sentences.  Do not restate the digest;
it is in `chess/pending/` and he reads it there.

## Judgement notes

Be hard to convince.  This job runs 52 times a year and its value depends
entirely on the reader trusting that when it says something changed, something
changed.  One week of 20 games is a small sample and the honest answer most
weeks is that nothing is distinguishable from noise.

When you do report something, say what would falsify it and how long that would
take.  "Rapid is worse by 13 over 36 games" is useful.  "Rapid is getting worse"
is not, because it hides how thin the evidence is.

Two spaces after a period.  Avoid em dashes.
