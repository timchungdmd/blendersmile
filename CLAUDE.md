# BlenderSmile - Project Context for Claude

**Last Updated:** 2026-04-09
**Architecture:** Thin script + modular folder
**Entry Script:** `blendersmile_pnp_full.py` (~80 lines — imports from `modular/`)
**Code Location:** `modular/` folder — ALL code edits happen here
**Type:** Blender 3.6+ addon for dental/smile design

---

## Workflow Pipeline — Departmental Orchestrator (Zero-Trust Architecture)

The workflow is not a linear "Request → Response" chain. It is a **Recursive Loop** focused on verification and precision.

### Stage 1: The Intake & Strategic Planning

**Input:** User Request (e.g., "Add margin smoothing to production_05.py")

1. **Cognitive Analysis:** The agent analyzes the request against this CLAUDE.md context.
2. **Departmental Routing:** The Strategist Department takes the lead.
3. **The "Edge Case" Hook:** Before the plan is finalized, the Strategist runs a pre-execution hook: *"Imagine this fails. Where is the breaking point?"* (e.g., does the operator handle empty meshes? degenerate geometry?)
4. **Todo Generation:** A verified roadmap is created in the todo list.

### Stage 2: The Execution Cycle (The Middleware Loop)

Every tool call follows this exact logic:

**A. Interception (The Pre-Hook)**
- **Routing:** The system identifies the department (e.g., Operator for file edits in `modular/`).
- **Audit:** The Pre-Execution Hook checks for risks (breaking existing operators, missing registrations in `panel.py`).
- **The "Rethink" Trigger:** If the Auditor finds a flaw, it aborts the tool call and sends a "Rethink" prompt back to the LLM. The agent must fix its reasoning *before* it is allowed to act.

**B. Action (The Tool Call)**
- **Execution:** The tool is executed (e.g., editing `modular/production_05.py`).
- **Raw Output:** The tool returns a raw result (e.g., "Success: File Written").

**C. Verification (The Post-Hook)**
- **Physical Audit:** The Post-Execution Hook runs.
- **ACID Check:** The Verifier checks: *"Does the file compile? (`python3 -m py_compile`) Are operators still registered?"*
- **Recursive Command:** If the Auditor finds a "success" is actually a "failure" (e.g., syntax error, missing import), it overrides the result and forces the agent to restart the task.

### Stage 3: Cognitive Maintenance (The Trajector)

Because complex dental workflow features create massive amounts of log noise, the Cognitive Guard intervenes:

- **The 5-Turn Trigger:** Every 5 tool calls, the Trajector Hook triggers.
- **Synthesis:** It prunes the raw logs and injects a "Trajectory Summary."
- **Goal Alignment:** This prevents "drift," ensuring the agent is still targeting the correct workflow tab and hasn't drifted into unrelated modules.

### Stage 4: The Final Validation & Delivery

The agent does not declare "Done" based on its own feeling. It uses **World-Verified Completion:**

1. **The Certification Check:** The Auditor runs a final check (e.g., *"Do all modular/*.py files pass py_compile? Are new operators in the classes tuple?"*).
2. **Sovereign Approval:** Only when the environment state (files, syntax, registrations) matches the Strategic Plan does the agent proceed.
3. **The Diplomat Delivery:** The Diplomat translates the technical logs into a clean, professional report.

### Pipeline Summary

```
User Request → Strategist (Plan → Edge Case Hook)
  → Operator (Tool → Pre-Hook → Action → Post-Hook/Verify)
  → Trajector (Context Pruning every 5 turns)
  → Auditor (Final Certification)
  → Diplomat (Final Result)
```

> **This is a "Zero-Trust" architecture.** The agent proposes, the Orchestrator audits, and the World verifies.

---

## Architecture Overview

```
blendersmile_pnp_full.py     ← thin entry script (~140 lines)
modular/
├── __init__.py              ← package marker
├── core_00.py               ← constants, utilities, helpers
├── properties_01.py         ← bpy.props definitions
├── setup_02.py              ← SETUP tab operators + UI
├── analysis_03.py           ← ANALYSIS tab operators + UI
├── mockup_04.py             ← MOCKUP tab operators + UI
├── production_05.py         ← PRODUCTION tab operators + UI (largest file)
├── veneer_import_06.py      ← VENEER_IMPORT tab operators + UI
├── no_prep_07.py            ← NO_PREP tab operators + UI
├── guided_08.py             ← GUIDED tab / CAD Wizard
├── extracted_margin_tracing.py ← margin tracing operators (extracted from production)
├── panel.py                 ← orchestrator: imports all tabs, registers
└── run_blender.py           ← alternative loader script
```

**Key principles:**
- `blendersmile_pnp_full.py` is the entry point you run in Blender. Do NOT edit it directly.
- ALL code edits happen in `modular/` files. Each tab module is independent.
- After editing a `modular/` file, run `reload()` in the Python console or re-run the script (Alt+P).

---

## Default Engineering & Review Workflow

**This section applies as the default prompt for all coding work on this project unless specified otherwise.**

Review any plan thoroughly before making any code changes. For every issue or recommendation, explain the concrete tradeoffs, give an opinionated recommendation, and ask for my input before assuming a direction.

### Engineering Preferences

- **DRY is important** — flag repetition aggressively.
- **Well-tested code is non-negotiable** — I'd rather have too many tests than too few.
- **"Engineered enough"** — not under-engineered (fragile, hacky) and not over-engineered (premature abstraction, unnecessary complexity).
- **Handle more edge cases, not fewer** — thoughtfulness > speed.
- **Bias toward explicit over clever.**

### Review Sections

#### 1. Architecture Review
Evaluate:
- Overall system design and component boundaries.
- Dependency graph and coupling concerns.
- Data flow patterns and potential bottlenecks.
- Scaling characteristics and single points of failure.
- Security architecture (auth, data access, API boundaries).

#### 2. Code Quality Review
Evaluate:
- Code organization and module structure.
- DRY violations — be aggressive here.
- Error handling patterns and missing edge cases (call these out explicitly).
- Technical debt hotspots.
- Areas that are over-engineered or under-engineered relative to my preferences.

#### 3. Test Review
Evaluate:
- Test coverage gaps (unit, integration, e2e).
- Test quality and assertion strength.
- Missing edge case coverage — be thorough.
- Untested failure modes and error paths.

#### 4. Performance Review
Evaluate:
- N+1 queries and database access patterns.
- Memory-usage concerns.
- Caching opportunities.
- Slow or high-complexity code paths.

### For Each Issue Found

For every specific issue (bug, smell, design concern, or risk):
- Describe the problem concretely, with file and line references.
- Present 2-3 options, including "do nothing" where that's reasonable.
- For each option, specify: implementation effort, risk, impact on other code, and maintenance burden.
- Give an opinionated recommended option and why, mapped to the engineering preferences above.
- Then explicitly ask whether I agree or want to choose a different direction before proceeding.

### Workflow & Interaction

- Do not assume my priorities on timeline or scale.
- Provide a clear summary of your recommended choices before proceeding.

---

## Project Summary

BlenderSmile is a comprehensive Blender addon for dental professionals to design smile makeovers. It combines 3D scan processing, photo-guided design, camera calibration (PnP), and automated veneer generation into an integrated workflow.

### Core Capabilities
- **Import & Processing:** Multi-format scan import (STL, OBJ, PLY, FBX, GLTF, USD), photo mockup import
- **Analysis Tools:** Landmark placement (FACE/MAX/MAN domains), arch tracing, camera calibration via PnP
- **Design Workflows:**
  - Golden Ruler system with tri-curve tooth positioning
  - Manual tooth placement with library integration
  - NO_PREP photo-guided veneer design
- **Production:** Margin tracing, veneer shell generation, batch export

### Completed Features (Changelog)

All features below are implemented and shipped. See git log for details.

| Feature | Module | Key Functions/Operators |
|---------|--------|------------------------|
| Delete Golden Set | mockup_04.py | `SMILE_OT_delete_golden_set` |
| Tri-Curve Tooth Positioning | mockup_04.py | `evaluate_tri_curve_position_for_tooth()`, `find_curve_with_priority()` |
| Tooth Orientation Enhancement | mockup_04.py | `detect_facial_surface_by_convexity()`, `SMILE_OT_verify_golden_orientation` |
| Pre-Import Orientation | mockup_04.py | `get_pre_import_orientation_correction()` |
| Perpendicular Tick Vector | mockup_04.py | In `SMILE_OT_golden_ruler.execute()`, `update_golden_ruler()` |
| Unified Ruler Transform | mockup_04.py | Parent-child hierarchy in `update_golden_ruler()` |
| Lip Line Control Markers | mockup_04.py | `draw_lip_line`, marker create/update/clear operators |
| Smile Arc Redesign | mockup_04.py | Clinical measurements (span, arc depth, symmetry) |
| P0 Hardening (2026-04-09) | All modular/ | Bare except fixes, vector normalize guards, bmesh try/finally |

---

## Tech Stack

### Core Platform
- **Blender:** 3.6+ (Python 3.10+)
- **API:** bpy (Blender Python API)
- **Geometry:** bmesh, mathutils (Vector, Matrix, KDTree)

### Auto-Installed Dependencies
- **Open3D:** ICP alignment, point cloud processing (auto-install system lines 95-180)
- **OpenCV:** PnP solver, camera calibration (auto-install system lines 181-252)
- **NumPy:** Required by OpenCV (bundled)

### File Format Support
```python
SUPPORTED_EXTS = {
    ".obj", ".stl", ".ply", ".fbx", ".gltf", ".glb",
    ".usd", ".usda", ".usdc", ".usdz", ".abc", ".dae"
}
```

### Data Organization
```python
# Blender Collections (organizational containers)
COL_SCANS   = "Scans"        # Imported scan meshes
COL_TEETH   = "Teeth"        # Library teeth and positioned teeth
COL_LM      = "SmileLandmarks"  # FACE/MAX/MAN landmark empties
COL_ARCH    = "SmileArch"    # Arch curves and splines
COL_PREVIEW = "SmilePreview" # Ghost preview meshes
COL_VENEER  = "Veneers"      # Generated veneer shells
COL_RIG     = "SmileRig"     # Tooth deformation rigs
COL_MARGINS = "VeneerMargins" # Margin trace curves
COL_GUIDES  = "SmileGuides"  # Visual guides
COL_SILHOUETTE = "SmileSilhouette" # Photo silhouettes
```

### Coordinate System
- **Blender:** Z-up, right-handed, units in millimeters
- **Dental Conventions:**
  - `-Z` = Incisal (cutting edge, DOWN)
  - `+Z` = Cervical (root, UP)
  - `-Y` = Facial/Buccal (front, towards lips)
  - `+Y` = Lingual (back, towards tongue)
  - `X` = Mesial/Distal (side-to-side)

---

## Code Style & Conventions

### Naming Patterns

**Operators:**
```python
class SMILE_OT_<action_name>(bpy.types.Operator):
    bl_idname = "smile.<action_name>"
    bl_label = "Human Readable Label"
    bl_options = {"REGISTER", "UNDO"}  # Standard for most ops
```

**Objects:**
```python
# Landmarks: <Domain>_LM_<ID>
FACE_LM_01, FACE_LM_02  # Face scan landmarks (spheres)
MAX_LM_01, MAX_LM_02    # Maxilla landmarks (cubes)
MAN_LM_01, MAN_LM_02    # Mandible landmarks (cones)

# PnP/Photo landmarks: PNP_<type>_<ID>
PNP_3D_01, PNP_3D_02    # 3D landmarks on scan (arrows)
PNP_IMG_01, PNP_IMG_02  # 2D landmarks on photo (circles)

# Golden Ruler system
SMILE_Golden_Ruler       # Linear ruler (shrinkwrapped)
SMILE_Golden_Arch        # Quadratic bezier with depth
SMILE_Golden_Ruler_Arch  # Auto-generated arch curve

# Arch curves
ARCH_MAX_CURVE  # Manual traced maxilla arch
ARCH_MAN_CURVE  # Manual traced mandible arch

# Teeth: Tooth#<FDI_Number>
Tooth#8, Tooth#9, Tooth#11  # FDI notation (#1-#32)
```

**Custom Properties (scene-level storage):**
```python
# Scene properties (JSON-serialized arrays)
scene[KEY_ARCH_MAX_PTS]    = "SMILE_ARCH_MAX_PTS"  # List of arch points
scene[KEY_ARCH_MAN_PTS]    = "SMILE_ARCH_MAN_PTS"
scene[KEY_MARGIN_PREFIX + obj.name]  # Per-object margin points

# Object tracking tags
obj["SMILE_GOLDEN_SET_IMPORT"] = True       # Imported via golden set
obj["SMILE_GOLDEN_SET_TOOTH_ID"] = tid      # Tooth #6-#11
obj["SMILE_CREATED_AT"] = float(time.time()) # Timestamp
obj["SMILE_IS_TOOTH"] = True                # Generic tooth marker
obj["SMILE_IS_FACE_LM"] = 1                 # Face landmark marker
```

**Functions:**
```python
# Helpers use snake_case
def evaluate_curve_at_parameter(curve_obj, t):
def find_curve_with_priority(curve_names, context_msg=""):
def calculate_orientation_from_anatomical_points(incisal_pt, facial_pt, center):

# Utility prefix patterns
def ensure_<resource>()  # Create if missing, return existing
def bbox_world(obj)      # Calculate bounding box in world space
def make_marker(name, loc, size, col, color, shape)  # Visual marker creation
```

**Constants:**
```python
# All caps for module-level constants
COL_SCANS = "Scans"
DOMAIN_FACE = "FACE"
NEON = [(r,g,b,a), ...]  # Color palette (8 neon colors)
```

### Error Handling Pattern
```python
def execute(self, context):
    try:
        # Validation
        if not prerequisite:
            self.report({'ERROR'}, "Clear message to user")
            return {'CANCELLED'}

        # Main logic
        result = do_operation()

        # Success feedback
        self.report({'INFO'}, f"Success: {result}")
        return {'FINISHED'}

    except Exception as e:
        self.report({'ERROR'}, f"Operation failed: {str(e)}")
        traceback.print_exc()  # Console logging
        return {'CANCELLED'}
```

### UI Patterns
```python
# Panel sections use boxes for grouping
box = layout.box()
box.label(text="Section Title", icon='ICON_NAME')
row = box.row(align=True)
row.operator("smile.action", text="Button Label", icon='ICON')

# Properties displayed inline
box.prop(props, "property_name")  # Auto-generates UI from property definition

# Collapsible sections (if needed in future)
# Use `box.prop(props, "show_advanced", icon='TRIA_DOWN' if props.show_advanced else 'TRIA_RIGHT')`
```

### Modal Operator Pattern (for interactive tools)
```python
class SMILE_OT_interactive_tool(bpy.types.Operator):
    bl_idname = "smile.interactive_tool"
    bl_label = "Interactive Tool"

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Pass-through for navigation
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or event.alt:
            return {'PASS_THROUGH'}

        # Cancel
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cleanup()
            return {'CANCELLED'}

        # Action
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.do_action(context, event)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}
```

---

## Project Structure

### File Organization

See **Architecture Overview** above for the current file tree. All code lives in `modular/`.

### Key Operators Reference

**Data Import (11 ops):**
- `smile.import_scan` - Load 3D scan mesh
- `smile.import_library_tooth` - Import single tooth from library
- `smile.import_golden_set` - **Modified in Phase 2** - Tri-curve tooth positioning
- `smile.delete_golden_set` - **Added in Phase 1** - Remove golden set teeth
- `smile.import_photo_mockup` - Load 2D photo plane

**Landmarks & Alignment (15 ops):**
- `smile.add_landmark` - Create FACE/MAX/MAN landmark
- `smile.add_landmark_pair` - Create PNP_3D + PNP_IMG pair (NO_PREP)
- `smile.show_alignment_lines` - Visualize landmark correspondence
- `smile.clear_calibration_landmarks` - Remove all PNP landmarks
- `smile.align_scan_to_photo` - **SVD/Kabsch algorithm** (NO_PREP recommended)
- `smile.calibrate_2d_camera` - **OpenCV PnP** (moves camera)

**Arch & Curves (8 ops):**
- `smile.arch_trace` - Modal arch tracing on scan
- `smile.golden_ruler` - Draw canine-to-canine ruler
- `smile.update_golden_ruler` - Regenerate golden arch with depth

**Tooth Placement & Layout (12 ops):**
- `smile.layout_teeth_width_aware` - Distribute teeth along arch
- `smile.golden_import` - Alias for import_golden_set
- Functions use tri-curve system:
  - `evaluate_tri_curve_position_for_tooth()` - **Phase 2 addition**
  - `find_curve_with_priority()` - **Phase 2 addition**
  - `find_existing_tooth_for_angulation()` - **Phase 2 addition**

**Margin Tracing (15+ ops):**
- `smile.margin_trace_livewire` - A* pathfinding on mesh
- `smile.margin_trace_geodesic` - Geodesic distance tracing
- `smile.margin_finalize` - Convert traced margin to curve

**Veneer Production (20+ ops):**
- `smile.generate_no_prep_veneer` - Create ultra-thin shell (NO_PREP)
- `smile.veneer_from_margin` - Generate veneer from margin curve
- `smile.export_no_prep_veneer_stl` - Export for 3D printing

---

## Workflow States (UI Tabs)

```python
workflow_state: EnumProperty(
    items=[
        ('IMPORT', "1. Import", "Import scans and photos"),
        ('ALIGN', "2. Analysis", "Landmarks and alignment"),
        ('DESIGN', "3. Design", "Tooth placement and mockup"),
        ('EXPORT', "4. Export", "Export and production"),
        ('NO_PREP', "5. No-Prep", "Photo-guided veneer design"),  # ⭐ Latest addition
    ]
)
```

**Tab 1 - IMPORT:**
- Scan import (multi-format support)
- Library browsing and cycling
- Batch import tools

**Tab 2 - ANALYSIS (ALIGN):**
- Landmark placement (FACE/MAX/MAN)
- Arch tracing modal
- Alignment diagnostics
- PnP calibration (if NO_PREP not used)

**Tab 3 - DESIGN:**
- Golden Ruler system
  - Draw ruler (canine-to-canine)
  - Set arch depth (golden_arch_depth slider)
  - Import golden set (#6-#11) - **Tri-curve positioning**
  - Delete golden set - **Phase 1 feature**
- Manual tooth placement
- Width-aware layout
- Tooth rigging and preview

**Tab 4 - EXPORT:**
- Veneer generation from margins
- Batch export (STL/OBJ)
- 3D printing validation

**Tab 5 - NO_PREP:** ⭐ **Photo-Guided Workflow**
- Import 2D photo mockup
- Add PnP landmark pairs (6-8 recommended)
- Visualize alignment lines
- Align scan to photo (SVD/Kabsch) OR move camera to scan (PnP)
- Generate ultra-thin veneer (0.3-1.0mm)
- Export veneer STL
- **Complete guide:** `NO_PREP_COMPLETE_GUIDE.md`

---

## Known Issues & Next TODOs

### Known Bugs

**None critical** — all operators working as of 2026-04-09.

### Future Enhancements (Not Started)

- AI-powered tooth segmentation and face analysis
- Beginner-friendly wizard workflows (guided_08.py has early CAD Wizard)
- ML margin prediction and automatic undercut detection
- Cloud library sync and tooth morphology auto-matching

---

## Test Scenarios

### Test Coverage Status

**Real coverage: ~0%** — Only `tests/test_capture_quality.py` is substantive. 83 operators are untested. Most code is tightly coupled to `bpy` and cannot be unit tested outside Blender. Priority: extract pure functions for testability.

### Testing Checklist for New Features

When adding new operators:
1. **Validation:** Check prerequisites (objects exist, correct types, etc.)
2. **Undo Support:** Add `'UNDO'` to bl_options
3. **User Feedback:** self.report({'INFO'|'WARNING'|'ERROR'}, message)
4. **Error Handling:** Try/except with console logging (traceback.print_exc())
5. **Collection Management:** Use ensure_collection() pattern
6. **Naming Conventions:** Follow established patterns (COL_*, <Domain>_LM_*, etc.)
7. **Registration:** Add to classes tuple and verify registration
8. **UI Integration:** Add button/prop to appropriate workflow tab
9. **Documentation:** Update CLAUDE.md and relevant guides

---

## Critical Code Locations

### Core Systems (Reference)
- **Constants:** `modular/core_00.py` (COL_*, DOMAIN_*, KEY_*)
- **Open3D auto-install:** `modular/core_00.py`
- **OpenCV auto-install:** `modular/core_00.py`
- **Kabsch alignment:** `modular/core_00.py` (SVD rigid body transform)
- **PnP system:** `modular/no_prep_07.py` (camera calibration)
- **NO_PREP operators:** `modular/no_prep_07.py` (AddLandmarkPair, AlignScanToPhoto, etc.)
- **Registration:** `modular/panel.py` (orchestrates all tab registrations)

---

## Development Guidelines

### Adding New Features

**Rule 1: Modularity**
- Isolate new code in clearly marked sections (`=== NEW FEATURE ===` comments)
- Use helper functions instead of inline logic
- Design for easy removal if feature doesn't work out

**Rule 2: Backward Compatibility**
- Never break existing workflows
- Use optional properties with safe defaults
- Provide fallback behavior (e.g., tri-curve fallback to single curve)

**Rule 3: Minimal Surface Area**
- Modify fewest possible existing functions
- Prefer adding new functions over modifying old ones
- Keep changes to existing code under 30 lines where possible

**Rule 4: Documentation**
- Update CLAUDE.md immediately after implementation
- Add inline comments for complex algorithms
- Document all custom properties in tooltips
- Keep NO_PREP_COMPLETE_GUIDE.md in sync with NO_PREP features

### Code Review Checklist

Before considering a feature "done":
- [ ] All new operators have bl_idname, bl_label, bl_options
- [ ] All new properties have name, description, sensible defaults
- [ ] UI buttons have clear text and appropriate icons
- [ ] Error messages are user-friendly (not technical Python errors)
- [ ] Console logging for debugging (print statements or logging module)
- [ ] Registration verified (operator shows in F3 search)
- [ ] Undo/redo works correctly
- [ ] No breaking changes to existing workflows
- [ ] Performance acceptable (no 10+ second operations without feedback)
- [ ] CLAUDE.md updated with new code locations and features

### Performance Notes

**KDTree Caching:**
```python
_KD_CACHE = {}  # (obj.name, obj.data.name, nverts) -> KDTree
# Used for fast nearest-neighbor queries during margin tracing
# Automatically invalidated when mesh topology changes
```

**Mesh Operations:**
- Use bmesh for topology changes (faster than bpy.ops)
- Batch geometry updates when possible
- Avoid repeated world matrix calculations in loops

**Open3D Operations:**
- ICP can be slow on high-poly meshes (100k+ verts)
- Consider downsampling for alignment, then apply to original
- Use voxel downsampling for preview: `pcd.voxel_down_sample(voxel_size=0.5)`

---

## Quick Reference

### Most Frequently Modified Files
```
modular/*.py             ← ALL code edits go here (tab modules)
modular/panel.py         ← orchestrator: tab dispatch, registration
blendersmile_pnp_full.py ← thin entry script (do NOT edit)
CLAUDE.md                ← This file (context documentation)
NO_PREP_COMPLETE_GUIDE.md  # NO_PREP workflow tutorial
clever-swinging-cosmos.md  # Phase-by-phase implementation plan
```

### Common Commands (Blender Console)
```python
import bpy

# Reload addon after code changes
bpy.ops.script.reload()

# Quick access to props
p = bpy.context.scene.smile_props

# List all operators
for op_id, op_name in [("smile.import_golden_set", "Import Golden Set"), ...]:
    print(f"{op_id}: {hasattr(bpy.ops.smile, op_id.split('.')[1])}")

# Check workflow state
print(p.workflow_state)  # 'NO_PREP', 'DESIGN', etc.
```

### Regex Patterns
```python
# Tooth ID extraction (FDI notation)
FDI_REGEX = re.compile(r"#\s*(\d{2})")
match = FDI_REGEX.search("Tooth#11")
if match:
    tooth_id = int(match.group(1))  # 11
```

### Color Palette (NEON)
```python
NEON[0]  # (1.0, 0.05, 0.55, 1.0)  Neon Pink
NEON[1]  # (0.1, 1.0, 0.1, 1.0)    Neon Green
NEON[2]  # (0.1, 0.65, 1.0, 1.0)   Neon Blue
# ... 8 colors total, used for landmark visualization
```

---

## Session Resumption Checklist

When starting a new session:
1. Read this file (CLAUDE.md) for full context
2. Run `git log --oneline -5` to see recent changes
3. Run `git status` for modified files
4. All code edits happen in `modular/` — NEVER edit `blendersmile_pnp_full.py`
5. After editing: `reload()` in Python console or re-run script (Alt+P)

---

*Last updated: 2026-04-09 — P0 hardening pass, CLAUDE.md restructured for AI effectiveness*
