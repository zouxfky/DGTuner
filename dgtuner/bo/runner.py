import argparse
import json
import time

from databases.factory import create_database_adapter
from dgtuner.common.paths import PROJECT_ROOT, bo_path, probing_path
from dgtuner.bo.io import append_jsonl, read_jsonl, write_jsonl
from dgtuner.bo.search_space import bounds_from_parameter_decisions, load_probing_artifacts


DEFAULT_DATABASE = "dingodb"
DEFAULT_PROBING_PATH = probing_path(DEFAULT_DATABASE)
DEFAULT_OUTPUT_PATH = bo_path(DEFAULT_DATABASE)


def parse_adapter_options(values):
    options = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"adapter option must be KEY=VALUE, got: {value}")
        key, raw = value.split("=", 1)
        options[key] = parse_scalar(raw)
    return options


def parse_scalar(value):
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def create_adapter(database, adapter_options):
    return create_database_adapter(database, **adapter_options)


def normalize_params(adapter, params):
    return adapter.get_true_values(params) if hasattr(adapter, "get_true_values") else params


def maximize_optimizer(optimizer, init_points, iterations, acquisition, kappa, xi):
    try:
        from bayes_opt.util import UtilityFunction

        utility = UtilityFunction(kind=acquisition, kappa=kappa, xi=xi)
        optimizer.maximize(init_points=init_points, n_iter=iterations, acquisition_function=utility)
    except (ImportError, TypeError):
        optimizer.maximize(init_points=init_points, n_iter=iterations)


class BOStage:
    def __init__(self, adapter, workload_path, output_path, concurrency, mode):
        self.adapter = adapter
        self.workload_path = workload_path
        self.output_path = output_path
        self.concurrency = concurrency
        self.mode = mode
        self.start_time = time.time()
        self.iteration = 0

    def objective(self, **params):
        self.iteration += 1
        applied_params = normalize_params(self.adapter, params)
        self.adapter.apply_config(params)
        self.adapter.clear_output_log()
        target = self.adapter.run_workload_target(self.workload_path, self.concurrency, self.mode)
        record = {
            "record_type": "bo_trial",
            "iteration": self.iteration,
            "target": target,
            "elapsed_time": time.time() - self.start_time,
            "params": params,
            "applied_params": applied_params,
        }
        append_jsonl(self.output_path, record)
        return target


def run_bo(
    database,
    probing_path,
    output_path,
    workload_path,
    iterations,
    init_points,
    concurrency,
    mode,
    adapter_options,
    random_state,
    acquisition,
    kappa,
    xi,
):
    records = read_jsonl(probing_path)
    summary, parameter_decisions = load_probing_artifacts(records)
    if workload_path is None:
        workload_path = summary.get("reduced_workload")
    if not workload_path:
        raise ValueError("workload path is required because probing summary has no reduced_workload")

    pbounds = bounds_from_parameter_decisions(parameter_decisions)
    adapter = create_adapter(database, adapter_options)
    stage = BOStage(adapter, workload_path, output_path, concurrency, mode)

    from bayes_opt import BayesianOptimization

    write_jsonl(output_path, [{
        "record_type": "meta",
        "database": database,
        "probing": str(probing_path),
        "workload": str(workload_path),
        "settings": {
            "iterations": iterations,
            "init_points": init_points,
            "concurrency": concurrency,
            "mode": mode,
            "adapter_options": adapter_options,
            "random_state": random_state,
            "acquisition": acquisition,
            "kappa": kappa,
            "xi": xi,
        },
        "pbounds": pbounds,
    }])

    optimizer = BayesianOptimization(
        f=stage.objective,
        pbounds=pbounds,
        verbose=2,
        random_state=random_state,
    )
    maximize_optimizer(optimizer, init_points, iterations, acquisition, kappa, xi)

    best = optimizer.max or {"target": None, "params": None}
    summary_record = {
        "record_type": "summary",
        "best_target": best.get("target"),
        "best_params": best.get("params"),
        "best_applied_params": normalize_params(adapter, best.get("params") or {}) if best.get("params") else None,
        "trial_count": stage.iteration,
        "output": str(output_path),
        "workload": str(workload_path),
    }
    append_jsonl(output_path, summary_record)
    return summary_record


def main():
    parser = argparse.ArgumentParser(description="Run Bayesian optimization using Stage 2 probing output.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--probing", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--workload", default=None)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--init-points", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--mode", type=int, default=1)
    parser.add_argument("--adapter-option", action="append", default=[])
    parser.add_argument("--random-state", type=int, default=2026)
    parser.add_argument("--acquisition", default="ei")
    parser.add_argument("--kappa", type=float, default=2.5)
    parser.add_argument("--xi", type=float, default=0.15)
    args = parser.parse_args()

    probing = args.probing or str(probing_path(args.database))
    output = args.output or str(bo_path(args.database))
    summary = run_bo(
        database=args.database,
        probing_path=probing,
        output_path=output,
        workload_path=args.workload,
        iterations=args.iterations,
        init_points=args.init_points,
        concurrency=args.concurrency,
        mode=args.mode,
        adapter_options=parse_adapter_options(args.adapter_option),
        random_state=args.random_state,
        acquisition=args.acquisition,
        kappa=args.kappa,
        xi=args.xi,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
