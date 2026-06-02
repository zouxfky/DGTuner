# DGTuner

DGTuner is a multi-stage database configuration tuning framework. The tuning
algorithms are database-agnostic; database-specific configuration, workload,
deployment, and knowledge files live under `databases/<database>/`.

## Layout

- `dgtuner/`: database-agnostic tuning stages.
  - `common/`: shared path helpers.
  - `llm_prior/`: Stage 1, LLM-based parameter pruning.
  - `probing/`: Stage 2, adaptive empirical probing for SQL and parameter reduction.
  - `bo/`: Stage 3, Bayesian optimization over the reduced search space.
- `databases/`: database adapters and database-specific assets.
  - `base.py`: adapter interface.
  - `factory.py`: adapter factory.
  - `dingodb/`: DingoDB adapter, knobs, runtime config, knowledge, workloads, and scripts.
  - `mysql/`, `postgres/`: placeholders for future adapters.
- `experiments/<database>/`: generated stage outputs for each database.
- `configs/`: global configuration, currently LLM API environment files.
- `environment/`: dependency records.
- `docs/`: design notes.
- `legacy/`: old implementation, old baselines, old experiment outputs, old final results, and archived large files.

## Commands

Run Stage 1:

```bash
python3 -m dgtuner.llm_prior --database dingodb --params-per-prompt 10 --llm-j 5
```

Run Stage 2:

```bash
python3 -m dgtuner.probing --database dingodb --initial-samples 5 --batch-size 5 --max-samples 30 --stable-rounds 2 --concurrency 10
```

Run Stage 3:

```bash
python3 -m dgtuner.bo --database dingodb --iterations 50 --init-points 5 --concurrency 10
```

Database-specific adapter options can be passed with repeated `--adapter-option`
arguments, for example:

```bash
python3 -m dgtuner.probing --database dingodb --adapter-option node_number=4
```

To keep multiple experiment runs, pass explicit output paths such as
`--output experiments/dingodb/ann_c10/probing.jsonl` and
`--reduced-workload experiments/dingodb/ann_c10/reduced_workload.sql`.
