"""Réglages d'exploitation : entrées réelles et planification des scénarios.

Deux choses séparent une démonstration d'un outil qui tourne : d'où viennent les données, et qui
déclenche le travail. Ce module tient les deux, dans `settings.json`, sur le volume de données.

* **entrées** : un dossier de CSV à traiter, des flux RSS, et un compte IMAP pour le tri de courrier ;
* **tâches** : quel scénario tourne, à quelle heure ou à quel intervalle, avec quel mode.

Le mot de passe IMAP n'est jamais renvoyé par l'API. Il est stocké dans le volume, en 0600.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SECRET_MASK = "********"
SCHEDULES = ("daily_at", "every_minutes")


# --------------------------------------------------------------------------- modèles


@dataclass
class MailConfig:
    host: str = ""
    port: int = 993
    user: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    archive_mailbox: str = ""
    ssl: bool = True

    def as_public(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": SECRET_MASK if self.password else "",
            "has_key": bool(self.password),
            "mailbox": self.mailbox,
            "archive_mailbox": self.archive_mailbox,
            "ssl": self.ssl,
            "configured": bool(self.host and self.user and self.password),
        }


@dataclass
class Inputs:
    csv_dir: str = ""
    feeds: list[str] = field(default_factory=list)

    def as_public(self) -> dict[str, Any]:
        exists = Path(self.csv_dir).is_dir() if self.csv_dir else False
        return {
            "csv_dir": self.csv_dir,
            "feeds": list(self.feeds),
            "csv_dir_exists": exists,
            "csv_files": sorted(p.name for p in Path(self.csv_dir).glob("*.csv"))[:20] if exists else [],
        }


@dataclass
class McpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    enabled: bool = True
    description: str = ""
    source: str = ""
    env: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.name or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,32}", self.name):
            raise ValueError(f"nom de serveur MCP invalide : {self.name!r}")
        if not self.command or " " in self.command:
            raise ValueError(f"commande invalide pour {self.name} : une seule commande, sans espace")
        if any(".." in str(a) for a in self.args):
            raise ValueError(f"argument suspect pour {self.name} : remontée de dossier refusée")

    def as_public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "enabled": self.enabled,
            "description": self.description,
            "source": self.source,
            "env_keys": sorted(self.env.keys()),
        }


@dataclass
class Job:
    id: str
    scenario: str
    schedule: str = "daily_at"  # "daily_at" ou "every_minutes"
    value: str = "08:00"  # "08:00" ou "60"
    enabled: bool = True
    mode: str = "live"
    last_run: str = ""
    last_status: str = ""
    last_run_id: str = ""

    def minutes(self) -> int:
        try:
            return max(5, int(self.value))
        except (TypeError, ValueError):
            return 60

    def _last(self) -> datetime | None:
        if not self.last_run:
            return None
        try:
            return datetime.strptime(self.last_run, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _slot_today(self, now: datetime) -> datetime:
        hour, _, minute = str(self.value).partition(":")
        try:
            target_h, target_m = int(hour), int(minute or 0)
        except ValueError:
            target_h, target_m = 8, 0
        return now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

    def next_run(self, now: datetime | None = None) -> str:
        """Prochaine échéance prévue, ou échéance passée si la tâche est en retard."""
        now = now or datetime.now(timezone.utc)
        if self.schedule == "every_minutes":
            reference = self._last() or now
            return (reference + timedelta(minutes=self.minutes())).strftime("%Y-%m-%dT%H:%M:%SZ")
        slot = self._slot_today(now)
        last = self._last()
        if last is not None and last >= slot:
            slot += timedelta(days=1)
        return slot.strftime("%Y-%m-%dT%H:%M:%SZ")

    def is_due(self, now: datetime | None = None) -> bool:
        """Une échéance est due dès qu'elle est passée et qu'aucun passage ne l'a consommée.

        Conséquence voulue : une tâche créée après son heure du jour se déclenche une fois tout de
        suite, puis reprend son rythme. C'est le comportement de rattrapage qu'on veut après une
        coupure ou des vacances.
        """
        if not self.enabled:
            return False
        now = now or datetime.now(timezone.utc)
        last = self._last()
        if self.schedule == "every_minutes":
            if last is None:
                return False
            return now >= last + timedelta(minutes=self.minutes())
        slot = self._slot_today(now)
        if last is not None:
            return last < slot <= now
        return now >= slot

    def as_public(self, now: datetime | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "scenario": self.scenario,
            "schedule": self.schedule,
            "value": self.value,
            "enabled": self.enabled,
            "mode": self.mode,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "last_run_id": self.last_run_id,
            "next_run": self.next_run(now) if self.enabled else "",
        }


@dataclass
class Settings:
    inputs: Inputs = field(default_factory=Inputs)
    mail: MailConfig = field(default_factory=MailConfig)
    jobs: list[Job] = field(default_factory=list)
    mcp_servers: list[McpServer] = field(default_factory=list)
    hidden_scenarios: list[str] = field(default_factory=list)
    approvals_required: bool = False

    # ---------- persistance ----------
    @classmethod
    def load(cls, path: Path) -> "Settings":
        path = Path(path)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            inputs=Inputs(**{k: v for k, v in (raw.get("inputs") or {}).items() if k in {"csv_dir", "feeds"}}),
            mail=MailConfig(
                **{
                    k: v
                    for k, v in (raw.get("mail") or {}).items()
                    if k in {"host", "port", "user", "password", "mailbox", "archive_mailbox", "ssl"}
                }
            ),
            hidden_scenarios=[str(slug) for slug in (raw.get("hidden_scenarios") or [])],
            approvals_required=bool(raw.get("approvals_required")),
            mcp_servers=[
                McpServer(
                    name=str(item.get("name") or ""),
                    command=str(item.get("command") or ""),
                    args=[str(a) for a in (item.get("args") or [])],
                    enabled=bool(item.get("enabled", True)),
                    description=str(item.get("description") or ""),
                    source=str(item.get("source") or ""),
                    env={str(k): str(v) for k, v in (item.get("env") or {}).items()},
                )
                for item in (raw.get("mcp_servers") or [])
            ],
            jobs=[
                Job(
                    id=str(item.get("id") or ""),
                    scenario=str(item.get("scenario") or ""),
                    schedule=str(item.get("schedule") or "daily_at"),
                    value=str(item.get("value") or "08:00"),
                    enabled=bool(item.get("enabled", True)),
                    mode=str(item.get("mode") or "live"),
                    last_run=str(item.get("last_run") or ""),
                    last_status=str(item.get("last_status") or ""),
                    last_run_id=str(item.get("last_run_id") or ""),
                )
                for item in (raw.get("jobs") or [])
            ],
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "inputs": {"csv_dir": self.inputs.csv_dir, "feeds": self.inputs.feeds},
            "mail": {
                "host": self.mail.host,
                "port": self.mail.port,
                "user": self.mail.user,
                "password": self.mail.password,
                "mailbox": self.mail.mailbox,
                "archive_mailbox": self.mail.archive_mailbox,
                "ssl": self.mail.ssl,
            },
            "hidden_scenarios": sorted(self.hidden_scenarios),
            "approvals_required": self.approvals_required,
            "mcp_servers": [
                {
                    "name": server.name,
                    "command": server.command,
                    "args": server.args,
                    "enabled": server.enabled,
                    "description": server.description,
                    "source": server.source,
                    "env": server.env,
                }
                for server in self.mcp_servers
            ],
            "jobs": [
                {
                    "id": job.id,
                    "scenario": job.scenario,
                    "schedule": job.schedule,
                    "value": job.value,
                    "enabled": job.enabled,
                    "mode": job.mode,
                    "last_run": job.last_run,
                    "last_status": job.last_status,
                    "last_run_id": job.last_run_id,
                }
                for job in self.jobs
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 : le mot de passe IMAP y est
        except OSError:
            pass

    # ---------- API ----------
    def update(self, raw: dict[str, Any]) -> None:
        inputs = raw.get("inputs") or {}
        if "csv_dir" in inputs:
            self.inputs.csv_dir = str(inputs["csv_dir"]).strip()
        if "feeds" in inputs:
            self.inputs.feeds = [str(f).strip() for f in inputs["feeds"] if str(f).strip()]

        mail = raw.get("mail") or {}
        for key in ("host", "user", "mailbox", "archive_mailbox"):
            if key in mail:
                setattr(self.mail, key, str(mail[key]).strip())
        if "port" in mail:
            self.mail.port = int(mail["port"] or 993)
        if "ssl" in mail:
            self.mail.ssl = bool(mail["ssl"])
        password = str(mail.get("password") or "")
        if password and password != SECRET_MASK:
            self.mail.password = password

        if "hidden_scenarios" in raw:
            self.hidden_scenarios = [str(slug) for slug in (raw.get("hidden_scenarios") or [])]
        if "approvals_required" in raw:
            self.approvals_required = bool(raw.get("approvals_required"))
        if "mcp_servers" in raw:
            self.mcp_servers = [
                McpServer(
                    name=str(item.get("name") or ""),
                    command=str(item.get("command") or ""),
                    args=[str(a) for a in (item.get("args") or [])],
                    enabled=bool(item.get("enabled", True)),
                    description=str(item.get("description") or ""),
                    source=str(item.get("source") or ""),
                    env={str(k): str(v) for k, v in (item.get("env") or {}).items()},
                )
                for item in raw["mcp_servers"]
            ]
        if "jobs" in raw:
            self.jobs = [
                Job(
                    id=str(item.get("id") or f"job-{index + 1}"),
                    scenario=str(item.get("scenario") or ""),
                    schedule=str(item.get("schedule") or "daily_at"),
                    value=str(item.get("value") or "08:00"),
                    enabled=bool(item.get("enabled", True)),
                    mode=str(item.get("mode") or "live"),
                    last_run=str(item.get("last_run") or ""),
                    last_status=str(item.get("last_status") or ""),
                    last_run_id=str(item.get("last_run_id") or ""),
                )
                for index, item in enumerate(raw["jobs"])
            ]
        for server in self.mcp_servers:
            server.validate()
        self.validate()

    def validate(self) -> None:
        for job in self.jobs:
            if not job.scenario:
                raise ValueError("une tâche doit viser un scénario")
            if job.schedule not in SCHEDULES:
                raise ValueError(f"planification inconnue : {job.schedule}")
            if job.mode not in ("live", "replay"):
                raise ValueError(f"mode inconnu : {job.mode}")
            if job.schedule == "daily_at":
                hour, _, minute = job.value.partition(":")
                try:
                    if not (0 <= int(hour) <= 23 and 0 <= int(minute or 0) <= 59):
                        raise ValueError
                except ValueError as exc:
                    raise ValueError(f"heure invalide : {job.value} (format HH:MM)") from exc
            if self.inputs.csv_dir and not Path(self.inputs.csv_dir).is_absolute():
                raise ValueError("le dossier de CSV doit être un chemin absolu")

    def as_public(self, now: datetime | None = None) -> dict[str, Any]:
        return {
            "inputs": self.inputs.as_public(),
            "mail": self.mail.as_public(),
            "jobs": [job.as_public(now) for job in self.jobs],
            "mcp_servers": [server.as_public() for server in self.mcp_servers],
            "hidden_scenarios": sorted(self.hidden_scenarios),
            "approvals_required": self.approvals_required,
        }
