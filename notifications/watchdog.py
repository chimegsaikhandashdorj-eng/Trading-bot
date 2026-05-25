"""
Watchdog — periodic heartbeat so external monitors can detect a frozen bot.

Two complementary mechanisms:

1. **Heartbeat file** — touch `logs/heartbeat.txt` every cycle. External
   processes (cron, k8s liveness probe, systemd watchdog) can `stat` the
   file and alert if mtime > N minutes.

2. **Self-tick monitor** — if `tick()` hasn't been called in
   `inactivity_threshold_sec` (bot scheduler frozen?), the background
   thread Telegrams a CRITICAL alert and writes a stall marker.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from utils.logger import get_logger

if TYPE_CHECKING:
    from notifications.telegram_notifier import TelegramNotifier

log = get_logger("Watchdog")

HEARTBEAT_FILE = Path("logs/heartbeat.txt")
STALL_MARKER = Path("logs/STALL")


class Watchdog:
    """
    Heartbeat-based liveness monitor.

    Usage
    -----
    >>> wd = Watchdog(notifier)
    >>> # call from any healthy code path
    >>> wd.tick()
    >>> # external monitors check `logs/heartbeat.txt` mtime
    """

    def __init__(
        self,
        notifier: "Optional[TelegramNotifier]" = None,
        inactivity_threshold_sec: int = 3600,
        check_interval_sec: int = 60,
    ) -> None:
        self.notifier = notifier
        self.inactivity_threshold = inactivity_threshold_sec
        self.check_interval = check_interval_sec
        self._last_tick: float = time.time()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._alerted = False
        self._thread: Optional[threading.Thread] = None
        self._ensure_log_dir()
        self.tick()
        self._start()

    @staticmethod
    def _ensure_log_dir() -> None:
        try:
            HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning(f"heartbeat dir create failed: {exc}")

    def tick(self) -> None:
        """Call from any healthy code path. Updates timestamp and heartbeat file."""
        now = time.time()
        with self._lock:
            self._last_tick = now
            self._alerted = False
        try:
            HEARTBEAT_FILE.write_text(str(int(now)), encoding="utf-8")
            if STALL_MARKER.exists():
                STALL_MARKER.unlink()
        except OSError as exc:
            log.warning(f"heartbeat write failed: {exc}")

    def _start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="WatchdogMonitor", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped.wait(self.check_interval):
            with self._lock:
                age = time.time() - self._last_tick
                already_alerted = self._alerted
            if age >= self.inactivity_threshold and not already_alerted:
                msg = (
                    f"⚠️ WATCHDOG: no tick in {int(age)}s "
                    f"(threshold={self.inactivity_threshold}s). Bot may be frozen."
                )
                log.critical(msg)
                try:
                    STALL_MARKER.write_text(str(int(time.time())), encoding="utf-8")
                except OSError:
                    pass
                if self.notifier is not None:
                    self.notifier.send(msg)
                with self._lock:
                    self._alerted = True

    def stop(self) -> None:
        """Stop the monitor thread. Safe to call repeatedly."""
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
