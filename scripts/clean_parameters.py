"""Aggressively clean the parameter knowledge bases in place.

Removes performance-irrelevant families (connection/deploy/protocol, observability,
binlog/replication/GTID/PFS, backup, coordinator metadata, risky durability),
out-of-range sentinel defaults, deprecated redo-log knobs, and enum-as-bool knobs.

Run:  python3 scripts/clean_parameters.py
"""
import json

MYSQL_PATH = "databases/mysql/knowledge/parameters.jsonl"
DINGO_PATH = "databases/dingodb/knowledge/parameters.jsonl"

# --- MySQL removal rules ---------------------------------------------------
MYSQL_REMOVE_PREFIXES = (
    "mysqlx_",            # X Protocol network endpoint / compression / timeouts
    "performance_schema", # PFS sizing infrastructure
    "binlog_",            # binary log (read-only TPC-H writes nothing)
    "optimizer_trace",    # optimizer trace output (observability)
    "replica_",           # replication applier topology
    "slave_",             # replication (legacy names)
    "relay_log",          # relay log (replication)
)

MYSQL_REMOVE_IDS = {
    # replication / binlog (non-prefixed)
    "log_bin", "log_bin_trust_function_creators", "log_bin_use_v1_row_events",
    "log_replica_updates", "log_slave_updates", "master_info_repository",
    "master_verify_checksum", "max_relay_log_size", "rpl_read_size",
    "rpl_stop_replica_timeout", "rpl_stop_slave_timeout", "sync_master_info",
    "sync_source_info", "sync_relay_log", "sync_relay_log_info",
    "max_binlog_cache_size", "max_binlog_size", "max_binlog_stmt_cache_size",
    "sync_binlog",
    # GTID
    "enforce_gtid_consistency", "gtid_executed_compression_period", "gtid_mode",
    # credentials / auth / roles / host resolution
    "activate_all_roles_on_login", "automatic_sp_privileges",
    "caching_sha2_password_digest_rounds", "check_proxy_users",
    "default_password_lifetime", "disconnect_on_expired_password",
    "generated_random_password_length", "partial_revokes", "password_history",
    "password_require_current", "password_reuse_interval",
    "print_identified_with_as_hex", "skip_name_resolve",
    # connection / network / OS endpoints
    "back_log", "connect_timeout", "create_admin_listener_thread",
    "host_cache_size", "interactive_timeout", "max_connect_errors",
    "max_connections", "max_delayed_threads", "max_insert_delayed_threads",
    "max_user_connections", "net_buffer_length", "net_read_timeout",
    "net_retry_count", "net_write_timeout", "open_files_limit", "thread_stack",
    "wait_timeout",
    # logging / slow log / profiling
    "expire_logs_days", "general_log", "log_error_verbosity", "log_output",
    "log_queries_not_using_indexes", "log_raw", "log_slow_admin_statements",
    "log_slow_extra", "log_slow_replica_statements", "log_slow_slave_statements",
    "log_statements_unsafe_for_binlog", "log_throttle_queries_not_using_indexes",
    "log_timestamps", "long_query_time", "min_examined_row_limit",
    "slow_launch_time", "slow_query_log", "sql_log_off", "profiling_history_size",
    # InnoDB diagnostic output
    "innodb_ft_enable_diag_print", "innodb_print_all_deadlocks",
    "innodb_print_ddl_logs", "innodb_status_output", "innodb_status_output_locks",
    # PFS sizing (non-prefixed)
    "max_digest_length", "max_sql_text_length", "max_statement_stack",
    "session_connect_attrs_size", "show_processlist",
    # other observability
    "information_schema_stats_expiry", "innodb_cmp_per_index_enabled",
    # no-write (read-only TPC-H never inserts)
    "auto_increment_increment", "auto_increment_offset",
    # deprecated in 8.0.30 (replaced by innodb_redo_log_capacity)
    "innodb_log_file_size", "innodb_log_files_in_group", "innodb_log_checksums",
    # deprecated / enum-as-bool / no perf meaning
    "avoid_temporal_upgrade", "event_scheduler",
    # out-of-range sentinel defaults (default = 2^64-1 with a small max)
    "connection_memory_limit", "global_connection_memory_limit",
    "max_seeks_for_key", "myisam_max_sort_file_size", "myisam_mmap_size",
    "parser_max_mem_size",
}

# --- DingoDB removal rules (exact ids) -------------------------------------
DINGO_REMOVE_IDS = {
    # observability: log switches / tracing / print / latency logs / metrics
    "-dingo_log_switch_coor_kv", "-dingo_log_switch_coor_lease",
    "-dingo_log_switch_coor_watch", "-dingo_log_switch_scalar_speed_up_detail",
    "-dingo_log_switch_txn_detail", "-dingo_log_switch_diskann_detail",
    "-dingo_log_switch_txn_gc_detail", "-dingo_trace_append_entry_latency",
    "-print_periodic_merge_check", "-print_periodic_split_check",
    "-print_process_job_error", "-print_raft_add_node",
    "-print_recycle_orphan_region_not_table_or_index",
    "-raft_latency_log_append_entries", "-raft_latency_log_batch_append_entries",
    "-raft_latency_log_handle_append_entries", "-raft_latency_log_init",
    "-raft_latency_log_threshold_ms", "-service_log_threshold_time_ns",
    "server.approximate_size_metrics_collect_interval_s",
    "server.metrics_collect_interval_s", "store.stats_dump_period_s",
    "coordinator.calc_metrics_interval_s", "server.store_metrics_collect_interval_s",
    "-enable_coprocessor_v2_statistics_time_consumption",
    "-enable_rocksdb_perf_metric", "log.level",
    # service exposure / backup-restore
    "-enable_dir_service", "-enable_threads_service",
    "-max_restore_count", "-max_restore_data_memory_size",
    # sentinel timers (default ~1048576 seconds ~= 12 days)
    "-bdb_checkpoint_time_s", "-bdb_dead_lock_detect_time_s", "-bdb_stat_time_s",
    # coordinator metadata management (no steady read-query effect)
    "-async_create_table", "coordinator.auto_compaction",
    "coordinator.balance_leader_inspection_time_period",
    "coordinator.balance_region_default_region_count_ratio",
    "coordinator.balance_region_inspection_time_period",
    "coordinator.compaction_interval_s",
    "coordinator.compaction_retention_rev_count", "coordinator.job_interval_s",
    "coordinator.lease_interval_s", "coordinator.meta_watch_clean_interval_s",
    "coordinator.push_interval_s", "coordinator.recycle_job_interval_s",
    "coordinator.recycle_orphan_interval_s", "coordinator.remove_watch_interval_s",
    "coordinator.reserve_job_recent_day", "coordinator.update_state_interval_s",
    # risky: durability / replication / structural (destabilizing to auto-tune)
    "-raft_sync", "-raft_meta_force_no_sync", "-raft_meta_periodic_sync_enabled",
    "-raft_meta_periodic_sync_interval_ms", "-default_replica_num",
    "raft.election_timeout_s", "region.enable_auto_split",
    "region.enable_auto_merge", "region.split_strategy",
}


def clean(path, remove_ids, remove_prefixes=()):
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    kept, removed = [], []
    for record in rows:
        pid = record["id"]
        if pid in remove_ids or (remove_prefixes and pid.startswith(remove_prefixes)):
            removed.append(pid)
        else:
            kept.append(record)
    with open(path, "w", encoding="utf-8") as out:
        for record in kept:
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"\n===== {path} =====")
    print(f"total={len(rows)}  removed={len(removed)}  kept={len(kept)}")
    print("--- removed ---")
    for pid in removed:
        print("  ", pid)
    return kept


if __name__ == "__main__":
    clean(MYSQL_PATH, MYSQL_REMOVE_IDS, MYSQL_REMOVE_PREFIXES)
    clean(DINGO_PATH, DINGO_REMOVE_IDS)
