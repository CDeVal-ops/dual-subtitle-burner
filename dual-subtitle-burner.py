import sys
import os
import subprocess
import json
import re
import time
import logging
from pathlib import Path

try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    ctypes = None

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QGroupBox, QFormLayout, QProgressBar,
    QListWidget, QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView,
    QTextEdit, QAbstractItemView, QComboBox
)

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
DARK_MODE_STYLESHEET = """
    QWidget { background-color: #2b2b2b; color: #dcdcdc; font-family: Segoe UI; font-size: 9pt; }
    QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 5px; margin-top: 7px; }
    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 5px; }
    QPushButton { background-color: #555; border: 1px solid #666; padding: 5px; border-radius: 3px; min-height: 18px; }
    QPushButton:hover { background-color: #666; border-color: #777; }
    QPushButton:pressed { background-color: #4E4E4E; }
    QPushButton:disabled { background-color: #333; color: #777; }
    QListWidget, QTableWidget, QTextEdit, QComboBox { background-color: #222; border: 1px solid #444; }
    QHeaderView::section { background-color: #444; padding: 4px; border: 1px solid #555; }
    QProgressBar { border: 1px solid #444; border-radius: 3px; text-align: center; color: #dcdcdc; }
    QProgressBar::chunk { background-color: #0078d4; }
"""

class BatchWorker(QThread):
    job_started = pyqtSignal(int, str)
    file_progress = pyqtSignal(int)
    stats_update = pyqtSignal(dict)
    job_finished = pyqtSignal(int, str, bool)
    batch_finished = pyqtSignal(str)

    def __init__(self, jobs, app_instance):
        super().__init__(); self.jobs, self.app, self.is_cancelled = jobs, app_instance, False

    def run(self):
        for i, job in enumerate(self.jobs):
            if self.is_cancelled: break
            self.job_started.emit(i, job['video'].name)
            merged_sub_path = self.app.merge_subs_for_batch(job['video'], job['top_sub'], job['bottom_sub'])
            if not merged_sub_path:
                self.job_finished.emit(i, "❌ Merge Failed", False); continue
            success, message = self.burn_job(job, merged_sub_path)
            if merged_sub_path.exists():
                try: merged_sub_path.unlink(); logging.info(f"Cleaned up temp file: {merged_sub_path.name}")
                except OSError as e: logging.error(f"Could not delete temp file: {e}")
            self.job_finished.emit(i, message, success)
        self.batch_finished.emit("⏹ Batch cancelled." if self.is_cancelled else "🎉 Batch complete!")

    def burn_job(self, job, merged_sub_path):
        try:
            duration_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(job['video'])]
            result = subprocess.run(duration_cmd, capture_output=True, text=True, check=True, creationflags=CREATE_NO_WINDOW)
            duration = float(result.stdout.strip())
        except: duration = 0; logging.error("Could not get video duration.")
        
        _, encoder_flags = self.app.determine_encoder()
        if not encoder_flags: return False, "No encoder found."
        
        output_video_file = self.app.output_folder / job['output_name']
        subtitle_filter_path = str(merged_sub_path).replace('\\', '/').replace(':', '\\:')
        
        ffmpeg_command = ["ffmpeg", "-i", str(job['video']), "-sn", "-vf", f"ass='{subtitle_filter_path}'"]
        ffmpeg_command.extend(encoder_flags); ffmpeg_command.extend(["-c:a", "copy", "-y", str(output_video_file)])
        
        logging.info(f"Executing FFmpeg command: {' '.join(map(str, ffmpeg_command))}")
        self.app.ffmpeg_process = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, errors='replace', creationflags=CREATE_NO_WINDOW)
        
        for line in self.app.ffmpeg_process.stderr:
            if self.is_cancelled: self.app.ffmpeg_process.terminate(); break
            logging.debug(line.strip())
            
            if 'time=' in line and 'bitrate=' in line:
                stats = {key.strip(): value.strip() for key, value in (pair.split('=') for pair in re.split(r'\s+', line.strip()) if '=' in pair)}
                self.stats_update.emit(stats)
                if duration > 0:
                    match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})", line)
                    if match:
                        try:
                            h, m, s, ms = map(int, match.groups())
                            current_time = h * 3600 + m * 60 + s + ms / 100
                            progress = int((current_time / duration) * 100)
                            self.file_progress.emit(progress)
                        except ValueError: continue
        
        self.app.ffmpeg_process.wait()
        if self.app.ffmpeg_process.returncode == 0 and not self.is_cancelled: return True, "Done"
        elif self.is_cancelled: return False, "Cancelled"
        else: return False, f"FFmpeg Error (code {self.app.ffmpeg_process.returncode})"

    def stop(self): self.is_cancelled = True

class SubtitleMergerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dual Subtitle Batch Processor"); self.setGeometry(300, 100, 850, 800)
        self.video_files, self.top_sub_files, self.bottom_sub_files = [], [], []
        self.jobs_to_process, self.ffmpeg_process, self.batch_worker = [], None, None
        self.font, self.font_size = "Roboto", 18
        self.last_vid_dir, self.last_top_sub_dir, self.last_bottom_sub_dir = Path.home(), Path.home(), Path.home()
        self.output_folder = Path.home() / "Videos"
        try:
            self.settings_dir = Path.home() / "Documents" / "Dual Sub Burner Settings"; self.settings_dir.mkdir(exist_ok=True) 
            self.settings_file = self.settings_dir / "settings.json"; self.setup_logging()
        except Exception as e:
            self.settings_file = Path(__file__).resolve().parent / "settings.json"; print(f"Could not create settings/log dir: {e}")
        self.init_ui(); self.load_settings()

    def showEvent(self, event): super().showEvent(event); self._enable_dark_mode_title_bar()
    def _enable_dark_mode_title_bar(self):
        if sys.platform == "win32" and ctypes:
            try:
                hwnd = int(self.winId()); DWMWA_USE_IMMERSIVE_DARK_MODE = 20; value = wintypes.BOOL(True)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)) != 0:
                    DWMWA_USE_IMMERSIVE_DARK_MODE = 19; ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
            except Exception as e: logging.warning(f"Could not set dark title bar: {e}")

    def setup_logging(self): logging.basicConfig(filename=self.settings_dir/"batch_log.txt", level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filemode='a'); logging.info("--- Application Started ---")
    
    def determine_encoder(self):
        encoders = [
            ('NVIDIA NVENC', ['-c:v', 'h264_nvenc', '-preset', 'p5', '-cq', '23']),
            ('AMD AMF', ['-c:v', 'h264_amf', '-preset', 'quality', '-cq', '23']),
            ('Intel QSV', ['-c:v', 'h264_qsv', '-preset', 'medium', '-cq', '23'])
        ]
        logging.info("--- Starting Encoder Detection ---")
        for name, flags in encoders:
            encoder_name = flags[1]
            try:
                cmd = ['ffmpeg', '-f', 'lavfi', '-i', 'nullsrc=s=640x480', '-c:v', encoder_name, '-frames:v', '1', '-f', 'null', '-']
                logging.info(f"Testing for encoder: {name} ({encoder_name})")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=CREATE_NO_WINDOW)
                if "Cannot create a CUDA device" in result.stderr or "No NVENC capable devices found" in result.stderr:
                    logging.warning(f"Encoder {name} known but no compatible hardware found.")
                    continue
                logging.info(f"Successfully detected and selected encoder: {name}")
                return (name, flags)
            except (subprocess.CalledProcessError, FileNotFoundError):
                logging.warning(f"Encoder {name} not available or test failed.")
                continue
        
        logging.info("No hardware encoder found. Falling back to CPU (libx264).")
        return ('CPU (Software)', ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23'])

    def init_ui(self):
        main_layout = QVBoxLayout()
        selection_group = QGroupBox("1. Select File Groups"); selection_layout = QHBoxLayout(); vid_vbox = QVBoxLayout(); self.select_videos_button = QPushButton("Select Video Files"); self.select_videos_button.clicked.connect(self.select_videos); self.video_list_widget = QListWidget(); vid_vbox.addWidget(QLabel("<b>Videos</b>")); vid_vbox.addWidget(self.select_videos_button); vid_vbox.addWidget(self.video_list_widget); top_vbox = QVBoxLayout(); self.select_top_subs_button = QPushButton("Select Top Subtitle Files"); self.select_top_subs_button.clicked.connect(self.select_top_subs); self.top_sub_list_widget = QListWidget(); top_vbox.addWidget(QLabel("<b>Top Subtitles</b>")); top_vbox.addWidget(self.select_top_subs_button); top_vbox.addWidget(self.top_sub_list_widget); bottom_vbox = QVBoxLayout(); self.select_bottom_subs_button = QPushButton("Select Bottom Subtitle Files"); self.select_bottom_subs_button.clicked.connect(self.select_bottom_subs); self.bottom_sub_list_widget = QListWidget(); bottom_vbox.addWidget(QLabel("<b>Bottom Subtitles</b>")); bottom_vbox.addWidget(self.select_bottom_subs_button); bottom_vbox.addWidget(self.bottom_sub_list_widget); selection_layout.addLayout(vid_vbox); selection_layout.addLayout(top_vbox); selection_layout.addLayout(bottom_vbox); selection_group.setLayout(selection_layout)
        matching_group = QGroupBox("2. Confirm Matched Files"); matching_layout = QVBoxLayout(); self.match_button = QPushButton("Preview Matched Files"); self.match_button.clicked.connect(self.match_and_populate_table); self.job_table = QTableWidget(); self.job_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.job_table.setColumnCount(4); self.job_table.setHorizontalHeaderLabels(["Process", "Video File", "Top Subtitle", "Bottom Subtitle"]); header = self.job_table.horizontalHeader(); header.setSectionResizeMode(1, QHeaderView.Stretch); header.setSectionResizeMode(2, QHeaderView.Stretch); header.setSectionResizeMode(3, QHeaderView.Stretch); matching_layout.addWidget(self.match_button); matching_layout.addWidget(self.job_table)
        reorder_hbox = QHBoxLayout(); self.move_up_button = QPushButton("▲ Move Up"); self.move_up_button.clicked.connect(self.move_job_up); self.move_down_button = QPushButton("▼ Move Down"); self.move_down_button.clicked.connect(self.move_job_down); reorder_hbox.addStretch(); reorder_hbox.addWidget(self.move_up_button); reorder_hbox.addWidget(self.move_down_button); matching_layout.addLayout(reorder_hbox); matching_group.setLayout(matching_layout)
        bottom_pane_hbox = QHBoxLayout(); actions_group = QGroupBox("3. Actions & Progress"); actions_layout = QVBoxLayout(); stats_group = QGroupBox("4. Statistics & Utilities"); stats_layout = QVBoxLayout()
        output_form = QFormLayout(); folder_hbox = QHBoxLayout(); btn_out_folder = QPushButton("Choose Output Folder"); btn_out_folder.clicked.connect(self.select_output_folder); self.output_folder_label = QLabel(str(self.output_folder)); folder_hbox.addWidget(btn_out_folder); folder_hbox.addWidget(self.output_folder_label, 1); output_form.addRow(QLabel("Output Folder:"), folder_hbox); actions_layout.addLayout(output_form)
        progress_form = QFormLayout(); self.progress_bar = QProgressBar(); self.progress_bar.setFormat("%p%"); self.overall_progress_label = QLabel("Overall: 0/0"); progress_hbox = QHBoxLayout(); progress_hbox.addWidget(self.overall_progress_label); progress_hbox.addWidget(self.progress_bar, 1); output_form.addRow(QLabel("Current File:"), progress_hbox); actions_layout.addLayout(progress_form)
        action_buttons_hbox = QHBoxLayout(); self.start_button = QPushButton("🔥 Start Batch"); self.start_button.clicked.connect(self.start_batch); self.cancel_button = QPushButton("❌ Cancel Batch"); self.cancel_button.clicked.connect(self.cancel_batch); self.cancel_button.setEnabled(False); action_buttons_hbox.addWidget(self.start_button); action_buttons_hbox.addWidget(self.cancel_button); action_buttons_hbox.addStretch(); actions_layout.addLayout(action_buttons_hbox); actions_group.setLayout(actions_layout)
        stats_form = QFormLayout(); self.fps_label = QLabel("N/A"); self.bitrate_label = QLabel("N/A"); self.speed_label = QLabel("N/A"); self.frame_label = QLabel("N/A"); stats_form.addRow("FPS:", self.fps_label); stats_form.addRow("Bitrate:", self.bitrate_label); stats_form.addRow("Speed:", self.speed_label); stats_form.addRow("Frame:", self.frame_label)
        util_buttons_hbox = QHBoxLayout(); self.clear_batch_button = QPushButton("Clear Batch List"); self.clear_batch_button.clicked.connect(self.clear_batch); btn_open_log_folder = QPushButton("📜 Open Log Folder"); btn_open_log_folder.clicked.connect(self.open_log_folder); btn_open_output_folder = QPushButton("📂 Open Output Folder"); btn_open_output_folder.clicked.connect(self.open_output_folder); util_buttons_hbox.addStretch(); util_buttons_hbox.addWidget(self.clear_batch_button); util_buttons_hbox.addWidget(btn_open_log_folder); util_buttons_hbox.addWidget(btn_open_output_folder)
        stats_layout.addLayout(stats_form); stats_layout.addLayout(util_buttons_hbox); stats_group.setLayout(stats_layout)
        bottom_pane_hbox.addWidget(actions_group, 2); bottom_pane_hbox.addWidget(stats_group, 1)
        self.status = QLabel("Welcome! Select your files."); main_layout.addWidget(selection_group); main_layout.addWidget(matching_group); main_layout.addLayout(bottom_pane_hbox); main_layout.addWidget(self.status); self.setLayout(main_layout); self.update_button_states()

    def select_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Video Files", str(self.last_vid_dir), "Video Files (*.mkv *.mp4 *.avi *.mov)");
        if paths: self.last_vid_dir = Path(paths[0]).parent; self.video_files = sorted([Path(p) for p in paths]); self.video_list_widget.clear(); self.video_list_widget.addItems([p.name for p in self.video_files]); self.update_button_states(); logging.info(f"Selected {len(paths)} video files.")
    def select_top_subs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Top Subtitle Files", str(self.last_top_sub_dir), "Subtitle Files (*.ass *.srt)");
        if paths: self.last_top_sub_dir = Path(paths[0]).parent; self.top_sub_files = sorted([Path(p) for p in paths]); self.top_sub_list_widget.clear(); self.top_sub_list_widget.addItems([p.name for p in self.top_sub_files]); self.update_button_states(); logging.info(f"Selected {len(paths)} top subtitle files.")
    def select_bottom_subs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Bottom Subtitle Files", str(self.last_bottom_sub_dir), "Subtitle Files (*.ass *.srt)");
        if paths: self.last_bottom_sub_dir = Path(paths[0]).parent; self.bottom_sub_files = sorted([Path(p) for p in paths]); self.bottom_sub_list_widget.clear(); self.bottom_sub_list_widget.addItems([p.name for p in self.bottom_sub_files]); self.update_button_states(); logging.info(f"Selected {len(paths)} bottom subtitle files.")
    
    def match_and_populate_table(self):
        logging.info("Attempting to match file groups.")
        if not (len(self.video_files) == len(self.top_sub_files) == len(self.bottom_sub_files)):
            QMessageBox.warning(self, "Mismatch Error", "The number of files in each category must be the same to match them."); logging.warning("File match failed: list sizes are different."); return
        self.job_table.setRowCount(0)
        for i in range(len(self.video_files)): self.add_row_to_table(self.video_files[i], i)
        self.job_table.resizeColumnsToContents(); self.update_button_states(); logging.info(f"Successfully matched {len(self.video_files)} jobs.")
    def add_row_to_table(self, video_path, index):
        row = self.job_table.rowCount(); self.job_table.insertRow(row); checkbox_widget = QWidget(); chk_layout = QHBoxLayout(checkbox_widget); chk_box = QCheckBox(); chk_layout.addWidget(chk_box); chk_layout.setAlignment(Qt.AlignCenter); chk_box.setChecked(True); self.job_table.setCellWidget(row, 0, checkbox_widget)
        video_item = QTableWidgetItem(video_path.name); video_item.setData(Qt.UserRole, video_path)
        top_combo = QComboBox(); top_combo.addItems([p.name for p in self.top_sub_files]); top_combo.setCurrentIndex(index)
        bottom_combo = QComboBox(); bottom_combo.addItems([p.name for p in self.bottom_sub_files]); bottom_combo.setCurrentIndex(index)
        for item in [video_item]: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.job_table.setItem(row, 1, video_item); self.job_table.setCellWidget(row, 2, top_combo); self.job_table.setCellWidget(row, 3, bottom_combo)
    def move_job_up(self):
        row = self.job_table.currentRow();
        if row > 0: self.swap_rows(row, row - 1); logging.info(f"Moved job up from row {row} to {row-1}.")
    def move_job_down(self):
        row = self.job_table.currentRow()
        if 0 <= row < self.job_table.rowCount() - 1: self.swap_rows(row, row + 1); logging.info(f"Moved job down from row {row} to {row+1}.")
    def swap_rows(self, source_row, dest_row):
        for col in range(self.job_table.columnCount()):
            if col == 0:
                source_widget = self.job_table.cellWidget(source_row, col).layout().itemAt(0).widget(); dest_widget = self.job_table.cellWidget(dest_row, col).layout().itemAt(0).widget()
                source_checked = source_widget.isChecked(); dest_checked = dest_widget.isChecked(); source_widget.setChecked(dest_checked); dest_widget.setChecked(source_checked)
            elif col in [2, 3]:
                source_widget = self.job_table.cellWidget(source_row, col); dest_widget = self.job_table.cellWidget(dest_row, col)
                source_index = source_widget.currentIndex(); dest_index = dest_widget.currentIndex(); source_widget.setCurrentIndex(dest_index); dest_widget.setCurrentIndex(source_index)
            else:
                source_item = self.job_table.takeItem(source_row, col); dest_item = self.job_table.takeItem(dest_row, col); self.job_table.setItem(source_row, col, dest_item); self.job_table.setItem(dest_row, col, source_item)
        self.job_table.selectRow(dest_row)
    def start_batch(self):
        self.jobs_to_process = []
        for row in range(self.job_table.rowCount()):
            if not self.job_table.cellWidget(row, 0).layout().itemAt(0).widget().isChecked(): continue
            top_sub_path = self.top_sub_files[self.job_table.cellWidget(row, 2).currentIndex()]
            bottom_sub_path = self.bottom_sub_files[self.job_table.cellWidget(row, 3).currentIndex()]
            job = {'video': self.job_table.item(row, 1).data(Qt.UserRole), 'top_sub': top_sub_path, 'bottom_sub': bottom_sub_path, 'output_name': f"{self.job_table.item(row, 1).data(Qt.UserRole).stem}.mp4", 'table_item': self.job_table.item(row, 1)}
            self.jobs_to_process.append(job)
        if not self.jobs_to_process: QMessageBox.warning(self, "No Jobs", "No jobs were checked for processing."); return
        self.start_button.setEnabled(False); self.cancel_button.setEnabled(True); self.match_button.setEnabled(False); self.clear_batch_button.setEnabled(False)
        self.progress_bar.setValue(0); logging.info(f"--- Starting New Batch of {len(self.jobs_to_process)} jobs ---")
        for job in self.jobs_to_process: job['table_item'].setBackground(self.palette().color(self.backgroundRole()))
        self.batch_worker = BatchWorker(self.jobs_to_process, self); self.batch_worker.job_started.connect(self.handle_job_started); self.batch_worker.file_progress.connect(self.progress_bar.setValue); self.batch_worker.stats_update.connect(self.update_stats_display); self.batch_worker.job_finished.connect(self.handle_job_finished); self.batch_worker.batch_finished.connect(self.handle_batch_finished)
        self.batch_worker.start()
    def update_stats_display(self, stats): self.fps_label.setText(stats.get('fps', self.fps_label.text())); self.bitrate_label.setText(stats.get('bitrate', self.bitrate_label.text())); self.speed_label.setText(stats.get('speed', self.speed_label.text())); self.frame_label.setText(stats.get('frame', self.frame_label.text()))
    def handle_job_started(self, job_index, video_name):
        self.progress_bar.setValue(0); self.overall_progress_label.setText(f"Overall: {job_index + 1}/{len(self.jobs_to_process)}"); logging.info(f"--- Starting Job {job_index + 1}/{len(self.jobs_to_process)}: {video_name} ---")
        self.status.setText(f"Processing: {video_name}")
    def handle_job_finished(self, job_index, final_status, success):
        item = self.jobs_to_process[job_index]['table_item']; logging.info(f"Job '{item.text()}' finished with status: {final_status}"); item.setText(final_status)
    def handle_batch_finished(self, message):
        self.status.setText(message); self.progress_bar.setValue(100); self.start_button.setEnabled(True); self.cancel_button.setEnabled(False); self.match_button.setEnabled(True); self.clear_batch_button.setEnabled(True); logging.info(f"--- {message} ---")
    def cancel_batch(self):
        logging.warning("Cancel button pressed. Terminating batch.")
        if self.batch_worker and self.batch_worker.isRunning(): self.batch_worker.stop()
    def clear_batch(self):
        self.job_table.setRowCount(0); self.progress_bar.setValue(0); self.video_list_widget.clear(); self.top_sub_list_widget.clear(); self.bottom_sub_list_widget.clear(); self.video_files, self.top_sub_files, self.bottom_sub_files = [], [], []; self.status.setText("Batch cleared. Ready for next job."); logging.info("Batch list cleared by user.")
    def update_button_states(self): all_selected = all([self.video_files, self.top_sub_files, self.bottom_sub_files]); self.match_button.setEnabled(all_selected); self.start_button.setEnabled(self.job_table.rowCount() > 0)
    def select_output_folder(self, *args):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", str(self.output_folder))
        if folder: self.output_folder = Path(folder); self.output_folder_label.setText(str(self.output_folder)); logging.info(f"Output folder set to: {folder}")
    def open_output_folder(self, *args):
        if self.output_folder.exists():
            try:
                if sys.platform == "win32": os.startfile(self.output_folder)
                else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(self.output_folder)], check=True)
                logging.info(f"Opened output folder: {self.output_folder}")
            except Exception as e: QMessageBox.critical(self, "Error", f"Could not open folder: {e}"); logging.error(f"Failed to open output folder: {e}")
    def open_log_folder(self, *args):
        if hasattr(self, 'settings_dir') and self.settings_dir.exists():
            try:
                if sys.platform == "win32": os.startfile(self.settings_dir)
                else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(self.settings_dir)], check=True)
                logging.info(f"Opened log folder: {self.settings_dir}")
            except Exception as e: QMessageBox.critical(self, "Error", f"Could not open log folder: {e}"); logging.error(f"Failed to open log folder: {e}")
            
    def merge_subs_for_batch(self, video_file, first_sub, second_sub):
        try:
            logging.info(f"Merging subs for {video_file.name}"); sub1_text = first_sub.read_text(encoding="utf-8", errors='ignore').splitlines(); sub2_text = second_sub.read_text(encoding="utf-8", errors='ignore').splitlines()
            
            def parse(lines):
                header, styles, events = [], [], []; sec = None
                for line in lines:
                    if line.startswith("[Script Info]"): sec = "info"
                    elif line.startswith("[V4+ Styles]"): sec = "styles"
                    elif line.startswith("[Events]"): sec = "events"
                    elif line.startswith("["): sec = None
                    if sec == "info": header.append(line)
                    elif sec == "styles": styles.append(line)
                    elif sec == "events" and (line.startswith("Dialogue:") or line.startswith("Comment:")): events.append(line)
                return header, styles, events

            def rename_styles(styles, align, tag, font, size):
                mapping, out = {}, []
                for line in styles:
                    if line.startswith("Style:"):
                        parts = line.split(":", 1)[1].split(',');
                        if len(parts) < 23: parts.extend(["0"] * (23 - len(parts)))
                        old_name = parts[0].strip(); new_name = f"{old_name}_{tag}"; mapping[old_name] = new_name
                        parts[0] = new_name; 
                        parts[1] = font; 
                        parts[2] = str(size); 
                        parts[3] = "&H00FFFFFF&";
                        parts[5] = "&H00000000&";
                        parts[6] = "&H00000000&";
                        parts[8] = "0";
                        parts[16] = "2";
                        parts[17] = "1";
                        parts[18] = align
                        out.append("Style:" + ",".join(parts))
                    else: out.append(line)
                return out, mapping
            
            def clean_and_map_dialogue(lines, mapping):
                mapped_lines = []
                fs_pattern = re.compile(r'{\\fs\d+\.?\d*}|\\fs\d+\.?\d*')
                for l in lines:
                    if l.startswith("Dialogue:"):
                        parts = l.split(',', 9)
                        if len(parts) == 10:
                            style_name = parts[3].strip()
                            text_part = parts[9]
                            if style_name in mapping:
                                parts[3] = mapping[style_name]
                            parts[9] = fs_pattern.sub('', text_part)
                            mapped_lines.append(",".join(parts))
                        else: mapped_lines.append(l)
                    else: mapped_lines.append(l)
                return mapped_lines

            head, styles1, events1 = parse(sub1_text); _, styles2, events2 = parse(sub2_text)
            s1, map1 = rename_styles(styles1, "8", "TOP", self.font, self.font_size); 
            s2, map2 = rename_styles(styles2, "2", "BOT", self.font, self.font_size); 
            e1 = clean_and_map_dialogue(events1, map1); 
            e2 = clean_and_map_dialogue(events2, map2)
            
            merged_header = [line for line in head if not line.startswith("Style:")]
            playresx_found = any("PlayResX" in line for line in merged_header)
            playresy_found = any("PlayResY" in line for line in merged_header)

            final_header = []
            for line in merged_header:
                if "PlayResX" in line and not playresx_found: continue
                if "PlayResY" in line and not playresy_found: continue
                final_header.append(line)
            
            if not playresx_found: final_header.append("PlayResX: 1920")
            if not playresy_found: final_header.append("PlayResY: 1080")

            merged_content = final_header[:]; 
            merged_content.extend(["\n[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"]); 
            merged_content.extend(s1); merged_content.extend(s2); 
            merged_content.extend(["\n[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]); 
            merged_content.extend(e1); merged_content.extend(e2)
            
            out_path = self.output_folder / f"{video_file.stem}_temp_merged.ass"; out_path.write_text("\n".join(merged_content), encoding="utf-8")
            return out_path
        except Exception as e: logging.error(f"Failed to merge subs for {video_file.name}: {e}"); return None

    def load_settings(self):
        if not self.settings_file.exists(): logging.warning("Settings file not found. Using defaults."); return
        try:
            with open(self.settings_file, 'r') as f: settings = json.load(f)
            if settings.get('output_folder') and Path(settings['output_folder']).exists(): self.output_folder = Path(settings['output_folder']); self.output_folder_label.setText(str(self.output_folder))
            if settings.get('last_vid_dir') and Path(settings['last_vid_dir']).exists(): self.last_vid_dir = Path(settings['last_vid_dir'])
            if settings.get('last_top_sub_dir') and Path(settings['last_top_sub_dir']).exists(): self.last_top_sub_dir = Path(settings['last_top_sub_dir'])
            if settings.get('last_bottom_sub_dir') and Path(settings['last_bottom_sub_dir']).exists(): self.last_bottom_sub_dir = Path(settings['last_bottom_sub_dir'])
            logging.info("Settings loaded successfully.")
        except Exception as e: logging.error(f"Error loading settings: {e}")

    def save_settings(self):
        settings = {'output_folder': str(self.output_folder), 'last_vid_dir': str(self.last_vid_dir), 'last_top_sub_dir': str(self.last_top_sub_dir), 'last_bottom_sub_dir': str(self.last_bottom_sub_dir)}
        try:
            with open(self.settings_file, 'w') as f: json.dump(settings, f, indent=4)
            logging.info("Settings saved successfully.")
        except Exception as e: logging.error(f"Could not save settings: {e}")

    def closeEvent(self, event):
        logging.info("--- Application Closing ---"); self.save_settings()
        if self.batch_worker and self.batch_worker.isRunning():
            self.cancel_batch(); self.batch_worker.wait()
        event.accept()

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_MODE_STYLESHEET)
    window = SubtitleMergerApp()
    window.show()
    sys.exit(app.exec_())