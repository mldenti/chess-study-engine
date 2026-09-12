#!/usr/bin/env python3
"""Lichess-vocabulary motif tags for a single move.

Shared by analyze.py, which writes the tags into the analysis JSON that is
kept, and distill.py, which uses them for the session writeup and the puzzle
candidates.  It lives in its own module so that the two agree by construction
rather than by coincidence, and so that the tags survive in the file the
database is built from rather than only in the prose writeup.
"""
import chess

MOTIF_TAGS = {"missedCapture", "missedCheck", "missedCaptureWithCheck", "missedMate",
              "checkedInsteadOfCaptured", "leftHanging", "wrongCapture", "wrongCheck",
              "quietMove"}

VALUE = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
         chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}


def hanging_gain(board):
    """Best net material the side to move can win with a single capture.

    A cheap stand-in for static exchange evaluation: take the captured piece,
    give back the capturing piece if the square is defended.
    """
    best = 0
    for m in board.legal_moves:
        if not board.is_capture(m):
            continue
        victim = board.piece_at(m.to_square)
        gain = VALUE[chess.PAWN] if board.is_en_passant(m) else VALUE[victim.piece_type]
        attacker = board.piece_at(m.from_square)
        board.push(m)
        defended = board.is_attacked_by(board.turn, m.to_square)
        board.pop()
        if defended:
            gain -= VALUE[attacker.piece_type]
        best = max(best, gain)
    return best


def phase_of(board):
    men = len(board.piece_map())
    if men <= 10:
        return "endgame"
    if board.fullmove_number <= 10:
        return "opening"
    return "middlegame"


def motifs(fen_before, played_san, best_san, loss):
    """Lichess-vocabulary tags for one mistake."""
    tags = set()
    b = chess.Board(fen_before)
    tags.add(phase_of(b))
    try:
        played = b.parse_san(played_san)
    except ValueError:
        played = None
    try:
        best = b.parse_san(best_san) if best_san else None
    except ValueError:
        best = None

    if best is not None:
        if b.is_capture(best) and (played is None or not b.is_capture(played)):
            tags.add("missedCapture")
        if b.gives_check(best) and (played is None or not b.gives_check(played)):
            tags.add("missedCheck")
        if b.is_capture(best) and b.gives_check(best):
            tags.add("missedCaptureWithCheck")
        b.push(best)
        if b.is_checkmate():
            tags.add("missedMate")
        b.pop()

    if played is not None:
        if b.gives_check(played) and best is not None and b.is_capture(best) \
                and not b.is_capture(played):
            # the check-before-capture habit already written up in endgames.md
            tags.add("checkedInsteadOfCaptured")
        b.push(played)
        if hanging_gain(b) >= 200:
            tags.add("leftHanging")
        b.pop()

    tags.add("blunder" if loss >= 300 else ("mistake" if loss >= 150 else "inaccuracy"))
    return sorted(tags)
