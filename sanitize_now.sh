#!/usr/bin/env bash
set -e

echo "========================================================"
echo " 🛡️  Media Sanitizer - Moca's Purity Filter 🌸"
echo "========================================================"
echo
echo "[INFO] Starting sanitization process..."
echo "[INFO] Target: ./input -> ./output"
echo

echo "[INFO] Starting Docker environment..."
echo "--------------------------------------------------------"

docker compose up --build --abort-on-container-exit

echo "--------------------------------------------------------"
echo
echo "✅ Process Finished!"
echo "Check the './output' folder for your sanitized files."

