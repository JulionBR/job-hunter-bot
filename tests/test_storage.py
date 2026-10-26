import json
import logging
from pathlib import Path

import pytest

from jobbot.log import ReopeningFileHandler, setup_logging
from jobbot.models import Job, JobStatus, PendingRequest, User
from jobbot.storage import JobRepository, JsonStore, PendingRepository, UserRepository


@pytest.fixture
def store(tmp_path: Path) -> JsonStore:
    return JsonStore(tmp_path / "state")


def make_job(url: str, status: JobStatus = JobStatus.NEW) -> Job:
    return Job(Job.id_for(url), "Dev", "Acme", "Remoto", url, status=status)


def test_read_missing_and_invalid(store: JsonStore, tmp_path: Path) -> None:
    assert store.read(tmp_path / "nope.json", {"d": 1}) == {"d": 1}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert store.read(bad, []) == []


def test_edit_persists_and_leaves_no_tmp(store: JsonStore) -> None:
    path = store.state_dir / "x.json"
    with store.edit(path, {}) as data:
        data["a"] = "ç"
    assert json.loads(path.read_text()) == {"a": "ç"}
    assert not path.with_suffix(".tmp").exists()
    assert (store.state_dir / "state.lock").exists()


def test_edit_recovers_from_invalid_json(store: JsonStore) -> None:
    path = store.state_dir / "x.json"
    path.write_text("garbage")
    with store.edit(path, {}) as data:
        data["k"] = 1
    assert json.loads(path.read_text()) == {"k": 1}


def test_edit_does_not_write_on_exception(store: JsonStore) -> None:
    path = store.state_dir / "x.json"
    store.write(path, {"a": 1})
    with pytest.raises(RuntimeError), store.edit(path, {}) as data:
        data["a"] = 2
        raise RuntimeError
    assert json.loads(path.read_text()) == {"a": 1}


def test_user_repository(store: JsonStore) -> None:
    repo = UserRepository(store)
    assert repo.all() == []
    assert repo.get(2002) is None
    repo.save(User(2002, "Ana", Path("/w/ana")))
    raw = json.loads((store.state_dir / "users.json").read_text())
    assert list(raw) == ["2002"]
    assert raw["2002"]["name"] == "Ana"

    updated = repo.update(2002, lambda u: setattr(u, "profile_ready", True))
    assert updated is not None and updated.profile_ready
    stored = repo.get(2002)
    assert stored is not None and stored.profile_ready
    assert repo.update(9999, lambda u: None) is None

    assert repo.remove(2002) is True
    assert repo.remove(2002) is False
    assert repo.all() == []


def test_user_repository_reads_legacy_file(store: JsonStore) -> None:
    legacy = {"2002": {"nome": "Ana", "pasta": "/w/ana", "perfil_ok": True, "desde": "01/02"}}
    (store.state_dir / "users.json").write_text(json.dumps(legacy))
    users = UserRepository(store).all()
    assert [(u.chat_id, u.name, u.profile_ready) for u in users] == [(2002, "Ana", True)]


def test_pending_repository(store: JsonStore) -> None:
    repo = PendingRepository(store)
    req = PendingRequest(2002, "Ana", "@ana", "01/02 10:00")
    assert repo.add_if_new(req) is True
    assert repo.add_if_new(req) is False
    assert repo.all() == [req]
    assert repo.pop(2002) == req
    assert repo.pop(2002) is None
    assert repo.all() == []


def test_job_repository_add_new_dedup(store: JsonStore) -> None:
    repo = JobRepository(store, 2002)
    a, b = make_job("https://example.com/a"), make_job("https://example.com/b")
    no_url = Job("zzz", "T", "C", "L", "")
    assert repo.add_new([a, no_url]) == [a]
    assert repo.add_new([a, b, b]) == [b]
    assert {j.job_id for j in repo.all()} == {a.job_id, b.job_id}
    assert repo.get(a.job_id) == a
    assert repo.get("missing") is None


def test_job_repository_set_status_and_take_waiting(store: JsonStore) -> None:
    repo = JobRepository(store, 2002)
    waiting = make_job("https://example.com/w", JobStatus.WAITING)
    other = make_job("https://example.com/o", JobStatus.SKIPPED)
    repo.add_new([waiting, other])

    released = repo.take_waiting()
    assert [j.job_id for j in released] == [waiting.job_id]
    assert released[0].status is JobStatus.NEW
    assert repo.take_waiting() == []
    skipped = repo.get(other.job_id)
    assert skipped is not None and skipped.status is JobStatus.SKIPPED

    assert repo.set_status(waiting.job_id, JobStatus.QUEUED) is True
    assert repo.set_status("missing", JobStatus.QUEUED) is False
    queued = repo.get(waiting.job_id)
    assert queued is not None and queued.status is JobStatus.QUEUED
    raw = json.loads((store.state_dir / "jobs-2002.json").read_text())
    assert raw[waiting.job_id]["status"] == "na_fila"


def test_setup_logging_format(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path)
    logger.info("hello")
    line = (tmp_path / "log.txt").read_text().strip()
    assert line.startswith("[") and line.endswith("] hello")
    assert len(line.split("]")[0]) == len("[2026-01-01 00:00:00")
    assert len(setup_logging(tmp_path).handlers) == 1


def test_log_rotates_at_limit_and_survives_external_removal(tmp_path: Path) -> None:
    handler = ReopeningFileHandler(tmp_path / "log.txt", max_bytes=50)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("jobbot.test-rotation")
    logger.propagate = False
    logger.addHandler(handler)
    logger.warning("a" * 60)
    logger.warning("second")
    assert (tmp_path / "log.txt.1").read_text() == "a" * 60 + "\n"
    assert (tmp_path / "log.txt").read_text() == "second\n"
    (tmp_path / "log.txt").unlink()
    logger.warning("third")
    assert (tmp_path / "log.txt").read_text() == "third\n"
