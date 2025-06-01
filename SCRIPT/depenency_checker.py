#!/usr/bin/env python3
"""
Dependency checking system for TranscriptionSuite.

This module provides comprehensive checking of external dependencies
and system requirements across different platforms.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import importlib.util

from platform_utils import get_platform_manager

logger = logging.getLogger(__name__)


class DependencyChecker:
    """
    Comprehensive dependency checking for the TranscriptionSuite.

    This class demonstrates defensive programming - checking all assumptions
    about the environment before attempting to use external resources.
    """

    def __init__(self):
        self.platform_manager = get_platform_manager()
        self.check_results: Dict[str, Dict] = {}

    def check_all_dependencies(self) -> Dict[str, Dict]:
        """
        Perform comprehensive dependency checking.

        Returns:
            Dictionary with check results for each dependency category
        """
        logger.info("Starting comprehensive dependency check")

        # Check Python packages
        self.check_results['python_packages'] = self._check_python_packages()

        # Check external executables
        self.check_results['executables'] = self._check_external_executables()

        # Check audio system
        self.check_results['audio'] = self._check_audio_system()

        # Check CUDA/GPU
        self.check_results['gpu'] = self._check_gpu_support()

        # Check system permissions
        self.check_results['permissions'] = self._check_system_permissions()

        # Generate summary
        self.check_results['summary'] = self._generate_summary()

        logger.info("Dependency check completed")
        return self.check_results

    def _check_python_packages(self) -> Dict[str, Dict]:
        """Check availability and versions of required Python packages."""
        required_packages = {
            'torch': {
                'required': True,
                'min_version': '1.9.0',
                'description': 'PyTorch for neural network inference'
            },
            'faster_whisper': {
                'required': True,
                'min_version': '0.9.0',
                'description': 'Faster Whisper for speech recognition'
            },
            'RealtimeSTT': {
                'required': True,
                'min_version': '0.1.0',
                'description': 'Real-time speech-to-text library'
            },
            'pyaudio': {
                'required': True,
                'min_version': None,
                'description': 'Audio input/output library'
            },
            'keyboard': {
                'required': False,
                'min_version': None,
                'description': 'Keyboard input handling'
            },
            'pyperclip': {
                'required': True,
                'min_version': None,
                'description': 'Clipboard operations'
            },
            'pynput': {
                'required': False,
                'min_version': None,
                'description': 'Cross-platform input handling'
            },
            'webrtcvad': {
                'required': False,
                'min_version': None,
                'description': 'Voice activity detection'
            },
            'rich': {
                'required': False,
                'min_version': None,
                'description': 'Enhanced console output'
            }
        }

        results = {}

        for package_name, package_info in required_packages.items():
            try:
                # Try to import the package
                spec = importlib.util.find_spec(package_name)
                if spec is None:
                    results[package_name] = {
                        'available': False,
                        'version': None,
                        'error': 'Package not found',
                        'required': package_info['required'],
                        'description': package_info['description']
                    }
                    continue

                # Import and get version
                module = importlib.import_module(package_name)
                version = getattr(module, '__version__', 'unknown')

                results[package_name] = {
                    'available': True,
                    'version': version,
                    'error': None,
                    'required': package_info['required'],
                    'description': package_info['description']
                }

            except ImportError as e:
                results[package_name] = {
                    'available': False,
                    'version': None,
                    'error': str(e),
                    'required': package_info['required'],
                    'description': package_info['description']
                }

        return results

    def _check_external_executables(self) -> Dict[str, Dict]:
        """Check availability of external executables."""
        executables = {
            'ffmpeg': {
                'required': True,
                'description': 'Audio/video processing for static transcription',
                'install_hint': self._get_ffmpeg_install_hint()
            }
        }

        if self.platform_manager.is_windows:
            executables['AutoHotkey'] = {
                'required': False,
                'description': 'Global hotkey support (alternative: pynput)',
                'install_hint': 'Download from https://www.autohotkey.com/'
            }

        results = {}

        for exe_name, exe_info in executables.items():
            exe_path = self.platform_manager.get_executable_path(exe_name)

            if exe_path:
                # Try to get version
                version = self._get_executable_version(exe_name, exe_path)
                results[exe_name] = {
                    'available': True,
                    'path': str(exe_path),
                    'version': version,
                    'required': exe_info['required'],
                    'description': exe_info['description']
                }
            else:
                results[exe_name] = {
                    'available': False,
                    'path': None,
                    'version': None,
                    'required': exe_info['required'],
                    'description': exe_info['description'],
                    'install_hint': exe_info.get('install_hint', 'Install via package manager')
                }

        return results

    def _get_ffmpeg_install_hint(self) -> str:
        """Get platform-specific FFmpeg installation instructions."""
        if self.platform_manager.is_windows:
            return "Download from https://ffmpeg.org/download.html or use 'winget install ffmpeg'"
        elif self.platform_manager.is_linux:
            return "Install via package manager: apt install ffmpeg, pacman -S ffmpeg, etc."
        else:  # macOS
            return "Install via Homebrew: brew install ffmpeg"

    def _get_executable_version(self, exe_name: str, exe_path: Path) -> Optional[str]:
        """Try to get version information from an executable."""
        version_flags = ['--version', '-version', '-V', '/V']

        for flag in version_flags:
            try:
                result = subprocess.run(
                    [str(exe_path), flag],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    # Parse version from output (this is basic - could be improved)
                    output = result.stdout + result.stderr
                    lines = output.split('\n')
                    if lines:
                        return lines[0].strip()[:100]  # First line, limited length

            except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
                continue

        return "version unknown"

    def _check_audio_system(self) -> Dict[str, Any]:
        """Check audio system availability and capabilities."""
        result = {
            'pyaudio_available': False,
            'default_device_accessible': False,
            'device_count': 0,
            'available_backends': [],
            'errors': []
        }

        # Check PyAudio
        try:
            import pyaudio
            result['pyaudio_available'] = True

            # Test device enumeration
            p = pyaudio.PyAudio()
            result['device_count'] = p.get_device_count()

            # Test default device access
            try:
                default_info = p.get_default_input_device_info()

                # Ensure device index is an integer
                device_index = int(default_info['index'])

                # Try to briefly open the default device
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=1024
                )
                stream.close()
                result['default_device_accessible'] = True

            except Exception as e:
                result['errors'].append(f"Default audio device not accessible: {e}")

            p.terminate()

        except ImportError:
            result['errors'].append("PyAudio not installed")
        except Exception as e:
            result['errors'].append(f"PyAudio error: {e}")

        # Check available audio backends
        result['available_backends'] = self.platform_manager.get_audio_backends()

        return result

    def _check_gpu_support(self) -> Dict[str, Any]:
        """Check GPU and CUDA support."""
        return self.platform_manager.check_cuda_availability()

    def _check_system_permissions(self) -> Dict[str, bool]:
        """Check various system permissions that might affect functionality."""
        permissions = {
            'can_create_temp_files': False,
            'can_access_clipboard': False,
            'can_create_network_sockets': False
        }

        # Test temporary file creation
        try:
            temp_dir = self.platform_manager.get_temp_dir()
            test_file = temp_dir / 'test_permissions.tmp'
            test_file.write_text('test')
            test_file.unlink()
            permissions['can_create_temp_files'] = True
        except Exception:
            pass

        # Test clipboard access
        try:
            import pyperclip
            original = pyperclip.paste()
            pyperclip.copy('test')
            if pyperclip.paste() == 'test':
                permissions['can_access_clipboard'] = True
                pyperclip.copy(original)  # Restore
        except Exception:
            pass

        # Test network socket creation
        try:
            import socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.bind(('127.0.0.1', 0))  # Bind to any available port
            test_socket.close()
            permissions['can_create_network_sockets'] = True
        except Exception:
            pass

        return permissions

    def _generate_summary(self) -> Dict[str, Any]:
        """Generate a summary of the dependency check results."""
        summary = {
            'overall_status': 'unknown',
            'critical_missing': [],
            'warnings': [],
            'recommendations': []
        }

        # Check for critical missing dependencies
        python_packages = self.check_results.get('python_packages', {})
        for package, info in python_packages.items():
            if info['required'] and not info['available']:
                summary['critical_missing'].append(f"Python package: {package}")

        executables = self.check_results.get('executables', {})
        for exe, info in executables.items():
            if info['required'] and not info['available']:
                summary['critical_missing'].append(f"Executable: {exe}")

        # Check audio system
        audio = self.check_results.get('audio', {})
        if not audio.get('pyaudio_available'):
            summary['critical_missing'].append("Audio system (PyAudio)")
        elif not audio.get('default_device_accessible'):
            summary['warnings'].append("Default audio device not accessible")

        # Check permissions
        permissions = self.check_results.get('permissions', {})
        if not permissions.get('can_create_temp_files'):
            summary['critical_missing'].append("Temporary file creation permission")
        if not permissions.get('can_access_clipboard'):
            summary['warnings'].append("Clipboard access not available")

        # Determine overall status
        if summary['critical_missing']:
            summary['overall_status'] = 'critical_issues'
        elif summary['warnings']:
            summary['overall_status'] = 'warnings_present'
        else:
            summary['overall_status'] = 'all_good'

        # Generate recommendations
        gpu = self.check_results.get('gpu', {})
        if not gpu.get('available'):
            summary['recommendations'].append("Install CUDA for GPU acceleration")

        if not audio.get('default_device_accessible') and audio.get('device_count', 0) > 1:
            summary['recommendations'].append("Check audio device configuration")

        return summary

    def print_dependency_report(self):
        """Print a human-readable dependency report."""
        if not self.check_results:
            print("No dependency check results available. Run check_all_dependencies() first.")
            return

        print("\n" + "=" * 60)
        print("TRANSCRIPTIONSUITE DEPENDENCY REPORT")
        print("=" * 60)

        # Overall status
        summary = self.check_results.get('summary', {})
        status = summary.get('overall_status', 'unknown')

        status_messages = {
            'all_good': "✅ All dependencies satisfied",
            'warnings_present': "⚠️  Some non-critical issues found",
            'critical_issues': "❌ Critical dependencies missing",
            'unknown': "❓ Status unknown"
        }

        print(f"\nOverall Status: {status_messages.get(status, status)}")

        # Critical missing
        if summary.get('critical_missing'):
            print(f"\n❌ Critical Missing Dependencies:")
            for item in summary['critical_missing']:
                print(f"   • {item}")

        # Warnings
        if summary.get('warnings'):
            print(f"\n⚠️  Warnings:")
            for item in summary['warnings']:
                print(f"   • {item}")

        # Recommendations
        if summary.get('recommendations'):
            print(f"\n💡 Recommendations:")
            for item in summary['recommendations']:
                print(f"   • {item}")

        print("\n" + "=" * 60)


def check_dependencies_and_report():
    """Convenience function to check dependencies and print report."""
    checker = DependencyChecker()
    results = checker.check_all_dependencies()
    checker.print_dependency_report()
    return results


if __name__ == "__main__":
    check_dependencies_and_report()