from conftest import ADMIN, ALICE, BOB, Env


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
    assert env.telegram.last(BOB) == "Seu acesso a este bot não foi liberado."
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
