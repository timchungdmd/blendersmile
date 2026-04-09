"""
BlenderSmile - Modular Package

This package contains all BlenderSmile addon components organized by tab.
Each tab is a self-contained module that can be enabled or disabled.

Structure:
    modular/
    ├── __init__.py          # This file - package marker
    ├── 00_core.py           # Constants and shared utilities (ALWAYS LOAD)
    ├── 01_properties.py     # All property definitions (ALWAYS LOAD)
    ├── 02_setup.py          # SETUP tab
    ├── 03_analysis.py       # ANALYSIS tab
    ├── 04_mockup.py         # MOCKUP tab
    ├── 05_production.py      # PRODUCTION tab
    ├── 06_veneer_import.py   # VENEER_IMPORT tab
    ├── 07_no_prep.py         # NO_PREP tab
    ├── 08_guided.py          # GUIDED tab (CAD Wizard)
    ├── panel.py              # Main panel (orchestrator)
    └── run_blender.py        # Loader script for Blender

Usage:
    1. Open Blender
    2. Go to Text Editor
    3. Open modular/run_blender.py
    4. Press Alt+P (Run Script)
    5. "Smile" tab appears in 3D View sidebar

To disable a tab:
    1. Edit panel.py
    2. Set _ENABLED_TABS["tab_name"] = False
    3. Re-run run_blender.py

To reload after editing:
    - Run reload() in Blender Python console
"""

__version__ = "2026.1.14"
__author__ = "BlenderSmile"
