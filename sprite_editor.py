"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import shutil
from copy import deepcopy
from typing import Optional
from PySide6 import QtWidgets, QtCore, QtWidgets, QtCore
from PySide6.QtWidgets import (
    QMessageBox, QStyle, QFileDialog, QListWidgetItem,
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QDialog, QHBoxLayout, QLineEdit, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap

from image_loader import ImageLoaderWidget, ActionIconButton
from inference import (
    AIModelManager,
    GenerateBaseSpriteImageInput,
    GenerateSpriteAnimationSuggestion,
    GenerateNextSpriteImageInput,
    GenerateSpriteBetweenImagesInput,
)
from sprite_file import SpriteFile, Animation
from sage_editor import SageFile
from utils import call_with_busy, UndoRedoManager


class AnimationPreviewWidget(QWidget):
    """Displays an animated sequence of frames."""
    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.pixmaps = []
        self.current_frame_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self._base_dir = None
        self.frame_delay_ms = 500  # Default: 10 FPS (100 ms per frame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QLabel("No animation selected")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(128, 128)  # Ensure a minimum size
        self.image_label.setAutoFillBackground(True)
        layout.addWidget(self.image_label)

    def set_frame_delay(self, ms: int):
        if ms <= 0:
            ms = 100
        self.frame_delay_ms = ms
        if self.timer.isActive():
            self.timer.start(self.frame_delay_ms)

    def load_animation(self, frame_paths: list[str], base_dir: str):
        """
        Load a sequence of image files (absolute or relative paths) into the preview.
        """
        self.timer.stop()
        self.pixmaps.clear()
        self.current_frame_index = 0
        self._base_dir = base_dir
        self.image_label.setText("Loading...")

        if not base_dir or not os.path.isdir(base_dir):
            print(f"AnimationPreviewWidget Error: Invalid base directory '{base_dir}'")
            self.image_label.setText("Error:\nInvalid base path")
            return

        if not frame_paths:
            self.image_label.setText("Animation has\nno frames")
            return

        loaded_count = 0
        # Scale target to 95% of label size (with a floor)
        target_size = self.image_label.size() * 0.95
        if target_size.width() < 32 or target_size.height() < 32:
            target_size = QSize(120, 120)

        for frame_path in frame_paths:
            # Use absolute if provided, else join with base_dir
            if os.path.isabs(frame_path):
                full_path = frame_path
            else:
                full_path = os.path.normpath(os.path.join(self._base_dir, frame_path))

            if os.path.exists(full_path):
                pixmap = QPixmap(full_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        target_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.pixmaps.append(scaled)
                    loaded_count += 1
                else:
                    print(f"AnimationPreviewWidget Warning: Could not load image: {full_path}")
            else:
                print(f"AnimationPreviewWidget Warning: Frame image not found: {full_path}")

        if not self.pixmaps:
            self.image_label.setText(f"Error:\nCould not load\nany frames\n(Found {len(frame_paths)})")
            return

        print(f"AnimationPreviewWidget: Loaded {loaded_count}/{len(frame_paths)} frames.")
        self.image_label.setPixmap(self.pixmaps[0])
        if len(self.pixmaps) > 1:
            self.image_label.setText("")
            self.timer.start(self.frame_delay_ms)
        else:
            self.image_label.setText("")
            self.image_label.setPixmap(self.pixmaps[0])

    def _next_frame(self):
        if not self.pixmaps:
            self.timer.stop()
            return
        self.current_frame_index = (self.current_frame_index + 1) % len(self.pixmaps)
        if self.current_frame_index < len(self.pixmaps):
            self.image_label.setPixmap(self.pixmaps[self.current_frame_index])
        else:
            print("AnimationPreviewWidget Error: Invalid frame index.")
            self.timer.stop()
            self.clear_preview()

    def clear_preview(self):
        self.timer.stop()
        self.pixmaps.clear()
        self.current_frame_index = 0
        self.image_label.setText("No animation selected")
        self.image_label.setPixmap(QPixmap())

# --- Modified SpriteEditorView ---
class SpriteEditorView(QtWidgets.QWidget):
    return_to_sage = QtCore.Signal(str)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.current_file_path = None
        self.sprite_data: Optional[SpriteFile] = None
        self._base_dir = None
        self._undo_redo_manager = UndoRedoManager[SpriteFile]()
        self.sage_file: Optional[SageFile] = None

        # --- UI Setup ---
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(8)

        # --- Form Layout for Basic Properties ---
        self.form_layout = QtWidgets.QFormLayout()
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setSpacing(5)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Return to project button on its own first row
        back_button = QPushButton()
        back_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        back_button.setToolTip("Return To Project")
        back_button.setFixedSize(back_button.sizeHint())
        back_button.clicked.connect(lambda: self.return_to_sage.emit(self.sage_file.filepath))
        self.form_layout.addRow("Return to project", back_button)

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
        self.base_image_loader = ImageLoaderWidget(base_dir=None, palette=self.palette, index=0)
        self.form_layout.addRow("Base Image:", self.base_image_loader)
        self.base_image_loader.action_clicked.connect(self._on_base_image_action_clicked)
        self.main_layout.addLayout(self.form_layout)

        # --- Animations Section ---
        self.animations_group = QtWidgets.QGroupBox("Animations")
        self.animations_layout = QtWidgets.QHBoxLayout(self.animations_group)
        self.animations_layout.setContentsMargins(5, 5, 5, 5)
        self.animations_layout.setSpacing(5)

        # Left side: Animation List and Controls
        anim_list_layout = QtWidgets.QVBoxLayout()
        anim_list_layout.setSpacing(3)
        self.anim_list_widget = QtWidgets.QListWidget()
        self.anim_list_widget.setToolTip("List of available animations")
        anim_button_layout = QtWidgets.QHBoxLayout()
        self.add_anim_button = QPushButton("Add Anim")
        self.remove_anim_button = QPushButton("Remove Anim")
        anim_button_layout.addWidget(self.add_anim_button)
        anim_button_layout.addWidget(self.remove_anim_button)
        anim_button_layout.addStretch()
        anim_list_layout.addWidget(self.anim_list_widget)
        anim_list_layout.addLayout(anim_button_layout)

        # Middle: Frame List and Controls
        frame_list_layout = QtWidgets.QVBoxLayout()
        frame_list_layout.setSpacing(3)
        self.frame_list_widget = QtWidgets.QListWidget()
        self.frame_list_widget.setToolTip("Image frames for the selected animation")

        frame_button_layout = QtWidgets.QHBoxLayout()
        # --- MODIFIED: Replace single Add Frame button with two new ones ---
        self.add_frame_before_icon = ActionIconButton(self.palette, "add_frame_before", tooltip="Add Frame Before (Icon)")
        self.add_frame_after_icon = ActionIconButton(self.palette, "add_frame_after", tooltip="Add Frame After (Icon)")
        self.add_frame_before_icon.clicked_with_action.connect(self._add_ai_generated_frame_before)
        self.add_frame_after_icon.clicked_with_action.connect(self._add_ai_generated_frame_after)

        self.add_frame_before_button = QPushButton("Add Frame Before")
        self.add_frame_after_button = QPushButton("Add Frame After"
                                                  )
        self.remove_frame_button = QPushButton("Remove Frame")
        # --- NEW: Move Buttons ---
        style = self.style()  # Or QtWidgets.QApplication.style()
        self.move_frame_up_button = QPushButton()
        self.move_frame_up_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.move_frame_up_button.setToolTip("Move selected frame up")
        self.move_frame_down_button = QPushButton()
        self.move_frame_down_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.move_frame_down_button.setToolTip("Move selected frame down")

        # Arrange the new buttons in the layout
        frame_button_layout.addWidget(self.add_frame_before_icon)
        frame_button_layout.addWidget(self.add_frame_before_button)
        frame_button_layout.addWidget(self.add_frame_after_icon)
        frame_button_layout.addWidget(self.add_frame_after_button)
        frame_button_layout.addWidget(self.remove_frame_button)
        frame_button_layout.addSpacing(10)  # Spacer between add/remove and move
        frame_button_layout.addWidget(self.move_frame_up_button)
        frame_button_layout.addWidget(self.move_frame_down_button)
        frame_button_layout.addStretch()

        frame_list_layout.addWidget(self.frame_list_widget)
        frame_list_layout.addLayout(frame_button_layout)

        # Right side: Animation Preview
        self.animation_preview = AnimationPreviewWidget(self.palette)

        # Add layouts and widget to the main animations layout
        self.animations_layout.addLayout(anim_list_layout, 1)
        self.animations_layout.addLayout(frame_list_layout, 2)
        self.animations_layout.addWidget(self.animation_preview, 1)

        self.main_layout.addWidget(self.animations_group)
        self.main_layout.addStretch()

        # --- Connect Signals ---
        self.base_image_loader.image_updated.connect(self._on_base_image_selected)

        # Animation/Frame button signals
        self.add_anim_button.clicked.connect(self._add_animation)
        self.remove_anim_button.clicked.connect(self._remove_animation)
        # --- NEW: Connect new Add Frame buttons to their respective functions ---
        self.add_frame_before_button.clicked.connect(self._add_frame_before)
        self.add_frame_after_button.clicked.connect(self._add_frame_after)
        self.remove_frame_button.clicked.connect(self._remove_frame)
        # --- NEW: Move Button Signals ---
        self.move_frame_up_button.clicked.connect(self._move_frame_up)
        self.move_frame_down_button.clicked.connect(self._move_frame_down)

        # List signals
        self.anim_list_widget.currentItemChanged.connect(self._on_current_anim_changed)

        # also catch clicks on the same item so we can restart playback
        self.anim_list_widget.itemClicked.connect(self._on_anim_clicked)

        # Update frame buttons … and also show static frame on frame‐click
        self.frame_list_widget.currentItemChanged.connect(self._update_frame_button_states)
        self.frame_list_widget.currentItemChanged.connect(self._on_current_frame_changed)

        self.name_edit.textChanged.connect(lambda: self.save())
        self.desc_edit.textChanged.connect(lambda: self.save())
        self.width_spin.valueChanged.connect(lambda: self.save())
        self.height_spin.valueChanged.connect(lambda: self.save())

        # Initially disable controls
        self._set_animation_controls_enabled(False)
        self._apply_styles()

    def _on_base_image_selected(self, path: str):
        """Handle when the user selects a new base image manually."""
        if not path:
            return
        if not os.path.isabs(path):
            # If path is not absolute, make it absolute relative to base_dir
            path = os.path.abspath(os.path.join(self._base_dir, path))
        print(f"User selected base image (absolute path): {path}")
        self.sprite_data.base_image = path
        self.save()

    def _on_base_image_action_clicked(self, index: int):
        sprite_description = self.desc_edit.toPlainText().strip() # Get text and remove leading/trailing whitespace
        if not sprite_description:
            # Show an alert message box
            QMessageBox.warning(
                self,
                "Missing Description",
                "The sprite description cannot be empty to use the AI image generation feature.\n\nPlease provide a description before generating."
            )
            print("AI generation aborted: Sprite description is empty.")
            return # Stop processing the rest of the function

        ai_manager = AIModelManager()
        # Generate the new base sprite image.
        new_image = call_with_busy(
            self,
            lambda: ai_manager.generate_base_sprite_image(
                input=GenerateBaseSpriteImageInput(
                    output_folder=self.sage_file.directory,
                    sprite_description=sprite_description,
                    project_description=self.sage_file.project_description,
                    camera=self.sage_file.camera,
                    keywords=self.sage_file.keywords,
                    images=self.sage_file.reference_image_abs_paths(),
                )
            ),
            message=f"Generating base sprite image with {ai_manager.get_active_vendor().value}",
        )
        
        if new_image is not None:
            self.sprite_data.base_image = new_image
            # Update the base image loader to show the newly generated image.
            self.base_image_loader.load_image(new_image)
            print(f"Base image updated to: {new_image}")
            
            self.save()
        else:
            print("No image returned from AIModelManager.generate_base_sprite_image()")
        
        print(f"ImageLoaderWidget at index {index} triggered AIModelManager.generate_base_sprite_image().")

    def _set_animation_controls_enabled(self, enabled: bool):
        """Enable/disable animation controls. Frame controls depend on selections."""
        self.add_anim_button.setEnabled(enabled)
        # Other buttons depend on selection, handled by _update_frame_button_states
        self.anim_list_widget.setEnabled(enabled)
        self.frame_list_widget.setEnabled(enabled)

        # If disabling all, also disable frame-specific buttons
        if not enabled:
            self.remove_anim_button.setEnabled(False)
            self.add_frame_before_button.setEnabled(False)
            self.add_frame_after_button.setEnabled(False)
            self.remove_frame_button.setEnabled(False)
            self.move_frame_up_button.setEnabled(False)
            self.move_frame_down_button.setEnabled(False)
        else:
            # If enabling, update based on current state
            self._update_frame_button_states()  # Update all buttons based on selection

    def _on_current_frame_changed(self, current_item, previous_item):
        """When a frame is clicked, stop playback and show only that frame."""
        if self.frame_list_widget.signalsBlocked() or not current_item:
            return
        # compute pixmap index (base image at 0 if present)
        has_base = bool(self.sprite_data.base_image is not None)
        frame_idx = self.frame_list_widget.row(current_item)
        pixmap_idx = frame_idx + (1 if has_base else 0)
        pm_list = self.animation_preview.pixmaps
        if 0 <= pixmap_idx < len(pm_list):
            # stop any running animation
            self.animation_preview.timer.stop()
            self.animation_preview.current_frame_index = pixmap_idx
            self.animation_preview.image_label.setPixmap(pm_list[pixmap_idx])

    def _on_anim_clicked(self, item):
        """Restart playback if the user clicks the already-selected animation."""
        # only do this if we’re not in a blocked state
        if self.anim_list_widget.signalsBlocked():
            return
        # if it’s the same current item, reload preview (which restarts timer)
        if item is self.anim_list_widget.currentItem():
            self._update_animation_preview()

    def _get_sprite_data_to_save(self) -> SpriteFile:
        current_sprite_data = deepcopy(self.sprite_data)
        current_sprite_data.name = self.name_edit.text()
        current_sprite_data.description = self.desc_edit.toPlainText()
        current_sprite_data.width = self.width_spin.value()
        current_sprite_data.height = self.height_spin.value()
        current_sprite_data.base_image = self.base_image_loader.get_absolute_path()
        return current_sprite_data

    def save(self):
        if not self.current_file_path or not self.sprite_data or not self.sage_file:
            return None

        current_sprite_data = self._get_sprite_data_to_save()
        self._undo_redo_manager.save_undo_state(self.sprite_data)
        current_sprite_data.save(fpath=self.current_file_path, sage_directory=self.sage_file.directory)
        self.sprite_data = current_sprite_data

    def undo(self):
        undo_sprite_file = self._undo_redo_manager.perform_undo(current_state=self._get_sprite_data_to_save())
        if undo_sprite_file:
            undo_sprite_file.save(fpath=self.current_file_path, sage_directory=self.sage_file.directory)
            self.load_sprite_data(file_path=self.current_file_path, sage_file=self.sage_file)

    def redo(self):
        redo_sprite_file = self._undo_redo_manager.perform_redo()
        if redo_sprite_file:
            redo_sprite_file.save(fpath=self.current_file_path, sage_directory=self.sage_file.directory)
            self.load_sprite_data(file_path=self.current_file_path, sage_file=self.sage_file)

    def _apply_styles(self):
        """Apply palette colors to UI elements."""
        bg_color = self.palette.get('widget_bg', '#333333')
        text_color = self.palette.get('text_color', '#D3D3D3')
        label_color = self.palette.get('label_color', '#A0A0A0')
        border_color = self.palette.get('border', '#555555')
        button_bg = self.palette.get('button_bg', '#555555')
        button_fg = self.palette.get('button_fg', '#D3D3D3')
        input_bg = self.palette.get('input_bg', '#444444')

        # Reduce padding slightly for icon buttons
        move_button_padding = "2px"  # Adjust as needed
        general_button_padding = "4px 8px"

        self.setStyleSheet(f"""
            QWidget {{ background-color: {bg_color}; color: {text_color}; }}
            QLabel {{ color: {label_color}; padding-top: 3px; }}
            QLineEdit, QPlainTextEdit, QSpinBox {{
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
                alternate-background-color: {self.palette.get('list_alt_bg', '#3A3A3A')};
            }}
             QListWidget::item:selected {{
                 background-color: {self.palette.get('list_selection_bg', '#5A9')};
                 color: {self.palette.get('list_selection_fg', '#FFF')};
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
            /* Style specifically for the move buttons if needed */
            QPushButton#MoveUpButton, QPushButton#MoveDownButton {{
                 padding: {move_button_padding};
                 min-width: 24px; /* Ensure enough space for icon */
            }}
        """)
        # Set object names for specific styling (optional)
        self.move_frame_up_button.setObjectName("MoveUpButton")
        self.move_frame_down_button.setObjectName("MoveDownButton")

    def load_sprite_data(self, file_path: str, sage_file: SageFile):
        self.sage_file = sage_file

        if self.current_file_path and self.current_file_path != file_path:
            self._undo_redo_manager.clear()

        self.current_file_path = file_path
        self._base_dir = os.path.dirname(file_path)
        print(f"SpriteEditorView: Loading {file_path}")
        print(f"SpriteEditorView: Base directory set to {self._base_dir}")
        self._clear_ui()
        try:
            self.sprite_data = SpriteFile.from_json(fpath=file_path, sage_directory=self.sage_file.directory)
        except Exception as e:
            # ... (Error handling as before) ...
            QMessageBox.critical(self, "Error", f"Failed to load sprite: {e}")
            self.sprite_data = None
            self.current_file_path = None
            self._base_dir = None
            return

        self._block_signals(True)
        self.name_edit.setText(self.sprite_data.name)
        self.desc_edit.setPlainText(self.sprite_data.description)
        self.width_spin.setValue(self.sprite_data.width)
        self.height_spin.setValue(self.sprite_data.height)
        self.base_image_loader.base_dir = self._base_dir
        base_image_path = self.sprite_data.base_image
        self.base_image_loader.load_image(base_image_path)

        animations = self.sprite_data.animations

        for anim_name in sorted(animations.keys()):
            self.anim_list_widget.addItem(anim_name)

        # Auto-select first animation AFTER enabling controls and unblocking signals for anim list
        self._set_animation_controls_enabled(True)  # Enable controls (inc. lists)
        self.anim_list_widget.blockSignals(False)  # Unblock anim list signals
        if self.anim_list_widget.count() > 0:
            self.anim_list_widget.setCurrentRow(0)  # Select first item, triggers _on_current_anim_changed
        else:
            self.animation_preview.clear_preview()
            # Ensure button states are correct even with no anim selected
            self._update_frame_button_states()  # Update buttons (will disable frame buttons)

        self.anim_list_widget.blockSignals(True)  # Re-block anim list signals for safety
        self._block_signals(False)  # Unblock other signals (like frame list)

    def _clear_ui(self):
        self._block_signals(True)
        self.name_edit.clear()
        self.desc_edit.clear()
        self.width_spin.setValue(0)
        self.height_spin.setValue(0)
        self.base_image_loader.clear_image(emit_signal=False)
        self.anim_list_widget.clear()
        self.frame_list_widget.clear()
        self.animation_preview.clear_preview()
        self._block_signals(False)
        self._set_animation_controls_enabled(False)  # Disable controls, inc frame buttons

    def _block_signals(self, block: bool):
        self.name_edit.blockSignals(block)
        self.desc_edit.blockSignals(block)
        self.width_spin.blockSignals(block)
        self.height_spin.blockSignals(block)
        self.base_image_loader.blockSignals(block)
        self.anim_list_widget.blockSignals(block)
        # Frame list signals are only used for button state updates, okay to leave unblocked generally
        # self.frame_list_widget.blockSignals(block)

    def _on_current_anim_changed(self, current_item: QListWidgetItem | None, previous_item: QListWidgetItem | None):
        """Updates the frame list AND the animation preview when the selected animation changes."""
        if self.anim_list_widget.signalsBlocked():
            return

        print(f"Current anim changed. Selected: {current_item.text() if current_item else 'None'}")

        # Block frame list signals while clearing/populating to avoid unwanted triggers
        self.frame_list_widget.blockSignals(True)
        self.frame_list_widget.clear()
        if current_item:
            anim_name = current_item.text()
            frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
            self.frame_list_widget.addItems(frames)
            # Select the first frame by default if frames exist
            if self.frame_list_widget.count() > 0:
                self.frame_list_widget.setCurrentRow(0)
        self.frame_list_widget.blockSignals(False)

        # Update preview
        self._update_animation_preview()

        # Update button states now that frame list is populated/cleared
        self._update_frame_button_states()

    def _update_animation_preview(self):
        """Loads the selected animation into the preview pane."""
        current_item = self.anim_list_widget.currentItem()

        if current_item and self._base_dir:
            anim_name = current_item.text()
            # Get the *current* order from sprite_data
            frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
            base_img = self.sprite_data.base_image
            frame_paths = ([base_img] if base_img else []) + frames
            print(f"Updating preview for '{anim_name}' with {len(frame_paths)} frames (incl. base). Base dir: {self._base_dir}")
            QTimer.singleShot(0, lambda: self.animation_preview.load_animation(frame_paths, self._base_dir))
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

        # Frame buttons (now for both Add Frame Before/After)
        self.add_frame_before_button.setEnabled(anim_selected)
        self.add_frame_after_button.setEnabled(anim_selected)
        self.remove_frame_button.setEnabled(frame_selected)

        # Move buttons
        can_move_up = frame_selected and current_row > 0
        can_move_down = frame_selected and current_row < (frame_count - 1)
        self.move_frame_up_button.setEnabled(can_move_up)
        self.move_frame_down_button.setEnabled(can_move_down)

    # --- Animation Actions ---

    def _add_animation(self):
        if not self.current_file_path:
            return
        # Show dialog to get animation name with AI suggestion inline
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Animation")
        layout = QVBoxLayout(dialog)
        # Prompt
        label = QLabel("Enter Animation Name:")
        layout.addWidget(label)
        # Input row: text field + AI suggestion button
        input_row = QWidget(dialog)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(dialog)
        input_layout.addWidget(line_edit)
        # AI button: suggest name but do not auto-accept
        ai_btn = ActionIconButton(
            self.palette,
            "add_animation_with_ai",
            tooltip="Suggest an animation name with AI",
            parent=dialog
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
        if result == QDialog.Accepted:
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
                QMessageBox.warning(self, "Duplicate Name", f"Animation '{anim_name}' already exists.")
                return

            self.sprite_data.animations[anim_name] = Animation(name=anim_name, frames=[])

            self.anim_list_widget.blockSignals(True)
            self.anim_list_widget.addItem(anim_name)
            new_row = self.anim_list_widget.count() - 1
            self.anim_list_widget.setCurrentRow(new_row)  # Select the new one
            self.anim_list_widget.blockSignals(False)

            # Manually trigger updates since selection happened while blocked
            self._on_current_anim_changed(self.anim_list_widget.item(new_row), None)
            self.save()
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
        sprite_description = self.desc_edit.toPlainText().strip()
        if not sprite_description:
            QMessageBox.warning(
                self,
                "Missing Description",
                "The sprite description cannot be empty to use the AI suggestion feature.\n\nPlease provide a description before generating."
            )
            print("AI suggestion aborted: Sprite description is empty.")
            return
        ai_manager = AIModelManager()
        current_names = list(self.sprite_data.animations.keys())
        suggestion = call_with_busy(
            self,
            lambda: ai_manager.generate_sprite_animation_suggestion(
                input=GenerateSpriteAnimationSuggestion(
                    output_folder=self.sage_file.directory,
                    animation_names=current_names,
                    sprite_description=sprite_description,
                    project_description=self.sage_file.project_description,
                    keywords=self.sage_file.keywords
                )
            ),
            message=f"Generating animation suggestion with {ai_manager.get_active_vendor().value}",
        )
        if suggestion:
            suggestion = suggestion.strip().strip("_")
            line_edit.setText(suggestion)
            print(f"AI suggested animation: {suggestion}")
        else:
            QMessageBox.warning(
                self,
                "AI Suggestion Failed",
                "Could not generate animation name suggestion."
            )
            print("No animation name returned from AIModelManager.generate_sprite_animation_suggestion()")

    def _remove_animation(self):
        current_item = self.anim_list_widget.currentItem()
        if not current_item or not self.current_file_path:
            return
        anim_name = current_item.text()
        reply = QMessageBox.question(self, "Confirm Removal",
                                     f"Are you sure you want to remove the animation '{anim_name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            row_to_remove = self.anim_list_widget.row(current_item)
            if anim_name in self.sprite_data.animations:
                del self.sprite_data.animations[anim_name]
            # taking item triggers currentItemChanged -> _on_current_anim_changed -> _update_frame_button_states
            self.anim_list_widget.takeItem(row_to_remove)
            self.save()
            print(f"Removed animation: {anim_name}")
            # Note: Button states update automatically via the signal chain

    def _insert_frames_at_index(self, file_paths: list[str], insertion_index: int):
        """
        Copy each file in file_paths into the sprite directory if needed,
        then insert its absolute path into the current animation at insertion_index.
        """
        anim_item = self.anim_list_widget.currentItem()
        if not anim_item or not self._base_dir:
            return
        anim_name = anim_item.text()

        added = []  # list of (index, absolute_path)
        norm_basedir = os.path.normpath(self._base_dir)

        for fpath in file_paths:
            abs_input = os.path.abspath(fpath)
            try:
                # If input isn't already under base_dir, copy it there
                if not abs_input.startswith(norm_basedir + os.sep):
                    basename = os.path.basename(abs_input)
                    target = os.path.join(self._base_dir, basename)
                    name, ext = os.path.splitext(basename)
                    counter = 1
                    while os.path.exists(target):
                        target = os.path.join(self._base_dir, f"{name}_{counter}{ext}")
                        counter += 1
                    shutil.copy2(abs_input, target)
                    abs_input = os.path.normpath(target)
                # Now abs_input is the full path we want to store
                absolute_path = abs_input
            except Exception as e:
                QMessageBox.critical(self, "Copy Error", f"Failed to copy frame file:\n{e}")
                continue

            anim_dict = self.sprite_data.animations
            frame_list = anim_dict.setdefault(anim_name, Animation(name=anim_name, frames=[])).frames
            if absolute_path not in frame_list:
                frame_list.insert(insertion_index, absolute_path)
                added.append((insertion_index, absolute_path))
                insertion_index += 1
            else:
                print(f"Skipping duplicate frame: {absolute_path}")

        # Reflect changes in the QListWidget
        for idx, path in added:
            self.frame_list_widget.insertItem(idx, QListWidgetItem(path))

        if added:
            self._update_animation_preview()
            self._update_frame_button_states()
            self.save()
            print(f"Inserted {len(added)} frame(s) into '{anim_name}' at index {added[0][0]}")

    def _add_frame_at_index(self, insertion_index: int, file_paths: list[str] | None = None):
        # If no paths provided, pop up the file selector:
        if file_paths is None:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                f"Select Frame(s) for '{self.anim_list_widget.currentItem().text()}'",
                self._base_dir,
                "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tiff)"
            )
            if not file_paths:
                return
        # Delegate to the common inserter:
        self._insert_frames_at_index(file_paths, insertion_index)

    def _add_ai_generated_frame_before(self):
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

        frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
        num_frames = len(frames)

        if num_frames == 0:
            new_image = call_with_busy(
                self,
                lambda: ai_manager.generate_next_sprite_image(
                    input=GenerateNextSpriteImageInput(
                        output_folder=self.sage_file.directory,
                        animation_name=anim_name,
                        image=self.sprite_data.base_image,
                        camera=self.sage_file.camera,
                    )
                ),
                message=f"Generating next sprite image with {ai_manager.get_active_vendor().value}",
            )
        elif pos == 0:
            new_image = call_with_busy(
                self,
                lambda: ai_manager.generate_sprite_between_images(
                    input=GenerateSpriteBetweenImagesInput(
                        output_folder=self.sage_file.directory,
                        animation_name=anim_name,
                        images=[self.sprite_data.base_image, frames[pos]],
                        camera=self.sage_file.camera,
                    )
                ),
                message=f"Generating sprite between images with {ai_manager.get_active_vendor().value}",
            )
        else:
            new_image = call_with_busy(
                self,
                lambda: ai_manager.generate_sprite_between_images(
                    input=GenerateSpriteBetweenImagesInput(
                        output_folder=self.sage_file.directory,
                        animation_name=anim_name,
                        images=[frames[pos - 1], frames[pos]],
                        camera=self.sage_file.camera,
                    )
                ),
                message=f"Generating sprite between images with {ai_manager.get_active_vendor().value}",
            )
        if not new_image:
            print("Failed to generate new image for _add_ai_generated_frame_before")
            return

        self._add_frame_at_index(pos, [new_image])

    def _add_ai_generated_frame_after(self):
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

        frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
        num_frames = len(frames)

        if num_frames == 0:
            new_image = call_with_busy(
                self,
                lambda: ai_manager.generate_next_sprite_image(
                    input=GenerateNextSpriteImageInput(
                        output_folder=self.sage_file.directory,
                        animation_name=anim_name,
                        image=self.sprite_data.base_image,
                        camera=self.sage_file.camera,
                    )
                ),
                message=f"Generating next sprite image with {ai_manager.get_active_vendor().value}",
            )
        elif current_index == num_frames - 1:
            new_image = call_with_busy(
                self,
                lambda: ai_manager.generate_sprite_between_images(
                    input=GenerateSpriteBetweenImagesInput(
                        output_folder=self.sage_file.directory,
                        animation_name=anim_name,
                        images=[frames[current_index], self.sprite_data.base_image],
                        camera=self.sage_file.camera,
                    )
                ),
                message=f"Generating sprite between images with {ai_manager.get_active_vendor().value}",
            )
        else:
            new_image = call_with_busy(
                self,
                lambda: ai_manager.generate_sprite_between_images(
                    input=GenerateSpriteBetweenImagesInput(
                        output_folder=self.sage_file.directory,
                        animation_name=anim_name,
                        images=[frames[current_index], frames[current_index + 1]],
                        camera=self.sage_file.camera,
                    )
                ),
                message=f"Generating sprite between images with {ai_manager.get_active_vendor().value}",
            )
        if not new_image:
            print("Failed to generate new image for _add_ai_generated_frame_after")
            return

        # Insert *after* the selected frame (or at 0 if empty)
        if num_frames == 0:
            insertion_index = 0
        else:
            insertion_index = current_index + 1

        self._add_frame_at_index(insertion_index, [new_image])

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

    def _remove_frame(self):
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_items = self.frame_list_widget.selectedItems()
        if not current_anim_item or not current_frame_items or not self.current_file_path:
            return

        anim_name = current_anim_item.text()
        frames_to_remove = [item.text() for item in current_frame_items]
        rows_to_remove = sorted([self.frame_list_widget.row(item) for item in current_frame_items], reverse=True)

        removed_count = 0
        if anim_name in self.sprite_data.animations:
            current_frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
            new_frames = [f for f in current_frames if f not in frames_to_remove]
            removed_count = len(current_frames) - len(new_frames)

            if removed_count > 0:
                self.sprite_data.animations[anim_name].frames = new_frames
                for row in rows_to_remove:
                    self.frame_list_widget.takeItem(row)
                self._update_animation_preview()
                self.save()
                self._update_frame_button_states()  # Update states after removal
                print(f"Removed {removed_count} frame(s) from: {anim_name}")
            else:
                print("Warning: No matching frames found internally for removal.")
        else:
            print(f"Warning: Animation '{anim_name}' not found internally.")

    def _move_frame_up(self):
        """Moves the selected frame one position up in the list."""
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_item = self.frame_list_widget.currentItem()

        if not current_anim_item or not current_frame_item or not self.current_file_path:
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.row(current_frame_item)

        if current_row > 0:  # Can move up
            # 1. Update Data Source First
            frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
            if len(frames) > current_row:  # Sanity check
                frames.insert(current_row - 1, frames.pop(current_row))
                new_row = current_row - 1

                # 2. Update UI
                self.frame_list_widget.blockSignals(True)
                item = self.frame_list_widget.takeItem(current_row)
                self.frame_list_widget.insertItem(new_row, item)
                self.frame_list_widget.setCurrentRow(new_row)
                self.frame_list_widget.blockSignals(False)

                # 3. Mark Modified and Update Preview/Buttons
                self.save()
                self._update_animation_preview()
                self._update_frame_button_states()
                print(f"Moved frame up in '{anim_name}' to index {new_row}")
            else:
                print("Error: Frame list/data mismatch during move up.")

    def _move_frame_down(self):
        """Moves the selected frame one position down in the list."""
        current_anim_item = self.anim_list_widget.currentItem()
        current_frame_item = self.frame_list_widget.currentItem()

        if not current_anim_item or not current_frame_item or not self.current_file_path:
            return

        anim_name = current_anim_item.text()
        current_row = self.frame_list_widget.row(current_frame_item)
        frame_count = self.frame_list_widget.count()

        if current_row < frame_count - 1:  # Can move down
            # 1. Update Data Source First
            frames = self.sprite_data.get_animation_frames(animation_name=anim_name)
            if len(frames) > current_row + 1:  # Sanity check
                item_to_move = frames.pop(current_row)
                frames.insert(current_row + 1, item_to_move)
                new_row = current_row + 1

                # 2. Update UI
                self.frame_list_widget.blockSignals(True)
                item = self.frame_list_widget.takeItem(current_row)
                self.frame_list_widget.insertItem(new_row, item)
                self.frame_list_widget.setCurrentRow(new_row)
                self.frame_list_widget.blockSignals(False)

                # 3. Mark Modified and Update Preview/Buttons
                self.save()
                self._update_animation_preview()
                self._update_frame_button_states()
                print(f"Moved frame down in '{anim_name}' to index {new_row}")
            else:
                print("Error: Frame list/data mismatch during move down.")
