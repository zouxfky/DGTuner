-- q13.sql
SELECT
  c_count,
  COUNT(*) AS custdist
FROM (
  SELECT
    c.c_custkey,
    COUNT(o.o_orderkey) AS c_count
  FROM customer c
  LEFT JOIN orders o ON c.c_custkey = o.o_custkey
    AND o.o_comment NOT LIKE '%special%requests%'
  GROUP BY c.c_custkey
) c_orders
GROUP BY c_count
ORDER BY custdist DESC, c_count DESC;
-- q15.sql
SELECT
  s.s_suppkey,
  s.s_name,
  s.s_address,
  s.s_phone,
  total_revenue
FROM supplier s
JOIN (
  SELECT
    l_suppkey AS supplier_no,
    SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
  FROM lineitem
  WHERE l_shipdate >= DATE '1996-01-01'
    AND l_shipdate < DATE '1996-04-01'
  GROUP BY l_suppkey
) revenue ON s.s_suppkey = revenue.supplier_no
WHERE total_revenue = (
  SELECT MAX(total_revenue)
  FROM (
    SELECT
      l_suppkey AS supplier_no,
      SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
    FROM lineitem
    WHERE l_shipdate >= DATE '1996-01-01'
      AND l_shipdate < DATE '1996-04-01'
    GROUP BY l_suppkey
  ) revenue2
)
ORDER BY s.s_suppkey;
