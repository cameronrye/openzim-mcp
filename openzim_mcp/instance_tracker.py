"""Cross-platform instance tracking for OpenZIM MCP servers.

This module provides functionality to track running OpenZIM MCP server instances
using file-based tracking in the user's home directory, replacing the
platform-specific process detection approach.

File locking is used to prevent race conditions when multiple processes
attempt to read/write instance files simultaneously.
"""

import contextlib
import json
import logging
import os
import platform
import subprocess  # nosec B404 - needed for Windows process detection
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

# Platform-specific file locking imports
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)


@contextmanager
def file_lock(file_handle: Any, exclusive: bool = True) -> Generator[None, None, None]:
    """Cross-platform file locking context manager (best-effort, non-blocking).

    Note: This is a best-effort locking mechanism. If lock acquisition fails,
    operations will proceed without the lock. This means concurrent access from
    multiple processes may result in race conditions. For most use cases this
    is acceptable as the instance tracking is used for advisory purposes only.
    """
    lock_acquired = False

    if sys.platform == "win32":
        # Windows: use msvcrt for byte-range locking
        try:
            # Lock the first byte of the file
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            lock_acquired = True
        except OSError as e:
            # If locking fails (e.g., file already locked), proceed without lock
            # Log at debug level to help diagnose potential race conditions
            logger.debug(
                f"File lock acquisition failed (Windows), proceeding without lock: {e}"
            )

        try:
            yield
        finally:
            if lock_acquired:
                try:
                    # Seek to beginning before unlocking
                    file_handle.seek(0)
                    msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    # Unlock errors are non-fatal - file will be unlocked on close
                    pass
    else:
        # Unix: use fcntl for advisory locking
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(file_handle.fileno(), lock_type | fcntl.LOCK_NB)
            lock_acquired = True
        except OSError as e:
            # If locking fails (e.g., file already locked), proceed without lock
            # Log at debug level to help diagnose potential race conditions
            logger.debug(
                f"File lock acquisition failed (Unix), proceeding without lock: {e}"
            )

        try:
            yield
        finally:
            if lock_acquired:
                with contextlib.suppress(OSError):
                    fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


def atomic_write_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Atomically write JSON data to a file using temporary file and rename.

    This prevents corruption if the process is interrupted during writing.

    Args:
        file_path: Destination path for the JSON file
        data: Dictionary to write as JSON
    """
    # Create temp file in same directory to ensure same filesystem for atomic rename
    dir_path = file_path.parent
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=dir_path,
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2)
            tmp_file.flush()  # Ensure data is written to disk
            os.fsync(tmp_file.fileno())  # Force OS to write to disk
            tmp_path = Path(tmp_file.name)

        # Atomic rename (on POSIX systems; best-effort on Windows)
        tmp_path.replace(file_path)
    except OSError as write_error:
        # Clean up temp file if rename failed
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                if tmp_path.exists():
                    tmp_path.unlink()
        raise write_error


def safe_log(log_func: Any, message: str) -> None:
    """Safely log a message, handling cases where logging is shut down.

    This is particularly important for atexit handlers that may run after
    the logging system has been shut down.
    """
    try:
        log_func(message)
    except Exception:  # noqa: BLE001 - intentionally broad for shutdown safety
        # Catch all exceptions during logging, including:
        # - ValueError: I/O operation on closed file
        # - OSError: file descriptor issues
        # - AttributeError: logging objects may be None during shutdown
        # - Any other logging-related errors during shutdown
        # Try stderr as a fallback (may also fail during shutdown)
        with contextlib.suppress(Exception):  # nosec B110
            sys.stderr.write(f"{message}\n")


class ServerInstance:
    """Represents an OpenZIM MCP server instance."""

    def __init__(
        self,
        pid: int,
        config_hash: str,
        allowed_directories: List[str],
        start_time: float,
        server_name: str = "openzim-mcp",
    ) -> None:
        """Initialize a server instance with the given parameters."""
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
        except OSError:
            return False

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp."""
        self.last_heartbeat = time.time()


class InstanceTracker:
    """Manages OpenZIM MCP server instance tracking using file-based storage."""

    def __init__(self) -> None:
        """Initialize the instance tracker with the default directory."""
        self.instances_dir = Path.home() / ".openzim_mcp_instances"
        self.instances_dir.mkdir(exist_ok=True)
        self.current_instance: Optional[ServerInstance] = None

    def register_instance(
        self,
        config_hash: str,
        allowed_directories: List[str],
        server_name: str = "openzim-mcp",
    ) -> ServerInstance:
        """Register a new server instance with file locking."""
        pid = os.getpid()
        start_time = time.time()

        instance = ServerInstance(
            pid=pid,
            config_hash=config_hash,
            allowed_directories=allowed_directories,
            start_time=start_time,
            server_name=server_name,
        )

        # Save instance file with file locking to prevent race conditions
        # Note: We use direct writes instead of atomic_write_json because
        # tempfile.NamedTemporaryFile internally calls os.getpid(), which
        # can interfere with mocked PIDs in tests.
        instance_file = self.instances_dir / f"server_{pid}.json"
        try:
            with open(instance_file, "w") as f, file_lock(f, exclusive=True):
                json.dump(instance.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            safe_log(
                logger.info,
                f"Registered server instance: PID {pid}, config hash {config_hash[:8]}",
            )
        except (OSError, ValueError) as e:
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
        except OSError as e:
            if not silent:
                safe_log(logger.warning, f"Failed to unregister instance: {e}")

        if self.current_instance and self.current_instance.pid == pid:
            self.current_instance = None

    def get_all_instances(self) -> List[ServerInstance]:
        """Get all registered server instances with file locking."""
        instances = []

        for instance_file in self.instances_dir.glob("server_*.json"):
            try:
                with (
                    open(instance_file, "r") as f,
                    file_lock(f, exclusive=False),
                ):
                    data = json.load(f)
                instance = ServerInstance.from_dict(data)
                instances.append(instance)
            except (OSError, KeyError, ValueError) as e:
                logger.warning(f"Failed to load instance from {instance_file}: {e}")
                # Clean up corrupted files
                with contextlib.suppress(OSError):
                    instance_file.unlink()

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
                with (
                    open(instance_file, "r") as f,
                    file_lock(f, exclusive=False),
                ):
                    data = json.load(f)
                instance = ServerInstance.from_dict(data)

                if not self._is_process_running(instance.pid):
                    instance_file.unlink()
                    cleaned_count += 1
                    logger.debug(f"Cleaned up stale instance file: {instance_file}")
            except (OSError, KeyError, ValueError):
                # If we can't read the file, it's probably corrupted
                with contextlib.suppress(OSError):
                    instance_file.unlink()
                    cleaned_count += 1
                    logger.debug(f"Cleaned up corrupted instance file: {instance_file}")

        return cleaned_count

    def update_heartbeat(self) -> None:
        """Update heartbeat for current instance with file locking."""
        if self.current_instance:
            self.current_instance.update_heartbeat()
            # Update the instance file with file locking
            instance_file = (
                self.instances_dir / f"server_{self.current_instance.pid}.json"
            )
            try:
                with open(instance_file, "w") as f, file_lock(f, exclusive=True):
                    json.dump(self.current_instance.to_dict(), f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as e:
                logger.warning(f"Failed to update heartbeat: {e}")

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running by PID."""
        if platform.system() == "Windows":
            try:
                result = subprocess.run(  # nosec B603 B607 - safe, hardcoded command
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                # tasklist always returns 0, so check if PID appears in output
                # When no process matches, output contains "No tasks are running"
                # or similar message instead of the actual PID
                return str(pid) in result.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.debug(f"Failed to check process {pid} on Windows: {e}")
                return False
        else:
            try:
                # On Unix-like systems, sending signal 0 checks if process exists
                os.kill(pid, 0)
                return True
            except PermissionError:
                # Process exists but we don't have permission to signal it
                return True
            except OSError:
                return False
