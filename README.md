# Project Wunderwaffe — Save tools

All tools are **one `.py` file**. No pip packages.

## Save editor (what you want now) — `wunderwaffe_save_editor.py`

Decrypts a save so your friend can edit values himself.

### Steps
1. Install Python 3.10+ (check **Add Python to PATH**)
2. **Close the game**
3. Double-click `wunderwaffe_save_editor.py` (or `run_save_editor.bat`)
4. Click **Decrypt save…** → pick a file in `SaveGame`
5. Open **`editable_values.json`** in Notepad
6. Change `"new_value"` (example: `120` → `9999999`)
7. Click **Apply edits…** → select that JSON
8. Load the save in-game

Also created next to it:
- `decoded_strings.txt` — readable text from the save (search Front / Days)
- `original_save.bak` — untouched copy
- `READ_ME.txt` — same instructions

### CLI
```bat
python wunderwaffe_save_editor.py --decrypt "C:\...\SaveGame\continue_save_game_pww"
python wunderwaffe_save_editor.py --apply "C:\...\continue_save_game_pww_decrypted\editable_values.json"
```

## Older tools
- `wunderwaffe_scanner.py` — Phase 1 full-install scan (already used)
- `wunderwaffe_patcher.py` — older auto-patcher (optional)
