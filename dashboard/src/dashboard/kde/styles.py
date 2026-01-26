"""
Stylesheet definitions for the Dashboard.

This module contains the CSS stylesheets used by the Dashboard window,
extracted to keep the main dashboard.py file smaller and more maintainable.
"""


def get_dashboard_stylesheet() -> str:
    """
    Get the main dashboard stylesheet.

    Returns the CSS stylesheet matching the Web UI color palette:
    - background: #0a0a0a (darker), surface: #1e1e1e, surface-light: #2d2d2d
    - primary: #90caf9, primary-dark: #42a5f5
    - error: #f44336, success: #4caf50, warning: #ff9800, info: #2196f3
    """
    return """
        QMainWindow {
            background-color: #0a0a0a;
        }

        QScrollArea {
            background-color: #0a0a0a;
            border: none;
        }

        QScrollBar:vertical {
            background-color: #1e1e1e;
            width: 10px;
            margin: 0;
        }

        QScrollBar::handle:vertical {
            background-color: #3d3d3d;
            min-height: 30px;
            border-radius: 5px;
        }

        QScrollBar::handle:vertical:hover {
            background-color: #4d4d4d;
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }

        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }

        QScrollBar:horizontal {
            background-color: #1e1e1e;
            height: 10px;
            margin: 0;
        }

        QScrollBar::handle:horizontal {
            background-color: #3d3d3d;
            min-width: 30px;
            border-radius: 5px;
        }

        QScrollBar::handle:horizontal:hover {
            background-color: #4d4d4d;
        }

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0;
        }

        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }

        /* Sidebar styles */
        #sidebar {
            background-color: #1a1a2e;
            border-right: 1px solid #2d2d2d;
        }

        #sidebarHeader {
            background-color: #1a1a2e;
            border-bottom: 1px solid #2d2d2d;
        }

        #sidebarTitle {
            color: #90caf9;
            font-size: 20px;
            font-weight: bold;
        }

        #sidebarSubtitle {
            color: #606080;
            font-size: 16px;
            font-weight: 500;
        }

        #sidebarButton {
            background-color: transparent;
            border: none;
            border-radius: 6px;
            color: #a0a0a0;
            padding: 10px 12px;
            font-size: 13px;
            text-align: left;
        }

        #sidebarButton:hover {
            background-color: #2d2d3d;
            color: #ffffff;
        }

        #sidebarButton:checked {
            background-color: #2d4a6d;
            color: #90caf9;
        }

        #sidebarButtonContainer {
            background-color: transparent;
            border-radius: 6px;
        }

        #sidebarButtonContainer:hover {
            background-color: #2d2d3d;
        }

        #sidebarBottom {
            background-color: #1a1a2e;
            border-top: 1px solid #2d2d2d;
        }

        /* Legacy navBar styles (kept for compatibility) */
        #navBar {
            background-color: #1e1e1e;
            border-bottom: 1px solid #2d2d2d;
        }

        #navButton {
            background-color: transparent;
            border: none;
            color: #a0a0a0;
            padding: 5px 10px;
            font-size: 13px;
        }

        #navButton:hover {
            color: #90caf9;
            background-color: #2d2d2d;
            border-radius: 4px;
        }

        #navTitle {
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
        }

        #welcomeTitle {
            color: #ffffff;
            font-size: 24px;
            font-weight: bold;
        }

        #welcomeSubtitle {
            color: #a0a0a0;
            font-size: 14px;
        }

        #welcomeButton {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
            color: #ffffff;
            font-size: 14px;
            padding: 20px;
        }

        #welcomeButton:hover {
            background-color: #2d2d2d;
            border-color: #3d3d3d;
        }

        #homeStatusLabel {
            color: #a0a0a0;
            font-size: 12px;
        }

        #homeStatusValue {
            color: #ffffff;
            font-size: 13px;
        }

        #viewTitle {
            color: #ffffff;
            font-size: 22px;
            font-weight: bold;
        }

        #statusCard {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
            padding: 20px;
        }

        #managementGroup {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 6px;
        }

        #columnHeader {
            color: #90caf9;
            font-size: 13px;
            font-weight: bold;
            margin-bottom: 6px;
        }

        #volumesStatusCard {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
        }

        #statusLabel {
            color: #a0a0a0;
            font-size: 13px;
            min-width: 100px;
        }

        #statusValue {
            color: #ffffff;
            font-weight: bold;
            font-size: 13px;
        }

        #statusDateInline {
            color: #6c757d;
            font-size: 11px;
            margin-left: 8px;
        }

        #tokenField {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 6px;
            color: #ffffff;
            padding: 8px 10px;
            font-size: 12px;
            font-family: monospace;
        }

        #tokenField:focus {
            border-color: #90caf9;
        }

        #primaryButton {
            background-color: #90caf9;
            border: none;
            border-radius: 6px;
            color: #121212;
            padding: 10px 20px;
            font-size: 13px;
            min-width: 100px;
            font-weight: 500;
        }

        #primaryButton:hover {
            background-color: #42a5f5;
        }

        #primaryButton:disabled {
            background-color: #2d2d2d;
            color: #606060;
        }

        #stopButton {
            background-color: #f44336;
            border: none;
            border-radius: 6px;
            color: white;
            padding: 10px 20px;
            font-size: 13px;
            min-width: 80px;
        }

        #stopButton:hover {
            background-color: #d32f2f;
        }

        #stopButton:disabled {
            background-color: #2d2d2d;
            color: #606060;
        }

        #secondaryButton {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            color: white;
            padding: 8px 16px;
            font-size: 12px;
        }

        #secondaryButton:hover {
            background-color: #3d3d3d;
            border-color: #4d4d4d;
        }

        #toggleButton {
            background-color: transparent;
            border: 1px solid #3d3d3d;
            border-radius: 4px;
            color: #a0a0a0;
            padding: 6px 12px;
            font-size: 12px;
        }

        #toggleButton:hover {
            background-color: #2d2d2d;
            color: #ffffff;
        }

        #toggleButton:checked {
            background-color: #2d2d2d;
            color: #ffffff;
        }

        #logView {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 4px;
            color: #d4d4d4;
            font-family: monospace;
            font-size: 11px;
        }

        QPushButton:disabled {
            background-color: #2d2d2d;
            color: #606060;
        }

        #noteLabel {
            color: #6c757d;
            font-size: 11px;
            font-style: italic;
        }

        #webNoteLabel {
            color: #808080;
            font-size: 11px;
            font-style: italic;
        }

        #dangerButton {
            background-color: #f44336;
            border: none;
            border-radius: 4px;
            color: white;
            padding: 8px 16px;
            font-size: 13px;
        }

        #dangerButton:hover {
            background-color: #d32f2f;
        }

        #dangerButton:disabled {
            background-color: #2d2d2d;
            color: #606060;
        }

        #homeIconButton {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 18px;
            color: #ffffff;
            font-size: 16px;
        }

        #homeIconButton:hover {
            background-color: #2d2d2d;
            border-color: #3d3d3d;
        }

        QLabel#homeStatusLabel[accent="server"] {
            color: #6B8DD9;
        }

        QLabel#homeStatusLabel[accent="client"] {
            color: #D070D0;
        }

        QPushButton#welcomeButton[accent="server"] {
            border: 2px solid #7BA9F5;
        }

        QPushButton#welcomeButton[accent="server"]:hover {
            border-color: #A0C5FF;
        }

        QPushButton#welcomeButton[accent="client"] {
            border: 2px solid #E78FF5;
        }

        QPushButton#welcomeButton[accent="client"]:hover {
            border-color: #F5B3FF;
        }

        QPushButton#secondaryButton[accent="web"] {
            border: 1px solid #4DD0E1;
        }

        QPushButton#secondaryButton[accent="web"]:hover {
            border-color: #80DEEA;
        }

        #sectionHeader {
            color: #a0a0a0;
            font-size: 14px;
            font-weight: bold;
        }
    """


def get_hamburger_menu_stylesheet() -> str:
    """Get the stylesheet for the hamburger menu."""
    return """
        QMenu {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 6px;
            padding: 4px;
        }
        QMenu::item {
            color: #ffffff;
            padding: 8px 12px 8px 8px;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #2d2d2d;
        }
        QMenu::separator {
            height: 1px;
            background-color: #2d2d2d;
            margin: 4px 8px;
        }
        QMenu::icon {
            padding-left: 20px;
            padding-right: -6px;
        }
    """


def get_about_dialog_stylesheet() -> str:
    """Get the stylesheet for the About dialog."""
    return """
        QDialog {
            background-color: #121212;
        }
        #linksFrame {
            background-color: #1e1e1e;
            border: 1px solid #2d2d2d;
            border-radius: 8px;
        }
        #linkButton {
            background-color: transparent;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            color: #ffffff;
            padding: 10px 16px;
            padding-left: 12px;
            text-align: left;
            font-size: 13px;
            min-width: 200px;
            min-height: 20px;
        }
        #linkButton:hover {
            background-color: #2d2d2d;
            border-color: #90caf9;
        }
        #primaryButton {
            background-color: #90caf9;
            border: none;
            border-radius: 6px;
            color: #121212;
            padding: 10px 32px;
            font-size: 13px;
            font-weight: 500;
        }
        #primaryButton:hover {
            background-color: #42a5f5;
        }
    """


def get_readme_viewer_stylesheet() -> str:
    """Get the stylesheet for the README viewer dialog."""
    return """
        QDialog {
            background-color: #121212;
        }
        QTextBrowser {
            background-color: #1e1e1e;
            border: none;
        }
    """


def get_readme_html_css() -> str:
    """Get the CSS for rendering README markdown as HTML."""
    return """
        body {
            color: #d4d4d4;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            line-height: 1.6;
            margin: 0;
            padding: 0;
        }
        h1 { color: #90caf9; font-size: 28px; margin-top: 24px; border-bottom: 1px solid #3d3d3d; padding-bottom: 8px; }
        h2 { color: #81d4fa; font-size: 22px; margin-top: 20px; border-bottom: 1px solid #2d2d2d; padding-bottom: 6px; }
        h3 { color: #b3e5fc; font-size: 18px; margin-top: 16px; }
        h4, h5, h6 { color: #e1f5fe; margin-top: 12px; }
        a { color: #90caf9; text-decoration: none; }
        a:hover { text-decoration: underline; }
        code {
            background-color: #2d2d2d;
            color: #ce93d8;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'CaskaydiaCove Nerd Font', 'Fira Code', 'Consolas', monospace;
            font-size: 13px;
        }
        pre {
            background-color: #1a1a1a;
            border: 1px solid #3d3d3d;
            border-radius: 6px;
            padding: 12px;
            overflow-x: auto;
            font-family: 'CaskaydiaCove Nerd Font', 'Fira Code', 'Consolas', monospace;
            font-size: 13px;
        }
        pre code {
            background-color: transparent;
            padding: 0;
            color: #d4d4d4;
        }
        blockquote {
            border-left: 4px solid #90caf9;
            margin: 16px 0;
            padding: 8px 16px;
            background-color: #252525;
            color: #b0b0b0;
        }
        table { border-collapse: collapse; width: 100%; margin: 16px 0; }
        th, td { border: 1px solid #3d3d3d; padding: 10px; text-align: left; }
        th { background-color: #2d2d2d; color: #90caf9; font-weight: 600; }
        tr:nth-child(even) { background-color: #252525; }
        ul, ol { padding-left: 24px; margin: 12px 0; }
        li { margin: 6px 0; }
        hr { border: none; border-top: 1px solid #3d3d3d; margin: 24px 0; }
        strong { color: #ffffff; }
        em { color: #b0b0b0; }
    """
