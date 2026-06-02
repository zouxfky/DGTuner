from databases.base import DatabaseAdapter


class PostgresAdapter(DatabaseAdapter):
    """Placeholder for future PostgreSQL tuning support."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("PostgresAdapter is not implemented yet")

