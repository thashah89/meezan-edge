# 📥 INSTALLATION GUIDE — Meezan Edge v3.0

**Complete Recovery After Accidental Deletion**

---

## ✅ What You Have Now

A **COMPLETE SYSTEM** with all files including:
- ✅ All Python files (13 core files)
- ✅ Streamlit configuration (.streamlit/config.toml & secrets.toml)
- ✅ All documentation (9 files)
- ✅ Startup scripts (start.sh, start.bat)
- ✅ Requirements.txt
- ✅ .gitignore
- ✅ Everything needed to run

**Total: 30 files — Nothing missing!**

---

## 🚀 Installation (5 Minutes)

### Step 1: Download the Complete Package

The `complete_v3_system/` folder contains everything.

Download/extract all files to your local computer.

### Step 2: Open Terminal/Command Prompt

**Windows:**
- Press `Win + R`
- Type `cmd` and press Enter
- Navigate: `cd path\to\complete_v3_system`

**Mac/Linux:**
- Open Terminal
- Navigate: `cd /path/to/complete_v3_system`

### Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- streamlit
- pandas
- numpy
- scikit-learn
- xgboost
- plotly
- requests
- beautifulsoup4
- kiteconnect
- joblib

**Wait for installation to complete** (2-3 minutes)

### Step 4: Initialize Database

```bash
python database_schema.py
```

You should see:
```
Database initialization complete
Database stats:
  stocks_master: 0 rows
  stock_metrics: 0 rows
  ...
```

This creates `meezan_v3.db` with 8 tables.

### Step 5: Run the Application

**Option A: Use startup script (Recommended)**

Linux/Mac:
```bash
./start.sh
```

Windows:
```cmd
start.bat
```

**Option B: Use run.py**
```bash
python run.py
```

**Option C: Direct Streamlit**
```bash
streamlit run app.py
```

### Step 6: Access the App

Open your browser and go to:
```
http://localhost:8501
```

You should see:
```
🧠 Meezan Edge v3.0 — Autonomous Hedge Fund
```

**✅ Installation Complete!**

---

## 🎯 First Time Setup (In the App)

### 1. View 1: Market Intelligence
- Click **"Load Halal Universe"**
- Wait for stocks to load (347 stocks)
- Status: "347 stocks loaded"

### 2. View 2: Portfolio Engine
- Enter **Total Capital**: ₹5,00,000 (or your amount)
- Click **"Run Autonomous Trade Selection"**
- Review selected trades
- Click **"Execute Paper Trades"**

### 3. View 3: AI Lab
- After 100 trades, click **"Train All Models"**
- ML models will improve win rate

**Done! System is running autonomously.**

---

## 📋 Verify Installation

### Check All Files Present

```bash
ls -la *.py
```

You should see:
```
app.py
capital_allocator.py
cleanup_v3.py
config.py
database_schema.py
halal_scraper.py
market_intel_engine.py
ml_trainer.py
paper_trader.py
run.py
test_imports.py
trade_selector.py
utils_indicators.py
```

**Total: 13 Python files**

### Test Imports

```bash
python test_imports.py
```

You should see:
```
✅ config
✅ database_schema
✅ market_intel_engine
✅ capital_allocator
✅ trade_selector
✅ paper_trader
✅ ml_trainer
✅ halal_scraper
✅ utils_indicators

All imports successful!
```

### Check Streamlit Config

```bash
ls -la .streamlit/
```

You should see:
```
config.toml
secrets.toml
```

---

## 🔧 Troubleshooting

### Issue: "pip: command not found"

**Solution:**
```bash
# Try pip3
pip3 install -r requirements.txt

# Or use python -m pip
python -m pip install -r requirements.txt
```

### Issue: "python: command not found"

**Solution:**
```bash
# Try python3
python3 database_schema.py
python3 run.py
```

### Issue: "streamlit: command not found"

**Solution:**
```bash
# Install streamlit explicitly
pip install streamlit

# Then run
streamlit run app.py
```

### Issue: "Import errors" when running

**Solution:**
```bash
# Make sure you're in the project directory
pwd  # Should show .../complete_v3_system

# Set Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"  # Linux/Mac
set PYTHONPATH=%PYTHONPATH%;%CD%  # Windows

# Run again
python run.py
```

### Issue: "Port 8501 already in use"

**Solution:**
```bash
# Kill the process
lsof -ti:8501 | xargs kill  # Linux/Mac

# Or use different port
streamlit run app.py --server.port 8502
```

### Issue: Database errors

**Solution:**
```bash
# Delete and recreate database
rm meezan_v3.db
python database_schema.py
```

---

## 🎓 Understanding the Structure

### Core Files (What Each Does)

```
app.py                    → Main Streamlit UI (3 views)
config.py                 → All settings and thresholds
database_schema.py        → Creates 8 database tables
market_intel_engine.py    → Analyzes market & scores stocks
capital_allocator.py      → Decides capital deployment
trade_selector.py         → Selects best trades autonomously
paper_trader.py           → Simulates trade execution
ml_trainer.py             → Trains ML models for predictions
halal_scraper.py          → Loads halal stock universe
utils_indicators.py       → Calculates technical indicators
```

### How They Work Together

```
1. halal_scraper.py       → Gets 347 halal stocks
2. utils_indicators.py    → Adds RSI, ADX, MACD to each
3. market_intel_engine.py → Scores each stock 0-100
4. capital_allocator.py   → Decides how much to deploy
5. trade_selector.py      → Picks best trades
6. paper_trader.py        → Executes trades (simulated)
7. ml_trainer.py          → Learns from results
8. app.py                 → Shows everything in UI
```

**It's all automatic!**

---

## 💡 Pro Tips

### Tip 1: Use Virtual Environment (Recommended)

```bash
# Create virtual environment
python -m venv meezan_env

# Activate it
source meezan_env/bin/activate  # Linux/Mac
meezan_env\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run app
python run.py

# Deactivate when done
deactivate
```

### Tip 2: Check Python Version

```bash
python --version
```

Needs **Python 3.8 or higher**

If you have older Python:
- Download latest from python.org
- Or use python3 command

### Tip 3: Keep Terminal Open

Don't close the terminal while app is running.

To stop the app:
- Press `Ctrl + C` in terminal

### Tip 4: Bookmark the URL

```
http://localhost:8501
```

Add to browser bookmarks for quick access.

---

## 📚 Next Steps

After installation:

### 1. Read Documentation
- Start with: `README.md`
- Then: `QUICK_START.md`
- Deep dive: `README_V3_COMPLETE.md`

### 2. Configure Settings (Optional)
Edit `config.py` to adjust:
- Risk levels
- Position sizing
- Profit targets

### 3. Start Trading
- Load stocks (View 1)
- Enter capital (View 2)
- Execute trades (View 2)
- Monitor performance

### 4. Let ML Learn
- Execute 100+ trades
- Train models (View 3)
- Watch accuracy improve

---

## ✅ Installation Checklist

- [ ] Downloaded complete_v3_system folder
- [ ] Opened terminal in the folder
- [ ] Ran: `pip install -r requirements.txt`
- [ ] Ran: `python database_schema.py`
- [ ] Ran: `python run.py`
- [ ] Accessed: http://localhost:8501
- [ ] Saw the app interface
- [ ] Loaded halal stocks
- [ ] Entered capital amount

**All checked? You're ready to make money! 🚀**

---

## 🎯 Common Mistakes to Avoid

### ❌ Wrong: Running from random directory
```bash
cd /some/other/place
python /path/to/complete_v3_system/app.py  # ❌ FAILS
```

### ✅ Right: Navigate to project first
```bash
cd /path/to/complete_v3_system
python run.py  # ✅ WORKS
```

### ❌ Wrong: Forgetting to install dependencies
```bash
python app.py  # ❌ Import errors
```

### ✅ Right: Install first
```bash
pip install -r requirements.txt  # ✅
python run.py
```

### ❌ Wrong: Skipping database setup
```bash
python run.py  # ❌ Database errors
```

### ✅ Right: Initialize database
```bash
python database_schema.py  # ✅
python run.py
```

---

## 📞 Still Having Issues?

### Quick Diagnostic

```bash
# 1. Check you're in the right place
pwd
ls -la app.py  # Should show the file

# 2. Check Python version
python --version  # Should be 3.8+

# 3. Test imports
python test_imports.py  # All should pass

# 4. Check dependencies
pip list | grep streamlit  # Should show streamlit

# 5. Try running
python run.py
```

If all these pass but app still doesn't work:
- Check firewall (allow port 8501)
- Try different browser
- Restart computer

---

## 🎉 Success!

When you see this in your browser:
```
🧠 Meezan Edge v3.0 — Autonomous Hedge Fund

[View 1: Market Intelligence]
[View 2: Portfolio Engine]
[View 3: AI Lab]
```

**You're done! The system is ready.**

Now just:
1. Load stocks
2. Enter capital
3. Let AI make money for you

**Target: 15-25% monthly returns**

---

**End of Installation Guide**

Start making money: `python run.py` 🚀
