#!/usr/bin/env bash
# Generic, idempotent installer. Run as root from a checkout of the repository.
#
# Prerequisites: Linux user "jobbot" with home /home/jobbot, python3 >= 3.12, systemd,
# and /home/jobbot/.config/jobbot/env filled in (see deploy/env.example), including ADMIN_IDS.
#
# Register an existing candidate afterwards with:
#   cd /home/jobbot/jobbot/app && sudo -u jobbot python3 -m jobbot add-user --chat-id ID --name NOME --workspace PASTA
# (run from /home/jobbot/jobbot/app)
#
# Usage: sudo deploy/install.sh [--force]
#   --force   skip the "Claude work in progress" safety check
#
# Safety: before touching anything the script aborts if Claude work is running (a `claude -p`
# process, a held state/claude.lock, or jobbot-search/jobbot-daily/jobbot-send active), then backs
# up the state directory to state.bak-<date>-<hhmm>.
#
# Rollback:
#   1. systemctl stop jobbot.service jobbot-search.timer jobbot-deliver.timer
#   2. rm -rf /home/jobbot/jobbot/state && cp -a /home/jobbot/jobbot/state.bak-<stamp> /home/jobbot/jobbot/state
#   3. restore the previous application code into /home/jobbot/jobbot/app (e.g. the old jobbot.py)
#      and reinstall the old units (jobbot.service, jobbot-daily.*, jobbot-send.*) into
#      /etc/systemd/system, then: systemctl daemon-reload && systemctl enable --now <old units>
#   4. rm -f /etc/systemd/system/jobbot-search.* /etc/systemd/system/jobbot-deliver.* && systemctl daemon-reload
set -euo pipefail

FORCE=0
for arg in "$@"; do
  case "${arg}" in
    --force) FORCE=1 ;;
    *) echo "error: unknown argument ${arg}" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "error: run as root" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOBBOT_USER="jobbot"
JOBBOT_HOME="/home/${JOBBOT_USER}"
APP_DIR="${JOBBOT_HOME}/jobbot/app"
STATE_DIR="${JOBBOT_HOME}/jobbot/state"
ENV_FILE="${JOBBOT_HOME}/.config/jobbot/env"
UNIT_DIR="/etc/systemd/system"
REFERENCE_DIR="${JOBBOT_HOME}/ai-job-search"

id "${JOBBOT_USER}" >/dev/null 2>&1 || { echo "error: user ${JOBBOT_USER} does not exist" >&2; exit 1; }

if [ ! -f "${ENV_FILE}" ]; then
  echo "error: ${ENV_FILE} not found. Copy deploy/env.example there and fill it in." >&2
  exit 1
fi
if ! grep -Eq '^[[:space:]]*ADMIN_IDS=[[:space:]]*[0-9]' "${ENV_FILE}"; then
  echo "error: ADMIN_IDS is missing or empty in ${ENV_FILE}." >&2
  echo "       Add a line like ADMIN_IDS=<telegram chat id>[,<another id>] and rerun." >&2
  exit 1
fi
chown "${JOBBOT_USER}:${JOBBOT_USER}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

# Refuse to run while Claude work is in progress (a restart would kill it).
if [ "${FORCE}" -ne 1 ]; then
  busy=""
  if pgrep -u "${JOBBOT_USER}" -f 'claude -p' >/dev/null 2>&1; then
    busy="a 'claude -p' process is running"
  elif [ -e "${STATE_DIR}/claude.lock" ] && ! flock -n "${STATE_DIR}/claude.lock" true; then
    busy="${STATE_DIR}/claude.lock is held"
  else
    for svc in jobbot-search jobbot-daily jobbot-send; do
      if systemctl is-active --quiet "${svc}.service" 2>/dev/null; then
        busy="${svc}.service is active"
        break
      fi
    done
  fi
  if [ -n "${busy}" ]; then
    echo "error: Claude work in progress (${busy}). Wait for it to finish or rerun with --force." >&2
    exit 1
  fi
fi

# Back up state before any change.
if [ -d "${STATE_DIR}" ]; then
  BACKUP_DIR="${JOBBOT_HOME}/jobbot/state.bak-$(date +%F-%H%M)"
  cp -a "${STATE_DIR}" "${BACKUP_DIR}"
  echo "state backed up to ${BACKUP_DIR}"
fi

# Application code
install -d -o "${JOBBOT_USER}" -g "${JOBBOT_USER}" "${APP_DIR}" "${STATE_DIR}"
rm -rf "${APP_DIR}/jobbot"
cp -r "${REPO_DIR}/src/jobbot" "${APP_DIR}/jobbot"
find "${APP_DIR}/jobbot" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R "${JOBBOT_USER}:${JOBBOT_USER}" "${APP_DIR}"

# LaTeX helper used by Claude in the reference workspace, and git-excluded bot scratch files.
TEX_ASSET="${REPO_DIR}/src/jobbot/assets/jobbot_tex.py"
if [ -f "${TEX_ASSET}" ]; then
  if [ -d "${REFERENCE_DIR}" ]; then
    install -d -o "${JOBBOT_USER}" -g "${JOBBOT_USER}" "${REFERENCE_DIR}/tools"
    install -m 644 -o "${JOBBOT_USER}" -g "${JOBBOT_USER}" "${TEX_ASSET}" "${REFERENCE_DIR}/tools/jobbot_tex.py"
  else
    echo "warning: ${REFERENCE_DIR} not found; jobbot_tex.py not installed" >&2
  fi
else
  echo "warning: ${TEX_ASSET} not found; skipping jobbot_tex.py" >&2
fi
if [ -d "${REFERENCE_DIR}/.git" ]; then
  EXCLUDE="${REFERENCE_DIR}/.git/info/exclude"
  install -d -o "${JOBBOT_USER}" -g "${JOBBOT_USER}" "$(dirname "${EXCLUDE}")"
  touch "${EXCLUDE}"
  grep -qxF '.jobbot-*' "${EXCLUDE}" || echo '.jobbot-*' >> "${EXCLUDE}"
  chown "${JOBBOT_USER}:${JOBBOT_USER}" "${EXCLUDE}"
fi

# Remove legacy units
for legacy in jobbot-daily jobbot-send; do
  systemctl disable --now "${legacy}.timer" "${legacy}.service" 2>/dev/null || true
  rm -f "${UNIT_DIR}/${legacy}.service" "${UNIT_DIR}/${legacy}.timer"
done

# Install units
for unit in "${REPO_DIR}"/deploy/systemd/*.service "${REPO_DIR}"/deploy/systemd/*.timer; do
  install -m 644 "${unit}" "${UNIT_DIR}/$(basename "${unit}")"
done
systemctl daemon-reload

systemctl enable jobbot.service jobbot-search.timer jobbot-deliver.timer
systemctl restart jobbot.service
systemctl start jobbot-search.timer jobbot-deliver.timer

echo
systemctl --no-pager status jobbot.service || true
echo
systemctl list-timers --no-pager 'jobbot-*'
echo
echo "To register an existing candidate:"
echo "  cd ${APP_DIR} && sudo -u ${JOBBOT_USER} python3 -m jobbot add-user --chat-id ID --name NOME --workspace PASTA"
