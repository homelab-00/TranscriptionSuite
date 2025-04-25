#!/usr/bin/env python3
# system_utils.py
#
# System utility functions for the Speech-to-Text system
#
# This module:
# - Provides hardware and version information detection
# - Manages configuration loading and saving
# - Handles AutoHotkey script management
# - Contains utility functions for system interactions

import os
import sys
import json
import logging
import subprocess
import time
import psutil
from typing import Dict, Any, Optional, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("stt_orchestrator.log"),
    ]
)

# Try to import Rich for prettier console output
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.live import Live
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

def safe_print(message, style="default"):
    """Print function that handles I/O errors gracefully with optional styling."""
    try:
        if HAS_RICH:
            if style == "error":
                console.print(f"[bold red]{message}[/bold red]")
            elif style == "warning":
                console.print(f"[bold yellow]{message}[/bold yellow]")
            elif style == "success":
                console.print(f"[bold green]{message}[/bold green]")
            elif style == "info":
                console.print(f"[bold blue]{message}[/bold blue]")
            else:
                console.print(message)
        else:
            print(message)
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            pass  # Silently ignore closed file errors
        else:
            # For other ValueErrors, log them
            logging.error(f"Error in safe_print: {e}")

class SystemUtils:
    """Utilities for system interaction and configuration management."""
    
    def __init__(self, config_path: str):
        """Initialize with configuration file path."""
        self.config_path = config_path
        self.ahk_pid = None
        self.config = {}
        
    def load_or_create_config(self) -> Dict[str, Any]:
        """Load configuration from file or create it if it doesn't exist."""
        # Define default configuration with full model names and English language
        default_config = {
            "realtime": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "default",
                "device": "cuda",
                "input_device_index": None,
                "use_default_input": True,
                # This flag controls whether the application will dynamically detect and use 
                # the system's current default input device (when set to True) or use a fixed
                # device specified by input_device_index (when set to False). When True, the 
                # application will automatically use whichever audio input device is currently 
                # selected as the default in Windows Sound settings, enabling on-the-fly
                # device switching without restarting the application.
                "gpu_device_index": 0,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": False,
                "silero_deactivity_detection": False,
                "webrtc_sensitivity": 3,
                "post_speech_silence_duration": 0.6,
                "min_length_of_recording": 1.0,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
                "ensure_sentence_starting_uppercase": True,
                "ensure_sentence_ends_with_period": True,
                "batch_size": 16,
                "beam_size": 5,
                "beam_size_realtime": 3,
                "initial_prompt": None,
                "allowed_latency_limit": 100,
                "early_transcription_on_silence": 0,
                "enable_realtime_transcription": True,
                "realtime_processing_pause": 0.2,
                "realtime_model_type": "tiny.en",
                "realtime_batch_size": 16
            },
            "longform": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "default",
                "device": "cuda",
                "input_device_index": None,
                "use_default_input": True,
                "gpu_device_index": 0,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": False,
                "silero_deactivity_detection": False,
                "webrtc_sensitivity": 3,
                "post_speech_silence_duration": 0.6,
                "min_length_of_recording": 1.0,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
                "ensure_sentence_starting_uppercase": True,
                "ensure_sentence_ends_with_period": True,
                "batch_size": 16,
                "beam_size": 5,
                "initial_prompt": None,
                "allowed_latency_limit": 100
            },
            "static": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "float16",
                "device": "cuda",
                "gpu_device_index": 0,
                "beam_size": 5,
                "batch_size": 16,
                "vad_aggressiveness": 2
            }
        }

        # Try to load existing config
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)

                    # Update default config with loaded values
                    for module_type in default_config:
                        if module_type in loaded_config:
                            for param, value in loaded_config[module_type].items():
                                if param in default_config[module_type]:
                                    default_config[module_type][param] = value

                    self.config = default_config
                    logging.info("Configuration loaded from file")
            except Exception as e:
                logging.error(f"Error loading configuration: {e}")
                self.config = default_config
        else:
            # Use defaults and save to file
            self.config = default_config
            self.save_config()
            logging.info("Default configuration created")
            
        return self.config

    def save_config(self) -> bool:
        """Save current configuration to file."""
        # Define a function to fix None values
        def fix_none_values(obj):
            if isinstance(obj, dict):
                return {k: fix_none_values(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [fix_none_values(i) for i in obj]
            elif obj == "":
                return None  # Convert empty strings back to None
            else:
                return obj
        
        try:
            # Apply the fix to the config object
            fixed_config = fix_none_values(self.config)
            
            with open(self.config_path, 'w') as f:
                json.dump(fixed_config, f, indent=4)
                
            logging.info("Configuration saved to file")
            return True
        except Exception as e:
            logging.error(f"Error saving configuration: {e}")
            return False
            
    def open_config_dialog(self, config_updated_callback=None):
        """Open the configuration dialog."""
        safe_print("Opening configuration dialog...", "info")
        
        try:
            # Add the script directory to sys.path if it's not already there
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.append(script_dir)
                
            from configuration_dialog_box_module import ConfigurationDialog
            
            # Create and show the dialog
            dialog = ConfigurationDialog(
                config_path=self.config_path,
                callback=config_updated_callback
            )
            
            result = dialog.show_dialog()
            
            # If the user clicked Apply
            if result:
                logging.info("Configuration dialog closed with Apply")
                # Reload the configuration
                if os.path.exists(self.config_path):
                    with open(self.config_path, 'r') as f:
                        self.config = json.load(f)
            else:
                logging.info("Configuration dialog closed without saving")
                
            return result
                
        except Exception as e:
            logging.error(f"Error opening configuration dialog: {e}")
            safe_print(f"Error opening configuration dialog: {e}", "error")
            return False
    
    def kill_leftover_ahk(self):
        """Kill any existing AHK processes using our script."""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if (
                    proc.info['name'] == 'AutoHotkeyU64.exe'
                    and proc.info['cmdline'] is not None
                    and "STT_hotkeys.ahk" in ' '.join(proc.info['cmdline'])
                ):
                    logging.info(f"Killing leftover AHK process with PID={proc.pid}")
                    psutil.Process(proc.pid).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    
    def start_ahk_script(self, ahk_path: str) -> bool:
        """Start the AutoHotkey script."""
        # First kill any leftover AHK processes
        self.kill_leftover_ahk()
        
        # Record existing AHK PIDs before launching
        pre_pids = set()
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'AutoHotkeyU64.exe':
                    pre_pids.add(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Launch the AHK script
        logging.info("Launching AHK script...")
        subprocess.Popen(
            [ahk_path],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            shell=True
        )

        # Give it a moment to start
        time.sleep(1.0)
        
        # Find the new AHK process
        post_pids = set()
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'AutoHotkeyU64.exe':
                    post_pids.add(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Store the PID of the new process
        new_pids = post_pids - pre_pids
        if len(new_pids) == 1:
            self.ahk_pid = new_pids.pop()
            logging.info(f"Detected new AHK script PID: {self.ahk_pid}")
            return True
        else:
            logging.info("Could not detect a single new AHK script PID. No PID stored.")
            self.ahk_pid = None
            return False
    
    def stop_ahk_script(self):
        """Kill AHK script if we know its PID."""
        if self.ahk_pid is not None:
            logging.info(f"Killing AHK script with PID={self.ahk_pid}")
            try:
                psutil.Process(self.ahk_pid).kill()
                return True
            except Exception as e:
                logging.error(f"Failed to kill AHK process: {e}")
                return False
        return False

    def get_version_info(self) -> Dict[str, str]:
        """Get version information for key dependencies."""
        version_info = {}

        # Get PyTorch version
        try:
            import torch
            version_info["torch"] = torch.__version__
        except ImportError:
            version_info["torch"] = "Not installed"
        
        # Get RealtimeSTT version
        try:
            import RealtimeSTT
            try:
                from importlib.metadata import version
                version_info["RealtimeSTT"] = version("realtimestt")
            except Exception:
                version_info["RealtimeSTT"] = "Unknown"
        except ImportError:
            version_info["RealtimeSTT"] = "Not installed"
        
        # Get Faster Whisper version
        try:
            import faster_whisper
            version_info["faster_whisper"] = getattr(faster_whisper, "__version__", "Unknown")
        except ImportError:
            version_info["faster_whisper"] = "Not installed"
        
        return version_info

    def get_hardware_info(self) -> Dict[str, str]:
        """Get basic CPU and GPU information."""
        hardware_info = {}
        
        # Get CPU info
        try:
            import platform
            hardware_info["cpu"] = platform.processor()
            if not hardware_info["cpu"]:  # On some systems, platform.processor() returns an empty string
                import os
                if os.name == 'nt':  # Windows
                    import subprocess
                    result = subprocess.check_output("wmic cpu get name", shell=True).decode().strip().split('\n')
                    if len(result) > 1:
                        hardware_info["cpu"] = result[1].strip()
                else:  # Linux/Mac
                    try:
                        with open('/proc/cpuinfo', 'r') as f:
                            for line in f:
                                if line.startswith('model name'):
                                    hardware_info["cpu"] = line.split(':')[1].strip()
                                    break
                    except:
                        pass
        except Exception as e:
            hardware_info["cpu"] = "Unknown"
            logging.error(f"Error getting CPU info: {e}")
        
        # Get GPU info
        try:
            import torch
            if torch.cuda.is_available():
                hardware_info["gpu"] = torch.cuda.get_device_name(0)
            else:
                hardware_info["gpu"] = "No CUDA GPU available"
        except Exception as e:
            hardware_info["gpu"] = "Unknown"
            logging.error(f"Error getting GPU info: {e}")
        
        return hardware_info
        
    def display_system_info(self) -> None:
        """Display system information including versions and hardware."""
        # Get version information
        version_info = self.get_version_info()
        
        # Get hardware information
        hardware_info = self.get_hardware_info()
        
        # Display startup banner
        if HAS_RICH:
            panel_content = (
                "[bold]Speech-to-Text Orchestrator[/bold]\n\n"
                "Control the system using these hotkeys:\n"
                "  [cyan]F1[/cyan]:  Open configuration dialogue box\n"
                "  [cyan]F2[/cyan]:  Toggle real-time transcription\n"
                "  [cyan]F3[/cyan]:  Start long-form recording\n"
                "  [cyan]F4[/cyan]:  Stop long-form recording and transcribe\n"
                "  [cyan]F10[/cyan]: Run static file transcription\n"
                "  [cyan]F7[/cyan]:  Quit application\n\n"
                f"[bold yellow]Selected Languages:[/bold yellow]\n"
                f"  Long Form: {self.config['longform']['language']}\n"
                f"  Real-time: {self.config['realtime']['language']}\n"
                f"  Static: {self.config['static']['language']}\n\n"
                f"[bold yellow]Versions:[/bold yellow]\n"
                f"  PyTorch: {version_info['torch']}\n"
                f"  RealtimeSTT: {version_info['RealtimeSTT']}\n"
                f"  Faster Whisper: {version_info['faster_whisper']}\n\n"
                f"[bold yellow]Hardware:[/bold yellow]\n"
                f"  CPU: {hardware_info['cpu']}\n"
                f"  GPU: {hardware_info['gpu']}"
            )
            
            info_panel = Panel(panel_content, title="Speech-to-Text System", border_style="green")
            with Live(info_panel, console=console, auto_refresh=False) as live:
                live.update(info_panel)
                # Brief pause to ensure proper display
                time.sleep(0.1)
        else:
            safe_print("="*50)
            safe_print("Speech-to-Text Orchestrator Running")
            safe_print("="*50)
            safe_print("Hotkeys:")
            safe_print("  F1: Open configuration dialogue box")
            safe_print("  F2: Toggle real-time transcription")
            safe_print("  F3: Start long-form recording")
            safe_print("  F4: Stop long-form recording and transcribe")
            safe_print("  F10: Run static file transcription")
            safe_print("  F7: Quit application")
            safe_print("="*50)
            safe_print("Selected Languages:")
            safe_print(f"  Long Form: {self.config['longform']['language']}")
            safe_print(f"  Real-time: {self.config['realtime']['language']}")
            safe_print(f"  Static: {self.config['static']['language']}")
            safe_print("="*50)
            safe_print("Versions:")
            safe_print(f"  PyTorch: {version_info['torch']}")
            safe_print(f"  RealtimeSTT: {version_info['RealtimeSTT']}")
            safe_print(f"  Faster Whisper: {version_info['faster_whisper']}")
            safe_print("="*50)
            safe_print("Hardware:")
            safe_print(f"  CPU: {hardware_info['cpu']}")
            safe_print(f"  GPU: {hardware_info['gpu']}")
            safe_print("="*50)