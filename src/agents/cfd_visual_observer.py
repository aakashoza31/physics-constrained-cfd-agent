"""Multimodal field observer: qualitative observations of rendered CFD fields.

``observe_cfd_images`` sends the standardized PNG renderings to Gemini and
returns a qualitative observation record.  It never decides acceptance.

The model identifier is read at request time from
``llm_provenance.gemini_model_name()`` (``GEMINI_MODEL`` or the shared
default).  When a request is made, the returned record includes ``model`` (the
identifier requested) and, when the SDK reports it, ``model_version``.  Before
this change the module had its own default (``gemini-3.6-flash``), which is
the model the archived step sessions' observer used when ``GEMINI_MODEL`` was
unset; those archived records do not contain a ``model`` field.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.agents.llm_provenance import gemini_model_name


class VisualObservationSchema(
    BaseModel
):

    pressure_observation: str

    mach_observation: str

    velocity_observation: str

    mesh_observation: str

    suspected_regions: list[
        str
    ]

    qualitative_anomalies: list[
        str
    ]

    visual_confidence: str


SYSTEM_PROMPT = """
You are the visual-observation component of a physics-constrained
CFD engineering agent.

You receive standardized CFD images generated from an OpenFOAM
calculation.

Your task is ONLY qualitative visual observation.

You may:
- identify where strong gradients appear,
- identify visually suspicious localized regions,
- state whether the mesh appears relatively coarse or fine near
  visible flow features,
- compare qualitative structure between pressure, Mach/velocity,
  and mesh views.

You MUST NOT:
- declare the CFD converged from images,
- declare the CFD numerically correct from images,
- estimate precise physical values from a color map,
- override deterministic numerical diagnostics,
- invent flow quantities that were not measured.

Numerical diagnostics always outrank visual inference.

Return only the requested structured response.
"""


def observe_cfd_images(
    *,
    image_paths: dict[
        str,
        str,
    ],
    numerical_context: dict[
        str,
        Any,
    ] | None = None,
) -> dict[
    str,
    Any,
]:

    usable: list[
        tuple[
            str,
            Path,
        ]
    ] = []

    for label, raw_path in (
        image_paths.items()
    ):

        path = Path(
            raw_path
        )

        if (
            path.exists()
            and path.suffix.lower()
            == ".png"
        ):

            usable.append(
                (
                    label,
                    path,
                )
            )


    if not usable:

        return {
            "status": (
                "visual_evidence_unavailable"
            ),
            "reason": (
                "No standardized CFD PNG files were available."
            ),
        }


    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:

        return {
            "status": (
                "visual_evidence_unavailable"
            ),
            "reason": (
                "GEMINI_API_KEY is not set."
            ),
        }


    contents: list[
        Any
    ] = [
        (
            "Inspect the attached standardized CFD images. "
            "Use them only for qualitative localization. "
            "The numerical context below is provided so that "
            "you do not infer numerical correctness from colors.\n\n"
            + json.dumps(
                numerical_context
                or {},
                indent=2,
                default=str,
            )
        )
    ]


    for label, path in usable:

        contents.append(
            f"IMAGE LABEL: {label}"
        )

        contents.append(
            types.Part.from_bytes(
                data=(
                    path.read_bytes()
                ),
                mime_type="image/png",
            )
        )


    model_name = gemini_model_name()

    try:

        client = genai.Client(
            api_key=api_key
        )

        response = (
            client.models.generate_content(
                model=model_name,
                contents=contents,
                config=(
                    types.GenerateContentConfig(
                        system_instruction=(
                            SYSTEM_PROMPT
                        ),
                        response_mime_type=(
                            "application/json"
                        ),
                        response_schema=(
                            VisualObservationSchema
                        ),
                        temperature=0,
                    )
                ),
            )
        )


        if not response.text:

            raise RuntimeError(
                "Gemini visual observer returned no text."
            )


        observation = (
            VisualObservationSchema
            .model_validate_json(
                response.text
            )
        )


        result = (
            observation.model_dump()
        )

        result[
            "status"
        ] = "visual_observation_complete"

        result[
            "images_examined"
        ] = [
            str(
                path
            )
            for _, path
            in usable
        ]

        result[
            "model"
        ] = model_name

        model_version = getattr(
            response,
            "model_version",
            None,
        )

        if model_version:
            result[
                "model_version"
            ] = str(
                model_version
            )

        return result


    except Exception as exc:

        # Visual evidence is supporting evidence.
        # Failure of this optional layer must never fabricate
        # a replacement observation or crash the CFD pipeline.

        return {
            "status": (
                "visual_observation_failed"
            ),
            "reason": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            "images_examined": [
                str(
                    path
                )
                for _, path
                in usable
            ],
            "model": model_name,
        }
