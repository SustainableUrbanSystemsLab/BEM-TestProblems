"""Optional PDFO BOBYQA adapter; simulator definitions do not depend on PDFO."""

from functools import partial
from math import isfinite

from .evaluation import make_objective
from .problems import Problem


def solve(problem, *, runner=None, weather=None, x0=None, max_evaluations=1000):
    """Minimize a problem with bounded, scaled BOBYQA evaluations.

    ``max_evaluations`` counts objective calls, including initialization, and
    must be at least ``problem.dimension + 3``. Smaller budgets use fewer
    interpolation points. The supplied start is preserved. Failed simulations
    propagate as errors; no invented objective penalty is substituted.
    The returned object is PDFO's documented ``OptimizeResult``.
    Benchmark problems use the same local setup defaults as ``make_objective``
    when no runner is supplied. Explicit runners retain their selected engine.
    """
    if isinstance(max_evaluations, bool) or not isinstance(max_evaluations, int):
        raise ValueError("max_evaluations must be an integer")
    if max_evaluations < problem.dimension + 3:
        raise ValueError("BOBYQA needs at least dimension + 3 objective evaluations")
    start = tuple(problem.midpoint if x0 is None else x0)
    if len(start) != problem.dimension:
        raise ValueError(f"Expected {problem.dimension} initial parameters")
    for value, (lower, upper) in zip(start, problem.bounds, strict=True):
        if not isfinite(value) or not lower <= value <= upper:
            raise ValueError("Initial parameters must be finite and within their bounds")
    try:
        from pdfo import pdfo
    except ImportError as exc:
        raise ImportError("Install bem-testproblems[optimize] to use PDFO BOBYQA") from exc

    evaluate = (
        make_objective(problem, runner=runner, weather=weather)
        if isinstance(problem, Problem)
        else partial(problem.evaluate, runner=runner, weather=weather)
    )
    failure = None
    evaluations = 0

    def objective(x):
        nonlocal failure, evaluations
        # An exception crossing a compiled Fortran callback can abort Python.
        # Return an invalid value while PDFO unwinds, then re-raise below. Once a
        # failure occurs, no further simulator evaluations are attempted.
        if failure is not None:
            return float("nan")
        if evaluations >= max_evaluations:
            failure = RuntimeError("PDFO attempted to exceed the requested evaluation budget")
            return float("nan")
        evaluations += 1
        try:
            value = float(evaluate(x))
            if not isfinite(value):
                raise ValueError("The simulator returned a nonfinite objective")
            return value
        except BaseException as exc:
            failure = exc
            return float("nan")

    result = pdfo(
        objective,
        start,
        bounds=problem.bounds,
        method="bobyqa",
        options={
            "maxfev": max_evaluations,
            "npt": min(2 * problem.dimension + 1, max_evaluations - 1),
            "scale": True,
            "quiet": True,
            "honour_x0": True,
        },
    )
    if failure is not None:
        raise failure
    return result
