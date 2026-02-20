#!/usr/bin/env python3
"""
test_imports.py - Verify all imports work correctly
"""

import sys
from pathlib import Path

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

print("🧪 Testing Meezan Edge v3.0 Imports")
print("=" * 50)
print(f"Current directory: {current_dir}")
print(f"Python path: {sys.path[0]}")
print()

# Test each import
imports_to_test = [
    'config',
    'database_schema',
    'market_intel_engine',
    'capital_allocator',
    'trade_selector',
    'paper_trader',
    'ml_trainer',
    'halal_scraper',
    'utils_indicators'
]

failed = []
passed = []

for module_name in imports_to_test:
    try:
        __import__(module_name)
        print(f"✅ {module_name}")
        passed.append(module_name)
    except ImportError as e:
        print(f"❌ {module_name}: {e}")
        failed.append(module_name)
    except Exception as e:
        print(f"⚠️  {module_name}: {type(e).__name__}: {e}")
        failed.append(module_name)

print()
print("=" * 50)
print(f"Results: {len(passed)} passed, {len(failed)} failed")

if failed:
    print(f"\n❌ Failed imports: {', '.join(failed)}")
    print("\nTroubleshooting:")
    print("1. Make sure you're running from the project directory")
    print("2. Check that all .py files exist")
    print("3. Try: cd /mnt/user-data/outputs && python test_imports.py")
    sys.exit(1)
else:
    print("\n✅ All imports successful!")
    print("You're ready to run the app:")
    print("   python run.py")
    print("   OR")
    print("   streamlit run app.py")

