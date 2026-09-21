#!/usr/bin/env python3
"""Parameterized Foundation v14 conical nozzle case generator.

PROVENANCE
----------
Parameterized derivative of validation/canonical_reference/build.py (frozen
scientific authority).  Every dictionary is emitted with the same structure and
the same text; only the geometry breakpoints, reservoir state, ambient pressure
and numerical controls come from a NozzleCaseSpec instead of module literals.

UNCHANGED, DELIBERATELY:
  solver               shockFluid (foamRun)
  flux scheme          Kurganov
  reconstruction       Minmod on rho, U, T
  time integration     Euler, adjustable dt, maxCo from the specification
  thermo               hePsiThermo / pureMixture / eConst / perfectGas
                       sensibleInternalEnergy, mu = 0, Pr = 1
  inlet                totalPressure + totalTemperature + directionMixed
  outlet               zeroGradient p/T/U, no imposed back pressure
  walls                slip / adiabatic
  azimuthal            one-cell wedge, wedgeFront/wedgeBack, empty axis
  function objects     per-timestep domain mass, extrema, all boundary fluxes

tests/nozzle_e2e/test_canonical_equivalence.py asserts byte equality of every
generated OpenFOAM input against the frozen authority for the canonical case.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    from .spec import NozzleCaseSpec, num
except ImportError:  # executed as a plain script inside the runtime code dir
    from spec import NozzleCaseSpec, num


def header(name, cls='dictionary'):
    return f'FoamFile {{ format ascii; class {cls}; object {name}; }}\n'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def build(case: Path, spec: NozzleCaseSpec) -> NozzleCaseSpec:
    spec.validate()

    if case.exists():
        raise RuntimeError(f'Refusing to overwrite {case}')

    xs = spec.axial_breakpoints_m
    rs = spec.radii_m

    nx = spec.axial_cells
    nr = spec.radial_cells

    p0 = spec.total_pressure_pa
    t0 = spec.total_temperature_k

    a = math.radians(spec.wedge_angle_deg / 2)
    verts = []

    for x, r in zip(xs, rs):
        verts.extend([
            (x, 0, 0),
            (x, r * math.cos(a), -r * math.sin(a)),
            (x, r * math.cos(a), r * math.sin(a)),
        ])

    blocks = []
    front = []
    back = []
    wall = []

    for i, n in enumerate(nx):
        b = 3 * i
        c = b + 3
        blocks.append(
            f'hex ({b} {c} {c+1} {b+1} {b} {c} {c+2} {b+2}) '
            f'({n} {nr} 1) simpleGrading (1 1 1)'
        )
        front.append(f'({b} {b+1} {c+1} {c})')
        back.append(f'({b} {c} {c+2} {b+2})')
        wall.append(f'({b+1} {b+2} {c+2} {c+1})')

    last = 3 * (len(xs) - 1)

    bd = ''

    for name, typ, faces in [
        ('inlet', 'patch', ['(0 2 1 0)']),
        ('outlet', 'patch', [f'({last} {last+1} {last+2} {last})']),
        ('walls', 'wall', wall),
        ('wedgeFront', 'wedge', front),
        ('wedgeBack', 'wedge', back),
    ]:
        bd += f'{name} {{ type {typ}; faces ( {" ".join(faces)} ); }}\n'

    write(
        case / 'system/blockMeshDict',
        header('blockMeshDict')
        + 'vertices (\n'
        + '\n'.join('(%.16g %.16g %.16g)' % v for v in verts)
        + '\n);\nblocks (\n'
        + '\n'.join(blocks)
        + '\n);\nedges ();\ndefaultPatch {name axis; type empty;}\nboundary (\n'
        + bd
        + ');\n',
    )

    write(
        case / 'constant/physicalProperties',
        header('physicalProperties')
        + '''thermoType { type hePsiThermo; mixture pureMixture; transport const; thermo eConst; equationOfState perfectGas; specie specie; energy sensibleInternalEnergy; }
mixture { specie { molWeight 28.9702542045296; } thermodynamics { Cv 717.5; Hf 0; } transport { mu 0; Pr 1; } }
''',
    )

    write(
        case / 'constant/momentumTransport',
        header('momentumTransport') + 'simulationType laminar;\n',
    )

    write(
        case / 'system/fvSchemes',
        header('fvSchemes')
        + '''fluxScheme Kurganov;
ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; reconstruct(rho) Minmod; reconstruct(U) Minmod; reconstruct(T) Minmod; }
snGradSchemes { default corrected; }
''',
    )

    write(
        case / 'system/fvSolution',
        header('fvSolution')
        + '''solvers { "rho.*" { solver diagonal; } "(U|e).*" { solver diagonal; } }
PIMPLE { nOuterCorrectors 1; }
''',
    )

    p, t, u = spec.quasi1d_state(spec.inlet_radius_m, False)

    for name, val, dim, bc in [
        (
            'p',
            str(p),
            'pressure',
            f'type totalPressure; p0 uniform {num(p0)}; psi psi; '
            f'gamma {num(spec.gamma)}; value uniform {p};',
        ),
        (
            'T',
            str(t),
            'temperature',
            f'type totalTemperature; T0 uniform {num(t0)}; '
            f'gamma {num(spec.gamma)}; psi psi; value uniform {t};',
        ),
        (
            'U',
            f'({u} 0 0)',
            'velocity',
            'type directionMixed; refValue uniform (0 0 0); '
            'refGradient uniform (0 0 0); valueFraction uniform (0 0 0 1 0 1);',
        ),
    ]:
        cls = 'volVectorField' if name == 'U' else 'volScalarField'
        wallbc = 'slip' if name == 'U' else 'zeroGradient'

        write(
            case / '0' / name,
            header(name, cls)
            + f'dimensions [{dim}];\ninternalField uniform {val};\n'
            + f'boundaryField {{ inlet {{ {bc} }} outlet {{type zeroGradient;}} '
            + f'walls {{type {wallbc};}} wedgeFront {{type wedge;}} '
            + 'wedgeBack {type wedge;} axis {type empty;} }\n',
        )

    funcs = '''mass {type volFieldValue; libs ("libfieldFunctionObjects.so"); cellZone all; operation volIntegrate; writeFields false; fields (rho); writeControl timeStep; writeInterval 1; log false;}
extrema {type volFieldValue; cellZone all; operation min; writeFields false; libs ("libfieldFunctionObjects.so"); fields (p T rho); writeControl timeStep; writeInterval 1; log false;}
'''

    for patch in ['inlet', 'outlet', 'walls', 'wedgeFront', 'wedgeBack']:
        funcs += (
            f'flux_{patch} {{type surfaceFieldValue; '
            f'libs ("libfieldFunctionObjects.so"); patch {patch}; '
            f'operation sum; fields (phi); writeFields false; '
            f'writeControl timeStep; writeInterval 1; log false;}}\n'
        )

    for patch in ['inlet', 'outlet']:
        funcs += (
            f'average_{patch} {{type surfaceFieldValue; '
            f'libs ("libfieldFunctionObjects.so"); patch {patch}; '
            f'operation areaAverage; fields (p T U); writeFields false; '
            f'writeControl timeStep; writeInterval 20; log false;}}\n'
        )

    write(
        case / 'system/controlDict',
        header('controlDict')
        + f'''application foamRun;
solver shockFluid;
startFrom startTime; startTime 0; stopAt endTime; endTime {num(spec.end_time_s)};
deltaT 1e-8; adjustTimeStep yes; maxCo {num(spec.max_courant)}; maxDeltaT 2e-6;
writeControl adjustableRunTime; writeInterval 0.00025; purgeWrite 0;
writeFormat ascii; writePrecision 14; writeCompression off; timePrecision 14;
runTimeModifiable false;
functions {{ {funcs} }}
''',
    )

    write(
        case / 'manifest.json',
        json.dumps(spec.manifest(), indent=2),
    )

    return spec


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Generate a parameterized canonical-recipe nozzle case.'
    )
    ap.add_argument('case', type=Path)
    ap.add_argument(
        '--spec',
        type=Path,
        required=True,
        help='JSON file holding the NozzleCaseSpec.',
    )
    ap.add_argument('--scale', type=float, default=None)
    ap.add_argument('--co', type=float, default=None)
    ap.add_argument('--end', type=float, default=None)
    ap.add_argument('--angle', type=float, default=None)
    ap.add_argument('--perturb', type=float, default=None)

    args = ap.parse_args()

    spec = NozzleCaseSpec.from_dict(
        json.loads(args.spec.read_text(encoding='utf-8-sig'))
    )

    overrides = {}

    if args.scale is not None:
        overrides['scale'] = args.scale
    if args.co is not None:
        overrides['max_courant'] = args.co
    if args.end is not None:
        overrides['end_time_s'] = args.end
    if args.angle is not None:
        overrides['wedge_angle_deg'] = args.angle
    if args.perturb is not None:
        overrides['startup_perturbation'] = args.perturb

    if overrides:
        data = spec.to_dict()
        data.update(overrides)
        spec = NozzleCaseSpec.from_dict(data)

    build(args.case, spec)

    print(
        json.dumps(
            {
                'case': str(args.case),
                'case_id': spec.case_id,
                'cells': sum(spec.axial_cells) * spec.radial_cells,
                'axial_cells': sum(spec.axial_cells),
                'radial_cells': spec.radial_cells,
                'area_ratio': spec.area_ratio,
            },
            indent=2,
        )
    )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
