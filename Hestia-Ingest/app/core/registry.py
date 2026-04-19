from fetchers.gmail_fetcher import GmailIMAPFetcher
from fetchers.gcal_fetcher import GCalFetcher
from fetchers.outlook_fetcher import OutlookFetcher

FETCHER_REGISTRY = {
    "gmail_imap": GmailIMAPFetcher,
    "gcal": GCalFetcher,
    "outlook_calendar": OutlookFetcher,
}


def get_fetcher_class(source_name: str):
    if source_name not in FETCHER_REGISTRY:
        raise ValueError(f"Fetcher '{source_name}' is not registered.")
    return FETCHER_REGISTRY[source_name]
