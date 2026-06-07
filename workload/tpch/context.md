# Workload Tuning Context

## Workload

- Benchmark: TPC-H.
- SQL set: 22 TPC-H analytical `SELECT` query templates.
- Dominant pattern: relational analytical workload with scans, joins, filters, grouping, aggregation, ordering, limits, subqueries, semi-joins, anti-joins, and date/range predicates.
- Query templates cover a broad range of decision-support access patterns rather than one repeated lookup pattern.
- The workload is read-heavy during performance evaluation; data loading is a separate preparation step and is not part of the tuning workload.
- The scale factor, data location, and concrete SQL file layout are runtime configuration details and do not affect the general workload characterization.

## Tables

- TPC-H tables: `region`, `nation`, `supplier`, `customer`, `part`, `partsupp`, `orders`, and `lineitem`.
- Large fact tables are typically `lineitem` and `orders`; dimension and lookup tables include `region`, `nation`, `supplier`, `customer`, and `part`.
- Frequent join paths include `orders` to `lineitem`, `customer` to `orders`, `supplier` to `lineitem`, `part` to `lineitem`, and nation/region dimension joins.
- Common predicates include date ranges, numeric ranges, string/category filters, `LIKE`, `IN`, `EXISTS`, `NOT EXISTS`, and correlated subqueries.
- Common operators include multi-table joins, aggregation, `GROUP BY`, `ORDER BY`, `LIMIT`, `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, arithmetic expressions, and conditional aggregation.

## Objective

- Primary objective: minimize total TPC-H workload execution time.
- Throughput is considered only insofar as it reduces total workload execution time under the tested concurrency.
- The tuning target is read-heavy analytical query execution.

## Execution Characteristics

- Reads large volumes of data through sequential and range scans over large tables.
- Performs many large multi-table joins that depend on the memory available for intermediate join processing.
- Sorts and groups large intermediate results for `ORDER BY`, `GROUP BY`, and aggregation.
- Benefits from keeping frequently accessed data and indexes resident in memory.
- Exploits parallel and concurrent query execution at the tested concurrency.
- Is read-dominated during evaluation; write, durability, replication, and logging activity do not contribute to query execution time.
- Is sensitive to background maintenance work only where it affects read latency.
