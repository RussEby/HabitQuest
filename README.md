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

## Desktop app

The same game in its own window, with no browser tabs and no address bar:

```bash
cd desktop
npm install
npm start
```

The Electron shell starts the Python server on a free port, waits for it to
answer, and points the window at it — so the window and the API share an origin
and the web app itself is untouched. The save file lives in the platform's
application-data folder, separate from the one `app.py` uses. Closing the window
stops the server and closes the save cleanly; `npm run verify` boots the whole
thing headlessly and checks the window and the API.

Requires Node 18+ to run, plus Python 3.10+ on the PATH. Set
`HABITQUEST_PYTHON` to use a specific interpreter.

### Packaging it for someone else

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-install.ps1
```

One command builds a Windows **installer** (with a desktop icon) and a
**portable zip** in `desktop\release\`. The Python backend is compiled into a
single executable and bundled, so the person installing it needs neither Python
nor Node, and the app works offline. Re-run the same command after any change
to produce a fresh build.

- [docs/BUILDING.md](docs/BUILDING.md) - prerequisites, what the script does,
  version bumping, troubleshooting, where the save file lives.
- [docs/USER-GUIDE.md](docs/USER-GUIDE.md) - installation and how to play, for
  the person receiving the app.

---

## How the game works

### Quests

Each habit you track has a name, an optional note, an icon, a colour, a stat it
trains, a base XP value, a base gold value, a difficulty and a **schedule**.

A quest runs every day unless you pick otherwise. In the quest form, **Available
on** is seven toggles — Mon through Sun — and any combination works: weekdays,
weekends, just Mondays, or Mon/Wed/Fri. Quests not scheduled for today move to a
dimmed **Resting today** section and cannot be started or completed until their
next day. The ring beside the quest list counts only the quests due today.

| Difficulty | Tiny | Easy | Normal | Hard | Epic |
|---|---|---|---|---|---|
| Multiplier | ×0.5 | ×1.0 | ×1.5 | ×2.5 | ×4.0 |

Rewards are `base × difficulty × streak × daily`, so:

- **Streak bonus** — each consecutive *scheduled* day adds **+5%**, capped at
  **+75%**. Days the quest is not available are rest days: they add nothing and
  break nothing, so a Mon–Fri habit keeps its streak over the weekend.
- **First quest of the day** — the first completion each day adds **+20%**.
- **★ Undo** — every quest completed today has a ↩ button, which rolls back the
  exact XP, gold, streak and level it awarded. Misclicks are harmless.

A quest can only be completed once per day, and only on the days it is
scheduled for. That's the point.

When a day is genuinely out of your hands — travel, illness, an emergency —
pressing **⏭ Skip** closes the quest for that day with **no reward and no
penalty**: no XP or gold, no completion recorded, and the skipped day behaves
exactly like a day the quest was never scheduled for. A 5-day run through
Tuesday survives a skipped Wednesday and becomes a 6-day run on Thursday. The
card moves to a **Skipped today** section with the rewards hidden, and its ↩
button takes the skip back. Skips are exempt from the hero's day streak and from
the nightly reckoning too.

A quest normally repeats until you delete it, but **Repeat** in the quest form
can cap it: choose *Ends after a set number of times* and give a number, and the
quest archives itself once that many occurrences are done. Every occurrence
still pays exactly what any other pays — finishing the run itself pays nothing
extra — and a skipped day does not count, so the run grows by one and finishes a
due day later. A counted quest shows its progress on its card (`🔁 2 of 5`).

**Finish within** gives an occurrence a grace period. Leave it at *Same day* and
nothing changes: an occurrence opens on its scheduled day and expires that day.
Choose *Within N days* instead and Monday's occurrence can be finished any day
Monday through the next N−1 days, with the same XP and gold as ever. Windows may
never overlap, so the form only offers windows the chosen days can accommodate,
and the store refuses an overlapping combination outright: a quest that runs
every day has no room at all, and Mon/Wed/Fri can take at most two days (Mon–Tue,
Wed–Thu, Fri–Sat). A windowed card reads `⏳ day 2 of 3 · by Wed 28 Oct`.
Streaks, skips and the nightly reckoning all count occurrences: an occurrence is
only late once its window has closed, and skipping one closes it whole and
stretches a counted run by one.

**📦** on any card sets a quest aside without deleting it. Quests that finish
their counted run, and quests you archive yourself, move to an **Archived**
section at the bottom of the Quests tab; they keep their history, streaks and
rewards, pay nothing and cost nothing while they sit there, and **↩ Re-engage**
puts one back on the board. A quest that had already finished its run starts a
fresh cycle when it is re-engaged.

The **⟳** button in the top bar reloads the whole save on demand. The window
also checks the date itself once a minute, on tab switches and when it regains
focus, so a quest list left open overnight clears itself at midnight without
rebuilding all state on every check.

### Timed sessions

A quest can also be a **timed session** with a countdown. When you start one, a
timer HUD docks to the bottom of the screen and keeps running wherever you
navigate, and a bell rings when the time is finished. There are two flavours,
and they punish different things:

| | **Beat the Clock** ⏱️ | **Stay the Course** 🛡️ |
|---|---|---|
| The rule | Finish **before** the bell | Keep at it for the **whole** time |
| Example | Sweep the floor in 20 minutes | Read for 30 minutes |
| Finishing early | The point of it — pays a **speed bonus** of +5% per 10% of the window left to spare (capped +60%) | Refused: *"Not yet — 12 minutes still to serve"* |
| Running over | Too late: the bell rings, you **take a hit** | Allowed and encouraged — the timer counts up as overtime |
| Reward | XP and gold, plus the speed bonus | XP and gold, plus a **+15% endurance bonus** |
| Give up | Costs nothing, unless the bell already rang | Costs nothing, no reward |

So the two modes ask different things of you: Beat the Clock is about *speed*,
Stay the Course is about *not stopping early*.

### Alarms and settings

The **Settings** tab holds preferences that apply to the whole app. The alarm
rings when a timed session's clock reaches zero, and for a Pomodoro it rings at
the end of **every** focus round *and* every break, so the next round never
starts in silence.

- **Built-in sounds** — Bell, Chime, Woodblock and Ping, synthesised in the
  browser. No audio assets, and they work offline.
- **Your own sound** — choose any **WAV, MP3 or OGG** file up to **2 MB**.
  You don't have to place it anywhere: the picker copies it into a `sounds/`
  folder beside your save file, and it is served from `/api/sound`. Replacing
  it swaps the file; **Remove custom file** deletes it and returns to a
  built-in sound.
- **Volume** — 0–100%, applied to built-ins and uploads alike. The 🔔 button on
  the session dock mutes every alarm without touching these settings.

Uploads are checked, not trusted: the extension/type must be one of the three,
the bytes must actually look like that format, and anything over the limit is
refused with a message that says which rule it broke.

### Health, hits and healing

Letting the bell catch you on a Beat the Clock quest is the one way to lose
something in Habit Quest, so your hero has health:

- **Max health** is `40 + 10 × VIT`, and VIT from equipped gear counts, so
  armour really does protect you.
- A missed window deals damage scaled by the quest's difficulty — 5% of max HP
  on a Tiny quest up to 25% on an Epic one — and resets that quest's streak.
- **Healing:** every completion mends a little, a new active day rests up 10%,
  and a **level-up is a full heal**.
- At **0 HP** your hero is **Wounded** and earns half gold until they recover.
  It never blocks you from playing — it's a bruise, not a game over.

If the window closes while your tab is shut, the server settles it when you next
open the app and plays the hit then, so nothing is silently lost.

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
fast and later ones feel earned. Level cap is 100.

### The Emporium

25 items across five slots — **weapon, head, body, boots, accessory** — in five
rarities: Common, Uncommon, Rare, Epic and Legendary. Gear is level-gated as
well as expensive, so the best sword in the shop is also a stretch goal. Equipped
items raise your stats, your Power, and visibly change your character on screen.

### Exporting the hero

The **Hero** tab has **⤓ Export hero sheet**, which downloads the character as a
single JSON file — identity, archetype, level and XP, stats, health, gold,
equipped gear and lifetime record. Quests, the journal, sessions and
achievements are deliberately left out: the file is a portable hero sheet for
another app (a story or battle site), not a save backup. Exporting is read-only.

The file carries a stable `character.uid`, so a site can recognise a returning
hero from a newer export instead of creating a duplicate.

See [docs/CHARACTER-EXPORT.md](docs/CHARACTER-EXPORT.md) for the full field
reference, compatibility rules, validation advice and starter code, plus the
machine-readable [schema](docs/character.schema.json) and a [real
example](docs/example-character.json). The same export is served live at
`GET /api/character/export`.

### Achievements and the Journal

**96 achievements across 22 stacks** track the long game. A stack is a ladder
on one track — quest completions (1 to 1,000), a single quest's streak (3 days
to a year), hero levels (5 to 100), stats (5 to 100), one quest's repeat count
(1 to 100), first completions per quest type, purchases, loadout, gold held and
total gold earned, timed sessions and their modes, streaks, perfect runs, busy
days and well-rounded stats.

The Journal shows **one card per stack**: the next tier still to earn, with its
progress. Earning that tier swaps the card for the one above it, and when the
last tier falls the card reads **Stack complete**. The header keeps a tally of
every achievement gathered so far, e.g. `(23 / 96)`. Underneath the cards the
Journal also shows a 30-day activity heatmap, your most-completed quests and a
running adventure log.

Streaks are measured against your schedule, not the calendar. If nothing is due
on a given day — a weekend with only weekday quests, say — that day is a rest
day: the hero's day streak and each quest's streak carry across it, and so does
a day you deliberately skipped. Missing a day that *did* have something scheduled
still breaks them, which keeps the streak honest.

---

## Project layout

```
app.py                  CLI entry point: argument parsing, console setup, launch
habitquest/
  data.py               static content — stats, archetypes, 25 items, achievements, tunables
  engine.py             pure rules — XP curve, rewards, power, streaks, achievements
  store.py              SQLite persistence + full state assembly
  api.py                JSON API routing (including the timed-session routes)
  server.py             stdlib HTTP server (API + static assets, loopback only)
  desktop.py            same server for the desktop app: ephemeral port + handshake
desktop/
  main.js               Electron main process: window, lifecycle, shutdown
  backend.js            starts and supervises the Python server
  backend_entry.py      entry point for the frozen (PyInstaller) backend
  smoke-backend.js      HTTP smoke test for the compiled backend
  verify.js             headless check that the window loads and can reach the API
  build/icon.png        app icon, generated by scripts/make-icon.py
docs/
  BUILDING.md           how to build the installer and portable zip
  GITHUB.md             publishing the source: remote, sign-in, what is ignored
  USER-GUIDE.md         installation and how to use the app
  CHARACTER-EXPORT.md   format and integration guide for the JSON hero sheet
  character.schema.json JSON Schema for that export
  example-character.json a real exported hero
scripts/
  build-install.ps1     one-command Windows build: backend, installer, zip
  make-icon.py          redraws the app icon (no image libraries needed)
static/
  index.html            the app shell: onboarding, topbar, four views, overlays
  styles.css            the whole visual identity — dark-fantasy RPG theme
  app.js                front end: rendering, interactions, animations
tests/
  test_engine.py        unit tests for the pure rules
  test_store.py         behavioural tests for persistence and the game loop
  test_sessions.py      timed sessions, health, and legacy-save migration
  test_schedule.py      weekday schedules, off-day rules and rest-day streaks
  test_skip.py          skipped days: no rewards, held streaks, HTTP routes
  test_recurrences.py   counted repeats, skip extension, the archive round trip
  test_windows.py       finish windows: caps, late completion, misses, streaks
  test_achievements.py  stacked achievement families, ladders and metrics
  test_settings.py      global alarm settings and sound uploads
  test_export.py        the portable hero sheet: fields, gear, identity, download
  test_api.py           end-to-end tests over a real HTTP socket
```

### API

The front end talks to a small JSON API; everything is also usable with `curl`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/state` | Everything the UI needs in one call |
| `POST` | `/api/character` | Create the hero (`{name, archetype}`) |
| `GET` | `/api/character/export` | Download the hero sheet as a named `.json` file |
| `POST` | `/api/demo` | Seed a demo save |
| `POST` | `/api/reset` | Wipe the save |
| `POST` `PUT` `DELETE` | `/api/tasks` … `/api/tasks/{id}` | Manage quests |
| `POST` | `/api/tasks/{id}/complete` | Complete an instant quest — returns rewards, level-up, unlocks |
| `POST` | `/api/tasks/{id}/undo` | Roll back today's completion |
| `POST` | `/api/tasks/{id}/skip` `…/unskip` | Set a quest aside for today, or take the skip back |
| `POST` | `/api/tasks/{id}/archive` `…/unarchive` | Park a quest, or re-engage it |
| `GET` | `/api/session` | The running timed session, if any |
| `POST` | `/api/tasks/{id}/session/start` | Start the clock on a timed quest |
| `POST` | `/api/tasks/{id}/session/finish` | Finish it — `won`, or `hit` if the bell beat you |
| `POST` | `/api/tasks/{id}/session/abandon` | Give up; no reward, no penalty |
| `POST` | `/api/skills/upgrade` | Spend a point (`{stat, amount}`) |
| `GET` `POST` | `/api/shop` … `/api/shop/buy` `equip` `unequip` | The Emporium |
| `GET` | `/api/history?days=30` | Activity series and top quests |
| `GET` | `/api/achievements` | Every achievement with its stack, tier and progress |
| `GET` | `/api/activity?limit=25` | The adventure log |
| `GET` `PUT` | `/api/settings` | Global preferences (`{sound, volume}`) |
| `PUT` `DELETE` | `/api/settings/sound` | Upload (`{name, type, data}` base64) or remove a custom alarm |
| `GET` | `/api/sound` | The uploaded alarm as audio bytes |

Failures return HTTP 400 with `{"ok": false, "error": "why"}`.

### Data

Everything is stored in one SQLite file (`habitquest.db` next to `app.py` by
default) — character, quests, completions, timed sessions, inventory, equipment,
achievements, the activity log and global settings. Delete it to start over, or
move it to back up your hero. A custom alarm lives in a `sounds/` folder beside
that file.

The schema migrates itself: a save written by an earlier version is upgraded in
place on first open, keeping the hero and every logged completion. Old quests
simply become instant quests.

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

340 tests, standard library `unittest` only (no `pytest` install needed). They
cover the XP curve and reward maths, streak rollovers, the complete/undo round
trip, shop and skill rules, achievement unlocking, save/reopen persistence, and
a full HTTP playthrough including error paths. The API tests talk to a real
server on a real socket, so routing and content types are covered too.

The session suite simulates elapsed time by moving a session's start timestamp
instead of sleeping, so it stays fast: both modes won and lost, the bell being
pressed *at* the buzzer, giving up before and after it, a window that closed
while the tab was shut, damage and healing, and a legacy save being migrated
from the version 1 schema.

---

## Notes

- The server binds to `127.0.0.1` only. It is a personal, local app — don't put
  it on a public interface.
- Everything works offline; there are no web fonts, CDNs or telemetry. The bell
  is synthesised with the Web Audio API, so there are no sound files either (and
  a blocked or unsupported audio context can never break the UI).
- Respects `prefers-reduced-motion` and adapts down to phone widths.

---

## Credits

Habit Quest was created using the **Freebuff AI system**. The game design,
rules and content are the author's; the Python backend, browser front end,
Electron desktop shell, packaging scripts and documentation were built with
Freebuff as the AI coding agent.

For publishing this repository to GitHub — adding the remote, signing in so
future pushes work, and what is deliberately kept out of version control — see
[docs/GITHUB.md](docs/GITHUB.md).
