import subprocess
import os


def run_cava_visualizer():
    """
    Launches the CAVA audio visualizer as a subprocess, using a local
    configuration file.
    """
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(script_dir, "cava.config")

    # Check if the configuration file exists
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        return

    command = ["cava", "-p", config_path]

    print(f"Starting CAVA with command: {' '.join(command)}")
    print("Press Ctrl+C in the terminal to stop the visualizer.")

    process = None

    try:
        # Using subprocess.Popen to run cava as a child process.
        # This allows cava to run continuously in the terminal.
        process = subprocess.Popen(command)

        # Wait for the process to terminate. The user can stop it with Ctrl+C.
        process.wait()

    except FileNotFoundError:
        print("\nError: The 'cava' command was not found.")
        print("Please ensure CAVA is installed and accessible in your system's PATH.")
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        print("\nCAVA process interrupted by user. Shutting down.")
        if process and process.poll() is None:
            process.terminate()
            # Wait a moment to ensure it has terminated
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                print("CAVA process did not terminate gracefully, forcing shutdown.")
    finally:
        print("CAVA has stopped.")


if __name__ == "__main__":
    run_cava_visualizer()
