"""Static game content: the rules of the world, in one place.

Everything here is data only. No I/O, no persistence - see ``engine.py`` for the
maths that consumes it and ``store.py`` for how it is stored.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Character stats
# --------------------------------------------------------------------------

# (key, label, icon, blurb)
STATS: list[tuple[str, str, str, str]] = [
    ("str", "Strength", "STR", "Discipline and heavy lifting."),
    ("int", "Intellect", "INT", "Study, focus and deep work."),
    ("vit", "Vitality", "VIT", "Health, sleep and body care."),
    ("agi", "Agility", "AGI", "Speed, tidiness and quick wins."),
    ("cha", "Charisma", "CHA", "People, creativity and expression."),
]

STAT_KEYS: list[str] = [s[0] for s in STATS]
STAT_LABELS: dict[str, str] = {s[0]: s[1] for s in STATS}
STAT_ABBR: dict[str, str] = {s[0]: s[2] for s in STATS}
STAT_BLURBS: dict[str, str] = {s[0]: s[3] for s in STATS}

# --------------------------------------------------------------------------
# Archetypes
# --------------------------------------------------------------------------

ARCHETYPES: list[dict] = [
    {
        "id": "warrior",
        "name": "Warrior",
        "icon": "🛡️",
        "blurb": "Forged by routine. Strength and Vitality lead the way.",
        "stats": {"str": 6, "vit": 6, "agi": 3, "int": 2, "cha": 1},
        "color": "#ef4444",
    },
    {
        "id": "mage",
        "name": "Mage",
        "icon": "🔮",
        "blurb": "A mind sharpened by study. Intellect first, always.",
        "stats": {"int": 7, "cha": 5, "agi": 3, "vit": 2, "str": 1},
        "color": "#8b5cf6",
    },
    {
        "id": "rogue",
        "name": "Rogue",
        "icon": "🗡️",
        "blurb": "Fast hands, faster habits. Agility wins the day.",
        "stats": {"agi": 7, "int": 4, "cha": 4, "str": 2, "vit": 1},
        "color": "#22d3ee",
    },
    {
        "id": "ranger",
        "name": "Ranger",
        "icon": "🏹",
        "blurb": "Balanced and relentless. Endurance over everything.",
        "stats": {"agi": 5, "vit": 5, "str": 5, "int": 2, "cha": 1},
        "color": "#22c55e",
    },
]

ARCHETYPE_BY_ID: dict[str, dict] = {a["id"]: a for a in ARCHETYPES}

# --------------------------------------------------------------------------
# Rarity
# --------------------------------------------------------------------------

RARITIES: list[str] = ["common", "uncommon", "rare", "epic", "legendary"]

RARITY_LABELS: dict[str, str] = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "epic": "Epic",
    "legendary": "Legendary",
}

RARITY_COLORS: dict[str, str] = {
    "common": "#9aa4b2",
    "uncommon": "#3fb950",
    "rare": "#3b82f6",
    "epic": "#a855f7",
    "legendary": "#f59e0b",
}

# --------------------------------------------------------------------------
# Equipment slots
# --------------------------------------------------------------------------

SLOTS: list[dict] = [
    {"id": "weapon", "label": "Weapon", "icon": "⚔️"},
    {"id": "head", "label": "Head", "icon": "🪖"},
    {"id": "body", "label": "Body", "icon": "🧥"},
    {"id": "boots", "label": "Boots", "icon": "🥾"},
    {"id": "accessory", "label": "Accessory", "icon": "💍"},
]

SLOT_IDS: list[str] = [s["id"] for s in SLOTS]
SLOT_LABELS: dict[str, str] = {s["id"]: s["label"] for s in SLOTS}

# --------------------------------------------------------------------------
# Shop catalog
# --------------------------------------------------------------------------

ITEMS: list[dict] = [
    # --- weapons -----------------------------------------------------------
    {"id": "wooden_sword", "name": "Wooden Sword", "slot": "weapon", "rarity": "common",
     "price": 60, "level_req": 1, "icon": "🗡️", "bonus": {"str": 1},
     "desc": "A training blade. Humble, but it shows up every day."},
    {"id": "iron_sword", "name": "Iron Sword", "slot": "weapon", "rarity": "uncommon",
     "price": 220, "level_req": 2, "icon": "⚔️", "bonus": {"str": 3},
     "desc": "Reliable steel for a disciplined hand."},
    {"id": "elven_blade", "name": "Elven Blade", "slot": "weapon", "rarity": "rare",
     "price": 700, "level_req": 4, "icon": "🌿", "bonus": {"str": 5, "agi": 2},
     "desc": "Light as a promise, sharp as a deadline."},
    {"id": "dragonfang", "name": "Dragonfang", "slot": "weapon", "rarity": "epic",
     "price": 1800, "level_req": 8, "icon": "🐉", "bonus": {"str": 9, "vit": 3},
     "desc": "Carved from a beast that never missed a morning."},
    {"id": "excalibur", "name": "Excalibur", "slot": "weapon", "rarity": "legendary",
     "price": 4200, "level_req": 12, "icon": "✨", "bonus": {"str": 14, "cha": 5},
     "desc": "Only the consistently worthy may hold it."},

    # --- head --------------------------------------------------------------
    {"id": "leather_cap", "name": "Leather Cap", "slot": "head", "rarity": "common",
     "price": 50, "level_req": 1, "icon": "🧢", "bonus": {"vit": 1},
     "desc": "Keeps the sun - and excuses - out of your eyes."},
    {"id": "iron_helm", "name": "Iron Helm", "slot": "head", "rarity": "uncommon",
     "price": 200, "level_req": 2, "icon": "🪖", "bonus": {"vit": 3},
     "desc": "Dented in the great battle of Waking Up On Time."},
    {"id": "mage_hood", "name": "Archmage Hood", "slot": "head", "rarity": "rare",
     "price": 650, "level_req": 4, "icon": "🎩", "bonus": {"int": 5},
     "desc": "Woven from late nights and good notes."},
    {"id": "crown_of_ages", "name": "Crown of Ages", "slot": "head", "rarity": "epic",
     "price": 1700, "level_req": 8, "icon": "👑", "bonus": {"cha": 8, "int": 2},
     "desc": "Worn by those whose habits outlived their motivation."},
    {"id": "dragon_helm", "name": "Dragonscale Helm", "slot": "head", "rarity": "legendary",
     "price": 3800, "level_req": 12, "icon": "🛡️", "bonus": {"vit": 10, "str": 4},
     "desc": "Nothing gets through it. Not even a skipped day."},

    # --- body --------------------------------------------------------------
    {"id": "cloth_tunic", "name": "Cloth Tunic", "slot": "body", "rarity": "common",
     "price": 55, "level_req": 1, "icon": "👕", "bonus": {"agi": 1},
     "desc": "Comfortable. Flexible. Ready for a quick start."},
    {"id": "chainmail", "name": "Chainmail Vest", "slot": "body", "rarity": "uncommon",
     "price": 240, "level_req": 2, "icon": "🥋", "bonus": {"vit": 4},
     "desc": "Every link a logged habit."},
    {"id": "ranger_cloak", "name": "Ranger's Cloak", "slot": "body", "rarity": "rare",
     "price": 680, "level_req": 4, "icon": "🧥", "bonus": {"agi": 5, "int": 1},
     "desc": "You move quietly from task to task."},
    {"id": "plate_armor", "name": "Obsidian Plate", "slot": "body", "rarity": "epic",
     "price": 1750, "level_req": 8, "icon": "🛡️", "bonus": {"vit": 9, "str": 1},
     "desc": "Heavy, and worth every ounce."},
    {"id": "celestial_robe", "name": "Celestial Robe", "slot": "body", "rarity": "legendary",
     "price": 4000, "level_req": 12, "icon": "🌌", "bonus": {"int": 10, "cha": 4},
     "desc": "Stitched from the quiet hours nobody sees."},

    # --- boots -------------------------------------------------------------
    {"id": "worn_boots", "name": "Worn Boots", "slot": "boots", "rarity": "common",
     "price": 45, "level_req": 1, "icon": "👞", "bonus": {"agi": 1},
     "desc": "Miles of small steps already behind them."},
    {"id": "swift_sandals", "name": "Swift Sandals", "slot": "boots", "rarity": "uncommon",
     "price": 190, "level_req": 2, "icon": "🩴", "bonus": {"agi": 3},
     "desc": "For errands run before the mood arrives."},
    {"id": "boots_of_speed", "name": "Boots of Speed", "slot": "boots", "rarity": "rare",
     "price": 620, "level_req": 4, "icon": "🥾", "bonus": {"agi": 5, "vit": 1},
     "desc": "The gap between wanting and doing, closed."},
    {"id": "shadowstep_boots", "name": "Shadowstep Boots", "slot": "boots", "rarity": "epic",
     "price": 1650, "level_req": 8, "icon": "🌑", "bonus": {"agi": 8, "int": 2},
     "desc": "You are simply... already at the desk."},
    {"id": "winged_boots", "name": "Winged Boots", "slot": "boots", "rarity": "legendary",
     "price": 3600, "level_req": 12, "icon": "🪽", "bonus": {"agi": 12, "cha": 2},
     "desc": "Momentum made physical."},

    # --- accessory ---------------------------------------------------------
    {"id": "copper_ring", "name": "Copper Ring", "slot": "accessory", "rarity": "common",
     "price": 40, "level_req": 1, "icon": "💍", "bonus": {"cha": 1},
     "desc": "Cheap, shiny, and a reminder of day one."},
    {"id": "amulet_of_focus", "name": "Amulet of Focus", "slot": "accessory", "rarity": "uncommon",
     "price": 210, "level_req": 2, "icon": "📿", "bonus": {"int": 3},
     "desc": "One task at a time. Nothing else gets in."},
    {"id": "ring_of_vitality", "name": "Ring of Vitality", "slot": "accessory", "rarity": "rare",
     "price": 640, "level_req": 4, "icon": "💚", "bonus": {"vit": 5},
     "desc": "Water, walks, and an actual bedtime."},
    {"id": "eye_of_the_oracle", "name": "Eye of the Oracle", "slot": "accessory", "rarity": "epic",
     "price": 1600, "level_req": 8, "icon": "👁️", "bonus": {"int": 7, "cha": 3},
     "desc": "It sees the version of you that finishes things."},
    {"id": "phoenix_heart", "name": "Phoenix Heart", "slot": "accessory", "rarity": "legendary",
     "price": 3900, "level_req": 12, "icon": "❤️‍🔥", "bonus": {"vit": 8, "str": 6},
     "desc": "Break the streak, and you rise anyway."},
]

ITEM_BY_ID: dict[str, dict] = {i["id"]: i for i in ITEMS}

# --------------------------------------------------------------------------
# Achievements
# --------------------------------------------------------------------------

# Achievements are grouped into *stacks*: tiers on a single track. The Journal
# shows one card per stack - the next tier still to earn - so a long ladder
# never floods the page. ``tier`` is the 1-based position inside its family.
ACHIEVEMENTS: list[dict] = []


def _stack(family: str, track: str, tiers: list[tuple]) -> None:
    """Append one family of achievement tiers, lowest goal first."""
    for position, tier in enumerate(tiers, start=1):
        goal, ach_id, name, icon, desc = tier
        ACHIEVEMENTS.append({
            "id": ach_id, "name": name, "icon": icon, "desc": desc,
            "goal": int(goal), "track": track,
            "family": family, "tier": position,
        })


# Quest completions, lifetime.
_stack("quests", "total_completions", [
    (1, "first_step", "First Step", "🌱", "Complete your very first quest."),
    (10, "warming_up", "Warming Up", "🔥", "Complete 10 quests."),
    (25, "habit_forming", "Habit Forming", "🔁", "Complete 25 quests."),
    (50, "steady_hand", "Steady Hand", "✋", "Complete 50 quests."),
    (100, "centurion", "Centurion", "💯", "Complete 100 quests."),
    (250, "quest_machine", "Quest Machine", "⚙️", "Complete 250 quests."),
    (500, "half_a_thousand", "Half a Thousand", "🏅", "Complete 500 quests."),
    (1_000, "legend_board", "Legend of the Board", "👑", "Complete 1,000 quests."),
])

# A single quest's streak, which skips the days it is not scheduled for.
_stack("task_streak", "best_task_streak", [
    (3, "streak_3", "Three in a Row", "3️⃣", "Hold a 3-day streak on any quest."),
    (7, "streak_7", "Unbroken Week", "📅", "Hold a 7-day streak on any quest."),
    (30, "streak_30", "Thirty Days", "🗓️", "Hold a 30-day streak on any quest."),
    (90, "streak_90", "A Season of Showing Up", "🍂",
     "Hold a 90-day streak on any quest."),
    (180, "streak_180", "Half-Year Habit", "🌗", "Hold a 180-day streak on any quest."),
    (365, "streak_365", "Year of the Hero", "🎉", "Hold a 365-day streak on any quest."),
])

_stack("level", "level", [
    (5, "level_5", "Seasoned", "⭐", "Reach level 5."),
    (10, "level_10", "Champion", "🌟", "Reach level 10."),
    (20, "level_20", "Mythic", "💫", "Reach level 20."),
    (50, "level_50", "Legend", "🏆", "Reach level 50."),
    (100, "level_100", "Ascended", "🌌", "Reach level 100."),
])

_stack("stat", "top_stat", [
    (5, "stat_5", "Getting Stronger", "💪", "Raise any single stat to 5."),
    (10, "stat_10", "Focused", "🧠", "Raise any single stat to 10."),
    (15, "skill_master", "Specialist", "📈", "Raise any single stat to 15."),
    (20, "stat_20", "Paragon", "🗿", "Raise any single stat to 20."),
    (50, "stat_50", "Titan", "🦾", "Raise any single stat to 50."),
    (100, "stat_100", "Demigod", "🌠", "Raise any single stat to 100."),
])

# The same quest completed over and over: the best single-quest count.
_stack("per_quest", "best_task_completions", [
    (1, "quest_1", "Once More", "✅", "Complete the same quest once."),
    (5, "quest_5", "Five Times Running", "🖐️", "Complete the same quest 5 times."),
    (10, "quest_10", "Ten Times", "🔟", "Complete the same quest 10 times."),
    (25, "quest_25", "Twenty-Five Deep", "🧱", "Complete the same quest 25 times."),
    (50, "quest_50", "Fifty Strong", "🏗️", "Complete the same quest 50 times."),
    (100, "quest_100", "The Hundredth Time", "🎯", "Complete the same quest 100 times."),
])

# First quest of each type - one stack per mode, so none can hide the others.
_stack("mode_instant", "completions_instant", [
    (1, "type_instant_1", "Quick Win", "⚡", "Complete your first Instant quest."),
    (10, "type_instant_10", "Instant Habit", "🎯", "Complete 10 Instant quests."),
    (25, "type_instant_25", "No Timer Needed", "🏃", "Complete 25 Instant quests."),
])
_stack("mode_beat_clock", "completions_beat_clock", [
    (1, "type_beat_1", "Against the Clock", "⏱️", "Complete your first Beat the Clock quest."),
    (10, "type_beat_10", "Beat the Bell", "🔔", "Complete 10 Beat the Clock quests."),
    (25, "type_beat_25", "Time Bender", "⏳", "Complete 25 Beat the Clock quests."),
])
_stack("mode_endure", "completions_endure", [
    (1, "type_endure_1", "Settled In", "🪑", "Complete your first Stay the Course quest."),
    (10, "type_endure_10", "Iron Discipline", "🧱", "Complete 10 Stay the Course quests."),
    (25, "type_endure_25", "Unshakeable", "⛰️", "Complete 25 Stay the Course quests."),
])
_stack("mode_pomodoro", "completions_pomodoro", [
    (1, "type_pomodoro_1", "Tomato Seasoned", "🍅", "Complete your first Pomodoro quest."),
    (10, "type_pomodoro_10", "Round After Round", "🔄", "Complete 10 Pomodoro quests."),
    (25, "type_pomodoro_25", "Break? What Break?", "🥵", "Complete 25 Pomodoro quests."),
])

_stack("purchases", "items_owned", [
    (1, "purchase_1", "Window Shopping", "🛍️", "Own your first piece of equipment."),
    (5, "collector", "Collector", "🎒", "Own 5 pieces of equipment."),
    (10, "purchase_10", "Armoury", "🛡️", "Own 10 pieces of equipment."),
    (25, "purchase_25", "The Whole Emporium", "🏪", "Own all 25 pieces of equipment."),
])

_stack("loadout", "slots_filled", [
    (1, "loadout_1", "First Fitting", "🧤", "Equip an item in any slot."),
    (3, "loadout_3", "Well Dressed", "👕", "Fill three equipment slots."),
    (5, "full_loadout", "Fully Decked", "🏆", "Equip an item in all five slots."),
])

_stack("gold", "coins", [
    (1_000, "rich", "Deep Pockets", "💰", "Hold 1,000 gold at once."),
    (5_000, "gold_5000", "Vault Builder", "🏦", "Hold 5,000 gold at once."),
    (10_000, "gold_10000", "Dragon's Hoard", "🐉", "Hold 10,000 gold at once."),
])

_stack("sessions", "sessions_won", [
    (1, "first_session", "On the Clock", "⏱️", "Complete your first timed session."),
    (10, "sessions_10", "Session Regular", "🕰️", "Complete 10 timed sessions."),
    (25, "time_lord", "Time Lord", "⌛", "Complete 25 timed sessions."),
    (50, "sessions_50", "Clockwork", "⚙️", "Complete 50 timed sessions."),
    (100, "sessions_100", "Century of Focus", "🎯", "Complete 100 timed sessions."),
    (250, "sessions_250", "Timekeeper Supreme", "👑", "Complete 250 timed sessions."),
])

_stack("endure", "endure_won", [
    (1, "endure_1", "First Sitting", "🪑", "Finish a Stay the Course session."),
    (10, "iron_will", "Iron Will", "🛡️", "Finish 10 Stay the Course sessions."),
    (25, "endure_25", "Endurance Athlete", "🏃", "Finish 25 Stay the Course sessions."),
    (50, "endure_50", "Made of Stone", "🗿", "Finish 50 Stay the Course sessions."),
])

_stack("swift", "swift_wins", [
    (1, "swift_1", "Quick Draw", "🎯", "Beat the clock with half the time to spare."),
    (5, "swift", "Swift", "⚡", "Beat the clock with half the time to spare, five times."),
    (25, "swift_25", "Speed Demon", "💨",
     "Beat the clock with half the time to spare, 25 times."),
    (100, "swift_100", "Blink and Miss It", "🌀",
     "Beat the clock with half the time to spare, 100 times."),
])

_stack("wounded", "wounded_wins", [
    (1, "scarred", "Scarred but Standing", "🩸", "Win a timed session while wounded."),
    (5, "wounded_5", "Still Standing", "🧹", "Win 5 timed sessions while wounded."),
    (25, "wounded_25", "Unkillable", "🔥", "Win 25 timed sessions while wounded."),
])

_stack("perfect_week", "longest_day_run", [
    (7, "perfect_week", "Perfect Week", "🎯",
     "Finish at least one quest every day for 7 days."),
    (30, "perfect_month", "Perfect Month", "🌙",
     "Finish at least one quest every day for 30 days."),
    (100, "perfect_100", "Hundred-Day Run", "📆",
     "Finish at least one quest every day for 100 days."),
    (365, "perfect_year", "Perfect Year", "🎆",
     "Finish at least one quest every day for a year."),
])

_stack("day_streak", "best_day_streak", [
    (3, "day_streak_3", "Three Days Active", "🌱", "Keep a 3-day hero streak."),
    (7, "day_streak_7", "Week Warrior", "🔥", "Keep a 7-day hero streak."),
    (30, "day_streak_30", "Monthly Momentum", "📅", "Keep a 30-day hero streak."),
    (90, "day_streak_90", "Quarter of a Year", "🍂", "Keep a 90-day hero streak."),
    (180, "day_streak_180", "Half-Year Hero", "🌗", "Keep a 180-day hero streak."),
    (365, "day_streak_365", "Full Circle", "🎉", "Keep a 365-day hero streak."),
])

_stack("coins_earned", "coins_earned", [
    (100, "purse_100", "First Purse", "👛", "Earn 100 gold in total."),
    (1_000, "purse_1000", "Paying Your Way", "💵", "Earn 1,000 gold in total."),
    (10_000, "purse_10000", "Gold Rush", "⛏️", "Earn 10,000 gold in total."),
    (100_000, "purse_100000", "Fortune", "💎", "Earn 100,000 gold in total."),
])

_stack("xp", "total_xp", [
    (100, "xp_100", "Apprentice", "📘", "Earn 100 XP in total."),
    (1_000, "xp_1000", "Journeyman", "📗", "Earn 1,000 XP in total."),
    (10_000, "xp_10000", "Veteran", "📕", "Earn 10,000 XP in total."),
    (100_000, "xp_100000", "Grandmaster", "🎓", "Earn 100,000 XP in total."),
    (1_000_000, "xp_1000000", "XP Immortal", "🌌", "Earn 1,000,000 XP in total."),
])

_stack("busy_day", "best_day_completions", [
    (5, "busy_5", "Busy Day", "🐝", "Complete 5 quests in one day."),
    (10, "busy_10", "Productive Day", "🏗️", "Complete 10 quests in one day."),
    (20, "busy_20", "Overachiever", "🚀", "Complete 20 quests in one day."),
    (50, "busy_50", "Unstoppable Day", "🌋", "Complete 50 quests in one day."),
])

_stack("all_stats", "min_stat", [
    (5, "rounded_5", "Well Rounded", "🧭", "Get every stat to at least 5."),
    (10, "rounded_10", "Balanced Hero", "⚖️", "Get every stat to at least 10."),
    (20, "rounded_20", "Complete Hero", "🧩", "Get every stat to at least 20."),
])

ACHIEVEMENT_BY_ID: dict[str, dict] = {a["id"]: a for a in ACHIEVEMENTS}

# --------------------------------------------------------------------------
# Task defaults
# --------------------------------------------------------------------------

TASK_ICONS: list[str] = [
    "📚", "🏃", "🧘", "💧", "🥗", "🛏️", "💪", "🧹", "🎸", "💻",
    "✍️", "🌿", "🚭", "🧠", "☀️", "🧴", "📵", "🐶", "🎨", "🤝",
]

TASK_COLORS: list[str] = [
    "#f59e0b", "#ef4444", "#22c55e", "#3b82f6", "#a855f7",
    "#22d3ee", "#ec4899", "#84cc16", "#f97316", "#8b5cf6",
]

DIFFICULTIES: list[dict] = [
    {"id": "tiny", "label": "Tiny", "multiplier": 0.5},
    {"id": "easy", "label": "Easy", "multiplier": 1.0},
    {"id": "normal", "label": "Normal", "multiplier": 1.5},
    {"id": "hard", "label": "Hard", "multiplier": 2.5},
    {"id": "epic", "label": "Epic", "multiplier": 4.0},
]

DIFFICULTY_BY_ID: dict[str, dict] = {d["id"]: d for d in DIFFICULTIES}

# Quests are available on the weekdays the hero picks. Numbers follow ISO order
# (Monday = 1 ... Sunday = 7) so ``date.isoweekday()`` can be used directly.
WEEKDAYS: list[dict] = [
    {"id": 1, "label": "Mon", "name": "Monday"},
    {"id": 2, "label": "Tue", "name": "Tuesday"},
    {"id": 3, "label": "Wed", "name": "Wednesday"},
    {"id": 4, "label": "Thu", "name": "Thursday"},
    {"id": 5, "label": "Fri", "name": "Friday"},
    {"id": 6, "label": "Sat", "name": "Saturday"},
    {"id": 7, "label": "Sun", "name": "Sunday"},
]

WEEKDAY_BY_ID: dict[int, dict] = {d["id"]: d for d in WEEKDAYS}
WEEKDAY_IDS: list[int] = [d["id"] for d in WEEKDAYS]

# --------------------------------------------------------------------------
# Timed sessions
# --------------------------------------------------------------------------

# A quest is either instant (tap to complete) or a timed session the hero has to
# run against the clock.
SESSION_MODES: list[dict] = [
    {
        "id": "instant",
        "label": "Instant",
        "icon": "⚡",
        "timed": False,
        "blurb": "Tick it off whenever it's done. No timer.",
    },
    {
        "id": "beat_clock",
        "label": "Beat the Clock",
        "icon": "⏱️",
        "timed": True,
        "blurb": "Finish before the bell. Let it ring and you take a hit.",
        "example": "Sweep the floor in 20 minutes.",
    },
    {
        "id": "endure",
        "label": "Stay the Course",
        "icon": "🛡️",
        "timed": True,
        "blurb": "Keep at it for the whole time. Finish early and it doesn't count.",
        "example": "Read for 30 minutes.",
    },
    {
        "id": "pomodoro",
        "label": "Pomodoro",
        "icon": "🍅",
        "timed": True,
        "blurb": "Focus rounds with breaks, for as long as you like.",
        "example": "25 min focus, 5 min break, repeat.",
    },
]

SESSION_MODE_BY_ID: dict[str, dict] = {m["id"]: m for m in SESSION_MODES}
TIMED_MODES: set[str] = {m["id"] for m in SESSION_MODES if m["timed"]}

DURATION_PRESETS: list[int] = [5, 10, 15, 20, 25, 30, 45, 60, 90]
SESSION_MIN_MINUTES = 1
SESSION_MAX_MINUTES = 240

# How far apart the hero's finish press and the deadline may be before the
# server calls it. This only absorbs network/render latency; the countdown the
# UI shows is driven by the server's own clock.
SESSION_GRACE_SECONDS = 1.0

# Pomodoro rounds run until the hero says they are done, so the payout is driven
# by the number of focus rounds actually finished rather than a fixed target.
POMODORO_DEFAULT_BREAK_MINUTES = 5
POMODORO_ROUND_BONUS = 0.5        # every finished round after the first adds this
POMODORO_MAX_FACTOR = 3.0         # ... up to this multiple of the quest's payout

# Finishing close to the round estimate the quest was created with pays extra:
# exactly as planned is worth +50%, and every round of difference costs 15% of
# that bonus until it runs out (being far off is never punished below par).
POMODORO_ESTIMATE_BONUS = 0.5
POMODORO_ESTIMATE_STEP = 0.15

# --------------------------------------------------------------------------
# Alarms (global settings, not per quest)
# --------------------------------------------------------------------------

# Built-in alarms are synthesised in the browser with the Web Audio API, so the
# app needs no audio assets and works offline. A custom file is copied into the
# save folder next to the database - the user never has to place it themselves.
ALARM_SOUNDS: list[dict] = [
    {"id": "bell", "label": "Bell", "blurb": "Three ringing strikes."},
    {"id": "chime", "label": "Chime", "blurb": "A gentle rising three-note chime."},
    {"id": "woodblock", "label": "Woodblock", "blurb": "Two short, dry knocks."},
    {"id": "ping", "label": "Ping", "blurb": "One bright, fading ping."},
]
ALARM_SOUND_BY_ID: dict[str, dict] = {s["id"]: s for s in ALARM_SOUNDS}
DEFAULT_ALARM_SOUND = "bell"
CUSTOM_ALARM_ID = "custom"
DEFAULT_ALARM_VOLUME = 0.7

ALARM_MAX_BYTES = 2 * 1024 * 1024
ALARM_TYPES: dict[str, str] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/vorbis": "ogg",
}
ALARM_FILE_LABEL = "WAV, MP3 or OGG"

# --------------------------------------------------------------------------
# Health, hits and healing
# --------------------------------------------------------------------------

MAX_HP_BASE = 40
MAX_HP_PER_VIT = 10
MAX_HP_PER_LEVEL = 10             # every level-up raises the health bar

# Fraction of maximum health lost when the bell catches you out.
HIT_DAMAGE_PCT: dict[str, float] = {
    "tiny": 0.05,
    "easy": 0.08,
    "normal": 0.12,
    "hard": 0.18,
    "epic": 0.25,
}

HEAL_PCT_PER_COMPLETION = 0.06    # every successful completion mends a little
HEAL_MIN_PER_COMPLETION = 2
REST_HEAL_PCT_PER_DAY = 0.10      # a new active day lets the hero recover
WOUNDED_COIN_MULTIPLIER = 0.5     # at 0 HP, "Wounded": half gold until healed

# A daily habit that never happened costs the same curve as a missed window.
# Scored once, lazily, when a new day is first opened.
MISSED_DAMAGE_PCT: dict[str, float] = HIT_DAMAGE_PCT

# When one day's misses hurt this badly and cut this deep, the quest log itself
# is probably too heavy: the UI suggests trimming it.
OVERLOAD_MISSED_MIN = 2
OVERLOAD_DAMAGE_FRACTION = 0.20   # of max HP, at risk in a single day
OVERLOAD_HP_FRACTION = 0.75       # and the hero is already at or below this

# How many past days the nightly reckoning will score when a hero returns
# after an absence. Coming back from a sabbatical should sting, not kill.
RECKONING_LOOKBACK_DAYS = 14

# --------------------------------------------------------------------------
# Session reward bonuses
# --------------------------------------------------------------------------

SPEED_BONUS_PER_10_PCT_LEFT = 0.05   # Beat the Clock: reward for spare time
SPEED_BONUS_CAP = 0.60
ENDURE_BONUS = 0.15                  # Stay the Course: reward for the commitment

# --------------------------------------------------------------------------
# Character export
# --------------------------------------------------------------------------

# A hero sheet other apps (a story or battle site) can consume. The format
# name and version are the contract: bump the version only when a consumer
# would have to change how it reads the document.
EXPORT_FORMAT = "habitquest.character"
EXPORT_FORMAT_VERSION = 1

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

SKILL_POINTS_PER_LEVEL = 3
XP_BASE = 100.0
XP_EXPONENT = 1.3
STREAK_BONUS_PER_DAY = 0.05
STREAK_BONUS_CAP = 0.75
DAILY_FIRST_BONUS = 0.20       # first completion of the day
MAX_LEVEL = 100
