import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor


class DatabaseClient:
    def __init__(self):
        # Uses the same connection string your Archive uses
        self.db_url = os.getenv(
            "DATABASE_URL", "postgresql://hestia_admin:admin_password@localhost:5432/hestia_memory")

    def get_connection(self):
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)

    def get_available_domains(self) -> list:
        """Finds out what topics we actually have data for."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT domain FROM entities;")
                    return [row['domain'] for row in cur.fetchall()]
        except Exception as e:
            print(f"DB Error: {e}")
            return []

    def get_active_entities(self, domain: str) -> str:
        """Pulls the active houses (or jobs) and formats them as a JSON string for the AI."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT entity_id, payload FROM entities WHERE domain = %s AND status = 'active';", (domain,))
                    rows = cur.fetchall()
                    # Convert to a clean JSON string so the LLM can read it easily
                    return json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False)
        except Exception as e:
            return f"[]"
