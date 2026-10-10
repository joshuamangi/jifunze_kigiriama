"""SM-2 style scheduling as a pure function: (card state, grade, today) -> (new state, due date).

The server owns this arithmetic; clients only ever send a grade. State is written to
user_progress, never to entries (entries are shared between users).
"""

from dataclasses import dataclass
from datetime import date, timedelta

# SM-2 "quality" for each grade the interface offers.
QUALITY = {"again": 1, "hard": 3, "good": 4, "easy": 5}
MIN_EASE = 1.3
DEFAULT_EASE = 2.5
FIRST_INTERVAL = 1  # days after the first success
SECOND_INTERVAL = 6  # days after the second


@dataclass(frozen=True)
class CardState:
    interval: int = 0  # days
    ease_factor: float = DEFAULT_EASE
    repetitions: int = 0  # consecutive successful reviews


def next_state(state: CardState, grade: str, today: date) -> tuple[CardState, date]:
    quality = QUALITY[grade]
    if quality < 3:
        # A miss: start the card over and keep it in today's queue until it is answered. The
        # ease factor is left alone, as in SM-2.
        return CardState(0, state.ease_factor, 0), today

    # SM-2 updates the ease factor from this grade first, then uses it for the next interval, so
    # Easy and Hard change the very next spacing, not only the one after.
    miss = 5 - quality
    ease = round(max(MIN_EASE, state.ease_factor + 0.1 - miss * (0.08 + miss * 0.02)), 4)
    repetitions = state.repetitions + 1
    if repetitions == 1:
        interval = FIRST_INTERVAL
    elif repetitions == 2:
        interval = SECOND_INTERVAL
    else:
        interval = round(state.interval * ease)
    return CardState(interval, ease, repetitions), today + timedelta(days=interval)
