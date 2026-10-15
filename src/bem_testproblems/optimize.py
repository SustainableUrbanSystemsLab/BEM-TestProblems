"""Optional PDFO BOBYQA adapter; simulator definitions do not depend on PDFO."""

from math import isfinite


def solve(problem, *, runner, weather=None, x0=None, max_evaluations=1000):
    """Minimize a problem with bounded, scaled BOBYQA evaluations.

    ``max_evaluations`` counts objective calls, including initialization. Failed
    simulations propagate as errors; no invented objective penalty is substituted.
    The returned object is PDFO's documented ``OptimizeResult``.
    """
    if isinstance(max_evaluations, bool) or not isinstance(max_evaluations, int):
        raise ValueError("max_evaluations must be an integer")
    if max_evaluations < problem.dimension + 2:
        raise ValueError("BOBYQA needs at least dimension + 2 objective evaluations")
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

    failure = None

    def objective(x):
        nonlocal failure
        # An exception crossing a compiled Fortran callback can abort Python.
        # Return an invalid value while PDFO unwinds, then re-raise below. Once a
        # failure occurs, no further simulator evaluations are attempted.
        if failure is not None:
            return float("nan")
        try:
            value = float(problem.evaluate(x, runner=runner, weather=weather))
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
        options={"maxfev": max_evaluations, "scale": True, "quiet": True},
    )
    if failure is not None:
        raise failure
    return result
