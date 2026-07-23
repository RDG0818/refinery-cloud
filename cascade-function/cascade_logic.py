import os
from azure.identity import DefaultAzureCredential
from azure.digitaltwins.core import DigitalTwinsClient


def get_adt_client() -> DigitalTwinsClient:
    """Build and return an authenticated client for talking to Azure Digital Twins."""
    ADT_HOSTNAME = os.getenv("ADT_ENDPOINT") # functions runtime adds local.settings.json to env vars
    if not ADT_HOSTNAME:
        raise RuntimeError("ADT_ENDPOINT environment variable is not set")
    creds = DefaultAzureCredential()
    return DigitalTwinsClient(ADT_HOSTNAME, creds)
