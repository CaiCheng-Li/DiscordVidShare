@echo off
REM Generates a 30s 720p test clip (color pattern + 440Hz tone) for testing.
cd /d "%~dp0\.."
ffmpeg -y -f lavfi -i testsrc=duration=30:size=1280x720:rate=30 ^
       -f lavfi -i sine=frequency=440:duration=30 ^
       -c:v libx264 -pix_fmt yuv420p -c:a aac sample.mp4
echo.
echo Wrote sample.mp4
