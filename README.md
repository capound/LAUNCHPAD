# LAUNCHPAD

One window for everything you reach for: apps, games, folders, files, links,
multi-step actions (like turning on your VPN) and project notes. Black and white,
with swappable ASCII art (Sisyphus by default) at the top of the home screen.

## Install (Windows 11)

1. Have **Python 3.10+** installed (python.org, tick "Add python.exe to PATH").
2. Put this folder somewhere permanent, e.g. `Documents\Launchpad`.
   The desktop shortcut and startup entry point here, so don't run it from Downloads.
3. Double-click **install.bat**.

It installs PySide6, opens Launchpad, puts a shortcut on your desktop and sets
Launchpad to start with Windows (hidden in the tray) so the hotkey always works.

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
| Projects | **Ctrl+P**, or the PROJECTS section on the home screen |
| To-do list | **Ctrl+T** |
| Calendar | **Ctrl+K** |

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

## VPN action (Surfshark)

Surfshark on Windows can't be switched on by another program, so the VPN action
opens Surfshark. To make that one click:

1. In Surfshark's settings, turn on its **auto-connect** option.
2. In Launchpad, the action **VPN ON (Surfshark)** is created automatically on
   first run if Surfshark is installed. You can also build your own under ACTIONS
   with the **+ SURFSHARK VPN STEP** button.

Actions can chain steps, for example: open Surfshark → wait 5 s → open a folder →
open a website.

## Projects

Clicking a project on the home screen lists everything pinned to it, so you can
open one item or all of them without leaving home.

The project page has notes (autosaved), a to-do list (tick, double-click to edit,
drag to reorder, Delete to remove) and a **PINNED** list of files, folders and
links (click to open, drag to reorder, right-click to edit or remove). Drop
anything onto a project page to pin it.

## To-do

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

## ASCII art

Use the **ART ▾** button on the art itself to:

- pick the art: Sisyphus, Sisyphus (compact strip), LAUNCHPAD title, Clock,
  Campsite, Old man fishing, Rotating globe, Saturn, Storm
- pick a different art for when the window isn't maximised
- set the size: Small, Medium or Large share of the window height. Every art
  scales to fit that space, so swapping art never moves anything else.
- change speed, pause it, or hide it (click SHOW ART to bring it back)

### Your own art

**ART ▾ → Open custom art folder** opens `%APPDATA%\Launchpad\art`. Any `.txt`
file in there appears in the art list (use **Reload custom art** after adding one).
There's an `example-rocket.txt` to copy.

- One frame = plain ASCII art. For animation, put a line reading `---frame---`
  between frames.
- Optional first line `fps 8` sets the speed (frames per second).

## Your data and updating

Everything (items, pins, projects, to-dos, reminders, settings, custom art) is saved in
`%APPDATA%\Launchpad\`, not in this folder, with a backup copy
`launchpad.json.bak` made at every start.

**To update:** quit Launchpad (tray icon → Quit), unzip the new version over this
folder, and start it again. Nothing needs re-adding. Export/Import backup in
Settings is for moving to another PC or keeping an extra copy.

## Files

- `launchpad.pyw`: the app (one file)
- `launchpad.ico`: icon
- `install.bat`: setup
- `build_exe.bat`: optional standalone .exe build
