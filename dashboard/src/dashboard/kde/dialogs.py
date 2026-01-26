"""
Dialog components for the Dashboard.

This module contains dialog-related methods and classes for the DashboardWindow,
including the About dialog and README viewer.
"""

import logging
import re
import webbrowser

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QMenu,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from dashboard.kde.styles import (
    get_about_dialog_stylesheet,
    get_hamburger_menu_stylesheet,
    get_readme_html_css,
    get_readme_viewer_stylesheet,
)
from dashboard.kde.utils import (
    GITHUB_PROFILE_URL,
    GITHUB_REPO_URL,
    get_assets_path,
    get_readme_path,
)

logger = logging.getLogger(__name__)


class DialogsMixin:
    """
    Mixin class providing dialog functionality for DashboardWindow.

    This mixin provides:
    - Hamburger menu with Settings, Help, and About options
    - Help menu with README options
    - README viewer dialog
    - About dialog with author info and links
    """

    # =========================================================================
    # Hamburger Menu
    # =========================================================================

    def _show_hamburger_menu(self) -> None:
        """Show hamburger menu with Settings, Help, and About options."""
        menu = QMenu(self)
        menu.setStyleSheet(get_hamburger_menu_stylesheet())

        # Settings action with white icon (symbolic only for monochrome appearance)
        settings_icon = self._icon_loader.get_icon("settings")
        settings_action = menu.addAction(settings_icon, "Settings")
        settings_action.triggered.connect(self._on_show_settings)

        menu.addSeparator()

        # Help submenu
        help_icon = self._icon_loader.get_icon("help")
        help_menu = menu.addMenu(help_icon, "Help")
        help_menu.setStyleSheet(menu.styleSheet())

        # User Guide
        user_guide_icon = self._icon_loader.get_icon("document")
        readme_action = help_menu.addAction(user_guide_icon, "User Guide (README)")
        readme_action.triggered.connect(lambda: self._show_readme_viewer(dev=False))

        # Developer Guide
        dev_guide_icon = self._icon_loader.get_icon("script")
        readme_dev_action = help_menu.addAction(
            dev_guide_icon, "Developer Guide (README_DEV)"
        )
        readme_dev_action.triggered.connect(lambda: self._show_readme_viewer(dev=True))

        # About action
        about_icon = self._icon_loader.get_icon("about")
        about_action = menu.addAction(about_icon, "About")
        about_action.triggered.connect(self._show_about_dialog)

        # Show menu below the hamburger button
        menu.exec(
            self._nav_menu_btn.mapToGlobal(self._nav_menu_btn.rect().bottomLeft())
        )

    def _show_help_menu(self) -> None:
        """Show help menu with README options."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #ffffff;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2d2d2d;
            }
        """)

        # User Guide icon - use document-properties or x-office-document for documentation
        user_guide_icon = QIcon.fromTheme("x-office-document")
        if user_guide_icon.isNull():
            user_guide_icon = QIcon.fromTheme("document-properties")
        if user_guide_icon.isNull():
            user_guide_icon = QIcon.fromTheme("text-x-generic")
        readme_action = menu.addAction(user_guide_icon, "User Guide (README)")
        readme_action.triggered.connect(lambda: self._show_readme_viewer(dev=False))

        # Developer Guide icon - use text-x-script or application-x-executable for code/dev docs
        dev_guide_icon = QIcon.fromTheme("text-x-script")
        if dev_guide_icon.isNull():
            dev_guide_icon = QIcon.fromTheme("text-x-source")
        if dev_guide_icon.isNull():
            dev_guide_icon = QIcon.fromTheme("application-x-executable")
        readme_dev_action = menu.addAction(
            dev_guide_icon, "Developer Guide (README_DEV)"
        )
        readme_dev_action.triggered.connect(lambda: self._show_readme_viewer(dev=True))

        # Show menu below the help button
        menu.exec(
            self._nav_help_btn.mapToGlobal(self._nav_help_btn.rect().bottomLeft())
        )

    # =========================================================================
    # README Viewer
    # =========================================================================

    def _show_readme_viewer(self, dev: bool = False) -> None:
        """Show a README file in a markdown viewer dialog with dark theme."""
        from PyQt6.QtWidgets import QMessageBox

        readme_path = get_readme_path(dev=dev)
        title = "Developer Guide" if dev else "User Guide"

        if readme_path is None or not readme_path.exists():
            msg = QMessageBox(self)
            msg.setWindowTitle("File Not Found")
            msg.setText(f"Could not find {'README_DEV.md' if dev else 'README.md'}")
            msg.setInformativeText(
                "This file should be bundled with the application. "
                "If running from source, ensure you're in the repository root."
            )
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.exec()
            return

        # Create viewer dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"TranscriptionSuite - {title}")
        dialog.resize(950, 750)
        dialog.setModal(False)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        # Markdown content viewer with HTML rendering
        text_browser = QTextBrowser()
        text_browser.setReadOnly(True)
        # Disable automatic link handling - we'll handle anchors manually
        text_browser.setOpenLinks(False)
        text_browser.setOpenExternalLinks(False)

        def handle_anchor_click(url: QUrl) -> None:
            """Handle anchor clicks - internal anchors scroll, external open browser."""
            url_str = url.toString()
            if url_str.startswith("#"):
                # Internal anchor - scroll to it
                anchor_name = url_str[1:]  # Remove the # prefix
                text_browser.scrollToAnchor(anchor_name)
            elif url_str.startswith("http://") or url_str.startswith("https://"):
                # External link - open in browser
                webbrowser.open(url_str)
            # Ignore other URL schemes (file://, etc.)

        text_browser.anchorClicked.connect(handle_anchor_click)

        # Apply dark theme styling
        text_browser.setStyleSheet("""
            QTextBrowser {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                padding: 20px;
                font-size: 14px;
                selection-background-color: #3d3d3d;
                selection-color: #ffffff;
            }
        """)

        # Set custom colors for links
        palette = text_browser.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#d4d4d4"))
        palette.setColor(QPalette.ColorRole.Link, QColor("#90caf9"))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#81d4fa"))
        text_browser.setPalette(palette)

        try:
            content = readme_path.read_text(encoding="utf-8")

            # Pre-process markdown content to handle HTML img tags and embedded HTML
            # The markdown library with extra extension handles inline HTML better

            # Remove HTML img tags and replace with text description
            # QTextBrowser has limited HTML support
            content = re.sub(
                r'<img[^>]*alt=["\']([^"\']*)["\'][^>]*>',
                r"[Image: \1]",
                content,
                flags=re.IGNORECASE,
            )
            content = re.sub(
                r'<img[^>]*src=["\']([^"\']*)["\'][^>]*>',
                r"[Image]",
                content,
                flags=re.IGNORECASE,
            )

            # Convert <pre> tags to fenced code blocks for better handling
            content = re.sub(r"<pre>\s*", "\n```\n", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*</pre>", "\n```\n", content, flags=re.IGNORECASE)

            # Try using markdown library to convert to HTML
            try:
                import markdown

                # Convert markdown to HTML with extensions
                # Using toc extension with slugify for consistent anchor IDs
                html_body = markdown.markdown(
                    content,
                    extensions=[
                        "fenced_code",
                        "tables",
                        "toc",
                        "sane_lists",
                        "attr_list",
                    ],
                    extension_configs={
                        "toc": {
                            "permalink": False,
                            "toc_depth": 4,
                        }
                    },
                )

                # Wrap in HTML with inline dark theme CSS
                css = get_readme_html_css()
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        {css}
                    </style>
                </head>
                <body>
                    {html_body}
                </body>
                </html>
                """
                text_browser.setHtml(html)

            except ImportError:
                # Fallback: use Qt's built-in setMarkdown
                text_browser.setMarkdown(content)

        except Exception as e:
            text_browser.setPlainText(f"Error reading file: {e}")

        layout.addWidget(text_browser)

        # Style the dialog
        dialog.setStyleSheet(get_readme_viewer_stylesheet())

        dialog.show()

    # =========================================================================
    # About Dialog
    # =========================================================================

    def _show_about_dialog(self) -> None:
        """Show the About dialog with author info and links."""
        dialog = QDialog(self)
        dialog.setWindowTitle("About TranscriptionSuite")
        dialog.setFixedSize(480, 620)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)

        # Profile picture with proper centering and clipping
        profile_container = QWidget()
        profile_container.setFixedSize(120, 120)
        profile_container_layout = QVBoxLayout(profile_container)
        profile_container_layout.setContentsMargins(0, 0, 0, 0)
        profile_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        profile_label = QLabel()
        profile_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        profile_label.setFixedSize(110, 110)

        profile_pixmap = self._load_profile_picture()
        if profile_pixmap:
            # Create circular mask for the profile picture
            scaled_pixmap = profile_pixmap.scaled(
                100,
                100,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

            # Create a rounded pixmap
            rounded = QPixmap(100, 100)
            rounded.fill(Qt.GlobalColor.transparent)

            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, 100, 100)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled_pixmap)
            painter.end()

            profile_label.setPixmap(rounded)
        else:
            # Fallback: use a placeholder
            profile_label.setText("👤")

        profile_container_layout.addWidget(profile_label)
        layout.addWidget(profile_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # App name
        app_name = QLabel("TranscriptionSuite")
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_name.setStyleSheet("color: #ffffff; font-size: 20px; font-weight: bold;")
        layout.addWidget(app_name)

        # Version info - always display (use shared version utility)
        from dashboard.common.version import __version__

        version_label = QLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        layout.addWidget(version_label)

        layout.addSpacing(4)

        # Description
        description = QLabel("Speech-to-Text Transcription Suite")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        layout.addWidget(description)

        # Copyright notice
        copyright_label = QLabel("© 2025-2026 homelab-00 • MIT License")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        layout.addWidget(copyright_label)

        layout.addSpacing(12)

        # Links section
        links_frame = QFrame()
        links_frame.setObjectName("linksFrame")
        links_layout = QVBoxLayout(links_frame)
        links_layout.setSpacing(10)
        links_layout.setContentsMargins(20, 20, 20, 20)

        # Author section header
        author_header = QLabel("Author")
        author_header.setStyleSheet(
            "color: #90caf9; font-size: 13px; font-weight: bold; margin-bottom: 4px;"
        )
        links_layout.addWidget(author_header)

        # GitHub profile
        github_btn = QPushButton("  GitHub Profile")
        github_icon = QIcon.fromTheme("user-identity")
        if github_icon.isNull():
            github_icon = QIcon.fromTheme("contact-new")
        github_btn.setIcon(github_icon)
        github_btn.setObjectName("linkButton")
        github_btn.clicked.connect(lambda: webbrowser.open(GITHUB_PROFILE_URL))
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        links_layout.addWidget(github_btn)

        links_layout.addSpacing(12)

        # Repository section header
        repo_header = QLabel("Repository")
        repo_header.setStyleSheet(
            "color: #90caf9; font-size: 13px; font-weight: bold; margin-bottom: 4px;"
        )
        links_layout.addWidget(repo_header)

        # GitHub repo
        github_repo_btn = QPushButton("  GitHub Repository")
        repo_icon = QIcon.fromTheme("folder-git")
        if repo_icon.isNull():
            repo_icon = QIcon.fromTheme("folder-development")
        if repo_icon.isNull():
            repo_icon = QIcon.fromTheme("folder")
        github_repo_btn.setIcon(repo_icon)
        github_repo_btn.setObjectName("linkButton")
        github_repo_btn.clicked.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        github_repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        links_layout.addWidget(github_repo_btn)

        layout.addWidget(links_frame)

        layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Style the dialog
        dialog.setStyleSheet(get_about_dialog_stylesheet())

        dialog.exec()

    def _load_profile_picture(self) -> QPixmap | None:
        """Load the profile picture from bundled assets."""
        assets_path = get_assets_path()
        profile_path = assets_path / "profile.png"

        if profile_path.exists():
            pixmap = QPixmap(str(profile_path))
            if not pixmap.isNull():
                return pixmap

        # Try loading from logo as fallback
        logo_path = assets_path / "logo.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                return pixmap

        return None
