# Workload Tuning Context

## Workload

- Benchmark: TPC-H.
- SQL set: 22 TPC-H analytical `SELECT` query templates.
- Dominant pattern: relational analytical workload with scans, joins, filters, grouping, aggregation, ordering, limits, subqueries, semi-joins, anti-joins, and date/range predicates.
- Query templates cover a broad range of decision-support access patterns rather than one repeated lookup pattern.
- The workload is read-heavy during performance evaluation; data loading is a separate preparation step and is not part of the tuning workload.
- The scale factor, data location, and concrete SQL file layout are runtime configuration details and should not affect the general workload characterization.

## Tables

- TPC-H tables: `region`, `nation`, `supplier`, `customer`, `part`, `partsupp`, `orders`, and `lineitem`.
- Large fact tables are typically `lineitem` and `orders`; dimension and lookup tables include `region`, `nation`, `supplier`, `customer`, and `part`.
- Frequent join paths include `orders` to `lineitem`, `customer` to `orders`, `supplier` to `lineitem`, `part` to `lineitem`, and nation/region dimension joins.
- Common predicates include date ranges, numeric ranges, string/category filters, `LIKE`, `IN`, `EXISTS`, `NOT EXISTS`, and correlated subqueries.
- Common operators include multi-table joins, aggregation, `GROUP BY`, `ORDER BY`, `LIMIT`, `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, arithmetic expressions, and conditional aggregation.

## Objective

- Primary objective: minimize total TPC-H workload execution time.
- Throughput can be considered only insofar as it helps reduce total workload execution time under the tested concurrency.
- The tuning target is read-heavy analytical query execution.

## Expected Relevance Bias

- Read path worker and queue parameters are likely relevant.
- Storage/cache/background-thread parameters can be relevant because TPC-H uses scans, joins, and aggregations over larger relational tables.
- RocksDB/cache/compaction-related settings may matter if they affect read latency, scan performance, or memory pressure.
- Request scheduling, service worker, scan execution, cache sizing, memory reclamation, and storage background maintenance parameters are natural candidates for relevance when their official descriptions connect them to read throughput or latency.
