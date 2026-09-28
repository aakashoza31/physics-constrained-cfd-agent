"""F3: surface-mounted cube. Executed, and deterministically REJECTED.

This family is a headline demonstration of REFUSAL, not of validation. Its one
registered case ran a 3-D turbulent CFD case to completion, looked numerically
healthy throughout, and was rejected because a lateral mode kept growing.
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
