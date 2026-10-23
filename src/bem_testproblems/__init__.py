"""Continuous building energy optimization problems.

Problem definitions are independent of the execution and optimization backends.
"""

__version__ = "0.1.0.dev0"


def get_problem(problem_id, *, numerical_variant="replication"):
    """Return a replication profile; pass numerical_variant="canonical" to opt out.

    P5/P6/P8 use historical HVAC compatibility, P1/P3/P4/P9/P10 use corrected
    v3, and P2/P13 use canonical models. Imports require no simulator.
    """
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
