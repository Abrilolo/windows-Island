"""HTTP POST dispatcher to the Galaxy S24+ (`Minimal Launcher`) with offline outbox fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request

from contracts.payload import IngestPayload
from sync.config import BridgeConfig
from sync.outbox import OutboxStore, QueuedItem


@dataclass
class DispatchResult:
    """Result of attempting to deliver pending payloads to the Galaxy S24+."""

    delivered: bool
    sent_batches: int
    sent_entities: int
    remaining_batches: int
    endpoint_url: str
    error_message: str | None = None


class PhoneDispatcher:
    """Sends merged `IngestPayload` batches to Minimal Launcher over LAN / Tailscale."""

    def __init__(
        self,
        config: BridgeConfig | None = None,
        outbox: OutboxStore | None = None,
    ) -> None:
        self.config = config or BridgeConfig.load()
        self.outbox = outbox or OutboxStore()

    def post_payload(self, payload: IngestPayload) -> tuple[bool, str | None]:
        """Send a single `IngestPayload` via HTTP POST to `config.phone_ingest_url`."""
        body_bytes = json.dumps(
            payload.to_launcher_dict(),
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            self.config.phone_ingest_url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "nook-bridge/0.1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                req, timeout=self.config.request_timeout_sec
            ) as resp:
                if 200 <= resp.status < 300:
                    return True, None
                return False, f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}: {exc.reason}"
        except urllib.error.URLError as exc:
            return False, f"S24+ inalcanzable ({exc.reason})"
        except TimeoutError:
            return (
                False,
                f"Tiempo agotado ({self.config.request_timeout_sec}s)",
            )
        except Exception as exc:
            return False, str(exc)

    def flush_outbox(self, items: list[QueuedItem] | None = None) -> DispatchResult:
        """Merge all queued items into one Room v6 payload and POST to the Galaxy S24+.

        - On HTTP 2xx: removes delivered items from `outbox.json`.
        - On network error: keeps items in `outbox.json` and records the failure reason.
        """
        target_items = items if items is not None else self.outbox.load_items()
        if not target_items:
            return DispatchResult(
                delivered=True,
                sent_batches=0,
                sent_entities=0,
                remaining_batches=0,
                endpoint_url=self.config.phone_ingest_url,
            )

        merged_payload = IngestPayload.merge_all(
            [item.payload for item in target_items],
            source="nook-desktop",
        )
        total_entities = merged_payload.total_items()
        target_ids = {item.id for item in target_items}

        ok, err = self.post_payload(merged_payload)
        if ok:
            remaining = self.outbox.remove_ids(target_ids)
            return DispatchResult(
                delivered=True,
                sent_batches=len(target_items),
                sent_entities=total_entities,
                remaining_batches=len(remaining),
                endpoint_url=self.config.phone_ingest_url,
            )

        remaining = self.outbox.mark_attempt_failed(
            target_ids, err or "Error desconocido"
        )
        return DispatchResult(
            delivered=False,
            sent_batches=0,
            sent_entities=0,
            remaining_batches=len(remaining),
            endpoint_url=self.config.phone_ingest_url,
            error_message=err,
        )
