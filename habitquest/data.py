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

ACHIEVEMENTS: list[dict] = [
    {"id": "first_step", "name": "First Step", "icon": "🌱",
     "desc": "Complete your very first task.", "goal": 1, "track": "total_completions"},
    {"id": "warming_up", "name": "Warming Up", "icon": "🔥",
     "desc": "Complete 10 tasks.", "goal": 10, "track": "total_completions"},
    {"id": "centurion", "name": "Centurion", "icon": "💯",
     "desc": "Complete 100 tasks.", "goal": 100, "track": "total_completions"},
    {"id": "streak_3", "name": "Three in a Row", "icon": "3️⃣",
     "desc": "Hold a 3-day streak on any task.", "goal": 3, "track": "best_task_streak"},
    {"id": "streak_7", "name": "Unbroken Week", "icon": "📅",
     "desc": "Hold a 7-day streak on any task.", "goal": 7, "track": "best_task_streak"},
    {"id": "streak_30", "name": "Thirty Days", "icon": "🗓️",
     "desc": "Hold a 30-day streak on any task.", "goal": 30, "track": "best_task_streak"},
    {"id": "level_5", "name": "Seasoned", "icon": "⭐",
     "desc": "Reach level 5.", "goal": 5, "track": "level"},
    {"id": "level_10", "name": "Champion", "icon": "🌟",
     "desc": "Reach level 10.", "goal": 10, "track": "level"},
    {"id": "level_20", "name": "Mythic", "icon": "💫",
     "desc": "Reach level 20.", "goal": 20, "track": "level"},
    {"id": "skill_master", "name": "Specialist", "icon": "📈",
     "desc": "Raise any single stat to 15.", "goal": 15, "track": "top_stat"},
    {"id": "collector", "name": "Collector", "icon": "🎒",
     "desc": "Own 5 pieces of equipment.", "goal": 5, "track": "items_owned"},
    {"id": "full_loadout", "name": "Fully Decked", "icon": "🏆",
     "desc": "Equip an item in all five slots.", "goal": 5, "track": "slots_filled"},
    {"id": "rich", "name": "Deep Pockets", "icon": "💰",
     "desc": "Hold 1,000 coins at once.", "goal": 1000, "track": "coins"},
    {"id": "perfect_week", "name": "Perfect Week", "icon": "🎯",
     "desc": "Finish at least one task every day for 7 days.",
     "goal": 7, "track": "longest_day_run"},
    {"id": "first_session", "name": "On the Clock", "icon": "⏱️",
     "desc": "Complete your first timed session.", "goal": 1, "track": "sessions_won"},
    {"id": "time_lord", "name": "Time Lord", "icon": "⌛",
     "desc": "Complete 25 timed sessions.", "goal": 25, "track": "sessions_won"},
    {"id": "iron_will", "name": "Iron Will", "icon": "🛡️",
     "desc": "Finish 10 Stay the Course sessions.", "goal": 10, "track": "endure_won"},
    {"id": "swift", "name": "Swift", "icon": "⚡",
     "desc": "Beat the clock with half the time to spare, five times.",
     "goal": 5, "track": "swift_wins"},
    {"id": "scarred", "name": "Scarred but Standing", "icon": "🩸",
     "desc": "Win a timed session while wounded.", "goal": 1, "track": "wounded_wins"},
]

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

# --------------------------------------------------------------------------
# Health, hits and healing
# --------------------------------------------------------------------------

MAX_HP_BASE = 40
MAX_HP_PER_VIT = 10

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

# --------------------------------------------------------------------------
# Session reward bonuses
# --------------------------------------------------------------------------

SPEED_BONUS_PER_10_PCT_LEFT = 0.05   # Beat the Clock: reward for spare time
SPEED_BONUS_CAP = 0.60
ENDURE_BONUS = 0.15                  # Stay the Course: reward for the commitment

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

SKILL_POINTS_PER_LEVEL = 3
XP_BASE = 100.0
XP_EXPONENT = 1.3
STREAK_BONUS_PER_DAY = 0.05
STREAK_BONUS_CAP = 0.75
DAILY_FIRST_BONUS = 0.20       # first completion of the day
MAX_LEVEL = 60
