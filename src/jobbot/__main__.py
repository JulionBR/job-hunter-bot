"""Command line: ``python -m jobbot bot | search | deliver | add-user``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from jobbot.clock import Clock
from jobbot.config import ConfigError, Settings
from jobbot.container import build_app
from jobbot.models import User
from jobbot.storage import JsonStore, UserRepository
from jobbot.workspace import PortalAudience, profile_ready


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobbot", description="Multi-user job search bot.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bot", help="serve Telegram (run as a service)")
    sub.add_parser("search", aliases=["daily"], help="search and rank jobs for every ready candidate")
    sub.add_parser("deliver", aliases=["enviar"], help="send the jobs the overnight search stored")
    add = sub.add_parser("add-user", help="register an existing candidate workspace")
    add.add_argument("--chat-id", type=int, required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--workspace", type=Path, required=True)
    add.add_argument("--pcd", choices=("sim", "nao"), help="PcD candidate (turns PcD portals on/off)")
    add.add_argument("--profile-ready", action="store_true", help="skip the CLAUDE.md check and mark ready")
    return parser


def add_user(
    settings: Settings, chat_id: int, name: str, workspace: Path, ready: bool | None, pcd: bool | None = None
) -> User:
    """Register (or update) a candidate; ``ready=None`` means: compute it from the workspace."""
    users = UserRepository(JsonStore(settings.state_dir))
    existing = users.get(chat_id)
    # An explicit "ready" closes any open /perfil conversation; otherwise the session and its start time
    # travel together (a session without a start time would never expire).
    keep_session = existing is not None and not ready
    user = User(
        chat_id=chat_id,
        name=name,
        workspace=workspace,
        profile_ready=profile_ready(workspace) if ready is None else ready,
        since=existing.since if existing else Clock(settings.tz).today(),
        manual_search_day=existing.manual_search_day if existing else "",
        pending_result=existing.pending_result if existing else None,
        profile_session=existing.profile_session if existing and keep_session else None,
        profile_session_started=existing.profile_session_started if existing and keep_session else None,
        pcd=existing.pcd if existing and pcd is None else pcd,
    )
    users.save(user)
    PortalAudience().sync(user)
    return user


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.load(require_token=args.command != "add-user")
    except ConfigError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    if args.command == "add-user":
        workspace: Path = args.workspace.resolve()
        if not workspace.is_dir():
            print(f"error: workspace folder not found: {workspace}", file=sys.stderr)
            return 1
        pcd = None if args.pcd is None else args.pcd == "sim"
        user = add_user(
            settings, args.chat_id, args.name, workspace, True if args.profile_ready else None, pcd
        )
        state = "ready" if user.profile_ready else "not ready"
        print(f"registered {user.name} ({user.chat_id}), profile {state}")
        return 0
    app = build_app(settings)
    if args.command == "bot":
        app.bot.run()
    elif args.command in ("search", "daily"):
        app.search.run()
    else:
        app.search.deliver_pending()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
