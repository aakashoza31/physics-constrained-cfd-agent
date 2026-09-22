#!/usr/bin/env python3
"""Regression tests for restart-aware transient mass closure (Case H).

BACKGROUND
----------
Case H ran 0 -> 0.5 -> 1 -> 2 as three solver executions of one case. At t = 2
the deterministic validator failed ``transient_mass_closure`` on a single
residual of -4.59e-4, sitting exactly on the 1 -> 2 restart seam. Every other
residual in the same run was ~1e-11 and the p99 was 2.09e-11.

The seam rows, verbatim from iteration_04/transient_mass.csv:

    t = 0.99944  m = 0.4332749512167377  net = -0.1079100485239115
    t = 1.00000  m = 0.4333350147443190  net = -0.1083002922915611
    t = 1.00059  m = 0.4333990977575122  net = -0.1083002922915611

dM/dt across the seam is 0.108108, an entirely ordinary number. The flux it
was differenced against belongs to the RESUMED segment - note that the seam
and the step after it carry the same value to all sixteen digits - so the pair
is a mass increment from one execution against a flux from the next, about one
timestep of flux evolution apart. That mismatch is the residual.

The t = 0.5 seam of the same run produced no spike at all, because the flux
happened to be flat there. Whether a seam shows up is an accident of where the
flux derivative is, which is why this is handled structurally rather than by
widening a tolerance. The 1e-6 conservation threshold is unchanged, and a seam
may only leave the physical statistics if the restart is independently shown
to have continued the same state.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.pipeline.forward_step_2d.collect_evidence import collect
from src.pipeline.forward_step_2d.diagnostics import (
    PHYSICAL_STEP,
    RESTART_BOUNDARY,
    RESTART_MASS_CONTINUITY_TOL,
    restart_continuity,
    select_conservation_basis,
    transient_balance,
)
from src.pipeline.forward_step_2d.validate import STATUS_PASS, validate
from tests.forward_step_2d.synthetic import make_case

FLAT = {"bottom": None, "top": None, "obstacle": None}


def _case_h_pattern(seam_flux_step: float = 3.9024376764962e-4):
    """Two segments meeting at t = 1, built to the Case H numbers.

    Within each segment the mass history is consistent with the flux to
    round-off. The resumed segment writes its own record of the seam instant,
    carrying its first-step flux, exactly as OpenFOAM's function objects do.
    """
    dt = 5.5559170376e-4
    before = np.array([1.0 - 2 * dt, 1.0 - dt, 1.0])
    after = np.array([1.0, 1.0 + dt, 1.0 + 2 * dt])

    net_before = np.array(
        [
            -0.1077092024191905 - seam_flux_step,
            -0.1077092024191905,
            -0.1079100485239115,
        ]
    )
    # The resumed segment's first-step flux, repeated on its seam record.
    net_after = np.full(3, -0.1083002922915611)

    def masses(times, net, start):
        m = [start]
        for i in range(1, len(times)):
            m.append(m[-1] - net[i] * (times[i] - times[i - 1]))
        return np.array(m)

    m_before = masses(before, net_before, 0.4331_648_0)
    m_after = masses(after, net_after, m_before[-1])

    time = np.concatenate([before, after])
    mass = np.concatenate([m_before, m_after])
    net = np.concatenate([net_before, net_after])
    segments = np.array([0, 0, 0, 1, 1, 1])

    zero = np.zeros_like(time)
    fluxes = {
        "inlet": np.full_like(time, -0.35),
        "outlet": net + 0.35,
        "bottom": zero,
        "top": zero,
        "obstacle": zero,
    }
    return time, mass, fluxes, segments


# ----------------------------------------------------------------------
# 7. the exact reported pattern
# ----------------------------------------------------------------------


def test_naive_concatenation_produces_the_seam_spike():
    """Reproduce the defect before asserting the fix removes it."""
    time, mass, fluxes, segments = _case_h_pattern()

    # What the old reader did: keep the LAST record per time, which is the
    # resumed segment's copy of the seam, then difference straight through.
    keep = np.array([0, 1, 3, 4, 5])
    naive, _ = transient_balance(
        time[keep],
        mass[keep],
        {k: v[keep] for k, v in fluxes.items()},
    )
    assert naive["relative_residual_max"] > 1e-4

    # And the segment-aware reader records that same number rather than
    # discarding it.
    aware, _ = transient_balance(time, mass, fluxes, segments=segments)
    (seam,) = aware["restart_boundaries"]
    assert abs(seam["naive_deduplicated_relative_residual"]) == pytest.approx(
        naive["relative_residual_max"], rel=1e-9
    )


def test_within_segment_residuals_are_round_off():
    time, mass, fluxes, segments = _case_h_pattern()
    summary, _ = transient_balance(time, mass, fluxes, segments=segments)
    assert summary["restart_aware"]["relative_residual_max"] < 1e-11
    assert summary["restart_aware"]["restart_boundaries_excluded"] == 1


def test_the_seam_measurement_is_preserved_and_classified():
    """Requirement: keep the raw measurement, do not hide it."""
    time, mass, fluxes, segments = _case_h_pattern()
    summary, table = transient_balance(time, mass, fluxes, segments=segments)

    (seam,) = summary["restart_boundaries"]
    assert seam["classification"] == RESTART_BOUNDARY
    assert seam["time"] == pytest.approx(1.0)
    assert seam["from_segment"] == 0 and seam["to_segment"] == 1
    # The historical naive reading is kept verbatim, with its provenance.
    assert abs(seam["naive_deduplicated_relative_residual"]) > 1e-4
    assert "not a physical residual" in seam["naive_note"].lower()

    # And the row is flagged in the CSV-bound table.
    assert table[:, 6].sum() == 1


def test_no_derivative_is_formed_across_the_seam():
    """The core rule: two executions, no timestep between them."""
    time, mass, fluxes, segments = _case_h_pattern()
    summary, table = transient_balance(time, mass, fluxes, segments=segments)
    seam_rows = table[table[:, 6] == 1]
    assert len(seam_rows) == 1
    assert seam_rows[0][3] == 0.0  # residual not formed
    assert summary["segments"][0]["end_time"] == pytest.approx(1.0)
    assert summary["segments"][1]["start_time"] == pytest.approx(1.0)


def test_both_statistics_are_reported_for_audit():
    """A and B side by side, so a reviewer sees exactly what happened."""
    time, mass, fluxes, segments = _case_h_pattern()
    summary, _ = transient_balance(time, mass, fluxes, segments=segments)

    assert summary["raw"]["includes_restart_boundaries"] is True
    assert summary["raw"]["samples"] > summary["restart_aware"]["samples"]
    assert "cumulative_defect_fraction_initial_mass" in summary["raw"]
    assert "cumulative_defect_fraction_initial_mass" in summary["restart_aware"]
    assert len(summary["segments"]) == 2


def test_a_single_segment_run_is_unchanged():
    """Nothing about a run with no restart may move."""
    t = np.linspace(0, 1, 11)
    inlet = np.full_like(t, -0.5)
    outlet = np.full_like(t, 0.3)
    zero = np.zeros_like(t)
    fluxes = {"inlet": inlet, "outlet": outlet, "bottom": zero, "top": zero,
              "obstacle": zero}
    mass = 1.0 + 0.2 * t

    plain, _ = transient_balance(t, mass, fluxes)
    labelled, _ = transient_balance(t, mass, fluxes, segments=np.zeros(11, int))

    assert plain["restart_boundaries"] == []
    assert plain["relative_residual_max"] == labelled["relative_residual_max"]
    assert plain["raw"]["samples"] == plain["restart_aware"]["samples"]


# ----------------------------------------------------------------------
# 4. continuity across the seam, verified independently
# ----------------------------------------------------------------------


def test_a_verified_restart_passes_end_to_end(tmp_path):
    """Segments detected, seam verified, closure computed within segments."""
    case = make_case(tmp_path, restart_at=0.2)
    collect(case, tmp_path / "out")
    mass = json.loads((tmp_path / "out/diagnostics.json").read_text())["mass"]

    continuity = mass["restart_continuity"]
    assert continuity["seam_count"] == 1
    assert continuity["all_seams_continuous"] is True
    (seam,) = continuity["seams"]
    assert seam["checks"] == {
        "stored_mass_continuous": True,
        "seam_times_match": True,
        "start_from_latest_time": True,
        "recorded_as_continuation": True,
        "restart_state_present": True,
    }
    assert seam["fields_reinitialized"] is False
    assert seam["relative_mass_jump"] <= RESTART_MASS_CONTINUITY_TOL

    assert mass["conservation_basis"] == "restart_aware"
    validation = json.loads((tmp_path / "out/validation.json").read_text())
    assert validation["hard_checks"]["transient_mass_closure"] is True
    assert validation["status"] == STATUS_PASS


def test_a_real_restart_discontinuity_fails(tmp_path):
    """Requirement: a restart that did not continue the state must fail."""
    case = make_case(tmp_path, restart_at=0.2, seam_mass_jump=1e-4)
    collect(case, tmp_path / "out")

    mass = json.loads((tmp_path / "out/diagnostics.json").read_text())["mass"]
    (seam,) = mass["restart_continuity"]["seams"]
    assert seam["checks"]["stored_mass_continuous"] is False
    assert seam["continuous"] is False
    assert seam["fields_reinitialized"] is True
    assert seam["relative_mass_jump"] > RESTART_MASS_CONTINUITY_TOL

    # Fail closed: an unverified seam may not be excluded, so the raw
    # statistics stand and the check fails.
    assert mass["conservation_basis"] == "raw"
    assert "not demonstrated" in mass["conservation_basis_reason"]

    validation = json.loads((tmp_path / "out/validation.json").read_text())
    assert validation["hard_checks"]["transient_mass_closure"] is False
    assert "transient_mass_closure" in validation["failed_checks"]
    assert validation["status"] == "FAIL"


def test_an_unverified_seam_cannot_be_excluded_by_residuals_alone():
    """Healthy within-segment residuals must not rescue a broken restart."""
    time, mass, fluxes, segments = _case_h_pattern()
    summary, _ = transient_balance(time, mass, fluxes, segments=segments)
    assert summary["restart_aware"]["relative_residual_max"] < 1e-11

    broken = select_conservation_basis(
        dict(summary),
        {"all_seams_continuous": False, "seam_count": 1, "seams": []},
    )
    assert broken["conservation_basis"] == "raw"

    document = {
        "mass": {**broken, "impermeable_flux_max_abs": 0.0, "final_inlet": 0.35}
    }
    assert not (
        document["mass"]["relative_residual_max"] < 1e-6
        and document["mass"]["restart_continuity"]["all_seams_continuous"]
    )


@pytest.mark.parametrize(
    "missing", ["start_from_latest_time", "recorded_as_continuation"]
)
def test_every_continuity_check_is_necessary(tmp_path, missing):
    """Removing any one piece of evidence must block the exclusion."""
    case = make_case(tmp_path, restart_at=0.2)

    if missing == "start_from_latest_time":
        control = case / "system/controlDict"
        control.write_text(
            control.read_text().replace("startFrom       latestTime;",
                                        "startFrom       startTime;")
        )
    else:
        records = json.loads((case / "execution.json").read_text())
        records[1]["continuation"] = False
        (case / "execution.json").write_text(json.dumps(records))

    collect(case, tmp_path / "out")
    mass = json.loads((tmp_path / "out/diagnostics.json").read_text())["mass"]
    (seam,) = mass["restart_continuity"]["seams"]

    assert seam["checks"][missing] is False
    assert seam["continuous"] is False
    assert mass["conservation_basis"] == "raw"
    validation = json.loads((tmp_path / "out/validation.json").read_text())
    assert validation["hard_checks"]["transient_mass_closure"] is False


def test_a_missing_restart_state_blocks_the_exclusion(tmp_path):
    """The state a restart claims to have read must still be on disk.

    Checked directly rather than by deleting a saved time directory, which
    would also remove fields the rest of the diagnostic legitimately needs.
    """
    from src.pipeline.forward_step_2d.diagnostics import _monitor_segments

    case = make_case(tmp_path, restart_at=0.2)
    segments = _monitor_segments(case, "mass")
    execution = json.loads((case / "execution.json").read_text())

    elsewhere = tmp_path / "no_saved_states"
    (elsewhere / "system").mkdir(parents=True)
    (elsewhere / "system/controlDict").write_text("startFrom       latestTime;\n")

    continuity = restart_continuity(elsewhere, segments, execution)
    (seam,) = continuity["seams"]
    assert seam["checks"]["restart_state_present"] is False
    assert seam["continuous"] is False
    assert continuity["all_seams_continuous"] is False


# ----------------------------------------------------------------------
# 1. segment detection from runtime evidence
# ----------------------------------------------------------------------


def test_segments_are_detected_from_the_monitor_layout(tmp_path):
    """OpenFOAM names one postProcessing directory per solver invocation."""
    from src.pipeline.forward_step_2d.diagnostics import _monitor_segments

    case = make_case(tmp_path, restart_at=0.2)
    segments = _monitor_segments(case, "mass")

    assert [start for start, _ in segments] == [0.0, 0.2]
    assert segments[0][1][-1, 0] == pytest.approx(0.2)
    assert segments[1][1][0, 0] == pytest.approx(0.2)
    # Both records of the seam survive; collapsing them would make the
    # restart unverifiable.
    assert len(segments[0][1]) + len(segments[1][1]) == 32


def test_a_case_with_no_restart_reports_no_seams(tmp_path):
    case = make_case(tmp_path)
    collect(case, tmp_path / "out")
    mass = json.loads((tmp_path / "out/diagnostics.json").read_text())["mass"]
    assert mass["restart_continuity"]["seam_count"] == 0
    assert mass["restart_continuity"]["all_seams_continuous"] is True
    assert mass["conservation_basis"] == "restart_aware"
    assert mass["raw"]["relative_residual_max"] == pytest.approx(
        mass["restart_aware"]["relative_residual_max"]
    )


def test_missing_execution_records_are_treated_as_unverified(tmp_path):
    """Absence of evidence is not evidence of continuity."""
    case = make_case(tmp_path, restart_at=0.2)
    from src.pipeline.forward_step_2d.diagnostics import _monitor_segments

    segments = _monitor_segments(case, "mass")
    continuity = restart_continuity(case, segments, execution=[])
    assert continuity["all_seams_continuous"] is False
    assert continuity["seams"][0]["checks"]["recorded_as_continuation"] is False


def test_the_classification_labels_are_distinct():
    assert PHYSICAL_STEP != RESTART_BOUNDARY
    assert "RESTART" in RESTART_BOUNDARY


def test_the_conservation_threshold_is_untouched():
    """The fix must not weaken the bound it was accused of tripping."""
    from pathlib import Path

    source = Path("src/pipeline/forward_step_2d/validate.py").read_text()
    assert 'd["mass"]["relative_residual_max"] < 1e-6' in source
