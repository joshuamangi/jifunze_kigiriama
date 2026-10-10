from datetime import date, timedelta

import pytest

from app.services.srs import MIN_EASE, CardState, next_state

TODAY = date(2026, 10, 10)


def run(grades, start=None):
    state, due, history = start or CardState(), TODAY, []
    for grade in grades:
        state, due = next_state(state, grade, TODAY)
        history.append((state.interval, state.repetitions, state.ease_factor, due))
    return state, history


def test_good_reviews_follow_one_six_then_grow_by_the_ease_factor():
    _, history = run(["good"] * 5)
    assert [h[0] for h in history] == [1, 6, 15, 38, 95]  # 6*2.5, 15*2.5, 38*2.5
    assert [h[3] for h in history][:3] == [
        TODAY + timedelta(days=1),
        TODAY + timedelta(days=6),
        TODAY + timedelta(days=15),
    ]
    assert all(h[2] == 2.5 for h in history)  # quality 4 leaves the ease factor unchanged


def test_intervals_keep_growing_after_good_grades():
    _, history = run(["good"] * 8)
    intervals = [h[0] for h in history]
    assert intervals == sorted(set(intervals))


def test_easy_grows_faster_and_hard_slower_than_good():
    easy, _ = run(["good", "good", "easy"])
    good, _ = run(["good", "good", "good"])
    hard, _ = run(["good", "good", "hard"])
    assert (easy.interval, good.interval, hard.interval) == (
        16,
        15,
        14,
    )  # 6 x 2.6, 6 x 2.5, 6 x 2.36
    assert easy.ease_factor == 2.6
    assert hard.ease_factor == 2.36


def test_again_resets_the_card_and_keeps_it_due_today():
    learned, _ = run(["good", "good", "good"])
    assert learned.interval == 15
    state, due = next_state(learned, "again", TODAY)
    assert (state.interval, state.repetitions, due) == (0, 0, TODAY)
    assert state.ease_factor == learned.ease_factor  # a miss does not change the ease factor


def test_after_a_miss_the_next_success_starts_again_at_one_day():
    state, due = next_state(CardState(15, 2.5, 3), "again", TODAY)
    state, due = next_state(state, "good", TODAY)
    assert (state.interval, state.repetitions, due) == (1, 1, TODAY + timedelta(days=1))


def test_ease_factor_never_drops_below_the_minimum():
    state, _ = run(["good"] + ["hard"] * 30)
    assert state.ease_factor == MIN_EASE


def test_a_new_card_state_is_the_sm2_default():
    assert CardState() == CardState(interval=0, ease_factor=2.5, repetitions=0)


def test_next_state_does_not_modify_its_input():
    before = CardState(6, 2.5, 2)
    next_state(before, "good", TODAY)
    assert before == CardState(6, 2.5, 2)


def test_unknown_grade_is_an_error():
    with pytest.raises(KeyError):
        next_state(CardState(), "perfect", TODAY)
