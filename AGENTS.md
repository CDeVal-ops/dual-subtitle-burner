# Repository Guidelines

## Project Structure & Module Organization
- `dual-subtitle-burner.py`: PyQt5 GUI entry point; orchestrates batch processing and FFmpeg calls.
- `sub-merger.py`: `SubMerger` class for merging/normalizing two ASS subtitle tracks into one.
- `README.md`: Basic usage and requirements.
- Runtime data: `%USERPROFILE%/Documents/Dual Sub Burner Settings` (logs, settings, temp merged `.ass`).
- No dedicated `tests/` directory yet; contributions adding tests are welcome.

## Build, Test, and Development Commands
- Create/activate venv (Windows): `py -m venv .venv && .venv\Scripts\activate`
- Install deps: `pip install pyqt5` (dev: `pip install pytest black ruff`)
- Run app (Windows): `py dual-subtitle-burner.py`  (macOS/Linux: `python3 dual-subtitle-burner.py`)
- Verify FFmpeg in PATH: `ffmpeg -version`

## Coding Style & Naming Conventions
- Follow PEP 8; 4‑space indentation.
- Names: functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- Modules: prefer `snake_case.py` for new importable files (avoid hyphens); scripts at root may be CLI/GUI entry points.
- Use `pathlib.Path` for paths; avoid `print`—use the configured `logging` (writes to console and `batch_log.txt`).
- Optional tools: format with `black` (line length 88) and lint with `ruff` before opening PRs.

## Testing Guidelines
- Framework: `pytest`. Place tests under `tests/` with files named `test_*.py`.
- Scope: add unit tests for pure logic (e.g., time parsing/normalization in `SubMerger`).
- Run: `pytest -q` (optionally `pytest -k sub_merger` for focused runs).

## Commit & Pull Request Guidelines
- Commits: concise, imperative subject; include a brief rationale. Examples inspired by history:
  - "Refactor: extract SubMerger from GUI"
  - "Fix: normalize overlapping dialogues"
- PRs: clear description, steps to run locally, before/after behavior, screenshots for UI changes, and linked issues. Keep changes focused and small.

## Security & Configuration Tips
- FFmpeg: ensure `ffmpeg`/`ffprobe` are installed and on PATH; the app auto‑detects encoders (NVENC/AMF/QSV) and falls back to CPU.
- File I/O: the app writes settings/logs to `Documents/Dual Sub Burner Settings`; avoid hard‑coded absolute paths.
- Large files/paths: handle spaces/non‑ASCII safely; use `Path` joins and quote shell args when necessary.

