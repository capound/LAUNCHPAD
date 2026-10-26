# LAUNCHPAD

One window for everything you reach for: apps, games, folders, files, links,
multi-step actions (like turning on your VPN), tasks, projects, a calendar and
daily goals. Black and white by default (or any colours you like), with swappable
ASCII art (Sisyphus by default) at the top of the home screen.

## Install (Windows 11)

1. Have **Python 3.10+** installed (python.org, tick "Add python.exe to PATH").
2. Put this folder somewhere permanent, e.g. `Documents\Launchpad`.
   The desktop shortcut and startup entry point here, so don't run it from Downloads.
3. Double-click **install.bat**.

It installs PySide6 (plus the optional song-info support for the media controls),
opens Launchpad, puts a shortcut on your desktop and sets Launchpad to start with
Windows (hidden in the tray) so the hotkey always works.

Optional: **build_exe.bat** makes a standalone `dist\Launchpad.exe` that doesn't
need Python.

## Using it

| Do this | How |
|---|---|
| Show / hide from anywhere | **Ctrl+Shift+Space** (change in Settings) |
| Find and open something | Start typing, then press **Enter** to open the top match |
| Add something | Drag it onto the window or onto a section, or use **+ ADD** / **Ctrl+N** |
| Move to another section, or reorder | Drag the tile onto a section (or between tiles) |
| Use a file/folder/link somewhere else | Drag the tile out to your desktop, Explorer, an email, a browser or an app. It drops a copy (hold Alt for a shortcut); the original never moves |
| Keep something at the very top | Right-click → **Pin to top**, or drag it into **PINNED** |
| Collapse a section | Click its header (`[-]` / `[+]`) |
| Edit, pin to a project, remove | Right-click any tile |
| Workbench tabs | **Ctrl+T** tasks · **Ctrl+P** projects · **Ctrl+K** calendar · **Ctrl+G** goals |
| Settings | the gear at the bottom of the sidebar, or **Ctrl+,** |

**What you can drop in:** programs (.exe), shortcuts (.lnk), folders, any file,
links dragged from your browser's address bar, and Steam game shortcuts.

**Lost files:** if something moves or gets deleted, its tile goes grey with a
strikethrough and a `?`. Right-click → Edit to point it at the new location.
**RECENT** at the top always shows the last 8 things you opened.

## Games

- **Steam:** in your Steam library, right-click a game → Manage → *Add desktop
  shortcut*, then drag that shortcut onto GAMES. Or add a link like
  `steam://rungameid/730`.
- **Riot / Battle.net / others:** drag the desktop shortcut the launcher made onto
  GAMES. That keeps the launch arguments, e.g. Riot's
  `RiotClientServices.exe --launch-product=valorant --launch-patchline=live`.

## Sidebar

Below the sections: **media controls** (previous / play-pause / next, plus song
and artist; this works with Spotify, YouTube in a browser, Apple Music and
anything else in Windows' volume flyout), a **clock** with the day and date, **+ ADD**
and the **settings gear**. The sidebar clock hides while the home screen is
showing the Clock art, so you don't get two clocks.

Song names need a one-off install (done by `install.bat`, or **Settings → Media →
TURN ON SONG INFO**). Without it the buttons still work as media keys.

## Workbench

Tasks, Projects, Calendar and Goals live together under **WORKBENCH**, one tab each.

## Projects

Clicking a project on the home screen lists everything pinned to it, so you can
open one item or all of them without leaving home.

The project page has notes (autosaved), a to-do list (tick, double-click to edit,
drag to reorder, Delete to remove) and a **PINNED** list of files, folders and
links (click to open, drag to reorder, right-click to edit or remove). Drop
anything onto a project page to pin it.

## Tasks

Each task has an **urgency meter**: 5 boxes, click box 1 (least) to 5 (most).
You can also set an optional **do-by date** (TODAY / TOMORROW / +1 WEEK buttons
or pick a date) and **notes**. Sort by urgency, do-by date or newest; tick a task
to mark it done (**show done** brings finished ones back).

**DUE SOON & URGENT** on the home screen shows any task at urgency 5, anything due
within 2 days (or overdue), and calendar reminders for today and tomorrow. Tick
a task there to finish it, or click it to open it.

## Calendar

A month view (Monday first). Click a day to see its reminders and the to-dos due
that day; double-click a day to start typing a reminder. Reminders can have an
optional time (`14:30`). To-dos with a do-by date appear on their day
automatically, and you can add a to-do due on the selected day from the side panel.

## Daily goals

**GOALS → + NEW GOAL**: pick a template (water, push-ups, calories, steps…) or
start from scratch. Set a daily target and a unit, and choose whether to **reach it**
or **stay under it** (good for calories or coffee).

- **Quick-add buttons** add a percentage of the target (10%, 25%, 50% by
  default; change them per goal). The button shows the actual amount, e.g. `+500 ml`.
- **Type an amount** and press Enter for anything else. A minus number takes some away.
  **UNDO** removes the last entry.
- Click the big number to set today's total directly.
- Each card shows the **last 7 days** (`#` hit, `+` some, `x` over the limit,
  `.` nothing) and your **streak**.
- Counts reset at midnight. Goals you don't use often can go in the **archive**
  (`...` → Archive) and come back any time.
- **TODAY'S GOALS** on the home screen shows a compact bar for each goal. Click
  one to log without leaving home.

## Themes

**Settings → Theme**: Mono, Paper (light), Amber terminal, Green phosphor, Deep
ocean, Dusk or Slate. Or click BACKGROUND / TEXT / ACCENT to pick any colour. The
ASCII art follows the text colour; the accent is used for highlights and borders.

## ASCII art

Use the **ART ▾** button on the art itself to:

- pick the art: Sisyphus, LAUNCHPAD title, Clock, Old man fishing, Rain on
  water, Paper planes, Underwater, Rotating globe, Saturn, Storm. Older ones
  (compact Sisyphus, Campsite, Rocket) are under **Deprecated**.
- pick a different art for when the window isn't maximised
- set the size: Small, Medium or Large share of the window height. Every art
  scales to fit that space, so swapping art never moves anything else.
- change speed, pause it, or hide it (click SHOW ART to bring it back)

### Your own art

**ART ▾ → Open custom art folder** opens `%APPDATA%\Launchpad\art`. Any `.txt`
file in there appears in the art list (use **Reload custom art** after adding one).
There's an `_example.txt` to copy (files starting with `_` aren't listed).

- One frame = plain ASCII art. For animation, put a line reading `---frame---`
  between frames.
- Optional first line `fps 8` sets the speed (frames per second).

## Your data and updating

Everything (items, pins, projects, to-dos, reminders, settings, custom art) is saved in
`%APPDATA%\Launchpad\`, not in this folder, with a backup copy
`launchpad.json.bak` made at every start.

**Updates:** Launchpad checks GitHub for a new release when it starts and shows a
bar at the top when one is out: **WHAT'S NEW**, **UPDATE NOW** (downloads,
installs and restarts), **LATER** or **SKIP THIS VERSION**. **Settings → Updates
→ CHECK NOW** checks straight away. The previous version is kept in
`%APPDATA%\Launchpad\backups`.

Updating by hand also works: unzip the new version over this folder and open it.
A newer copy automatically takes over from an older one still running in the tray.

Export/Import backup in Settings is for moving to another PC or keeping an extra copy.

See `CHANGELOG.md` for what changed in each version, and `RELEASING.md` for how to
publish an update.

## Files

- `launchpad.pyw`: the app (one file)
- `launchpad.ico`: icon
- `install.bat`: setup
- `build_exe.bat`: optional standalone .exe build
- `CHANGELOG.md`: what changed in each version
- `RELEASING.md`: how to publish an update on GitHub
