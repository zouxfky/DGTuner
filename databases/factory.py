from databases.dingodb.adapter import DingoDBAdapter
from databases.mysql.adapter import MySQLAdapter
from databases.postgres.adapter import PostgresAdapter


def create_database_adapter(database="dingodb", **kwargs):
    if database == "dingodb":
        return DingoDBAdapter(**kwargs)
    if database == "mysql":
        return MySQLAdapter(**kwargs)
    if database in {"postgres", "postgresql"}:
        return PostgresAdapter(**kwargs)
    raise ValueError(f"Unsupported database adapter: {database}")
