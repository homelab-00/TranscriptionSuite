#!/usr/bin/env python3
"""
Cross-platform hotkey management system.

This module provides a unified interface for global hotkey detection across
different platforms, replacing the Windows-only AutoHotkey solution with
platform-appropriate alternatives.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Callable, Optional, Set
import subprocess
import os
import signal

from platform_utils import get_platform_manager

logger = logging.getLogger(__name__)

# Import Windows-specific subprocess constants conditionally
if os.name == 'nt':  # Windows
    try:
        from subprocess import DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
        WINDOWS_SUBPROCESS_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    except ImportError:
        # Fallback if constants aren't available
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        WINDOWS_SUBPROCESS_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
else:
    # On non-Windows systems, these constants don't exist
    DETACHED_PROCESS = None
    CREATE_NEW_PROCESS_GROUP = None
    WINDOWS_SUBPROCESS_FLAGS = None


class HotkeyBackend(ABC):
    """
    Abstract base class for hotkey detection backends.

    This demonstrates the Strategy pattern - different platforms can implement
    hotkey detection differently while providing the same interface.
    """

    def __init__(self, command_callback: Callable[[str], None]):
        """
        Initialize the hotkey backend.

        Args:
            command_callback: Function to call when a hotkey is pressed.
                             Should accept a string command as parameter.
        """
        self.command_callback = command_callback
        self.running = False
        self.registered_hotkeys: Dict[str, str] = {}

    @abstractmethod
    def register_hotkey(self, key_combination: str, command: str) -> bool:
        """
        Register a global hotkey.

        Args:
            key_combination: Key combination string (e.g., "F1", "ctrl+shift+f")
            command: Command string to send when hotkey is pressed

        Returns:
            True if registration was successful, False otherwise
        """
        pass

    @abstractmethod
    def start(self) -> bool:
        """
        Start the hotkey detection system.

        Returns:
            True if started successfully, False otherwise
        """
        pass

    @abstractmethod
    def stop(self):
        """Stop the hotkey detection system."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this backend is available on the current system.

        Returns:
            True if the backend can be used, False otherwise
        """
        pass


class AutoHotkeyBackend(HotkeyBackend):
    """
    Windows AutoHotkey backend - maintains compatibility with existing setup.

    This preserves your existing AutoHotkey script functionality while
    fitting into the new cross-platform architecture.
    """

    def __init__(self, command_callback: Callable[[str], None]):
        super().__init__(command_callback)
        self.platform_manager = get_platform_manager()
        self.script_process: Optional[subprocess.Popen] = None
        self.script_path: Optional[str] = None

    def is_available(self) -> bool:
        """Check if AutoHotkey is available."""
        if not self.platform_manager.is_windows:
            return False

        # Check if AutoHotkey executable exists
        ahk_path = self.platform_manager.get_executable_path("AutoHotkey")
        return ahk_path is not None

    def register_hotkey(self, key_combination: str, command: str) -> bool:
        """Register hotkey by storing the mapping for script generation."""
        self.registered_hotkeys[key_combination] = command
        logger.info(f"Registered AutoHotkey: {key_combination} -> {command}")
        return True

    def start(self) -> bool:
        """Start AutoHotkey script with registered hotkeys."""
        if not self.is_available():
            logger.error("AutoHotkey not available")
            return False

        if self.running:
            logger.warning("AutoHotkey backend already running")
            return True

        # Generate and start the AutoHotkey script
        try:
            self.script_path = self._generate_ahk_script()
            self._start_ahk_script()
            self.running = True
            logger.info("AutoHotkey backend started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start AutoHotkey backend: {e}")
            return False

    def stop(self):
        """Stop the AutoHotkey script."""
        if self.script_process:
            try:
                self.script_process.terminate()
                self.script_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.script_process.kill()
            except Exception as e:
                logger.error(f"Error stopping AutoHotkey process: {e}")

            self.script_process = None

        # Clean up script file
        if self.script_path and os.path.exists(self.script_path):
            try:
                os.remove(self.script_path)
            except OSError as e:
                logger.warning(f"Could not remove AHK script file: {e}")

        self.running = False
        logger.info("AutoHotkey backend stopped")

    def _generate_ahk_script(self) -> str:
        """Generate AutoHotkey script based on registered hotkeys."""
        # Create a temporary script file
        import tempfile
        script_fd, script_path = tempfile.mkstemp(suffix='.ahk', text=True)

        # Convert our hotkey mappings to AutoHotkey format
        ahk_mappings = {
            "F1": "*F1::",
            "F2": "*F2::",
            "F3": "*F3::",
            "F4": "*F4::",
            "F7": "*F7::",
            "F10": "*F10::"
        }

        script_content = '''
; Auto-generated AutoHotkey script for TranscriptionSuite
#NoEnv
#SingleInstance Force
SendMode Input
SetWorkingDir %A_ScriptDir%

; Function to send command using TCP
SendCommand(command) {
    try {
        ; Use PowerShell as reliable TCP client
        psCmd := "powershell.exe -Command ""$client = New-Object System.Net.Sockets.TCPClient('127.0.0.1', 35000); $stream = $client.GetStream(); $writer = New-Object System.IO.StreamWriter($stream); $writer.WriteLine('" command "'); $writer.Flush(); $client.Close()"""
        RunWait, %psCmd%, , Hide
    } catch e {
        ; Silently ignore connection errors
    }
}

'''

        # Add hotkey definitions
        for key_combo, command in self.registered_hotkeys.items():
            if key_combo in ahk_mappings:
                ahk_key = ahk_mappings[key_combo]
                script_content += f'''
{ahk_key}
    SendCommand("{command}")
return
'''

        # Write script to file
        with os.fdopen(script_fd, 'w') as f:
            f.write(script_content)

        logger.info(f"Generated AutoHotkey script: {script_path}")
        return script_path

    def _start_ahk_script(self):
        """Start the generated AutoHotkey script."""
        ahk_executable = self.platform_manager.get_executable_path("AutoHotkey")
        
        # Check if executable was found
        if not ahk_executable:
            raise RuntimeError("AutoHotkey executable not found")
        
        # Ensure script_path is available
        if not self.script_path:
            raise RuntimeError("AutoHotkey script not generated")

        # Prepare subprocess arguments
        popen_args = [str(ahk_executable), self.script_path]
        popen_kwargs = {}

        # Add Windows-specific process creation flags
        if self.platform_manager.is_windows and WINDOWS_SUBPROCESS_FLAGS is not None:
            popen_kwargs['creationflags'] = WINDOWS_SUBPROCESS_FLAGS

        # Start the script as a detached process
        try:
            self.script_process = subprocess.Popen(popen_args, **popen_kwargs)
        except Exception as e:
            raise RuntimeError(f"Failed to start AutoHotkey process: {e}")

        # Give it a moment to start
        time.sleep(1)

        # Check if process started successfully
        if self.script_process.poll() is not None:
            raise RuntimeError("AutoHotkey script failed to start")


class PynputBackend(HotkeyBackend):
    """
    Cross-platform hotkey backend using the pynput library.

    This provides a Python-native solution that works on Windows, Linux, and macOS.
    It's particularly useful as a fallback when platform-specific solutions aren't available.
    """

    def __init__(self, command_callback: Callable[[str], None]):
        super().__init__(command_callback)
        self.listener = None
        self.pressed_keys: Set[str] = set()

    def is_available(self) -> bool:
        """Check if pynput is available and can access the system."""
        try:
            from pynput import keyboard

            # Test if we can actually access the keyboard
            # This may fail in some containerized or restricted environments
            test_listener = keyboard.Listener(on_press=lambda key: None)
            test_listener.start()
            test_listener.stop()
            return True
        except ImportError:
            logger.warning("pynput not installed")
            return False
        except Exception as e:
            logger.warning(f"pynput cannot access system input: {e}")
            return False

    def register_hotkey(self, key_combination: str, command: str) -> bool:
        """Register hotkey combination."""
        self.registered_hotkeys[key_combination.lower()] = command
        logger.info(f"Registered pynput hotkey: {key_combination} -> {command}")
        return True

    def start(self) -> bool:
        """Start the pynput keyboard listener."""
        if not self.is_available():
            return False

        try:
            from pynput import keyboard

            self.listener = keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release
            )
            self.listener.start()
            self.running = True
            logger.info("Pynput hotkey backend started")
            return True
        except Exception as e:
            logger.error(f"Failed to start pynput backend: {e}")
            return False

    def stop(self):
        """Stop the keyboard listener."""
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.running = False
        logger.info("Pynput hotkey backend stopped")

    def _on_key_press(self, key):
        """Handle key press events."""
        try:
            key_name = self._get_key_name(key)
            if key_name:
                self.pressed_keys.add(key_name)
                self._check_hotkey_combinations()
        except Exception as e:
            logger.debug(f"Error in key press handler: {e}")

    def _on_key_release(self, key):
        """Handle key release events."""
        try:
            key_name = self._get_key_name(key)
            if key_name and key_name in self.pressed_keys:
                self.pressed_keys.remove(key_name)
        except Exception as e:
            logger.debug(f"Error in key release handler: {e}")

    def _get_key_name(self, key) -> Optional[str]:
        """Convert pynput key to string name."""
        try:
            from pynput import keyboard

            if hasattr(key, 'name'):
                # Special keys like F1, F2, etc.
                return key.name.lower()
            elif hasattr(key, 'char') and key.char:
                # Regular character keys
                return key.char.lower()
            else:
                return None
        except AttributeError:
            return None

    def _check_hotkey_combinations(self):
        """Check if current pressed keys match any registered hotkeys."""
        for hotkey, command in self.registered_hotkeys.items():
            # For function keys, we just check if that single key is pressed
            if hotkey.startswith('f') and hotkey in self.pressed_keys:
                # Ensure it's the only key pressed (to avoid conflicts)
                if len(self.pressed_keys) == 1:
                    logger.info(f"Hotkey triggered: {hotkey} -> {command}")
                    self.command_callback(command)


class HotkeyManager:
    """
    Main hotkey manager that selects and manages the appropriate backend.

    This demonstrates the Facade pattern - it provides a simple interface
    that hides the complexity of multiple backend implementations.
    """

    def __init__(self, command_callback: Callable[[str], None]):
        """
        Initialize hotkey manager with automatic backend selection.

        Args:
            command_callback: Function to call when hotkeys are triggered
        """
        self.command_callback = command_callback
        self.backend: Optional[HotkeyBackend] = None
        self.platform_manager = get_platform_manager()

        # Default hotkey mappings for the application
        self.default_hotkeys = {
            "F1": "OPEN_CONFIG",
            "F2": "TOGGLE_REALTIME",
            "F3": "START_LONGFORM",
            "F4": "STOP_LONGFORM",
            "F7": "QUIT",
            "F10": "RUN_STATIC"
        }

    def initialize(self) -> bool:
        """
        Initialize the hotkey system by selecting the best available backend.

        Returns:
            True if initialization was successful, False otherwise
        """
        # Try backends in order of preference
        backends_to_try = self._get_preferred_backends()

        for backend_class in backends_to_try:
            try:
                backend = backend_class(self.command_callback)
                if backend.is_available():
                    logger.info(f"Using hotkey backend: {backend.__class__.__name__}")
                    self.backend = backend
                    return self._register_default_hotkeys()
            except Exception as e:
                logger.warning(f"Failed to initialize {backend_class.__name__}: {e}")

        logger.error("No suitable hotkey backend found")
        return False

    def _get_preferred_backends(self) -> list:
        """Get list of backend classes in order of preference for this platform."""
        if self.platform_manager.is_windows:
            # On Windows, prefer AutoHotkey if available, fallback to pynput
            return [AutoHotkeyBackend, PynputBackend]
        else:
            # On Linux/macOS, use pynput (we could add X11-specific backends later)
            return [PynputBackend]

    def _register_default_hotkeys(self) -> bool:
        """Register the default hotkey mappings."""
        if not self.backend:
            return False

        success = True
        for key_combo, command in self.default_hotkeys.items():
            if not self.backend.register_hotkey(key_combo, command):
                logger.warning(f"Failed to register hotkey: {key_combo}")
                success = False

        return success

    def start(self) -> bool:
        """Start the hotkey detection system."""
        if not self.backend:
            logger.error("No hotkey backend initialized")
            return False

        return self.backend.start()

    def stop(self):
        """Stop the hotkey detection system."""
        if self.backend:
            self.backend.stop()

    def is_available(self) -> bool:
        """Check if hotkey functionality is available."""
        return self.backend is not None and self.backend.is_available()

    def get_backend_info(self) -> Dict[str, str]:
        """Get information about the current backend."""
        if not self.backend:
            return {"backend": "none", "status": "not_initialized"}

        return {
            "backend": self.backend.__class__.__name__,
            "status": "running" if self.backend.running else "stopped",
            "platform": self.platform_manager.platform
        }