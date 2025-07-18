# dual-subtitle-burner
Dual Subtitle Batch Processor
A Python-based GUI application for efficiently burning two subtitle tracks onto multiple video files in a single batch process.

(Note: You should replace this link with a URL to your own screenshot!)

Core Features
Batch Processing: Select and process entire groups of videos and subtitles at once, saving significant time.

Intelligent File Matching: Select videos, top subtitles, and bottom subtitles from different folders. The application automatically pairs them based on a sorted filename match.

Interactive Confirmation & Reordering: Review all proposed file pairings in a clean table. Use dropdown menus to easily correct any mismatches and "Move Up/Down" buttons to change the processing order.

Hardware-Accelerated Encoding: The application auto-detects the best available GPU encoder on your system (NVIDIA NVENC, AMD AMF, or Intel QSV) for maximum speed. If no hardware encoder is found, it seamlessly falls back to a high-quality CPU-based encoder.

Real-time Monitoring: A dedicated panel displays live statistics from FFmpeg during the encoding process, including FPS, bitrate, and speed.

Modern UI: Features a polished, professional dark theme that is easy on the eyes, including a native dark title bar on modern Windows systems.

Persistent Memory: Remembers the last-used folders for each file selector to streamline your workflow across sessions.

Detailed Logging: Automatically generates a batch_log.txt file for easy troubleshooting.

Workflow
Select Files: Click "Select Video Files," "Select Top Subtitle Files," and "Select Bottom Subtitle Files" to choose your corresponding groups of media.

Match & Preview: Click "Preview Matched Files." The app will sort the lists and display its best guess for the pairings in the table below.

Confirm & Reorder: Review the pairings. Use the dropdown menus in each row to correct any mismatches and the "Move Up/Down" buttons to set your desired processing order.

Process: Choose your Output Folder and click "Start Batch."

Requirements
Python 3.x

PyQt5 (pip install pyqt5)

FFmpeg (must be downloaded from the official site and the location of ffmpeg.exe must be added to your system's PATH).

How to Run
Save the code as a .py file (e.g., batch_burner.py) and run it from your terminal:

PowerShell

py dual-subtitle-burner.py