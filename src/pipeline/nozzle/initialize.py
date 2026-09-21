#!/usr/bin/env python3
"""Parameterized verified quasi-1D initialization.

PROVENANCE
----------
Parameterized derivative of validation/canonical_reference/initialize.py (frozen
scientific authority).  The initialization STRATEGY is unchanged: actual mesh
cell centres from foamPostProcess, an explicit non-uniform per-cell quasi-1D
state, a wall-tangent radial startup component, strict read-back verification,
and no use of the obsolete setFieldsDict syntax that Foundation v14 silently
ignored.

ONE DELIBERATE CHANGE, as requested
-----------------------------------
The canonical sanity assertion

    assert v[:,0].min() < 60000 and v[:,0].max() > 190000

hard-codes the canonical reservoir pressure and exit area ratio as absolute
pascal literals.  At p0 = 220 kPa the quasi-1D exit static pressure is 59.5 kPa,
i.e. 0.8% from the 60 kPa literal, so the check would fail for reasons unrelated
to physics.  It is replaced by the physically equivalent statement: the
initialized field must span the quasi-1D range it is constructed from, reaching
down to the supersonic exit static pressure and up to the subsonic inlet static
pressure, within a tolerance that accommodates the declared startup
perturbation.  For the canonical case the replacement is STRICTER on the lower
bound (55.2 kPa versus 60 kPa).  See NozzleCaseSpec.expected_initial_pressure_bounds.

No CFD acceptance threshold is touched by this file.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

try:
    from .spec import NozzleCaseSpec
    from .foamio import field
except ImportError:  # executed as a plain script inside the runtime code dir
    from spec import NozzleCaseSpec
    from foamio import field


def initialize(case: Path) -> dict:
    spec = NozzleCaseSpec.from_manifest(case / 'manifest.json')

    c = field(case / '0/C')

    xs = np.array(spec.axial_breakpoints_m)
    rs = np.array(spec.radii_m)

    throat_end = spec.throat_end_m
    length = spec.length_m
    perturbation = spec.startup_perturbation

    values = []

    for x, y, z in c:
        j = min(np.searchsorted(xs, x, side='right') - 1, len(xs) - 2)
        r = np.interp(x, xs, rs)
        slope = (rs[j + 1] - rs[j]) / (xs[j + 1] - xs[j])

        p, t, u = spec.quasi1d_state(r, x > throat_end)

        p *= 1 + perturbation * np.sin(np.pi * x / length)

        # Quasi-1D axial velocity plus wall-tangent radial component. This is an
        # approximate startup, not an exact 2D steady solution or a persistent
        # source.
        values.append((p, t, u, u * y * slope / r, u * z * slope / r))

    v = np.array(values)

    for name, arr in [('p', v[:, 0]), ('T', v[:, 1]), ('U', v[:, 2:])]:
        path = case / '0' / name
        text = path.read_text()
        vector = arr.ndim == 2

        body = (
            '\n'.join(
                '(' + ' '.join(f'{x:.16g}' for x in row) + ')' for row in arr
            )
            if vector
            else '\n'.join(f'{x:.16g}' for x in arr)
        )

        block = (
            f'internalField nonuniform List<{"vector" if vector else "scalar"}>'
            f'\n{len(arr)}\n(\n{body}\n);'
        )

        text, n = re.subn(
            r'internalField\s+uniform\s+[^;]+;', block, text, count=1
        )

        if n != 1:
            raise ValueError(f'Refusing to reinitialize {path}')

        path.write_text(text)

        assert np.allclose(field(path), arr, rtol=1e-13, atol=1e-13)

    p_min = float(v[:, 0].min())
    p_max = float(v[:, 0].max())

    max_allowed_p_min, min_allowed_p_max = (
        spec.expected_initial_pressure_bounds()
    )

    assert p_min < max_allowed_p_min, (
        f'Initialized minimum pressure {p_min:.6g} Pa does not reach the '
        f'quasi-1D supersonic exit state (required < {max_allowed_p_min:.6g} Pa).'
    )

    assert p_max > min_allowed_p_max, (
        f'Initialized maximum pressure {p_max:.6g} Pa does not reach the '
        f'quasi-1D subsonic inlet state (required > {min_allowed_p_max:.6g} Pa).'
    )

    record = {
        'cells': len(c),
        'p_min': p_min,
        'p_max': p_max,
        'T_min': float(v[:, 1].min()),
        'Uax_max': float(v[:, 2].max()),
        'readback_pass': True,
        'case_id': spec.case_id,
        'expected_p_min_below_pa': max_allowed_p_min,
        'expected_p_max_above_pa': min_allowed_p_max,
        'bounds_basis': (
            'quasi-1D exit and inlet static pressures for this specification, '
            'with a startup-perturbation tolerance'
        ),
    }

    (case / 'initialization_verified.json').write_text(
        json.dumps(record, indent=2)
    )

    return record


if __name__ == '__main__':
    case = Path(sys.argv[1])
    initialize(case)
    print((case / 'initialization_verified.json').read_text())
