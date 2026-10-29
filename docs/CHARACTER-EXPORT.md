# Habit Quest character export — format and integration guide

Habit Quest can export the hero as a single JSON file. The file is a
self-contained character sheet: another app (a story site, a battle game, a
character viewer) can read it without knowing anything about Habit Quest's
database.

**This document is written to be handed to a developer or an AI coding agent.**
It describes exactly what is in the file, what the values mean, what is
deliberately *not* in the file, and the safety rules an importer must follow.
A machine-readable version of the same contract is in
[character.schema.json](character.schema.json), and a complete real example is
in [example-character.json](example-character.json).

---

## 1. Getting the file

In the app: **Hero** tab → **⤓ Export hero sheet**. The browser downloads a file
named `habit-quest-<hero-name>-<YYYY-MM-DD>.json` (ASCII slug, so `Rowan the
Swift` becomes `habit-quest-rowan-the-swift-2026-10-28.json`).

Or fetch it directly while the app is running:

```bash
curl -OJ http://127.0.0.1:8765/api/character/export
```

```powershell
Invoke-WebRequest http://127.0.0.1:8765/api/character/export -OutFile hero.json
```

`-OJ` (or opening the URL in a browser) uses the
`Content-Disposition` header, which carries the same file name. The default port
is `8765`; `python app.py --port 9000` changes it. The response is ordinary
UTF-8 JSON, so any text editor will open it.

Exporting is read-only. It never changes the save, spends nothing and does not
count as activity.

---

## 2. What the file is

```
top-level document
├── format              "habitquest.character"  ← identity of the format
├── format_version      1                       ← contract version
├── exported_at         snapshot timestamp
├── source              which app/version wrote it
├── stats_meta          labels for the five stat keys
└── character           the hero sheet
    ├── uid, name, created_at
    ├── archetype
    ├── level, xp, level_* fields
    ├── power
    ├── skill_points
    ├── stats           base / gear / total
    ├── health          hp / max_hp / pct / wounded
    ├── gold            current / earned
    ├── equipment       five slots, each an item or null
    └── record          lifetime quest count and streaks
```

### What is not in the file

Quests (including archived ones), completion history, the journal/heatmap,
sessions, skips, achievements and settings are **not exported**. This is
intentional: the export is a hero sheet for a different experience, not a save
file backup. Do not expect `tasks`, `journal`, `activity` or `achievements`
keys to exist.

There is also no import endpoint. A consuming site can store the uploaded sheet,
but it cannot write gold, XP or gear back into Habit Quest.

### Snapshot, not a live link

Every field is a copy taken at `exported_at`. The hero keeps changing in Habit
Quest afterwards; the uploaded file does not. If your site wants current data,
ask the player to export again — `character.uid` is how you recognise that it is
the same hero.

---

## 3. The contract

| Field | Type | Meaning |
|---|---|---|
| `format` | string | Always `"habitquest.character"`. Reject anything else. |
| `format_version` | integer | `1` for this document. |
| `exported_at` | string | Snapshot time, ISO 8601 **local time**, milliseconds, no timezone offset (e.g. `"2026-10-28T18:24:05.512"`). Display metadata only. |
| `source.app` | string | `"Habit Quest"`. |
| `source.app_version` | string | Version of the app that wrote the file. |
| `stats_meta` | array | `{key,label,abbr,blurb}` for `str`, `int`, `vit`, `agi`, `cha`, in that order. |

### Compatibility rules (important)

1. Check `format === "habitquest.character"` and `format_version === 1`.
2. **Ignore unknown fields.** New optional fields may appear in version 1
   without a version bump. Do not reject a file for having more than you expect.
3. Only a change that removes or redefines a field gets `format_version: 2`.
   When that happens, write a separate parser rather than guessing.
4. Never index blindly (`character.equipment.weapon.name`) without checking for
   `null`: empty slots are explicit nulls.

---

## 4. Field reference

### `character`

| Field | Type | Notes |
|---|---|---|
| `uid` | string (UUID) | Stable identity for this hero. Same hero = same `uid` on every export; a reset or new character gets a new one. Use it as your primary key. |
| `name` | string | 1–32 characters, chosen by the player. Display as plain text — never as HTML. |
| `created_at` | string | When the hero was created, local ISO 8601. |
| `archetype.id` | string | `warrior`, `mage`, `rogue` or `ranger` today. Treat it as an open string, not an enum. |
| `archetype.name` / `icon` / `color` / `blurb` | string | Presentation data (emoji icon, `#RRGGBB` colour, one-line description). |
| `archetype.base_stats` | stat block | The archetype's starting stats. Informational; already included in `stats.base`. |

### Level and progression

| Field | Type | Notes |
|---|---|---|
| `level` | integer 1–100 | Current level. |
| `xp` | integer | Lifetime XP. |
| `level_floor_xp` | integer | Lifetime XP at which the current level began. |
| `level_xp` | integer | XP earned inside the current level (`xp - level_floor_xp`). |
| `level_xp_needed` | integer | XP the current level spans. |
| `level_progress` | number 0–1 | `level_xp / level_xp_needed`, rounded to 4 decimals. |
| `next_level_xp` | integer | Lifetime XP needed for the next level. |
| `max_level` | boolean | True at level 100. |
| `skill_points.available` | integer | Unspent points. |
| `skill_points.spent` | integer | Points already put into stats. |

### Stats — the numbers a battle should use

`stats` has three blocks with the same five keys:

| Block | Meaning |
|---|---|
| `stats.base` | The hero's own stats: archetype start plus spent skill points, **without gear**. |
| `stats.gear` | Sum of the bonuses of the currently equipped items. |
| `stats.total` | `base + gear`. **This is the number to use in combat.** |

The five keys and what they represent:

| Key | Label | Habit it comes from |
|---|---|---|
| `str` | Strength | Discipline, physical effort |
| `int` | Intellect | Study, focus, deep work |
| `vit` | Vitality | Health, sleep, body care |
| `agi` | Agility | Speed, tidiness, quick wins |
| `cha` | Charisma | People, creativity, expression |

Gear bonuses are **already inside** `stats.gear` and `stats.total`. Never add
equipment bonuses to `total` a second time.

### Health

| Field | Type | Notes |
|---|---|---|
| `health.max_hp` | integer ≥ 1 | Maximum health including Vitality and level. Start battles from this value. |
| `health.hp` | integer ≥ 0 | Current health in Habit Quest's own health system. Useful for flavour, but do not assume a fresh battle starts here. |
| `health.pct` | number 0–1 | `hp / max_hp`, rounded to 4 decimals. |
| `health.wounded` | boolean | True when Habit Quest currently has the hero at 0 HP. |

`max_hp = 40 + 10 × stats.total.vit + 10 × (level − 1)`.

### Gold

| Field | Type | Notes |
|---|---|---|
| `gold.current` | integer | Gold on hand at export time. |
| `gold.earned` | integer | Lifetime gold earned. |

Gold is a snapshot for flavour or a starting purse. It is not a currency the
consuming site can spend back in Habit Quest.

### Equipment

`equipment` always has exactly five keys: `weapon`, `head`, `body`, `boots`,
`accessory`. Each value is either `null` (empty slot) or an item:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable item id, e.g. `iron_sword`. |
| `name` | string | Display name. |
| `slot` | string | The slot the item occupies (matches its key). |
| `icon` | string | Emoji. |
| `rarity` | string | `common`, `uncommon`, `rare`, `epic` or `legendary`. |
| `rarity_label` | string | Display label, e.g. `Uncommon`. |
| `level_req` | integer | Level required to wear it. |
| `price` | integer | Shop price in gold. |
| `bonus` | object | Only the stats it raises, e.g. `{"str": 3, "agi": 2}`. Absent keys mean zero. |
| `bonus_text` | string | Human-readable form, e.g. `+3 STR`. |
| `description` | string | Flavour text. |

### Record

| Field | Type | Notes |
|---|---|---|
| `record.quests_completed` | integer | Lifetime completions. |
| `record.day_streak` | integer | Consecutive active days. |
| `record.best_day_streak` | integer | Best day streak ever. |
| `record.last_active_day` | string or null | `YYYY-MM-DD`; null for a new hero. |

`power` is Habit Quest's own balance number — convenient for sorting or rough
encounter scaling, not a combat rule:

```
power = 3 × sum(stats.total) + 5 × sum(stats.gear) + 10 × level
```

---

## 5. Example

A shortened excerpt; [example-character.json](example-character.json) is the
full file.

```json
{
  "format": "habitquest.character",
  "format_version": 1,
  "exported_at": "2026-10-28T18:24:05.512",
  "source": { "app": "Habit Quest", "app_version": "1.0.0" },
  "stats_meta": [
    { "key": "str", "label": "Strength", "abbr": "STR", "blurb": "Discipline and heavy lifting." }
  ],
  "character": {
    "uid": "4d12cdff-48ea-4da3-9f63-e64e9d0a96eb",
    "name": "Rowan",
    "created_at": "2026-10-28T23:00:41",
    "archetype": {
      "id": "ranger", "name": "Ranger", "icon": "🏹", "color": "#22c55e",
      "blurb": "Balanced and relentless. Endurance over everything.",
      "base_stats": { "str": 5, "int": 2, "vit": 5, "agi": 5, "cha": 1 }
    },
    "level": 6,
    "xp": 2350,
    "level_xp": 171,
    "level_xp_needed": 1027,
    "level_progress": 0.1665,
    "next_level_xp": 3206,
    "max_level": false,
    "power": 146,
    "skill_points": { "available": 15, "spent": 0 },
    "stats": {
      "base":  { "str": 5, "int": 2, "vit": 5, "agi": 5, "cha": 1 },
      "gear":  { "str": 3, "int": 0, "vit": 1, "agi": 0, "cha": 0 },
      "total": { "str": 8, "int": 2, "vit": 6, "agi": 5, "cha": 1 }
    },
    "health": { "hp": 90, "max_hp": 150, "pct": 0.6, "wounded": false },
    "gold": { "current": 640, "earned": 2950 },
    "equipment": {
      "weapon": {
        "id": "iron_sword", "name": "Iron Sword", "slot": "weapon", "icon": "⚔️",
        "rarity": "uncommon", "rarity_label": "Uncommon", "level_req": 2,
        "price": 220, "bonus": { "str": 3 }, "bonus_text": "+3 STR",
        "description": "Reliable steel for a disciplined hand."
      },
      "head": null, "body": null, "boots": null, "accessory": null
    },
    "record": {
      "quests_completed": 87, "day_streak": 12,
      "best_day_streak": 21, "last_active_day": "2026-10-28"
    }
  }
}
```

---

## 6. Building the battle/story site

### Upload flow

1. `<input type="file" accept="application/json,.json">` — one file at a time.
2. Read it as text, cap it (256 KB is generous; a real export is ~5 KB), then
   `JSON.parse` inside `try/catch`.
3. Validate the envelope (`format`, `format_version`) and the character fields
   you actually use. [character.schema.json](character.schema.json) can be
   used with a JSON Schema validator, or validate by hand as below.
4. Key the stored hero by `character.uid` so uploading a newer export updates
   the same hero instead of creating a duplicate.
5. Render `name`, `archetype.name`, `record` and item names with `textContent`
   or your framework's escaping — never `innerHTML` with file data.

### Suggested mapping to combat stats

Habit Quest does not define combat; these are starting points, not laws:

| Battle concept | Reasonable source |
|---|---|
| Maximum HP | `health.max_hp` |
| Physical attack | `str` (weapon bonus is already in `total.str`) |
| Magic / tech attack | `int` and/or `cha` |
| Defence / damage reduction | `vit` and equipped `body`/`head` rarity |
| Initiative, dodge, crit | `agi` |
| Encounter tier | `level`; use `power` for finer sorting |
| Starting purse / shop | `gold.current` |
| Story tone | `archetype.id`, `archetype.blurb`, `record` |

A simple, readable baseline (feel free to replace it):

```js
function battleProfile(doc) {
  const c = doc.character;
  const s = c.stats.total;
  return {
    name: c.name,
    archetype: c.archetype.name,
    level: c.level,
    maxHp: c.health.max_hp,
    attack: 3 + s.str * 2 + Math.floor(s.agi / 2),
    magic: 3 + s.int * 2 + Math.floor(s.cha / 2),
    defence: 2 + Math.floor(s.vit * 1.5),
    initiative: s.agi + Math.floor(s.cha / 2),
    power: c.power,
  };
}
```

If you invent bosses, scale them from the hero's `level` and `power` rather than
from raw HP alone; a level 6 hero has ~150 HP but a level 40 hero has far more,
and gear can add a large share of the total stats.

### Validation rules worth enforcing server-side

Even after a schema check, treat the file as untrusted input:

- `format` must be exactly `habitquest.character`; `format_version` must be 1.
- `name`: string, 1–32 characters after trimming; strip control characters.
- `level`: integer 1–100. `power`: integer 0–100 000.
- Every stat and every equipment bonus: integer 0–10 000 (a legitimate hero is
  far below this; the cap only stops absurd payloads).
- `health.max_hp` ≥ 1 and `health.hp` ≤ `health.max_hp`.
- `equipment` keys must be the five known slots; each item's `slot` must match
  its key; `bonus` keys must be known stats.
- `uid`: a UUID string. If it is missing or malformed, generate your own id and
  store the sheet as a one-off instead of rejecting a playable character.
- Recompute `stats.total` as `base + gear` if you rely on it, and clamp it; the
  file is editable by the player.
- Never trust the export for anything competitive or monetary. If your site has
  leaderboards or purchases, keep the authoritative numbers in your own
  database and treat the uploaded sheet as a starting snapshot.

### TypeScript types

```ts
export interface StatBlock {
  str: number; int: number; vit: number; agi: number; cha: number;
}

export interface EquippedItem {
  id: string;
  name: string;
  slot: "weapon" | "head" | "body" | "boots" | "accessory";
  icon: string;
  rarity: "common" | "uncommon" | "rare" | "epic" | "legendary";
  rarity_label: string;
  level_req: number;
  price: number;
  bonus: Partial<StatBlock>;
  bonus_text: string;
  description: string;
}

export interface CharacterExport {
  format: "habitquest.character";
  format_version: 1;
  exported_at: string;
  source: { app: "Habit Quest"; app_version: string };
  stats_meta: { key: keyof StatBlock; label: string; abbr: string; blurb: string }[];
  character: {
    uid: string;
    name: string;
    created_at: string;
    archetype: {
      id: string; name: string; icon: string; color: string;
      blurb: string; base_stats: StatBlock;
    };
    level: number;
    xp: number;
    level_floor_xp: number;
    level_xp: number;
    level_xp_needed: number;
    level_progress: number;
    next_level_xp: number;
    max_level: boolean;
    power: number;
    skill_points: { available: number; spent: number };
    stats: { base: StatBlock; gear: StatBlock; total: StatBlock };
    health: { hp: number; max_hp: number; pct: number; wounded: boolean };
    gold: { current: number; earned: number };
    equipment: Record<EquippedItem["slot"], EquippedItem | null>;
    record: {
      quests_completed: number;
      day_streak: number;
      best_day_streak: number;
      last_active_day: string | null;
    };
  };
}

export function isCharacterExport(value: unknown): value is CharacterExport {
  if (!value || typeof value !== "object") return false;
  const doc = value as Record<string, any>;
  const c = doc.character;
  return doc.format === "habitquest.character"
    && doc.format_version === 1
    && !!c && typeof c === "object"
    && typeof c.uid === "string"
    && typeof c.name === "string"
    && typeof c.level === "number"
    && !!c.stats && !!c.stats.total
    && !!c.health && typeof c.health.max_hp === "number"
    && !!c.equipment && typeof c.equipment === "object";
}
```

### Minimal Python check (for a backend)

```python
from typing import Any

STAT_KEYS = {"str", "int", "vit", "agi", "cha"}
SLOTS = {"weapon", "head", "body", "boots", "accessory"}


def parse_export(doc: Any) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("Not a JSON object.")
    if doc.get("format") != "habitquest.character" or doc.get("format_version") != 1:
        raise ValueError("Not a Habit Quest character export (need format_version 1).")
    hero = doc.get("character")
    if not isinstance(hero, dict) or not isinstance(hero.get("uid"), str):
        raise ValueError("Missing character.uid.")
    if set(hero.get("equipment", {})) != SLOTS:
        raise ValueError("Equipment must contain exactly the five slots.")

    stats = hero.get("stats", {}).get("total", {})
    for key in STAT_KEYS:
        if not isinstance(stats.get(key), int) or not 0 <= stats[key] <= 10_000:
            raise ValueError(f"Bad stat: {key}")

    level = hero.get("level")
    if not isinstance(level, int) or not 1 <= level <= 100:
        raise ValueError("Bad level.")
    # Re-derive rather than trusting: totals are base + gear.
    base = hero["stats"]["base"]
    gear = hero["stats"]["gear"]
    if any(stats[k] != base[k] + gear[k] for k in STAT_KEYS):
        raise ValueError("stats.total does not match base + gear.")
    return hero
```

### Things that surprise importers

- **`health.hp` is not necessarily full.** Habit Quest has its own damage and
  healing. If a battle should start fresh, use `health.max_hp`.
- **`hp` can exceed nothing but `max_hp`** — pct is always ≤ 1, and `wounded`
  means exactly 0 HP.
- **Gear is already counted.** `totals` include equipment; `base` is the
  gear-free view.
- **`last_active_day` is null for a brand-new hero.**
- **A hero can be level 100** with no further XP progress; `max_level` is true
  and `level_progress` sits at 1.
- **Timestamps have no offset.** Do not compare them across time zones; use
  `exported_at` only to show "exported on …".
- **Emoji are normal.** Names, icons and descriptions can contain any Unicode.
  Store and render as UTF-8 text.

---

## 7. Brief for an AI building the consuming site

Copy this together with this document:

> Build an upload-and-battle experience for Habit Quest character exports.
> Users upload a `habitquest.character` v1 JSON file. Read
> `docs/CHARACTER-EXPORT.md` and validate against
> `docs/character.schema.json` / `docs/example-character.json` before building.
> Key saved heroes by `character.uid`, use `character.stats.total` for combat
> attributes, `character.health.max_hp` as the battle HP pool, and
> `character.level`/`character.power` to scale encounters. Do not display quest
> or journal data (it is not in the file), do not trust the file for
> competitive or monetary results, and render player-supplied names as text,
> never as HTML. Show the archetype, level, stats, equipped items and record on
> the hero screen, then let the hero enter the story.

---

## 8. Version history

| `format_version` | App version | Change |
|---|---|---|
| 1 | 1.0.0 | First release: identity, archetype, level/XP, power, stats, health, gold, equipment, record. |
