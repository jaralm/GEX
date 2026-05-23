"""
Compatibility entrypoint for manual MEFF recalculations.

The daily pipeline now lives in meff_opciones.py and generates every dashboard
artifact, including both GEX and DEX. Keeping this file as a thin wrapper avoids
maintaining a second implementation that can drift from the main pipeline.
"""

from meff_opciones import main


if __name__ == "__main__":
    main()
