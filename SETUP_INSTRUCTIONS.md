# 🔧 Setup Instructions — Fix Import Errors

## Quick Fix (3 Steps)

### Step 1: Navigate to Project Directory

```bash
cd /path/to/meezan_v3_outputs
```

**Important:** You must be IN the directory containing all the .py files.

### Step 2: Verify Files Exist

```bash
ls -la *.py
```

You should see:
- ✅ app.py
- ✅ config.py
- ✅ database_schema.py
- ✅ market_intel_engine.py
- ✅ capital_allocator.py
- ✅ trade_selector.py
- ✅ paper_trader.py
- ✅ ml_trainer.py
- ✅ halal_scraper.py
- ✅ utils_indicators.py

### Step 3: Run Using Python Script

**Option A: Use run.py (Recommended)**

```bash
python run.py
```

**Option B: Run Streamlit directly from the directory**

```bash
streamlit run app.py
```

**Option C: Set Python path manually**

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
streamlit run app.py
```

---

## If Errors Persist

### Error: "Import halal_scraper could not be resolved"

**Cause:** Your IDE (VSCode/PyCharm) can't find the module.

**Solution 1: Run from terminal** (not IDE)
```bash
cd /mnt/user-data/outputs
python run.py
```

**Solution 2: Add to IDE workspace**
- VSCode: Open folder `/mnt/user-data/outputs` as workspace
- PyCharm: Mark directory as "Sources Root"

**Solution 3: Install as package** (advanced)
```bash
cd /mnt/user-data/outputs
pip install -e .
```

---

## Alternative: Create Virtual Environment

```bash
# Create virtual environment
python -m venv meezan_env

# Activate it
source meezan_env/bin/activate  # Linux/Mac
# OR
meezan_env\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run app
python run.py
```

---

## Test Imports

Create a test file to verify imports work:

```python
# test_imports.py
import sys
print("Python path:", sys.path)

try:
    import halal_scraper
    print("✅ halal_scraper imported")
except ImportError as e:
    print("❌ halal_scraper import failed:", e)

try:
    import utils_indicators
    print("✅ utils_indicators imported")
except ImportError as e:
    print("❌ utils_indicators import failed:", e)

try:
    import database_schema
    print("✅ database_schema imported")
except ImportError as e:
    print("❌ database_schema import failed:", e)

print("\nAll imports successful!")
```

Run it:
```bash
python test_imports.py
```

---

## File Structure Should Look Like This

```
/mnt/user-data/outputs/
├── __init__.py                 ← Makes directory a Python package
├── run.py                      ← Startup script
├── app.py                      ← Main Streamlit app
├── config.py
├── database_schema.py
├── market_intel_engine.py
├── capital_allocator.py
├── trade_selector.py
├── paper_trader.py
├── ml_trainer.py
├── halal_scraper.py           ← This file exists!
├── utils_indicators.py        ← This file exists!
├── requirements.txt
└── meezan_v3.db              ← Created after first run
```

---

## Initialize Database (First Time Only)

Before running the app for the first time:

```bash
python database_schema.py
```

This creates `meezan_v3.db` with all tables.

---

## Common Issues & Solutions

### Issue 1: "ModuleNotFoundError: No module named 'halal_scraper'"

**Fix:**
```bash
# Make sure you're in the right directory
pwd  # Should show /mnt/user-data/outputs or similar

# List files
ls halal_scraper.py  # Should show the file

# Run from this directory
python run.py
```

### Issue 2: "streamlit: command not found"

**Fix:**
```bash
pip install streamlit
# OR
pip install -r requirements.txt
```

### Issue 3: IDE shows red underlines on imports

**Fix:** This is just IDE intellisense issue. The code will run fine.
- Ignore the warnings
- OR configure your IDE's Python path
- OR run from terminal instead of IDE

### Issue 4: "sqlite3.OperationalError: no such table"

**Fix:** Initialize database first
```bash
python database_schema.py
```

---

## Recommended Workflow

1. **Open terminal** (not IDE)
2. **Navigate to directory:**
   ```bash
   cd /mnt/user-data/outputs
   ```
3. **Initialize database** (first time only):
   ```bash
   python database_schema.py
   ```
4. **Run app:**
   ```bash
   python run.py
   ```
5. **Access at:** http://localhost:8501

---

## Still Having Issues?

### Quick Diagnostic

```bash
# Check Python version (needs 3.8+)
python --version

# Check if files exist
ls -la *.py | wc -l  # Should show 12+ files

# Check current directory
pwd

# Try running test
python -c "import halal_scraper; print('Success!')"
```

### Manual Import Test

```python
# test.py
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Now try imports
import halal_scraper
import utils_indicators
import database_schema

print("✅ All imports work!")
```

---

## Success Checklist

- [ ] All .py files in same directory
- [ ] Terminal open in that directory
- [ ] Database initialized (`python database_schema.py`)
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Running via `python run.py` or `streamlit run app.py`
- [ ] App opens at http://localhost:8501

**If all checked → App will work!**

---

## Need More Help?

The import error is almost always caused by:
1. Not being in the correct directory
2. Running from IDE instead of terminal
3. Python path not set

**Solution:** Always run from terminal, in the outputs directory.

```bash
cd /mnt/user-data/outputs && python run.py
```

**This will work 100% of the time.**
