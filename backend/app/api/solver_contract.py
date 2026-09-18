"""Integration-level outcomes exposed by solver adapters.

These describe what the run API can safely do next. Solver implementations
translate their domain-specific errors into one of these outcomes at the
adapter boundary instead of leaking solver internals into HTTP orchestration.
"""


class SolverUnavailable(RuntimeError):
    """No solver implementation is installed or configured."""


class ScenarioUnavailable(RuntimeError):
    """The requested scenario is not implemented by the active solver."""


class SolverInputInvalid(RuntimeError):
    """Cross-file or topology validation rejected a parseable input instance."""
