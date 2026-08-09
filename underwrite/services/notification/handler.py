"""Notification service — dispatches alerts via configurable channels."""

from __future__ import annotations

import concurrent.futures
import os
from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__events__ import Event, EventType
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__logger__ import logger
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.services import Core


class NotificationHandler(Core):
    """Sends notifications for fraud alerts, NPA events, and early warnings.

    Dispatches via configurable channels (SES/SendGrid for email,
    Twilio/SNS for SMS) in a background thread pool to avoid
    blocking event dispatch.
    """

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the notification service with a thread pool executor."""
        super().__init__(
            service_id=service_id,
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
        self.__executor: concurrent.futures.ThreadPoolExecutor | None = concurrent.futures.ThreadPoolExecutor(
            max_workers=4
        )
        self.handlers: dict[str, Any] = {
            EventType.FRAUD_ALERT: self.__on_notify_event,
            EventType.WASH_FLAG: self.__on_notify_event,
            EventType.VELOCITY_FLAG: self.__on_notify_event,
            EventType.RISK_EARLY_WARNING: self.__on_notify_event,
            EventType.NPA_BUCKET_CHANGED: self.__on_notify_event,
            EventType.DLG_TRIGGERED: self.__on_notify_event,
        }

    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor | None:
        """Test/extension hook for the notification thread pool."""
        return self.__executor

    @executor.setter
    def executor(self, value: concurrent.futures.ThreadPoolExecutor | None) -> None:
        self.__executor = value

    def stop(self) -> None:
        """Shut down the thread pool executor."""
        if self.__executor is not None:
            self.__executor.shutdown(wait=True)
            self.__executor = None
        super().stop()

    def handle(self, event: Event) -> None:
        """Dispatch a notification event to the handler.

        Args:
            event: The incoming notification event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_notify_event(self, event: Event) -> None:
        """Submit a notification dispatch to the thread pool.

        Args:
            event: The event to notify about.
        """
        if self.__executor is None:
            logger.warning("notification executor not available, dispatching synchronously")
            self.__dispatch_notification(event)
            return
        self.__executor.submit(self.__dispatch_notification, event)
        self.emit(
            EventType.NOTIFICATION_SENT,
            {
                "original_event": event.event_type,
                "payload": dict(event.payload),
            },
            correlation_id=event.correlation_id,
        )

    def __dispatch_notification(self, event: Event) -> None:
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
                self.__send_email(recipient, event_type, payload)
            if sms_enabled:
                self.__send_sms(recipient, event_type, payload)

            if not email_enabled and not sms_enabled:
                logger.info("notification dispatched (log-only): {}", log_data)
            else:
                logger.info("notification dispatched: {}", log_data)
        except Exception:
            logger.exception("failed to dispatch notification for {}", event.event_id)

    def __send_email(self, recipient: str, event_type: str, payload: dict[str, Any]) -> None:
        """Send an email notification via SES or log.

        Args:
            recipient: Email recipient address.
            event_type: Type of event triggering the notification.
            payload: Event payload data.
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
            except Exception:
                logger.exception("SES email failed for {}", recipient)
        else:
            logger.info("email to {}: [{}] {}", recipient, event_type, payload)

    def __send_sms(self, recipient: str, event_type: str, payload: dict[str, Any]) -> None:
        """Send an SMS notification via Twilio or log.

        Args:
            recipient: SMS recipient phone number.
            event_type: Type of event triggering the notification.
            payload: Event payload data.
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
            except Exception:
                logger.exception("Twilio SMS failed for {}", recipient)
        else:
            logger.info("SMS to {}: [{}] {}", recipient, event_type, payload)
