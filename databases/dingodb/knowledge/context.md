# Database Tuning Context

## Database

- Database: DingoDB.
- Candidate parameters are official DingoDB configuration parameters.

## Workload

- Total SQL statements: 30.
- SQL type: 30 `SELECT` statements.
- Write statements: 0.
- Vector/ANN statements: 20.
- Non-vector lookup/filter/group/order statements: 10.
- Dominant pattern: read-only vector/ANN workload with additional normal SELECT queries.
- The vector queries use DingoDB SQL `vector(...)` table-function style syntax.
- The vector queries include `/*+ vector_pre */` hints in many statements.
- The vector queries use ANN search arguments such as vector arrays, top-k value `100`, and `map[efsearch, 50]`.

## Tables

- Normal SELECT queries touch tables such as `user_problem`, `problem`, `reply`, `user`, and `comments`.
- Vector queries search vector fields on tables such as `reply`, `comments`, and `problem`.

## Objective

- Primary objective: minimize workload execution time / latency.
- Throughput can be considered only insofar as it helps reduce total workload execution time under the tested concurrency.

## Expected Relevance Bias

- Parameters on the `index` role and vector/HNSW execution path are likely more relevant.
- Read path worker and queue parameters are likely more relevant than write path parameters.
- Storage/cache/background-thread parameters can be relevant if they affect read latency.
- Coordinator metadata, watch, lease, table creation, logging, tracing, metrics, Raft apply, and write/transaction limits are usually lower priority for this read-only ANN workload unless the official parameter name and role strongly indicate otherwise.

## Environment

- No concrete hardware resource count is provided.
- Do not assume CPU core count, memory size, disk type, network bandwidth, or node count.
