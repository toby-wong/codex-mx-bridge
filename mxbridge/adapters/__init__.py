"""Select an explicit client; payload fields never choose their own adapter."""
from . import claude, codex, kiro
from .common import CLIENTS, LABELS, Event, identity

ADAPTERS = {"codex": codex, "claude": claude, "kiro": kiro}


def normalize(client, payload, instance=""):
    if client not in ADAPTERS:
        raise ValueError("Unsupported hook client")
    instance = identity(instance, optional=True, limit=80)
    return ADAPTERS[client].normalize(payload, instance)
