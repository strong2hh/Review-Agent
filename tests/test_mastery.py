from datetime import datetime

from app.services.mastery import compute_interval_days, score_to_star, update_mastery_and_schedule


def test_score_to_star_mapping():
    assert score_to_star(0) == 0
    assert score_to_star(19) == 0
    assert score_to_star(20) == 1
    assert score_to_star(40) == 2
    assert score_to_star(60) == 3
    assert score_to_star(75) == 4
    assert score_to_star(90) == 5


def test_interval_adaptive_factor():
    assert compute_interval_days(0, 0) == 1
    assert compute_interval_days(3, 5) >= 14


def test_mastery_update_and_next_review():
    now = datetime(2026, 1, 1, 0, 0, 0)
    mastery, stage, next_review_at, star = update_mastery_and_schedule(2.0, 2, 92, now)

    assert star == 5
    assert mastery == 2.9
    assert stage == 3
    assert next_review_at > now
