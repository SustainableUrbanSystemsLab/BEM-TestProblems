"""Continuous building energy optimization problems.

Problem definitions are independent of the execution and optimization backends.
"""

__version__ = "0.1.0.dev0"


def get_problem(problem_id):
    """Return one of problems 1–6, 8–10 or 13; imports require no simulator."""
    from .problems import get_problem as lookup

    return lookup(problem_id)


def __getattr__(name):
    if name == "EnergyPlusRunner":
        from .energyplus import EnergyPlusRunner

        return EnergyPlusRunner
    if name == "solve":
        from .optimize import solve

        return solve
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
