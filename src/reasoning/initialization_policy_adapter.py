from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class InitializationMode(
    str,
    Enum,
):
    CLEAN_START = "CLEAN_START"
    CONTINUE_SAME_MESH = "CONTINUE_SAME_MESH"
    MAP_FIELDS = "MAP_FIELDS"


@dataclass(
    frozen=True
)
class InitializationDecision:

    mode: InitializationMode

    reason: str

    mapping_allowed: bool

    requires_post_map_diagnostics: bool

    source_trusted: bool | None

    def to_dict(
        self,
    ) -> dict[
        str,
        Any,
    ]:

        result = asdict(
            self
        )

        result[
            "mode"
        ] = self.mode.value

        return result


def select_initialization_mode(
    *,
    first_run: bool,
    geometry_changed: bool,
    mesh_changed: bool,
    source_trusted: bool | None = None,
    allow_mapping: bool = False,
) -> InitializationDecision:
    """
    Conservative production initialization gate.

    Policy
    ------
    1. First simulation:
       always clean start.

    2. Geometry changed:
       always clean start.

    3. Same geometry + same mesh:
       continue the existing solution.

    4. Same geometry + new mesh:
       clean start by default.

    5. mapFields is permitted only when:
       - mapping has been explicitly enabled, AND
       - source_trusted is explicitly True.

    Unknown source trust is treated as untrusted.

    This deliberately favors robustness over runtime savings.
    """

    if first_run:

        return InitializationDecision(
            mode=(
                InitializationMode
                .CLEAN_START
            ),
            reason=(
                "First CFD run has no trusted "
                "parent solution."
            ),
            mapping_allowed=False,
            requires_post_map_diagnostics=False,
            source_trusted=None,
        )


    if geometry_changed:

        return InitializationDecision(
            mode=(
                InitializationMode
                .CLEAN_START
            ),
            reason=(
                "Geometry changed. A solution from "
                "another geometry is not mapped."
            ),
            mapping_allowed=False,
            requires_post_map_diagnostics=False,
            source_trusted=(
                source_trusted
            ),
        )


    if not mesh_changed:

        return InitializationDecision(
            mode=(
                InitializationMode
                .CONTINUE_SAME_MESH
            ),
            reason=(
                "Geometry and mesh are unchanged. "
                "Continue the existing CFD state."
            ),
            mapping_allowed=False,
            requires_post_map_diagnostics=False,
            source_trusted=(
                source_trusted
            ),
        )


    # ------------------------------------------------------------
    # A remesh has occurred.
    #
    # Production/demo default:
    # DO NOT map.
    # ------------------------------------------------------------

    if not allow_mapping:

        return InitializationDecision(
            mode=(
                InitializationMode
                .CLEAN_START
            ),
            reason=(
                "Mesh changed and field mapping is "
                "disabled in the production-safe mode."
            ),
            mapping_allowed=False,
            requires_post_map_diagnostics=False,
            source_trusted=(
                source_trusted
            ),
        )


    # ------------------------------------------------------------
    # Unknown is deliberately NOT treated as trusted.
    # ------------------------------------------------------------

    if source_trusted is not True:

        return InitializationDecision(
            mode=(
                InitializationMode
                .CLEAN_START
            ),
            reason=(
                "Mesh changed, but the parent CFD state "
                "is not explicitly trusted."
            ),
            mapping_allowed=False,
            requires_post_map_diagnostics=False,
            source_trusted=(
                source_trusted
            ),
        )


    # ------------------------------------------------------------
    # Mapping is opt-in and requires an explicitly trusted source.
    # ------------------------------------------------------------

    return InitializationDecision(
        mode=(
            InitializationMode
            .MAP_FIELDS
        ),
        reason=(
            "Same geometry was remeshed and the "
            "parent CFD state is explicitly trusted."
        ),
        mapping_allowed=True,
        requires_post_map_diagnostics=True,
        source_trusted=True,
    )
