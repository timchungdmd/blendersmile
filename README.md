# BlenderSmile Pro - Dental Design Addon for Blender

**Addon entrypoint (CANONICAL):** `blendersmile_addon/__init__.py`  
**Main workflow module:** `blendersmile_pnp_full.py`  
**No-Prep guide:** `NO_PREP_COMPLETE_GUIDE.md`  
**Last Updated:** 2026-03-31

---

## Installation & Quick Start

### Method 1: Install as Package (RECOMMENDED)

1. **Zip the addon package:**
   ```bash
   cd /path/to/blendersmile
   zip -r blendersmile_pro.zip blendersmile_addon/
   ```

2. **Install in Blender:**
   - Open Blender 3.6+
   - Go to: `Edit` → `Preferences` → `Add-ons`
   - Click `Install...`
   - Select `blendersmile_pro.zip`
   - **Enable the addon** by checking the checkbox next to "BlenderSmile Pro"

3. **Verify installation:**
   - Open `3D View` → Press `N` key
   - Look for `Smile` tab in sidebar

### Method 2: Development Install

For development, symlink or copy the package:
```bash
# macOS/Linux
ln -s /path/to/blendersmile/blendersmile_addon ~/.config/blender/3.6/scripts/addons/

# Or copy
cp -r blendersmile_addon ~/.config/blender/3.6/scripts/addons/
```

### Method 3: Direct Script Loading

For quick testing without installation:
```python
# In Blender's Python Console:
import sys
sys.path.append('/path/to/blendersmile')
import blendersmile_addon
blendersmile_addon.register()
```

---

## Package Structure

```
blendersmile/
├── blendersmile_addon/          # CANONICAL PACKAGE (install this)
│   └── __init__.py              # Entrypoint with bl_info
├── blendersmile_pnp_full.py     # Main implementation (49K lines)
├── docs/
│   └── project/
│       └── package_authority.md # Architecture documentation
├── README.md                    # This file
└── INSTALL.md                   # Detailed installation guide
```

**Important:** 
- Install `blendersmile_addon/` as the package, NOT the root directory
- The `blendersmile_pnp_full.py` file is the implementation, not the entrypoint
- Other Python files in the root are development/test utilities

---

## Workflow Tabs (Canonical)

The in-panel workflow states are:

1. `1. Setup`
2. `2. Analysis`
3. `3. Mockup`
4. `4. Production`
5. `5. No-Prep`
6. `6. Veneer Lab`

For lab fabrication, the canonical staged flow is **Veneer Lab → CAD Wizard (A-H)**.

---

## No-Prep Camera Alignment Quick Flow

1. `5. No-Prep` → Import mockup photo
2. Import/target scan mesh
3. Add 6-8 landmark pairs
4. Align scan to photo
5. Verify in camera view
6. Continue generation/export in `4. Production` or `6. Veneer Lab`

---

## Reloading After Updates

After modifying code, reload the addon in Blender:

- Press `F3` → Search "Reload Scripts" → Execute
- Or in Python console: `bpy.ops.script.reload()`
- Or restart Blender

---

## Troubleshooting

- **Missing buttons/operators:** `F3` → Reload Scripts
- **Alignment quality poor:** Use more spread landmarks (6-8+)
- **Import errors:** Ensure you installed `blendersmile_addon/` not the root folder
- **Full step-by-step:** See `NO_PREP_COMPLETE_GUIDE.md`

---

## Architecture

This addon uses a **wrapper package architecture**:

1. **Package Layer** (`blendersmile_addon/__init__.py`):
   - Provides canonical `bl_info` for Blender detection
   - Handles path setup and module loading
   - Delegates registration to implementation

2. **Implementation Layer** (`blendersmile_pnp_full.py`):
   - Contains all operators, panels, properties
   - 49K lines of functionality
   - Self-contained monolithic module

This separation allows:
- Clean installation (single package folder)
- Easy updates (replace implementation file)
- Future modularization (split monolith without changing entrypoint)

See `docs/project/package_authority.md` for full architecture details.

---

## Support & Documentation

- **Installation guide:** `INSTALL.md`
- **No-Prep workflow:** `NO_PREP_COMPLETE_GUIDE.md`
- **Architecture:** `docs/project/package_authority.md`
- **Project context:** `CLAUDE.md` (for AI assistants)

---

**Version:** 2026.3.31  
**Blender:** 3.6.0+  
**License:** See LICENSE file
