@echo off
chcp 65001 > nul
echo.
echo ========================================================
echo   🛡️  Media Sanitizer - Moca's Purity Filter 🌸
echo ========================================================
echo.
echo  [INFO] Starting sanitization process...
echo  [INFO] Target: ./input -> ./output
echo.
echo  Starting Docker environment...
echo --------------------------------------------------------

docker-compose up --build

echo --------------------------------------------------------
echo.
echo  ✅ Process Finished!
echo  Check the './output' folder for your sanitized files.
echo.
pause
