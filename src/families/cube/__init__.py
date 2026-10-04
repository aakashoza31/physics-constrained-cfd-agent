"""Experimental surface-mounted cube stationarity/development study.

This family demonstrates REFUSAL, not validation. Its one registered case ran a
3-D turbulent (incompressible URANS, k-omega SST) CFD case to completion,
looked numerically healthy throughout, and was rejected because a lateral mode
kept growing (half-window lateral-force ratio 2.10 against a limit of 1.25).
The case was run outside the agent loop; the stationarity gate
(cube-stationarity/1.0.0) was registered retrospectively on 2026-09-28.
Nothing here may be presented as a successful validation.
"""
from src.families.cube.stationarity import (  # noqa: F401
    ASSESSMENT_WINDOW,
    FORCE_DRIFT_FRACTION_MAX,
    LATERAL_GROWTH_RATIO_MAX,
    LATERAL_RELATIVE_MAX,
    StationarityResult,
    assess,
)
