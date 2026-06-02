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
