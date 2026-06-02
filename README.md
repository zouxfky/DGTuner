# DGTuner

DGTuner is a multi-stage database configuration tuning framework. User-facing
run configuration, workload assets, database adapters, and stage outputs are
kept separate so new databases and workloads can be added without changing the
core tuning logic.

## Layout

- `dgtuner/`: database-agnostic tuning stages.
  - `common/`: shared path helpers.
  - `llm_prior/`: Stage 1, LLM-based parameter pruning.
  - `probing/`: Stage 2, adaptive empirical probing for SQL and parameter reduction.
  - `bo/`: Stage 3, Bayesian optimization over the reduced search space.
- `configs/runs/`: user-facing run configs. A run config selects the database,
  workload, scale factor, and database runtime file.
- `workload/`: benchmark workload assets shared across database adapters.
  - `tpch/`: TPC-H queries, data generation/loading scripts, and database-specific schemas.
- `databases/`: database adapters and database-specific assets.
  - `base.py`: adapter interface.
  - `factory.py`: adapter factory.
  - `dingodb/`: DingoDB adapter, knobs, runtime config, knowledge, and runtime scripts.
- `configs/`: global configuration, currently LLM API environment files.
- `docs/`: design notes.

## Run Configuration

Users normally edit only a file under `configs/runs/`, for example
`configs/runs/dingodb_tpch.yaml`:

```yaml
database: "dingodb"
workload: "tpch"
scale_factor: "0.1"
database_runtime: "databases/dingodb/runtime.yaml"
```

From this config DGTuner derives the workload SQL, context, schema, data
directory, and stage output paths:

- workload SQL: `workload/<workload>/all.sql`
- workload context: `workload/<workload>/context.md`
- database schema: `workload/<workload>/schema/<database>.sql`
- generated data: `workload/<workload>/data/sf<scale_factor>`
- stage outputs: `databases/<database>/results/<workload>/<stage-number>/`

## DingoDB Local Docker Runtime

The default DingoDB runtime is a local single-machine Docker deployment based on
`databases/dingodb/docker-compose.yml`. `databases/dingodb/runtime.yaml` is a
database runtime file, not a workload selector:

- `docker_runtime.host_ip`: keep `auto` unless auto-detection picks the wrong
  non-loopback host address.
- `workload_client`: MySQL-compatible endpoint and credentials.
- `config_apply.docker.roles`: container names and in-container config paths if
  the Docker image layout changes.

Start or stop the local DingoDB runtime:

```bash
python3 -m databases.dingodb.docker_runtime start
python3 -m databases.dingodb.docker_runtime check
python3 -m databases.dingodb.docker_runtime stop
```

The adapter writes YAML and gflags changes into the running DingoDB containers
with `docker cp`, so Stage 2 and Stage 3 do not require SSH or host-mounted
configuration files.

## Commands

Run Stage 1:

```bash
python3 -m dgtuner.run 1 --config configs/runs/dingodb_tpch.yaml --params-per-prompt 10 --llm-j 5
```

Prepare and run the TPC-H workload for DingoDB:

```bash
python3 workload/tpch/prepare_dingodb.py --config configs/runs/dingodb_tpch.yaml
python3 -m dgtuner.run 2 --config configs/runs/dingodb_tpch.yaml --initial-samples 5 --batch-size 5 --max-samples 30 --stable-rounds 2 --concurrency 10
```

`prepare_dingodb.py` checks the configured TPC-H data directory automatically.
If the `.tbl` files are missing, it generates them with dbgen; otherwise it
reuses the existing data.

`workload/tpch/queries/q01.sql` through `q22.sql` are the reusable benchmark
SQL files. `workload/tpch/all.sql` is the concatenated single-file form used by
the current Stage 2 runner.

For `workload: tpch`, Stage 1 writes to `databases/dingodb/results/tpch/1/`,
Stage 2 writes to `databases/dingodb/results/tpch/2/`, and Stage 3 writes to
`databases/dingodb/results/tpch/3/`.

Run Stage 3:

```bash
python3 -m dgtuner.run 3 --config configs/runs/dingodb_tpch.yaml --iterations 50 --init-points 5 --concurrency 10
```

Database-specific adapter options can be passed with repeated `--adapter-option`
arguments, for example:

```bash
python3 -m dgtuner.probing --database dingodb --adapter-option node_number=4
```

For DingoDB, stage outputs are derived from the run config and stored under
`databases/dingodb/results/<workload>/<stage-number>/`.
