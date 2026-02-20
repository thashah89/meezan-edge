#!/bin/bash
# start.sh - Easy startup script for Meezan Edge v3.0

echo "🧠 Meezan Edge v3.0 - Autonomous Hedge Fund"
echo "==========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: app.py not found"
    echo "Please run this script from the project directory"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+"
    exit 1
fi

echo "✅ Python found: $(python3 --version)"

# Check if database exists
if [ ! -f "meezan_v3.db" ]; then
    echo "📊 Initializing database..."
    python3 database_schema.py
    echo "✅ Database created"
else
    echo "✅ Database exists"
fi

# Check dependencies
echo "📦 Checking dependencies..."
python3 -c "import streamlit" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Installing dependencies..."
    pip install -r requirements.txt
fi

echo ""
echo "🚀 Launching Meezan Edge..."
echo "   Access at: http://localhost:8501"
echo ""

# Set Python path and run
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
streamlit run app.py
