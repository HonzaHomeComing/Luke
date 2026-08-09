# Project Wunderwaffe — Save tools

All tools are **one `.py` file**. No pip packages.

## Save editor — `wunderwaffe_save_editor.py`

Decrypts a save into a **readable report** + editable JSON.

### Steps
1. Install Python 3.10+ (check **Add Python to PATH**)
2. **Close the game**
3. Double-click `wunderwaffe_save_editor.py` (or `run_save_editor.bat`)
4. Click **Decrypt save…** → pick a file in `SaveGame`
5. Open **`readable_report.txt`** first (clean summary)
6. Edit **`editable_values.json`** — change `"new_value"`
7. Click **Apply edits…**
8. Load the save in-game

### Important finding
Steam `SaveGame\save_game_pww_*` files are **Main_Level base layouts** (rooms/resources).
They do **not** store the front-day timer.

Also check:
```
%LOCALAPPDATA%\ProjectWunderwaffe\
%LOCALAPPDATA%\ProjectWunderwaffe\Saved\SaveGames\
```
Or start a **new game**, save immediately at ~120 days, and decrypt that.

### CLI
```bat
python wunderwaffe_save_editor.py --decrypt "C:\...\SaveGame\continue_save_game_pww"
python wunderwaffe_save_editor.py --apply "C:\...\continue_save_game_pww_decrypted\editable_values.json"
```

## Older tools
- `wunderwaffe_scanner.py` — Phase 1 full-install scan (already used)
- `wunderwaffe_patcher.py` — older auto-patcher (optional)
