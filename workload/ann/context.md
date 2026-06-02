# Workload Tuning Context

## Workload

- Workload type: read-heavy vector/ANN search workload with additional normal SELECT queries.
- Dominant access pattern: vector similarity search plus relational lookup/filter/group/order queries.
- Vector queries use DingoDB SQL `vector(...)` table-function style syntax.
- Many vector queries use `/*+ vector_pre */` hints.
- Vector query arguments include vector arrays, top-k limits, and ANN search parameters such as `efsearch`.

## Tables

- Normal SELECT queries touch application tables such as `user_problem`, `problem`, `reply`, `user`, and `comments`.
- Vector queries search vector fields on tables such as `reply`, `comments`, and `problem`.

## Objective

- Primary objective: minimize workload execution time and query latency.
- Throughput can be considered only insofar as it helps reduce total workload execution time under the tested concurrency.

## Expected Relevance Bias

- Vector index execution, vector batching, ANN search, HNSW/DiskANN, and index-role CPU/memory parameters are likely relevant.
- Read path worker and queue parameters are likely relevant.
- Storage/cache/background-thread parameters can be relevant if they affect read latency.
