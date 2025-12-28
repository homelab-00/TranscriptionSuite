"""
Windows 11 system tray implementation using PyQt6.

Provides native system tray integration for Windows desktop.
Uses the same Qt6Tray implementation as KDE since PyQt6 works on both.
"""

import logging

logger = logging.getLogger(__name__)


def run_tray(config) -> int:
    """
    Run the Windows tray application.

    Args:
        config: Client configuration

    Returns:
        Exit code
    """
    # Windows uses the same PyQt6 implementation as KDE
    from client.common.orchestrator import ClientOrchestrator
    from client.kde.tray import Qt6Tray

    try:
        tray = Qt6Tray(config=config)
        orchestrator = ClientOrchestrator(
            config=config,
            auto_connect=True,
            auto_copy_clipboard=config.get("clipboard", "auto_copy", default=True),
        )
        orchestrator.start(tray)
        return 0

    except ImportError as e:
        logger.error(f"PyQt6 not available: {e}")
        print(
            "Error: PyQt6 is required for Windows tray. Install with: pip install PyQt6"
        )
        return 1

    except RuntimeError as e:
        logger.error(f"Tray initialization failed: {e}")
        print(f"Error: {e}")
        return 1

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1
