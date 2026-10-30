from pathlib import Path

from jobbot.models import Job, JobStatus, PendingRequest, User


def test_status_values_are_portuguese_strings() -> None:
    assert JobStatus.WAITING == "aguardando"
    assert JobStatus("na_fila") is JobStatus.QUEUED
    assert str(JobStatus.SENT) == "enviada"


def test_user_legacy_keys_round_trip() -> None:
    legacy = {
        "nome": "Ana",
        "pasta": "/w/ana",
        "perfil_ok": True,
        "desde": "01/02",
        "busca_manual": "03/02",
        "resultado_pendente": "2",
    }
    user = User.from_dict("2002", legacy)
    assert user == User(2002, "Ana", Path("/w/ana"), True, "01/02", "03/02", "2")
    assert user.to_dict() == {
        "name": "Ana",
        "workspace": "/w/ana",
        "profile_ready": True,
        "since": "01/02",
        "manual_search_day": "03/02",
        "pending_result": "2",
    }
    assert User.from_dict(2002, user.to_dict()) == user


def test_user_without_pending_result_omits_key() -> None:
    user = User.from_dict(2002, {"nome": "Ana", "pasta": "/w"})
    assert user.pending_result is None
    assert "pending_result" not in user.to_dict()


def test_pending_request_legacy_and_new() -> None:
    legacy = PendingRequest.from_dict("2002", {"nome": "Ana", "username": "@ana", "quando": "01/02 10:00"})
    assert legacy == PendingRequest(2002, "Ana", "@ana", "01/02 10:00")
    assert PendingRequest.from_dict(2002, legacy.to_dict()) == legacy


def test_job_legacy_keys_to_english() -> None:
    legacy = {
        "titulo": "Dev",
        "empresa": "Acme",
        "local": "Remoto",
        "url": "https://example.com/1",
        "nota": "8/10",
        "pontos_fortes": "python",
        "lacunas": "go",
        "prazo": "",
        "status": "aguardando",
        "data": "01/02",
    }
    job = Job.from_dict(legacy, "abc")
    assert job.status is JobStatus.WAITING
    assert job.job_id == "abc"
    assert job.to_dict() == {
        "title": "Dev",
        "company": "Acme",
        "location": "Remoto",
        "url": "https://example.com/1",
        "score": "8/10",
        "strengths": "python",
        "gaps": "go",
        "deadline": "",
        "status": "aguardando",
        "date": "01/02",
        "source": "",
    }
    assert Job.from_dict(job.to_dict(), "abc") == job


def test_job_id_for_matches_sha1_prefix() -> None:
    assert len(Job.id_for("x")) == 10
    assert Job.id_for("x") == "11f6ad8ec5"
    assert Job.from_dict({"url": "x"}).job_id == "11f6ad8ec5"
    assert Job.from_dict({"url": "x"}).status is JobStatus.NEW


def test_from_shortlist_ignores_status_and_job_id() -> None:
    url = "https://example.com/1"
    item = {"titulo": "Dev", "url": url, "status": "new", "job_id": "x" * 80, "nota": "9/10"}
    job = Job.from_shortlist(item)
    assert job is not None
    assert job.job_id == Job.id_for(url)
    assert len(job.job_id) == 10
    assert job.status is JobStatus.NEW
    assert (job.title, job.score) == ("Dev", "9/10")


def test_from_shortlist_requires_url_and_accepts_english_keys() -> None:
    assert Job.from_shortlist({"title": "Dev"}) is None
    assert Job.from_shortlist({"url": "  "}) is None
    job = Job.from_shortlist({"url": "u", "title": "T", "strengths": "s", "gaps": "g"})
    assert job is not None and (job.title, job.strengths, job.gaps) == ("T", "s", "g")


def test_from_dict_unknown_status_falls_back_to_error() -> None:
    assert Job.from_dict({"url": "u", "status": "bogus"}).status is JobStatus.ERROR


def test_user_profile_session_round_trip_and_legacy_files() -> None:
    legacy = User.from_dict("2002", {"nome": "Ana", "pasta": "/w/ana"})
    assert legacy.profile_session is None and "profile_session" not in legacy.to_dict()
    user = User.from_dict("2002", {"name": "Ana", "workspace": "/w", "profile_session": "abc"})
    assert user.profile_session == "abc"
    assert user.to_dict()["profile_session"] == "abc"


def test_shortlist_source_is_kept_and_shown_on_the_card() -> None:
    from jobbot import messages

    job = Job.from_shortlist({"url": "https://x/1", "title": "T", "source": "Himalayas (himalayas.app)"})
    assert job is not None and job.source == "Himalayas (himalayas.app)"
    assert Job.from_dict(job.to_dict()).source == job.source
    assert 'via <a href="https://himalayas.app">Himalayas</a>' in messages.job_card(job)
    plain = Job.from_shortlist({"url": "https://x/2", "title": "T"})
    assert plain is not None and " via " not in messages.job_card(plain)


def test_card_credit_links_himalayas_and_escapes_other_sources() -> None:
    from jobbot import messages

    link = 'via <a href="https://himalayas.app">Himalayas</a>'
    by_url = Job.from_shortlist({"url": "https://himalayas.app/jobs/x", "title": "T"})
    assert by_url is not None and link in messages.job_card(by_url)
    sub = Job.from_shortlist({"url": "https://www.himalayas.app/jobs/x", "title": "T", "source": "x"})
    assert sub is not None and link in messages.job_card(sub) and "via x" not in messages.job_card(sub)
    named = Job.from_shortlist({"url": "https://x/1", "title": "T", "source": "HIMALAYAS jobs"})
    assert named is not None and link in messages.job_card(named)
    lookalike = Job.from_shortlist({"url": "https://nothimalayas.app/1", "title": "T", "source": "A<b>"})
    assert lookalike is not None and "via A&lt;b&gt;" in messages.job_card(lookalike)


def test_card_survives_a_malformed_url() -> None:
    from jobbot import messages

    job = Job.from_shortlist({"url": "https://[abc", "title": "T", "source": "Gupy"})
    assert job is not None and "via Gupy" in messages.job_card(job)
