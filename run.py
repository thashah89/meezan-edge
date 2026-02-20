#!/usr/bin/env python3
"""
run.py — Simple launcher for Meezan Edge v3.0

Usage: python run.py
"""

import sys
import os
from pathlib import Path

# Ensure we're in the correct directory
script_dir = Path(__file__).parent
os.chdir(script_dir)

# Add to path
sys.path.insert(0, str(script_dir))

print("🧠 Meezan Edge v3.0 — Autonomous Hedge Fund System")
print("=" * 60)
print()

# Check dependencies
print("Checking dependencies...")
missing = []

try:
    import streamlit
    print("✅ streamlit")
except ImportError:
    missing.append("streamlit")
    print("❌ streamlit")

try:
    import pandas
    print("✅ pandas")
except ImportError:
    missing.append("pandas")
    print("❌ pandas")

try:
    import plotly
    print("✅ plotly")
except ImportError:
    missing.append("plotly")
    print("❌ plotly")

try:
    import xgboost
    print("✅ xgboost")
except ImportError:
    missing.append("xgboost")
    print("❌ xgboost")

try:
    import sklearn
    print("✅ scikit-learn")
except ImportError:
    missing.append("scikit-learn")
    print("❌ scikit-learn")

print()

if missing:
    print(f"⚠️  Missing dependencies: {', '.join(missing)}")
    print()
    print("Install with:")
    print("  pip install -r requirements.txt")
    print()
    sys.exit(1)

# Check database
db_path = script_dir / "meezan_v3.db"
if not db_path.exists():
    print("⚠️  Database not initialized")
    print()
    print("Run this first:")
    print("  python database_schema.py")
    print()
    
    try:
        response = input("Initialize database now? (y/n): ")
        if response.lower() == 'y':
            print("\nInitializing database...")
            from database_schema import init_database
            init_database()
            print("✅ Database initialized")
        else:
            sys.exit(1)
    except:
        print("\nPlease run: python database_schema.py")
        sys.exit(1)
else:
    print("✅ Database found")

print()
print("=" * 60)
print("🚀 Launching Meezan Edge v3.0...")
print("=" * 60)
print()

# Launch Streamlit
import subprocess
subprocess.run([
    sys.executable, "-m", "streamlit", "run", 
    str(script_dir / "app.py"),
    "--server.headless", "true"
])
