# TPC-H Workload

This directory is database-agnostic benchmark material at the project level.
Database-specific loaders and schemas live here only when the SQL dialect or
client path differs.

## Layout

- `queries/q01.sql` to `queries/q22.sql`: executable TPC-H query files.
- `all.sql`: concatenated single-file form for current DGTuner runners.
- `context.md`: user-written workload description used by Stage 1.
- `schema/dingodb.sql`: DingoDB-compatible TPC-H schema.
- `prepare_dingodb.py`: generate data with dbgen and load it into DingoDB.
- `build_all.py`: regenerate `all.sql` from the 22 query files.
- `data/`: generated `.tbl` files, ignored by git.
- `dbgen/`: local TPC-H dbgen source/build tree, ignored by git.

## DingoDB

The DingoDB preparation script reads a run config such as
`configs/runs/dingodb_tpch.yaml`. Users normally edit the run config's
`scale_factor`; paths are derived internally from the database and workload
names.

```bash
python3 -m databases.dingodb.docker_runtime check
python3 workload/tpch/prepare_dingodb.py --config configs/runs/dingodb_tpch.yaml
```

The script checks `workload/tpch/data/sf<scale>/` automatically. If the TPC-H
`.tbl` files are missing, it runs dbgen; if they already exist, it reuses them.

Use the individual files under `workload/tpch/queries/` as the benchmark SQL
set. Use `workload/tpch/all.sql` when a runner expects a single SQL file.

```bash
python3 workload/tpch/build_all.py
```
