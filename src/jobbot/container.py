"""Composition root: builds every object once and wires the dependencies. No global state."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from jobbot.bot.app import BotApp, Worker
from jobbot.bot.handlers import AdminHandlers, CallbackHandlers, CandidateHandlers, GuestHandlers, Spawn
from jobbot.bot.router import Router
from jobbot.claude import ClaudeRunner, ClaudeRunnerPort
from jobbot.clock import Clock
from jobbot.config import Settings
from jobbot.log import setup_logging
from jobbot.services.access import AccessService
from jobbot.services.admin import AdminService
from jobbot.services.applications import ApplicationService
from jobbot.services.profile import ProfileService
from jobbot.services.search import SearchService
from jobbot.storage import JsonStore, PendingRepository, UserRepository
from jobbot.systemd import systemctl_show
from jobbot.telegram import Notifier, Telegram, TelegramClient
from jobbot.workspace import Provisioner, WorkspaceProvisioner


def spawn_thread(fn: Callable[[], object]) -> None:
    threading.Thread(target=fn, daemon=True).start()


@dataclass
class App:
    """The wired application."""

    settings: Settings
    clock: Clock
    store: JsonStore
    users: UserRepository
    pending: PendingRepository
    telegram: Telegram
    claude: ClaudeRunnerPort
    worker: Worker
    profile: ProfileService
    search: SearchService
    applications: ApplicationService
    access: AccessService
    admin: AdminService
    router: Router
    bot: BotApp


def build_app(
    settings: Settings,
    *,
    telegram: Telegram | None = None,
    claude: ClaudeRunnerPort | None = None,
    provisioner: Provisioner | None = None,
    spawn: Spawn = spawn_thread,
    show_unit: Callable[[str, str], str] = systemctl_show,
    clock: Clock | None = None,
) -> App:
    """Wire everything. The keyword arguments let tests inject fakes for the external ports."""
    setup_logging(settings.state_dir)
    clock = clock or Clock(settings.tz)
    store = JsonStore(settings.state_dir)
    users, pending = UserRepository(store), PendingRepository(store)
    telegram = telegram or TelegramClient(settings.telegram_token)
    notifier = Notifier(telegram, settings.admin_ids)
    runner = ClaudeRunner(settings.state_dir, notifier)
    claude = claude or runner
    provisioner = provisioner or WorkspaceProvisioner(
        settings.home, settings.reference_workspace, settings.candidates_dir, store, runner.exclusive
    )
    worker = Worker(telegram, notifier)
    profile = ProfileService(settings, users, claude, telegram, notifier, clock)
    search = SearchService(settings, users, store, claude, telegram, notifier, clock)
    applications = ApplicationService(users, store, claude, telegram, notifier)
    access = AccessService(settings, users, pending, provisioner, profile, telegram, notifier, clock)
    admin = AdminService(store, users, pending, claude, profile, worker, show_unit)
    router = Router(
        settings,
        telegram,
        users,
        GuestHandlers(access),
        AdminHandlers(telegram, users, access, admin, search, spawn),
        CandidateHandlers(settings, telegram, users, profile, search, admin, worker, spawn, clock),
        CallbackHandlers(settings, telegram, users, store, access, applications, worker, spawn),
    )
    bot = BotApp(settings, telegram, users, router, worker)
    return App(
        settings, clock, store, users, pending, telegram, claude, worker, profile,
        search, applications, access, admin, router, bot,
    )  # fmt: skip
