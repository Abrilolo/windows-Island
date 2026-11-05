"""UDP LAN discovery, ADB tunnel fallback, HTTP dispatcher, and persistent offline outbox queue."""

from sync.config import BridgeConfig, normalize_phone_url
from sync.dispatcher import DispatchResult, PhoneDispatcher
from sync.outbox import OutboxStore, QueuedItem
from sync.phone_connector import (
    PhoneConnection,
    connect_to_phone,
    discover_phone,
    ping_phone_health,
    post_to_phone,
    send_message_to_phone,
)

__all__ = [
    "BridgeConfig",
    "DispatchResult",
    "OutboxStore",
    "PhoneConnection",
    "PhoneDispatcher",
    "QueuedItem",
    "connect_to_phone",
    "discover_phone",
    "normalize_phone_url",
    "ping_phone_health",
    "post_to_phone",
    "send_message_to_phone",
]
