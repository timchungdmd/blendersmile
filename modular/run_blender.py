"""
BlenderSmile Loader Script

Run this script in Blender's Text Editor to load all modular addon components.

Usage:
1. Open Blender
2. Go to Text Editor
3. Open this file (Text > Open Text Block)
4. Press Run Script (Alt+P)
5. The addon will be registered and the "Smile" tab will appear in 3D View sidebar

To disable a tab:
1. Edit this file or panel.py
2. Set _ENABLED_TABS["tab_name"] = False
3. Re-run this script

To reload after editing modules:
1. Run unload() first
2. Then run load()
"""

import bpy
import sys
import os

# === CONFIGURATION ===
# Set to True to see detailed loading output
VERBOSE_LOADING = True


def log(msg):
    """Print message if verbose mode is enabled."""
    if VERBOSE_LOADING:
        print(f"[BlenderSmile] {msg}")


def get_addon_directory():
    """Get the directory containing this script."""
    # This file should be in the modular/ folder
    this_file = os.path.abspath(__file__)
    return os.path.dirname(this_file)


def load():
    """
    Load/reload the BlenderSmile addon modules.
    Call this after making changes to reload.
    """
    log("Starting BlenderSmile loader...")

    addon_dir = get_addon_directory()
    log(f"Addon directory: {addon_dir}")

    # Add addon directory to Python path if not already there
    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)
        log(f"Added to sys.path: {addon_dir}")

    # Import the panel module (this triggers all other imports)
    try:
        import panel

        log("Imported panel module")
    except Exception as e:
        print(f"[BlenderSmile] ERROR importing panel: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Register
    try:
        panel.register()
        log("Registration complete!")
        return True
    except Exception as e:
        print(f"[BlenderSmile] ERROR during registration: {e}")
        import traceback

        traceback.print_exc()
        return False


def unload():
    """
    Unregister the BlenderSmile addon.
    Call this before reloading to clean up.
    """
    log("Starting BlenderSmile unload...")

    try:
        import panel

        panel.unregister()
        log("Unregistration complete!")
        return True
    except Exception as e:
        print(f"[BlenderSmile] ERROR during unregistration: {e}")
        import traceback

        traceback.print_exc()
        return False


def reload():
    """Unload then load - convenient for reloading after edits."""
    unload()
    load()


def show_info():
    """Display information about the loaded addon."""
    import panel

    print("\n" + "=" * 50)
    print("BlenderSmile Pro - Modular Addon")
    print("=" * 50)
    print(f"Addon directory: {get_addon_directory()}")
    print(f"Enabled tabs: {panel.get_enabled_tabs()}")
    print()
    print("To reload after editing modules:")
    print("  1. Run reload()")
    print()
    print("To disable a tab:")
    print("  1. Edit modular/panel.py")
    print("  2. Set _ENABLED_TABS['tab_name'] = False")
    print("  3. Run reload()")
    print("=" * 50 + "\n")


# === AUTO-EXECUTE ===
# When run as a script, automatically load
if __name__ == "__main__":
    success = load()
    if success:
        show_info()
    else:
        print("\n[BlenderSmile] Failed to load. Check console for errors.\n")
