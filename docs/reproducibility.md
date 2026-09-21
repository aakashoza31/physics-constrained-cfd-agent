# Reproducibility

Requirements:
- OpenFOAM Foundation v14
- Python 3
- NumPy
- Windows with WSL or Linux

Windows / WSL:
    .\validation\canonical_reference\RunReference.ps1

Linux:
    bash validation/canonical_reference/Allrun

Revalidation:
    bash validation/canonical_reference/Allverify /absolute/path/to/campaign

The deterministic CFD layer owns geometry generation, meshing, initialization, solver execution, diagnostics, and scientific acceptance.

Higher-level agent logic may construct supported inputs and interpret evidence, but it does not override deterministic acceptance.
