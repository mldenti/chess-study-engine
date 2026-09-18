#!/usr/bin/env bash
# Import and analyse history, resumably, without fighting the nightly.
#
# Two phases.  Games with no row in games_log.jsonl get the full pipeline, so
# they end up indistinguishable from a game the nightly handled.  Games that
# are already logged but have no per-ply data get analyse only, since their
# annotations and log rows are already right.
#
# Every batch takes the nightly's lock, so the two never run at once.  The
# nightly's cron line must use `flock -w 3600` rather than `flock -n`, or it
# will give up instead of waiting its turn.
#
# Resumable: state lives in analysis/.backfill-*.  Re-running redoes at most
# one batch and never re-fetches.
#
# Usage:  tools/backfill.sh [YYYY-MM-DD]     (default 2026-05-01)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PY="$ROOT/.venv/bin/python"
export STOCKFISH="${STOCKFISH:-$(command -v stockfish || echo /usr/games/stockfish)}"
cd "$ROOT"; mkdir -p analysis
LOCK="$ROOT/.nightly.lock"
SINCE="${1:-2026-05-01}"
BATCH=6

pkill -x stockfish || true

if [ ! -f analysis/.backfill-fetched ]; then
  echo "$(date -Is)  fetching from $SINCE"
  python3 tools/fetch_games.py --since "$SINCE"
  touch analysis/.backfill-fetched
fi

remaining () { comm -23 <(sort "$1") <(sort "$2"); }

# ---- phase 1: games with no log row ---------------------------------------
touch analysis/.p1-done
"$PY" - > analysis/.p1-todo <<'PY'
import json, glob, os
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if False else os.getcwd()
logged = set()
p = os.path.join(root, 'tools', 'games_log.jsonl')
if os.path.exists(p):
    for line in open(p):
        try: logged.add(json.loads(line).get('file'))
        except Exception: pass
for f in sorted(glob.glob(os.path.join(root, 'games', '*.pgn'))):
    b = os.path.basename(f)
    if b not in logged:
        print('games/' + b)
PY
echo "$(date -Is)  phase 1: $(remaining analysis/.p1-todo analysis/.p1-done | wc -l) games need the full pipeline"

while :; do
  mapfile -t B < <(remaining analysis/.p1-todo analysis/.p1-done | head -$BATCH)
  [ "${#B[@]}" -eq 0 ] && break
  s=$(basename "${B[0]}" | cut -c1-8)
  q=$(printf '%02d' $(( $(ls sessions/${s}-*-analysis.md 2>/dev/null | wc -l) + 1 )))
  echo "$(date -Is)  p1 ${s}-${q}: ${#B[@]} games, $(remaining analysis/.p1-todo analysis/.p1-done | wc -l) left"
  flock -w 7200 "$LOCK" "$PY" tools/analyze.py "${B[@]}" \
    --screen-depth 16 --threads 2 --hash 64 -o "analysis/${s}-${q}.json"
  "$PY" tools/annotate.py "analysis/${s}-${q}.json" --games-dir "$ROOT/games"
  "$PY" tools/distill.py "analysis/${s}-${q}.json" --root "$ROOT" \
    --date "$s" --seq "$q" --min-loss 100 --log tools/games_log.jsonl
  printf '%s\n' "${B[@]}" >> analysis/.p1-done
done

# ---- phase 2: logged games with no per-ply data ---------------------------
touch analysis/.p2-done
"$PY" - > analysis/.p2-todo <<'PY'
import json, glob, os
root = os.getcwd()
have = set()
for f in glob.glob(os.path.join(root, 'analysis', '*.json')):
    try: d = json.load(open(f))
    except Exception: continue
    for g in d:
        if g.get('plies'): have.add(g.get('file'))
for f in sorted(glob.glob(os.path.join(root, 'games', '*.pgn'))):
    b = os.path.basename(f)
    if b not in have:
        print('games/' + b)
PY
echo "$(date -Is)  phase 2: $(remaining analysis/.p2-todo analysis/.p2-done | wc -l) games need per-ply data"

while :; do
  mapfile -t B < <(remaining analysis/.p2-todo analysis/.p2-done | head -$BATCH)
  [ "${#B[@]}" -eq 0 ] && break
  n=$(printf '%04d' $(( $(ls analysis/backfill-*.json 2>/dev/null | wc -l) + 1 )))
  echo "$(date -Is)  p2 batch $n: ${#B[@]} games, $(remaining analysis/.p2-todo analysis/.p2-done | wc -l) left"
  flock -w 7200 "$LOCK" "$PY" tools/analyze.py "${B[@]}" \
    --screen-depth 16 --threads 2 --hash 64 -o "analysis/backfill-$n.json"
  printf '%s\n' "${B[@]}" >> analysis/.p2-done
done

echo "$(date -Is)  backfill complete"
