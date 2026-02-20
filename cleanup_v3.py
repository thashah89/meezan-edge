#!/usr/bin/env python3
"""
cleanup_v3.py - Automated cleanup script for Meezan Edge v3.0

Removes all v1.5 files and keeps only v3.0 system.
"""

import os
from pathlib import Path

# Files to DELETE (v1.5 old files)
FILES_TO_DELETE = [
    'backtester.py',
    'data_cache.py',
    'live_engine.py',
    'market_data.py',
    'pattern_engine.py',
    'trend_filter.py',
    'zerodha_auth.py',
    'scraper.py',
    'old_halal_scraper.py',
    'CHANGELOG.md',
    'DEPLOYMENT_GUIDE.md',
    'README.md',
    'halal_stocks_cache.json',
    'halal_cache.json',
    'MeezanEdge_UserGuide.pptx',
    'run.bat',
    'report.txt',
]

# Directories to DELETE
DIRS_TO_DELETE = [
    '.devcontainer',
]

# V3.0 ESSENTIAL FILES (for verification)
V3_ESSENTIAL_FILES = [
    'app.py',
    'config.py',
    'database_schema.py',
    'market_intel_engine.py',
    'capital_allocator.py',
    'trade_selector.py',
    'paper_trader.py',
    'ml_trainer.py',
    'halal_scraper.py',
    'utils_indicators.py',
    '__init__.py',
    'run.py',
    'requirements.txt',
]

def verify_v3_files():
    """Verify all v3.0 essential files are present."""
    missing = []
    for file in V3_ESSENTIAL_FILES:
        if not Path(file).exists():
            missing.append(file)
    return missing

def cleanup():
    """Remove all v1.5 files."""
    print("🧹 Meezan Edge v3.0 Cleanup Tool")
    print("=" * 50)
    print()
    
    # Verify v3 files first
    print("1️⃣ Verifying v3.0 files are present...")
    missing = verify_v3_files()
    
    if missing:
        print(f"❌ ERROR: Missing v3.0 essential files:")
        for f in missing:
            print(f"   - {f}")
        print("\n⚠️  Cannot proceed. Please download all v3.0 files first.")
        return False
    
    print(f"✅ All {len(V3_ESSENTIAL_FILES)} v3.0 files present")
    print()
    
    # Show what will be deleted
    print("2️⃣ Files to be deleted (v1.5 old system):")
    files_found = []
    for file in FILES_TO_DELETE:
        if Path(file).exists():
            size = Path(file).stat().st_size
            files_found.append(file)
            print(f"   📄 {file} ({size:,} bytes)")
    
    for dir_name in DIRS_TO_DELETE:
        if Path(dir_name).exists():
            files_found.append(dir_name)
            print(f"   📁 {dir_name}/")
    
    if not files_found:
        print("   (No v1.5 files found - already clean!)")
        print()
        print("✅ Your project is already clean and ready for v3.0")
        return True
    
    print()
    print(f"Total: {len(files_found)} items will be deleted")
    print()
    
    # Confirm
    response = input("3️⃣ Proceed with deletion? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("❌ Cleanup cancelled")
        return False
    
    print()
    print("4️⃣ Deleting files...")
    
    deleted_count = 0
    failed_count = 0
    
    # Delete files
    for file in FILES_TO_DELETE:
        if Path(file).exists():
            try:
                Path(file).unlink()
                print(f"   ✅ Deleted: {file}")
                deleted_count += 1
            except Exception as e:
                print(f"   ❌ Failed: {file} ({e})")
                failed_count += 1
    
    # Delete directories
    for dir_name in DIRS_TO_DELETE:
        if Path(dir_name).exists():
            try:
                import shutil
                shutil.rmtree(dir_name)
                print(f"   ✅ Deleted: {dir_name}/")
                deleted_count += 1
            except Exception as e:
                print(f"   ❌ Failed: {dir_name}/ ({e})")
                failed_count += 1
    
    print()
    print("=" * 50)
    print(f"✅ Cleanup complete!")
    print(f"   Deleted: {deleted_count} items")
    if failed_count > 0:
        print(f"   Failed: {failed_count} items")
    print()
    print("🚀 Your v3.0 system is now clean and ready!")
    print()
    print("Next steps:")
    print("  1. Run: python database_schema.py  (if first time)")
    print("  2. Run: python run.py")
    print("  3. Access: http://localhost:8501")
    print()
    
    return True

if __name__ == "__main__":
    try:
        cleanup()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
