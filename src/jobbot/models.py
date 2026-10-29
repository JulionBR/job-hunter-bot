"""Domain models. ``from_dict`` accepts legacy Portuguese keys; ``to_dict`` always writes English keys."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger("jobbot")


class JobStatus(StrEnum):
    """Job lifecycle. Values are persisted and shown in /status, so they stay in Portuguese."""

    NEW = "nova"
    WAITING = "aguardando"
    QUEUED = "na_fila"
    SKIPPED = "pulada"
    GENERATED = "gerada"
    SENT = "enviada"
    ERROR = "erro"


def _pick(data: Mapping[str, Any], new: str, old: str, default: Any = "") -> Any:
    if new in data:
        return data[new]
    return data.get(old, default)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


@dataclass
class User:
    chat_id: int
    name: str
    workspace: Path
    profile_ready: bool = False
    since: str = ""
    manual_search_day: str = ""
    pending_result: str | None = None
    profile_session: str | None = None  # UUID of the open /perfil conversation (survives restarts)
    profile_session_started: str | None = None  # ISO timestamp; old sessions expire
    pcd: bool | None = None  # None = unknown: the bot leaves the PcD portals untouched

    @classmethod
    def from_dict(cls, chat_id: int | str, data: Mapping[str, Any]) -> User:
        pending = _pick(data, "pending_result", "resultado_pendente", None)
        session = data.get("profile_session")
        started = data.get("profile_session_started")
        pcd = data.get("pcd")
        return cls(
            chat_id=int(chat_id),
            name=_text(_pick(data, "name", "nome")),
            workspace=Path(_text(_pick(data, "workspace", "pasta"))),
            profile_ready=bool(_pick(data, "profile_ready", "perfil_ok", False)),
            since=_text(_pick(data, "since", "desde")),
            manual_search_day=_text(_pick(data, "manual_search_day", "busca_manual")),
            pending_result=None if pending is None else str(pending),
            profile_session=None if session is None else str(session),
            profile_session_started=None if started is None else str(started),
            pcd=pcd if isinstance(pcd, bool) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise without ``chat_id`` (it is the key in users.json)."""
        data: dict[str, Any] = {
            "name": self.name,
            "workspace": str(self.workspace),
            "profile_ready": self.profile_ready,
            "since": self.since,
            "manual_search_day": self.manual_search_day,
        }
        if self.pending_result is not None:
            data["pending_result"] = self.pending_result
        if self.profile_session is not None:
            data["profile_session"] = self.profile_session
        if self.profile_session_started is not None:
            data["profile_session_started"] = self.profile_session_started
        if self.pcd is not None:
            data["pcd"] = self.pcd
        return data


@dataclass
class PendingRequest:
    chat_id: int
    name: str
    username: str = ""
    requested_at: str = ""

    @classmethod
    def from_dict(cls, chat_id: int | str, data: Mapping[str, Any]) -> PendingRequest:
        return cls(
            chat_id=int(chat_id),
            name=_text(_pick(data, "name", "nome")),
            username=_text(data.get("username")),
            requested_at=_text(_pick(data, "requested_at", "quando")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "username": self.username, "requested_at": self.requested_at}


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    location: str
    url: str
    score: str = ""
    strengths: str = ""
    gaps: str = ""
    deadline: str = ""
    status: JobStatus = JobStatus.NEW
    date: str = ""

    @staticmethod
    def id_for(url: str) -> str:
        """Stable job id: first 10 hex chars of sha1(url)."""
        return hashlib.sha1(url.encode()).hexdigest()[:10]

    @classmethod
    def from_shortlist(cls, item: Mapping[str, object]) -> Job | None:
        """Build a NEW job from an untrusted shortlist item written by Claude.

        Reads only the job fields (Portuguese or English keys). Any ``status`` or ``job_id`` in the
        item is ignored: the id is always ``id_for(url)``. Returns None when there is no URL.
        """
        url = _text(item.get("url")).strip()
        if not url:
            return None
        return cls(
            job_id=cls.id_for(url),
            title=_text(_pick(item, "title", "titulo")),
            company=_text(_pick(item, "company", "empresa")),
            location=_text(_pick(item, "location", "local")),
            url=url,
            score=_text(_pick(item, "score", "nota")),
            strengths=_text(_pick(item, "strengths", "pontos_fortes")),
            gaps=_text(_pick(item, "gaps", "lacunas")),
            deadline=_text(_pick(item, "deadline", "prazo")),
            status=JobStatus.NEW,
            date="",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], job_id: str | None = None) -> Job:
        """Build a job from stored state; ``job_id`` defaults to ``id_for(url)``.

        An unknown stored status falls back to ``ERROR`` (and is logged) instead of raising.
        """
        url = _text(data.get("url"))
        raw_status = _text(data.get("status")) or JobStatus.NEW.value
        try:
            status = JobStatus(raw_status)
        except ValueError:
            logger.warning("unknown job status %r for %s; using %s", raw_status, url, JobStatus.ERROR)
            status = JobStatus.ERROR
        return cls(
            job_id=job_id or _text(data.get("job_id")) or cls.id_for(url),
            title=_text(_pick(data, "title", "titulo")),
            company=_text(_pick(data, "company", "empresa")),
            location=_text(_pick(data, "location", "local")),
            url=url,
            score=_text(_pick(data, "score", "nota")),
            strengths=_text(_pick(data, "strengths", "pontos_fortes")),
            gaps=_text(_pick(data, "gaps", "lacunas")),
            deadline=_text(_pick(data, "deadline", "prazo")),
            status=status,
            date=_text(_pick(data, "date", "data")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise without ``job_id`` (it is the key in jobs-<chat>.json)."""
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "score": self.score,
            "strengths": self.strengths,
            "gaps": self.gaps,
            "deadline": self.deadline,
            "status": str(self.status),
            "date": self.date,
        }
