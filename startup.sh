#!/bin/bash

# Teams Bot Application Startup Script
# Supports both main.py (unified) and app.py (Flask + Teams AI integration)

echo "🚀 Starting Teams Bot Application..."
echo "📊 Environment: $(env | grep -E '(BOT_|OPENAI_|GRAPH_|PORT)' | wc -l) variables configured"

# Check which entry point to use
if [ -f "main.py" ]; then
    echo "📌 Using main.py (unified Teams AI entry point)"
    python main.py
elif [ -f "app.py" ]; then
    echo "📌 Using app.py (Flask + Teams AI integration)"
    python app.py
else
    echo "❌ No entry point found (main.py or app.py)"
    exit 1
fi 