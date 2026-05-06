from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil

BASE_INTERVALS = [1, 2, 4, 7, 15, 30]
STAR_FACTORS = {
    0: 0.6,
    1: 0.8,
    2: 1.0,
    3: 1.2,
    4: 1.5,
    5: 2.0,
}


def score_to_star(score_0_100: int) -> int:
    if score_0_100 <= 19:
        return 0
    if score_0_100 <= 39:
        return 1
    if score_0_100 <= 59:
        return 2
    if score_0_100 <= 74:
        return 3
    if score_0_100 <= 89:
        return 4
    return 5


def _next_stage(old_stage: int, current_star: int) -> int:
    stage = max(0, min(old_stage, len(BASE_INTERVALS) - 1))
    if current_star >= 4:
        stage += 1
    elif current_star <= 1:
        stage -= 1
    return max(0, min(stage, len(BASE_INTERVALS) - 1))


def compute_interval_days(stage: int, star: int) -> int:
    stage = max(0, min(stage, len(BASE_INTERVALS) - 1))
    star = max(0, min(star, 5))
    days = ceil(BASE_INTERVALS[stage] * STAR_FACTORS[star])
    return max(1, days)


def update_mastery_and_schedule(
    old_mastery: float,
    old_stage: int,
    score_0_100: int,
    now: datetime,
) -> tuple[float, int, datetime, int]:
    current_star = score_to_star(score_0_100)
    new_mastery = round(0.7 * old_mastery + 0.3 * current_star, 1)
    new_stage = _next_stage(old_stage, current_star)
    days = compute_interval_days(new_stage, current_star)
    next_review_at = now + timedelta(days=days)
    return new_mastery, new_stage, next_review_at, current_star
