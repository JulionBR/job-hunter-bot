"""JSON persistence shared by the bot and the scheduled jobs (separate processes)."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jobbot.models import Job, JobStatus, PendingRequest, User


class JsonStore:
    """File-locked JSON store with atomic writes. One instance per state directory."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path = state_dir / "state.lock"

    def read(self, path: Path, default: Any) -> Any:
        """Return parsed JSON, or ``default`` if the file is missing or invalid."""
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def write(self, path: Path, value: Any) -> None:
        """Atomically write ``value`` as JSON (tmp file + replace)."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1))
        tmp.replace(path)

    @contextmanager
    def edit(self, path: Path, default: Any) -> Iterator[Any]:
        """Read under an exclusive lock, let the caller mutate the value, then write it back.

        Must not be nested: the lock is not re-entrant, so a nested call deadlocks.
        If the body raises, nothing is written.
        """
        with self._lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = self.read(path, default)
            yield value
            self.write(path, value)


class UserRepository:
    """Approved candidates (users.json, keyed by chat id as string)."""

    def __init__(self, store: JsonStore) -> None:
        self._store = store
        self._path = store.state_dir / "users.json"

    def all(self) -> list[User]:
        data = self._store.read(self._path, {})
        return [User.from_dict(chat, raw) for chat, raw in data.items()]

    def get(self, chat_id: int) -> User | None:
        raw = self._store.read(self._path, {}).get(str(chat_id))
        return None if raw is None else User.from_dict(chat_id, raw)

    def save(self, user: User) -> None:
        with self._store.edit(self._path, {}) as data:
            data[str(user.chat_id)] = user.to_dict()

    def remove(self, chat_id: int) -> bool:
        with self._store.edit(self._path, {}) as data:
            return data.pop(str(chat_id), None) is not None

    def update(self, chat_id: int, fn: Callable[[User], None]) -> User | None:
        """Apply ``fn`` to the stored user atomically; returns the updated user or None if absent."""
        with self._store.edit(self._path, {}) as data:
            raw = data.get(str(chat_id))
            if raw is None:
                return None
            user = User.from_dict(chat_id, raw)
            fn(user)
            data[str(chat_id)] = user.to_dict()
            return user


class PendingRepository:
    """Access requests awaiting admin approval (pending.json)."""

    def __init__(self, store: JsonStore) -> None:
        self._store = store
        self._path = store.state_dir / "pending.json"

    def all(self) -> list[PendingRequest]:
        data = self._store.read(self._path, {})
        return [PendingRequest.from_dict(chat, raw) for chat, raw in data.items()]

    def add_if_new(self, request: PendingRequest) -> bool:
        """Store the request unless one exists for that chat; True if it was added."""
        with self._store.edit(self._path, {}) as data:
            key = str(request.chat_id)
            if key in data:
                return False
            data[key] = request.to_dict()
            return True

    def pop(self, chat_id: int) -> PendingRequest | None:
        with self._store.edit(self._path, {}) as data:
            raw = data.pop(str(chat_id), None)
        return None if raw is None else PendingRequest.from_dict(chat_id, raw)


class JobRepository:
    """Jobs found for one candidate (jobs-<chat>.json, keyed by job id)."""

    def __init__(self, store: JsonStore, chat_id: int) -> None:
        self._store = store
        self.chat_id = chat_id
        self._path = store.state_dir / f"jobs-{chat_id}.json"

    def all(self) -> list[Job]:
        data = self._store.read(self._path, {})
        return [Job.from_dict(raw, job_id) for job_id, raw in data.items()]

    def get(self, job_id: str) -> Job | None:
        raw = self._store.read(self._path, {}).get(job_id)
        return None if raw is None else Job.from_dict(raw, job_id)

    def recent_rejected(self, limit: int = 15) -> list[Job]:
        """Read-only: up to ``limit`` ``SKIPPED`` jobs, newest first.

        "Newest" is by when the job was found (reverse insertion order), not when it was turned down:
        no rejection timestamp is stored. With fewer than ``limit`` rejections the difference does not matter.
        """
        data = self._store.read(self._path, {})
        rejected: list[Job] = []
        for job_id, raw in reversed(list(data.items())):
            if len(rejected) >= limit:
                break
            if raw.get("status") == JobStatus.SKIPPED:
                rejected.append(Job.from_dict(raw, job_id))
        return rejected

    def add_new(self, items: list[Job]) -> list[Job]:
        """Insert already-built jobs (see ``Job.from_shortlist``) whose id is unknown.

        Contract: callers convert raw shortlist items with ``Job.from_shortlist`` first and set
        status/date; jobs without a URL or with a known id are skipped. Returns those added.
        """
        added: list[Job] = []
        with self._store.edit(self._path, {}) as data:
            for job in items:
                if job.url and job.job_id not in data:
                    data[job.job_id] = job.to_dict()
                    added.append(job)
        return added

    def set_status(self, job_id: str, status: JobStatus) -> bool:
        with self._store.edit(self._path, {}) as data:
            if job_id not in data:
                return False
            data[job_id]["status"] = str(status)
            return True

    def take_waiting(self) -> list[Job]:
        """Move every ``WAITING`` job to ``NEW`` and return them (with the new status)."""
        released: list[Job] = []
        with self._store.edit(self._path, {}) as data:
            for job_id, raw in data.items():
                if raw.get("status") == JobStatus.WAITING:
                    raw["status"] = str(JobStatus.NEW)
                    released.append(Job.from_dict(raw, job_id))
        return released
