# Desktop launcher

A Windows window to start and stop the sparring bot without a terminal, Python or uv (feature F17). It is an
Electron app that runs the bot as a child process and shows what it says.

## Using it (players)

1. Install `UnmatchedSparring-Setup-<version>.exe` (it installs for your user only, no administrator needed) and open
   **Unmatched Sparring** from the Start menu.
2. Open Tabletop Simulator and load the tournament savegame (Unmatched Official Tournament Table). Sit in the
   **White** seat: the bot plays **Green**.
3. Pick the options (or leave them as they are) and press **START** (EMPEZAR in Spanish). The status line says
   "Connecting to Tabletop Simulator..." and then "Playing". Play with the bot's panel on the table.
4. Press **STOP** (PARAR) to finish. The bot removes its panel and the floor labels, the same as Ctrl+C on the command
   line. Closing the window while it plays does the same before the window goes.

**CHECK THE TABLE** runs the read-only check (`--read-only`): it reads the table, changes nothing, and prints the
report in the console area.

The options are the command line ones (see the main README, section 4): who goes first, both heroes (automatic or a
hero, never the same on both sides), language (English by default; the selector at the top right of the window changes it, the window follows it too, and the choice is remembered), the AI and its think time, the pause
between bot actions, resume the saved game. **Advanced** holds the ports, a configuration file and `--timing`.

Where things are kept:

| What | Where |
|---|---|
| Last options used | `%APPDATA%\Unmatched Sparring\options.json` |
| Saved game and its log | `%LOCALAPPDATA%\UnmatchedSparring\state\session.json` and `session.log` |
| Bot program and its data | `resources\bot\` inside the install folder |

Errors come in plain words: Tabletop Simulator not open, a port already in use (another bot running), the
configuration unreadable, or the reason the bot gives for not starting (shown in the console area).

## Building (developers)

Requirements: Node.js 22 and npm, [uv](https://docs.astral.sh/uv/) (it fetches Python 3.11 and PyInstaller by
itself; nothing is installed in the project's `.venv`).

```powershell
cd launcher
npm install
npm test              # unit tests of the launcher (node:test, no extra dependencies)
npm run dev           # the window, running the bot with `uv run python -m sparring.play` from the repository
npm run build:bot     # PyInstaller: build\bot-dist\sparring-bot\sparring-bot.exe (+ _internal\ with data\ and config\)
npm run dist          # build:bot, then electron-builder: dist\UnmatchedSparring-Setup-<version>.exe
```

If `npm install` leaves `node_modules\electron\dist` empty (the download can fail silently behind a TLS-inspecting
proxy), run `$env:NODE_OPTIONS="--use-system-ca"; node node_modules\electron\install.js`. The same
`NODE_OPTIONS` helps electron-builder download its tools. `build:bot` already passes `--system-certs` to uv.

How it fits together:

- `bot\sparring_bot.py` is the PyInstaller entry (`sparring.play.main`). The build is one folder, not one file, so
  the bot starts without unpacking itself to a temporary folder every time. `data\` and `config\table.json` sit in
  `_internal\` next to the code, where `sparring` already looks for them. From the frozen exe the default `--state`
  is under `%LOCALAPPDATA%\UnmatchedSparring\state` (the install folder may not be writable).
- The launcher always passes `--launcher` to the bot: UTF-8 output, one `[sparring:status] <state>` line per change
  (`connecting`, `playing`, `error <kind>`, `exit <code>`), and a `quit` line on its stdin (or stdin closing) stops it
  cleanly. If it has not exited 15 s after STOP, the launcher kills the process tree.
- `src\main.js` (main process, IPC), `src\bot.js` (child process and the protocol), `src\options.js` (options to
  command line, validation), `src\store.js` (hero list from `data\heroes\*.json`, saved options),
  `src\renderer\` (the window, no Node access: `contextIsolation` and `sandbox`), `src\i18n\` (the window's texts in
  Spanish and English).

The installer is not code-signed: Windows SmartScreen will warn the first time ("More info", "Run anyway").
