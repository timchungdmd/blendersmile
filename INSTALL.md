# BlenderSmile Installation Guide

## Quick Start (3 Methods)

### Method 1: Package Install (CANONICAL) ✅ RECOMMENDED

This is the **authoritative installation method** for BlenderSmile Pro.

**Step 1: Create the package ZIP**
```bash
cd /path/to/blendersmile
zip -r blendersmile_pro.zip blendersmile_addon/
```

The ZIP should have this structure:
```
blendersmile_pro.zip
└── blendersmile_addon/
    └── __init__.py  (contains bl_info)
```

**Step 2: Install in Blender**
1. Open Blender 3.6+
2. Go to: `Edit` → `Preferences` → `Add-ons`
3. Click `Install...`
4. Select `blendersmile_pro.zip`
5. **Enable the addon** by checking "BlenderSmile Pro"

**Step 3: Verify**
1. Open 3D View
2. Press `N` key (sidebar)
3. Look for `Smile` tab
4. Panel should display workflow tabs: Setup, Analysis, Mockup, Production, No-Prep, Veneer Lab

---

### Method 2: Manual Copy (Advanced)

For developers or persistent installation:

1. **Find Blender's addon directory:**
   - **Windows:** `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`
   - **macOS:** `~/Library/Application Support/Blender/<version>/scripts/addons/`
   - **Linux:** `~/.config/blender/<version>/scripts/addons/`

2. **Copy the package:**
   ```bash
   # Copy ONLY the blendersmile_addon folder
   cp -r blendersmile_addon /path/to/blender/addons/
   ```

3. **Restart Blender**

4. **Enable addon:**
   - `Edit` → `Preferences` → `Add-ons`
   - Search for "BlenderSmile Pro"
   - Enable checkbox

---

### Method 3: Development/Symlink (For Testing)

**macOS/Linux:**
```bash
# Create symlink to addon directory
ln -s /path/to/blendersmile/blendersmile_addon \
      ~/.config/blender/3.6/scripts/addons/blendersmile_addon
```

**Windows (Administrator PowerShell):**
```powershell
New-Item -ItemType SymbolicLink `
  -Path "$env:APPDATA\Blender Foundation\Blender\3.6\scripts\addons\blendersmile_addon" `
  -Target "C:\path\to\blendersmile\blendersmile_addon"
```

**Reload after code changes:**
- Press `F3` → Search "Reload Scripts"
- Or: `bpy.ops.script.reload()`

---

## Important: Package vs. Root Directory

**DO NOT install the entire repository root.**

| What to Install | Why |
|----------------|-----|
| ✅ `blendersmile_addon/` | Canonical package with proper `bl_info` |
| ❌ Repository root | Contains dev files, tests, multiple entrypoints |

**Correct:**
```
addons/
└── blendersmile_addon/    ← Install this
    └── __init__.py
```

**Incorrect:**
```
addons/
└── blendersmile/          ← Do NOT install root
    ├── blendersmile_addon/
    ├── tests/
    ├── docs/
    └── ... (conflicting files)
```

---

## Verification Checklist

After installation, verify:

### ✅ Check 1: Addon Appears in Preferences
1. `Edit` → `Preferences` → `Add-ons`
2. Search: "BlenderSmile"
3. Should see: **"BlenderSmile Pro"**
4. Version should show: `(2026, 3, 31)`

### ✅ Check 2: Console Output (on enable)
When you enable the addon, check Blender's console:

**Expected output:**
```
[BlenderSmile] Registering addon v(2026, 3, 31)
[BlenderSmile] Entrypoint: blendersmile_addon/__init__.py
[BlenderSmile] Implementation: blendersmile_pnp_full.py
[BlenderSmile][Register] quarantined_legacy_ops=X
[BlenderSmile][Register] classes ok=Y fail=0
[BlenderSmile] Registration complete
```

### ✅ Check 3: Sidebar Tab Exists
1. Open `3D View`
2. Press `N` key (sidebar)
3. Look for `Smile` tab
4. Should see panels with 6 workflow tabs

### ✅ Check 4: Python Import Test
In Blender's Python console:
```python
import blendersmile_addon
print(blendersmile_addon.bl_info)
# Should print: {'name': 'BlenderSmile Pro', 'version': (2026, 3, 31), ...}
```

---

## Troubleshooting

### Issue 1: "No module named 'blendersmile_pnp_full'"

**Cause:** Package installed incorrectly or path issue.

**Solution:**
1. Ensure you installed `blendersmile_addon/` folder, not the repository root
2. Check that `blendersmile_pnp_full.py` is in the parent directory:
   ```
   blendersmile_addon/
   └── __init__.py           ← installed here
   blendersmile_pnp_full.py  ← should be in parent of installed location
   ```
3. The `__init__.py` expects this structure:
   ```
   addons/
   └── blendersmile_addon/
       └── __init__.py
   blendersmile_pnp_full.py  ← sibling to blendersmile_addon/
   ```

**Alternative:** If you want a self-contained package, copy `blendersmile_pnp_full.py` into `blendersmile_addon/` before zipping.

---

### Issue 2: "Register failed to register X classes"

**Cause:** Blender version mismatch or Python error in operators.

**Solution:**
1. Ensure Blender 3.6.0 or higher
2. Check console for detailed error messages
3. Try a clean Blender config:
   - Rename/delete `~/Library/Application Support/Blender/3.6/` (macOS)
   - Restart Blender
   - Reinstall addon

---

### Issue 3: Multiple addon entries in preferences

**Cause:** Installed multiple times (different locations).

**Solution:**
1. Check for duplicates:
   - `~/.config/blender/3.6/scripts/addons/blendersmile_addon/`
   - `~/.config/blender/3.6/scripts/addons/addons/blendersmile_addon/`
2. Remove all but one installation
3. Restart Blender

---

### Issue 4: "bl_info not found" when installing

**Cause:** ZIP structure incorrect.

**Solution:**
Ensure ZIP structure is:
```
blendersmile_pro.zip
└── blendersmile_addon/
    └── __init__.py  ← bl_info at top of file
```

**NOT:**
```
blendersmile_pro.zip
└── __init__.py  ← WRONG: should be inside blendersmile_addon/
```

**Create ZIP correctly:**
```bash
cd /path/to/blendersmile
zip -r blendersmile_pro.zip blendersmile_addon/
```

---

### Issue 5: Operators missing after reload

**Cause:** Hot reload doesn't fully clear old registrations.

**Solution:**
1. Restart Blender (most reliable)
2. Or disable addon → enable addon in Preferences
3. Or run in Python console:
   ```python
   import bpy
   # Disable
   bpy.ops.preferences.addon_disable(module='blendersmile_addon')
   # Re-enable
   bpy.ops.preferences.addon_enable(module='blendersmile_addon')
   ```

---

## Package Architecture

```
blendersmile_addon/
└── __init__.py
    ├── bl_info                    # Blender addon metadata
    ├── import blendersmile_pnp_full  # Load implementation
    ├── register()                 # Delegate to implementation
    └── unregister()               # Delegate to implementation

blendersmile_pnp_full.py           # Main implementation (49K lines)
├── Operators (120+ classes)
├── Panels (SMILE_PT_panel)
├── Properties (SmileAddonStateV2)
├── Constants (COL_*, KEY_*)
├── Helper functions
└── register()/unregister()
```

This **wrapper architecture** provides:
- Clean separation of entrypoint and implementation
- Easy updates (replace `blendersmile_pnp_full.py`)
- Forward compatibility for future modularization
- Single authoritative `bl_info`

---

## Platform-Specific Notes

### Windows
- ✅ Full support (Blender 3.6+)
- May need Visual C++ Redistributable for OpenCV
- Use `blender_debug.exe` for console output

### macOS
- ✅ Full support (Blender 3.6+)
- Apple Silicon (M1/M2/M3): Native support
- Terminal: Run `Blender.app/Contents/MacOS/Blender` for console output

### Linux
- ✅ Full support (Blender 3.6+)
- Some distros need: `sudo apt install python3-dev`
- Run from terminal for console output

---

## Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| Blender | 3.6.0 or higher |
| Python | 3.10+ (included with Blender) |
| RAM | 4 GB minimum, 8 GB recommended |
| Disk Space | 100 MB (addon + dependencies) |

---

## Dependencies

BlenderSmile auto-installs required dependencies on first use:

- **Open3D** - ICP alignment, point cloud processing
- **OpenCV** - PnP solver, camera calibration
- **NumPy** - Required by OpenCV

These are installed to Blender's Python site-packages when first operator requiring them is invoked.

---

## Uninstallation

### Method 1: Blender Preferences
1. `Edit` → `Preferences` → `Add-ons`
2. Search "BlenderSmile Pro"
3. Expand addon entry
4. Click `Remove`

### Method 2: Manual
1. Close Blender
2. Delete addon folder from scripts/addons/
3. Restart Blender

---

## Upgrading

When upgrading to a new version:

1. **Remove old version:**
   - Disable and remove in Preferences
   - Or delete `blendersmile_addon/` from addons directory

2. **Clear Python cache:**
   ```bash
   find /path/to/blendersmile_addon -name "__pycache__" -type d -exec rm -rf {} +
   ```

3. **Install new version:**
   - Zip and install as in Method 1 above

4. **Restart Blender**

---

## Next Steps

After successful installation:

1. **Try the workflow:**
   - Import a dental scan (STL/OBJ)
   - Use `1. Setup` to load library teeth
   - Use `2. Analysis` for landmarks
   - Use `3. Mockup` for tooth positioning

2. **Read documentation:**
   - `README.md` - Quick start
   - `NO_PREP_COMPLETE_GUIDE.md` - Photo alignment workflow
   - `docs/project/package_authority.md` - Architecture details

3. **Report issues:**
   - Check Blender console for error messages
   - Include version info: `(2026, 3, 31)`
   - Note Blender version and OS

---

**Installation successful?** Open Blender, press `N`, click `Smile` tab! 🎉

**Having issues?** Check console output and see Troubleshooting above.
