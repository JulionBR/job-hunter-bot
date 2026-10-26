from conftest import ADMIN, ALICE, Env
from jobbot.messages import ADMIN_CMDS, USER_CMDS


def test_admin_without_profile_gets_admin_help(env: Env) -> None:
    env.message(ADMIN, "oi")
    assert env.telegram.last(ADMIN).startswith("Comandos de admin:\n/usuarios")
    env.message(ADMIN, "/xyz")
    assert env.telegram.last(ADMIN).startswith("Comandos de admin:")


def test_candidate_help_and_unknown_command(env: Env) -> None:
    env.add_candidate()
    env.message(ALICE, "/ajuda")
    assert "Como funciona" in env.telegram.last(ALICE)
    assert "Admin:" not in env.telegram.last(ALICE)
    assert "às 0h" in env.telegram.last(ALICE)
    env.message(ALICE, "bla bla")
    assert "Como funciona" in env.telegram.last(ALICE)


def test_admin_candidate_help_includes_admin_commands(env: Env) -> None:
    env.add_candidate(ADMIN, "Root")
    env.message(ADMIN, "/ajuda")
    assert "<b>Admin:</b>\n/usuarios" in env.telegram.last(ADMIN)


def test_command_with_bot_suffix_and_case(env: Env) -> None:
    env.add_candidate()
    env.message(ALICE, "/STATUS@meubot")
    assert env.telegram.last(ALICE) == "📊 nenhuma vaga ainda"


def test_non_admin_cannot_use_admin_commands(env: Env) -> None:
    env.add_candidate()
    env.message(ALICE, "/usuarios")
    assert "Como funciona" in env.telegram.last(ALICE)
    env.message(ALICE, "/remover 2002")
    assert env.app.users.get(ALICE) is not None


def test_status_counts(env: Env) -> None:
    env.add_candidate()
    env.app.search.run()
    env.message(ALICE, "/status")
    assert env.telegram.last(ALICE) == "📊 nova: 1"


def test_guest_commands_become_a_request_not_admin_actions(env: Env) -> None:
    env.message(5005, "/usuarios")
    assert any("Pedido de acesso" in t for t in env.texts(ADMIN))


def test_set_commands_menus(env: Env) -> None:
    env.app.bot.set_commands()
    assert env.telegram.commands[0] == (USER_CMDS, None)
    admin_menu, scope = env.telegram.commands[1]
    assert admin_menu == ADMIN_CMDS and scope == {"type": "chat", "chat_id": ADMIN}
    env.add_candidate(ADMIN, "Root")
    env.telegram.commands.clear()
    env.app.bot.set_commands()
    names = [c for c, _ in env.telegram.commands[1][0]]
    assert "perfil" in names and names.count("buscar") == 1


def test_poll_loop_offsets_and_error_handling(env: Env) -> None:
    env.add_candidate()
    slept: list[float] = []
    env.app.bot._sleep = slept.append
    bad = {"update_id": 10, "message": {"chat": {"id": ALICE}, "text": "/status"}, "callback_query": None}
    bad_cb = {"update_id": 11, "callback_query": {"data": "garbage"}}
    good = {"update_id": 12, "message": {"chat": {"id": ALICE}, "text": "/status"}}
    env.telegram.updates = [[bad_cb, good]]
    env.app.bot.poll_once()
    assert env.telegram.last(ALICE) == "📊 nenhuma vaga ainda"
    env.app.bot.poll_once()
    assert env.telegram.offsets == [None, 13]
    env.telegram.update_error = OSError("rede")
    env.app.bot.poll_once()
    assert slept == [10]
    assert bad["update_id"] == 10


def test_unknown_callback_kind_changes_nothing_and_never_escapes_the_loop(env: Env) -> None:
    import pytest

    env.add_candidate()
    env.app.search.run()
    with pytest.raises(KeyError):
        env.callback(ALICE, "x:abc")
    assert env.telegram.answers == [] and env.telegram.cleared == []
    env.telegram.updates = [
        [
            {
                "update_id": 1,
                "callback_query": {
                    "id": "q",
                    "data": "x:abc",
                    "message": {"chat": {"id": ALICE}, "message_id": 1},
                },
            }
        ]
    ]
    env.app.bot.poll_once()  # logged as "update erro", not raised
    assert env.app.bot._offset == 2


def test_status_shows_not_interested_label_for_skipped(env: Env) -> None:
    env.add_candidate()
    env.app.search.run()
    status = next(iter(env.app.admin.status_counts(ALICE)), None)
    assert status == "nova"
    from jobbot.storage import JobRepository

    repo = JobRepository(env.app.store, ALICE)
    env.callback(ALICE, f"s:{repo.all()[0].job_id}")
    env.message(ALICE, "/status")
    assert env.telegram.last(ALICE) == "📊 não tenho interesse: 1"
    env.message(ADMIN, "/usuarios")
    assert "não tenho interesse: 1" in env.telegram.last(ADMIN)
    assert repo.all()[0].status.value == "pulada"
