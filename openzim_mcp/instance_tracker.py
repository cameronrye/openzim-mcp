"""
Cross-platform instance tracking for OpenZIM MCP servers.

This module provides functionality to track running OpenZIM MCP server instances
using file-based tracking in the user's home directory, replacing the
platform-specific process detection approach.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def safe_log(log_func: Any, message: str) -> None:
    """
    Safely log a message, handling cases where logging system is shut down.

    This is particularly important for atexit handlers that may run after
    the logging system has been shut down.
    """
    try:
        log_func(message)
    except Exception:
        # Catch all exceptions during logging, including:
        # - ValueError: I/O operation on closed file
        # - OSError: file descriptor issues
        # - AttributeError: logging objects may be None during shutdown
        # - Any other logging-related errors during shutdown
        pass


class ServerInstance:
    """Represents an OpenZIM MCP server instance."""

    def __init__(
        self,
        pid: int,
        config_hash: str,
        allowed_directories: List[str],
        start_time: float,
        server_name: str = "openzim-mcp",
    ):
        self.pid = pid
        self.config_hash = config_hash
        self.allowed_directories = allowed_directories
        self.start_time = start_time
        self.server_name = server_name
        self.last_heartbeat = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert instance to dictionary for JSON serialization."""
        return {
            "pid": self.pid,
            "config_hash": self.config_hash,
            "allowed_directories": self.allowed_directories,
            "start_time": self.start_time,
            "server_name": self.server_name,
            "last_heartbeat": self.last_heartbeat,
            "start_time_iso": datetime.fromtimestamp(
                self.start_time, tz=timezone.utc
            ).isoformat(),
            "last_heartbeat_iso": datetime.fromtimestamp(
                self.last_heartbeat, tz=timezone.utc
            ).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServerInstance":
        """Create instance from dictionary."""
        instance = cls(
            pid=data["pid"],
            config_hash=data["config_hash"],
            allowed_directories=data["allowed_directories"],
            start_time=data["start_time"],
            server_name=data.get("server_name", "openzim-mcp"),
        )
        instance.last_heartbeat = data.get("last_heartbeat", data["start_time"])
        return instance

    def is_alive(self) -> bool:
        """Check if the process is still running."""
        try:
            # On Unix-like systems, sending signal 0 checks if process exists
            # On Windows, this will raise an exception for non-existent processes
            os.kill(self.pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp."""
        self.last_heartbeat = time.time()


class InstanceTracker:
    """Manages OpenZIM MCP server instance tracking using file-based storage."""

    def __init__(self) -> None:
        self.instances_dir = Path.home() / ".openzim_mcp_instances"
        self.instances_dir.mkdir(exist_ok=True)
        self.current_instance: Optional[ServerInstance] = None

    def register_instance(
        self,
        config_hash: str,
        allowed_directories: List[str],
        server_name: str = "openzim-mcp",
    ) -> ServerInstance:
        """Register a new server instance."""
        pid = os.getpid()
        start_time = time.time()

        instance = ServerInstance(
            pid=pid,
            config_hash=config_hash,
            allowed_directories=allowed_directories,
            start_time=start_time,
            server_name=server_name,
        )

        # Save instance file
        instance_file = self.instances_dir / f"server_{pid}.json"
        try:
            with open(instance_file, "w") as f:
                json.dump(instance.to_dict(), f, indent=2)
            safe_log(
                logger.info,
                f"Registered server instance: PID {pid}, config hash {config_hash[:8]}",
            )
        except Exception as e:
            safe_log(logger.warning, f"Failed to register instance: {e}")

        self.current_instance = instance
        return instance

    def unregister_instance(
        self, pid: Optional[int] = None, silent: bool = False
    ) -> None:
        """Unregister a server instance."""
        if pid is None:
            pid = os.getpid()

        instance_file = self.instances_dir / f"server_{pid}.json"
        try:
            if instance_file.exists():
                instance_file.unlink()
                if not silent:
                    safe_log(logger.info, f"Unregistered server instance: PID {pid}")
        except Exception as e:
            if not silent:
                safe_log(logger.warning, f"Failed to unregister instance: {e}")

        if self.current_instance and self.current_instance.pid == pid:
            self.current_instance = None

    def get_all_instances(self) -> List[ServerInstance]:
        """Get all registered server instances."""
        instances = []

        for instance_file in self.instances_dir.glob("server_*.json"):
            try:
                with open(instance_file, "r") as f:
                    data = json.load(f)
                instance = ServerInstance.from_dict(data)
                instances.append(instance)
            except Exception as e:
                logger.warning(f"Failed to load instance from {instance_file}: {e}")
                # Clean up corrupted files
                try:
                    instance_file.unlink()
                except Exception:
                    pass

        return instances

    def get_active_instances(self) -> List[ServerInstance]:
        """Get only active (running) server instances."""
        all_instances = self.get_all_instances()
        active_instances = []

        for instance in all_instances:
            if self._is_process_running(instance.pid):
                active_instances.append(instance)
            else:
                # Clean up stale instance files
                self.unregister_instance(instance.pid)

        return active_instances

    def detect_conflicts(self, current_config_hash: str) -> List[Dict[str, Any]]:
        """Detect potential conflicts with other server instances."""
        active_instances = self.get_active_instances()
        conflicts = []

        for instance in active_instances:
            if instance.pid == os.getpid():
                continue  # Skip current instance

            conflict_info = {
                "type": "multiple_instances",
                "instance": instance.to_dict(),
                "severity": "warning",
            }

            # Check for configuration conflicts
            if instance.config_hash != current_config_hash:
                conflict_info["type"] = "configuration_mismatch"
                conflict_info["severity"] = "high"
                conflict_info["details"] = "Different server configurations detected"

            conflicts.append(conflict_info)

        return conflicts

    def cleanup_stale_instances(self) -> int:
        """Clean up stale instance files and return count of cleaned files."""
        cleaned_count = 0

        for instance_file in self.instances_dir.glob("server_*.json"):
            try:
                with open(instance_file, "r") as f:
                    data = json.load(f)
                instance = ServerInstance.from_dict(data)

                if not self._is_process_running(instance.pid):
                    instance_file.unlink()
                    cleaned_count += 1
                    logger.debug(f"Cleaned up stale instance file: {instance_file}")
            except Exception:
                # If we can't read the file, it's probably corrupted
                try:
                    instance_file.unlink()
                    cleaned_count += 1
                    logger.debug(f"Cleaned up corrupted instance file: {instance_file}")
                except Exception:
                    pass

        return cleaned_count

    def update_heartbeat(self) -> None:
        """Update heartbeat for current instance."""
        if self.current_instance:
            self.current_instance.update_heartbeat()
            # Update the instance file
            instance_file = (
                self.instances_dir / f"server_{self.current_instance.pid}.json"
            )
            try:
                with open(instance_file, "w") as f:
                    json.dump(self.current_instance.to_dict(), f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to update heartbeat: {e}")

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running by PID."""
        import platform
        import subprocess

        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return False
        else:
            try:
                # On Unix-like systems, sending signal 0 checks if process exists
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False
            except PermissionError:
                # Process exists but we don't have permission to signal it
                return True
