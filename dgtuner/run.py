import argparse
import sys

from dgtuner.run_config import DEFAULT_RUN_CONFIG, resolve_run_config


STAGE_ALIASES = {
    "1": "stage1",
    "stage1": "stage1",
    "llm": "stage1",
    "llm_prior": "stage1",
    "2": "stage2",
    "stage2": "stage2",
    "probing": "stage2",
    "3": "stage3",
    "stage3": "stage3",
    "bo": "stage3",
}


def run_stage1(run, args):
    from dgtuner.llm_prior.runner import main

    sys.argv = [
        "dgtuner.llm_prior",
        "--database",
        run["database"],
        "--parameters",
        str(run["parameters"]),
        "--context",
        str(run["context"]),
        "--output",
        str(run["llm_pruning"]),
        *args,
    ]
    main()


def run_stage2(run, args):
    from dgtuner.probing.runner import main

    sys.argv = [
        "dgtuner.probing",
        "--database",
        run["database"],
        "--workload",
        str(run["workload_file"]),
        "--llm-pruning",
        str(run["llm_pruning"]),
        "--output",
        str(run["probing"]),
        "--reduced-workload",
        str(run["reduced_workload"]),
        *args,
    ]
    main()


def run_stage3(run, args):
    from dgtuner.bo.runner import main

    sys.argv = [
        "dgtuner.bo",
        "--database",
        run["database"],
        "--probing",
        str(run["probing"]),
        "--output",
        str(run["bo"]),
        "--workload",
        str(run["reduced_workload"]),
        *args,
    ]
    main()


def main():
    parser = argparse.ArgumentParser(description="Run a DGTuner stage from a run config.")
    parser.add_argument("stage", choices=sorted(STAGE_ALIASES))
    parser.add_argument("--config", default=str(DEFAULT_RUN_CONFIG))
    args, remaining = parser.parse_known_args()

    run = resolve_run_config(args.config)
    stage = STAGE_ALIASES[args.stage]
    if stage == "stage1":
        run_stage1(run, remaining)
    elif stage == "stage2":
        run_stage2(run, remaining)
    elif stage == "stage3":
        run_stage3(run, remaining)
    else:
        raise ValueError(f"Unsupported stage: {args.stage}")


if __name__ == "__main__":
    main()
