"""Lecture IMAP réelle, sans dépendance : imaplib et email de la bibliothèque standard.

Sert à deux choses : montrer que l'agent travaille sur une vraie boîte quand un compte est
configuré, et refuser proprement quand il ne l'est pas. Aucune donnée de courrier n'est stockée.
"""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from typing import Any

from .settings_store import MailConfig


class MailError(RuntimeError):
    """Erreur IMAP lisible : le message est renvoyé tel quel au modèle."""


def _connect(config: MailConfig) -> imaplib.IMAP4:
    if not (config.host and config.user and config.password):
        raise MailError(
            "compte IMAP non configuré : renseigne hôte, utilisateur et mot de passe dans /settings"
        )
    try:
        if config.ssl:
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(config.host, int(config.port or 993))
        else:
            client = imaplib.IMAP4(config.host, int(config.port or 143))
        client.login(config.user, config.password)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise MailError(f"connexion IMAP impossible ({config.host}) : {exc}") from exc
    return client


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError):
        return value


def _snippet(payload: bytes, limit: int = 220) -> str:
    text = payload.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def list_messages(config: MailConfig, limit: int = 8, mailbox: str = "") -> list[dict[str, Any]]:
    """Derniers messages : expéditeur, objet, date et début du corps."""
    client = _connect(config)
    try:
        folder = mailbox or config.mailbox or "INBOX"
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise MailError(f"dossier IMAP introuvable : {folder}")
        status, data = client.search(None, "ALL")
        if status != "OK":
            raise MailError("recherche IMAP refusée")
        uids = (data[0] or b"").split()
        messages = []
        for uid in reversed(uids[-int(limit) :]):
            status, payload = client.fetch(uid, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            parsed = email.message_from_bytes(payload[0][1])
            body = ""
            if parsed.is_multipart():
                for part in parsed.walk():
                    if part.get_content_type() == "text/plain":
                        body = _snippet(part.get_payload(decode=True) or b"")
                        break
            else:
                body = _snippet(parsed.get_payload(decode=True) or b"")
            messages.append(
                {
                    "uid": uid.decode(),
                    "de": _decode(parsed.get("From")),
                    "objet": _decode(parsed.get("Subject")),
                    "date": _decode(parsed.get("Date")),
                    "extrait": body,
                    "pieces_jointes": sum(
                        1 for part in parsed.walk() if part.get_filename()
                    ),
                }
            )
        return messages
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def move_message(config: MailConfig, uid: str, folder: str = "") -> str:
    """Déplace un message vers un dossier d'archive (créé s'il manque)."""
    client = _connect(config)
    try:
        mailbox = config.mailbox or "INBOX"
        client.select(mailbox)
        target = folder or config.archive_mailbox
        if not target:
            raise MailError("aucun dossier d'archive configuré")
        status, _ = client.list('""', f'"{target}"')
        if status != "OK" or not _:
            client.create(target)
        status, _ = client.copy(uid.encode(), target)
        if status != "OK":
            raise MailError(f"copie impossible vers {target}")
        client.store(uid.encode(), "+FLAGS", "\\Deleted")
        client.expunge()
        return f"message {uid} déplacé vers {target}"
    except imaplib.IMAP4.error as exc:
        raise MailError(f"déplacement impossible : {exc}") from exc
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def test_connection(config: MailConfig) -> str:
    """Ouvre la boîte, compte les messages, referme. Sert au bouton « tester »."""
    client = _connect(config)
    try:
        folder = config.mailbox or "INBOX"
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise MailError(f"dossier IMAP introuvable : {folder}")
        status, data = client.search(None, "ALL")
        count = len((data[0] or b"").split()) if status == "OK" else 0
        return f"connexion OK, {count} message(s) dans {folder}"
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
