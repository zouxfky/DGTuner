DROP DATABASE IF EXISTS tpch;
CREATE DATABASE tpch;
USE tpch;

CREATE TABLE region (
  r_regionkey INT NOT NULL,
  r_name VARCHAR(25) NOT NULL,
  r_comment VARCHAR(152),
  PRIMARY KEY (r_regionkey)
) ENGINE=InnoDB;

CREATE TABLE nation (
  n_nationkey INT NOT NULL,
  n_name VARCHAR(25) NOT NULL,
  n_regionkey INT NOT NULL,
  n_comment VARCHAR(152),
  PRIMARY KEY (n_nationkey),
  KEY n_regionkey_idx (n_regionkey)
) ENGINE=InnoDB;

CREATE TABLE part (
  p_partkey INT NOT NULL,
  p_name VARCHAR(55) NOT NULL,
  p_mfgr VARCHAR(25) NOT NULL,
  p_brand VARCHAR(10) NOT NULL,
  p_type VARCHAR(25) NOT NULL,
  p_size INT NOT NULL,
  p_container VARCHAR(10) NOT NULL,
  p_retailprice DECIMAL(15,2) NOT NULL,
  p_comment VARCHAR(23) NOT NULL,
  PRIMARY KEY (p_partkey)
) ENGINE=InnoDB;

CREATE TABLE supplier (
  s_suppkey INT NOT NULL,
  s_name VARCHAR(25) NOT NULL,
  s_address VARCHAR(40) NOT NULL,
  s_nationkey INT NOT NULL,
  s_phone VARCHAR(15) NOT NULL,
  s_acctbal DECIMAL(15,2) NOT NULL,
  s_comment VARCHAR(101) NOT NULL,
  PRIMARY KEY (s_suppkey),
  KEY s_nationkey_idx (s_nationkey)
) ENGINE=InnoDB;

CREATE TABLE partsupp (
  ps_partkey INT NOT NULL,
  ps_suppkey INT NOT NULL,
  ps_availqty INT NOT NULL,
  ps_supplycost DECIMAL(15,2) NOT NULL,
  ps_comment VARCHAR(199) NOT NULL,
  PRIMARY KEY (ps_partkey, ps_suppkey),
  KEY ps_suppkey_idx (ps_suppkey)
) ENGINE=InnoDB;

CREATE TABLE customer (
  c_custkey INT NOT NULL,
  c_name VARCHAR(25) NOT NULL,
  c_address VARCHAR(40) NOT NULL,
  c_nationkey INT NOT NULL,
  c_phone VARCHAR(15) NOT NULL,
  c_acctbal DECIMAL(15,2) NOT NULL,
  c_mktsegment VARCHAR(10) NOT NULL,
  c_comment VARCHAR(117) NOT NULL,
  PRIMARY KEY (c_custkey),
  KEY c_nationkey_idx (c_nationkey),
  KEY c_mktsegment_idx (c_mktsegment)
) ENGINE=InnoDB;

CREATE TABLE orders (
  o_orderkey INT NOT NULL,
  o_custkey INT NOT NULL,
  o_orderstatus VARCHAR(1) NOT NULL,
  o_totalprice DECIMAL(15,2) NOT NULL,
  o_orderdate DATE NOT NULL,
  o_orderpriority VARCHAR(15) NOT NULL,
  o_clerk VARCHAR(15) NOT NULL,
  o_shippriority INT NOT NULL,
  o_comment VARCHAR(79) NOT NULL,
  PRIMARY KEY (o_orderkey),
  KEY o_custkey_idx (o_custkey),
  KEY o_orderdate_idx (o_orderdate)
) ENGINE=InnoDB;

CREATE TABLE lineitem (
  l_orderkey INT NOT NULL,
  l_partkey INT NOT NULL,
  l_suppkey INT NOT NULL,
  l_linenumber INT NOT NULL,
  l_quantity DECIMAL(15,2) NOT NULL,
  l_extendedprice DECIMAL(15,2) NOT NULL,
  l_discount DECIMAL(15,2) NOT NULL,
  l_tax DECIMAL(15,2) NOT NULL,
  l_returnflag VARCHAR(1) NOT NULL,
  l_linestatus VARCHAR(1) NOT NULL,
  l_shipdate DATE NOT NULL,
  l_commitdate DATE NOT NULL,
  l_receiptdate DATE NOT NULL,
  l_shipinstruct VARCHAR(25) NOT NULL,
  l_shipmode VARCHAR(10) NOT NULL,
  l_comment VARCHAR(44) NOT NULL,
  PRIMARY KEY (l_orderkey, l_linenumber),
  KEY l_part_supp_idx (l_partkey, l_suppkey),
  KEY l_suppkey_idx (l_suppkey),
  KEY l_shipdate_idx (l_shipdate),
  KEY l_receiptdate_idx (l_receiptdate)
) ENGINE=InnoDB;
