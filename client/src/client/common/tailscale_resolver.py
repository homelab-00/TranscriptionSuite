"""
Tailscale helper utilities for TranscriptionSuite client.

Provides automatic IP resolution when Tailscale MagicDNS fails,
which commonly occurs on mobile networks or when systemd-resolved
is not configured properly.

Usage:
    from client.common.tailscale_resolver import TailscaleResolver

    if TailscaleResolver.is_tailscale_hostname(hostname):
        ip, original = await TailscaleResolver.resolve_ip(hostname)
        if ip:
            # Use IP for connection, original for SSL server_hostname
            pass
"""

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

# Regex to match .ts.net hostnames
# Example: <your-machine>.tail1234.ts.net -> captures "desktop"
TS_NET_PATTERN = re.compile(r"^([^.]+)\.[^.]+\.ts\.net$", re.IGNORECASE)


class TailscaleResolver:
    """Resolves Tailscale device IPs from hostname when DNS fails."""

    @staticmethod
    def is_tailscale_hostname(hostname: str) -> bool:
        """Check if hostname is a .ts.net Tailscale hostname."""
        return hostname.lower().endswith(".ts.net")

    @staticmethod
    def extract_device_name(hostname: str) -> str | None:
        """
        Extract device name from .ts.net hostname.

        Example: '<your-machine>.tail1234.ts.net' -> 'desktop'

        Returns:
            Device name or None if pattern doesn't match
        """
        match = TS_NET_PATTERN.match(hostname.lower())
        return match.group(1) if match else None

    @staticmethod
    async def get_tailscale_status() -> dict | None:
        """
        Query tailscale status --json asynchronously.

        Returns:
            Parsed JSON dict or None if tailscale CLI not available/failed
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "tailscale",
                "status",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)

            if proc.returncode != 0:
                logger.debug(f"tailscale status failed: {stderr.decode().strip()}")
                return None

            return json.loads(stdout.decode())

        except FileNotFoundError:
            logger.debug("tailscale CLI not found in PATH")
            return None
        except asyncio.TimeoutError:
            logger.debug("tailscale status timed out (5s)")
            return None
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse tailscale status JSON: {e}")
            return None
        except Exception as e:
            logger.debug(f"Unexpected error querying tailscale: {e}")
            return None

    @classmethod
    async def resolve_ip(cls, hostname: str) -> tuple[str | None, str | None]:
        """
        Resolve a .ts.net hostname to its Tailscale IP.

        This is useful when MagicDNS is not working (e.g., on mobile networks,
        or when /etc/resolv.conf is overwritten by NetworkManager).

        Args:
            hostname: The .ts.net hostname (e.g., '<your-machine>.tail1234.ts.net')

        Returns:
            Tuple of (ipv4_address, original_hostname) or (None, None) if not found.
            The original hostname is returned for use with SSL server_hostname.
        """
        if not cls.is_tailscale_hostname(hostname):
            logger.debug(f"Not a Tailscale hostname: {hostname}")
            return None, None

        device_name = cls.extract_device_name(hostname)
        if not device_name:
            logger.warning(f"Could not extract device name from {hostname}")
            return None, None

        status = await cls.get_tailscale_status()
        if not status:
            logger.debug("Could not get tailscale status")
            return None, None

        # Check Self first (in case connecting to own machine)
        self_info = status.get("Self", {})
        self_dns = self_info.get("DNSName", "").rstrip(".").lower()
        if self_dns == hostname.lower():
            ips = self_info.get("TailscaleIPs", [])
            if ips:
                # Prefer IPv4 (first IP without colon)
                ipv4 = next((ip for ip in ips if ":" not in ip), None)
                if ipv4:
                    logger.info(f"Resolved {hostname} to {ipv4} (self)")
                    return ipv4, hostname

        # Check Peers
        peers = status.get("Peer", {})
        for peer_info in peers.values():
            peer_dns = peer_info.get("DNSName", "").rstrip(".").lower()
            if peer_dns == hostname.lower():
                ips = peer_info.get("TailscaleIPs", [])
                if ips:
                    ipv4 = next((ip for ip in ips if ":" not in ip), None)
                    if ipv4:
                        online = peer_info.get("Online", False)
                        logger.info(f"Resolved {hostname} to {ipv4} (online={online})")
                        return ipv4, hostname

        # Fallback: Try matching by device name if exact DNS match fails
        # This handles cases where tailnet suffix changed or hostname differs
        for peer_info in peers.values():
            peer_hostname = peer_info.get("HostName", "").lower()
            peer_dns_first = peer_info.get("DNSName", "").split(".")[0].lower()
            if peer_dns_first == device_name or peer_hostname == device_name:
                ips = peer_info.get("TailscaleIPs", [])
                if ips:
                    ipv4 = next((ip for ip in ips if ":" not in ip), None)
                    if ipv4:
                        logger.info(
                            f"Resolved {hostname} to {ipv4} (matched by device name '{device_name}')"
                        )
                        return ipv4, hostname

        logger.warning(f"Device '{device_name}' not found in tailscale status")
        return None, None
