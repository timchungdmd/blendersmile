# Package Authority - BlenderSmile Architecture

**Document Status:** CANONICAL  
**Last Updated:** 2026-03-31  
**Applies To:** BlenderSmile Pro v2026.3.31+

---

## Purpose

This document establishes the **authoritative package structure** for BlenderSmile addon installation. It defines:

1. Which entrypoint is canonical
2. How to install the addon
3. What to avoid (stale entrypoints)
4. Architecture rationale

**Key Principle:** There is ONE authoritative entrypoint for BlenderSmile installation.

---

## Canonical Entrypoint

**Package:** `blendersmile_addon/`  
**Entrypoint:** `blendersmile_addon/__init__.py`  
**Implementation:** `blendersmile_pnp_full.py` (sibling to package)

```
Repository Structure:
blendersmile/
├── blendersmile_addon/          # CANONICAL PACKAGE (install this)
│   └── __init__.py              # Contains bl_info, imports implementation
├── blendersmile_pnp_full.py     # Main implementation (49K lines)
├── README.md                    # Updated with canonical instructions
├── INSTALL.md                   # Detailed installation guide
└── docs/project/
    └── package_authority.md     # This document
```

---

## Installation Target

### What to Install

**CORRECT:** Install `blendersmile_addon/` folder as a Blender addon.

```bash
# Create distributable ZIP
cd /path/to/blendersmile
zip -r blendersmile_pro.zip blendersmile_addon/

# Install in Blender
# Edit → Preferences → Add-ons → Install → blendersmile_pro.zip
```

### What NOT to Install

**INCORRECT:** Do NOT install the repository root or other Python files.

| File/Folder | Status | Reason |
|-------------|--------|--------|
| `blendersmile_addon/` | ✅ CANONICAL | Proper bl_info, clean namespace |
| `blendersmile_pnp_full.py` | ❌ NOT AN ADDON | Implementation module, no bl_info |
| `modular/` | ❌ STALE | Development experiment, deprecated |
| Repository root | ❌ WRONG | Contains tests, dev files, conflicts |
| `*.py` in root | ❌ NOT ADDONS | Test scripts, utilities |

---

## Architecture

### Wrapper Pattern

BlenderSmile uses a **wrapper package architecture**:

```
┌─────────────────────────────────────┐
│  blendersmile_addon/__init__.py     │  ← Package Layer
│  ┌─────────────────────────────┐   │
│  │ bl_info                     │   │  Blender metadata
│  │ import blendersmile_pnp_full│   │  Load implementation
│  │ register() → impl.register()│   │  Delegate registration
│  │ unregister()                │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  blendersmile_pnp_full.py           │  ← Implementation Layer
│  ┌─────────────────────────────┐   │
│  │ 120+ Operator classes       │   │
│  │ Panel classes               │   │
│  │ Property definitions        │   │
│  │ Helper functions            │   │
│  │ Constants                   │   │
│  │ register()/unregister()     │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

### Why Wrapper Architecture?

1. **Separation of Concerns:**
   - Package layer handles Blender integration (bl_info, path setup)
   - Implementation layer handles functionality

2. **Easy Updates:**
   - Replace `blendersmile_pnp_full.py` without changing entrypoint
   - Version bumps only require updating bl_info in wrapper

3. **Future Modularization:**
   - Can split monolith into modules without changing entrypoint
   - Wrapper can be updated to import from multiple modules

4. **Namespace Isolation:**
   - Clean `blendersmile_addon` namespace in Blender
   - Implementation details hidden from Blender's addon system

---

## Entrypoint Details

### bl_info (Package Layer)

```python
bl_info = {
    "name": "BlenderSmile Pro",
    "author": "BlenderSmile Team",
    "version": (2026, 3, 31),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Smile",
    "category": "3D View",
    "description": "Dental smile design addon - scan processing, tooth positioning, veneer generation",
}
```

This is the **only** bl_info that should be recognized by Blender. All other bl_info declarations in the repository are historical or development-only.

### Implementation Import

The wrapper imports the implementation dynamically:

```python
import sys
import os

# Add parent directory to path
_current_dir = os.path.dirname(__file__)
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Import implementation
import blendersmile_pnp_full as _impl

# Re-export all public names
_public_names = [name for name in dir(_impl) if not name.startswith('_')]
for _name in _public_names:
    globals()[_name] = getattr(_impl, _name)
```

This allows the implementation to live outside the package (as `blendersmile_pnp_full.py` in the parent directory).

---

## Stale Entrypoints (Deprecated)

### Status: DO NOT USE

These entrypoints exist in the repository but are **NOT for installation**:

| Entrypoint | Status | Notes |
|------------|--------|-------|
| `blendersmile_pnp_full.py` (as addon) | DEPRECATED | Run as script for testing only |
| `modular/__init__.py` | STALE | Development experiment, abandoned |
| `modular/run_blender.py` | STALE | Loader script, not an addon |
| `*.py` test files | TESTING | Not addons, test utilities only |

### Why These Are Stale

1. **blendersmile_pnp_full.py:**
   - Contains bl_info but is the *implementation*, not the entrypoint
   - Installing directly would bypass wrapper benefits
   - Run as script (`__name__ == "__main__"`) for testing only

2. **modular/:**
   - Early attempt at modularization
   - Incomplete, does not have all operators
   - Panel does not match current functionality

3. **Test scripts:**
   - `test_*.py` files are for development only
   - Not part of the addon distribution

---

## Verification

### How to Verify Correct Installation

**In Blender Python Console:**
```python
import blendersmile_addon
print(blendersmile_addon.bl_info['name'])  # "BlenderSmile Pro"
print(blendersmile_addon.bl_info['version'])  # (2026, 3, 31)
```

**In Blender Console (on enable):**
```
[BlenderSmile] Registering addon v(2026, 3, 31)
[BlenderSmile] Entrypoint: blendersmile_addon/__init__.py
[BlenderSmile] Implementation: blendersmile_pnp_full.py
[BlenderSmile][Register] classes ok=XXX fail=0
[BlenderSmile] Registration complete
```

**File system check:**
```
/path/to/blender/addons/
└── blendersmile_addon/
    └── __init__.py
```

---

## Versioning

### Version Bump Process

1. **Update bl_info in wrapper:**
   ```python
   # blendersmile_addon/__init__.py
   bl_info = {
       ...
       "version": (2026, 4, 1),  # ← Update this
       ...
   }
   ```

2. **Update implementation if needed:**
   - No need to update `blendersmile_pnp_full.py` bl_info
   - Wrapper's bl_info is canonical

3. **Update documentation:**
   - README.md: Update version and date
   - This file: Update "Last Updated"
   - INSTALL.md: Update version references

### Version Format

Versions follow semantic versioning: `(YEAR, MAJOR, MINOR)`

- `(2026, 3, 31)` = March 31, 2026 release
- Minor bumps for bug fixes
- Major bumps for new features
- Year bump for annual releases

---

## Distribution

### Creating a Release Package

```bash
#!/bin/bash
# release_package.sh

VERSION="2026.3.31"
PACKAGE_NAME="blendersmile_pro_${VERSION}"

# Clean previous builds
rm -rf dist/
mkdir -p dist/

# Copy canonical package
cp -r blendersmile_addon "dist/${PACKAGE_NAME}"

# Optionally include implementation (for self-contained package)
# cp blendersmile_pnp_full.py "dist/${PACKAGE_NAME}/"

# Create ZIP
cd dist/
zip -r "${PACKAGE_NAME}.zip" "${PACKAGE_NAME}"

echo "Release package created: dist/${PACKAGE_NAME}.zip"
```

### Distribution Contents

**Standard distribution:**
```
blendersmile_pro_2026.3.31.zip
└── blendersmile_addon/
    └── __init__.py
```

User must have `blendersmile_pnp_full.py` sibling to `blendersmile_addon/`.

**Self-contained distribution (optional):**
```
blendersmile_pro_2026.3.31.zip
└── blendersmile_addon/
    ├── __init__.py
    └── blendersmile_pnp_full.py  ← Included for portability
```

Modify `__init__.py` to import from local file:
```python
# Change this line in self-contained version:
import blendersmile_pnp_full as _impl
# To:
from . import blendersmile_pnp_full as _impl
```

---

## Future Evolution

### Modularization Path

The wrapper architecture enables future modularization without breaking installs:

**Phase 1 (Current):** Wrapper + Monolith
```
blendersmile_addon/
└── __init__.py → blendersmile_pnp_full.py
```

**Phase 2 (Future):** Wrapper + Modules
```
blendersmile_addon/
├── __init__.py
├── operators/
│   ├── scan.py
│   ├── teeth.py
│   └── veneer.py
├── properties.py
└── panels.py
```

The entrypoint (`blendersmile_addon/__init__.py`) remains the same, ensuring existing installations continue to work.

### Migration Plan

When modularizing:

1. Keep `blendersmile_addon/__init__.py` as entrypoint
2. Split `blendersmile_pnp_full.py` into modules
3. Update `__init__.py` to import from modules instead
4. No change to installation process
5. No change to user workflow

---

## Summary

| Aspect | Canonical |
|--------|-----------|
| **Package** | `blendersmile_addon/` |
| **Entrypoint** | `blendersmile_addon/__init__.py` |
| **bl_info** | In wrapper only |
| **Implementation** | `blendersmile_pnp_full.py` |
| **Install Method** | ZIP `blendersmile_addon/` |
| **Stale Entrypoints** | Do NOT use |

**One authoritative entrypoint. One canonical package. Clear separation.**

---

## References

- `README.md` - User-facing documentation
- `INSTALL.md` - Installation instructions
- `CLAUDE.md` - Project context for AI assistants
- `blendersmile_pnp_full.py` - Implementation source

---

*This document is part of Phase 0 of the BlenderSmile architecture-first backlog.*
