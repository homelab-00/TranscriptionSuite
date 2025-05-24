#!/usr/bin/env python3
# command_server.py
#
# TCP server for handling hotkey commands from AutoHotkey
#
# This module:
# - Sets up a TCP server to listen for commands from the AutoHotkey script
# - Receives and processes hotkey commands
# - Dispatches commands to appropriate handlers in the orchestrator

import socket
import threading
import logging
from typing import Dict, Callable, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("stt_orchestrator.log"),
    ]
)

# Try to import Rich for console output with color support
try:
    from rich.console import Console
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

class CommandServer:
    """
    TCP server for receiving and processing commands from the AutoHotkey script.
    """
    
    def __init__(self, host='127.0.0.1', port=35000):
        """Initialize the command server with host and port."""
        self.host = host
        self.port = port
        self.running = False
        self.server_thread = None
        self.command_handlers = {}
        
    def register_command_handler(self, command: str, handler: Callable):
        """Register a handler function for a specific command."""
        self.command_handlers[command] = handler
        
    def register_handlers(self, handlers_dict: Dict[str, Callable]):
        """Register multiple command handlers at once."""
        for command, handler in handlers_dict.items():
            self.register_command_handler(command, handler)
    
    def start(self):
        """Start the TCP server to listen for commands."""
        if self.running:
            logging.warning("Command server is already running")
            return
            
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        logging.info(f"TCP server started on {self.host}:{self.port}")
    
    def stop(self, timeout: Optional[float] = 2.0):
        """Stop the TCP server."""
        if not self.running:
            return
            
        self.running = False
        
        # Only try to join the server thread if we're not currently in it
        current_thread_id = threading.get_ident()
        server_thread_id = self.server_thread.ident if self.server_thread else None
        
        try:
            if (self.server_thread and self.server_thread.is_alive() and 
                current_thread_id != server_thread_id):
                self.server_thread.join(timeout=timeout)
        except Exception as e:
            logging.error(f"Error joining server thread: {e}")
            
        logging.info("TCP server stopped")
    
    def _run_server(self):
        """Run the TCP server loop."""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server_socket.bind((self.host, self.port))
            server_socket.listen(5)
            server_socket.settimeout(1)  # Allow checking self.running every second
            
            while self.running:
                try:
                    client_socket, addr = server_socket.accept()
                    data = client_socket.recv(1024).decode('utf-8').strip()
                    logging.info(f"Received command: {data}")
                    
                    # Process command
                    self._handle_command(data)
                    
                    client_socket.close()
                except socket.timeout:
                    continue  # Just a timeout, check self.running and continue
                except Exception as e:
                    logging.error(f"Error handling client connection: {e}")
        except Exception as e:
            logging.error(f"Server error: {e}")
        finally:
            server_socket.close()
    
    def _handle_command(self, command: str):
        """Process commands received from AutoHotkey."""
        try:
            if command in self.command_handlers:
                self.command_handlers[command]()
            else:
                logging.error(f"Unknown command: {command}")
                safe_print(f"Unknown command: {command}", "error")
        except Exception as e:
            logging.error(f"Error handling command {command}: {e}")
            safe_print(f"Error handling command {command}: {e}", "error")