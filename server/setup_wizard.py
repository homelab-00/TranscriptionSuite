"""
First-run setup wizard for TranscriptionSuite Docker container.

On first run, this wizard prompts the user for required configuration:
- HuggingFace token (for diarization models)
- Admin authentication token
- Optional settings

Configuration is saved to persistent storage (/data/config/).
"""

import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

# Paths for persistent storage
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_DIR = DATA_DIR / "config"
SETUP_COMPLETE_FILE = CONFIG_DIR / ".setup_complete"
SECRETS_FILE = CONFIG_DIR / "secrets.json"


def is_setup_complete() -> bool:
    """Check if initial setup has been completed."""
    return SETUP_COMPLETE_FILE.exists()


def load_secrets() -> dict[str, Any]:
    """Load saved secrets from persistent storage."""
    if SECRETS_FILE.exists():
        with open(SECRETS_FILE) as f:
            return json.load(f)
    return {}


def save_secrets(secrets_data: dict[str, Any]) -> None:
    """Save secrets to persistent storage."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Set restrictive permissions
    with open(SECRETS_FILE, "w") as f:
        json.dump(secrets_data, f, indent=2)

    os.chmod(SECRETS_FILE, 0o600)


def generate_admin_token() -> str:
    """Generate a secure random admin token."""
    return secrets.token_urlsafe(32)


def print_banner() -> None:
    """Print setup wizard banner."""
    print()
    print("=" * 60)
    print("  TranscriptionSuite - First Run Setup")
    print("=" * 60)
    print()
    print("This wizard will help you configure the server.")
    print("Configuration will be saved to persistent storage.")
    print()


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt for yes/no answer."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(question + suffix).strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'")


def prompt_string(question: str, default: str = "", secret: bool = False) -> str:
    """Prompt for string input."""
    if default:
        suffix = f" [{default}]: "
    else:
        suffix = ": "

    if secret:
        import getpass

        value = getpass.getpass(question + suffix)
    else:
        value = input(question + suffix).strip()

    return value if value else default


def run_setup_wizard(force: bool = False) -> dict[str, Any]:
    """
    Run the interactive setup wizard.

    Args:
        force: Run setup even if already completed

    Returns:
        Configuration dict with all settings
    """
    if is_setup_complete() and not force:
        print("Setup already complete. Use --force-setup to reconfigure.")
        return load_secrets()

    print_banner()

    secrets_data = load_secrets()

    # HuggingFace Token (required for diarization)
    print("=" * 40)
    print("HuggingFace Token")
    print("=" * 40)
    print()
    print("A HuggingFace token is required for speaker diarization.")
    print("Get your token at: https://huggingface.co/settings/tokens")
    print()
    print("You must also accept the model licenses:")
    print("  - https://huggingface.co/pyannote/speaker-diarization-3.1")
    print("  - https://huggingface.co/pyannote/segmentation-3.0")
    print()

    current_hf = secrets_data.get("huggingface_token", "")
    if current_hf:
        print(f"Current token: {current_hf[:8]}...{current_hf[-4:]}")
        if not prompt_yes_no("Update HuggingFace token?", default=False):
            hf_token = current_hf
        else:
            hf_token = prompt_string("Enter HuggingFace token", secret=True)
    else:
        hf_token = prompt_string(
            "Enter HuggingFace token (or press Enter to skip)", secret=True
        )

    if hf_token:
        secrets_data["huggingface_token"] = hf_token
        print("✓ HuggingFace token saved")
    else:
        print("⚠ No HuggingFace token - diarization will be disabled")

    print()

    # Admin Token
    print("=" * 40)
    print("Admin Authentication Token")
    print("=" * 40)
    print()
    print("An admin token is used to authenticate API requests.")
    print("This token has full access to all server features.")
    print()

    current_admin = secrets_data.get("admin_token", "")
    if current_admin:
        print(f"Current admin token exists: {current_admin[:8]}...")
        if prompt_yes_no("Generate new admin token?", default=False):
            admin_token = generate_admin_token()
            print(f"\n✓ New admin token generated: {admin_token}")
            print("\n⚠ SAVE THIS TOKEN - it will not be shown again!")
        else:
            admin_token = current_admin
    else:
        if prompt_yes_no("Generate admin token automatically?", default=True):
            admin_token = generate_admin_token()
            print(f"\n✓ Admin token generated: {admin_token}")
            print("\n⚠ SAVE THIS TOKEN - it will not be shown again!")
        else:
            admin_token = prompt_string("Enter custom admin token", secret=True)

    secrets_data["admin_token"] = admin_token

    print()

    # Optional: LM Studio URL
    print("=" * 40)
    print("LM Studio Integration (Optional)")
    print("=" * 40)
    print()
    print("TranscriptionSuite can connect to LM Studio for AI chat features.")
    print("Default URL: http://host.docker.internal:1234")
    print()

    current_lm = secrets_data.get("lm_studio_url", "http://host.docker.internal:1234")
    if prompt_yes_no("Configure LM Studio URL?", default=False):
        lm_url = prompt_string("LM Studio URL", default=current_lm)
        secrets_data["lm_studio_url"] = lm_url
    else:
        secrets_data["lm_studio_url"] = current_lm

    print()

    # Save configuration
    print("=" * 40)
    print("Saving Configuration")
    print("=" * 40)
    print()

    save_secrets(secrets_data)

    # Mark setup as complete
    SETUP_COMPLETE_FILE.touch()

    print("✓ Configuration saved to:", SECRETS_FILE)
    print("✓ Setup complete!")
    print()
    print("You can re-run setup anytime with: --force-setup")
    print()

    return secrets_data


def get_config() -> dict[str, Any]:
    """
    Get configuration, running setup wizard if needed.

    For non-interactive environments (e.g., Docker without TTY),
    configuration can be provided via environment variables:
      - HUGGINGFACE_TOKEN
      - ADMIN_TOKEN
      - LM_STUDIO_URL
    """
    # Check for environment variable overrides
    env_config = {}

    if os.environ.get("HUGGINGFACE_TOKEN"):
        env_config["huggingface_token"] = os.environ["HUGGINGFACE_TOKEN"]

    if os.environ.get("ADMIN_TOKEN"):
        env_config["admin_token"] = os.environ["ADMIN_TOKEN"]

    if os.environ.get("LM_STUDIO_URL"):
        env_config["lm_studio_url"] = os.environ["LM_STUDIO_URL"]

    # If all required config is in env vars, use that
    if env_config.get("admin_token"):
        # Merge with any saved config
        saved_config = load_secrets()
        saved_config.update(env_config)
        save_secrets(saved_config)
        return saved_config

    # Check if setup is complete
    if is_setup_complete():
        return load_secrets()

    # Check if we have a TTY for interactive setup
    if sys.stdin.isatty():
        return run_setup_wizard()
    else:
        # Non-interactive mode without config
        print("=" * 60)
        print("ERROR: First-run setup required but no TTY available.")
        print("=" * 60)
        print()
        print("Provide configuration via environment variables:")
        print("  ADMIN_TOKEN=<token>           # Required")
        print("  HUGGINGFACE_TOKEN=<token>     # Optional, for diarization")
        print("  LM_STUDIO_URL=<url>           # Optional")
        print()
        print("Or run the container interactively:")
        print("  docker run -it transcriptionsuite --setup")
        print()
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TranscriptionSuite Setup Wizard")
    parser.add_argument("--force", action="store_true", help="Force re-run setup")
    parser.add_argument("--show", action="store_true", help="Show current config")
    args = parser.parse_args()

    if args.show:
        config = load_secrets()
        print("Current configuration:")
        for key, value in config.items():
            if "token" in key.lower():
                print(
                    f"  {key}: {value[:8]}...{value[-4:] if len(value) > 12 else '***'}"
                )
            else:
                print(f"  {key}: {value}")
    else:
        run_setup_wizard(force=args.force)
