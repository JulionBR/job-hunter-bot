from typing import Any

import pytest

from conftest import FakeTelegram
from jobbot.telegram import Notifier, TelegramClient


class RecordingClient(TelegramClient):
    def __init__(self) -> None:
        super().__init__("token")
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.calls.append((method, params))
        if self.fail:
            raise OSError("rede")
        return {"result": []}


def test_send_message_truncates_and_swallows_errors() -> None:
    client = RecordingClient()
    client.send_message(1, "x" * 5000, {"inline_keyboard": []}, silent=True)
    method, params = client.calls[0]
    assert method == "sendMessage" and len(params["text"]) == 4000
    assert params["parse_mode"] == "HTML" and params["disable_notification"] is True
    client.fail = True
    client.send_message(1, "oi")  # must not raise


def test_send_plain_splits_and_propagates_errors() -> None:
    client = RecordingClient()
    client.send_plain(1, "y" * 8500)
    assert [len(p["text"]) for _, p in client.calls] == [4000, 4000, 500]
    client.send_plain(1, "   ")
    assert client.calls[-1][1]["text"] == "(sem resposta)"
    client.fail = True
    with pytest.raises(OSError):
        client.send_plain(1, "oi")


def test_notifier_reaches_every_admin() -> None:
    fake = FakeTelegram()
    Notifier(fake, {3, 1}).notify("alerta", silent=True)
    assert [(m.chat, m.silent) for m in fake.messages] == [(1, True), (3, True)]
