import sys
import os
import subprocess
import json
import re
import logging
from pathlib import Path
from collections import Counter

try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    ctypes = None

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QGroupBox,
    QFormLayout,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QAbstractItemView,
    QComboBox,
    QCheckBox,
)

# --- Constants ---
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
DARK_MODE_STYLESHEET = """
    QWidget { background-color: #2b2b2b; color: #dcdcdc; font-family: Segoe UI; font-size: 9pt; }
    QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 5px; margin-top: 7px; }
    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; }
    QPushButton { background-color: #555; border: 1px solid #666; padding: 5px; border-radius: 3px; min-height: 18px; }
    QPushButton:hover { background-color: #6a6a6a; }
    QPushButton:pressed { background-color: #4a4a4a; }
    QPushButton:disabled { background-color: #404040; color: #888; }
    QTableWidget { border: 1px solid #444; border-radius: 3px; gridline-color: #444; }
    QTextEdit { border: 1px solid #444; border-radius: 3px; background-color: #222; }
    QComboBox { border: 1px solid #444; border-radius: 3px; padding: 3px; background-color: #3c3c3c; }
    QComboBox::drop-down { border: none; }
    QHeaderView::section { background-color: #3c3c3c; padding: 4px; border: 1px solid #555; }
    QProgressBar { border: 1px solid #444; border-radius: 3px; text-align: center; color: #dcdcdc; }
    QProgressBar::chunk { background-color: #007acc; border-radius: 2px; }
    QLabel#statsLabel { font-family: Consolas, 'Courier New', monospace; background-color: #222; border: 1px solid #444; padding: 4px; border-radius: 3px; }
"""


# --- Main Application Class ---
class SubtitleMergerApp(QWidget):
    def __init__(self):
        super().__init__()
        # --- File Paths and Settings ---
        self.output_folder = Path.home() / "Videos"
        self.settings_dir = Path.home() / "Documents" / "Dual Sub Burner Settings"
        self.settings_file = self.settings_dir / "settings.json"
        self.log_file = self.settings_dir / "batch_log.txt"

        self.last_vid_dir = Path.home()
        self.last_top_sub_dir = Path.home()
        self.last_bottom_sub_dir = Path.home()

        # --- Data Lists ---
        self.video_files = []
        self.top_sub_files = []
        self.bottom_sub_files = []
        self.matched_files = []

        # --- Processing Defaults ---
        self.ffmpeg_path = None
        self.ffprobe_path = None
        self.video_codec = "libx264"
        self.preset = "medium"
        self.batch_worker = None

        self.setup_logging()
        self.load_settings()
        self.init_ui()
        self.detect_ffmpeg()
        if self.ffmpeg_path:
            self.detect_encoders()

    def setup_logging(self):
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.log_file, mode="a", encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
        logging.info("--- Application Starting ---")

    def init_ui(self):
        self.setWindowTitle("Dual Subtitle Batch Processor")
        self.setGeometry(100, 100, 1300, 900)
        self.setStyleSheet(DARK_MODE_STYLESHEET)

        main_layout = QHBoxLayout(self)
        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()

        # --- Left Panel: File Selection ---
        vid_box = QGroupBox("1. Select Video Files")
        vid_layout = QHBoxLayout()
        self.vid_list_widget = QTextEdit()
        self.vid_list_widget.setReadOnly(True)
        btn_vid = QPushButton("Select Videos...")
        btn_vid.clicked.connect(self.select_video_files)
        vid_layout.addWidget(self.vid_list_widget)
        vid_layout.addWidget(btn_vid)
        vid_box.setLayout(vid_layout)
        top_sub_box = QGroupBox("2. Select Top Subtitle Files")
        top_layout = QHBoxLayout()
        self.top_sub_list_widget = QTextEdit()
        self.top_sub_list_widget.setReadOnly(True)
        btn_top = QPushButton("Select Top Subs...")
        btn_top.clicked.connect(self.select_top_subs)
        top_layout.addWidget(self.top_sub_list_widget)
        top_layout.addWidget(btn_top)
        top_sub_box.setLayout(top_layout)
        bot_sub_box = QGroupBox("3. Select Bottom Subtitle Files")
        bot_layout = QHBoxLayout()
        self.bottom_sub_list_widget = QTextEdit()
        self.bottom_sub_list_widget.setReadOnly(True)
        btn_bot = QPushButton("Select Bottom Subs...")
        btn_bot.clicked.connect(self.select_bottom_subs)
        bot_layout.addWidget(self.bottom_sub_list_widget)
        bot_layout.addWidget(btn_bot)
        bot_sub_box.setLayout(bot_layout)

        self.preview_button = QPushButton("Match & Preview Files")
        self.preview_button.clicked.connect(self.preview_matched_files)

        left_panel.addWidget(vid_box, 1)
        left_panel.addWidget(top_sub_box, 1)
        left_panel.addWidget(bot_sub_box, 1)
        left_panel.addWidget(self.preview_button)

        # --- Right Panel: Confirmation and Controls ---
        confirm_box = QGroupBox("4. Confirm and Reorder Matches")
        confirm_layout = QVBoxLayout()
        self.confirm_table = QTableWidget()
        self.confirm_table.setColumnCount(5)
        self.confirm_table.setHorizontalHeaderLabels(
            ["Process", "Video File", "Top Subtitle", "Bottom Subtitle", "Status"]
        )
        self.confirm_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.confirm_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.confirm_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.confirm_table.setColumnWidth(0, 50)
        self.confirm_table.setColumnWidth(4, 100)

        reorder_layout = QHBoxLayout()
        btn_up = QPushButton("Move Up")
        btn_down = QPushButton("Move Down")
        btn_clear = QPushButton("Clear Batch")
        btn_up.clicked.connect(lambda: self.move_row(-1))
        btn_down.clicked.connect(lambda: self.move_row(1))
        btn_clear.clicked.connect(self.clear_batch)
        reorder_layout.addStretch()
        reorder_layout.addWidget(btn_clear)
        reorder_layout.addWidget(btn_up)
        reorder_layout.addWidget(btn_down)
        confirm_layout.addWidget(self.confirm_table)
        confirm_layout.addLayout(reorder_layout)
        confirm_box.setLayout(confirm_layout)

        controls_box = QGroupBox("5. Process Files")
        controls_layout = QFormLayout()
        output_layout = QHBoxLayout()
        self.output_label = QLabel(str(self.output_folder))
        btn_output = QPushButton("Select...")
        btn_output.clicked.connect(self.select_output_folder)
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(btn_output)

        self.mode_selector = QComboBox()
        self.mode_selector.addItems(
            ["Soft Burn (Mux Combined Track)", "Mux Separate Tracks", "Burn (Hardsubs)"]
        )
        controls_layout.addRow("Output Folder:", output_layout)
        controls_layout.addRow("Processing Mode:", self.mode_selector)

        self.start_button = QPushButton("Start Batch")
        self.start_button.clicked.connect(self.start_batch)
        self.cancel_button = QPushButton("Cancel Batch")
        self.cancel_button.clicked.connect(self.cancel_batch)
        self.cancel_button.setDisabled(True)
        controls_layout.addRow(self.start_button, self.cancel_button)
        controls_box.setLayout(controls_layout)

        # --- Right Panel: Monitoring ---
        monitor_box = QGroupBox("Monitoring")
        monitor_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Current File: %p% | Overall: 0/0")

        stats_grid = QHBoxLayout()
        self.fps_label = QLabel("FPS: --")
        self.fps_label.setObjectName("statsLabel")
        self.speed_label = QLabel("Speed: --")
        self.speed_label.setObjectName("statsLabel")
        self.bitrate_label = QLabel("Bitrate: --")
        self.bitrate_label.setObjectName("statsLabel")
        stats_grid.addWidget(self.fps_label)
        stats_grid.addWidget(self.speed_label)
        stats_grid.addWidget(self.bitrate_label)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFontFamily("Consolas")
        self.log_display.setLineWrapMode(QTextEdit.NoWrap)

        utility_layout = QHBoxLayout()
        self.status_label = QLabel("Ready.")
        utility_layout.addWidget(self.status_label, 1)
        btn_open_log = QPushButton("Open Log")
        btn_open_log.clicked.connect(self.open_log_file)
        btn_open_folder = QPushButton("Open Output")
        btn_open_folder.clicked.connect(self.open_output_folder)
        utility_layout.addWidget(btn_open_log)
        utility_layout.addWidget(btn_open_folder)

        monitor_layout.addWidget(self.progress_bar)
        monitor_layout.addLayout(stats_grid)
        monitor_layout.addWidget(self.log_display)
        monitor_layout.addLayout(utility_layout)
        monitor_box.setLayout(monitor_layout)

        right_panel.addWidget(confirm_box, 2)
        right_panel.addWidget(controls_box, 0)
        right_panel.addWidget(monitor_box, 1)
        main_layout.addLayout(left_panel, 1)
        main_layout.addLayout(right_panel, 3)

    def select_files(self, title, initial_dir, file_filter):
        files, _ = QFileDialog.getOpenFileNames(
            self, title, str(initial_dir), file_filter
        )
        if files:
            return [Path(f) for f in sorted(files)], Path(files[0]).parent
        return [], initial_dir

    def select_video_files(self):
        self.video_files, self.last_vid_dir = self.select_files(
            "Select Video Files", self.last_vid_dir, "Video Files (*.mp4 *.mkv)"
        )
        self.vid_list_widget.setText("\n".join(p.name for p in self.video_files))

    def select_top_subs(self):
        self.top_sub_files, self.last_top_sub_dir = self.select_files(
            "Select Top Subs", self.last_top_sub_dir, "Subtitle Files (*.ass)"
        )
        self.top_sub_list_widget.setText("\n".join(p.name for p in self.top_sub_files))

    def select_bottom_subs(self):
        self.bottom_sub_files, self.last_bottom_sub_dir = self.select_files(
            "Select Bottom Subs", self.last_bottom_sub_dir, "Subtitle Files (*.ass)"
        )
        self.bottom_sub_list_widget.setText(
            "\n".join(p.name for p in self.bottom_sub_files)
        )

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(self.output_folder)
        )
        if folder:
            self.output_folder = Path(folder)
            self.output_label.setText(str(self.output_folder))

    def clear_batch(self):
        (
            self.video_files,
            self.top_sub_files,
            self.bottom_sub_files,
            self.matched_files,
        ) = ([], [], [], [])
        self.vid_list_widget.clear()
        self.top_sub_list_widget.clear()
        self.bottom_sub_list_widget.clear()
        self.confirm_table.setRowCount(0)
        self.status_label.setText("Batch cleared.")

    def preview_matched_files(self):
        """
        Intelligently matches video and subtitle files by extracting and comparing
        their specific episode numbers. All logic is self-contained in this method.
        """

        def extract_episode_number(filename: str) -> int | None:
            """
            (Nested function) Extracts the episode number from a filename.

            It uses a series of common patterns, ordered from most specific to
            most general, to find the correct number.
            """
            # Captures numbers from formats like: S02E01, 2x01, [01], - 01.
            patterns = [
                r"[._ -]S\d+[Ee](\d+)",  # S02E01, S02E12
                r"[._ -](\d+)[xX]\d+",  # 02x01, 2x12
                r"[._ -]E(\d+)[._ -]",  # E01, E12
                r"\[(\d{2,3})\]",  # [01], [12], [123]
                r"-\s*(\d{2,3})\s*[\.\[]",  # - 01., - 12 [
            ]

            for pattern in patterns:
                match = re.search(pattern, filename, re.IGNORECASE)
                if match:
                    try:
                        # Return the first captured group as an integer
                        return int(match.group(1))
                    except (ValueError, IndexError):
                        continue

            logging.warning(
                f"Could not extract a definitive episode number from: {filename}"
            )
            return None

        # --- Main matching logic begins here ---
        self.matched_files = []

        # Create dictionaries mapping episode numbers to subtitle files for fast lookups.
        top_sub_map = {extract_episode_number(f.name): f for f in self.top_sub_files}
        bottom_sub_map = {
            extract_episode_number(f.name): f for f in self.bottom_sub_files
        }

        # Remove None keys in case some subs couldn't be parsed
        top_sub_map.pop(None, None)
        bottom_sub_map.pop(None, None)

        for vid_file in self.video_files:
            match_info = {
                "video": vid_file,
                "top": None,
                "bottom": None,
                "process": True,
            }

            # Extract the unique episode number for the video using the nested function
            episode_num = extract_episode_number(vid_file.name)

            if episode_num is None:
                logging.warning(
                    f"Could not find an episode number for video: {vid_file.name}. Skipping match."
                )
                self.matched_files.append(match_info)
                continue

            # Find matches directly using the episode number as the key
            match_info["top"] = top_sub_map.get(episode_num)
            match_info["bottom"] = bottom_sub_map.get(episode_num)

            self.matched_files.append(match_info)

        # self.update_confirm_table() # Your existing UI update function
        print(f"Processed {len(self.matched_files)} video files.")
        for match in self.matched_files:
            print(f"  Video: {match['video'].name}")
            print(f"    Top Sub: {match['top'].name if match['top'] else '---'}")
            print(
                f"    Bottom Sub: {match['bottom'].name if match['bottom'] else '---'}\n"
            )

        self.update_confirm_table()

    def update_confirm_table(self):
        self.confirm_table.setRowCount(len(self.matched_files))
        for row, match in enumerate(self.matched_files):
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk = QCheckBox()
            chk.setChecked(match["process"])
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_widget.setLayout(chk_layout)
            chk.stateChanged.connect(
                lambda state, r=row: self.update_match_process(r, state)
            )
            self.confirm_table.setCellWidget(row, 0, chk_widget)

            self.confirm_table.setCellWidget(
                row,
                1,
                self.create_file_combo(self.video_files, match["video"], row, "video"),
            )
            self.confirm_table.setCellWidget(
                row,
                2,
                self.create_file_combo(self.top_sub_files, match["top"], row, "top"),
            )
            self.confirm_table.setCellWidget(
                row,
                3,
                self.create_file_combo(
                    self.bottom_sub_files, match["bottom"], row, "bottom"
                ),
            )
            self.confirm_table.setItem(row, 4, QTableWidgetItem("Pending"))
        self.confirm_table.resizeRowsToContents()

    def create_file_combo(self, file_list, selected_file, row, key):
        combo = QComboBox()
        combo.addItem("None", None)
        for p in file_list:
            combo.addItem(p.name, p)
        if selected_file:
            try:
                combo.setCurrentIndex(file_list.index(selected_file) + 1)
            except ValueError:
                pass
        combo.currentIndexChanged.connect(
            lambda _, r=row, k=key, c=combo: self.update_match_file(
                r, k, c.currentData()
            )
        )
        return combo

    def update_match_process(self, row, state):
        self.matched_files[row]["process"] = state == Qt.Checked

    def update_match_file(self, row, key, path):
        self.matched_files[row][key] = path

    def move_row(self, direction):
        row = self.confirm_table.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if 0 <= new_row < len(self.matched_files):
            self.matched_files.insert(new_row, self.matched_files.pop(row))
            self.update_confirm_table()
            self.confirm_table.selectRow(new_row)

    def start_batch(self):
        final_jobs = [
            job
            for job in self.matched_files
            if job["process"] and job["video"] and job["top"] and job["bottom"]
        ]
        if not final_jobs:
            QMessageBox.warning(
                self,
                "No Valid Jobs",
                "Please ensure jobs are selected and all files are assigned.",
            )
            return
        self.log_display.clear()
        self.batch_worker = BatchWorker(self, final_jobs)
        self.batch_worker.job_started.connect(self.on_job_started)
        self.batch_worker.job_progress.connect(self.on_job_progress)
        self.batch_worker.job_finished.connect(self.on_job_finished)
        self.batch_worker.parsed_stats.connect(self.on_parsed_stats)
        self.batch_worker.raw_log.connect(self.log_display.append)
        self.batch_worker.batch_finished.connect(self.on_batch_finished)
        self.batch_worker.start()

    def cancel_batch(self):
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel()

    def on_job_started(self, row_index, total_jobs, video_path):
        self.status_label.setText(
            f"Starting job {row_index + 1}/{total_jobs}: {video_path.name}"
        )
        self.confirm_table.item(row_index, 4).setText("Processing...")
        self.progress_bar.setFormat(
            f"Current File: %p% | Overall: {row_index + 1}/{total_jobs}"
        )

    def on_job_progress(self, percentage):
        self.progress_bar.setValue(percentage)

    def on_job_finished(self, row_index, status):
        self.confirm_table.item(row_index, 4).setText(status)
        self.progress_bar.setValue(100)

    def on_parsed_stats(self, stats):
        self.fps_label.setText(f"FPS: {stats.get('fps', '--')}")
        self.speed_label.setText(f"Speed: {stats.get('speed', '--')}")
        self.bitrate_label.setText(f"Bitrate: {stats.get('bitrate', '--')}")

    def on_batch_finished(self, message):
        self.status_label.setText(message)
        self.progress_bar.setFormat("Complete!")
        QMessageBox.information(self, "Complete", "Batch processing has finished.")

    def open_log_file(self):
        os.startfile(self.log_file)

    def open_output_folder(self):
        os.startfile(self.output_folder)

    def detect_ffmpeg(self):
        try:
            self.ffmpeg_path = "ffmpeg"
            self.ffprobe_path = "ffprobe"
            subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                check=True,
                creationflags=CREATE_NO_WINDOW,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            QMessageBox.critical(
                self,
                "FFmpeg/FFprobe Not Found",
                "Please ensure FFmpeg is installed and in your system's PATH.",
            )
            self.ffmpeg_path = None
            self.ffprobe_path = None

    def detect_encoders(self):
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-encoders"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            encoders = result.stdout
            if "h264_nvenc" in encoders:
                self.video_codec = "h264_nvenc"
                self.preset = "p6"
            elif "h264_amf" in encoders:
                self.video_codec = "h264_amf"
                self.preset = "quality"
            elif "h264_qsv" in encoders:
                self.video_codec = "h264_qsv"
                self.preset = "medium"
            else:
                self.video_codec = "libx264"
                self.preset = "medium"
            logging.info(
                f"Using detected encoder: {self.video_codec} with preset {self.preset}"
            )
        except Exception as e:
            logging.error(f"Error detecting encoders: {e}")

    def merge_subs_for_batch(self, video_file, first_sub, second_sub):
        """
        Performs the definitive "style unification and vertical stacking" merge.
        This version uses a hybrid approach:
        - Priority-based style name mapping for the top (English) subtitles.
        - Style-name-based detection for the bottom (Chinese) subtitles, processing
          only a specific style and merging the rest directly.
        - Builds all styles from scratch with correct sizes and margin-based stacking.
        """
        try:
            # --- NESTED HELPER FUNCTIONS (UNCHANGED) ---
            def _parse_ass_file(sub_lines):
                styles, events = {}, []
                current_section = None
                for line in sub_lines:
                    line_strip_lower = line.strip().lower()
                    if line_strip_lower == "[v4+ styles]":
                        current_section = "styles"
                    elif line_strip_lower == "[events]":
                        current_section = "events"
                    elif line.strip().startswith("["):
                        current_section = None

                    if current_section == "styles" and line.lower().startswith(
                        "style:"
                    ):
                        try:
                            name = line.split(":", 1)[1].split(",")[0].strip()
                            styles[name] = line
                        except IndexError:
                            logging.warning(f"Could not parse style line: {line}")
                    elif current_section == "events" and (
                        line.lower().startswith("dialogue:")
                        or line.lower().startswith("comment:")
                    ):
                        events.append(line)
                return styles, events

            def create_top_style_map(original_styles, events):
                """Creates a style map for top subs based on known names and usage."""
                style_map = {}
                known_primary = {"Default"}
                known_secondary = {"Italics", "On Top Italic", "On Top", "OS"}

                for style_name in original_styles.keys():
                    if style_name in known_primary:
                        style_map[style_name] = "Top-Primary"
                    elif style_name in known_secondary:
                        style_map[style_name] = "Top-Secondary"

                # Fallback for unknown style names based on usage
                if not style_map:
                    dialogue_events = [
                        line for line in events if line.lower().startswith("dialogue:")
                    ]
                    if dialogue_events:
                        style_counts = Counter(
                            line.split(",", 9)[3].strip() for line in dialogue_events
                        )
                        if style_counts:
                            primary = style_counts.most_common(1)[0][0]
                            style_map[primary] = "Top-Primary"
                            if len(style_counts) > 1:
                                secondary = style_counts.most_common(2)[1][0]
                                if primary != secondary:
                                    style_map[secondary] = "Top-Secondary"
                return style_map

            # --- 1. PARSE BOTH FILES (UNCHANGED) ---
            sub1_text = first_sub.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            sub2_text = second_sub.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()

            styles1, events1 = _parse_ass_file(sub1_text)
            styles2, events2 = _parse_ass_file(sub2_text)

            # --- 2. CREATE MASTER STYLES FROM SCRATCH (UNCHANGED) ---
            final_styles = {
                "Top-Primary": "Style: Top-Primary,Arial,52,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,2.5,2,8,20,20,25,1",
                "Top-Secondary": "Style: Top-Secondary,Arial,44,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,-1,0,0,100,100,0,0,1,2.5,2,8,20,20,80,1",
                "Bottom-Primary": "Style: Bottom-Primary,Arial,52,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,2.5,2,2,20,20,80,1",
                "Bottom-Secondary": "Style: Bottom-Secondary,Arial,44,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,-1,0,0,100,100,0,0,1,2.5,2,2,20,20,25,1",
            }

            # --- 3. PROCESS AND REMAP EVENTS ---
            final_events = []
            tag_stripper = re.compile(r"\{\\[^\}]*?(an|pos|move|org)[^\}]*\}")

            # Process Top Subtitles using the priority-based style map (Unchanged)
            style_map1 = create_top_style_map(styles1, events1)
            for line in events1:
                # Process both Dialogue and Comment lines from the top sub
                if line.lower().startswith(("dialogue:", "comment:")):
                    try:
                        parts = line.split(",", 9)
                        original_style = parts[3].strip()
                        # Use a default style if the original isn't in the map
                        parts[3] = style_map1.get(original_style, "Top-Primary")
                        parts[9] = tag_stripper.sub("", parts[9])
                        final_events.append(",".join(parts))

                        # Preserve any unmapped styles that aren't being replaced
                        if (
                            original_style not in style_map1
                            and original_style not in final_styles
                        ):
                            if original_style in styles1:
                                final_styles[original_style] = styles1[original_style]
                    except IndexError:
                        final_events.append(line)  # Append malformed lines as-is
                else:
                    final_events.append(line)

            # ### MODIFIED SECTION ###
            # Process Bottom Subtitles using style-based separation
            for line in events2:
                # This check now handles both Dialogue and Comment lines correctly.
                if line.lower().startswith(("dialogue:", "comment:")):
                    try:
                        parts = line.split(",", 9)
                        original_style = parts[3].strip()

                        # Check if the style is the one designated for processing
                        if original_style == "Sub-CN":
                            # Process this line: remap style and strip tags
                            text_field = parts[9]
                            if text_field.strip().startswith("{\\an8}"):
                                parts[3] = "Bottom-Secondary"
                            else:
                                parts[3] = "Bottom-Primary"

                            parts[9] = tag_stripper.sub("", text_field)
                            final_events.append(",".join(parts))
                        else:
                            # This is the "remainder". Merge it directly.
                            # 1. Append the line without any modification.
                            final_events.append(line)
                            # 2. Ensure its original style definition is carried over if not already present.
                            if (
                                original_style not in final_styles
                                and original_style in styles2
                            ):
                                final_styles[original_style] = styles2[original_style]
                    except IndexError:
                        # Append malformed lines as-is to preserve them
                        final_events.append(line)
                else:
                    # Append non-event lines as-is (though _parse_ass_file should filter these out)
                    final_events.append(line)
            # ### END MODIFIED SECTION ###

            # --- 4. ASSEMBLE CLEAN FILE (UNCHANGED) ---
            clean_header = [
                "[Script Info]",
                "; Script generated by Dual Subtitle Burner - Final Method",
                "Title: Merged Subtitle",
                "ScriptType: v4.00+",
                "WrapStyle: 0",
                "PlayResX: 1920",
                "PlayResY: 1080",
                "Collisions: Normal",
            ]

            merged_content = clean_header
            merged_content.extend(
                [
                    "\n[V4+ Styles]",
                    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                ]
            )
            merged_content.extend(sorted(final_styles.values()))
            merged_content.extend(
                [
                    "\n[Events]",
                    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                ]
            )
            merged_content.extend(final_events)

            out_path = self.settings_dir / f"{video_file.stem}_temp_merged.ass"
            out_path.write_text("\n".join(merged_content), encoding="utf-8-sig")

            logging.info(
                f"Successfully performed final style-unification and stacking merge for {video_file.name}."
            )
            return out_path
        except Exception as e:
            logging.error(
                f"Definitive style-unification merge failed for {video_file.name}: {e}",
                exc_info=True,
            )
            return None

    def load_settings(self):
        try:
            if not self.settings_file.exists():
                return
            with open(self.settings_file, "r") as f:
                settings = json.load(f)
            if (
                settings.get("output_folder")
                and Path(settings["output_folder"]).exists()
            ):
                self.output_folder = Path(settings["output_folder"])
            if settings.get("last_vid_dir") and Path(settings["last_vid_dir"]).exists():
                self.last_vid_dir = Path(settings["last_vid_dir"])
            if (
                settings.get("last_top_sub_dir")
                and Path(settings["last_top_sub_dir"]).exists()
            ):
                self.last_top_sub_dir = Path(settings["last_top_sub_dir"])
            if (
                settings.get("last_bottom_sub_dir")
                and Path(settings["last_bottom_sub_dir"]).exists()
            ):
                self.last_bottom_sub_dir = Path(settings["last_bottom_sub_dir"])
            logging.info("Settings loaded.")
        except Exception as e:
            logging.error(f"Error loading settings: {e}")

    def save_settings(self):
        settings = {
            "output_folder": str(self.output_folder),
            "last_vid_dir": str(self.last_vid_dir),
            "last_top_sub_dir": str(self.last_top_sub_dir),
            "last_bottom_sub_dir": str(self.last_bottom_sub_dir),
        }
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=4)
            logging.info("Settings saved.")
        except Exception as e:
            logging.error(f"Could not save settings: {e}")

    def closeEvent(self, event):
        logging.info("--- Application Closing ---")
        self.save_settings()
        if self.batch_worker and self.batch_worker.isRunning():
            self.cancel_batch()
            self.batch_worker.wait()
        event.accept()


# --- Worker Thread Class ---
class BatchWorker(QThread):
    job_started = pyqtSignal(int, int, Path)
    job_progress = pyqtSignal(int)
    job_finished = pyqtSignal(int, str)
    batch_finished = pyqtSignal(str)
    parsed_stats = pyqtSignal(dict)
    raw_log = pyqtSignal(str)

    def __init__(self, app_instance, jobs):
        super().__init__()
        self.app = app_instance
        self.jobs = jobs
        self.is_cancelled = False
        self.process = None

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.kill()
            except Exception as e:
                logging.error(f"Error killing FFmpeg process: {e}")

    def get_video_duration(self, video_path):
        try:
            result = subprocess.run(
                [
                    self.app.ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                check=True,
                creationflags=CREATE_NO_WINDOW,
            )
            return float(result.stdout.strip())
        except Exception as e:
            logging.error(f"Could not get duration for {video_path.name}: {e}")
            return 0

    def run(self):
        self.app.start_button.setDisabled(True)
        self.app.cancel_button.setEnabled(True)
        total_jobs = len(self.jobs)

        for i, job in enumerate(self.jobs):
            if self.is_cancelled:
                break

            self.job_started.emit(i, total_jobs, job["video"])

            duration = (
                self.get_video_duration(job["video"])
                if "Burn" in self.app.mode_selector.currentText()
                else 0
            )
            processing_mode = self.app.mode_selector.currentText()
            ffmpeg_command, merged_subs_path = [], None

            try:
                if "Soft Burn" in processing_mode:
                    merged_subs_path = self.app.merge_subs_for_batch(
                        job["video"], job["top"], job["bottom"]
                    )
                    if not merged_subs_path:
                        logging.error(
                            f"Skipping {job['video'].name} due to subtitle merging error."
                        )
                        self.job_finished.emit(i, "❌ Merge Failed")
                        continue
                    output_file = (
                        self.app.output_folder / f"{job['video'].stem}_softburned.mkv"
                    )
                    ffmpeg_command = [
                        self.app.ffmpeg_path,
                        "-y",
                        "-i",
                        str(job["video"]),
                        "-i",
                        str(merged_subs_path),
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-map",
                        "1",
                        "-c",
                        "copy",
                        "-disposition:s:0",
                        "default",
                        str(output_file),
                    ]

                elif "Mux Separate" in processing_mode:
                    output_file = (
                        self.app.output_folder / f"{job['video'].stem}_muxed.mkv"
                    )
                    ffmpeg_command = [
                        self.app.ffmpeg_path,
                        "-y",
                        "-i",
                        str(job["video"]),
                        "-i",
                        str(job["top"]),
                        "-i",
                        str(job["bottom"]),
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-map",
                        "1",
                        "-map",
                        "2",
                        "-c",
                        "copy",
                        "-c:s",
                        "ass",
                        "-metadata:s:s:0",
                        "language=eng",
                        "-metadata:s:s:0",
                        "title=English",
                        "-metadata:s:s:1",
                        "language=chi",
                        "-metadata:s:s:1",
                        "title=Chinese",
                        "-disposition:s:s:0",
                        "default",
                        str(output_file),
                    ]

                elif "Burn" in processing_mode:
                    merged_subs_path = self.app.merge_subs_for_batch(
                        job["video"], job["top"], job["bottom"]
                    )
                    if not merged_subs_path:
                        logging.error(
                            f"Skipping {job['video'].name} due to subtitle merging error."
                        )
                        self.job_finished.emit(i, "❌ Merge Failed")
                        continue
                    output_file = (
                        self.app.output_folder / f"{job['video'].stem}_burned.mp4"
                    )

                    filter_path = merged_subs_path.as_posix().replace(":", r"\:")
                    vf_filter = f"ass='{filter_path}'"

                    ffmpeg_command = [
                        self.app.ffmpeg_path,
                        "-y",
                        "-i",
                        str(job["video"]),
                        "-vf",
                        vf_filter,
                        "-c:v",
                        self.app.video_codec,
                        "-preset",
                        self.app.preset,
                        "-crf",
                        "23",
                        "-c:a",
                        "copy",
                        str(output_file),
                    ]

                logging.info(f"Executing command: {' '.join(ffmpeg_command)}")
                self.process = subprocess.Popen(
                    ffmpeg_command,
                    creationflags=CREATE_NO_WINDOW,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding="utf-8",
                    errors="replace",
                )

                for line in self.process.stderr:
                    if self.is_cancelled:
                        break
                    self.raw_log.emit(line.strip())

                    if time_match := re.search(
                        r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})", line
                    ):
                        if duration > 0:
                            h, m, s, ms = map(int, time_match.groups())
                            elapsed = h * 3600 + m * 60 + s + ms / 100
                            self.job_progress.emit(int((elapsed / duration) * 100))

                    stats = {}
                    if fps_match := re.search(r"fps=\s*([\d.]+)", line):
                        stats["fps"] = fps_match.group(1)
                    if speed_match := re.search(r"speed=\s*([\d.]+)x", line):
                        stats["speed"] = speed_match.group(1) + "x"
                    if bitrate_match := re.search(r"bitrate=\s*([\d.]+kbits/s)", line):
                        stats["bitrate"] = bitrate_match.group(1)
                    if stats:
                        self.parsed_stats.emit(stats)

                self.process.wait()
                if self.is_cancelled:
                    self.job_finished.emit(i, "Cancelled")
                elif self.process.returncode == 0:
                    self.job_finished.emit(i, "Done")
                else:
                    self.job_finished.emit(i, "❌ Failed")

            except Exception as e:
                logging.error(f"Worker thread error on job {i}: {e}", exc_info=True)
                self.job_finished.emit(i, "❌ Error")
            finally:
                if merged_subs_path and merged_subs_path.exists():
                    try:
                        merged_subs_path.unlink()
                    except OSError as e:
                        logging.error(
                            f"Error removing temp file {merged_subs_path}: {e}"
                        )

        self.batch_finished.emit(
            "Batch processing finished."
            if not self.is_cancelled
            else "Batch cancelled."
        )


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    ex = SubtitleMergerApp()
    ex.show()
    if ctypes and sys.platform == "win32":
        try:
            hwnd = ex.winId()
            value = ctypes.c_int(1)
            # Use constant 20 for Windows 11, fallback to 19 for Windows 10
            if (
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
                )
                != 0
            ):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception as e:
            logging.warning(f"Could not set dark title bar: {e}")
    sys.exit(app.exec_())
