import json
import os
from datetime import datetime, timedelta


class StateManager:
    """Manages the memory of when each fetcher last ran."""

    def __init__(self, filepath="state.json"):
        self.filepath = filepath
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if os.path.exists(self.filepath):
            with open(self.filepath, 'r') as f:
                return json.load(f)
        return {}

    def get_last_run_date(self, fetcher_name: str, default_days_back: int = 2) -> datetime:
        """Gets the last run date, or defaults to a few days ago if it's the first time."""
        if fetcher_name in self.state:
            # Parse the saved ISO date string back into a datetime object
            return datetime.fromisoformat(self.state[fetcher_name])

        # If no memory exists, default to X days ago
        return datetime.now() - timedelta(days=default_days_back)

    def mark_as_run(self, fetcher_name: str):
        """Saves today's exact time to memory for this specific fetcher."""
        self.state[fetcher_name] = datetime.now().isoformat()
        with open(self.filepath, 'w') as f:
            json.dump(self.state, f, indent=4)
