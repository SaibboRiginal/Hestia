from fetchers.gmail_fetcher import GmailIMAPFetcher

FETCHER_REGISTRY = {
    "gmail_imap": GmailIMAPFetcher,
}


def get_fetcher_class(source_name: str):
    if source_name not in FETCHER_REGISTRY:
        raise ValueError(f"Fetcher '{source_name}' is not registered.")
    return FETCHER_REGISTRY[source_name]
