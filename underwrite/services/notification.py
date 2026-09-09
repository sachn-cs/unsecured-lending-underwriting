# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Notification service — dispatches alerts via configurable channels."""

from __future__ import annotations

import concurrent.futures
import os
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import BoundedExecutor, Core, Dependencies
from underwrite.store import StoreBackend
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer


class Handler(Core):
    """Sends notifications for fraud alerts, NPA events, and early warnings.

    Dispatches via configurable channels (SES/SendGrid for email,
    Twilio/SNS for SMS) in a background thread pool to avoid
    blocking event dispatch.
    """

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: StoreBackend,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the notification service with a thread pool executor."""
        deps = Dependencies(
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        super().__init__(
            name=name,
            bus=deps.bus,
            store=deps.store,
            metrics=deps.metrics,
            health=deps.health,
            authz=deps.authz,
            tracer=deps.tracer,
            saga=deps.saga,
            supervisor=deps.supervisor,
            secrets_manager=deps.secrets_manager,
            max_concurrent=deps.max_concurrent,
        )
        self.thread_pool: BoundedExecutor | None = BoundedExecutor(max_workers=4)
        self.handlers: dict[str, Any] = {
            Type.FRAUD_ALERT: self.on_notify_event,
            Type.WASH_FLAG: self.on_notify_event,
            Type.VELOCITY_FLAG: self.on_notify_event,
            Type.RISK_EARLY_WARNING: self.on_notify_event,
            Type.NPA_BUCKET_CHANGED: self.on_notify_event,
            Type.DLG_TRIGGERED: self.on_notify_event,
        }

    @property
    def executor(self) -> "BoundedExecutor | None":
        """Test/extension hook for the notification thread pool."""
        return self.thread_pool

    @executor.setter
    def executor(self, value: "BoundedExecutor | None") -> None:
        self.thread_pool = value

    def stop(self) -> None:
        """Shut down the thread pool executor."""
        if self.thread_pool is not None:
            self.thread_pool.shutdown(wait=True)
            self.thread_pool = None
        super().stop()

    def handle(self, event: Message) -> None:
        """Dispatch a notification event to the handler.

        Args:
            event: The incoming notification event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def on_notify_event(self, event: Message) -> None:
        """Submit a notification dispatch to the thread pool.

        Args:
            event: The event to notify about.
        """
        if self.thread_pool is None:
            logger.warning("notification executor not available, dispatching synchronously")
            self.dispatch_notification(event)
            return
        self.thread_pool.submit(self.dispatch_notification, event)
        self.emit(
            Type.NOTIFICATION_SENT,
            {
                "original_event": event.event_type,
                "payload": dict(event.payload),
            },
            correlation_id=event.correlation_id,
        )

    def dispatch_notification(self, event: Message) -> None:
        """Dispatch a notification through configured channels.

        Args:
            event: The event to notify about.
        """
        try:
            payload = event.payload
            recipient = payload.get("borrower") or payload.get("user") or ""
            event_type = event.event_type

            log_data = f"event={event_type} recipient={recipient}"

            email_enabled = os.environ.get("NOTIFICATION_EMAIL_ENABLED", "false").lower() == "true"
            sms_enabled = os.environ.get("NOTIFICATION_SMS_ENABLED", "false").lower() == "true"

            if email_enabled:
                self.send_email_method(recipient, event_type, payload)
            if sms_enabled:
                self.send_sms_method(recipient, event_type, payload)

            if not email_enabled and not sms_enabled:
                logger.info("notification dispatched (log-only): {}", log_data)
            else:
                logger.info("notification dispatched: {}", log_data)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("failed to dispatch notification for {}", event.event_id)

    def send_email_method(self, recipient: str, event_type: str, payload: dict[str, Any]) -> None:
        """Send an email notification via SES or log.

        Args:
            recipient: Email recipient address.
            event_type: Type of event triggering the notification.
            payload: Message payload data.
        """
        ses_region = os.environ.get("AWS_REGION", "")
        sender = os.environ.get("NOTIFICATION_EMAIL_SENDER", "noreply@underwrite.local")
        if ses_region:
            try:
                import boto3

                client = boto3.client("ses", region_name=ses_region)
                client.send_email(
                    Source=sender,
                    Destination={"ToAddresses": [recipient]},
                    Message={
                        "Subject": {"Data": f"Underwrite Alert: {event_type}"},
                        "Body": {"Text": {"Data": str(payload)}},
                    },
                )
            except (OSError, ValueError, TypeError, KeyError):
                logger.exception("SES email failed for {}", recipient)
        else:
            logger.info("email to {}: [{}] {}", recipient, event_type, payload)

    def send_sms_method(self, recipient: str, event_type: str, payload: dict[str, Any]) -> None:
        """Send an SMS notification via Twilio or log.

        Args:
            recipient: SMS recipient phone number.
            event_type: Type of event triggering the notification.
            payload: Message payload data.
        """
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
        if account_sid and auth_token and from_number:
            try:
                from twilio.rest import Client
            except ImportError:
                logger.warning("twilio not installed; install underwrite[notify] or pip install twilio")
                return
            try:
                client = Client(account_sid, auth_token)
                client.messages.create(
                    body=f"Underwrite Alert ({event_type}): {payload}",
                    from_=from_number,
                    to=recipient,
                )
            except (OSError, ValueError, TypeError, KeyError):
                logger.exception("Twilio SMS failed for {}", recipient)
        else:
            logger.info("SMS to {}: [{}] {}", recipient, event_type, payload)
