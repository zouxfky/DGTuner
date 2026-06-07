class DatabaseAdapter:
    """Interface between tuning algorithms and a concrete DBMS deployment."""

    def get_pbounds(self):
        raise NotImplementedError

    def get_true_values(self, params):
        raise NotImplementedError

    def get_knob_type(self, knob_name):
        raise NotImplementedError

    def normalize_logged_knob_name(self, knob_name):
        return knob_name

    def set_query_timeouts(self, caps_by_index):
        """Optional: per-query execution-time caps in seconds, keyed by 1-based
        statement index within the workload file. No-op unless an adapter supports
        a per-query timeout (e.g. MySQL MAX_EXECUTION_TIME)."""
        return None

    def apply_config(self, params):
        raise NotImplementedError

    def clear_output_log(self):
        raise NotImplementedError

    def run_workload(self, workload_path, concurrency, mode=1):
        raise NotImplementedError

    def run_workload_with_query_info(self, workload_path, concurrency):
        raise NotImplementedError

    def run_workload_target(self, workload_path, concurrency, mode=1):
        status_code, execution_time = self.run_workload(workload_path, concurrency, mode)
        if status_code != 0 or abs(float(execution_time)) < 1:
            return -999
        return -float(execution_time)
