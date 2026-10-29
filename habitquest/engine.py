"""Pure game rules: XP curve, levels, rewards, power and achievements.

Nothing in here touches the database or the network, which keeps it trivially
testable (see ``tests/test_engine.py``).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Iterable

from . import data as D


# --------------------------------------------------------------------------
# XP curve
# --------------------------------------------------------------------------

def xp_to_next(level: int) -> int:
    """XP needed to climb from ``level`` to ``level + 1``."""
    level = max(1, int(level))
    return int(round(D.XP_BASE * (level ** D.XP_EXPONENT)))


def cumulative_xp(level: int) -> int:
    """Total lifetime XP required to *be* ``level`` (level 1 == 0 XP)."""
    level = max(1, int(level))
    return sum(xp_to_next(l) for l in range(1, level))


def level_from_xp(xp: int) -> dict:
    """Resolve a lifetime XP total into a level plus progress information."""
    xp = max(0, int(xp))
    level = 1
    while level < D.MAX_LEVEL and xp >= cumulative_xp(level + 1):
        level += 1

    floor = cumulative_xp(level)
    if level >= D.MAX_LEVEL:
        need = xp_to_next(level)
        into = need
    else:
        need = xp_to_next(level)
        into = xp - floor

    into = max(0, min(into, need))
    progress = (into / need) if need else 1.0
    return {
        "level": level,
        "level_floor_xp": floor,
        "level_xp": into,
        "level_xp_needed": need,
        "level_progress": round(progress, 4),
        "next_level_xp": floor + need,
        "max_level": level >= D.MAX_LEVEL,
    }


# --------------------------------------------------------------------------
# Rewards
# --------------------------------------------------------------------------

def streak_multiplier(streak: int) -> float:
    """Bonus earned by keeping a chain alive (capped)."""
    streak = max(1, int(streak))
    bonus = min((streak - 1) * D.STREAK_BONUS_PER_DAY, D.STREAK_BONUS_CAP)
    return 1.0 + bonus


def compute_rewards(task: dict, streak: int, is_first_today: bool) -> dict:
    """Effective XP / coin payout for completing ``task`` right now.

    ``xp`` and ``coins`` stored on a task are *base* values; difficulty,
    streak and the first-completion-of-the-day bonus all scale them.
    """
    difficulty = D.DIFFICULTY_BY_ID.get(task.get("difficulty", "easy"), D.DIFFICULTY_BY_ID["easy"])
    diff_mult = float(difficulty["multiplier"])
    sm = streak_multiplier(streak)
    daily = 1.0 + (D.DAILY_FIRST_BONUS if is_first_today else 0.0)

    total = diff_mult * sm * daily
    base_xp = max(0, int(task.get("xp", 0)))
    base_coins = max(0, int(task.get("coins", 0)))

    return {
        "xp": int(round(base_xp * total)),
        "coins": int(round(base_coins * total)),
        "base_xp": base_xp,
        "base_coins": base_coins,
        "multiplier": round(total, 3),
        "difficulty_multiplier": diff_mult,
        "streak_multiplier": round(sm, 3),
        "daily_bonus": is_first_today,
        "streak": streak,
    }


# --------------------------------------------------------------------------
# Character power
# --------------------------------------------------------------------------

def _clean_bonus(value) -> dict[str, int]:
    if not value:
        return {}
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {k: int(v) for k, v in dict(value).items() if k in D.STAT_KEYS}


def aggregate_bonuses(items: Iterable[dict]) -> dict[str, int]:
    """Sum the stat bonuses of a collection of shop items."""
    totals = {k: 0 for k in D.STAT_KEYS}
    for item in items:
        if not item:
            continue
        for stat, amount in _clean_bonus(item.get("bonus")).items():
            totals[stat] += amount
    return totals


def total_stats(stats: dict, equip_bonus: dict) -> dict[str, int]:
    return {k: int(stats.get(k, 0)) + int(equip_bonus.get(k, 0)) for k in D.STAT_KEYS}


def power_score(stats: dict, equip_bonus: dict, level: int) -> int:
    """A single number that rewards both breadth and depth."""
    combined = total_stats(stats, equip_bonus)
    stat_power = sum(combined.values()) * 3
    gear_power = sum(equip_bonus.values()) * 5
    return int(stat_power + gear_power + level * 10)


def spent_skill_points(stats: dict, base_stats: dict) -> int:
    return sum(max(0, int(stats.get(k, 0)) - int(base_stats.get(k, 0))) for k in D.STAT_KEYS)


def available_skill_points(level: int, stats: dict, base_stats: dict) -> int:
    earned = max(0, (int(level) - 1) * D.SKILL_POINTS_PER_LEVEL)
    return earned - spent_skill_points(stats, base_stats)


# --------------------------------------------------------------------------
# Timed sessions
# --------------------------------------------------------------------------

def speed_bonus(elapsed_seconds: float, duration_seconds: float) -> float:
    """Beat the Clock: reward for finishing with time to spare.

    Worth ``SPEED_BONUS_PER_10_PCT_LEFT`` for every tenth of the window still
    on the clock, capped so a very short sprint can't dwarf the quest itself.
    """
    if duration_seconds <= 0:
        return 0.0
    remaining = max(0.0, float(duration_seconds) - float(elapsed_seconds))
    tenths_left = remaining / (float(duration_seconds) / 10.0)
    return min(tenths_left * D.SPEED_BONUS_PER_10_PCT_LEFT, D.SPEED_BONUS_CAP)


def session_bonus(mode: str, elapsed_seconds: float, duration_seconds: float) -> float:
    """The mode-specific bonus multiplier minus one (0.0 means no bonus)."""
    if mode == "beat_clock":
        return speed_bonus(elapsed_seconds, duration_seconds)
    if mode == "endure":
        return D.ENDURE_BONUS
    return 0.0


def session_rewards(task: dict, streak: int, is_first_today: bool, mode: str,
                    elapsed_seconds: float, duration_seconds: float) -> dict:
    """Full payout for a finished timed session, before any wounded penalty."""
    rewards = compute_rewards(task, streak, is_first_today)
    bonus = session_bonus(mode, elapsed_seconds, duration_seconds)
    rewards["xp"] = int(round(rewards["xp"] * (1.0 + bonus)))
    rewards["coins"] = int(round(rewards["coins"] * (1.0 + bonus)))
    rewards["session_bonus"] = round(bonus, 3)
    rewards["speed_bonus"] = round(bonus, 3) if mode == "beat_clock" else 0.0
    rewards["endure_bonus"] = round(bonus, 3) if mode == "endure" else 0.0
    return rewards


def apply_wounded_penalty(rewards: dict, wounded: bool) -> dict:
    """A hero on 0 HP earns less gold until they recover."""
    if not wounded:
        return rewards
    out = dict(rewards)
    out["coins"] = int(round(rewards["coins"] * D.WOUNDED_COIN_MULTIPLIER))
    out["wounded"] = True
    return out


def session_outcome(mode: str, elapsed_seconds: float, duration_seconds: float,
                    grace: float = D.SESSION_GRACE_SECONDS) -> str:
    """Classify a finish attempt without touching storage.

    Returns ``"won"``, ``"hit"`` (Beat the Clock ran out) or ``"too_early"``
    (Stay the Course tried to finish before the time was served).
    """
    elapsed = max(0.0, float(elapsed_seconds))
    duration = max(0.0, float(duration_seconds))
    if mode == "beat_clock":
        return "won" if elapsed <= duration + grace else "hit"
    if mode == "endure":
        return "won" if elapsed + grace >= duration else "too_early"
    return "won"


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------

def max_hp(stats: dict, level: int = 1) -> int:
    """Maximum health grows with Vitality and with every level the hero earns.

    The old two-argument form is preserved for migrations and tests: a missing
    level simply means level 1.
    """
    return (D.MAX_HP_BASE + max(0, int(stats.get("vit", 0))) * D.MAX_HP_PER_VIT
            + max(0, int(level) - 1) * D.MAX_HP_PER_LEVEL)


def miss_damage(difficulty: str, maximum_hp: int) -> int:
    """Damage for a daily habit that never happened, scaled by difficulty."""
    return hit_damage(difficulty, maximum_hp)


def hit_damage(difficulty: str, maximum_hp: int) -> int:
    """Damage taken when the bell catches you out, scaled by difficulty."""
    pct = D.HIT_DAMAGE_PCT.get(difficulty, D.HIT_DAMAGE_PCT["easy"])
    return max(1, int(round(max(1, int(maximum_hp)) * pct)))


def heal_per_completion(maximum_hp: int) -> int:
    return max(D.HEAL_MIN_PER_COMPLETION,
               int(round(max(1, int(maximum_hp)) * D.HEAL_PCT_PER_COMPLETION)))


def rest_heal(maximum_hp: int) -> int:
    return max(1, int(round(max(1, int(maximum_hp)) * D.REST_HEAL_PCT_PER_DAY)))


# --------------------------------------------------------------------------
# Streaks / calendar helpers
# --------------------------------------------------------------------------

def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# Quest schedules
# --------------------------------------------------------------------------

# Stored schedules are the sorted ISO weekday numbers a quest is available on,
# e.g. "1,2,3,4,5" for weekdays. An empty string means every day, which is how
# saves written before scheduling existed are read.

def days_list(value) -> list[int]:
    """The weekday numbers (Mon=1 .. Sun=7) in a stored schedule."""
    if value is None or value == "":
        return list(D.WEEKDAY_IDS)
    if isinstance(value, str):
        parts = [p for p in value.replace(" ", "").split(",") if p]
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return list(D.WEEKDAY_IDS)
    picked = set()
    for part in parts:
        try:
            number = int(part)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 7:
            picked.add(number)
    return sorted(picked) or list(D.WEEKDAY_IDS)


def normalise_days(value) -> str:
    """Canonical storage for a schedule; every day is stored as ''. """
    picked = days_list(value)
    if len(picked) == 7:
        return ""
    return ",".join(str(n) for n in picked)


def days_label(value) -> str:
    """A short human label: "Every day", "Weekends", "Mon-Fri", ..."""
    picked = days_list(value)
    if len(picked) == 7:
        return "Every day"
    if picked == [1, 2, 3, 4, 5]:
        return "Weekdays"
    if picked == [6, 7]:
        return "Weekends"
    if len(picked) > 1 and picked[-1] - picked[0] == len(picked) - 1:
        return f"{D.WEEKDAY_BY_ID[picked[0]]['label']}\u2013{D.WEEKDAY_BY_ID[picked[-1]]['label']}"
    return ", ".join(D.WEEKDAY_BY_ID[n]["label"] for n in picked)


def day_is_due(value, weekday: int) -> bool:
    """Is a quest with this schedule available on ``weekday`` (Mon=1 .. Sun=7)?"""
    return int(weekday) in days_list(value)


def max_window(value) -> int:
    """The longest finish window a schedule can allow without overlapping itself.

    A quest's occurrence opens on a scheduled day and stays open for the window.
    If the window reached the next scheduled day the two would be on the board at
    once, so the window can be no longer than the shortest gap between starts: a
    quest that runs every day has a window of one day, and a quest that runs on a
    single weekday can stay open all week.
    """
    picked = days_list(value)
    if not picked:
        return 1                      # '' means every day: no room at all
    if len(picked) == 1:
        return 7
    gaps = []
    for index, start in enumerate(picked):
        following = picked[(index + 1) % len(picked)]
        gap = (following - start) % 7
        gaps.append(gap or 7)
    return max(1, min(gaps))


def window_span(day, value, window: int = 1):
    """The occurrence window covering ``day`` as ``(first_day, last_day)``.

    Windows never overlap (see :func:`max_window`), so a day belongs to at most
    one of them. ``None`` means no window is open that day: the quest is resting.
    """
    width = max(1, int(window or 1))
    if not isinstance(day, date):
        day = parse_date(day)
        if day is None:
            return None
    for offset in range(width):
        start = day - timedelta(days=offset)
        if day_is_due(value, start.isoweekday()):
            return start, start + timedelta(days=width - 1)
    return None


def window_start(day, value, window: int = 1):
    """The day the occurrence covering ``day`` opened, or ``None``."""
    span = window_span(day, value, window)
    return span[0] if span else None


def _skipped_set(days) -> frozenset[str]:
    """Normalise a collection of skipped days into ISO date strings."""
    if not days:
        return frozenset()
    if isinstance(days, str):
        days = [days]
    out = set()
    for value in days:
        parsed = value if isinstance(value, date) else parse_date(value)
        if parsed is not None:
            out.add(parsed.isoformat())
    return frozenset(out)


def _occurrences(dates: Iterable[str], schedule, window: int) -> list[date]:
    """Collapse completion days into the occurrence each one closed.

    One occurrence is one link in the chain, so finishing Tuesday's grace day
    and then the same window again (which play cannot do, but old saves and
    undos can) must not count twice.
    """
    width = max(1, int(window or 1))
    starts = set()
    for value in dates:
        parsed = parse_date(value)
        if parsed is None:
            continue
        span = window_span(parsed, schedule, width)
        starts.add(span[0] if span else parsed)
    return sorted(starts)


def _window_gap_clear(prev: date, until: date, schedule, window: int,
                      skipped: frozenset[str]) -> bool:
    """True when no uncompleted occurrence window closed between two dates.

    A streak is counted in occurrences, not calendar days: a quest with a
    five-day window is still done on time when it is finished on the fourth day.
    The window of the earlier date always ends in a completion, so it can never
    break the run; any later window that closes before ``until`` uncompleted -
    and was not skipped - does. Days outside a window, and days inside a window
    that is still open, are rest days: they neither add nor break a streak.
    """
    width = max(1, int(window or 1))
    span = window_span(prev, schedule, width)
    grace_end = span[1] if span else prev + timedelta(days=width - 1)
    day = prev + timedelta(days=1)
    while day < until:
        if day > grace_end:
            closing = window_span(day, schedule, width)
            if closing is not None and closing[1] == day:
                covered = {(closing[0] + timedelta(days=i)).isoformat()
                           for i in range(width)}
                if not (covered & set(skipped)):
                    return False
        day += timedelta(days=1)
    return True


def next_streak(last_date: str | None, today: str, current: int,
                schedule=None, skipped=None, window: int = 1) -> int:
    """Where a task's streak lands when completed again today.

    Days the quest is not scheduled on - and days it was skipped - are rest
    days: they neither add to the streak nor break it, so a Mon-Fri habit keeps
    its run over the weekend and a skipped Wednesday does not cost the chain.
    A finish window pushes the same idea further out: an occurrence is only late
    once its window has closed, however many days that takes.
    """
    if not last_date:
        return 1
    last = parse_date(last_date)
    now = parse_date(today)
    if last is None or now is None:
        return 1
    delta = (now - last).days
    if delta <= 0:
        return max(1, int(current))          # already counted today
    if _window_gap_clear(last, now, schedule, window, _skipped_set(skipped)):
        return max(1, int(current)) + 1      # chain continues across rest days
    return 1                                  # an occurrence was missed


def longest_day_run(dates: Iterable[str], schedule=None, skipped=None,
                    window: int = 1) -> int:
    """Longest run of occurrences present in ``dates``."""
    rest = _skipped_set(skipped)
    unique = _occurrences(dates, schedule, window)
    if not unique:
        return 0
    best = run = 1
    for prev, cur in zip(unique, unique[1:]):
        run = run + 1 if _window_gap_clear(prev, cur, schedule, window, rest) else 1
        best = max(best, run)
    return best


def current_streak(dates: Iterable[str], schedule=None, today: str | None = None,
                   skipped=None, window: int = 1) -> int:
    """The run that is still alive: its last completion is today, or the only
    days since then were rest days."""
    rest = _skipped_set(skipped)
    unique = _occurrences(dates, schedule, window)
    if not unique:
        return 0
    now = parse_date(today) if today else date.today()
    if now is None:
        now = date.today()
    if not _window_gap_clear(unique[-1], now, schedule, window, rest):
        return 0
    run = 1
    for prev, cur in zip(reversed(unique), reversed(unique[:-1])):
        if _window_gap_clear(prev, cur, schedule, window, rest):
            run += 1
        else:
            break
    return run


def now_stamp() -> str:
    """Timestamp with sub-second precision, used for session deadlines."""
    return datetime.now().isoformat(timespec="milliseconds")


def parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def seconds_between(start: str | None, end: str | None) -> float:
    """Whole seconds from ``start`` to ``end`` (never negative)."""
    first, second = parse_stamp(start), parse_stamp(end)
    if first is None or second is None:
        return 0.0
    return max(0.0, (second - first).total_seconds())


def date_range(days: int, end: str | None = None) -> list[str]:
    """ISO dates for the last ``days`` days, oldest first (inclusive of end)."""
    end_date = parse_date(end) if end else date.today()
    if end_date is None:
        end_date = date.today()
    start = end_date - timedelta(days=max(1, days) - 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(max(1, days))]


def heat_level(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    if count <= 5:
        return 3
    return 4


# --------------------------------------------------------------------------
# Achievements
# --------------------------------------------------------------------------

def achievement_progress(track: str, metrics: dict) -> tuple[int, int, int]:
    """(progress, goal, percent) for one achievement track."""
    goal = 0
    for ach in D.ACHIEVEMENTS:
        if ach["track"] == track:
            goal = int(ach["goal"])
            break
    progress = int(metrics.get(track, 0) or 0)
    if goal <= 0:
        return progress, 0, 100
    percent = min(100, int(round(progress / goal * 100)))
    return progress, goal, percent


def evaluate_achievements(track_values: dict) -> dict[str, dict]:
    """Return ``{achievement_id: {progress, goal, percent, unlocked}}``."""
    out: dict[str, dict] = {}
    for ach in D.ACHIEVEMENTS:
        track = ach["track"]
        goal = int(ach["goal"])
        progress = int(track_values.get(track, 0) or 0)
        out[ach["id"]] = {
            "id": ach["id"],
            "progress": progress,
            "goal": goal,
            "percent": 100 if goal <= 0 else min(100, int(round(progress / goal * 100))),
            "unlocked": progress >= goal,
        }
    return out


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def clamp_float(value, low: float, high: float, default: float = 0.0) -> float:
    try:
        num = float(value)
    except (ValueError, TypeError):
        num = default
    if math.isnan(num) or math.isinf(num):
        num = default
    return max(low, min(high, num))
