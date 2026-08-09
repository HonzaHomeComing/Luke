# Project Wunderwaffe — Day Timer Tools

Two single-file Python apps (no pip packages).

## 1) Scanner — `wunderwaffe_scanner.py`
Finds clues about the 120-day timer. Already done if you sent the logs.

## 2) Patcher — `wunderwaffe_patcher.py`  ← use this now

Your scan showed an **Unreal Engine** game. Save strings are stored as `byte - 1`
(e.g. `F\`ld.Ldbg\`mhbr` → `Game/Mechanics`). The patcher uses that to find
Front/Days fields and set them to **9999999**.

### Friend-proof steps
1. Install Python 3.10+ (check **Add Python to PATH**).
2. **Close Project Wunderwaffe.**
3. Double-click `wunderwaffe_patcher.py`
4. Confirm the game folder (Steam `...\Project Wunderwaffe`)
5. Click **1) Analyze saves**
6. Click **2) Patch selected/high scores**
7. Click **3) Launch game**

Backups are written next to each save as `*.bak`.

### Optional CLI
```bat
python wunderwaffe_patcher.py --cli-analyze
python wunderwaffe_patcher.py --cli-patch --launch
```

### If patch finds nothing strong
Also click **Analyze exe default**, then patch again.  
If it still fails, send one save file from:
`...\Project Wunderwaffe\ProjectWunderwaffe\SaveGame\`
