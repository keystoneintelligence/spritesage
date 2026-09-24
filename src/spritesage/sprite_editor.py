"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import shutil
from copy import deepcopy
from typing import Optional
from PIL import Image
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import (
    QMessageBox,
    QStyle,
    QFileDialog,
    QListWidgetItem,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QSlider,
    QSpinBox,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPainter, QPixmap

from .export_ui import GodotExportUiMixin
from .animation_widgets import PixelCanvas, FrameTimeline, thumbnail
from .image_loader import ImageLoaderWidget, ActionIconButton
from .image_polish import save_polished_copy
from .image_polish_dialog import ImagePolishDialog
from .config import build_application_stylesheet
from .exporter import GodotSpriteExporter
from .inference import (
    AIModelManager,
    GenerateBaseSpriteImageInput,
    GenerateSpriteAnimationSuggestion,
    GenerateNextSpriteImageInput,
    GenerateSpriteBetweenImagesInput,
)
from .sprite_file import SpriteFile, Animation
from .sage_editor import SageFile
from .undo_redo import UndoRedoManager
from .animation_service import (
    add_animation,
    duplicate_frame,
    insert_frames,
    make_ping_pong_loop,
    move_frame,
    plan_ai_frame_after,
    plan_ai_frame_before,
    plan_frame_copy,
    plan_frame_duplicate,
    remove_animation,
    remove_frame_indices,
    reverse_animation_frames,
    reorder_frame,
)
from .utils import (
    call_ai_with_busy,
    call_with_progress,
    ensure_llm_configured,
)


class AnimationPreviewWidget(QWidget):
    """Displays an animated sequence of frames."""

    frame_changed = QtCore.Signal(int)
    playback_changed = QtCore.Signal(bool)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
        self.pixmaps = []
        self.current_frame_index = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._next_frame)
        self._base_dir = None
        self.frame_delay_ms = 500
        self.animation = Animation("", [])
        self._playback_finished = False
        self._timer_rounding_ms = 0.0
        self.onion_skin_enabled = False
        self.onion_skin_opacity = 0.35

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = PixelCanvas(palette, "Select or create an animation")
        self.image_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)
        self.frame_paths = []

    def set_playing(self, playing: bool):
        if playing and self.pixmaps:
            if not self.timer.isActive():
                self._timer_rounding_ms = 0.0
            if self._playback_finished:
                self.show_frame(0)
            self.timer.start(self._current_frame_delay())
        else:
            self.timer.stop()
        self.playback_changed.emit(self.timer.isActive())

    def toggle_playback(self):
        self.set_playing(not self.timer.isActive())

    def step_frame(self, direction):
        self.set_playing(False)
        if self.pixmaps:
            self.show_frame((self.current_frame_index + direction) % len(self.pixmaps))

    def hideEvent(self, event):
        self.set_playing(False)
        super().hideEvent(event)

    def set_frame_delay(self, ms: int):
        if ms <= 0:
            ms = 100
        self.frame_delay_ms = ms
        self.animation.fps = 1000 / ms
        self._timer_rounding_ms = 0.0
        if self.timer.isActive():
            self.timer.start(self._current_frame_delay())

    def set_timing(self, animation: Animation):
        self.animation = deepcopy(animation)
        self._timer_rounding_ms = 0.0
        self.frame_delay_ms = max(1, round(1000 / animation.fps))
        if self.timer.isActive():
            self.timer.start(self._current_frame_delay())

    def _current_frame_delay(self) -> int:
        if self.current_frame_index < len(self.animation.frames):
            exact = 1000 * self.animation.frame_seconds(self.current_frame_index)
            interval = max(1, min(2147483647, round(exact + self._timer_rounding_ms)))
            # Carry fractional milliseconds so 30 FPS does not become 30.3 FPS.
            self._timer_rounding_ms = (
                exact + self._timer_rounding_ms - interval if 1 <= exact <= 2147483647 else 0.0
            )
            return interval
        return self.frame_delay_ms

    def set_onion_skin_enabled(self, enabled: bool):
        self.onion_skin_enabled = enabled
        self.show_current_frame()

    def set_onion_skin_opacity(self, opacity_percent: int):
        opacity = max(0, min(opacity_percent, 100)) / 100
        self.onion_skin_opacity = opacity
        self.show_current_frame()

    def load_animation(
        self, frame_paths: list[str], base_dir: str, *, animation: Animation | None = None
    ):
        """
        Load a sequence of image files (absolute or relative paths) into the preview.
        """
        self.set_playing(False)
        self._playback_finished = False
        self.set_timing(animation or Animation("", list(frame_paths), 1000 / self.frame_delay_ms))
        self.pixmaps.clear()
        self.frame_paths = list(frame_paths)
        self.current_frame_index = 0
        self._base_dir = base_dir
        self.image_label.canvas_size = QSize()
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Loading...")
        self.frame_changed.emit(-1)

        if not base_dir or not os.path.isdir(base_dir):
            print(f"AnimationPreviewWidget Error: Invalid base directory '{base_dir}'")
            self.image_label.setText("Error:\nInvalid base path")
            return

        if not frame_paths:
            self.image_label.setText("Animation has\nno frames")
            return

        for frame_path in frame_paths:
            # Use absolute if provided, else join with base_dir
            if os.path.isabs(frame_path):
                full_path = frame_path
            else:
                full_path = os.path.normpath(os.path.join(self._base_dir, frame_path))

            pixmap = QPixmap(full_path)
            if pixmap.isNull():
                print(f"AnimationPreviewWidget Warning: Frame image not found: {full_path}")
            # Keep missing entries so timeline and playback indices never drift.
            self.pixmaps.append(pixmap)

        self.image_label.canvas_size = self._preview_canvas_size()
        self.show_frame(0)
        self.set_playing(len(self.pixmaps) > 1)

    def _next_frame(self):
        if not self.pixmaps:
            self.set_playing(False)
            return
        if self.current_frame_index == len(self.pixmaps) - 1 and not self.animation.loop:
            self.set_playing(False)
            self._playback_finished = True
            return
        self.current_frame_index = (self.current_frame_index + 1) % len(self.pixmaps)
        self.show_current_frame()
        if self.timer.isActive():
            self.timer.start(self._current_frame_delay())

    def show_frame(self, frame_index: int):
        if not self.pixmaps:
            return
        self.current_frame_index = max(0, min(frame_index, len(self.pixmaps) - 1))
        self._playback_finished = False
        self.show_current_frame()

    def show_current_frame(self):
        if not self.pixmaps:
            return
        self.image_label.setText("")
        self.image_label.setPixmap(self._preview_pixmap_for_index(self.current_frame_index))
        if self.pixmaps[self.current_frame_index].isNull():
            self.image_label.setText("Could not load this frame\nCheck the source image path")
        if self.current_frame_index < len(self.frame_paths):
            pixmap = self.pixmaps[self.current_frame_index]
            self.image_label.setToolTip(
                f"{self.frame_paths[self.current_frame_index]}\n"
                f"{pixmap.width()} × {pixmap.height()} px"
            )
        self.frame_changed.emit(self.current_frame_index)

    def _preview_pixmap_for_index(self, frame_index: int) -> QPixmap:
        current = self.pixmaps[frame_index]
        if current.isNull():
            return current
        if not self.onion_skin_enabled or len(self.pixmaps) < 2:
            return current

        canvas_size = self._preview_canvas_size()
        composite = QPixmap(canvas_size)
        composite.fill(Qt.GlobalColor.transparent)
        painter = QPainter(composite)
        try:
            painter.setOpacity(self.onion_skin_opacity)
            if frame_index > 0:
                self._draw_centered_pixmap(painter, self.pixmaps[frame_index - 1], canvas_size)
            if frame_index < len(self.pixmaps) - 1:
                self._draw_centered_pixmap(painter, self.pixmaps[frame_index + 1], canvas_size)
            painter.setOpacity(1.0)
            self._draw_centered_pixmap(painter, current, canvas_size)
        finally:
            painter.end()
        return composite

    def _preview_canvas_size(self) -> QSize:
        return QSize(
            max(1, max((pixmap.width() for pixmap in self.pixmaps), default=1)),
            max(1, max((pixmap.height() for pixmap in self.pixmaps), default=1)),
        )

    @staticmethod
    def _draw_centered_pixmap(painter: QPainter, pixmap: QPixmap, canvas_size: QSize) -> None:
        x = max(0, (canvas_size.width() - pixmap.width()) // 2)
        y = max(0, (canvas_size.height() - pixmap.height()) // 2)
        painter.drawPixmap(x, y, pixmap)

    def clear_preview(self):
        self.set_playing(False)
        self.pixmaps.clear()
        self.frame_paths.clear()
        self.animation = Animation("", [])
        self._playback_finished = False
        self.current_frame_index = 0
        self.image_label.canvas_size = QSize()
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Select or create an animation")
        self.image_label.setToolTip("")
        self.frame_changed.emit(-1)


# --- Modified SpriteEditorView ---
class SpriteEditorView(GodotExportUiMixin, QtWidgets.QWidget):
    return_to_sage = QtCore.Signal(str)
    undo_redo_state_changed = QtCore.Signal(object)
    project_file_changed = QtCore.Signal(object, object, str)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.app_palette = palette
        self.current_file_path = None
        self.sprite_data: Optional[SpriteFile] = None
        self._base_dir = None
        self._undo_redo_manager = UndoRedoManager[SpriteFile]()
        self.sage_file: Optional[SageFile] = None

        # --- UI Setup ---
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(8)

        action_bar = QWidget()
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        back_button = QPushButton("Project")
        back_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        back_button.setToolTip("Return To Project")
        back_button.clicked.connect(self._return_to_sage_project)
        action_layout.addWidget(back_button, 0)

        self.export_sprite_button = QPushButton("Export Sprite")
        self.export_sprite_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirLinkIcon)
        )
        self.export_sprite_button.setToolTip("Export this sprite for Godot")
        self.export_sprite_button.setEnabled(False)
        self.export_sprite_button.clicked.connect(self.export_current_sprite_to_godot)
        action_layout.addWidget(self.export_sprite_button, 0)

        self.disassociate_sprite_button = QPushButton("Remove from Project")
        self.disassociate_sprite_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.disassociate_sprite_button.setToolTip(
            "Remove this sprite from the project without deleting any files"
        )
        self.disassociate_sprite_button.setEnabled(False)
        self.disassociate_sprite_button.clicked.connect(self._disassociate_current_sprite)
        action_layout.addWidget(self.disassociate_sprite_button, 0)
        action_layout.addStretch(1)
        self.main_layout.addWidget(action_bar)

        self.sprite_tabs = QtWidgets.QTabWidget()
        self.info_tab = QWidget()
        self.animations_tab = QWidget()
        self.edit_tab = QWidget()
        self.sprite_tabs.addTab(self.info_tab, "Info")
        self.sprite_tabs.addTab(self.animations_tab, "Animations")
        self.sprite_tabs.addTab(self.edit_tab, "Edit")
        self.main_layout.addWidget(self.sprite_tabs, 1)

        # --- Form Layout for Basic Properties ---
        info_layout = QVBoxLayout(self.info_tab)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(8)
        self.form_layout = QtWidgets.QFormLayout()
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setSpacing(5)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name field on second row
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Sprite Name (e.g., Orc)")
        self.form_layout.addRow("Name:", self.name_edit)

        self.desc_edit = QtWidgets.QPlainTextEdit()
        self.desc_edit.setPlaceholderText("Optional description of the sprite.")
        self.desc_edit.setFixedHeight(60)
        self.form_layout.addRow("Description:", self.desc_edit)
        size_layout = QtWidgets.QHBoxLayout()
        self.width_spin = QtWidgets.QSpinBox()
        self.width_spin.setRange(1, 8192)
        self.width_spin.setSuffix(" px")
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(1, 8192)
        self.height_spin.setSuffix(" px")
        size_layout.addWidget(QtWidgets.QLabel("Width:"))
        size_layout.addWidget(self.width_spin)
        size_layout.addSpacing(10)
        size_layout.addWidget(QtWidgets.QLabel("Height:"))
        size_layout.addWidget(self.height_spin)
        size_layout.addStretch()
        self.form_layout.addRow(size_layout)
        self.pixel_art_check = QtWidgets.QCheckBox(
            "Pixel art · nearest-neighbor preview and export"
        )
        self.pixel_art_check.setChecked(True)
        self.pixel_art_check.setToolTip(
            "Turn off for smooth scaling of painted or rendered artwork"
        )
        self.form_layout.addRow("Rendering:", self.pixel_art_check)
        self.base_image_loader = ImageLoaderWidget(base_dir=None, palette=self.app_palette, index=0)
        self.base_image_loader.pixel_art = True
        self.base_image_loader.checkerboard = True
        base_image_row = QWidget()
        base_image_layout = QHBoxLayout(base_image_row)
        base_image_layout.setContentsMargins(0, 0, 0, 0)
        base_image_layout.setSpacing(6)
        base_image_layout.addWidget(self.base_image_loader, 0)
        base_image_layout.addStretch(1)
        self.form_layout.addRow("Base Image:", base_image_row)
        self.base_image_loader.action_clicked.connect(self._on_base_image_action_clicked)
        self.include_base_image_check = QtWidgets.QCheckBox(
            "Start each animation with the base image"
        )
        self.include_base_image_check.setChecked(True)
        info_layout.addLayout(self.form_layout)
        info_layout.addStretch(1)

        # Preview and timeline have independent, remembered splitters.
        animations_tab_layout = QVBoxLayout(self.animations_tab)
        animations_tab_layout.setContentsMargins(8, 8, 8, 8)
        animations_tab_layout.setSpacing(6)
        self.animation_splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        self.animation_splitter.setChildrenCollapsible(False)
        self.preview_splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.preview_splitter.setChildrenCollapsible(False)
        animations_tab_layout.addWidget(self.animation_splitter)
        self.animation_splitter.addWidget(self.preview_splitter)

        animation_panel = QWidget()
        animation_panel.setMinimumWidth(136)
        anim_list_layout = QVBoxLayout(animation_panel)
        anim_list_layout.setContentsMargins(0, 0, 6, 0)
        anim_list_layout.addWidget(QLabel("ANIMATIONS"))
        self.anim_list_widget = QtWidgets.QListWidget()
        self.anim_list_widget.setMinimumWidth(110)
        self.anim_list_widget.setAccessibleName("Animations")
        self.anim_list_widget.setToolTip("Select an animation to preview and edit")
        anim_list_layout.addWidget(self.anim_list_widget)
        anim_button_layout = QHBoxLayout()
        self.add_anim_button = QPushButton("Add")
        self.remove_anim_button = QPushButton("Remove")
        self.add_anim_button.setToolTip("Create an animation")
        self.remove_anim_button.setToolTip("Remove the selected animation")
        anim_button_layout.addWidget(self.add_anim_button)
        anim_button_layout.addWidget(self.remove_anim_button)
        anim_list_layout.addLayout(anim_button_layout)
        self.template_anim_button = QPushButton("From Template…")
        self.template_anim_button.setToolTip("Transfer 3D motions to this character using local AI")
        self.template_anim_button.clicked.connect(self._animate_from_template)
        anim_list_layout.addWidget(self.template_anim_button)
        self.preview_splitter.addWidget(animation_panel)

        preview_panel = QWidget()
        preview_panel.setMinimumWidth(320)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        preview_toolbar = QHBoxLayout()
        preview_toolbar.addWidget(QLabel("PREVIEW"))
        preview_toolbar.addStretch()
        preview_toolbar.addWidget(QLabel("Zoom"))
        self.zoom_combo = QtWidgets.QComboBox()
        self.zoom_combo.setAccessibleName("Preview zoom")
        self.zoom_combo.addItem("Fit", 0)
        for zoom in (1, 2, 3, 4, 6, 8, 12, 16):
            self.zoom_combo.addItem(f"{zoom}×", zoom)
        self.zoom_combo.setToolTip(
            "Fit uses integer enlargement for pixel art. Fixed zoom can be scrolled."
        )
        preview_toolbar.addWidget(self.zoom_combo)
        self.preview_options_button = QPushButton("View")
        self.preview_options_menu = QtWidgets.QMenu(self.preview_options_button)
        self.checkerboard_action = self.preview_options_menu.addAction("Transparency checkerboard")
        self.checkerboard_action.setCheckable(True)
        self.checkerboard_action.setChecked(True)
        self.preview_options_button.setMenu(self.preview_options_menu)
        self.pixel_art_action = self.preview_options_menu.addAction(
            "Pixel art (preview and export)"
        )
        self.pixel_art_action.setCheckable(True)
        self.pixel_art_action.setChecked(True)
        self.pixel_art_action.toggled.connect(self.pixel_art_check.setChecked)
        preview_toolbar.addWidget(self.preview_options_button)
        preview_layout.addLayout(preview_toolbar)
        self.animation_preview = AnimationPreviewWidget(self.app_palette)
        preview_layout.addWidget(self.animation_preview, 1)

        playback = QHBoxLayout()
        self.previous_frame_button = QPushButton()
        self.play_pause_button = QPushButton("Play")
        self.next_frame_button = QPushButton()
        style = self.style()
        for button, icon, label in (
            (
                self.previous_frame_button,
                QStyle.StandardPixmap.SP_MediaSkipBackward,
                "Previous frame (Left)",
            ),
            (self.play_pause_button, QStyle.StandardPixmap.SP_MediaPlay, "Play or pause (Space)"),
            (
                self.next_frame_button,
                QStyle.StandardPixmap.SP_MediaSkipForward,
                "Next frame (Right)",
            ),
        ):
            button.setIcon(style.standardIcon(icon))
            button.setToolTip(label)
            button.setAccessibleName(label)
            playback.addWidget(button)
        self.frame_position_label = QLabel("No frames")
        self.frame_position_label.setMinimumWidth(86)
        playback.addWidget(self.frame_position_label)
        playback.addStretch()
        self.preview_fps_spin = QtWidgets.QDoubleSpinBox()
        self.preview_fps_spin.setRange(0.01, 1000)
        self.preview_fps_spin.setDecimals(2)
        self.preview_fps_spin.setKeyboardTracking(False)
        self.preview_fps_spin.setValue(2)
        self.preview_fps_spin.setSuffix(" fps")
        self.preview_fps_spin.setAccessibleName("Animation FPS")
        self.preview_fps_spin.setToolTip(
            "Saved animation speed for preview and export. Changing FPS scales every frame's duration."
        )
        playback.addWidget(self.preview_fps_spin)
        preview_layout.addLayout(playback)

        timing_controls = QHBoxLayout()
        self.animation_loop_check = QtWidgets.QCheckBox("Loop")
        self.animation_loop_check.setChecked(True)
        self.animation_loop_check.setToolTip(
            "Repeat this animation in preview and export. Turn off to play once."
        )
        timing_controls.addWidget(self.animation_loop_check)
        timing_controls.addStretch()
        self.frame_duration_label = QLabel("Frame duration")
        timing_controls.addWidget(self.frame_duration_label)
        self.frame_duration_spin = QtWidgets.QDoubleSpinBox()
        self.frame_duration_spin.setDecimals(2)
        self.frame_duration_spin.setRange(0.01, 86400000)
        self.frame_duration_spin.setSuffix(" ms")
        self.frame_duration_spin.setKeyboardTracking(False)
        self.frame_duration_spin.setAccessibleName("Selected frame duration in milliseconds")
        self.frame_duration_spin.setToolTip(
            "How long the selected frame is shown at this animation's FPS. Saved with the frame."
        )
        timing_controls.addWidget(self.frame_duration_spin)
        self.reset_frame_duration_button = QPushButton("Reset")
        self.reset_frame_duration_button.setToolTip("Give this frame the default duration: 1 / FPS")
        timing_controls.addWidget(self.reset_frame_duration_button)
        preview_layout.addLayout(timing_controls)

        preview_controls = QHBoxLayout()
        self.onion_skin_check = QtWidgets.QCheckBox("Onion skin")
        self.onion_skin_check.setToolTip("Overlay the previous and next frames")
        self.onion_skin_opacity_label = QLabel("35%")
        self.onion_skin_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.onion_skin_opacity_slider.setRange(5, 80)
        self.onion_skin_opacity_slider.setValue(35)
        self.onion_skin_opacity_slider.setMaximumWidth(100)
        self.onion_skin_opacity_slider.setAccessibleName("Onion skin opacity")
        self.onion_skin_opacity_slider.setEnabled(False)
        self.onion_skin_opacity_slider.setVisible(False)
        self.onion_skin_opacity_label.setVisible(False)
        preview_controls.addWidget(self.onion_skin_check)
        preview_controls.addWidget(self.onion_skin_opacity_slider)
        preview_controls.addWidget(self.onion_skin_opacity_label)
        preview_controls.addStretch()
        preview_layout.addLayout(preview_controls)
        self.preview_splitter.addWidget(preview_panel)
        self.preview_splitter.setSizes([150, 500])
        self.preview_splitter.setStretchFactor(0, 0)
        self.preview_splitter.setStretchFactor(1, 1)

        timeline_panel = QWidget()
        frame_list_layout = QVBoxLayout(timeline_panel)
        frame_list_layout.setContentsMargins(0, 2, 0, 0)
        frame_list_layout.setSpacing(6)
        timeline_heading = QHBoxLayout()
        timeline_heading.addWidget(QLabel("FRAMES"))
        self.timeline_hint = QLabel("Drag to reorder")
        timeline_heading.addWidget(self.timeline_hint)
        timeline_heading.addStretch()
        self.include_base_image_check.setText("Include base image")
        self.include_base_image_check.setToolTip(
            "Play and export the base image before the timeline frames"
        )
        timeline_heading.addWidget(self.include_base_image_check)
        self.base_frame_button = QPushButton("Base")
        self.base_frame_button.setToolTip("Preview the fixed base frame; edit its image in Info")
        timeline_heading.addWidget(self.base_frame_button)
        frame_list_layout.addLayout(timeline_heading)
        self.frame_list_widget = FrameTimeline()
        frame_list_layout.addWidget(self.frame_list_widget, 1)

        # Less frequent commands live in menus so every label fits at laptop sizes.
        frame_actions = QHBoxLayout()
        self.add_frames_button = QPushButton("Add frames")
        add_menu = QtWidgets.QMenu(self.add_frames_button)
        self.add_frame_before_button = add_menu.addAction("Import before selection…")
        self.add_frame_after_button = add_menu.addAction("Import after selection…")
        add_menu.addSeparator()
        self.add_frame_before_icon = add_menu.addAction("Generate before selection with AI…")
        self.add_frame_after_icon = add_menu.addAction("Generate after selection with AI…")
        self.add_frame_before_icon.triggered.connect(self._add_ai_generated_frame_before)
        self.add_frame_after_icon.triggered.connect(self._add_ai_generated_frame_after)
        self.add_frames_button.setMenu(add_menu)
        self.duplicate_frame_button = QPushButton("Duplicate")
        self.remove_frame_button = QPushButton("Remove")
        self.move_frame_up_button = QPushButton()
        self.move_frame_down_button = QPushButton()
        for button, icon, label in (
            (self.move_frame_up_button, QStyle.StandardPixmap.SP_ArrowLeft, "Move frame earlier"),
            (self.move_frame_down_button, QStyle.StandardPixmap.SP_ArrowRight, "Move frame later"),
        ):
            button.setIcon(style.standardIcon(icon))
            button.setToolTip(label)
            button.setAccessibleName(label)
        self.sequence_button = QPushButton("Sequence")
        sequence_menu = QtWidgets.QMenu(self.sequence_button)
        self.reverse_frames_button = sequence_menu.addAction("Reverse frames")
        self.ping_pong_button = sequence_menu.addAction("Make ping-pong loop")
        self.sequence_button.setMenu(sequence_menu)
        for button in (
            self.add_frames_button,
            self.duplicate_frame_button,
            self.remove_frame_button,
            self.move_frame_up_button,
            self.move_frame_down_button,
        ):
            frame_actions.addWidget(button)
        frame_actions.addStretch()
        frame_actions.addWidget(self.sequence_button)
        frame_list_layout.addLayout(frame_actions)
        self.animation_splitter.addWidget(timeline_panel)
        self.animation_splitter.setSizes([420, 180])
        self.animation_splitter.setStretchFactor(0, 1)
        self.animation_splitter.setStretchFactor(1, 0)

        self.previous_frame_button.clicked.connect(lambda: self.animation_preview.step_frame(-1))
        self.next_frame_button.clicked.connect(lambda: self.animation_preview.step_frame(1))
        self.play_pause_button.clicked.connect(self.animation_preview.toggle_playback)
        self.preview_fps_spin.valueChanged.connect(self._on_animation_fps_changed)
        self.animation_loop_check.toggled.connect(self._on_animation_loop_changed)
        self.frame_duration_spin.valueChanged.connect(self._on_frame_duration_changed)
        self.reset_frame_duration_button.clicked.connect(self._reset_frame_duration)
        self.zoom_combo.currentIndexChanged.connect(
            lambda: self.animation_preview.image_label.set_zoom(self.zoom_combo.currentData())
        )
        self.checkerboard_action.toggled.connect(self._set_checkerboard)
        self.pixel_art_check.toggled.connect(self._set_pixel_art)
        self.base_frame_button.clicked.connect(self._select_base_frame)
        self.animation_preview.frame_changed.connect(self._sync_playhead)
        self.animation_preview.playback_changed.connect(self._sync_playback)
        self.frame_list_widget.frames_reordered.connect(self._on_frames_reordered)
        self.frame_list_widget.drag_started.connect(
            lambda: self.animation_preview.set_playing(False)
        )
        self.frame_list_widget.step_requested.connect(self.animation_preview.step_frame)
        self.frame_list_widget.play_requested.connect(self.animation_preview.toggle_playback)
        self.onion_skin_opacity_slider.valueChanged.connect(
            lambda value: self.onion_skin_opacity_label.setText(f"{value}%")
        )
        self._play_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Space"), self.animation_preview)
        self._play_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._play_shortcut.activated.connect(self.animation_preview.toggle_playback)

        # --- Edit Section ---
        edit_layout = QHBoxLayout(self.edit_tab)
        edit_layout.setContentsMargins(8, 8, 8, 8)
        edit_layout.setSpacing(8)
        edit_asset_layout = QVBoxLayout()
        edit_asset_layout.setSpacing(4)
        edit_asset_layout.addWidget(QLabel("Assets"))
        self.edit_asset_list_widget = QtWidgets.QListWidget()
        self.edit_asset_list_widget.setIconSize(QSize(40, 32))
        self.edit_asset_list_widget.setMinimumWidth(140)
        self.edit_asset_list_widget.setToolTip("Base image and animation frames available to edit")
        edit_asset_layout.addWidget(self.edit_asset_list_widget, 1)
        self.polish_selected_asset_button = QPushButton("Polish Selected...")
        self.polish_selected_asset_button.setToolTip("Clean up the selected image locally")
        self.polish_selected_asset_button.setEnabled(False)
        edit_asset_layout.addWidget(self.polish_selected_asset_button)
        edit_layout.addLayout(edit_asset_layout, 1)

        edit_preview_layout = QVBoxLayout()
        edit_preview_layout.setSpacing(4)
        edit_preview_layout.addWidget(QLabel("Preview"))
        self.edit_preview_label = PixelCanvas(self.app_palette, "Select an asset to edit")
        self.edit_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_preview_label.setMinimumSize(100, 100)
        self.edit_preview_label.setAutoFillBackground(True)
        edit_preview_layout.addWidget(self.edit_preview_label, 1)
        edit_layout.addLayout(edit_preview_layout, 2)

        # --- Connect Signals ---
        self.base_image_loader.image_updated.connect(self._on_base_image_selected)
        self.include_base_image_check.toggled.connect(
            self._on_include_base_image_in_animations_toggled
        )

        # Animation/Frame button signals
        self.add_anim_button.clicked.connect(self._add_animation)
        self.remove_anim_button.clicked.connect(self._remove_animation)
        # --- NEW: Connect new Add Frame buttons to their respective functions ---
        self.add_frame_before_button.triggered.connect(self._add_frame_before)
        self.add_frame_after_button.triggered.connect(self._add_frame_after)
        self.remove_frame_button.clicked.connect(self._remove_frame)
        # --- NEW: Move Button Signals ---
        self.move_frame_up_button.clicked.connect(self._move_frame_up)
        self.move_frame_down_button.clicked.connect(self._move_frame_down)
        self.duplicate_frame_button.clicked.connect(self._duplicate_frame)
        self.reverse_frames_button.triggered.connect(self._reverse_frames)
        self.ping_pong_button.triggered.connect(self._make_ping_pong_loop)
        self.polish_selected_asset_button.clicked.connect(self._polish_selected_edit_asset)
        self.onion_skin_check.toggled.connect(self._on_onion_skin_toggled)
        self.onion_skin_opacity_slider.valueChanged.connect(
            self.animation_preview.set_onion_skin_opacity
        )

        # List signals
        self.anim_list_widget.currentItemChanged.connect(self._on_current_anim_changed)

        # also catch clicks on the same item so we can restart playback
        # Playback is controlled explicitly; selecting the same animation does not restart it.

        # Update frame buttons … and also show static frame on frame‐click
        self.frame_list_widget.currentItemChanged.connect(self._update_frame_button_states)
        self.frame_list_widget.currentItemChanged.connect(self._on_current_frame_changed)
        self.frame_list_widget.itemClicked.connect(
            lambda item: self._on_current_frame_changed(item, None)
        )
        self.frame_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.frame_list_widget.customContextMenuRequested.connect(self._show_frame_context_menu)
        self.edit_asset_list_widget.currentItemChanged.connect(self._on_edit_asset_changed)

        self.name_edit.textChanged.connect(
            lambda: self.save(label="Edit sprite name", merge_key="sprite:name")
        )
        self.desc_edit.textChanged.connect(
            lambda: self.save(label="Edit sprite description", merge_key="sprite:description")
        )
        self.width_spin.valueChanged.connect(
            lambda: self.save(label="Edit sprite width", merge_key="sprite:width")
        )
        self.height_spin.valueChanged.connect(
            lambda: self.save(label="Edit sprite height", merge_key="sprite:height")
        )

        # Initially disable controls
        self._set_animation_controls_enabled(False)
        self._sync_playhead(-1)
        self._apply_styles()

    def _set_checkerboard(self, enabled):
        for canvas in (self.animation_preview.image_label, self.edit_preview_label):
            canvas.checkerboard = enabled
            canvas.update()

    def _set_pixel_art(self, enabled):
        with QtCore.QSignalBlocker(self.pixel_art_action):
            self.pixel_art_action.setChecked(enabled)
        for canvas in (self.animation_preview.image_label, self.edit_preview_label):
            canvas.pixel_art = enabled
            canvas.update()
        if isinstance(self.base_image_loader, ImageLoaderWidget):
            self.base_image_loader.set_pixel_art(enabled)
        for row in range(self.frame_list_widget.count()):
            item = self.frame_list_widget.item(row)
            item.setIcon(
                thumbnail(
                    self._absolute_image_path(self._frame_path_from_item(item)),
                    self.app_palette,
                    enabled,
                )
            )
        if self.sprite_data:
            self.save(label="Change pixel-art rendering")
            self._reload_edit_assets()

    def _sync_playback(self, playing):
        self.play_pause_button.setText("Pause" if playing else "Play")
        icon = (
            QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_pause_button.setIcon(self.style().standardIcon(icon))
        self._sync_frame_timing()

    def _selected_animation(self):
        item = self.anim_list_widget.currentItem()
        return self.sprite_data.animations.get(item.text()) if self.sprite_data and item else None

    def _sync_animation_timing(self):
        animation = self._selected_animation()
        self.preview_fps_spin.setEnabled(animation is not None)
        self.animation_loop_check.setEnabled(animation is not None)
        with (
            QtCore.QSignalBlocker(self.preview_fps_spin),
            QtCore.QSignalBlocker(self.animation_loop_check),
        ):
            self.preview_fps_spin.setValue(animation.fps if animation else 2)
            self.animation_loop_check.setChecked(animation.loop if animation else True)
        if animation and self.sprite_data is not None:
            for index in range(min(self.frame_list_widget.count(), len(animation.frames))):
                item = self.frame_list_widget.item(index)
                milliseconds = 1000 * animation.frame_seconds(index)
                item.setData(Qt.ItemDataRole.UserRole + 1, milliseconds)
                item.setToolTip(
                    f"Frame {index + 1} · {milliseconds:.2f} ms\n{animation.frames[index]}"
                )
            playback = self.sprite_data.get_animation_playback(animation.name)
            seconds = sum(playback.frame_durations) / playback.fps
            self.timeline_hint.setText(f"Drag to reorder · {seconds:.2f} s")
        else:
            self.timeline_hint.setText("Drag to reorder")
        self._sync_frame_timing()

    def _sync_frame_timing(self):
        animation = self._selected_animation()
        row = self.frame_list_widget.currentRow()
        base_selected = bool(animation and self.base_frame_button.isChecked())
        selected = bool(animation and (base_selected or 0 <= row < len(animation.frames)))
        enabled = selected and not self.animation_preview.timer.isActive()
        self.frame_duration_spin.setEnabled(enabled)
        self.reset_frame_duration_button.setEnabled(enabled)
        self.frame_duration_label.setText("Base duration" if base_selected else "Frame duration")
        if selected and animation is not None:
            duration = (
                animation.base_frame_duration if base_selected else animation.frame_durations[row]
            )
            with QtCore.QSignalBlocker(self.frame_duration_spin):
                self.frame_duration_spin.setValue(1000 * duration / animation.fps)

    def _save_animation_timing(self, before, label, merge_key=None):
        if self.save(label=label, merge_key=merge_key, previous_state=before) is False:
            self.sprite_data = before
            QMessageBox.critical(
                self,
                "Could not save timing",
                "The animation timing could not be saved. Check that the project folder is writable.",
            )
        animation = self._selected_animation()
        if animation and self.sprite_data is not None:
            self.animation_preview.set_timing(
                self.sprite_data.get_animation_playback(animation.name)
            )
        self._sync_animation_timing()

    def _on_animation_fps_changed(self, fps):
        animation = self._selected_animation()
        if animation is None or animation.fps == fps:
            return
        before = deepcopy(self.sprite_data)
        animation.fps = fps
        self._save_animation_timing(before, "Change animation FPS", f"fps:{animation.name}")

    def _on_animation_loop_changed(self, loop):
        animation = self._selected_animation()
        if animation is None or animation.loop == loop:
            return
        before = deepcopy(self.sprite_data)
        animation.loop = loop
        self._save_animation_timing(before, "Change animation loop")

    def _on_frame_duration_changed(self, milliseconds):
        animation = self._selected_animation()
        if animation is None or not self.frame_duration_spin.isEnabled():
            return
        row = self.frame_list_widget.currentRow()
        base_selected = self.base_frame_button.isChecked()
        before = deepcopy(self.sprite_data)
        duration = milliseconds * animation.fps / 1000
        if base_selected:
            animation.base_frame_duration = duration
        elif 0 <= row < len(animation.frames):
            animation.frame_durations[row] = duration
        else:
            return
        self._save_animation_timing(
            before, "Change frame duration", f"duration:{animation.name}:{row}"
        )

    def _reset_frame_duration(self):
        animation = self._selected_animation()
        if animation:
            self._on_frame_duration_changed(1000 / animation.fps)

    def _sync_playhead(self, index):
        count = len(self.animation_preview.pixmaps)
        self.play_pause_button.setEnabled(count > 0)
        self.previous_frame_button.setEnabled(count > 0)
        self.next_frame_button.setEnabled(count > 0)
        has_base = bool(
            self.sprite_data
            and self.sprite_data.base_image
            and self.include_base_image_check.isChecked()
        )
        self.base_frame_button.setEnabled(has_base and count > 0)
        self.base_frame_button.setCheckable(True)
        self.base_frame_button.setChecked(has_base and index == 0 and count > 0)
        self.frame_position_label.setText(
            (
                f"Base / {count}"
                if has_base and index == 0
                else f"Frame {index + 1 - int(has_base)} / {count - int(has_base)}"
            )
            if count and index >= 0
            else "No frames"
        )
        if count and index >= 0:
            row = index - int(has_base)
            with QtCore.QSignalBlocker(self.frame_list_widget):
                self.frame_list_widget.setCurrentRow(row)
            if row >= 0 and self.frame_list_widget.currentItem():
                self.frame_list_widget.scrollToItem(self.frame_list_widget.currentItem())
        self._update_frame_button_states()
        self._sync_frame_timing()

    def _select_base_frame(self):
        self.animation_preview.set_playing(False)
        self.animation_preview.show_frame(0)

    def _on_frames_reordered(self, source, destination):
        item = self.anim_list_widget.currentItem()
        if self.sprite_data is None or item is None:
            return
        before = deepcopy(self.sprite_data)
        reorder_frame(self.sprite_data, item.text(), source, destination)
        self.save(label="Reorder frames", previous_state=before)
        self._update_animation_preview()
        self._reload_edit_assets()

    def _on_base_image_selected(self, path: str):
        """Handle when the user selects a new base image manually."""
        sprite_data = self.sprite_data
        if sprite_data is None:
            return
        previous_sprite_data = deepcopy(sprite_data)
        if not path:
            sprite_data.base_image = ""
            self._reload_edit_assets()
            self._update_animation_preview()
            self.save(label="Clear base image", previous_state=previous_sprite_data)
            return
        if not os.path.isabs(path):
            base_dir = self._base_dir
            if base_dir is None:
                return
            # If path is not absolute, make it absolute relative to base_dir
            path = os.path.abspath(os.path.join(base_dir, path))
        print(f"User selected base image (absolute path): {path}")
        sprite_data.base_image = path
        self._reload_edit_assets()
        self._update_animation_preview()
        self.save(label="Change base image", previous_state=previous_sprite_data)

    def _return_to_sage_project(self):
        if self.sage_file is None:
            return
        self.return_to_sage.emit(self.sage_file.filepath)

    def _disassociate_current_sprite(self):
        if not self.current_file_path or self.sage_file is None:
            return

        try:
            relative_path = os.path.relpath(
                self.current_file_path, self.sage_file.directory
            ).replace("\\", "/")
        except ValueError:
            QMessageBox.warning(
                self,
                "Remove Sprite",
                "This sprite is not inside the current project directory.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Remove Sprite",
            (
                f"Remove '{relative_path}' from this project?\n\n"
                "The .sprite file and image files will remain on disk."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        previous_sage_file = deepcopy(self.sage_file)
        hidden_sprites = {
            path.replace("\\", "/") for path in getattr(self.sage_file, "hidden_sprites", [])
        }
        hidden_sprites.add(relative_path)
        self.sage_file.hidden_sprites = sorted(hidden_sprites)
        self.sage_file.save()
        self.project_file_changed.emit(
            previous_sage_file,
            deepcopy(self.sage_file),
            "Remove sprite from project",
        )

    def _on_include_base_image_in_animations_toggled(self, checked: bool):
        if not self.sprite_data:
            return
        previous_sprite_data = deepcopy(self.sprite_data)
        self.sprite_data.include_base_image_in_animations = checked
        self._update_animation_preview()
        self.save(
            label="Toggle base image in animations",
            previous_state=previous_sprite_data,
        )

    def _call_ai(self, ai_manager: AIModelManager, fn, action_message: str):
        if not ensure_llm_configured(self, ai_manager):
            return None
        return call_ai_with_busy(
            self,
            ai_manager,
            fn,
            message=f"{action_message} with {ai_manager.get_active_vendor().value}",
            palette=self.app_palette,
        )

    def _on_base_image_action_clicked(self, index: int):
        sprite_description = (
            self.desc_edit.toPlainText().strip()
        )  # Get text and remove leading/trailing whitespace
        if not sprite_description:
            # Show an alert message box
            QMessageBox.warning(
                self,
                "Missing Description",
                "The sprite description cannot be empty to use the AI image generation feature.\n\nPlease provide a description before generating.",
            )
            print("AI generation aborted: Sprite description is empty.")
            return  # Stop processing the rest of the function

        sage_file = self.sage_file
        if sage_file is None:
            return

        ai_manager = AIModelManager()
        # Generate the new base sprite image.
        new_image = self._call_ai(
            ai_manager,
            lambda: ai_manager.generate_base_sprite_image(
                input=GenerateBaseSpriteImageInput(
                    output_folder=sage_file.directory,
                    sprite_description=sprite_description,
                    project_description=sage_file.project_description,
                    camera=sage_file.camera,
                    keywords=sage_file.keywords,
                    images=sage_file.reference_image_abs_paths(),
                )
            ),
            "Generating base sprite image",
        )

        if new_image is not None:
            sprite_data = self.sprite_data
            if sprite_data is None:
                return
            previous_sprite_data = deepcopy(sprite_data)
            sprite_data.base_image = new_image
            # Update the base image loader to show the newly generated image.
            self.base_image_loader.load_image(new_image)
            self._reload_edit_assets()
            print(f"Base image updated to: {new_image}")

            self.save(label="Generate base image", previous_state=previous_sprite_data)
        else:
            print("No image returned from AIModelManager.generate_base_sprite_image()")

        print(
            f"ImageLoaderWidget at index {index} triggered AIModelManager.generate_base_sprite_image()."
        )

    def _set_animation_controls_enabled(self, enabled: bool):
        """Enable/disable animation controls. Frame controls depend on selections."""
        self.add_anim_button.setEnabled(enabled)
        # Other buttons depend on selection, handled by _update_frame_button_states
        self.anim_list_widget.setEnabled(enabled)
        self.frame_list_widget.setEnabled(enabled)

        # If disabling all, also disable frame-specific buttons
        if not enabled:
            self.preview_fps_spin.setEnabled(False)
            self.animation_loop_check.setEnabled(False)
            self.frame_duration_spin.setEnabled(False)
            self.reset_frame_duration_button.setEnabled(False)
            self.remove_anim_button.setEnabled(False)
            self.add_frame_before_icon.setEnabled(False)
            self.add_frame_after_icon.setEnabled(False)
            self.add_frame_before_button.setEnabled(False)
            self.add_frame_after_button.setEnabled(False)
            self.remove_frame_button.setEnabled(False)
            self.move_frame_up_button.setEnabled(False)
            self.move_frame_down_button.setEnabled(False)
            self.duplicate_frame_button.setEnabled(False)
            self.reverse_frames_button.setEnabled(False)
            self.ping_pong_button.setEnabled(False)
            self.onion_skin_check.setEnabled(False)
            self.onion_skin_opacity_slider.setEnabled(False)
            self._set_onion_skin_opacity_visible(False)
        else:
            self.onion_skin_check.setEnabled(True)
            self.onion_skin_opacity_slider.setEnabled(self.onion_skin_check.isChecked())
            self._set_onion_skin_opacity_visible(self.onion_skin_check.isChecked())
            # If enabling, update based on current state
            self._update_frame_button_states()  # Update all buttons based on selection

    def _on_onion_skin_toggled(self, enabled: bool):
        self.onion_skin_opacity_slider.setEnabled(enabled)
        self._set_onion_skin_opacity_visible(enabled)
        self.animation_preview.set_onion_skin_enabled(enabled)

    def _set_onion_skin_opacity_visible(self, visible: bool):
        self.onion_skin_opacity_label.setVisible(visible)
        self.onion_skin_opacity_slider.setVisible(visible)

    def _make_frame_item(self, frame_path: str) -> QListWidgetItem:
        item = QListWidgetItem(self._display_name_for_path(frame_path))
        item.setData(Qt.ItemDataRole.UserRole, frame_path)
        item.setToolTip(frame_path)
        item.setIcon(
            thumbnail(
                self._absolute_image_path(frame_path),
                self.app_palette,
                self.pixel_art_check.isChecked(),
            )
        )
        item.setData(Qt.ItemDataRole.AccessibleTextRole, self._display_name_for_path(frame_path))
        return item

    @staticmethod
    def _frame_path_from_item(item: QListWidgetItem) -> str:
        stored_path = item.data(Qt.ItemDataRole.UserRole)
        return str(stored_path) if stored_path else item.text()

    @staticmethod
    def _display_name_for_path(path: str) -> str:
        name = os.path.basename(path)
        return name or path

    def _add_frame_items(self, frames: list[str]) -> None:
        for frame_path in frames:
            self.frame_list_widget.addItem(self._make_frame_item(frame_path))

    def _on_current_frame_changed(self, current_item, previous_item):
        """When a frame is clicked, stop playback and show only that frame."""
        if self.frame_list_widget.signalsBlocked() or not current_item or not self.sprite_data:
            return
        # compute pixmap index (base image at 0 if present)
        has_base = bool(self.sprite_data.base_image and self.include_base_image_check.isChecked())
        frame_idx = self.frame_list_widget.row(current_item)
        pixmap_idx = frame_idx + (1 if has_base else 0)
        pm_list = self.animation_preview.pixmaps
        if 0 <= pixmap_idx < len(pm_list):
            # stop any running animation
            self.animation_preview.set_playing(False)
            self.animation_preview.show_frame(pixmap_idx)

    def _get_sprite_data_to_save(self) -> SpriteFile:
        if self.sprite_data is None:
            raise RuntimeError("Cannot save before sprite data is loaded.")
        current_sprite_data = deepcopy(self.sprite_data)
        current_sprite_data.name = self.name_edit.text()
        current_sprite_data.description = self.desc_edit.toPlainText()
        current_sprite_data.width = self.width_spin.value()
        current_sprite_data.height = self.height_spin.value()
        current_sprite_data.base_image = self.base_image_loader.get_absolute_path() or ""
        current_sprite_data.include_base_image_in_animations = (
            self.include_base_image_check.isChecked()
        )
        current_sprite_data.pixel_art = self.pixel_art_check.isChecked()
        return current_sprite_data

    def undo_redo_state(self):
        return self._undo_redo_manager.state()

    def _emit_undo_redo_state(self):
        self.undo_redo_state_changed.emit(self.undo_redo_state())

    def apply_recovered_file(self, file_path: str, sage_file: SageFile, before: SpriteFile):
        """Reload recovery as one Undo action, retaining the existing editing history."""
        keep_history = self.current_file_path == file_path and self.sprite_data is not None
        self.load_sprite_data(file_path, sage_file, reset_history=not keep_history)
        if self.sprite_data is not None:
            self._undo_redo_manager.record_change(
                before, self.sprite_data, label="Recover saved version"
            )
            self._emit_undo_redo_state()

    def save(
        self,
        label: str = "Edit sprite",
        merge_key: str | None = None,
        previous_state: SpriteFile | None = None,
    ):
        if not self.current_file_path or not self.sprite_data or not self.sage_file:
            return None

        previous_sprite_data = previous_state if previous_state is not None else self.sprite_data
        current_sprite_data = self._get_sprite_data_to_save()
        try:
            current_sprite_data.save(
                fpath=self.current_file_path, sage_directory=self.sage_file.directory
            )
        except (OSError, ValueError, TypeError):
            return False
        history_changed = self._undo_redo_manager.record_change(
            previous_sprite_data,
            current_sprite_data,
            label=label,
            merge_key=merge_key,
        )
        self.sprite_data = current_sprite_data
        if history_changed:
            self._emit_undo_redo_state()
        return True

    def export_current_sprite_to_godot(self):
        if not self.current_file_path or not self.sprite_data or not self.sage_file:
            QMessageBox.warning(self, "Export Sprite", "No sprite file is currently loaded.")
            return

        self.save()
        base = os.path.splitext(os.path.basename(self.current_file_path))[0]
        default_name = f"{base}_godot_export"
        folder_name, ok = self._prompt_for_export_folder_name(default_name)
        if not ok or not folder_name.strip():
            return

        output_dir = self._resolve_godot_export_dir(folder_name.strip())
        try:
            sprite_file = SpriteFile.from_json(
                fpath=self.current_file_path,
                sage_directory=self.sage_file.directory,
            )

            def run_export(progress_callback=None):
                exporter = GodotSpriteExporter(
                    sprite_file=sprite_file,
                    output_dir=output_dir,
                    progress_callback=progress_callback,
                )
                exporter.export()

            call_with_progress(
                self,
                run_export,
                message="Preparing Godot export",
                progress_label="Exporting Godot sprite",
                palette=self.app_palette,
            )
            self._show_export_complete(self.current_file_path, output_dir)
        except Exception as e:
            self._show_export_failed(e)

    def _godot_export_project_directory(self) -> str:
        if self.sage_file is None:
            raise RuntimeError("Cannot export before a project is loaded.")
        return self.sage_file.directory

    def _show_export_complete(self, sprite_path: str, output_dir: str):
        self._show_export_message(
            QMessageBox.Icon.Information,
            "Export Complete",
            f"Exported '{os.path.basename(sprite_path)}' to:\n{output_dir}",
        )

    def _show_export_failed(self, error: Exception):
        self._show_export_message(
            QMessageBox.Icon.Critical,
            "Export Failed",
            f"Could not export sprite:\n{error}",
        )

    def undo(self):
        if not self.current_file_path or not self.sprite_data or not self.sage_file:
            return

        undo_sprite_file = self._undo_redo_manager.undo(
            current_state=self._get_sprite_data_to_save()
        )
        if undo_sprite_file is not None:
            try:
                undo_sprite_file.save(
                    fpath=self.current_file_path, sage_directory=self.sage_file.directory
                )
            except (OSError, ValueError, TypeError):
                self._undo_redo_manager.redo()
                self._emit_undo_redo_state()
                return
            self.load_sprite_data(
                file_path=self.current_file_path,
                sage_file=self.sage_file,
                reset_history=False,
            )
        else:
            self._emit_undo_redo_state()

    def redo(self):
        if not self.current_file_path or not self.sage_file:
            return

        redo_sprite_file = self._undo_redo_manager.redo()
        if redo_sprite_file is not None:
            try:
                redo_sprite_file.save(
                    fpath=self.current_file_path, sage_directory=self.sage_file.directory
                )
            except (OSError, ValueError, TypeError):
                self._undo_redo_manager.undo()
                self._emit_undo_redo_state()
                return
            self.load_sprite_data(
                file_path=self.current_file_path,
                sage_file=self.sage_file,
                reset_history=False,
            )
        else:
            self._emit_undo_redo_state()

    def _apply_styles(self):
        """Apply palette colors to UI elements."""
        bg_color = self.app_palette.get("widget_bg", "#333333")
        text_color = self.app_palette.get("text_color", "#D3D3D3")
        label_color = self.app_palette.get("label_color", "#A0A0A0")
        border_color = self.app_palette.get("placeholder_border", "#555555")
        button_bg = self.app_palette.get("button_bg", "#555555")
        button_fg = self.app_palette.get("button_text", "#D3D3D3")
        input_bg = self.app_palette.get("editable_value_bg", "#313335")

        # Reduce padding slightly for icon buttons
        move_button_padding = "2px"  # Adjust as needed
        general_button_padding = "4px 8px"

        self.setStyleSheet(f"""
            QWidget {{ background-color: {bg_color}; color: {text_color}; }}
            QLabel {{ color: {label_color}; padding-top: 3px; }}
            QTabWidget::pane {{
                border: 1px solid {border_color};
                background-color: {bg_color};
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {button_bg};
                color: {button_fg};
                border: 1px solid {border_color};
                border-bottom: none;
                padding: 5px 12px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {bg_color};
                color: {text_color};
                border-bottom: 1px solid {bg_color};
            }}
            QTabBar::tab:hover {{
                background-color: #4A4D4F;
            }}
            QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
                background-color: {input_bg};
                color: {text_color};
                border: 1px solid {border_color};
                padding: 3px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}
            QGroupBox {{
                color: {label_color};
                border: 1px solid {border_color};
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 3px 0 3px;
                left: 10px;
            }}
            QListWidget {{
                background-color: {input_bg};
                border: 1px solid {border_color};
                alternate-background-color: {self.app_palette.get('list_alt_bg', '#3A3A3A')};
            }}
             QListWidget::item:selected {{
                 background-color: {self.app_palette.get('tree_item_selected_bg', '#5A7E9E')};
                 color: {self.app_palette.get('tree_item_selected_text', '#FFFFFF')};
             }}
            QPushButton {{
                background-color: {button_bg};
                color: {button_fg};
                border: 1px solid {border_color};
                padding: {general_button_padding};
                min-height: 18px;
            }}
            QPushButton:hover {{ background-color: #6A6A6A; }}
            QPushButton:pressed {{ background-color: #4E4E4E; }}
            QPushButton:disabled {{ background-color: #404040; color: #777777; border-color: #444444; }}
            QPushButton:checked {{ background-color: {self.app_palette['tree_item_selected_bg']}; color: white; }}
            QPushButton:focus, QComboBox:focus, QSpinBox:focus {{
                border: 1px solid {self.app_palette['tree_item_selected_bg']};
            }}
            QMenu {{ background-color: {input_bg}; color: {text_color}; border: 1px solid {border_color}; }}
            QMenu::item {{ padding: 7px 22px; }}
            QMenu::item:selected {{ background-color: {self.app_palette['tree_item_selected_bg']}; color: white; }}
            QMenu::item:disabled {{ color: {label_color}; }}
            QToolTip {{ background-color: {input_bg}; color: {text_color}; border: 1px solid {border_color}; }}
            QListWidget::item {{ padding: 4px; }}
            QListWidget#FrameTimeline::item {{ border: 2px solid transparent; border-radius: 4px; }}
            QListWidget#FrameTimeline::item:selected {{ border-color: {self.app_palette['tree_item_selected_bg']}; }}
            QSplitter::handle {{ background-color: {border_color}; }}
            /* Compact directional controls. */
            QPushButton#MoveUpButton, QPushButton#MoveDownButton {{
                 padding: {move_button_padding};
                 min-width: 24px; /* Ensure enough space for icon */
            }}
        """)
        # Set object names for specific styling (optional)
        self.move_frame_up_button.setObjectName("MoveUpButton")
        self.move_frame_down_button.setObjectName("MoveDownButton")

    def load_sprite_data(self, file_path: str, sage_file: SageFile, *, reset_history: bool = True):
        selected_animation = self.anim_list_widget.currentItem()
        keep_animation = (
            selected_animation.text() if selected_animation and not reset_history else None
        )
        keep_row = self.frame_list_widget.currentRow()
        self.sage_file = sage_file

        self.current_file_path = file_path
        self._base_dir = os.path.dirname(file_path)
        print(f"SpriteEditorView: Loading {file_path}")
        print(f"SpriteEditorView: Base directory set to {self._base_dir}")
        self._clear_ui()
        try:
            self.sprite_data = SpriteFile.from_json(
                fpath=file_path, sage_directory=self.sage_file.directory
            )
        except Exception as e:
            # ... (Error handling as before) ...
            QMessageBox.critical(self, "Error", f"Failed to load sprite: {e}")
            self.sprite_data = None
            self.current_file_path = None
            self._base_dir = None
            self._undo_redo_manager.clear()
            self._emit_undo_redo_state()
            return False

        if reset_history:
            self._undo_redo_manager.reset(self.sprite_data)

        self._block_signals(True)
        self.name_edit.setText(self.sprite_data.name)
        self.desc_edit.setPlainText(self.sprite_data.description)
        self.width_spin.setValue(self.sprite_data.width)
        self.height_spin.setValue(self.sprite_data.height)
        self.base_image_loader.base_dir = self._base_dir
        base_image_path = self.sprite_data.base_image
        self.base_image_loader.load_image(base_image_path)
        self.include_base_image_check.setChecked(
            getattr(self.sprite_data, "include_base_image_in_animations", True)
        )
        self.pixel_art_check.setChecked(getattr(self.sprite_data, "pixel_art", True))
        with QtCore.QSignalBlocker(self.pixel_art_action):
            self.pixel_art_action.setChecked(self.pixel_art_check.isChecked())
        self.animation_preview.image_label.pixel_art = self.pixel_art_check.isChecked()
        self.edit_preview_label.pixel_art = self.pixel_art_check.isChecked()
        if isinstance(self.base_image_loader, ImageLoaderWidget):
            self.base_image_loader.set_pixel_art(self.pixel_art_check.isChecked())

        animations = self.sprite_data.animations

        for anim_name in sorted(animations.keys()):
            self.anim_list_widget.addItem(anim_name)

        # Auto-select first animation AFTER enabling controls and unblocking signals for anim list
        self._set_animation_controls_enabled(True)  # Enable controls (inc. lists)
        self.anim_list_widget.blockSignals(False)  # Unblock anim list signals
        if self.anim_list_widget.count() > 0:
            matches = self.anim_list_widget.findItems(
                keep_animation or "", Qt.MatchFlag.MatchExactly
            )
            self.anim_list_widget.setCurrentItem(
                matches[0] if matches else self.anim_list_widget.item(0)
            )
            if keep_animation and self.frame_list_widget.count():
                self.frame_list_widget.setCurrentRow(
                    max(0, min(keep_row, self.frame_list_widget.count() - 1))
                )
        else:
            self.animation_preview.clear_preview()
            # Ensure button states are correct even with no anim selected
            self._update_frame_button_states()  # Update buttons (will disable frame buttons)

        self.anim_list_widget.blockSignals(True)  # Re-block anim list signals for safety
        self._block_signals(False)  # Unblock other signals (like frame list)
        self.export_sprite_button.setEnabled(True)
        self.disassociate_sprite_button.setEnabled(True)
        self._reload_edit_assets()
        self._emit_undo_redo_state()

    def _clear_ui(self):
        self._block_signals(True)
        self.name_edit.clear()
        self.desc_edit.clear()
        self.width_spin.setValue(0)
        self.height_spin.setValue(0)
        self.base_image_loader.clear_image(emit_signal=False)
        self.include_base_image_check.setChecked(True)
        self.anim_list_widget.clear()
        self.frame_list_widget.clear()
        self.edit_asset_list_widget.clear()
        self.edit_preview_label.setText("Select an asset to edit")
        self.edit_preview_label.setPixmap(QPixmap())
        self.polish_selected_asset_button.setEnabled(False)
        self.animation_preview.clear_preview()
        self._block_signals(False)
        self._set_animation_controls_enabled(False)  # Disable controls, inc frame buttons
        self.export_sprite_button.setEnabled(False)
        self.disassociate_sprite_button.setEnabled(False)

    def _block_signals(self, block: bool):
        self.name_edit.blockSignals(block)
        self.desc_edit.blockSignals(block)
        self.width_spin.blockSignals(block)
        self.height_spin.blockSignals(block)
        self.base_image_loader.blockSignals(block)
        self.include_base_image_check.blockSignals(block)
        self.pixel_art_check.blockSignals(block)
        self.anim_list_widget.blockSignals(block)
        # Frame list signals are only used for button state updates, okay to leave unblocked generally
        # self.frame_list_widget.blockSignals(block)

    def _on_current_anim_changed(
        self, current_item: QListWidgetItem | None, previous_item: QListWidgetItem | None
    ):
        """Updates the frame list AND the animation preview when the selected animation changes."""
        sprite_data = self.sprite_data
        if self.anim_list_widget.signalsBlocked() or sprite_data is None:
            return

        print(f"Current anim changed. Selected: {current_item.text() if current_item else 'None'}")

        # Block frame list signals while clearing/populating to avoid unwanted triggers
        self.frame_list_widget.blockSignals(True)
        self.frame_list_widget.clear()
        if current_item:
            anim_name = current_item.text()
            frames = sprite_data.get_animation_frames(animation_name=anim_name)
            self._add_frame_items(frames)
            # Select the first frame by default if frames exist
            if self.frame_list_widget.count() > 0:
                self.frame_list_widget.setCurrentRow(0)
        self.frame_list_widget.blockSignals(False)

        # Update preview
        self._update_animation_preview()

        # Update button states now that frame list is populated/cleared
        self._update_frame_button_states()
        self._reload_edit_assets()

    def _update_animation_preview(self):
        """Loads the selected animation into the preview pane."""
        current_item = self.anim_list_widget.currentItem()
        base_dir = self._base_dir
        sprite_data = self.sprite_data
        self._sync_animation_timing()

        if current_item and base_dir and sprite_data:
            anim_name = current_item.text()
            # Get the *current* order from sprite_data
            base_img = sprite_data.base_image
            include_base = self.include_base_image_check.isChecked()
            animation = sprite_data.get_animation_playback(anim_name)
            frame_paths = animation.frames
            print(
                f"Updating preview for '{anim_name}' with {len(frame_paths)} frames. "
                f"Include base: {include_base}. Base dir: {base_dir}"
            )
            # Loading originals is independent of widget geometry. Do it synchronously
            # so a pending callback cannot restore a deleted/switched animation.
            row = self.frame_list_widget.currentRow()
            self.animation_preview.load_animation(frame_paths, base_dir, animation=animation)
            self.animation_preview.set_playing(False)
            self._sync_playhead(0 if frame_paths else -1)
            if frame_paths:
                self.animation_preview.show_frame(
                    max(0, row + int(bool(include_base and base_img)))
                )
        else:
            print("Clearing preview (no item selected or no base_dir)")
            self.animation_preview.clear_preview()

    # --- RENAMED and EXPANDED Button State Update ---
    def _update_frame_button_states(self):
        """Enable/disable ALL frame-related buttons based on current selection."""
        anim_selected = self.anim_list_widget.currentItem() is not None
        current_frame_item = self.frame_list_widget.currentItem()
        frame_selected = current_frame_item is not None
        frame_count = self.frame_list_widget.count()
        current_row = -1
        if frame_selected:
            current_row = self.frame_list_widget.row(current_frame_item)

        # Animation buttons
        self.remove_anim_button.setEnabled(anim_selected)
        self.add_frames_button.setEnabled(anim_selected)
        self.sequence_button.setEnabled(anim_selected and frame_count > 1)
        self.include_base_image_check.setEnabled(self.sprite_data is not None)

        # Frame buttons (now for both Add Frame Before/After)
        self.add_frame_before_icon.setEnabled(anim_selected)
        self.add_frame_after_icon.setEnabled(anim_selected)
        self.add_frame_before_button.setEnabled(anim_selected)
        self.add_frame_after_button.setEnabled(anim_selected)
        self.remove_frame_button.setEnabled(frame_selected)
        self.duplicate_frame_button.setEnabled(frame_selected)
        self.reverse_frames_button.setEnabled(anim_selected and frame_count > 1)
        self.ping_pong_button.setEnabled(anim_selected and frame_count > 2)

        # Move buttons
        can_move_up = frame_selected and current_row > 0
        can_move_down = frame_selected and current_row < (frame_count - 1)
        self.move_frame_up_button.setEnabled(can_move_up)
        self.move_frame_down_button.setEnabled(can_move_down)

    def _show_frame_context_menu(self, pos: QtCore.QPoint):
        item = self.frame_list_widget.itemAt(pos)
        if item is None:
            return

        self.frame_list_widget.setCurrentItem(item)
        self._on_current_frame_changed(item, None)
        menu = QtWidgets.QMenu(self)
        for button in (
            self.duplicate_frame_button,
            self.remove_frame_button,
            self.move_frame_up_button,
            self.move_frame_down_button,
        ):
            action = menu.addAction(button.text() or button.toolTip())
            action.setEnabled(button.isEnabled())
            action.triggered.connect(button.click)
        menu.addSeparator()
        polish_action = menu.addAction("Polish Frame...")
        selected_action = menu.exec(self.frame_list_widget.viewport().mapToGlobal(pos))
        if selected_action == polish_action:
            self._polish_current_frame()

    def _reload_edit_assets(self):
        if not hasattr(self, "edit_asset_list_widget"):
            return

        previous_path = None
        current_item = self.edit_asset_list_widget.currentItem()
        if current_item is not None:
            previous_path = current_item.data(Qt.ItemDataRole.UserRole)

        self.edit_asset_list_widget.blockSignals(True)
        self.edit_asset_list_widget.clear()
        sprite_data = self.sprite_data
        if sprite_data is not None and sprite_data.base_image:
            base_item = QListWidgetItem("Base Image")
            base_item.setData(Qt.ItemDataRole.UserRole, sprite_data.base_image)
            base_item.setData(Qt.ItemDataRole.UserRole + 1, ("base", "", -1))
            base_item.setToolTip(sprite_data.base_image)
            base_item.setIcon(
                thumbnail(
                    self._absolute_image_path(sprite_data.base_image),
                    self.app_palette,
                    self.pixel_art_check.isChecked(),
                )
            )
            self.edit_asset_list_widget.addItem(base_item)

        animations = getattr(sprite_data, "animations", {}) if sprite_data is not None else {}
        if sprite_data is not None:
            for anim_name in sorted(animations.keys()):
                frames = sprite_data.get_animation_frames(animation_name=anim_name)
                for frame_index, frame_path in enumerate(frames):
                    item = QListWidgetItem(
                        f"{anim_name} / {frame_index + 1}: {self._display_name_for_path(frame_path)}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, frame_path)
                    item.setData(Qt.ItemDataRole.UserRole + 1, ("frame", anim_name, frame_index))
                    item.setToolTip(frame_path)
                    item.setIcon(
                        thumbnail(
                            self._absolute_image_path(frame_path),
                            self.app_palette,
                            self.pixel_art_check.isChecked(),
                        )
                    )
                    self.edit_asset_list_widget.addItem(item)

        selected_row = 0 if self.edit_asset_list_widget.count() else -1
        if previous_path is not None:
            for row in range(self.edit_asset_list_widget.count()):
                item = self.edit_asset_list_widget.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == previous_path:
                    selected_row = row
                    break
        if selected_row >= 0:
            self.edit_asset_list_widget.setCurrentRow(selected_row)
        self.edit_asset_list_widget.blockSignals(False)
        self._on_edit_asset_changed(self.edit_asset_list_widget.currentItem(), None)

    def _on_edit_asset_changed(self, current_item, previous_item):
        if current_item is None:
            self.polish_selected_asset_button.setEnabled(False)
            self.edit_preview_label.setPixmap(QPixmap())
            self.edit_preview_label.setText("Select an asset to edit")
            return

        image_path = str(current_item.data(Qt.ItemDataRole.UserRole) or "")
        self.polish_selected_asset_button.setEnabled(bool(image_path))
        self._show_edit_preview(image_path)

    def _show_edit_preview(self, image_path: str):
        path = self._absolute_image_path(image_path)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.edit_preview_label.setPixmap(QPixmap())
            self.edit_preview_label.setText("Preview unavailable")
            self.edit_preview_label.setToolTip(path)
            return

        self.edit_preview_label.setText("")
        self.edit_preview_label.setPixmap(pixmap)
        self.edit_preview_label.setToolTip(path)

    def _polish_selected_edit_asset(self):
        item = self.edit_asset_list_widget.currentItem()
        if item is None:
            return

        metadata = item.data(Qt.ItemDataRole.UserRole + 1)
        if not metadata:
            return

        kind, anim_name, frame_index = metadata
        if kind == "base":
            self._polish_base_image()
            return

        if kind != "frame":
            return

        for row in range(self.anim_list_widget.count()):
            anim_item = self.anim_list_widget.item(row)
            if anim_item.text() == anim_name:
                self.anim_list_widget.setCurrentRow(row)
                break
        if 0 <= frame_index < self.frame_list_widget.count():
            self.frame_list_widget.setCurrentRow(frame_index)
            self._polish_current_frame()

    def _polish_base_image(self):
        sprite_data = self.sprite_data
        source_path = self.base_image_loader.get_absolute_path()
        if sprite_data is None or not source_path:
            return

        output_path = self._run_polish_dialog(source_path, title="Polish Base Image")
        if output_path is None:
            return

        previous_sprite_data = deepcopy(sprite_data)
        sprite_data.base_image = str(output_path)
        self.base_image_loader.load_image(str(output_path))
        self._update_animation_preview()
        self._reload_edit_assets()
        self.save(label="Polish base image", previous_state=previous_sprite_data)

    def _polish_current_frame(self):
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_item = self.frame_list_widget.currentItem()
        sprite_data = self.sprite_data
        if (
            current_anim_item is None
            or current_frame_item is None
            or sprite_data is None
            or not self.current_file_path
        ):
            return

        source_path = self._absolute_image_path(self._frame_path_from_item(current_frame_item))
        output_path = self._run_polish_dialog(source_path, title="Polish Frame")
        if output_path is None:
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.row(current_frame_item)
        frames = sprite_data.get_animation_frames(animation_name=anim_name)
        if current_row < 0 or current_row >= len(frames):
            return

        previous_sprite_data = deepcopy(sprite_data)
        sprite_data.animations[anim_name].frames[current_row] = str(output_path)
        replacement_item = self._make_frame_item(str(output_path))
        self.frame_list_widget.takeItem(current_row)
        self.frame_list_widget.insertItem(current_row, replacement_item)
        self.frame_list_widget.setCurrentRow(current_row)
        self._update_animation_preview()
        self._update_frame_button_states()
        self._reload_edit_assets()
        self.save(label="Polish frame", previous_state=previous_sprite_data)

    def _absolute_image_path(self, image_path: str) -> str:
        if os.path.isabs(image_path):
            return image_path
        if self._base_dir:
            return os.path.abspath(os.path.join(self._base_dir, image_path))
        return image_path

    def _run_polish_dialog(self, source_path: str, *, title: str) -> os.PathLike[str] | None:
        if not os.path.exists(source_path):
            QMessageBox.warning(
                self,
                title,
                f"Image file could not be found:\n{source_path}",
            )
            return None

        try:
            with Image.open(source_path) as image:
                source_image = image.convert("RGBA")
        except Exception as exc:
            QMessageBox.warning(
                self,
                title,
                f"Image file could not be opened:\n{exc}",
            )
            return None

        dialog = ImagePolishDialog(
            source_image,
            palette=self.app_palette,
            title=title,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        try:
            return save_polished_copy(source_path, dialog.polished_image)
        except Exception as exc:
            QMessageBox.critical(
                self,
                title,
                f"Failed to save polished copy:\n{exc}",
            )
            return None

    # --- Animation Actions ---

    def _animate_from_template(self):
        if not self.current_file_path or self.sprite_data is None or self.sage_file is None:
            return
        from .animation_transfer.dialog import AnimationTransferDialog
        from .animation_transfer.service import merge_animations

        dialog = AnimationTransferDialog(
            self.sage_file.directory,
            self.app_palette,
            self,
            sprite=self._get_sprite_data_to_save(),
            project_description=self.sage_file.project_description,
            keywords=self.sage_file.keywords,
        )
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or dialog.result_data is None:
            return
        previous = deepcopy(self.sprite_data)
        try:
            merge_animations(self.sprite_data, dialog.result_data)
            if self.save(label="Transfer template animations", previous_state=previous) is False:
                raise OSError(
                    "Could not save the sprite. Generated frames are still in the project."
                )
        except Exception as error:
            self.sprite_data = previous
            QMessageBox.warning(self, "Could not add animations", str(error))
            return
        self.load_sprite_data(self.current_file_path, self.sage_file, reset_history=False)

    def _add_animation(self):
        if not self.current_file_path or self.sprite_data is None:
            return
        # Show dialog to get animation name with AI suggestion inline
        dialog = QDialog(self)
        dialog.setObjectName("SpriteSagePopupDialog")
        dialog.setStyleSheet(build_application_stylesheet(self.app_palette))
        dialog.setWindowTitle("Add Animation")
        layout = QVBoxLayout(dialog)
        # Prompt
        label = QLabel("Enter Animation Name:")
        label.setProperty("dialogTextPanel", True)
        layout.addWidget(label)
        # Input row: text field + AI suggestion button
        input_row = QWidget(dialog)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(dialog)
        input_layout.addWidget(line_edit)
        # AI button: suggest name but do not auto-accept
        ai_btn = ActionIconButton(
            self.app_palette,
            "add_animation_with_ai",
            tooltip="Suggest an animation name with AI",
            parent=dialog,
        )
        ai_btn.clicked_with_action.connect(
            lambda action, le=line_edit: self._on_add_animation_with_ai_action(le)
        )
        input_layout.addWidget(ai_btn)
        layout.addWidget(input_row)
        # Row for future AI-generated frames count (0-20)
        ai_frames_row = QWidget(dialog)
        ai_frames_layout = QHBoxLayout(ai_frames_row)
        ai_frames_layout.setContentsMargins(0, 0, 0, 0)
        ai_frames_label = QLabel("Add AI Generated Frames:")
        ai_frames_label.setProperty("dialogTextPanel", True)
        ai_frames_layout.addWidget(ai_frames_label)
        ai_frames_spin = QSpinBox(dialog)
        ai_frames_spin.setRange(0, 20)
        ai_frames_spin.setValue(0)
        ai_frames_layout.addWidget(ai_frames_spin)
        ai_frames_layout.addStretch()
        layout.addWidget(ai_frames_row)
        # Dialog action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        ok_btn = QPushButton("OK", dialog)
        ok_btn.clicked.connect(dialog.accept)
        buttons_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel", dialog)
        cancel_btn.clicked.connect(dialog.reject)
        buttons_layout.addWidget(cancel_btn)
        layout.addLayout(buttons_layout)

        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            anim_name = line_edit.text()
            ok = True
        else:
            anim_name = ""
            ok = False
        if ok and anim_name:
            anim_name = anim_name.strip()
            if not anim_name:
                QMessageBox.warning(self, "Invalid Name", "Animation name cannot be empty.")
                return
            if anim_name in self.sprite_data.animations:
                QMessageBox.warning(
                    self, "Duplicate Name", f"Animation '{anim_name}' already exists."
                )
                return

            previous_sprite_data = deepcopy(self.sprite_data)
            add_animation(self.sprite_data, anim_name)

            self.anim_list_widget.blockSignals(True)
            self.anim_list_widget.addItem(anim_name)
            new_row = self.anim_list_widget.count() - 1
            self.anim_list_widget.setCurrentRow(new_row)  # Select the new one
            self.anim_list_widget.blockSignals(False)

            # Manually trigger updates since selection happened while blocked
            self._on_current_anim_changed(self.anim_list_widget.item(new_row), None)
            self._reload_edit_assets()
            self.save(label="Add animation", previous_state=previous_sprite_data)
            # If requested, auto-generate AI frames after adding animation
            try:
                frame_count = ai_frames_spin.value()
            except Exception:
                frame_count = 0
            for _ in range(frame_count):
                self._add_ai_generated_frame_after()
            print(f"Added animation: {anim_name} with {frame_count} AI-generated frame(s)")

    def _on_add_animation_with_ai_action(self, line_edit: QLineEdit):
        """Handle AI suggestion for a new animation name: fill the dialog box."""
        sprite_data = self.sprite_data
        sage_file = self.sage_file
        if sprite_data is None or sage_file is None:
            return

        sprite_description = self.desc_edit.toPlainText().strip()
        if not sprite_description:
            QMessageBox.warning(
                self,
                "Missing Description",
                "The sprite description cannot be empty to use the AI suggestion feature.\n\nPlease provide a description before generating.",
            )
            print("AI suggestion aborted: Sprite description is empty.")
            return
        ai_manager = AIModelManager()
        current_names = list(sprite_data.animations.keys())
        suggestion = self._call_ai(
            ai_manager,
            lambda: ai_manager.generate_sprite_animation_suggestion(
                input=GenerateSpriteAnimationSuggestion(
                    output_folder=sage_file.directory,
                    animation_names=current_names,
                    sprite_description=sprite_description,
                    project_description=sage_file.project_description,
                    keywords=sage_file.keywords,
                )
            ),
            "Generating animation suggestion",
        )
        if suggestion:
            suggestion = suggestion.strip().strip("_")
            line_edit.setText(suggestion)
            print(f"AI suggested animation: {suggestion}")
        else:
            QMessageBox.warning(
                self, "AI Suggestion Failed", "Could not generate animation name suggestion."
            )
            print(
                "No animation name returned from AIModelManager.generate_sprite_animation_suggestion()"
            )

    def _remove_animation(self):
        current_item = self.anim_list_widget.currentItem()
        if not current_item or not self.current_file_path or self.sprite_data is None:
            return
        anim_name = current_item.text()
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove the animation '{anim_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            row_to_remove = self.anim_list_widget.row(current_item)
            previous_sprite_data = deepcopy(self.sprite_data)
            removed = remove_animation(self.sprite_data, anim_name)
            if not removed:
                return
            # taking item triggers currentItemChanged -> _on_current_anim_changed -> _update_frame_button_states
            self.anim_list_widget.takeItem(row_to_remove)
            self._reload_edit_assets()
            self.save(label="Remove animation", previous_state=previous_sprite_data)
            print(f"Removed animation: {anim_name}")
            # Note: Button states update automatically via the signal chain

    def _insert_frames_at_index(self, file_paths: list[str], insertion_index: int):
        """
        Copy each file in file_paths into the sprite directory if needed,
        then insert its absolute path into the current animation at insertion_index.
        """
        anim_item = self.anim_list_widget.currentItem()
        base_dir = self._base_dir
        sprite_data = self.sprite_data
        if not anim_item or not base_dir or sprite_data is None:
            return
        anim_name = anim_item.text()

        previous_sprite_data = deepcopy(sprite_data)
        paths_to_insert: list[str] = []

        for fpath in file_paths:
            try:
                copy_plan = plan_frame_copy(fpath, base_dir)
                if copy_plan.requires_copy:
                    shutil.copy2(copy_plan.source_path, copy_plan.stored_path)
            except Exception as e:
                QMessageBox.critical(self, "Copy Error", f"Failed to copy frame file:\n{e}")
                continue

            paths_to_insert.append(copy_plan.stored_path)

        added = insert_frames(sprite_data, anim_name, insertion_index, paths_to_insert)
        # Reflect changes in the QListWidget
        for frame in added:
            self.frame_list_widget.insertItem(frame.index, self._make_frame_item(frame.path))

        added_paths = {frame.path for frame in added}
        for skipped_path in [path for path in paths_to_insert if path not in added_paths]:
            print(f"Skipping duplicate frame: {skipped_path}")

        if added:
            with QtCore.QSignalBlocker(self.frame_list_widget):
                self.frame_list_widget.setCurrentRow(added[0].index)
            self._update_animation_preview()
            self._reload_edit_assets()
            self._update_frame_button_states()
            label = "Add frame" if len(added) == 1 else "Add frames"
            self.save(label=label, previous_state=previous_sprite_data)
            print(f"Inserted {len(added)} frame(s) into '{anim_name}' at index {added[0].index}")

    def _add_frame_at_index(self, insertion_index: int, file_paths: list[str] | None = None):
        # If no paths provided, pop up the file selector:
        if file_paths is None:
            anim_item = self.anim_list_widget.currentItem()
            base_dir = self._base_dir
            if anim_item is None or base_dir is None:
                return
            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                f"Select Frame(s) for '{anim_item.text()}'",
                base_dir,
                "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tiff)",
            )
            if not file_paths:
                return
        # Delegate to the common inserter:
        self._insert_frames_at_index(file_paths, insertion_index)

    def _add_ai_generated_frame_before(self):
        sprite_data = self.sprite_data
        sage_file = self.sage_file
        if sprite_data is None or sage_file is None:
            return

        if self.frame_list_widget.currentItem():
            pos = self.frame_list_widget.currentRow()
        else:
            pos = 0

        ai_manager = AIModelManager()

        anim_item = self.anim_list_widget.currentItem()
        if not anim_item:
            print("No animation selected for _add_ai_generated_frame_before")
            return
        anim_name = anim_item.text()

        generation_plan = plan_ai_frame_before(sprite_data, anim_name, pos)
        if generation_plan.generation_kind == "next":
            new_image = self._call_ai(
                ai_manager,
                lambda: ai_manager.generate_next_sprite_image(
                    input=GenerateNextSpriteImageInput(
                        output_folder=sage_file.directory,
                        animation_name=anim_name,
                        image=generation_plan.images[0],
                        camera=sage_file.camera,
                    )
                ),
                "Generating next sprite image",
            )
        else:
            new_image = self._call_ai(
                ai_manager,
                lambda: ai_manager.generate_sprite_between_images(
                    input=GenerateSpriteBetweenImagesInput(
                        output_folder=sage_file.directory,
                        animation_name=anim_name,
                        images=list(generation_plan.images),
                        camera=sage_file.camera,
                    )
                ),
                "Generating sprite between images",
            )
        if not new_image:
            print("Failed to generate new image for _add_ai_generated_frame_before")
            return

        self._add_frame_at_index(generation_plan.insertion_index, [new_image])

    def _add_ai_generated_frame_after(self):
        sprite_data = self.sprite_data
        sage_file = self.sage_file
        if sprite_data is None or sage_file is None:
            return

        # Use currentIndex for generation logic…
        if self.frame_list_widget.currentItem():
            current_index = self.frame_list_widget.currentRow()
        else:
            current_index = 0

        ai_manager = AIModelManager()

        anim_item = self.anim_list_widget.currentItem()
        if not anim_item:
            print("No animation selected for _add_ai_generated_frame_after")
            return
        anim_name = anim_item.text()

        generation_plan = plan_ai_frame_after(sprite_data, anim_name, current_index)
        if generation_plan.generation_kind == "next":
            new_image = self._call_ai(
                ai_manager,
                lambda: ai_manager.generate_next_sprite_image(
                    input=GenerateNextSpriteImageInput(
                        output_folder=sage_file.directory,
                        animation_name=anim_name,
                        image=generation_plan.images[0],
                        camera=sage_file.camera,
                    )
                ),
                "Generating next sprite image",
            )
        else:
            new_image = self._call_ai(
                ai_manager,
                lambda: ai_manager.generate_sprite_between_images(
                    input=GenerateSpriteBetweenImagesInput(
                        output_folder=sage_file.directory,
                        animation_name=anim_name,
                        images=list(generation_plan.images),
                        camera=sage_file.camera,
                    )
                ),
                "Generating sprite between images",
            )
        if not new_image:
            print("Failed to generate new image for _add_ai_generated_frame_after")
            return

        self._add_frame_at_index(generation_plan.insertion_index, [new_image])

    def _add_frame_before(self):
        if self.frame_list_widget.currentItem():
            pos = self.frame_list_widget.currentRow()
        else:
            pos = 0
        self._add_frame_at_index(pos)

    def _add_frame_after(self):
        if self.frame_list_widget.currentItem():
            pos = self.frame_list_widget.currentRow() + 1
        else:
            pos = self.frame_list_widget.count()
        self._add_frame_at_index(pos)

    def _reload_current_frame_list(self, selected_row: int | None = None):
        current_anim_item = self.anim_list_widget.currentItem()
        sprite_data = self.sprite_data
        if current_anim_item is None or sprite_data is None:
            return

        frames = sprite_data.get_animation_frames(animation_name=current_anim_item.text())
        self.frame_list_widget.blockSignals(True)
        self.frame_list_widget.clear()
        self._add_frame_items(frames)
        if frames:
            row = 0 if selected_row is None else selected_row
            self.frame_list_widget.setCurrentRow(max(0, min(row, len(frames) - 1)))
        self.frame_list_widget.blockSignals(False)

    def _duplicate_frame(self):
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_item = self.frame_list_widget.currentItem()
        sprite_data = self.sprite_data
        if (
            not current_anim_item
            or not current_frame_item
            or not self.current_file_path
            or sprite_data is None
        ):
            return

        source_path = self._frame_path_from_item(current_frame_item)
        if not os.path.exists(source_path):
            QMessageBox.warning(
                self,
                "Duplicate Frame",
                f"Selected frame file could not be found:\n{source_path}",
            )
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.row(current_frame_item)
        previous_sprite_data = deepcopy(sprite_data)
        try:
            copy_plan = plan_frame_duplicate(source_path)
            shutil.copy2(copy_plan.source_path, copy_plan.stored_path)
            duplicated = duplicate_frame(
                sprite_data,
                anim_name,
                current_row,
                copy_plan.stored_path,
            )
        except Exception as e:
            QMessageBox.critical(self, "Duplicate Frame", f"Failed to duplicate frame:\n{e}")
            return

        if duplicated is None:
            print("Warning: No matching frame found internally for duplication.")
            return

        self.frame_list_widget.insertItem(duplicated.index, self._make_frame_item(duplicated.path))
        self.frame_list_widget.setCurrentRow(duplicated.index)
        self._update_animation_preview()
        self._reload_edit_assets()
        self._update_frame_button_states()
        self.save(label="Duplicate frame", previous_state=previous_sprite_data)
        print(f"Duplicated frame in '{anim_name}' at index {duplicated.index}")

    def _reverse_frames(self):
        current_anim_item = self.anim_list_widget.currentItem()
        sprite_data = self.sprite_data
        if not current_anim_item or not self.current_file_path or sprite_data is None:
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.currentRow()
        frame_count = self.frame_list_widget.count()
        previous_sprite_data = deepcopy(sprite_data)
        if not reverse_animation_frames(sprite_data, anim_name):
            return

        selected_row = frame_count - 1 - current_row if current_row >= 0 else 0
        self._reload_current_frame_list(selected_row)
        self._update_animation_preview()
        self._reload_edit_assets()
        self._update_frame_button_states()
        self.save(label="Reverse frames", previous_state=previous_sprite_data)
        print(f"Reversed frame order for '{anim_name}'")

    def _make_ping_pong_loop(self):
        current_anim_item = self.anim_list_widget.currentItem()
        sprite_data = self.sprite_data
        if not current_anim_item or not self.current_file_path or sprite_data is None:
            return

        anim_name = current_anim_item.text()
        selected_row = self.frame_list_widget.currentRow()
        previous_sprite_data = deepcopy(sprite_data)
        inserted = make_ping_pong_loop(sprite_data, anim_name)
        if not inserted:
            return

        self._reload_current_frame_list(selected_row)
        self._update_animation_preview()
        self._reload_edit_assets()
        self._update_frame_button_states()
        self.save(label="Create ping-pong loop", previous_state=previous_sprite_data)
        print(f"Added {len(inserted)} ping-pong frame(s) to '{anim_name}'")

    def _remove_frame(self):
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_items = self.frame_list_widget.selectedItems()
        sprite_data = self.sprite_data
        if (
            not current_anim_item
            or not current_frame_items
            or not self.current_file_path
            or sprite_data is None
        ):
            return

        anim_name = current_anim_item.text()
        rows_to_remove = sorted(
            [self.frame_list_widget.row(item) for item in current_frame_items], reverse=True
        )

        if anim_name in sprite_data.animations:
            previous_sprite_data = deepcopy(sprite_data)
            removed_count = remove_frame_indices(sprite_data, anim_name, rows_to_remove)

            if removed_count == 0:
                print("Warning: No matching frames found internally for removal.")
                return

            for row in rows_to_remove:
                self.frame_list_widget.takeItem(row)
            self._update_animation_preview()
            self._reload_edit_assets()
            label = "Remove frame" if removed_count == 1 else "Remove frames"
            self.save(label=label, previous_state=previous_sprite_data)
            self._update_frame_button_states()  # Update states after removal
            print(f"Removed {removed_count} frame(s) from: {anim_name}")
        else:
            print(f"Warning: Animation '{anim_name}' not found internally.")

    def _move_frame_up(self):
        """Moves the selected frame one position up in the list."""
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_item = self.frame_list_widget.currentItem()
        sprite_data = self.sprite_data

        if (
            not current_anim_item
            or not current_frame_item
            or not self.current_file_path
            or sprite_data is None
        ):
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.row(current_frame_item)

        if current_row > 0:  # Can move up
            # 1. Update Data Source First
            previous_sprite_data = deepcopy(sprite_data)
            new_row = move_frame(sprite_data, anim_name, current_row, -1)
            if new_row is not None:
                # 2. Update UI
                self.frame_list_widget.blockSignals(True)
                item = self.frame_list_widget.takeItem(current_row)
                self.frame_list_widget.insertItem(new_row, item)
                self.frame_list_widget.setCurrentRow(new_row)
                self.frame_list_widget.blockSignals(False)

                # 3. Mark Modified and Update Preview/Buttons
                self.save(label="Move frame", previous_state=previous_sprite_data)
                self._update_animation_preview()
                self._reload_edit_assets()
                self._update_frame_button_states()
                print(f"Moved frame up in '{anim_name}' to index {new_row}")
            else:
                print("Error: Frame list/data mismatch during move up.")

    def _move_frame_down(self):
        """Moves the selected frame one position down in the list."""
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_item = self.frame_list_widget.currentItem()
        sprite_data = self.sprite_data

        if (
            not current_anim_item
            or not current_frame_item
            or not self.current_file_path
            or sprite_data is None
        ):
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.row(current_frame_item)
        frame_count = self.frame_list_widget.count()

        if current_row < frame_count - 1:  # Can move down
            # 1. Update Data Source First
            previous_sprite_data = deepcopy(sprite_data)
            new_row = move_frame(sprite_data, anim_name, current_row, 1)
            if new_row is not None:
                # 2. Update UI
                self.frame_list_widget.blockSignals(True)
                item = self.frame_list_widget.takeItem(current_row)
                self.frame_list_widget.insertItem(new_row, item)
                self.frame_list_widget.setCurrentRow(new_row)
                self.frame_list_widget.blockSignals(False)

                # 3. Mark Modified and Update Preview/Buttons
                self.save(label="Move frame", previous_state=previous_sprite_data)
                self._update_animation_preview()
                self._reload_edit_assets()
                self._update_frame_button_states()
                print(f"Moved frame down in '{anim_name}' to index {new_row}")
            else:
                print("Error: Frame list/data mismatch during move down.")
