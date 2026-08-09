# Project Wunderwaffe — Day Timer Tools

Phase **1** is ready: a scanner that walks your game install, decodes common encodings, hunts for the **120 in-game-day** timer (and related front/day values), and writes logs.

Phase **2** (patcher that changes `120` → `9999999` and launches the game) will be built **after you send the scan logs**.

## What you do now

1. Install **Python 3.10+** from https://www.python.org/downloads/  
   (on Windows, enable **Add Python to PATH**).
2. Copy this project folder to your PC (or clone the repo).
3. Double-click `run_scanner.bat`  
   or run:
   ```bat
   python -m wunderwaffe_scanner
   ```
4. Browse to your Steam install, usually:
   ```
   C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe
   ```
   Also worth a second scan on:
   ```
   ...\Project Wunderwaffe\ProjectWunderwaffe\SaveGame
   ```
5. Click **Start Scan**. When it finishes, open the log folder.
6. Send back **both** files:
   - `wunderwaffe_scan_YYYYMMDD_HHMMSS.txt`
   - `wunderwaffe_scan_YYYYMMDD_HHMMSS.json`

## CLI (no GUI)

```bat
python -m wunderwaffe_scanner --cli "C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe" --out .\scan_logs
```

## What the scanner looks for

- Literal / binary encodings of `120` (int16/32/64, float, ASCII, UTF-16)
- Related values (hours/seconds for 120 days)
- Keywords: days, front days, days left, timer, deadline, etc.
- Gzip/zlib-wrapped blobs inside data files
- String tables inside `.dll` / `.exe` / save / asset files

It **does not modify** any game files.

## After you send the logs

The next app will:

1. Target the exact file(s) identified in your log
2. Patch the day timer to **9999999**
3. Save a backup + patched copy
4. Launch the changed game
