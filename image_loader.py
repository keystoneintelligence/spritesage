"""
SPDX-License-Identifier: GPL-3.0-only
Copyright © 2025 Keystone Intelligence LLC
Licensed under GPL v3 (see LICENSE file for details)
"""

import os
import shutil
from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtWidgets import QStyle, QMessageBox
from PySide6.QtCore import Qt

from config import ACTION_ICON_PATH


class ActionIconButton(QtWidgets.QPushButton):
    """
    A reusable QPushButton that automatically uses ACTION_ICON_PATH as its icon.
    It emits a signal with an action_string so that all such buttons can be handled
    by a single slot in a 'case statement' style.
    """
    clicked_with_action = QtCore.Signal(str)

    def __init__(self, palette, action_string, tooltip=None, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.action_string = action_string

        # Use the common icon for all "action" buttons
        # Use a standard icon if the path is invalid/placeholder
        icon = QtGui.QIcon(ACTION_ICON_PATH)
        if icon.isNull():
             # Fallback to a standard Qt icon if the custom one fails
             print(f"Warning: Could not load action icon from {ACTION_ICON_PATH}. Using fallback.")
             icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView) # Example fallback
        self.setIcon(icon)
        self.setFixedSize(24, 24)
        # Either use the provided tooltip or the action_string
        self.setToolTip(tooltip if tooltip else action_string)

        # Connect normal clicked signal to our custom signal with the action string
        self.clicked.connect(self._on_clicked)

        # Apply initial styling
        self._apply_styles()

    def _on_clicked(self):
        # Emit a signal that includes the action string
        self.clicked_with_action.emit(self.action_string)

    def _apply_styles(self):
        # Here, replicate any style that you want to use consistently for
        # all action-icon buttons. You may adapt from your existing style methods.
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.palette.get('button_bg', '#555555')};
                color: {self.palette.get('button_fg', '#D3D3D3')};
                border: 1px solid {self.palette.get('placeholder_border', '#555555')};
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: #6A6A6A;
                border: 1px solid #777777;
            }}
            QPushButton:pressed {{
                background-color: #4E4E4E;
            }}
        """)


# --- Custom Image Loader Widget (Generalized) ---
class ImageLoaderWidget(QtWidgets.QLabel):
    """
    A clickable label to load and display an image, handling file paths.
    Includes an overlay action button and a remove button.
    Does NOT depend on SageEditorView. Interactions are handled via signals.

    Signals:
        image_updated(str): Emitted when the image path changes (selected or cleared).
                            Provides the new relative path (or "" if cleared).
        action_clicked(int): Emitted when the overlay action button is clicked.
                             Provides the widget's index.
    """
    image_updated = QtCore.Signal(str)
    action_clicked = QtCore.Signal(int)

    _BUTTON_SIZE = 22 # Slightly smaller button for overlay
    _BUTTON_MARGIN = 3

    def __init__(self, base_dir, palette, index, parent=None):
        super().__init__(parent)
        # Ensure base_dir is usable, store absolute path
        self.base_dir = os.path.abspath(base_dir) if base_dir else None
        self.palette = palette
        self.index = index
        self.image_path = None # Relative path from base_dir
        self._absolute_path = None # Absolute path (derived)
        self._pixmap = None # Store the original pixmap for rescaling

        self.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(120, 120)
        self.setMaximumSize(120, 120)
        self.setToolTip("Click to select an image")

        # -- Action Button (Top-Left): use ActionIconButton now --
        self.action_button = ActionIconButton(
            palette=self.palette,
            action_string=f"IMAGE_OVERLAY_ACTION_{self.index}", # String might still be useful for caller filtering
            tooltip=f"Perform Action for Image {self.index + 1}", # Generic tooltip
            parent=self
        )
        # Connect to the internal handler that just emits action_clicked
        self.action_button.clicked_with_action.connect(self._on_action_button_clicked)
        self.action_button.show()

        # Remove Button (Top-Right)
        self.remove_button = QtWidgets.QPushButton(self)
        red_x_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
        self.remove_button.setIcon(red_x_icon)
        self.remove_button.setFixedSize(self._BUTTON_SIZE, self._BUTTON_SIZE)
        self.remove_button.setToolTip("Remove this image")
        self.remove_button.setStyleSheet("""
            QPushButton {
                background-color: #AA3333;
                color: white;
                border: 1px solid #AA3333;
                border-radius: 11px; /* half of _BUTTON_SIZE for a circular button */
                padding: 1px;
            }
            QPushButton:hover {
                background-color: #CC4444;
            }
            QPushButton:pressed {
                background-color: #882222;
            }
        """)
        self.remove_button.hide()
        self.remove_button.clicked.connect(self._on_remove_button_clicked)

        self._apply_styles()
        self.clear_image(emit_signal=False) # Don't emit signal on init

    def _update_button_positions(self):
        """Handles visibility and positioning of overlay buttons."""
        action_btn_x = self._BUTTON_MARGIN
        action_btn_y = self._BUTTON_MARGIN
        self.action_button.move(action_btn_x, action_btn_y)
        self.action_button.raise_()

        if self.image_path is not None:
            remove_btn_x = self.width() - self.remove_button.width() - self._BUTTON_MARGIN
            remove_btn_y = self._BUTTON_MARGIN
            if not self.remove_button.isVisible():
                self.remove_button.show()
            self.remove_button.move(remove_btn_x, remove_btn_y)
            self.remove_button.raise_()
        else:
            self.remove_button.hide()

    # RENAMED and SIMPLIFIED: No AI logic, just emit signal
    def _on_action_button_clicked(self, action_string: str):
        """Handles the action button click by emitting the action_clicked signal."""
        # The action_string is passed by ActionIconButton, but we mainly care about the index
        print(f"ImageLoaderWidget {self.index} action button clicked.")
        # Check if base_dir is valid before emitting, as the action likely needs it
        if not self.base_dir or not os.path.isdir(self.base_dir):
             QMessageBox.warning(self, "Error", f"Cannot perform action: Base directory is not set or invalid for image {self.index+1}.")
             return
        # Emit the signal with the index. The listener will handle the specific action.
        self.action_clicked.emit(self.index)

    def _apply_styles(self):
        # Styles remain largely the same
        if self._pixmap and not self._pixmap.isNull():
            border_style = "solid"
        else:
            border_style = "dashed"

        self.setStyleSheet(f"""
            ImageLoaderWidget {{
                background-color: {self.palette.get('image_loader_bg', '#3A3A3A')};
                border: 1px {border_style} {self.palette.get('image_loader_border', '#666666')};
                color: {self.palette.get('label_color', '#A0A0A0')};
                min-width: 120px;
                min-height: 120px;
                padding: 5px;
            }}
            ImageLoaderWidget:hover {{
                border: 1px {border_style} #FFFFFF;
            }}
        """)

    def load_image(self, relative_fpath: str | None):
        """
        Loads an image specified by a path relative to the base_dir.
        Updates the display and internal state. Does NOT emit image_updated signal.
        The caller should emit signals if needed after calling load_image.
        """
        if not relative_fpath or not self.base_dir:
            self.clear_image(emit_signal=False) # clear_image handles button hiding
            return

        # Normalize and compute absolute path
        relative_fpath = relative_fpath.replace("\\", "/") # Ensure consistent separators
        abs_path = os.path.abspath(os.path.join(self.base_dir, relative_fpath))

        if os.path.isfile(abs_path):
            loaded_pixmap = QtGui.QPixmap(abs_path)
            if not loaded_pixmap.isNull():
                self.image_path = relative_fpath
                self._absolute_path = abs_path
                self._pixmap = loaded_pixmap
                self._update_button_positions()
                self._display_pixmap()
                self.setToolTip(f"Image: {self.image_path}\nClick to change")
                self.setStyleSheet(self.styleSheet().replace("border: 1px dashed", "border: 1px solid"))
                self.setText("")
            else:
                # Invalid image file
                self.image_path = relative_fpath # Store the problematic path
                self._absolute_path = abs_path
                self._pixmap = None
                self._update_button_positions()
                self.setPixmap(QtGui.QPixmap())
                self.setText(f"Invalid\nImage\n({os.path.basename(relative_fpath)})")
                self.setToolTip(f"Failed to load image: {relative_fpath}\nExpected at: {abs_path}")
                print(f"Warning: Could not load image file: {abs_path}")
                self._apply_styles() # Reapply dashed border
        else:
            # File not found
            self.image_path = relative_fpath # Store the missing path
            self._absolute_path = abs_path
            self._pixmap = None
            self._update_button_positions()
            self.setPixmap(QtGui.QPixmap())
            self.setText(f"Image\nNot Found\n({os.path.basename(relative_fpath)})")
            self.setToolTip(f"Image file not found: {relative_fpath}\nExpected at: {abs_path}")
            print(f"Warning: Image file not found: {abs_path} (relative: {relative_fpath})")
            self._apply_styles() # Reapply dashed border


    def _display_pixmap(self):
        if self._pixmap and not self._pixmap.isNull():
            # Calculate available size inside border/padding (approximate)
            content_margin = 2 # Adjust as needed based on border/padding visual inspection
            available_size = self.size() - QtCore.QSize(content_margin * 2, content_margin * 2)
            if available_size.width() > 0 and available_size.height() > 0:
                 scaled_pixmap = self._pixmap.scaled(available_size,
                                                     Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)
                 self.setPixmap(scaled_pixmap)
            else:
                 self.setPixmap(QtGui.QPixmap()) # Clear if size is too small
        elif not self.image_path: # No image path set, ensure placeholder text is shown
             self.setPixmap(QtGui.QPixmap())
             self.setText(f"+ Add Image\n({self.index + 1})")
        # else: Keep existing text ("Not Found", "Invalid Image") if path is set but pixmap is null

    def get_relative_path(self, sage_dir: str) -> str | None:
        """Returns the currently stored relative image path."""
        return self._absolute_path if not self._absolute_path else os.path.relpath(self._absolute_path, sage_dir)

    def get_absolute_path(self) -> str | None:
        return self._absolute_path

    def clear_image(self, emit_signal=True):
        """Clears the image, resets state, and optionally emits image_updated."""
        previous_path = self.image_path
        self.image_path = None
        self._absolute_path = None
        self._pixmap = None
        self._update_button_positions()
        self.setPixmap(QtGui.QPixmap())
        self.setText(f"+ Add Image\n({self.index + 1})")
        self.setToolTip("Click to select an image")
        self._apply_styles() # Apply dashed border etc.

        # Emit signal only if the path actually changed and emit_signal is True
        if emit_signal and previous_path is not None:
            self.image_updated.emit("")

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        self._update_button_positions()
        self._display_pixmap() # Rescale pixmap on resize

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        buttons_to_check = [self.action_button]
        if self.remove_button.isVisible():
            buttons_to_check.append(self.remove_button)

        for button in buttons_to_check:
            if button.geometry().contains(event.pos()):
                # Let the button handle its own click event
                # Stop propagation to prevent triggering _select_image
                event.accept()
                # Let the button's click handler run normally
                super().mousePressEvent(event)
                return

        # If click is not on a button, proceed with image selection
        if event.button() == Qt.MouseButton.LeftButton:
            self._select_image()
            event.accept() # Indicate we handled this click
        else:
            super().mousePressEvent(event) # Handle other mouse buttons normally

    def _select_image(self):
        """Handles the file dialog for selecting an image."""
        if not self.base_dir or not os.path.isdir(self.base_dir):
            print("Error: Base directory for image selection is not set or invalid.")
            QMessageBox.warning(self, "Error", "Cannot select image: Project base directory is not valid.")
            return

        # Prefer starting in 'reference_images' if it exists within base_dir
        start_dir = os.path.join(self.base_dir, "reference_images")
        if not os.path.isdir(start_dir):
            start_dir = self.base_dir # Fallback to base_dir

        fpath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Reference Image", start_dir,
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tiff)"
        )

        if fpath:
            fpath = os.path.abspath(fpath)
            final_relative_path = None

            try:
                # Try to make path relative to base_dir
                relative_to_base = os.path.relpath(fpath, self.base_dir)
                # Check if the file is inside the base_dir hierarchy
                if not relative_to_base.startswith("..") and not os.path.isabs(relative_to_base):
                    final_relative_path = relative_to_base.replace("\\", "/")
                    print(f"Selected image is within base directory: '{final_relative_path}'")
                else:
                    # Path is outside, needs copying
                    pass # Handled below
            except ValueError:
                # Paths are on different drives (Windows), needs copying
                pass # Handled below

            if final_relative_path:
                 # Image is already within the project structure
                 self.load_image(final_relative_path)
                 self.image_updated.emit(self.image_path) # Emit the confirmed relative path
            else:
                 # Image is outside project or on different drive, copy it in
                 target_dir = os.path.join(self.base_dir, "reference_images")
                 try:
                     os.makedirs(target_dir, exist_ok=True)
                     base_filename = os.path.basename(fpath)
                     target_fpath = os.path.join(target_dir, base_filename)
                     counter = 1
                     # Ensure unique filename in target directory
                     name, ext = os.path.splitext(base_filename)
                     while os.path.exists(target_fpath):
                         target_fpath = os.path.join(target_dir, f"{name}_{counter}{ext}")
                         counter += 1

                     print(f"Copying selected image from '{fpath}' to '{target_fpath}'")
                     shutil.copy2(fpath, target_fpath) # Copy the file

                     # Now calculate the relative path of the *copied* file to base_dir
                     final_relative_path = os.path.relpath(target_fpath, self.base_dir).replace("\\", "/")
                     self.load_image(final_relative_path)
                     self.image_updated.emit(self.image_path) # Emit the new relative path
                 except OSError as e:
                     print(f"Error creating directory or copying file: {e}")
                     QMessageBox.critical(self, "File Error", f"Could not copy image file to project directory.\nCheck permissions and path.\n\n{e}")
                 except Exception as e:
                     print(f"Unexpected error during image copy: {e}")
                     QMessageBox.critical(self, "Copy Error", f"An unexpected error occurred while copying the image:\n\n{e}")


    # SIMPLIFIED: No direct save call, just clear and emit signal
    def _on_remove_button_clicked(self):
        """Clears the image and emits the image_updated signal."""
        print(f"Remove button clicked for image {self.index}")
        # clear_image now handles emitting the signal if the path changes
        self.clear_image(emit_signal=True)
        # The parent will receive image_updated("") via its
        # _on_image_updated slot, which triggers content_changed.
        # The main application should handle saving based on content_changed.
