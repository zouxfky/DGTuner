from databases.base import DatabaseAdapter


class MySQLAdapter(DatabaseAdapter):
    """Placeholder for future native MySQL tuning support."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("MySQLAdapter is not implemented yet")

