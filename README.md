# Project Wunderwaffe — Day Timer Scanner

**One file only:** `wunderwaffe_scanner.py`

## For your friend (simple)

1. Install **Python 3.10+** → https://www.python.org/downloads/  
   Check **Add Python to PATH**.
2. Download / copy `wunderwaffe_scanner.py` onto the PC.
3. Double-click it  
   (or run: `python wunderwaffe_scanner.py`)
4. Browse to:
   ```
   C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe
   ```
5. Click **Start Scan**.
6. Send back **both** files from the `scan_logs` folder:
   - `wunderwaffe_scan_....txt`
   - `wunderwaffe_scan_....json`

Nothing is changed in the game. Phase 2 (change 120 → 9999999 days) comes after the logs.

## Optional CLI

```bat
python wunderwaffe_scanner.py --cli "C:\Program Files (x86)\Steam\steamapps\common\Project Wunderwaffe"
```
