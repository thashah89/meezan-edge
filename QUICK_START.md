# 🚀 QUICK START — Fix Import Issues

## ⚡ FASTEST Solution (Copy-Paste This)

```bash
# 1. Navigate to the folder with all files
cd /path/to/meezan_v3_complete

# 2. Install dependencies
pip install -r requirements.txt

# 3. Initialize database (one time only)
python database_schema.py

# 4. Launch the app
python run.py
```

**App opens at http://localhost:8501**

---

## 🔧 If You See "Import halal_scraper could not be resolved"

This is a **path issue**. The fix depends on how you're running it:

### ✅ Fix 1: Use the Launcher (Recommended)

```bash
cd /path/to/meezan_v3_complete
python run.py
```

The launcher automatically fixes path issues.

---

### ✅ Fix 2: Run from Command Line

```bash
# Make sure you're IN the directory
cd /path/to/meezan_v3_complete

# Then run
streamlit run app.py
```

**Key:** You MUST be in the directory with all the .py files.

---

### ✅ Fix 3: Use Virtual Environment (Best Practice)

```bash
# Create virtual environment
python -m venv venv

# Activate
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate          # Windows

# Install
pip install -r requirements.txt

# Run
streamlit run app.py
```

---

## 📁 Verify File Structure

All files must be in SAME folder:

```
your-folder/
├── app.py
├── config.py
├── halal_scraper.py       ← This file MUST be here
├── database_schema.py
├── market_intel_engine.py
├── capital_allocator.py
├── trade_selector.py
├── paper_trader.py
├── ml_trainer.py
├── utils_indicators.py
├── requirements.txt
└── run.py
```

Check with:
```bash
ls *.py | wc -l    # Should show 10+ files
```

---

## 🐍 VS Code / PyCharm Users

### VS Code:
1. Open FOLDER (not individual files): `File → Open Folder`
2. Open terminal: `Terminal → New Terminal`
3. Run: `streamlit run app.py`

### PyCharm:
1. Open project: `File → Open`
2. Right-click folder → Mark Directory as Sources Root
3. Terminal: `streamlit run app.py`

---

## ✅ Test Imports Work

Run this one-liner:

```bash
python -c "import sys; sys.path.insert(0, '.'); import halal_scraper; print('✅ Import OK')"
```

If you see "✅ Import OK", imports work!

---

## 🎯 Common Errors

**Error:** `ModuleNotFoundError: No module named 'halal_scraper'`  
**Fix:** Run from correct directory: `cd /path/to/folder && streamlit run app.py`

**Error:** `ModuleNotFoundError: No module named 'streamlit'`  
**Fix:** Install dependencies: `pip install -r requirements.txt`

**Error:** `FileNotFoundError: app.py`  
**Fix:** You're in wrong folder. Use `cd` to navigate to correct folder.

---

## 🚀 Ready to Launch?

Once imports work:

1. Initialize database: `python database_schema.py`
2. Launch app: `python run.py` OR `streamlit run app.py`
3. Open browser: http://localhost:8501
4. Start trading!

---

**Target: 15-25% monthly returns**
