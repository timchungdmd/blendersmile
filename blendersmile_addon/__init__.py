"""
BlenderSmile Pro - Dental Design Addon for Blender 3.6+

This is the CANONICAL ENTRYPOINT for BlenderSmile addon installation.

Installation:
    1. Zip this blendersmile_addon/ folder
    2. In Blender: Edit -> Preferences -> Add-ons -> Install
    3. Select the zip file
    4. Enable "BlenderSmile Pro"

Architecture:
    This package wraps blendersmile_pnp_full.py (the monolithic implementation).
    All operators, panels, and properties are defined in that module.
    This wrapper provides:
    - Canonical bl_info for Blender addon detection
    - Clean namespace isolation
    - Forward compatibility for future modularization

See also:
    - blendersmile_pnp_full.py (main implementation, 49K lines)
    - docs/project/package_authority.md (architecture documentation)
"""

bl_info = {
    "name": "BlenderSmile Pro",
    "author": "BlenderSmile Team",
    "version": (2026, 3, 31),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Smile",
    "category": "3D View",
    "description": "Dental smile design addon - scan processing, tooth positioning, veneer generation",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
}

import sys
import os

# Add parent directory to path to allow importing blendersmile_pnp_full
_current_dir = os.path.dirname(__file__)
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Import all from the monolithic implementation
# This brings in all operators, panels, properties, and register/unregister functions
try:
    # Import the module first
    import blendersmile_pnp_full as _impl

    # Re-export all public names
    _public_names = [name for name in dir(_impl) if not name.startswith("_")]
    _globals = globals()
    for _name in _public_names:
        _globals[_name] = getattr(_impl, _name)

    # Store reference to implementation module
    _implementation = _impl

except ImportError as e:
    print(f"[BlenderSmile] ERROR: Failed to import implementation module: {e}")
    print(f"[BlenderSmile] Expected to find blendersmile_pnp_full.py in: {_parent_dir}")
    raise


def register():
    """Register all addon classes with Blender.

    This delegates to the implementation module's register function,
    which handles class registration, property setup, and handlers.
    """
    print(f"[BlenderSmile] Registering addon v{bl_info['version']}")
    print(f"[BlenderSmile] Entrypoint: blendersmile_addon/__init__.py")
    print(f"[BlenderSmile] Implementation: blendersmile_pnp_full.py")

    if hasattr(_implementation, "register"):
        _implementation.register()
        print("[BlenderSmile] Registration complete")
    else:
        raise RuntimeError("Implementation module has no register() function")


def unregister():
    """Unregister all addon classes from Blender.

    This delegates to the implementation module's unregister function.
    """
    print("[BlenderSmile] Unregistering addon")

    if hasattr(_implementation, "unregister"):
        _implementation.unregister()
        print("[BlenderSmile] Unregistration complete")
    else:
        print(
            "[BlenderSmile] WARNING: Implementation module has no unregister() function"
        )


# Allow running as standalone script for testing
if __name__ == "__main__":
    register()
