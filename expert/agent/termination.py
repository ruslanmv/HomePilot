class TerminationPolicy:
    def should_stop(self, step_count: int, max_steps: int, saw_finalize: bool) -> bool:
        if saw_finalize:
            return True
        return step_count >= max_steps
