# ⚔️ Habit Quest

Turn the habits you want to build into an RPG character. Every quest you complete
earns **XP** and **gold**; XP levels your hero and grants **skill points**, gold
buys **weapons, armour, boots and accessories** in the Emporium. Keep a streak
alive and the rewards multiply.

Written in pure Python (standard library only) with a zero-dependency HTML/CSS/JS
front end. No installs, no build step, no internet connection required — your
save file lives on your own machine.

```
python app.py
```

That's it. Your browser opens at <http://127.0.0.1:8765/> and you're in.

---

## Getting started

```bash
python app.py                  # play (opens your browser)
python app.py --demo           # start with a month of history pre-loaded
python app.py --port 9000      # run on another port
python app.py --no-browser     # headless: just serve
python app.py --db my.db       # choose where the save file lives
python app.py --reset          # wipe the save and start a fresh legend
python app.py --verbose        # log every HTTP request
```

Requires **Python 3.10+**. There is nothing to `pip install`.

### First run

1. Name your hero and pick a **calling** (Warrior, Mage, Rogue or Ranger) — this
   sets your starting stats.
2. You start with **100 gold** and three starter quests.
3. Toggle to **Quests**, hit **✓ Complete** on something you've actually done.
4. Watch the XP, the gold and the streak counter move. Level up, spend skill
   points on **Hero**, then go shopping.

---

## How the game works

### Quests

Each habit you track has a name, an optional note, an icon, a colour, a stat it
trains, a base XP value, a base gold value and a difficulty.

| Difficulty | Tiny | Easy | Normal | Hard | Epic |
|---|---|---|---|---|---|
| Multiplier | ×0.5 | ×1.0 | ×1.5 | ×2.5 | ×4.0 |

Rewards are `base × difficulty × streak × daily`, so:

- **Streak bonus** — each consecutive day adds **+5%**, capped at **+75%**.
- **First quest of the day** — the first completion each day adds **+20%**.
- **★ Undo** — every quest completed today has a ↩ button, which rolls back the
  exact XP, gold, streak and level it awarded. Misclicks are harmless.

A quest can only be completed once per day. That's the point.

### Stats and skills

Five abilities, each fed by the quests you tag with it:

| | Stat | Trains |
|---|---|---|
| **STR** | Strength | Discipline and heavy lifting |
| **INT** | Intellect | Study, focus and deep work |
| **VIT** | Vitality | Health, sleep and body care |
| **AGI** | Agility | Speed, tidiness and quick wins |
| **CHA** | Charisma | People, creativity and expression |

Every **level grants 3 skill points**, spendable on any ability. Your **Power**
score is `3 × stats + 5 × gear bonuses + 10 × level`.

The XP curve grows with each level (`100 × level^1.3`), so early levels come
fast and later ones feel earned. Level cap is 60.

### The Emporium

25 items across five slots — **weapon, head, body, boots, accessory** — in five
rarities: Common, Uncommon, Rare, Epic and Legendary. Gear is level-gated as
well as expensive, so the best sword in the shop is also a stretch goal. Equipped
items raise your stats, your Power, and visibly change your character on screen.

### Achievements and the Journal

Fourteen achievements track the long game (first completion, 100 completions,
7- and 30-day streaks, level 10, a full loadout, a perfect week…). The Journal
shows a 30-day activity heatmap, your most-completed quests, achievement
progress and a running adventure log.

---

## Project layout

```
app.py                  CLI entry point: argument parsing, console setup, launch
habitquest/
  data.py               static content — stats, archetypes, 25 items, achievements, tunables
  engine.py             pure rules — XP curve, rewards, power, streaks, achievements
  store.py              SQLite persistence + full state assembly
  api.py                JSON API routing
  server.py             stdlib HTTP server (API + static assets, loopback only)
static/
  index.html            the app shell: onboarding, topbar, four views, overlays
  styles.css            the whole visual identity — dark-fantasy RPG theme
  app.js                front end: rendering, interactions, animations
tests/
  test_engine.py        unit tests for the pure rules
  test_store.py         behavioural tests for persistence and the game loop
  test_api.py           end-to-end tests over a real HTTP socket
```

### API

The front end talks to a small JSON API; everything is also usable with `curl`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/state` | Everything the UI needs in one call |
| `POST` | `/api/character` | Create the hero (`{name, archetype}`) |
| `POST` | `/api/demo` | Seed a demo save |
| `POST` | `/api/reset` | Wipe the save |
| `POST` `PUT` `DELETE` | `/api/tasks` … `/api/tasks/{id}` | Manage quests |
| `POST` | `/api/tasks/{id}/complete` | Complete it — returns rewards, level-up, unlocks |
| `POST` | `/api/tasks/{id}/undo` | Roll back today's completion |
| `POST` | `/api/skills/upgrade` | Spend a point (`{stat, amount}`) |
| `GET` `POST` | `/api/shop` … `/api/shop/buy` `equip` `unequip` | The Emporium |
| `GET` | `/api/history?days=30` | Activity series and top quests |
| `GET` | `/api/activity?limit=25` | The adventure log |

Failures return HTTP 400 with `{"ok": false, "error": "why"}`.

### Data

Everything is stored in one SQLite file (`habitquest.db` next to `app.py` by
default) — character, quests, completions, inventory, equipment, achievements
and the activity log. Delete it to start over, or move it to back up your hero.

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

90 tests, standard library `unittest` only (no `pytest` install needed). They
cover the XP curve and reward maths, streak rollovers, the complete/undo round
trip, shop and skill rules, achievement unlocking, save/reopen persistence, and
a full HTTP playthrough including error paths. The API tests talk to a real
server on a real socket, so routing and content types are covered too.

---

## Notes

- The server binds to `127.0.0.1` only. It is a personal, local app — don't put
  it on a public interface.
- Everything works offline; there are no web fonts, CDNs or telemetry.
- Respects `prefers-reduced-motion` and adapts down to phone widths.
