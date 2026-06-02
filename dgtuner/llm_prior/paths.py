from dgtuner.common.paths import PROJECT_ROOT


DEFAULT_DATABASE = "dingodb"
DEFAULT_KNOWLEDGE_DIR = PROJECT_ROOT / "databases" / DEFAULT_DATABASE / "knowledge"
DEFAULT_PARAMETERS_PATH = DEFAULT_KNOWLEDGE_DIR / "parameters.jsonl"
DEFAULT_CONTEXT_PATH = DEFAULT_KNOWLEDGE_DIR / "context.md"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "experiments" / DEFAULT_DATABASE / "llm_pruning.jsonl"
DEFAULT_LLM_ENV_PATH = PROJECT_ROOT / "configs" / "llm.env"
