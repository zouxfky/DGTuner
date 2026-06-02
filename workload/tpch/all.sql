-- q01.sql
SELECT
  l_returnflag,
  l_linestatus,
  SUM(l_quantity) AS sum_qty,
  SUM(l_extendedprice) AS sum_base_price,
  SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
  SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
  AVG(l_quantity) AS avg_qty,
  AVG(l_extendedprice) AS avg_price,
  AVG(l_discount) AS avg_disc,
  COUNT(*) AS count_order
FROM lineitem
WHERE l_shipdate <= DATE '1998-09-02'
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus;

-- q02.sql
SELECT
  s.s_acctbal,
  s.s_name,
  n.n_name,
  p.p_partkey,
  p.p_mfgr,
  s.s_address,
  s.s_phone,
  s.s_comment
FROM part p
JOIN partsupp ps ON p.p_partkey = ps.ps_partkey
JOIN supplier s ON s.s_suppkey = ps.ps_suppkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
JOIN region r ON n.n_regionkey = r.r_regionkey
WHERE p.p_size = 15
  AND p.p_type LIKE '%BRASS'
  AND r.r_name = 'EUROPE'
  AND ps.ps_supplycost = (
    SELECT MIN(ps2.ps_supplycost)
    FROM partsupp ps2
    JOIN supplier s2 ON s2.s_suppkey = ps2.ps_suppkey
    JOIN nation n2 ON s2.s_nationkey = n2.n_nationkey
    JOIN region r2 ON n2.n_regionkey = r2.r_regionkey
    WHERE ps2.ps_partkey = p.p_partkey
      AND r2.r_name = 'EUROPE'
  )
ORDER BY s.s_acctbal DESC, n.n_name, s.s_name, p.p_partkey
LIMIT 100;

-- q03.sql
SELECT
  l.l_orderkey,
  SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue,
  o.o_orderdate,
  o.o_shippriority
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON l.l_orderkey = o.o_orderkey
WHERE c.c_mktsegment = 'BUILDING'
  AND o.o_orderdate < DATE '1995-03-15'
  AND l.l_shipdate > DATE '1995-03-15'
GROUP BY l.l_orderkey, o.o_orderdate, o.o_shippriority
ORDER BY revenue DESC, o.o_orderdate
LIMIT 10;

-- q04.sql
SELECT
  o.o_orderpriority,
  COUNT(*) AS order_count
FROM orders o
WHERE o.o_orderdate >= DATE '1993-07-01'
  AND o.o_orderdate < DATE '1993-10-01'
  AND EXISTS (
    SELECT 1
    FROM lineitem l
    WHERE l.l_orderkey = o.o_orderkey
      AND l.l_commitdate < l.l_receiptdate
  )
GROUP BY o.o_orderpriority
ORDER BY o.o_orderpriority;

-- q05.sql
SELECT
  n.n_name,
  SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON l.l_orderkey = o.o_orderkey
JOIN supplier s ON l.l_suppkey = s.s_suppkey
JOIN nation n ON c.c_nationkey = n.n_nationkey AND s.s_nationkey = n.n_nationkey
JOIN region r ON n.n_regionkey = r.r_regionkey
WHERE r.r_name = 'ASIA'
  AND o.o_orderdate >= DATE '1994-01-01'
  AND o.o_orderdate < DATE '1995-01-01'
GROUP BY n.n_name
ORDER BY revenue DESC;

-- q06.sql
SELECT
  SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= DATE '1994-01-01'
  AND l_shipdate < DATE '1995-01-01'
  AND l_discount >= 0.05
  AND l_discount <= 0.07
  AND l_quantity < 24;

-- q07.sql
SELECT
  supp_nation,
  cust_nation,
  l_year,
  SUM(volume) AS revenue
FROM (
  SELECT
    n1.n_name AS supp_nation,
    n2.n_name AS cust_nation,
    YEAR(l.l_shipdate) AS l_year,
    l.l_extendedprice * (1 - l.l_discount) AS volume
  FROM supplier s
  JOIN lineitem l ON s.s_suppkey = l.l_suppkey
  JOIN orders o ON o.o_orderkey = l.l_orderkey
  JOIN customer c ON c.c_custkey = o.o_custkey
  JOIN nation n1 ON s.s_nationkey = n1.n_nationkey
  JOIN nation n2 ON c.c_nationkey = n2.n_nationkey
  WHERE ((n1.n_name = 'FRANCE' AND n2.n_name = 'GERMANY')
      OR (n1.n_name = 'GERMANY' AND n2.n_name = 'FRANCE'))
    AND l.l_shipdate >= DATE '1995-01-01'
    AND l.l_shipdate <= DATE '1996-12-31'
) shipping
GROUP BY supp_nation, cust_nation, l_year
ORDER BY supp_nation, cust_nation, l_year;

-- q08.sql
SELECT
  o_year,
  SUM(CASE WHEN nation = 'BRAZIL' THEN volume ELSE 0 END) / SUM(volume) AS mkt_share
FROM (
  SELECT
    YEAR(o.o_orderdate) AS o_year,
    l.l_extendedprice * (1 - l.l_discount) AS volume,
    n2.n_name AS nation
  FROM part p
  JOIN lineitem l ON p.p_partkey = l.l_partkey
  JOIN supplier s ON s.s_suppkey = l.l_suppkey
  JOIN orders o ON o.o_orderkey = l.l_orderkey
  JOIN customer c ON c.c_custkey = o.o_custkey
  JOIN nation n1 ON c.c_nationkey = n1.n_nationkey
  JOIN region r ON n1.n_regionkey = r.r_regionkey
  JOIN nation n2 ON s.s_nationkey = n2.n_nationkey
  WHERE r.r_name = 'AMERICA'
    AND o.o_orderdate >= DATE '1995-01-01'
    AND o.o_orderdate <= DATE '1996-12-31'
    AND p.p_type = 'ECONOMY ANODIZED STEEL'
) all_nations
GROUP BY o_year
ORDER BY o_year;

-- q09.sql
SELECT
  nation,
  o_year,
  SUM(amount) AS sum_profit
FROM (
  SELECT
    n.n_name AS nation,
    YEAR(o.o_orderdate) AS o_year,
    l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity AS amount
  FROM part p
  JOIN lineitem l ON p.p_partkey = l.l_partkey
  JOIN partsupp ps ON ps.ps_partkey = l.l_partkey AND ps.ps_suppkey = l.l_suppkey
  JOIN supplier s ON s.s_suppkey = l.l_suppkey
  JOIN orders o ON o.o_orderkey = l.l_orderkey
  JOIN nation n ON s.s_nationkey = n.n_nationkey
  WHERE p.p_name LIKE '%green%'
) profit
GROUP BY nation, o_year
ORDER BY nation, o_year DESC;

-- q10.sql
SELECT
  c.c_custkey,
  c.c_name,
  SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue,
  c.c_acctbal,
  n.n_name,
  c.c_address,
  c.c_phone,
  c.c_comment
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON l.l_orderkey = o.o_orderkey
JOIN nation n ON c.c_nationkey = n.n_nationkey
WHERE o.o_orderdate >= DATE '1993-10-01'
  AND o.o_orderdate < DATE '1994-01-01'
  AND l.l_returnflag = 'R'
GROUP BY c.c_custkey, c.c_name, c.c_acctbal, c.c_phone, n.n_name, c.c_address, c.c_comment
ORDER BY revenue DESC
LIMIT 20;

-- q11.sql
SELECT
  ps.ps_partkey,
  SUM(ps.ps_supplycost * ps.ps_availqty) AS value
FROM partsupp ps
JOIN supplier s ON ps.ps_suppkey = s.s_suppkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
WHERE n.n_name = 'GERMANY'
GROUP BY ps.ps_partkey
HAVING SUM(ps.ps_supplycost * ps.ps_availqty) > (
  SELECT SUM(ps2.ps_supplycost * ps2.ps_availqty) * 0.0001
  FROM partsupp ps2
  JOIN supplier s2 ON ps2.ps_suppkey = s2.s_suppkey
  JOIN nation n2 ON s2.s_nationkey = n2.n_nationkey
  WHERE n2.n_name = 'GERMANY'
)
ORDER BY value DESC;

-- q12.sql
SELECT
  l.l_shipmode,
  SUM(CASE WHEN o.o_orderpriority = '1-URGENT' OR o.o_orderpriority = '2-HIGH' THEN 1 ELSE 0 END) AS high_line_count,
  SUM(CASE WHEN o.o_orderpriority <> '1-URGENT' AND o.o_orderpriority <> '2-HIGH' THEN 1 ELSE 0 END) AS low_line_count
FROM orders o
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
WHERE l.l_shipmode IN ('MAIL', 'SHIP')
  AND l.l_commitdate < l.l_receiptdate
  AND l.l_shipdate < l.l_commitdate
  AND l.l_receiptdate >= DATE '1994-01-01'
  AND l.l_receiptdate < DATE '1995-01-01'
GROUP BY l.l_shipmode
ORDER BY l.l_shipmode;

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

-- q14.sql
SELECT
  100.00 * SUM(CASE WHEN p.p_type LIKE 'PROMO%' THEN l.l_extendedprice * (1 - l.l_discount) ELSE 0 END)
    / SUM(l.l_extendedprice * (1 - l.l_discount)) AS promo_revenue
FROM lineitem l
JOIN part p ON l.l_partkey = p.p_partkey
WHERE l.l_shipdate >= DATE '1995-09-01'
  AND l.l_shipdate < DATE '1995-10-01';

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

-- q16.sql
SELECT
  p.p_brand,
  p.p_type,
  p.p_size,
  COUNT(DISTINCT ps.ps_suppkey) AS supplier_cnt
FROM partsupp ps
JOIN part p ON p.p_partkey = ps.ps_partkey
WHERE p.p_brand <> 'Brand#45'
  AND p.p_type NOT LIKE 'MEDIUM POLISHED%'
  AND p.p_size IN (49, 14, 23, 45, 19, 3, 36, 9)
  AND ps.ps_suppkey NOT IN (
    SELECT s.s_suppkey
    FROM supplier s
    WHERE s.s_comment LIKE '%Customer%Complaints%'
  )
GROUP BY p.p_brand, p.p_type, p.p_size
ORDER BY supplier_cnt DESC, p.p_brand, p.p_type, p.p_size;

-- q17.sql
SELECT
  SUM(l.l_extendedprice) / 7.0 AS avg_yearly
FROM lineitem l
JOIN part p ON p.p_partkey = l.l_partkey
WHERE p.p_brand = 'Brand#23'
  AND p.p_container = 'MED BOX'
  AND l.l_quantity < (
    SELECT 0.2 * AVG(l2.l_quantity)
    FROM lineitem l2
    WHERE l2.l_partkey = p.p_partkey
  );

-- q18.sql
SELECT
  c.c_name,
  c.c_custkey,
  o.o_orderkey,
  o.o_orderdate,
  o.o_totalprice,
  SUM(l.l_quantity) AS sum_quantity
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
WHERE o.o_orderkey IN (
  SELECT l2.l_orderkey
  FROM lineitem l2
  GROUP BY l2.l_orderkey
  HAVING SUM(l2.l_quantity) > 300
)
GROUP BY c.c_name, c.c_custkey, o.o_orderkey, o.o_orderdate, o.o_totalprice
ORDER BY o.o_totalprice DESC, o.o_orderdate
LIMIT 100;

-- q19.sql
SELECT
  SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM lineitem l
JOIN part p ON p.p_partkey = l.l_partkey
WHERE (
    p.p_brand = 'Brand#12'
    AND p.p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
    AND l.l_quantity >= 1 AND l.l_quantity <= 11
    AND p.p_size BETWEEN 1 AND 5
    AND l.l_shipmode IN ('AIR', 'AIR REG')
    AND l.l_shipinstruct = 'DELIVER IN PERSON'
  )
  OR (
    p.p_brand = 'Brand#23'
    AND p.p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
    AND l.l_quantity >= 10 AND l.l_quantity <= 20
    AND p.p_size BETWEEN 1 AND 10
    AND l.l_shipmode IN ('AIR', 'AIR REG')
    AND l.l_shipinstruct = 'DELIVER IN PERSON'
  )
  OR (
    p.p_brand = 'Brand#34'
    AND p.p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
    AND l.l_quantity >= 20 AND l.l_quantity <= 30
    AND p.p_size BETWEEN 1 AND 15
    AND l.l_shipmode IN ('AIR', 'AIR REG')
    AND l.l_shipinstruct = 'DELIVER IN PERSON'
  );

-- q20.sql
SELECT
  s.s_name,
  s.s_address
FROM supplier s
JOIN nation n ON s.s_nationkey = n.n_nationkey
WHERE n.n_name = 'CANADA'
  AND s.s_suppkey IN (
    SELECT ps.ps_suppkey
    FROM partsupp ps
    WHERE ps.ps_partkey IN (
      SELECT p.p_partkey
      FROM part p
      WHERE p.p_name LIKE 'forest%'
    )
      AND ps.ps_availqty > (
        SELECT 0.5 * SUM(l.l_quantity)
        FROM lineitem l
        WHERE l.l_partkey = ps.ps_partkey
          AND l.l_suppkey = ps.ps_suppkey
          AND l.l_shipdate >= DATE '1994-01-01'
          AND l.l_shipdate < DATE '1995-01-01'
      )
  )
ORDER BY s.s_name;

-- q21.sql
SELECT
  s.s_name,
  COUNT(*) AS numwait
FROM supplier s
JOIN lineitem l1 ON s.s_suppkey = l1.l_suppkey
JOIN orders o ON o.o_orderkey = l1.l_orderkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
WHERE o.o_orderstatus = 'F'
  AND l1.l_receiptdate > l1.l_commitdate
  AND EXISTS (
    SELECT 1
    FROM lineitem l2
    WHERE l2.l_orderkey = l1.l_orderkey
      AND l2.l_suppkey <> l1.l_suppkey
  )
  AND NOT EXISTS (
    SELECT 1
    FROM lineitem l3
    WHERE l3.l_orderkey = l1.l_orderkey
      AND l3.l_suppkey <> l1.l_suppkey
      AND l3.l_receiptdate > l3.l_commitdate
  )
  AND n.n_name = 'SAUDI ARABIA'
GROUP BY s.s_name
ORDER BY numwait DESC, s.s_name
LIMIT 100;

-- q22.sql
SELECT
  cntrycode,
  COUNT(*) AS numcust,
  SUM(c_acctbal) AS totacctbal
FROM (
  SELECT
    SUBSTR(c_phone, 1, 2) AS cntrycode,
    c_acctbal,
    c_custkey
  FROM customer
  WHERE SUBSTR(c_phone, 1, 2) IN ('13', '31', '23', '29', '30', '18', '17')
    AND c_acctbal > (
      SELECT AVG(c_acctbal)
      FROM customer
      WHERE c_acctbal > 0.00
        AND SUBSTR(c_phone, 1, 2) IN ('13', '31', '23', '29', '30', '18', '17')
    )
) custsale
WHERE NOT EXISTS (
  SELECT 1
  FROM orders
  WHERE o_custkey = custsale.c_custkey
)
GROUP BY cntrycode
ORDER BY cntrycode;

