# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment (Windows)
py -m venv .venv && .venv\Scripts\activate

# Install dependencies
pip install pyqt5

# Development dependencies (optional)
pip install pytest black ruff
```

### Running the Application
```bash
# Windows
py dual-subtitle-burner.py

# macOS/Linux
python3 dual-subtitle-burner.py
```

### Testing and Quality
```bash
# Run tests (when available)
pytest -q

# Run focused tests on SubMerger
pytest -k sub_merger

# Format code (optional)
black dual-subtitle-burner.py sub-merger.py

# Lint code (optional)
ruff dual-subtitle-burner.py sub-merger.py

# Verify FFmpeg is available
ffmpeg -version
```

## Architecture Overview

This is a PyQt5-based GUI application for batch processing video files with dual subtitle tracks. The application consists of two main components:

### Core Modules

- **`dual-subtitle-burner.py`**: Main GUI application using PyQt5. Handles file selection, batch processing orchestration, and FFmpeg execution with hardware acceleration auto-detection (NVENC/AMF/QSV fallback to CPU).

- **`sub-merger.py`**: Contains the `SubMerger` class responsible for merging two ASS subtitle files into a single file. Handles subtitle parsing, time normalization, overlap detection, and positioning logic.

### Key Architecture Patterns

- **Separation of Concerns**: GUI logic in the main script, subtitle processing logic isolated in `SubMerger` class
- **Hardware Acceleration**: Auto-detects best available GPU encoder (NVIDIA NVENC → AMD AMF → Intel QSV → CPU fallback)
- **File Matching System**: Intelligent pairing of video files with corresponding top and bottom subtitle files based on sorted filename matching
- **Asynchronous Processing**: Uses QThread for non-blocking batch processing with real-time progress updates

### Data Flow

1. User selects video files, top subtitles, and bottom subtitles through GUI
2. Application sorts and matches files by filename similarity
3. User confirms/adjusts pairings in interactive table
4. `SubMerger` processes each subtitle pair:
   - Parses ASS files and extracts styles/events
   - Maps original styles to standardized master styles
   - Handles overlapping subtitle positioning (raises bottom subtitles when needed)
   - Outputs merged ASS file to temporary location
5. FFmpeg processes each video with merged subtitles using optimal encoder
6. Progress and statistics displayed in real-time

### File System Integration

- **Settings Directory**: `%USERPROFILE%/Documents/Dual Sub Burner Settings` (Windows)
- **Logging**: Automatic `batch_log.txt` generation for troubleshooting
- **Persistent State**: Remembers last-used folders across sessions
- **Temporary Files**: Merged subtitle files stored in settings directory during processing

## Coding Conventions

- **Style**: Follow PEP 8 with 4-space indentation
- **Naming**: `snake_case` for functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
- **Path Handling**: Use `pathlib.Path` instead of string concatenation
- **Logging**: Use configured logging instead of `print()` statements
- **Error Handling**: Graceful fallbacks for hardware detection and file processing