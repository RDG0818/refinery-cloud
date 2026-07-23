import os
import logging
from azure.communication.email import EmailClient


def get_email_client() -> EmailClient:
    """Build a client for Azure Communication Services Email, using the
    same connection-string pattern as everything else here."""
    connection_string = os.environ["ACS_CONNECTION_STRING"]
    return EmailClient.from_connection_string(connection_string)


def send_alert_email(switch_id: str, event_type: str) -> None:
    """Send a one-line alert email for a switch going unreachable or
    recovering. event_type should be 'unreachable' or 'recovered'."""
    client = get_email_client()

    if event_type == "unreachable":
        subject = f"[ALERT] {switch_id} is unreachable"
        body = f"Switch {switch_id} has lost connectivity to the DMZ gateway."
    else:
        subject = f"[RESOLVED] {switch_id} has recovered"
        body = f"Switch {switch_id} is reachable from the DMZ gateway again."

    message = {
        "senderAddress": os.environ["ALERT_EMAIL_SENDER"],
        "recipients": {
            "to": [{"address": os.environ["ALERT_EMAIL_RECIPIENT"]}]
        },
        "content": {
            "subject": subject,
            "plainText": body,
        },
    }

    poller = client.begin_send(message)
    result = poller.result()
    logging.info(f"Alert email sent for {switch_id} ({event_type}): {result['status']}")
