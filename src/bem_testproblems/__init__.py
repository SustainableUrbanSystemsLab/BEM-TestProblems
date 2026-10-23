"""Continuous building energy optimization problems.

Problem definitions are independent of the execution and optimization backends.
"""

__version__ = "0.1.0.dev0"


def get_problem(problem_id, *, numerical_variant=None):
    """Return one of problems 1–6, 8–10 or 13; imports require no simulator."""
    from .problems import get_problem as lookup

    return lookup(problem_id, numerical_variant=numerical_variant)


def __getattr__(name):
    if name == "make_objective":
        from .evaluation import make_objective

        return make_objective
    if name == "EnergyPlusRunner":
        from .energyplus import EnergyPlusRunner

        return EnergyPlusRunner
    if name in {"solve_bobyqa", "solve"}:
        from .optimize import solve_bobyqa

        return solve_bobyqa
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
