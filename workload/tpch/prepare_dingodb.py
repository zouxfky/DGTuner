import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from databases.dingodb.controller import load_simple_yaml
from dgtuner.run_config import DEFAULT_RUN_CONFIG, resolve_run_config


TPCH_DIR = Path(__file__).resolve().parent
DBGEN_DIR = TPCH_DIR / "dbgen"
TABLES = (
    "region",
    "nation",
    "part",
    "supplier",
    "partsupp",
    "customer",
    "orders",
    "lineitem",
)
LOAD_COLUMNS = {
    "region": ("r_regionkey", "r_name", "r_comment"),
    "nation": ("n_nationkey", "n_name", "n_regionkey", "n_comment"),
    "part": (
        "p_partkey",
        "p_name",
        "p_mfgr",
        "p_brand",
        "p_type",
        "p_size",
        "p_container",
        "p_retailprice",
        "p_comment",
    ),
    "supplier": (
        "s_suppkey",
        "s_name",
        "s_address",
        "s_nationkey",
        "s_phone",
        "s_acctbal",
        "s_comment",
    ),
    "partsupp": ("ps_partkey", "ps_suppkey", "ps_availqty", "ps_supplycost", "ps_comment"),
    "customer": (
        "c_custkey",
        "c_name",
        "c_address",
        "c_nationkey",
        "c_phone",
        "c_acctbal",
        "c_mktsegment",
        "c_comment",
    ),
    "orders": (
        "o_orderkey",
        "o_custkey",
        "o_orderstatus",
        "o_totalprice",
        "o_orderdate",
        "o_orderpriority",
        "o_clerk",
        "o_shippriority",
        "o_comment",
    ),
    "lineitem": (
        "l_orderkey",
        "l_partkey",
        "l_suppkey",
        "l_linenumber",
        "l_quantity",
        "l_extendedprice",
        "l_discount",
        "l_tax",
        "l_returnflag",
        "l_linestatus",
        "l_shipdate",
        "l_commitdate",
        "l_receiptdate",
        "l_shipinstruct",
        "l_shipmode",
        "l_comment",
    ),
}


def resolve_project_path(value):
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


def run(command, cwd=None):
    print("+ " + subprocess.list2cmdline([str(item) for item in command]))
    return subprocess.run(command, cwd=cwd, check=True)


def ensure_dbgen():
    executable = DBGEN_DIR / "dbgen"
    if executable.exists():
        return executable
    if not DBGEN_DIR.exists():
        raise FileNotFoundError(
            f"Missing {DBGEN_DIR}. Clone TPC-H dbgen source there before preparing data."
        )
    run(["make", "MACHINE=LINUX", "DATABASE=MYSQL", "dbgen"], cwd=DBGEN_DIR)
    if not executable.exists():
        raise FileNotFoundError(f"dbgen build did not create {executable}")
    return executable


def generate_data(scale, data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    dists_source = DBGEN_DIR / "dists.dss"
    dists_target = data_dir / "dists.dss"
    if not dists_target.exists():
        shutil.copyfile(dists_source, dists_target)
    run([ensure_dbgen(), "-s", str(scale), "-f"], cwd=data_dir)


def missing_table_files(data_dir):
    return [data_dir / f"{table}.tbl" for table in TABLES if not (data_dir / f"{table}.tbl").exists()]


def mysql_args(runtime_path, sql=None, sql_file=None, volume=None, local_infile=False):
    config = load_simple_yaml(str(runtime_path))
    client = config.get("workload_client") or config.get("sql_client")
    if not client:
        raise ValueError(f"Missing workload_client in {runtime_path}")

    if client.get("mode") == "docker":
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            str(client.get("network", "host")),
        ]
        if volume:
            command.extend(["-v", volume])
        command.extend([str(client.get("image", "mysql:5.7")), "mysql"])
    else:
        command = [str(client.get("binary", "mysql"))]

    if local_infile:
        command.append("--local-infile=1")
    command.extend(
        [
            "-h",
            str(client["host"]),
            "-P",
            str(client["port"]),
            "-u",
            str(client["user"]),
            f"-p{client['password']}",
        ]
    )
    if sql is not None:
        command.extend(["-e", sql])
    if sql_file is not None:
        command.extend(["-e", f"source {sql_file}"])
    return command


def apply_schema(runtime_path, schema_path):
    run(
        mysql_args(
            runtime_path,
            sql_file=f"/schema/{schema_path.name}",
            volume=f"{schema_path.parent.resolve()}:/schema:ro",
        )
    )


def load_tables(runtime_path, data_dir):
    mount = f"{data_dir.resolve()}:/data:ro"
    for table in TABLES:
        columns = ", ".join(LOAD_COLUMNS[table])
        sql = (
            f"LOAD DATA LOCAL INFILE '/data/{table}.tbl' INTO TABLE {table} "
            "FIELDS TERMINATED BY '|' "
            f"({columns}, @unused);"
        )
        run(mysql_args(runtime_path, sql=sql, volume=mount, local_infile=True))


def smoke_test(runtime_path):
    selects = [
        f"SELECT '{table}' AS table_name, COUNT(*) AS row_count FROM {table}"
        for table in TABLES
    ]
    run(mysql_args(runtime_path, sql=" UNION ALL ".join(selects) + ";"))


def parse_args():
    parser = argparse.ArgumentParser(description="Generate and load TPC-H data into DingoDB.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_RUN_CONFIG),
        help="Run config path. Defaults to configs/runs/dingodb_tpch.yaml.",
    )
    parser.add_argument(
        "--runtime",
        default=None,
        help="Optional database runtime override. Defaults to database_runtime in the run config.",
    )
    parser.add_argument(
        "--scale",
        default=None,
        help="TPC-H scale factor. Defaults to scale_factor in the run config.",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Schema SQL file. Defaults to workload/<workload>/schema/<database>.sql.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Output directory for .tbl files. Defaults to workload/<workload>/data/sf<scale>.",
    )
    parser.add_argument("--skip-load", action="store_true", help="Generate data only; do not create/load DingoDB tables")
    return parser.parse_args()


def main():
    args = parse_args()
    run_config = resolve_run_config(args.config)
    runtime_path = Path(args.runtime).resolve() if args.runtime else run_config["database_runtime"]
    scale = str(args.scale or run_config["scale_factor"])
    schema_path = resolve_project_path(args.schema) if args.schema else run_config["schema"]
    data_dir = (
        Path(args.data_dir).resolve()
        if args.data_dir
        else run_config["data_dir"]
    )

    if missing_table_files(data_dir):
        generate_data(scale, data_dir)
    missing = [str(path) for path in missing_table_files(data_dir)]
    if missing:
        raise FileNotFoundError("Missing generated TPC-H files: " + ", ".join(missing))

    if not args.skip_load:
        apply_schema(runtime_path, schema_path)
        load_tables(runtime_path, data_dir)
        smoke_test(runtime_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
