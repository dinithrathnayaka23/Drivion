"""Background services and their lifecycle.

A *service* is a long-running piece of work (wake-word listener, camera
reader, speech recogniser) that must never run on the UI thread. Every
service can be started and stopped, and stopping must release its hardware.

``ThreadedService`` runs ``run()`` in its own thread and gives it a stop flag.
``ServiceManager`` starts services in order and stops them in reverse order,
continuing even if one of them fails to stop, so one broken service can't
leave the microphone or camera open.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

CrashHandler = Callable[[str, BaseException], None]


class Service(Protocol):
    name: str

    def start(self) -> None: ...
    def stop(self, timeout: float = 2.0) -> bool: ...
    @property
    def is_running(self) -> bool: ...


class ThreadedService(ABC):
    """Base class: subclasses implement ``run`` and check ``stop_event`` often."""

    def __init__(self, name: str, on_crash: CrashHandler | None = None) -> None:
        self.name = name
        self._on_crash = on_crash
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            log.debug("Service %s already running", self.name)
            return
        self._stop_event.clear()
        # daemon=True is only a last resort so a hung service can't keep the
        # process alive forever; normal shutdown always calls stop() and joins.
        self._thread = threading.Thread(
            target=self._run_safely, name=f"svc-{self.name}", daemon=True
        )
        self._thread.start()
        log.info("Service %s started", self.name)

    def stop(self, timeout: float = 2.0) -> bool:
        """Ask the service to stop and wait. Returns False if it didn't stop in time."""
        self._stop_event.set()
        thread = self._thread
        if thread is None:
            return True
        if thread is not threading.current_thread():
            thread.join(timeout)
        stopped = not thread.is_alive()
        if stopped:
            self._thread = None
            log.info("Service %s stopped", self.name)
        else:
            log.error("Service %s did not stop within %.1fs", self.name, timeout)
        return stopped

    def _run_safely(self) -> None:
        try:
            self.run(self._stop_event)
        except Exception as exc:
            log.exception("Service %s crashed", self.name)
            if self._on_crash is not None:
                self._on_crash(self.name, exc)
        finally:
            self.cleanup()

    @abstractmethod
    def run(self, stop_event: threading.Event) -> None:
        """Do the work until ``stop_event`` is set. Runs in the service thread."""

    def cleanup(self) -> None:
        """Release resources (mic, camera, models). Always called when run() ends."""


class ServiceManager:
    def __init__(self) -> None:
        self._services: list[Service] = []
        self._lock = threading.Lock()

    def register(self, service: Service) -> None:
        with self._lock:
            if any(s.name == service.name for s in self._services):
                raise ValueError(f"Service {service.name!r} is already registered")
            self._services.append(service)

    @property
    def services(self) -> list[Service]:
        return list(self._services)

    def start_all(self) -> None:
        """Start every service; if one fails, stop the ones already started."""
        started: list[Service] = []
        for service in self.services:
            try:
                service.start()
            except Exception:
                log.exception("Service %s failed to start; rolling back", service.name)
                self._stop(reversed(started))
                raise
            started.append(service)

    def stop_all(self, timeout: float = 2.0) -> list[str]:
        """Stop every service in reverse start order. Returns names that failed to stop."""
        return self._stop(reversed(self.services), timeout)

    @staticmethod
    def _stop(services, timeout: float = 2.0) -> list[str]:
        failed = []
        for service in services:
            try:
                if not service.stop(timeout):
                    failed.append(service.name)
            except Exception:
                log.exception("Service %s raised while stopping", service.name)
                failed.append(service.name)
        return failed
