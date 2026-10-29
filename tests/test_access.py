from conftest import ADMIN, ALICE, BOB, Env
from jobbot import messages


def test_single_request_per_person(env: Env) -> None:
    env.message(ALICE, "oi")
    assert str(ALICE) in [str(p.chat_id) for p in env.app.pending.all()]
    assert any("Pedido de acesso" in t for t in env.texts(ADMIN))
    assert "Pedi ao administrador" in env.telegram.last(ALICE)
    env.message(ALICE, "oi de novo")
    assert sum("Pedido de acesso" in t for t in env.texts(ADMIN)) == 1
    request = env.telegram.messages[0]
    assert request.markup is not None
    buttons = request.markup["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"ok:{ALICE}", f"no:{ALICE}"]


def test_non_admin_cannot_approve(env: Env) -> None:
    env.message(ALICE, "oi")
    env.callback(ALICE, f"ok:{ALICE}")
    assert env.app.users.get(ALICE) is None
    assert env.telegram.answers[-1][1] == "Só o administrador pode fazer isso."
    assert env.app.pending.all()


def test_approval_creates_folder_and_explains(env: Env) -> None:
    env.message(ALICE, "oi")
    env.callback(ADMIN, f"ok:{ALICE}")
    user = env.app.users.get(ALICE)
    assert user is not None
    assert user.workspace.name == f"primo-{ALICE}"
    assert not user.profile_ready
    assert "Acesso liberado" in env.texts(ALICE)[-1]
    assert "Como funciona" in env.texts(ALICE)[-1]
    assert any("aprovado(a)" in t for t in env.texts(ADMIN))
    assert env.telegram.cleared == [(ADMIN, 5)]
    assert env.app.pending.all() == []


def test_approval_failure_warns_admin_and_registers_nobody(env: Env) -> None:
    env.provisioner.error = RuntimeError("git quebrou")
    env.message(ALICE, "oi")
    env.app.access.approve(ALICE)
    assert env.app.users.get(ALICE) is None
    assert "Não consegui criar a pasta" in env.texts(ADMIN)[-1]
    assert "git quebrou" in env.texts(ADMIN)[-1]


def test_approve_unknown_or_existing_is_noop(env: Env) -> None:
    env.app.access.approve(BOB)
    assert env.app.users.get(BOB) is None
    env.add_candidate()
    env.message(ALICE, "x")  # already a user: not a request
    assert env.app.pending.all() == []


def test_refusal_notifies_the_person(env: Env) -> None:
    env.message(BOB, "oi")
    env.callback(ADMIN, f"no:{BOB}")
    assert env.telegram.last(BOB) == messages.ACCESS_REFUSED
    assert env.telegram.answers[-1][1] == "Recusado."
    assert env.app.pending.all() == []


def test_remove_keeps_folder_and_closes_profile_session(env: Env) -> None:
    workspace = env.add_candidate()
    env.message(ALICE, "/perfil")
    assert env.app.profile.is_active(ALICE)
    env.message(ADMIN, f"/remover {ALICE}")
    assert env.app.users.get(ALICE) is None
    assert not env.app.profile.is_active(ALICE)
    assert workspace.exists()
    assert "Removido: Alice" in env.texts(ADMIN)[-1]
    env.message(ADMIN, "/remover 999")
    assert env.texts(ADMIN)[-1].startswith("Uso: /remover ID")


def test_pending_listing(env: Env) -> None:
    env.message(ADMIN, "/pendentes")
    assert env.telegram.last(ADMIN) == "Nenhum pedido pendente."
    env.message(BOB, "oi")
    env.message(ADMIN, "/pendentes")
    assert str(BOB) in env.telegram.last(ADMIN)
    assert env.telegram.messages[-1].markup is not None


def test_join_as_admin_creates_candidate_with_first_name(env: Env) -> None:
    env.message(ADMIN, "/participar")
    user = env.app.users.get(ADMIN)
    assert user is not None and user.name == "Primo"
    assert user.workspace.name == f"primo-{ADMIN}"
    assert not user.profile_ready and not user.pcd
    assert env.provisioner.created == [user.workspace]
    assert "/perfil" in env.texts(ADMIN)[-1]


def test_join_as_admin_is_idempotent(env: Env) -> None:
    env.message(ADMIN, "/participar")
    env.message(ADMIN, "/participar")
    assert len(env.provisioner.created) == 1
    assert len(env.app.users.all()) == 1
    assert env.texts(ADMIN)[-1] == messages.ALREADY_CANDIDATE


def test_non_admin_cannot_join(env: Env) -> None:
    env.message(ALICE, "/participar")
    assert env.app.users.get(ALICE) is None
    assert env.provisioner.created == []
    assert any("Pedido de acesso" in t for t in env.texts(ADMIN))
    env.add_candidate(BOB, "Bob")
    env.message(BOB, "/participar")
    assert env.provisioner.created == []
    assert "Como funciona" in env.texts(BOB)[-1]


def test_join_as_admin_failure_is_handled_like_approval(env: Env) -> None:
    env.provisioner.error = RuntimeError("git quebrou")
    env.message(ADMIN, "/participar")
    assert env.app.users.get(ADMIN) is None
    assert "Não consegui criar a pasta" in env.texts(ADMIN)[-1]
    assert "git quebrou" in env.texts(ADMIN)[-1]


def test_admin_candidate_free_text_goes_to_profile_setup_not_admin_help(env: Env) -> None:
    env.message(ADMIN, "/participar")
    env.message(ADMIN, "/perfil")
    env.run_queue()
    assert env.app.profile.is_active(ADMIN)
    calls = len(env.claude.calls)
    env.message(ADMIN, "procuro vagas de marketing")
    env.run_queue()
    assert len(env.claude.calls) == calls + 1
    assert "procuro vagas de marketing" in env.claude.calls[-1]["prompt"]
    assert not any(t.startswith("Comandos de admin:") for t in env.texts(ADMIN))


def test_finish_works_for_admin_candidate(env: Env) -> None:
    env.message(ADMIN, "/participar")
    env.message(ADMIN, "/perfil")
    env.run_queue()
    env.message(ADMIN, "/fim")
    assert messages.PROFILE_FINISH_QUEUED in env.texts(ADMIN)
    env.run_queue()
    assert not env.app.profile.is_active(ADMIN)


def test_admin_help_lists_participar(env: Env) -> None:
    env.message(ADMIN, "oi")
    assert "/participar" in env.texts(ADMIN)[-1]
