#!/usr/bin/env python3
"""Deterministic parsers for the RAW authoritative TMR .dat assets.

The registered external assets are the raw downloaded files, byte for byte. This
module parses them; it never asks a human to pre-convert authoritative data, and
it never invents a value.

DERIVED ARTIFACTS
  Anything this module normalises is a DERIVED artifact, not an external
  scientific asset. Every parse result carries a ``Derivation`` recording the
  source asset key, the source SHA256, the parser version, and exactly what
  transformation was applied -- so an acceptance decision is traceable back to
  the raw bytes.

NATIVE FORMAT
  The TMR .dat files are whitespace-delimited numeric columns with free-form
  title / "variables=" / "zone" lines interleaved. The parsers therefore:
    * ignore any line that is not a row of numbers;
    * use zone/title text, when present, to label datasets and surfaces;
    * REFUSE, with the offending line quoted, when the column count or the
      labelling is ambiguous.
  Refusal is the correct outcome for an unexpected layout: a mis-parsed
  reference is a silently wrong acceptance gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.pipeline.airfoil import assets as asset_mod

PARSER_VERSION = "airfoil-tmr-dat-parser/1.0.0"

UPPER = "upper"
LOWER = "lower"
BOTH = "both"

#: A line of pure numbers. Anything else is metadata.
_NUMERIC = re.compile(r"^[\s+\-0-9.eEdD]+$")
_ZONE = re.compile(r"""zone\s*(?:t\s*=\s*)?["']?([^"'\n,]+)""", re.I)
_VARIABLES = re.compile(r"variables\s*=", re.I)


class ReferenceError(RuntimeError):
    """A registered reference dataset is missing, unusable or ambiguous."""


@dataclass(frozen=True)
class Derivation:
    """Provenance of a derived artifact. Never an external asset itself."""

    source_asset_key: str
    source_filename: str
    source_sha256: str
    parser_version: str
    transformations: Tuple[str, ...] = ()
    derived_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_class": "derived",
            "source_asset_key": self.source_asset_key,
            "source_filename": self.source_filename,
            "source_sha256": self.source_sha256,
            "parser_version": self.parser_version,
            "transformations": list(self.transformations),
            "derived_sha256": self.derived_sha256,
            "note": (
                "a derived representation of a registered raw asset; the "
                "acceptance validator remains traceable to the raw SHA256 above"
            ),
        }


def _tokenise(path: Path) -> List[Tuple[str, Any]]:
    """Split a .dat file into ('zone', label) and ('row', [floats]) entries."""
    entries: List[Tuple[str, Any]] = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        zone = _ZONE.search(line)
        if zone:
            entries.append(("zone", zone.group(1).strip()))
            continue
        if _VARIABLES.search(line):
            continue
        if line.startswith(("#", "!", "%", "*")):
            entries.append(("zone", line.lstrip("#!%* ").strip()))
            continue
        if not _NUMERIC.match(line):
            entries.append(("zone", line))
            continue
        try:
            values = [float(v.replace("D", "E").replace("d", "e"))
                      for v in line.split()]
        except ValueError:
            entries.append(("zone", line))
            continue
        if values:
            entries.append(("row", values))
    return entries


def _resolve(key: str, repo_root: Optional[Path]) -> Tuple[Path, Derivation]:
    try:
        path = asset_mod.require(key, repo_root)
    except asset_mod.AssetError as exc:
        raise ReferenceError(str(exc)) from exc
    asset = asset_mod.REGISTER[key]
    return path, Derivation(
        source_asset_key=key,
        source_filename=asset.filename,
        source_sha256=asset_mod.sha256_of(path),
        parser_version=PARSER_VERSION,
    )


def _with(derivation: Derivation, *transformations: str) -> Derivation:
    return Derivation(
        source_asset_key=derivation.source_asset_key,
        source_filename=derivation.source_filename,
        source_sha256=derivation.source_sha256,
        parser_version=derivation.parser_version,
        transformations=tuple(transformations),
    )


# ----------------------------------------------------------------------
# Force data: alpha, CL, CD (+ optional further columns, which are ignored)
# ----------------------------------------------------------------------
@dataclass
class ForceTable:
    datasets: Dict[str, List[Tuple[float, float, float]]]
    derivation: Derivation
    columns_used: Tuple[int, int, int] = (0, 1, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "datasets": {k: len(v) for k, v in self.datasets.items()},
            "columns_used_alpha_CL_CD": list(self.columns_used),
            "derivation": self.derivation.to_dict(),
        }


def parse_force_dat(key: str, repo_root: Optional[Path] = None) -> ForceTable:
    """Parse a TMR force .dat into per-dataset (alpha, CL, CD) rows."""
    path, derivation = _resolve(key, repo_root)
    entries = _tokenise(path)

    datasets: Dict[str, List[Tuple[float, float, float]]] = {}
    label = Path(asset_mod.REGISTER[key].filename).stem
    widths: set = set()
    for kind, payload in entries:
        if kind == "zone":
            label = str(payload)
            continue
        widths.add(len(payload))
        if len(payload) < 3:
            raise ReferenceError(
                f"{path.name}: a data row has {len(payload)} column(s); alpha, CL "
                f"and CD are required. Offending row: {payload}. Refusing to guess "
                "which column is which."
            )
        datasets.setdefault(label, []).append(
            (float(payload[0]), float(payload[1]), float(payload[2]))
        )
    if not datasets:
        raise ReferenceError(f"{path.name}: no numeric data rows found")
    for rows in datasets.values():
        rows.sort()

    transformations = [
        "parsed whitespace-delimited numeric rows; metadata lines ignored",
        f"columns 1-3 read as alpha_deg, CL, CD (row widths seen: {sorted(widths)})",
        f"grouped into {len(datasets)} dataset(s) by zone/title line",
        "rows sorted by alpha",
    ]
    return ForceTable(datasets, _with(derivation, *transformations))


@dataclass(frozen=True)
class DragReference:
    """One tripped dataset's zero-incidence drag, linearly interpolated."""

    dataset: str
    cd: float
    bracket_alpha: Tuple[float, float]
    bracket_cd: Tuple[float, float]
    derivation: Derivation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "CD_at_zero_incidence": self.cd,
            "interpolated_between_alpha": list(self.bracket_alpha),
            "interpolated_between_CD": list(self.bracket_cd),
            "method": "linear interpolation in alpha; experimental offset preserved",
            "derivation": self.derivation.to_dict(),
        }


def ladson_zero_incidence_drag(
    repo_root: Optional[Path] = None, *, target_alpha: float = 0.0
) -> List[DragReference]:
    """Per-dataset zero-incidence CD from the RAW Ladson .dat. Never extrapolates."""
    table = parse_force_dat(asset_mod.REF_LADSON_FORCES, repo_root)
    out: List[DragReference] = []
    for dataset, rows in sorted(table.datasets.items()):
        alphas = [r[0] for r in rows]
        if not (min(alphas) <= target_alpha <= max(alphas)):
            raise ReferenceError(
                f"dataset {dataset!r} does not bracket alpha = {target_alpha}: "
                f"range {min(alphas)} .. {max(alphas)}. Refusing to extrapolate."
            )
        lo = max((r for r in rows if r[0] <= target_alpha), key=lambda r: r[0])
        hi = min((r for r in rows if r[0] >= target_alpha), key=lambda r: r[0])
        if hi[0] == lo[0]:
            cd = lo[2]
        else:
            frac = (target_alpha - lo[0]) / (hi[0] - lo[0])
            cd = lo[2] + frac * (hi[2] - lo[2])
        out.append(
            DragReference(
                dataset, cd, (lo[0], hi[0]), (lo[2], hi[2]),
                _with(
                    table.derivation,
                    *table.derivation.transformations,
                    f"linear interpolation to alpha = {target_alpha} between "
                    f"{lo[0]} and {hi[0]}",
                ),
            )
        )
    if not out:
        raise ReferenceError("no tripped Ladson datasets found")
    return out


def cfl3d_forces(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Registered NASA CFL3D SST forces. Supporting CFD reference."""
    table = parse_force_dat(asset_mod.REF_CFL3D_FORCES, repo_root)
    rows = [
        {"alpha_deg": a, "CL": cl, "CD": cd}
        for dataset in sorted(table.datasets)
        for a, cl, cd in table.datasets[dataset]
    ]
    return {"rows": rows, "derivation": table.derivation.to_dict()}


# ----------------------------------------------------------------------
# Surface distributions: x/c and one value, optionally per zone
# ----------------------------------------------------------------------
@dataclass
class SurfaceCurves:
    curves: Dict[str, List[Tuple[float, float]]]
    derivation: Derivation
    surface_labels_present: bool = False

    def for_surfaces(self) -> Dict[str, List[Tuple[float, float]]]:
        """Upper/lower curves, applying an unlabelled single curve to both.

        Applying one curve to both surfaces is a RECORDED transformation, not a
        silent assumption: the derivation carries it, and the validator still
        computes each surface's RMSE independently.
        """
        if self.surface_labels_present:
            return {k: v for k, v in self.curves.items() if k in (UPPER, LOWER)}
        single = next(iter(self.curves.values()))
        return {UPPER: list(single), LOWER: list(single)}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "curves": {k: len(v) for k, v in self.curves.items()},
            "surface_labels_present": self.surface_labels_present,
            "derivation": self.derivation.to_dict(),
        }


def _classify(label: str) -> Optional[str]:
    low = label.lower()
    if "upper" in low or low.endswith(("_u", " u")) or "suction" in low:
        return UPPER
    if "lower" in low or low.endswith(("_l", " l")) or "pressure side" in low:
        return LOWER
    return None


def parse_surface_dat(
    key: str, repo_root: Optional[Path] = None, *, value_name: str = "value"
) -> SurfaceCurves:
    """Parse a TMR surface-distribution .dat into x/c -> value curves."""
    path, derivation = _resolve(key, repo_root)
    entries = _tokenise(path)

    curves: Dict[str, List[Tuple[float, float]]] = {}
    label = BOTH
    labelled = False
    widths: set = set()
    # Count zone blocks that carry data but no recognisable surface label. More
    # than one means the file is split into blocks we cannot attribute, and
    # merging them into a single curve would be a silent, wrong normalisation.
    unlabelled_blocks = 0
    seen_rows_in_block = False
    for kind, payload in entries:
        if kind == "zone":
            classified = _classify(str(payload))
            if classified is not None:
                label, labelled = classified, True
            elif seen_rows_in_block:
                unlabelled_blocks += 1
            seen_rows_in_block = False
            continue
        seen_rows_in_block = True
        widths.add(len(payload))
        if len(payload) < 2:
            raise ReferenceError(
                f"{path.name}: a data row has {len(payload)} column(s); x/c and "
                f"{value_name} are required. Offending row: {payload}."
            )
        curves.setdefault(label, []).append((float(payload[0]), float(payload[1])))
    if not curves:
        raise ReferenceError(f"{path.name}: no numeric data rows found")
    if labelled and set(curves) - {UPPER, LOWER}:
        raise ReferenceError(
            f"{path.name}: zone labels produced surfaces {sorted(curves)}; expected "
            "only 'upper' and 'lower'. Refusing an ambiguous surface split."
        )
    if not labelled and (len(curves) != 1 or unlabelled_blocks > 0):
        raise ReferenceError(
            f"{path.name}: {unlabelled_blocks + len(curves)} unlabelled data "
            "block(s) found. Surfaces are compared independently, so an unlabelled "
            "multi-block file cannot be split without guessing, and merging the "
            "blocks into one curve would be a silent normalisation. Refusing."
        )
    for points in curves.values():
        points.sort()

    transformations = [
        "parsed whitespace-delimited numeric rows; metadata lines ignored",
        f"columns 1-2 read as x_over_c, {value_name} (widths seen: {sorted(widths)})",
        "rows sorted by x/c",
    ]
    if labelled:
        transformations.append("surfaces taken from zone/title labels")
    else:
        transformations.append(
            "no surface labels in the file: the single curve is applied to BOTH "
            "surfaces, and each surface is still evaluated independently"
        )
    return SurfaceCurves(curves, _with(derivation, *transformations), labelled)


def cfl3d_cp(repo_root: Optional[Path] = None) -> SurfaceCurves:
    """Registered NASA CFL3D SST Cp at zero incidence. The Cp comparison target."""
    return parse_surface_dat(asset_mod.REF_CFL3D_CP, repo_root, value_name="Cp")


def cfl3d_cf(repo_root: Optional[Path] = None) -> SurfaceCurves:
    """Registered NASA CFL3D SST Cf. SUPPORTING evidence only, never a gate."""
    return parse_surface_dat(asset_mod.REF_CFL3D_CF, repo_root, value_name="Cf")


def availability(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Which registered references are usable. Used by the scope gate."""
    out: Dict[str, Any] = {}
    for key in asset_mod.REFERENCE_KEYS:
        status = asset_mod.check_asset(key, repo_root)
        out[key] = {
            "filename": asset_mod.REGISTER[key].filename,
            "ok": status["ok"],
            "reason": status["reason"],
        }
    return out
