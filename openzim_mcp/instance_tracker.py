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


def _safe_log(log_func: Any, message: str) -> None:
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
        transport: str = "stdio",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """Initialize a server instance with the given parameters."""
        self.pid = pid
        self.config_hash = config_hash
        self.allowed_directories = allowed_directories
        self.start_time = start_time
        self.server_name = server_name
        self.transport = transport
        self.host = host
        self.port = port
        self.last_heartbeat = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert instance to dictionary for JSON serialization."""
        return {
            "pid": self.pid,
            "config_hash": self.config_hash,
            "allowed_directories": self.allowed_directories,
            "start_time": self.start_time,
            "server_name": self.server_name,
            "transport": self.transport,
            "host": self.host,
            "port": self.port,
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
        """Create instance from dictionary.

        Coerces numeric fields so a corrupt or hand-edited instance file
        with the wrong type (e.g. ``"pid": "1234"``) raises ValueError —
        which is in get_all_instances()'s except tuple — instead of
        leaking a TypeError out of os.kill() much later.

        Records written before transport/host/port were tracked default to
        ``transport="stdio"``, ``host=None``, ``port=None``.
        """
        port_raw = data.get("port")
        instance = cls(
            pid=int(data["pid"]),
            config_hash=data["config_hash"],
            allowed_directories=data["allowed_directories"],
            start_time=float(data["start_time"]),
            server_name=data.get("server_name", "openzim-mcp"),
            transport=data.get("transport", "stdio"),
            host=data.get("host"),
            port=int(port_raw) if port_raw is not None else None,
        )
        instance.last_heartbeat = float(data.get("last_heartbeat", data["start_time"]))
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

    def __init__(self, registry_dir: Optional[Path] = None) -> None:
        """Initialize the tracker.

        Args:
            registry_dir: directory where per-instance JSON files live. Defaults
                to ``~/.openzim_mcp_instances``. Tests pass a tmp_path here so
                the user's real home is never touched.
        """
        self.instances_dir = (
            Path(registry_dir)
            if registry_dir is not None
            else Path.home() / ".openzim_mcp_instances"
        )
        self.instances_dir.mkdir(exist_ok=True)
        self.current_instance: Optional[ServerInstance] = None

    def register_instance(
        self,
        config_hash: str,
        allowed_directories: List[str],
        server_name: str = "openzim-mcp",
        transport: str = "stdio",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> ServerInstance:
        """Register a new server instance with file locking.

        Args:
            config_hash: SHA-256 of the running config.
            allowed_directories: dirs the instance serves.
            server_name: server identifier.
            transport: "stdio" (default) or "http".
            host: HTTP bind host (None for stdio).
            port: HTTP bind port (None for stdio).
        """
        pid = os.getpid()
        start_time = time.time()

        instance = ServerInstance(
            pid=pid,
            config_hash=config_hash,
            allowed_directories=allowed_directories,
            start_time=start_time,
            server_name=server_name,
            transport=transport,
            host=host,
            port=port,
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
            _safe_log(
                logger.info,
                f"Registered server instance: PID {pid}, config hash {config_hash[:8]}",
            )
        except (OSError, ValueError) as e:
            _safe_log(logger.warning, f"Failed to register instance: {e}")

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
                    _safe_log(logger.info, f"Unregistered server instance: PID {pid}")
        except OSError as e:
            if not silent:
                _safe_log(logger.warning, f"Failed to unregister instance: {e}")

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
        """Get only active (running) server instances.

        Pure read — does NOT delete stale instance files. Use
        ``cleanup_stale_instances`` for that. Keeping this side-effect-free
        avoids the surprise where two consecutive callers disagree on the
        stale count because the first one silently consumed them.
        """
        return [
            inst
            for inst in self.get_all_instances()
            if self._is_process_running(inst.pid)
        ]

    def list_running_instances(self) -> List[ServerInstance]:
        """Return live server instances (alias for get_active_instances)."""
        return self.get_active_instances()

    def detect_conflicts(
        self,
        current_config_hash: str,
        transport: str = "stdio",
    ) -> List[Dict[str, Any]]:
        """Return live instances that genuinely conflict with this server.

        Conflict semantics (transport-aware):

        * **stdio↔stdio, same config**: conflict (``multiple_instances``) —
          two stdio sessions for the same config compete for the same MCP
          client wiring.
        * **stdio↔stdio, different config**: not a conflict — they're parallel
          sessions over different working sets and don't interfere.
        * **stdio↔http** or **http↔anything**: not a conflict — different
          protocols / different ports, no resource race.

        Re-verifies each candidate's liveness right before reporting it,
        auto-unregistering phantom instance files (PID gone between
        ``get_active_instances()`` and now).

        Args:
            current_config_hash: hash of the calling server's config.
            transport: ``"stdio"`` (default) or ``"http"``.

        Returns:
            List of conflict-info dicts, one per genuine conflict.
        """
        # HTTP starters never conflict in tracker logic; the OS handles port
        # collisions and the protocols don't share state.
        if transport == "http":
            return []

        active_instances = self.get_active_instances()
        conflicts: List[Dict[str, Any]] = []
        phantoms_cleaned = 0

        for instance in active_instances:
            if instance.pid == os.getpid():
                continue  # Skip current instance

            # Defensive re-check — if the process is gone now, drop the file
            # and don't surface a stale "conflict".
            if not self._is_process_running(instance.pid):
                self.unregister_instance(instance.pid, silent=True)
                phantoms_cleaned += 1
                logger.debug(
                    f"Auto-cleaned phantom instance file for PID {instance.pid}"
                )
                continue

            existing_transport = getattr(instance, "transport", "stdio")
            # stdio-side: only flag genuine same-protocol same-config overlaps.
            if existing_transport != "stdio":
                continue
            if instance.config_hash != current_config_hash:
                continue

            conflicts.append(
                {
                    "type": "multiple_instances",
                    "instance": instance.to_dict(),
                    "severity": "warning",
                }
            )

        if phantoms_cleaned:
            logger.info(
                f"Auto-cleaned {phantoms_cleaned} phantom instance files during "
                f"conflict detection"
            )

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
