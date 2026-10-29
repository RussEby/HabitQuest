# Habit Quest — User Guide

Habit Quest turns the habits you want to build into an RPG character. Every
quest you finish earns **XP** and **gold**; XP levels your hero and hands out
**skill points**, gold buys **weapons, armour, boots and accessories**. Everything
is saved on your own computer, and the app works completely offline.

This guide covers installing it, then how to actually play.

---

## 1. Installing

You will have been given one of two things: an installer (`.exe`) or a zip file.

### Option A — the installer (recommended, gives you the desktop icon)

1. Double-click **`Habit-Quest-Setup-<version>.exe`**.
2. Windows may show **"Windows protected your PC"**. That is normal for an app
   that has not been code-signed. Click **More info → Run anyway**.
3. Choose where to install it (the default is fine), then click **Install**.
4. The installer puts **Habit Quest** on your desktop and in the Start menu
   automatically. Double-click the icon and the game opens in its own window —
   a window with no address bar or tabs, just the game. That is all the setup
   there is.

It installs for your user account only, so it does not ask for an administrator
password, and it does not touch anything else on the machine.

### Option B — the portable zip (no installation at all)

1. Right-click the zip and choose **Extract All…**
2. Open the extracted folder and run **`Habit Quest.exe`**.
3. To get a desktop icon, right-click `Habit Quest.exe` → **Send to → Desktop
   (create shortcut)**.

You can put the folder anywhere, including a USB stick. The save file is stored
in your Windows user folder either way, so moving the app folder does not lose
your hero.

### What you need

- Windows 10 or 11, 64-bit.
- Nothing else. **No Python, no Node.js, no internet connection.**

### A note the first time you open it

Windows may take a few seconds to start the app the very first time (it is
unpacking its own copy of the engine). After that it opens quickly. If your
antivirus interrupts the first launch, allow the app and try again.

### Updating

Run the newer installer over the old one — your hero, quests, achievements and
settings all live outside the install folder and are kept. The portable version
is updated by extracting the new zip over the old folder.

### Uninstalling

- **Installer version:** Windows *Settings → Apps → Habit Quest → Uninstall*
  (or *Add or remove programs*).
- **Portable version:** delete the folder, and the desktop shortcut if you made
  one.

Both leave your save file in place. See [§10](#10-your-save-file) if you want to
remove that too.

---

## 2. The first run

The first window asks for two things:

1. **Name your hero** — up to 24 characters. Anything you like.
2. **Choose a calling** — this sets your starting stats:

| Calling | Leans toward |
|---|---|
| **Warrior** | Strength — discipline and heavy lifting |
| **Mage** | Intellect — study and deep work |
| **Rogue** | Agility — speed and quick wins |
| **Ranger** | Vitality — health, sleep and body care |

Click **Begin the journey**. You start at level 1 with 100 gold and three
starter quests.

Curious before committing? **Peek at a demo save** loads a character with a
month of history so you can see the Journal, achievements and shop full of
things. **Reset save** in the Journal replaces it with your own hero later.

---

## 3. The screen at a glance

Along the top: your **level**, your **gold**, an XP bar and a **day streak**
counter. The five tabs are:

| Tab | What lives there |
|---|---|
| **Hero** | Your character, health, abilities and equipment |
| **Quests** | The habits you are tracking today |
| **Shop** | The Emporium: 25 pieces of gear |
| **Journal** | 30-day activity, stats, achievements and the adventure log |
| **Settings** | The alarm sound, app-wide |

A green bar under the top bar shows progress to the next level. When you level
up, a dialog appears and you gain **3 skill points**.

### Keeping the day current

The **⟳** button beside your level and gold reloads everything from your save
file. You will rarely need it: the window checks the date by itself about once
a minute, and also whenever you switch tabs or come back to the window. So if
you leave Habit Quest open overnight, the finished quests un-finish themselves
when the day turns and a *A new day has begun* note appears.

The check is deliberately cheap — it reads the date only, and the full reload
happens just when that date has actually changed or when you press ⟳.

---

## 4. Quests

### Creating one

Click **＋ New Quest**. The form asks for:

| Field | Notes |
|---|---|
| **Quest name** | Up to 60 characters, e.g. "Read 10 pages" |
| **Notes** | Optional reminder of why it matters |
| **Trains** | Which stat it feeds: STR, INT, VIT, AGI or CHA |
| **Difficulty** | Tiny ×0.5, Easy ×1.0, Normal ×1.5, Hard ×2.5, Epic ×4.0 |
| **Available on** | Any mix of the seven weekdays. All seven by default |
| **Finish within** | **Same day** (the default) or a window of up to seven days — see [§4](#finish-windows) |
| **Repeat** | **♾ Ongoing** (the default, never ends) or *Ends after a set number of times* — see [§4](#counting-the-repeats) |
| **Base XP / Base gold** | The raw reward, before multipliers |
| **Session type** | Instant, Beat the Clock, Stay the Course or Pomodoro |

**Session type** is the big one:

- **⚡ Instant** — tick it off whenever it is done. No timer. Most habits are
  this.
- **⏱️ Beat the Clock** — a countdown you must beat. Example: *sweep the floor
  in 20 minutes*. Finish early and you get a speed bonus; let the bell ring and
  you take a hit.
- **🛡️ Stay the Course** — a timer you have to sit through. Example: *read for
  30 minutes*. Finishing early is refused; finish the whole window and you get
  an endurance bonus.
- **🍅 Pomodoro** — focus rounds with breaks, for as long as you like. See
  [§6](#6-pomodoro-quests).

Choosing a timed type reveals a **duration** picker (5 to 90 minutes, or type
your own). Choosing **Pomodoro** instead reveals two more fields:

- **Rounds estimate** — how many focus rounds you *expect* this quest to take
  (default 4). You are not held to it; finishing near it pays a bonus (§6).
- **Break minutes** — the length of each break (default 5, range 1–60).

### The sections

The Quests tab is always ordered the same way:

1. **Not finished** — the quests due today that still need doing. This is the
   part you actually work from. The counter next to the heading says how many
   are left.
2. **Finished** — what you have already banked today, each with a **↩** undo
   button.
3. **Skipped today** — quests you set aside for a reason outside your control,
   each with a **↩** that takes the skip back. They pay nothing (see below).
4. **Resting today** — quests whose schedule does not include today. They are
   dimmed and cannot be completed or started until their next day, but you can
   still edit them.
5. **Archived** — quests you have put away instead of deleting, including any
   that finished their counted run. They keep everything they earned and each
   has an **↩ Re-engage** button. See [§4](#the-archive).

The ring beside the heading (e.g. `5/9`) counts quests due **today** only, and
the line under the title sums it up: *"5 of 9 quests done today · 2 timed · 1
quest resting"*. On a day with nothing scheduled it says *"Nothing scheduled
today — a well-earned rest day."*

### Completing and undoing

For an instant quest, press **✓ Complete**. You get a hit of XP and gold, the
quest moves to Finished, and the streak on that quest goes up.

Pressed it by mistake? **↩ Undo** rolls back the exact XP, gold, streak and
level it gave. Nothing is lost.

A quest can only be completed **once per day**, and only on the days it is
scheduled for.

### Skipping a day

Sometimes a quest is impossible through no fault of yours — you are travelling,
ill, or a family emergency eats the evening. Press **⏭ Skip** on the quest and
confirm. The quest then:

- **pays nothing** — no XP, no gold, no completion, no achievement progress,
  exactly as if you had not done it; and
- **keeps its streak** — the skipped day is treated as though the quest was not
  on the board at all. A quest on a 5-day run through Tuesday, skipped on
  Wednesday, is on a 6-day run when you finish it on Thursday.

A skip closes the quest for today: it cannot be completed or started until its
next due day. The card moves to **Skipped today** with no reward shown. Changed
your mind? **↩** next to it reopens the quest for the rest of the day.

Skips are also excused from the hero's day streak and from the nightly health
reckoning, so a legitimate skip never costs you anything.

### Finish windows

Some days you simply cannot get to a quest before the day is over. **Finish
within** gives an occurrence a grace period instead of expiring it at midnight:

- **Same day — no window** (the default) is the old behaviour. The quest has to
  be finished on the day it opens.
- **Within N days** keeps it finishable for the next N days in total. Pick
  *Monday* with *Within 5 days* and you can finish it Monday, Tuesday,
  Wednesday, Thursday or Friday.

That works for any session type — instant ticks, Beat the Clock, Stay the
Course and Pomodoro alike — and the reward is the same whichever day inside the
window you finish it. The card says where you are: **⏳ day 2 of 3 · by Wed 28
Oct**.

Two occurrences may never be open at once, so the window is capped by the gap
between the days you picked:

| Available on | Longest window |
|---|---|
| Every day, or Monday–Tuesday | Same day only |
| Mon / Wed / Fri | 2 days (Mon–Tue, Wed–Thu, Fri–Sat) |
| One weekday, e.g. Monday | 7 days (all the way to the next Monday) |

The form only offers the windows the chosen days allow, and the server refuses
an overlapping combination if one is sent anyway.

Everything else counts **occurrences**, not days:

- The quest is **not late** while its window is open. The nightly reckoning only
  steps in once the window has fully closed with nothing done.
- **Streaks** survive a late finish inside the window, and break only when an
  occurrence's whole window passes unnoticed.
- **Skip** closes the whole occurrence, so a windowed quest cannot be
  half-skipped and half-finished. As always, a skip costs nothing and stretches a
  counted repeat run by one.

### Counting the repeats

Some habits only need doing a handful of times — a five-visit course, a
three-week tidying spree. **Repeat** in the quest form handles that:

- **♾ Ongoing** (the default) keeps the quest on your board forever, exactly as
  before.
- **Ends after a set number of times** takes a number from 1 to 200. The quest
  archives itself once that many occurrences are done.

Only **completions** count. A rest day or a day you skipped is not a
repeat. Every occurrence still pays exactly what it would have paid anyway — the
last one included. Finishing the whole run pays **no bonus**, so the total is
simply the sum of the times you did it.

A **skip does not count**, so it does not shorten the run: it makes the run one
repeat longer. Set Mon/Wed/Fri for 3 repeats and skip the Wednesday, and the
quest runs Monday, *(skipped Wednesday)*, Friday, then next Monday — three real
completions, one of them a week later than planned.

The card shows where you are, e.g. **🔁 2 of 5**. Change your mind and edit the
quest: raising the number extends the run, lowering it below what you have
already done archives the quest straight away.

### The archive

You do not have to delete a quest to get it off your board. Press **📦** on any
card and confirm: the quest moves to the **Archived** section at the bottom of
the Quests tab. It keeps its streak, its history and everything it paid you, and
while it sits there it is never due, cannot cost you health and is left alone by
the nightly reckoning. Quests that finish their counted repeats archive
themselves the same way, marked *Run finished*.

**↩ Re-engage** puts an archived quest back on the board. If it had simply been
set aside it picks up where it left off (`2 of 5` stays `2 of 5`); if it had
already finished its run it starts a fresh cycle of the same length. The 🗑 on an
archived card deletes it for good.

### How the rewards are calculated

```
XP and gold = base × difficulty × streak bonus × first-of-the-day bonus
```

- **Streak bonus** — each consecutive scheduled day adds **+5%**, up to **+75%**.
- **First quest of the day** — **+20%** on the first one you finish each day.
- **Rest days** — days the quest is not scheduled for, and days you skipped,
  neither add to nor break its streak, so a Mon–Fri habit keeps its run over the
  weekend.

---

## 5. Timed sessions

Start a timed quest with **▶ Start**. A timer panel docks to the bottom of the
screen and keeps counting wherever you go in the app.

| Button | What it does |
|---|---|
| **✓ Finished** | Claims the quest. For Beat the Clock, do it before the bell. |
| **⏸ Pause** | *(Pomodoro only)* Freezes the clock. The quest stays active; press **▶ Resume** when you are back. |
| **⏸ Pause quest** | *(Pomodoro only)* Leaves the quest unfinished but **banks the rounds you have completed**. Starting it again later picks up from that count. |
| **Give up** | Ends the session with no reward and no penalty. |
| **🔔** | Mutes or unmutes alarms for this session only. |

**Beat the Clock** pays a speed bonus of +5% for every 10% of the window you
have left, up to +60%. If the bell rings first, you take damage and the quest's
streak resets — see health, below.

**Stay the Course** refuses to finish early: *"Not yet — 12 minutes still to
serve."* When the window is up, press **✓ Finish now** for a +15% endurance
bonus. You may also keep going; the timer counts up as overtime.

If you close the app mid-session, the server settles it the next time you open
the app, so nothing is silently lost.

### Health

Your hero has HP: `40 + 10 × VIT`, including VIT from equipped gear.

- A missed Beat the Clock window deals 5% (Tiny) to 25% (Epic) of your max HP
  and resets that quest's streak.
- You heal a little on every completion, 10% at the start of a new active day,
  and **fully on a level-up**.
- At **0 HP** you are **Wounded** and earn half gold until you recover. It never
  stops you playing.

---

## 6. Pomodoro quests

A Pomodoro quest is a chain of focus rounds separated by breaks. It keeps going
until *you* say you are done.

### How a run goes

1. Press **▶ Start**. Round 1 begins, with the hint *"Focus for 25 min · round 1.
   A break follows, then another round."*
2. Work until the focus timer ends. The bell rings, the round is counted, and a
   **break starts automatically** and counts down (*"Break for 5 min. Focus round
   2 starts when it ends."*).
3. When the break ends the bell rings **again** — that is your signal to start
   the next round. It starts by itself; just go back to work.
4. Repeat as many rounds as you need. The button always tells you the score:
   **✓ Finish · 3 rounds**.
5. Press it when you are done. The quest is completed for the day.

Rounds are never forced on you: if you finish after two rounds, that is a
completed quest. Breaks do not count as rounds.

### Pausing

Two different things, deliberately:

- **⏸ Pause** freezes the running clock. The quest stays active and nothing is
  lost — press **▶ Resume** to continue the same round from where you stopped.
- **⏸ Pause quest** stops the run and leaves the quest **unfinished**. The
  rounds you completed are remembered. Start the quest again later — the same
  day or the next time it is scheduled — and it resumes with those rounds
  already banked.

### How the score works

The payout grows with the work you actually did, and pays extra for knowing
yourself:

- **Rounds:** the quest's normal payout, **+50% per additional completed round**,
  up to **3×** the base.
- **Estimate accuracy:** finishing exactly the number of rounds you predicted
  when you created the quest adds **+50%**. Each round you are off costs 15
  percentage points of that bonus (one off = +35%, two off = +20%, three off =
  +5%, four or more off = nothing extra). Being far off is never punished — you
  simply do not get the bonus.
- Streak, difficulty and first-of-the-day bonuses apply as usual.

So a 4-round estimate finished in 4 rounds is worth the most; the same quest
finished in 8 rounds still earns plenty, just not the accuracy bonus.

### Alarms

The bell rings at the end of **every** focus round **and** every break, so the
next round never starts in silence. Which sound it is, and how loud, is set in
[Settings](#9-settings).

---

## 7. Hero, abilities and gear

### Abilities

Five stats, each fed by the quests you tag with it:

| | Stat | Trains |
|---|---|---|
| **STR** | Strength | Discipline and heavy lifting |
| **INT** | Intellect | Study, focus and deep work |
| **VIT** | Vitality | Health, sleep and body care |
| **AGI** | Agility | Speed, tidiness and quick wins |
| **CHA** | Charisma | People, creativity and expression |

The **＋** buttons spend skill points, one point per +1. You earn **3 points per
level**, so the badge (e.g. *7 points*) is simply everything you have earned
minus everything you have spent. Gear bonuses are extra and never consume
points.

Your **Power** score is `3 × stats + 5 × gear bonuses + 10 × level`.

### Equipment

Five slots — **weapon, head, body, boots, accessory**. Equipped items raise your
stats, your Power, your HP (through VIT) and visibly change your avatar. The
Equipment card on the Hero tab shows what is in each slot and a **Go shopping**
button.

### The Emporium

The Shop tab has 25 items across the five slots and five rarities — Common,
Uncommon, Rare, Epic and Legendary. Use the filter chips to narrow by slot or
rarity. Items are level-gated as well as priced, so the best sword is also a
stretch goal. Buy, then equip from **Your inventory** at the bottom of the tab.

### Taking your hero elsewhere

The **Hero** tab has a **⤓ Export hero sheet** button. It downloads a JSON file
named after your hero, e.g. `habit-quest-rowan-2026-10-28.json`, holding the
character's name, calling, level, XP, stats, health, gold, equipped gear and
lifetime record.

The file is meant for other apps — for example a story or battle website where
you upload your Habit Quest hero. Quests, the Journal, achievements and settings
are not included; this is a hero sheet, not a backup of your save (for that, see
[§10](#10-your-save-file)). Exporting never changes anything in the app and
costs nothing.

Upload the same file again after you have played more and your hero's progress
will be recognised by its stable id rather than duplicated. Developers can read
[docs/CHARACTER-EXPORT.md](CHARACTER-EXPORT.md) for every field and a
machine-readable schema.

---

## 8. Journal and achievements

The Journal is the proof you showed up:

- **Activity** — a 30-day heat map. Darker squares are busier days.
- **Journal stats** — totals for completions, XP, gold, streaks and Power.
- **Most completed** — your top quests with bars.
- **Achievements** — see below.
- **Adventure log** — every completion, purchase, level-up and session, newest
  first.

### Achievements

There are **96 achievements across 22 stacks**. A stack is a ladder on one
track, and the Journal shows **one card per stack**: the next tier still to earn,
with a progress bar. Claim that tier and the card is replaced by the next one up.
When the final tier falls, the card reads **✦ Stack complete**.

The heading keeps a running tally of everything gathered, e.g. **`(23 / 96)`**.

The stacks, briefly:

| Stack | Ladder |
|---|---|
| Quests completed | 1 → 1,000 |
| One quest's streak | 3 days → 1 year |
| Hero level | 5 → 100 |
| Any single stat | 5 → 100 |
| The same quest, repeated | 1 → 100 times |
| First of each quest type | Instant, Beat the Clock, Stay the Course, Pomodoro |
| Purchases | 1, 5, 10, all 25 |
| Loadout | 1 slot, 3 slots, all 5 |
| Gold held at once | 1,000 → 10,000 |
| Gold earned overall | 100 → 100,000 |
| Timed sessions, wins, swift wins, wounded wins | 1 → 250 |
| Day streak, perfect runs, best day, well-rounded stats | several tiers each |

Achievements unlock themselves; there is nothing to claim. Unlocking one is
announced in the adventure log and in a toast at the top of the screen.

---

## 9. Settings

The Settings tab holds preferences that apply to the whole app.

### Alarm sound

- Choose from four built-in sounds — **Bell**, **Chime**, **Woodblock** and
  **Ping**. They are synthesised by the app, so they need no files and work
  offline.
- Or use **Choose a sound file…** to pick your own.

**Your own sound must be:**

| | |
|---|---|
| **Format** | WAV, MP3 or OGG |
| **Size** | 2 MB or smaller |

You do **not** have to put the file anywhere. Picking it copies it into the
app's own `sounds` folder next to your save, and it plays from there. Replacing
it swaps the file; **Remove custom file** deletes it and returns to a built-in
sound. The file is checked, not trusted: the wrong format or a file over the
limit is refused with a message telling you which rule it broke.

**Volume** (0–100%) applies to built-in and custom sounds alike. **▶ Test sound**
plays the current choice at the current volume. The 🔔 button on the session
panel mutes everything temporarily without changing these settings.

---

## 10. Your save file

Everything — hero, quests, completions, gear, achievements, the log and your
settings — lives in one SQLite file:

```
%APPDATA%\Habit Quest\habitquest.db
```

A custom alarm, if you added one, sits beside it in `%APPDATA%\Habit Quest\sounds\`.

Paste `%APPDATA%\Habit Quest` into the address bar of File Explorer to open the
folder.

### Backing up

Close the app, copy `habitquest.db` somewhere safe. To restore, close the app and
copy it back over the existing file.

### Moving to another computer

Install Habit Quest there, then replace its `habitquest.db` with your copy.
Everything comes with it.

### Starting over

**Journal → Reset save** wipes the save and returns you to the hero-creation
screen. There is no undo, so take a copy of the file first if you might want it
back.

The standalone app and the `python app.py` version keep **separate** saves; they
do not share a file.

---

## 11. Troubleshooting

**Nothing happens when I double-click the icon.** Give it a few seconds on the
first launch. If it still does not open, check Task Manager for a hung
`Habit Quest` process, end it, and try again.

**"Windows protected your PC".** Click **More info → Run anyway**. The app is not
code-signed, which is what triggers the warning.

**"Habit Quest could not start" dialog.** The game server behind the window could
not launch. This normally only happens with a test build that expects Python on
the machine — reinstall from the normal installer, which carries its own copy.

**The window opens but the page is blank.** Close and reopen. If it stays blank,
your save may be from an incompatible build: rename `habitquest.db` to
`habitquest-old.db` and reopen to see whether a fresh save works. (Keep the old
file — it usually can be migrated.)

**Two copies are open.** Only one can run at a time; the second launch brings the
first window forward instead of opening a second one.

**The alarm is silent.** Check the volume slider in Settings, press **▶ Test
sound**, and make sure the 🔔 button on the session panel is not muting it. Some
Windows sound settings mute individual apps.

**A quest is not in the list.** It is probably in **Resting today** at the bottom
of the Quests tab — its schedule does not include today. Edit it and change
**Available on** if that is wrong.

**My streak did not break over the weekend.** That is intended: rest days do not
count against you. A day only counts if at least one quest was scheduled for it.

**The Pomodoro keeps going after I finish.** Press **✓ Finish · N rounds** on the
timer panel — the rounds are endless until you say stop. Use **⏸ Pause quest** if
you want to stop without completing it today.

---

## 12. Quick answers

**Does it need the internet?** No. Everything is local, including the sounds.

**Does anything leave my computer?** No. There is no account, no telemetry and no
cloud sync.

**Can I run it on a Mac or Linux?** The packaged build is Windows-only today.
The source version runs anywhere Python does (`python app.py`).

**How do I start with a populated demo instead of a blank hero?** Click **Peek
at a demo save** on the first screen.

**What if I miss a day?** Nothing catastrophic. A streak that had something
scheduled breaks, and a missed Beat the Clock timer costs some HP. Everything
else waits for you.

**How do I retire a quest without losing its history?** Press **📦** on its
card. It moves to the Archived section at the bottom of the Quests tab and
**↩ Re-engage** brings it back whenever you want.

**Can I make a quest stop after a certain number of times?** Yes — set **Repeat**
to *Ends after a set number of times* when you create or edit the quest. It
archives itself after the last one.

**Can I have more than one hero?** Not inside one save. To run a second, keep a
copy of `habitquest.db` and swap files (or use `python app.py --db other.db` with
the source version).
