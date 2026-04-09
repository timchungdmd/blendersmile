"""
BlenderSmile Panel Module - Main panel and registration orchestrator

This module ties together all tab modules and provides the main Blender panel.
The actual UI for each tab is defined in its respective module.

To disable a tab, set _ENABLED_TABS["tab_name"] = False below.
"""

import bpy
import sys
import os
import json
import math
import time
import traceback
from datetime import datetime
from mathutils import Vector, Matrix

# === CONFIGURATION ===
_ENABLED_TABS = {
    "setup": True,
    "analysis": True,
    "mockup": True,
    "production": True,
    "veneer_import": True,
    "no_prep": True,
    "guided": True,
}

# === TAB MODULE IMPORTS ===
import core_00 as core
import properties_01 as properties
import setup_02
import analysis_03
import mockup_04
import production_05
import veneer_import_06
import no_prep_07
import guided_08

# === GIZMO GROUP ===
try:
    from bpy.types import Gizmo, GizmoGroup

    GIZMOS_AVAILABLE = True
except ImportError:
    GIZMOS_AVAILABLE = False

_GIZMO_CLASS = None
for _mod in [
    core,
    properties,
    setup_02,
    analysis_03,
    mockup_04,
    production_05,
    veneer_import_06,
    no_prep_07,
    guided_08,
]:
    if hasattr(_mod, "SMILE_GGT_tooth_gimbal"):
        _GIZMO_CLASS = getattr(_mod, "SMILE_GGT_tooth_gimbal")
        break

if _GIZMO_CLASS is None and GIZMOS_AVAILABLE:

    class SMILE_GGT_tooth_gimbal(GizmoGroup):
        bl_idname = "SMILE_GGT_tooth_gimbal"
        bl_label = "Smile Tooth Gizmos"
        bl_options = {"3D"}

        @classmethod
        def poll(cls, context):
            return context.object and context.object.type == "MESH"

        def setup(self, context):
            pass

        def refresh(self, context):
            pass

        def draw_prepare(self, context):
            pass

        def draw(self, context):
            pass

    GIZMO_CLASS = SMILE_GGT_tooth_gimbal
elif _GIZMO_CLASS is not None:
    GIZMO_CLASS = _GIZMO_CLASS
else:
    GIZMO_CLASS = None

# === TAB DISPATCH MAP ===
_TAB_DRAW_FUNCTIONS = {}
if _ENABLED_TABS.get("setup"):
    _TAB_DRAW_FUNCTIONS["SETUP"] = setup_02.draw_setup_tab
if _ENABLED_TABS.get("analysis"):
    _TAB_DRAW_FUNCTIONS["ANALYSIS"] = analysis_03.draw_analysis_tab
if _ENABLED_TABS.get("mockup"):
    _TAB_DRAW_FUNCTIONS["MOCKUP"] = mockup_04.draw_mockup_tab
if _ENABLED_TABS.get("production"):
    _TAB_DRAW_FUNCTIONS["PRODUCTION"] = production_05.draw_production_tab
if _ENABLED_TABS.get("veneer_import"):
    _TAB_DRAW_FUNCTIONS["VENEER_IMPORT"] = veneer_import_06.draw_veneer_import_tab
if _ENABLED_TABS.get("no_prep"):
    _TAB_DRAW_FUNCTIONS["NO_PREP"] = no_prep_07.draw_no_prep_tab
if _ENABLED_TABS.get("guided"):
    _TAB_DRAW_FUNCTIONS["GUIDED"] = guided_08.draw_guided_tab


# === MAIN PANEL CLASS ===
class SMILE_PT_panel(bpy.types.Panel):
    """BlenderSmile Pro - Dental Smile Design Panel"""

    bl_label = "BlenderSmile Pro"
    bl_idname = "SMILE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smile"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        if not hasattr(scene, "smile_v2"):
            layout.label(text="Smile addon not initialized", icon="ERROR")
            return
        props = scene.smile_v2
        workflow = props.workflow_state
        layout.prop(props, "workflow_state", expand=True)
        if workflow in _TAB_DRAW_FUNCTIONS:
            draw_func = _TAB_DRAW_FUNCTIONS[workflow]
            try:
                draw_func(context, layout, props)
            except Exception as e:
                layout.label(text=f"Error drawing tab: {e}", icon="ERROR")
        else:
            layout.label(text=f"Tab '{workflow}' not available", icon="INFO")


# === REGISTRATION ===
CLASSES = [SMILE_PT_panel]


def register():
    """Register all enabled modules."""
    print("[BlenderSmile] Starting registration...")
    print(
        f"[BlenderSmile] P4_CLASSES_LIST type: {type(P4_CLASSES_LIST)}, len: {len(P4_CLASSES_LIST)}"
    )

    # Register core modules
    if hasattr(core, "register"):
        try:
            core.register()
            print("[BlenderSmile] Core registered")
        except Exception as e:
            print(f"[BlenderSmile] Core registration failed: {e}")
            import traceback

            traceback.print_exc()
    else:
        print("[BlenderSmile] WARNING: core has no register function")

    if hasattr(properties, "register"):
        try:
            properties.register()
            print("[BlenderSmile] Properties registered")
        except Exception as e:
            print(f"[BlenderSmile] Properties registration failed: {e}")
            import traceback

            traceback.print_exc()
    else:
        print("[BlenderSmile] WARNING: properties has no register function")

    registered_count = 0
    if _ENABLED_TABS.get("setup") and hasattr(setup_02, "register"):
        try:
            setup_02.register()
            registered_count += 1
            print("[BlenderSmile] Setup tab registered")
        except Exception as e:
            print(f"[BlenderSmile] Setup tab registration failed: {e}")
    if _ENABLED_TABS.get("analysis") and hasattr(analysis_03, "register"):
        try:
            analysis_03.register()
            registered_count += 1
            print("[BlenderSmile] Analysis tab registered")
        except Exception as e:
            print(f"[BlenderSmile] Analysis tab registration failed: {e}")
    if _ENABLED_TABS.get("mockup") and hasattr(mockup_04, "register"):
        try:
            mockup_04.register()
            registered_count += 1
            print("[BlenderSmile] Mockup tab registered")
        except Exception as e:
            print(f"[BlenderSmile] Mockup tab registration failed: {e}")
    if _ENABLED_TABS.get("production") and hasattr(production_05, "register"):
        try:
            production_05.register()
            registered_count += 1
            print("[BlenderSmile] Production tab registered")
        except Exception as e:
            print(f"[BlenderSmile] Production tab registration failed: {e}")
    if _ENABLED_TABS.get("veneer_import") and hasattr(veneer_import_06, "register"):
        try:
            veneer_import_06.register()
            registered_count += 1
            print("[BlenderSmile] Veneer import tab registered")
        except Exception as e:
            print(f"[BlenderSmile] Veneer import tab registration failed: {e}")
    if _ENABLED_TABS.get("no_prep") and hasattr(no_prep_07, "register"):
        try:
            no_prep_07.register()
            registered_count += 1
            print("[BlenderSmile] No-Prep tab registered")
        except Exception as e:
            print(f"[BlenderSmile] No-Prep tab registration failed: {e}")
    if _ENABLED_TABS.get("guided") and hasattr(guided_08, "register"):
        try:
            guided_08.register()
            registered_count += 1
            print("[BlenderSmile] Guided tab registered")
        except Exception as e:
            print(f"[BlenderSmile] Guided tab registration failed: {e}")

    # Register main panel
    try:
        bpy.utils.register_class(SMILE_PT_panel)
        print("[BlenderSmile] SMILE_PT_panel registered successfully")
    except Exception as e:
        print(f"[BlenderSmile] Panel registration failed: {e}")
        import traceback

        traceback.print_exc()

    if GIZMO_CLASS is not None:
        try:
            bpy.utils.register_class(GIZMO_CLASS)
            print("[BlenderSmile] Gizmo class registered")
        except Exception as e:
            print(f"[BlenderSmile] Gizmo registration failed: {e}")

    print(f"[BlenderSmile] Registration complete. {registered_count} tabs enabled.")

    # Register P4 operators
    try:
        print(
            f"[BlenderSmile][P4] Attempting to register {len(P4_CLASSES_LIST)} operators..."
        )
        for c in P4_CLASSES_LIST:
            try:
                bpy.utils.register_class(c)
                print(f"[BlenderSmile][P4] Registered: {c.bl_idname}")
            except Exception as e2:
                print(f"[BlenderSmile][P4] Failed to register {c}: {e2}")
        print(f"[BlenderSmile][P4] Operator registration complete.")
    except Exception as e:
        print(f"[BlenderSmile][P4] Operator registration failed: {e}")
        import traceback

        traceback.print_exc()

    try:
        setup_dental_workspace()
        print("[BlenderSmile][P4] Dental workspace setup complete")
    except Exception as e:
        print(f"[BlenderSmile][P4] Workspace setup failed: {e}")
        import traceback

        traceback.print_exc()

    try:
        bpy.app.handlers.depsgraph_update_post.append(smile_ruler_depsgraph_handler)
        print("[BlenderSmile][P4] Depsgraph handler registered")
    except Exception as e:
        print(f"[BlenderSmile][P4] Depsgraph handler registration failed: {e}")
        import traceback

        traceback.print_exc()


def unregister():
    """Unregister all modules in reverse order."""
    print("[BlenderSmile] Starting unregistration...")
    try:
        if smile_ruler_depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(smile_ruler_depsgraph_handler)
    except Exception:
        pass
    try:
        for c in reversed(P4_CLASSES_LIST):
            bpy.utils.unregister_class(c)
    except Exception:
        pass
    if GIZMO_CLASS is not None:
        try:
            bpy.utils.unregister_class(GIZMO_CLASS)
        except Exception:
            pass
    try:
        bpy.utils.unregister_class(SMILE_PT_panel)
    except Exception:
        pass
    if _ENABLED_TABS.get("guided") and hasattr(guided_08, "unregister"):
        guided_08.unregister()
    if _ENABLED_TABS.get("no_prep") and hasattr(no_prep_07, "unregister"):
        no_prep_07.unregister()
    if _ENABLED_TABS.get("veneer_import") and hasattr(veneer_import_06, "unregister"):
        veneer_import_06.unregister()
    if _ENABLED_TABS.get("production") and hasattr(production_05, "unregister"):
        production_05.unregister()
    if _ENABLED_TABS.get("mockup") and hasattr(mockup_04, "unregister"):
        mockup_04.unregister()
    if _ENABLED_TABS.get("analysis") and hasattr(analysis_03, "unregister"):
        analysis_03.unregister()
    if _ENABLED_TABS.get("setup") and hasattr(setup_02, "unregister"):
        setup_02.unregister()
    if hasattr(properties, "unregister"):
        properties.unregister()
    if hasattr(core, "unregister"):
        core.unregister()
    print("[BlenderSmile] Unregistration complete.")


# === HELPER FUNCTIONS ===
def get_enabled_tabs():
    return [k for k, v in _ENABLED_TABS.items() if v]


def disable_tab(tab_name):
    if tab_name in _ENABLED_TABS:
        _ENABLED_TABS[tab_name] = False


def enable_tab(tab_name):
    if tab_name in _ENABLED_TABS:
        _ENABLED_TABS[tab_name] = True


# === P4 FORWARD DECLARATIONS (will be populated by code at end of file) ===
# These placeholders are overwritten by the actual definitions at end of file
P4_CLASSES_LIST = []


def setup_dental_workspace():
    """Placeholder - actual implementation defined below."""
    pass


def smile_ruler_depsgraph_handler(scene, depsgraph):
    """Placeholder - actual implementation defined below."""
    pass


# === P4 CLASSES LIST (forward reference, updated at end of file) ===
# This will be populated with the actual P4 operator classes defined below
# P4_CLASSES_LIST = (
#     SMILE_OT_apply_collection_visibility_now,
#     ... etc ...
# )
# See end of file for actual definition.


# === P4 REVIEW WORKSPACE, CASE REPORT, AND REGISTRATION INFRASTRUCTURE ===
# Extracted from blendersmile_pnp_full_cleaned_20260318_165959.py


# --- HELPER FUNCTIONS ---
def ensure_collection(name: str):
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        try:
            bpy.context.scene.collection.children.link(col)
        except (AttributeError, RuntimeError):
            # Safe for restricted context during registration
            pass
    return col


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


def focus_object(context, obj):
    if not obj:
        return
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    try:
        obj.hide_set(False)
    except Exception:
        pass
    obj.hide_viewport = False
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _set_collection_viewport_state(context, col_name: str, should_show: bool):
    col = bpy.data.collections.get(col_name)
    if not col:
        return False
    try:
        col.hide_viewport = not bool(should_show)
    except Exception:
        pass
    try:
        lc_root = context.view_layer.layer_collection
        lc = _find_layer_collection(lc_root, col_name)
        if lc:
            lc.exclude = False
            lc.hide_viewport = not bool(should_show)
    except Exception:
        pass
    return True


def _apply_workflow_collection_visibility(scene, workflow_state, context=None):
    if not scene:
        try:
            scene = context.scene if context else getattr(bpy.context, "scene", None)
        except (AttributeError, RuntimeError):
            scene = None
    if not scene:
        return
    visibility_map = WORKFLOW_COLLECTION_VISIBILITY_MAP.get(str(workflow_state or ""))
    if not isinstance(visibility_map, dict):
        return

    ensure_core_collections()
    for col_name, should_show in visibility_map.items():
        col = bpy.data.collections.get(col_name)
        if not col:
            continue
        try:
            col.hide_viewport = not bool(should_show)
        except Exception:
            pass
        try:
            for view_layer in scene.view_layers:
                layer_col = _find_layer_collection(
                    view_layer.layer_collection, col_name
                )
                if layer_col:
                    layer_col.exclude = False
                    layer_col.hide_viewport = not bool(should_show)
        except (AttributeError, RuntimeError):
            pass

    if str(workflow_state) in {"MOCKUP", "PRODUCTION", "NO_PREP", "VENEER_IMPORT"}:
        try:
            ensure_arch_tracers_visible(scene, context or bpy.context)
        except Exception:
            pass


def _apply_review_section_style(obj, style_key: str):
    if (
        not obj
        or obj.type != "MESH"
        or str(obj.get("SMILE_REVIEW_KIND", "")) != "SECTION"
    ):
        return False
    preset = review_section_style_preset(style_key)
    display_type = str(preset.get("display_type", "SOLID") or "SOLID")
    obj.display_type = display_type
    obj.show_wire = display_type == "WIRE"
    obj.show_in_front = bool(preset.get("show_in_front", True))
    rgba = tuple(preset.get("color", (0.18, 0.72, 1.0, 1.0)))
    obj.color = rgba
    if display_type != "WIRE":
        mat = _ensure_review_section_material(style_key)
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    return True


def review_preset_visibility(preset_key):
    key = str(preset_key or "ALL").upper()
    base = REVIEW_WORKSPACE_PRESETS.get(key, REVIEW_WORKSPACE_PRESETS["ALL"])
    return dict(base)


def build_local_present_snapshot_name(scene_name, workflow_state, preset_key, stamp):
    base = f"{scene_name}_{workflow_state}_{preset_key}_{stamp}".strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    return f"{base or 'smile_present_snapshot'}.png"


def build_review_artifact_name(kind, label, tooth_id=0):
    kind_token = (
        re.sub(r"[^A-Z0-9]+", "_", str(kind or "artifact").upper()).strip("_")
        or "ARTIFACT"
    )
    label_token = (
        re.sub(r"[^A-Z0-9]+", "_", str(label or "item").upper()).strip("_") or "ITEM"
    )
    tid = int(tooth_id or 0)
    if tid > 0:
        return f"REVIEW_{kind_token}_T{tid}_{label_token}"
    return f"REVIEW_{kind_token}_{label_token}"


def review_section_axis_vector(orientation):
    key = str(orientation or "CORONAL").upper()
    mapping = {
        "AXIAL": (0.0, 0.0, 1.0),
        "CORONAL": (0.0, 1.0, 0.0),
        "SAGITTAL": (1.0, 0.0, 0.0),
    }
    return tuple(mapping.get(key, mapping["CORONAL"]))


def calculate_review_section_offset_mm(origin_xyz, location_xyz, axis_xyz):
    origin = tuple(float(v) for v in (origin_xyz or (0.0, 0.0, 0.0)))
    location = tuple(float(v) for v in (location_xyz or (0.0, 0.0, 0.0)))
    axis = tuple(float(v) for v in (axis_xyz or (0.0, 1.0, 0.0)))
    axis_len = sum(v * v for v in axis) ** 0.5
    if axis_len < 1e-8:
        return 0.0
    delta = tuple(location[i] - origin[i] for i in range(3))
    projected_world = sum(delta[i] * axis[i] for i in range(3)) / axis_len
    return projected_world * 1000.0


def _sync_workflow_progress(props):
    """
    Keep workflow tab and guided step logically compatible.
    Current policy:
    - if enforce_step_lock is ON, guided step is auto-raised to tab minimum.
    """
    before = _current_design_step(props) if props is not None else 1
    state = (
        str(getattr(props, "workflow_state", "SETUP") or "SETUP")
        if props is not None
        else "SETUP"
    )
    min_required = _workflow_min_step_for_state(state)
    changed = False
    after = before

    if (
        props is not None
        and bool(getattr(props, "enforce_step_lock", False))
        and before < min_required
    ):
        props.design_step = str(min_required)
        after = int(min_required)
        changed = True

    return {
        "changed": bool(changed),
        "workflow_state": state,
        "design_step_before": int(before),
        "design_step_after": int(after),
        "min_required_step": int(min_required),
    }


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


def universal_to_fdi(tooth_id: int):
    """Convert Universal adult tooth ID (1..32) to FDI (11..48)."""
    try:
        u = int(tooth_id)
    except Exception:
        return None
    if 1 <= u <= 8:
        return int(10 + (9 - u))
    if 9 <= u <= 16:
        return int(20 + (u - 8))
    if 17 <= u <= 24:
        return int(30 + (25 - u))
    if 25 <= u <= 32:
        return int(40 + (u - 24))
    return None


def _normalize_tooth_id_universal(tooth_id, notation_hint="AUTO"):
    """Normalize tooth ID input to Universal notation when possible."""
    if tooth_id is None:
        return None
    try:
        tid = int(tooth_id)
    except Exception:
        return None

    hint = str(notation_hint or "AUTO").upper()
    if hint == "FDI":
        return fdi_to_universal(tid)
    if hint == "UNIVERSAL":
        return tid if 1 <= tid <= 32 else None
    # AUTO: preserve valid Universal first, then try FDI conversion.
    if 1 <= tid <= 32:
        return tid
    conv = fdi_to_universal(tid)
    return conv if conv is not None else None


def _int_or_default(v, default=0):
    try:
        return int(v)
    except Exception:
        return int(default)


def resolve_source_obj(active_obj):
    """
    Canonical source resolver:
    - If a veneer is active, return the recorded source mesh.
    - Otherwise return the active mesh itself.
    """
    if not active_obj or active_obj.type != "MESH":
        return None

    source_name = str(active_obj.get("SMILE_VENEER_SOURCE", "")).strip()
    if source_name:
        src = bpy.data.objects.get(source_name)
        if src and src.type == "MESH":
            return src

    guessed = _guess_source_from_veneer_name(active_obj.name)
    if guessed:
        return guessed
    return active_obj


def _json_obj(value, default=None):
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    if isinstance(value, (int, float, bool)):
        return default
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, dict):
            return parsed
        return default
    except Exception:
        return default


def _mesh_signature(obj) -> str:
    if not obj or obj.type != "MESH":
        return ""
    n = len(obj.data.vertices)
    m = len(obj.data.polygons)
    bb = [Vector(c) for c in obj.bound_box] if obj.bound_box else [Vector((0, 0, 0))]
    mn = Vector((min(c.x for c in bb), min(c.y for c in bb), min(c.z for c in bb)))
    mx = Vector((max(c.x for c in bb), max(c.y for c in bb), max(c.z for c in bb)))
    payload = f"{obj.name}|{n}|{m}|{mn.x:.6f}|{mn.y:.6f}|{mn.z:.6f}|{mx.x:.6f}|{mx.y:.6f}|{mx.z:.6f}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_input_checksum(source_obj, recipe=None, align_state=None) -> str:
    """
    Hash of build-critical inputs used to detect stale exports/regeneration contexts.
    """
    source = resolve_source_obj(source_obj)
    source_sig = _mesh_signature(source)

    recipe_payload = (
        _json_obj(recipe, default={}) if not isinstance(recipe, dict) else dict(recipe)
    )
    align_payload = _json_obj(align_state, default={})
    if isinstance(align_payload, dict):
        align_payload = dict(align_payload)
        align_payload.pop("timestamp_utc", None)  # exclude volatile field

    payload = {
        "source_name": source.name if source else "",
        "source_signature": source_sig,
        "recipe": recipe_payload,
        "align_state": align_payload,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


def _find_veneer_by_tooth_id(source_obj, tooth_id):
    source = resolve_source_obj(source_obj)
    if not source:
        return None
    tid = int(tooth_id)
    ven_name = canonical_veneer_name(source.name, tid)
    ven = bpy.data.objects.get(ven_name)
    if ven and ven.type == "MESH":
        return ven

    col = bpy.data.collections.get(COL_VENEER)
    if not col:
        return None
    for o in col.objects:
        if o.type != "MESH":
            continue
        if (
            str(o.get("SMILE_VENEER_SOURCE", "")) == source.name
            and _int_or_default(o.get("SMILE_VENEER_TOOTH_ID", 0), 0) == tid
        ):
            return o
    tag = f"_T{tid}"
    for o in col.objects:
        if o.type == "MESH" and tag in o.name:
            return o
    return None


def get_saved_veneer_recipe(obj, tooth_id=None):
    """Load recipe from mesh custom props (preferred) with scene fallback."""
    obj = resolve_source_obj(obj)
    if not obj:
        return None
    if tooth_id is None:
        tooth_id = parse_tooth_id_from_name(obj.name) or getattr(
            bpy.context.scene.smile_v2, "ven_target_tooth_id", 0
        )
    key = _recipe_key_for_tooth(int(tooth_id))

    raw = None
    if obj.data and key in obj.data:
        raw = obj.data.get(key)
    elif bpy.context.scene and key in bpy.context.scene:
        raw = bpy.context.scene.get(key)

    if raw is None:
        return None

    if isinstance(raw, dict):
        return raw

    parsed = _json_obj(raw, default=None)
    return parsed


def _get_frame3d_apply_summary(scene):
    if not scene:
        return {}
    return _json_obj(scene.get(KEY_FRAME3D_LAST_APPLY_JSON, "{}"), default={})


def _get_case_report_diagnostics(scene):
    if not scene:
        return {}
    return _json_obj(scene.get(KEY_CASE_REPORT_DIAG_JSON, "{}"), default={})


def _store_case_report_diagnostics(
    scene, diagnostics, action="", status="", filepath=""
):
    if not scene:
        return
    diag = _json_obj(diagnostics, default={})
    if not isinstance(diag, dict):
        diag = {"value": diag}
    ts = datetime.utcnow().isoformat() + "Z"
    meta = _json_obj(diag.get("_meta", {}), default={})
    if not isinstance(meta, dict):
        meta = {}
    meta["timestamp_utc"] = ts
    meta["action"] = str(action or meta.get("action", ""))
    meta["status"] = str(status or meta.get("status", ""))
    meta["filepath"] = str(filepath or meta.get("filepath", ""))
    diag["_meta"] = meta
    scene[KEY_CASE_REPORT_DIAG_TS] = ts
    scene[KEY_CASE_REPORT_DIAG_JSON] = json.dumps(
        diag, sort_keys=True, separators=(",", ":")
    )


def _case_report_diagnostics(payload, scene=None):
    """
    Lightweight integrity diagnostics for case report payloads.
    Runs both at export and import time.
    """
    p = _json_obj(payload, default={})
    if not isinstance(p, dict):
        return {
            "schema_ok": False,
            "schema_version_found": None,
            "schema_version_expected": 1,
            "missing_sections": [],
            "missing_fields": [],
            "object_refs": {},
            "stale": {"is_stale": False, "reasons": []},
            "warnings": ["payload_not_dict"],
            "errors": ["invalid_payload_type"],
        }

    expected_ver = 1
    found_ver = p.get("report_version")
    schema_ok = bool(found_ver == expected_ver)

    required_sections = [
        "report_version",
        "workflow",
        "targets",
        "settings_snapshot",
        "frame3d_last_apply",
    ]
    missing_sections = [k for k in required_sections if k not in p]

    missing_fields = []
    wf = p.get("workflow", {}) if isinstance(p.get("workflow", {}), dict) else {}
    for key in (
        "state",
        "design_step",
        "step1_done",
        "step2_done",
        "step3_done",
        "step4_done",
        "step5_done",
        "step6_done",
    ):
        if key not in wf:
            missing_fields.append(f"workflow.{key}")
    tg = p.get("targets", {}) if isinstance(p.get("targets", {}), dict) else {}
    for key in ("face", "max", "man", "photo", "target_tooth_id"):
        if key not in tg:
            missing_fields.append(f"targets.{key}")

    object_refs = {}
    if scene is not None and isinstance(tg, dict):
        for ref_key in (
            "face",
            "max",
            "man",
            "photo",
            "source_object",
            "veneer_object",
        ):
            nm = str(tg.get(ref_key, "") or "").strip()
            if not nm:
                object_refs[ref_key] = {"name": "", "exists": False}
                continue
            obj = bpy.data.objects.get(nm)
            object_refs[ref_key] = {
                "name": nm,
                "exists": bool(obj is not None),
                "type": str(obj.type) if obj else "",
            }

    stale_obj = p.get("veneer_staleness", {})
    stale = {"is_stale": False, "reasons": []}
    if isinstance(stale_obj, dict):
        stale = {
            "is_stale": bool(stale_obj.get("is_stale", False)),
            "reasons": stale_obj.get("reasons", [])
            if isinstance(stale_obj.get("reasons", []), list)
            else [],
        }

    warnings = []
    errors = []
    if not schema_ok:
        warnings.append("schema_version_mismatch")
    if missing_sections:
        warnings.append("missing_sections")
    if missing_fields:
        warnings.append("missing_fields")
    if stale.get("is_stale", False):
        warnings.append("veneer_state_stale")
    if isinstance(scene, bpy.types.Scene) and object_refs:
        unresolved = [
            k
            for k, v in object_refs.items()
            if not bool(v.get("exists", False)) and v.get("name", "")
        ]
        if unresolved:
            warnings.append("unresolved_object_refs")

    return {
        "schema_ok": bool(schema_ok),
        "schema_version_found": found_ver,
        "schema_version_expected": expected_ver,
        "missing_sections": missing_sections,
        "missing_fields": missing_fields,
        "object_refs": object_refs,
        "stale": stale,
        "warnings": warnings,
        "errors": errors,
    }


def _collect_live_veneer_staleness(scene, source, tooth_id):
    staleness = {
        "available": False,
        "source_name": "",
        "tooth_id": int(tooth_id),
        "is_stale": False,
        "reasons": [],
        "source_signature_saved": "",
        "source_signature_current": "",
        "input_checksum_saved": "",
        "input_checksum_current": "",
    }
    try:
        if source and source.type == "MESH":
            recipe = get_saved_veneer_recipe(source, tooth_id) or {}
            ven = _find_veneer_by_tooth_id(source, tooth_id)
            align_payload = _json_obj(
                scene.get("SMILE_NO_PREP_LAST_ALIGN", "{}"), default={}
            )
            sig_saved = str(
                recipe.get(
                    "source_signature",
                    ven.get("SMILE_VENEER_SOURCE_SIG", "") if ven else "",
                )
            )
            sig_curr = _mesh_signature(source)
            chk_saved = str(
                recipe.get(
                    "input_checksum",
                    ven.get(KEY_VENEER_INPUT_CHECKSUM, "") if ven else "",
                )
            )
            chk_curr = compute_input_checksum(
                source, recipe if isinstance(recipe, dict) else {}, align_payload
            )
            stale_sig = bool(sig_saved and sig_curr and sig_saved != sig_curr)
            stale_chk = bool(chk_saved and chk_curr and chk_saved != chk_curr)
            reasons = []
            if stale_sig:
                reasons.append("source_signature_changed")
            if stale_chk:
                reasons.append("input_checksum_changed")
            staleness.update(
                {
                    "available": True,
                    "source_name": str(source.name),
                    "is_stale": bool(stale_sig or stale_chk),
                    "reasons": reasons,
                    "source_signature_saved": sig_saved,
                    "source_signature_current": sig_curr,
                    "input_checksum_saved": chk_saved,
                    "input_checksum_current": chk_curr,
                }
            )
    except Exception:
        pass
    return staleness


def _build_support_bundle_json_payload(
    scene, p, active_obj, source, tooth_id, diag, frame, staleness
):
    return {
        "schema_version": 1,
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "context": {
            "scene_name": str(scene.name),
            "workflow_state": str(p.workflow_state),
            "design_step": int(p.design_step),
            "step_lock": bool(p.enforce_step_lock),
            "active_object": str(active_obj.name) if active_obj else "",
            "source_object": str(source.name) if source else "",
            "tooth_id": int(tooth_id),
        },
        "diagnostics": diag if isinstance(diag, dict) else {},
        "frame3d_summary": frame if isinstance(frame, dict) else {},
        "live_veneer_staleness": staleness if isinstance(staleness, dict) else {},
    }


def _build_support_bundle_markdown_text(
    scene, p, active_obj, source, tooth_id, diag, frame, staleness
):
    dmeta = (
        _json_obj(diag.get("_meta", {}), default={}) if isinstance(diag, dict) else {}
    )
    d_warn = (
        diag.get("warnings", [])
        if isinstance(diag, dict) and isinstance(diag.get("warnings", []), list)
        else []
    )
    d_err = (
        diag.get("errors", [])
        if isinstance(diag, dict) and isinstance(diag.get("errors", []), list)
        else []
    )
    d_miss_s = (
        diag.get("missing_sections", [])
        if isinstance(diag, dict) and isinstance(diag.get("missing_sections", []), list)
        else []
    )
    d_miss_f = (
        diag.get("missing_fields", [])
        if isinstance(diag, dict) and isinstance(diag.get("missing_fields", []), list)
        else []
    )
    d_stale = (
        diag.get("stale", {})
        if isinstance(diag, dict) and isinstance(diag.get("stale", {}), dict)
        else {}
    )

    f_rows = (
        frame.get("tooth_metrics", [])
        if isinstance(frame, dict) and isinstance(frame.get("tooth_metrics", []), list)
        else []
    )
    top_rows = []
    if f_rows:
        try:
            top_rows = sorted(
                f_rows,
                key=lambda r: (
                    float(r.get("move_mm", 0.0)) + float(r.get("rot_deg", 0.0))
                ),
                reverse=True,
            )[:5]
        except Exception:
            top_rows = f_rows[:5]

    lines = []
    lines.append("# Smile Support Bundle")
    lines.append("")
    lines.append("## Context")
    lines.append(f"- scene: `{scene.name}`")
    lines.append(f"- workflow_state: `{p.workflow_state}`")
    lines.append(f"- design_step: `{p.design_step}` lock=`{bool(p.enforce_step_lock)}`")
    lines.append(f"- active_object: `{active_obj.name if active_obj else ''}`")
    lines.append(f"- source_object: `{source.name if source else ''}`")
    lines.append(f"- tooth_id: `{tooth_id}`")
    lines.append("")
    lines.append("## Case Diagnostics")
    if isinstance(diag, dict) and diag:
        lines.append(
            f"- action/status: `{dmeta.get('action', '')}/{dmeta.get('status', '')}`"
        )
        lines.append(f"- timestamp: `{dmeta.get('timestamp_utc', '')}`")
        lines.append(
            f"- schema_ok: `{bool(diag.get('schema_ok', False))}` found=`{diag.get('schema_version_found', None)}` expected=`{diag.get('schema_version_expected', 1)}`"
        )
        lines.append(
            f"- missing_sections: `{', '.join([str(x) for x in d_miss_s[:8]])}`"
        )
        lines.append(f"- missing_fields: `{', '.join([str(x) for x in d_miss_f[:8]])}`")
        lines.append(f"- warnings: `{', '.join([str(x) for x in d_warn[:8]])}`")
        lines.append(f"- errors: `{', '.join([str(x) for x in d_err[:8]])}`")
        lines.append(
            f"- diag_stale: `{bool(d_stale.get('is_stale', False))}` reasons=`{', '.join([str(x) for x in (d_stale.get('reasons', []) if isinstance(d_stale.get('reasons', []), list) else [])[:6]])}`"
        )
    else:
        lines.append("- diagnostics: `none`")
    lines.append("")
    lines.append("## Frame3D Summary")
    if isinstance(frame, dict) and frame:
        lines.append(
            f"- mode/status: `{frame.get('mode', '')}/{frame.get('status', '')}`"
        )
        lines.append(f"- timestamp: `{frame.get('timestamp_utc', '')}`")
        lines.append(
            f"- moved_count: `{frame.get('moved_count', 0)}` avg_move_mm=`{float(frame.get('avg_move_mm', 0.0)):.3f}`"
        )
        lines.append(
            f"- rotated_count: `{frame.get('rotated_count', 0)}` avg_rot_deg=`{float(frame.get('avg_rot_deg', 0.0)):.3f}`"
        )
        lines.append(
            f"- clamp_counts: move=`{frame.get('move_clamped_count', 0)}` rot=`{frame.get('rot_clamped_count', 0)}`"
        )
        if top_rows:
            lines.append("- top_tooth_metrics:")
            for rec in top_rows:
                tid = rec.get("tooth_id", "")
                tnm = rec.get("tooth_name", "")
                mm = float(rec.get("move_mm", 0.0))
                deg = float(rec.get("rot_deg", 0.0))
                cm = bool(rec.get("move_clamped", False))
                cr = bool(rec.get("rot_clamped", False))
                lines.append(
                    f"  - `{tnm}` (T{tid}): move=`{mm:.3f}`mm rot=`{deg:.3f}`deg clamp(M/R)=`{cm}/{cr}`"
                )
    else:
        lines.append("- frame3d_summary: `none`")
    lines.append("")
    lines.append("## Live Veneer Staleness")
    lines.append(
        f"- available: `{staleness['available']}` source=`{staleness['source_name']}`"
    )
    lines.append(
        f"- is_stale: `{staleness['is_stale']}` reasons=`{', '.join([str(x) for x in staleness['reasons'][:6]])}`"
    )
    lines.append(
        f"- source_sig(saved/current): `{staleness['source_signature_saved']}` / `{staleness['source_signature_current']}`"
    )
    lines.append(
        f"- checksum(saved/current): `{staleness['input_checksum_saved']}` / `{staleness['input_checksum_current']}`"
    )

    return "\n".join(lines).strip() + "\n"


def get_margin_data(scene, tooth_obj, tooth_id=None):
    """
    Retrieve margin data from tooth_obj.data.
    Supports portability: data follows the mesh if appended/linked.
    """
    if not tooth_obj or not tooth_obj.data:
        return None

    suffix = f"_T{tooth_id}" if tooth_id else ""
    key = KEY_MARGIN_DATA_PREFIX + suffix  # Use specific ID key on data block

    if key in tooth_obj.data:
        import json

        try:
            data_str = tooth_obj.data[key]
            data = json.loads(data_str)
            if isinstance(data, dict):
                # Keep world-space control points synced to current mesh pose.
                _apply_margin_local_to_world(tooth_obj, data)
            return data
        except Exception:
            return None
    # Backward compatibility: older files stored unsuffixed key.
    if tooth_id:
        legacy_key = KEY_MARGIN_DATA_PREFIX
        if legacy_key in tooth_obj.data:
            import json

            try:
                data_str = tooth_obj.data[legacy_key]
                data = json.loads(data_str)
                if isinstance(data, dict):
                    _apply_margin_local_to_world(tooth_obj, data)
                    # Opportunistically migrate to T-specific key.
                    set_margin_data(scene, tooth_obj, dict(data), tooth_id=tooth_id)
                return data
            except Exception:
                return None

    return None


def _autodie_queue_count(scene):
    return len(_autodie_queue_read(scene))


def _recipe_key_for_tooth(tooth_id: int) -> str:
    return f"{KEY_VENEER_RECIPE_PREFIX}T{int(tooth_id)}"


# --- REVIEW/WORKSPACE OPERATORS ---
class SMILE_OT_apply_collection_visibility_now(bpy.types.Operator):
    """Apply collection visibility preset for the active workflow tab."""

    bl_idname = "smile.apply_collection_visibility_now"
    bl_label = "Apply Collection Visibility"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        _apply_workflow_collection_visibility(
            context.scene, p.workflow_state, context=context
        )
        self.report({"INFO"}, f"Applied visibility preset for {p.workflow_state}.")
        return {"FINISHED"}


class SMILE_OT_apply_review_visibility_preset(bpy.types.Operator):
    """Apply a Blender-local review workspace visibility preset."""

    bl_idname = "smile.apply_review_visibility_preset"
    bl_label = "Apply Review Visibility Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: bpy.props.EnumProperty(
        name="Preset",
        items=[
            ("ALL", "All", "Show all review layers"),
            ("ALIGN", "Align", "Focus on scan/alignment layers"),
            ("DESIGN", "Design", "Focus on planning/design layers"),
            ("VALIDATE", "Validate", "Focus on validation layers"),
            ("EXPORT", "Export", "Focus on export-ready layers"),
        ],
        default="VALIDATE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        preset_key = str(self.preset or "ALL").upper()
        vis_map = review_preset_visibility(preset_key)
        for col_name, should_show in vis_map.items():
            _set_collection_viewport_state(context, col_name, bool(should_show))
        p.review_workspace_preset = preset_key
        self.report({"INFO"}, f"Applied review preset: {preset_key}")
        return {"FINISHED"}


class SMILE_OT_export_present_snapshot(bpy.types.Operator):
    """Export the current 3D viewport as a local presentation still image."""

    bl_idname = "smile.export_present_snapshot"
    bl_label = "Export Present Snapshot"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")

    def invoke(self, context, event):
        scene = context.scene
        p = scene.smile_v2
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = build_local_present_snapshot_name(
            str(getattr(scene, "name", "scene") or "scene"),
            str(getattr(p, "workflow_state", "SETUP") or "SETUP"),
            str(getattr(p, "review_workspace_preset", "VALIDATE") or "VALIDATE"),
            stamp,
        )
        self.filepath = bpy.path.abspath(f"//{filename}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        target = str(self.filepath or "").strip()
        if not target:
            self.report({"ERROR"}, "Choose an output filepath.")
            return {"CANCELLED"}
        if not target.lower().endswith(".png"):
            target = target + ".png"

        scene = context.scene
        old_path = str(scene.render.filepath)
        old_format = str(scene.render.image_settings.file_format)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            scene.render.filepath = target
            scene.render.image_settings.file_format = "PNG"
            bpy.ops.render.opengl(write_still=True, view_context=True)
        except Exception as e:
            self.report({"ERROR"}, f"Snapshot export failed: {e}")
            return {"CANCELLED"}
        finally:
            scene.render.filepath = old_path
            scene.render.image_settings.file_format = old_format

        self.report({"INFO"}, f"Present snapshot exported: {target}")
        return {"FINISHED"}


class SMILE_OT_add_review_note(bpy.types.Operator):
    """Add a lightweight review note object at the 3D cursor."""

    bl_idname = "smile.add_review_note"
    bl_label = "Add Review Note"
    bl_options = {"REGISTER", "UNDO"}

    text: bpy.props.StringProperty(name="Text", default="")

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        note_text = str(self.text or getattr(p, "review_note_text", "") or "").strip()
        if not note_text:
            self.report({"ERROR"}, "Enter review note text first.")
            return {"CANCELLED"}

        tid = int(getattr(p, "target_tooth_id", 0) or 0)
        name = build_review_artifact_name("note", note_text, tid)
        curve_data = bpy.data.curves.new(f"{name}_Data", type="FONT")
        curve_data.body = note_text
        curve_data.size = 0.003
        obj = bpy.data.objects.new(name, curve_data)
        obj.location = context.scene.cursor.location.copy()
        obj["SMILE_REVIEW_KIND"] = "NOTE"
        obj["SMILE_REVIEW_TEXT"] = note_text
        link_to_collection(obj, ensure_collection(COL_PREVIEW))
        try:
            obj.show_in_front = True
        except Exception:
            pass
        self.report({"INFO"}, f"Review note added: {name}")
        return {"FINISHED"}


class SMILE_OT_create_review_section_plane(bpy.types.Operator):
    """Create a visible section-plane scaffold in the preview collection."""

    bl_idname = "smile.create_review_section_plane"
    bl_label = "Create Review Section Plane"
    bl_options = {"REGISTER", "UNDO"}

    orientation: bpy.props.EnumProperty(
        name="Orientation",
        items=[
            ("AXIAL", "Axial", "Horizontal section plane"),
            ("CORONAL", "Coronal", "Front/back section plane"),
            ("SAGITTAL", "Sagittal", "Left/right section plane"),
        ],
        default="CORONAL",
    )

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        orient = str(self.orientation or "CORONAL").upper()
        tid = int(getattr(p, "target_tooth_id", 0) or 0)
        name = build_review_artifact_name("section", orient, tid)

        size_world = max(
            0.001, float(getattr(p, "review_section_plane_size_mm", 24.0)) / 1000.0
        )
        half = size_world / 2.0
        mesh = bpy.data.meshes.new(f"{name}_Data")
        mesh.from_pydata(
            [
                (-half, -half, 0.0),
                (half, -half, 0.0),
                (half, half, 0.0),
                (-half, half, 0.0),
            ],
            [],
            [(0, 1, 2, 3)],
        )
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = context.scene.cursor.location.copy()
        if orient == "CORONAL":
            obj.rotation_euler[0] = math.radians(90.0)
        elif orient == "SAGITTAL":
            obj.rotation_euler[1] = math.radians(90.0)
        obj.display_type = "WIRE"
        obj.show_wire = True
        obj["SMILE_REVIEW_KIND"] = "SECTION"
        obj["SMILE_REVIEW_ORIENTATION"] = orient
        obj["SMILE_REVIEW_AXIS"] = review_section_axis_vector(orient)
        link_to_collection(obj, ensure_collection(COL_PREVIEW))
        _apply_review_section_style(
            obj, str(getattr(p, "review_section_style", "CLINICAL") or "CLINICAL")
        )
        self.report({"INFO"}, f"Review section plane added: {name}")
        return {"FINISHED"}


class SMILE_OT_apply_review_section_style(bpy.types.Operator):
    """Apply the configured review section style to the active section plane."""

    bl_idname = "smile.apply_review_section_style"
    bl_label = "Apply Review Section Style"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or str(obj.get("SMILE_REVIEW_KIND", "")) != "SECTION":
            self.report({"ERROR"}, "Select a review section plane first.")
            return {"CANCELLED"}
        style_key = str(
            getattr(context.scene.smile_v2, "review_section_style", "CLINICAL")
            or "CLINICAL"
        )
        if not _apply_review_section_style(obj, style_key):
            self.report({"ERROR"}, "Could not apply review section style.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Applied review section style: {style_key}")
        return {"FINISHED"}


class SMILE_OT_nudge_review_section_plane(bpy.types.Operator):
    """Move the active review section plane along its local normal."""

    bl_idname = "smile.nudge_review_section_plane"
    bl_label = "Nudge Review Section Plane"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.EnumProperty(
        name="Direction",
        items=[
            ("BACKWARD", "Backward", "Move opposite the section normal"),
            ("FORWARD", "Forward", "Move along the section normal"),
        ],
        default="FORWARD",
    )

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or str(obj.get("SMILE_REVIEW_KIND", "")) != "SECTION":
            self.report({"ERROR"}, "Select a review section plane first.")
            return {"CANCELLED"}

        step_mm = float(
            getattr(context.scene.smile_v2, "review_section_step_mm", 0.5) or 0.5
        )
        sign = 1.0 if str(self.direction or "FORWARD").upper() == "FORWARD" else -1.0
        normal = obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
        if normal.length < 1e-8:
            self.report({"ERROR"}, "Section plane normal is invalid.")
            return {"CANCELLED"}
        obj.location += normal.normalized() * ((step_mm / 1000.0) * sign)
        self.report(
            {"INFO"},
            f"Section plane nudged {self.direction.lower()} by {step_mm:.2f} mm",
        )
        return {"FINISHED"}


class SMILE_OT_focus_active_review_artifact(bpy.types.Operator):
    """Select and frame the active review note or section artifact."""

    bl_idname = "smile.focus_active_review_artifact"
    bl_label = "Focus Active Review Artifact"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or str(obj.get("SMILE_REVIEW_KIND", "")) not in {"NOTE", "SECTION"}:
            self.report({"ERROR"}, "Select a review note or section plane first.")
            return {"CANCELLED"}
        focus_object(context, obj)
        try:
            bpy.ops.view3d.view_selected(use_all_regions=False)
        except Exception:
            pass
        self.report({"INFO"}, f"Focused review artifact: {obj.name}")
        return {"FINISHED"}


class SMILE_OT_annotate_active_review_section(bpy.types.Operator):
    """Create a review note showing the active section plane offset from the 3D cursor."""

    bl_idname = "smile.annotate_active_review_section"
    bl_label = "Annotate Active Review Section"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or str(obj.get("SMILE_REVIEW_KIND", "")) != "SECTION":
            self.report({"ERROR"}, "Select a review section plane first.")
            return {"CANCELLED"}

        orientation = str(
            obj.get("SMILE_REVIEW_ORIENTATION", "CORONAL") or "CORONAL"
        ).upper()
        axis = tuple(
            obj.get("SMILE_REVIEW_AXIS", review_section_axis_vector(orientation))
        )
        offset_mm = calculate_review_section_offset_mm(
            tuple(context.scene.cursor.location),
            tuple(obj.location),
            axis,
        )
        note_text = f"{orientation.title()} {offset_mm:+.2f} mm"
        tid = int(getattr(context.scene.smile_v2, "target_tooth_id", 0) or 0)
        name = build_review_artifact_name("note", note_text, tid)
        curve_data = bpy.data.curves.new(f"{name}_Data", type="FONT")
        curve_data.body = note_text
        curve_data.size = 0.003
        note_obj = bpy.data.objects.new(name, curve_data)
        note_obj.location = obj.location.copy()
        note_obj["SMILE_REVIEW_KIND"] = "NOTE"
        note_obj["SMILE_REVIEW_TEXT"] = note_text
        note_obj["SMILE_REVIEW_SOURCE"] = obj.name
        link_to_collection(note_obj, ensure_collection(COL_PREVIEW))
        try:
            note_obj.show_in_front = True
        except Exception:
            pass
        self.report({"INFO"}, f"Annotated section offset: {note_text}")
        return {"FINISHED"}


class SMILE_OT_set_workflow_state(bpy.types.Operator):
    """Switch workflow tab explicitly."""

    bl_idname = "smile.set_workflow_state"
    bl_label = "Switch Workflow Tab"
    bl_options = {"REGISTER", "UNDO"}

    target_state: bpy.props.EnumProperty(
        name="Target Workflow State",
        items=[
            ("SETUP", "1. Setup", ""),
            ("ANALYSIS", "2. Analysis", ""),
            ("MOCKUP", "3. Mockup", ""),
            ("PRODUCTION", "4. Production", ""),
            ("NO_PREP", "5. No-Prep", ""),
            ("VENEER_IMPORT", "6. Veneer Lab", ""),
        ],
        default="SETUP",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        p.workflow_state = str(self.target_state or "SETUP")
        _sync_workflow_progress(p)
        if bool(getattr(p, "auto_manage_collection_visibility", False)):
            _apply_workflow_collection_visibility(
                context.scene, p.workflow_state, context=context
            )
        self.report({"INFO"}, f"Switched to {p.workflow_state}.")
        return {"FINISHED"}


# --- CASE REPORT OPERATORS ---
class SMILE_OT_export_case_report(bpy.types.Operator):
    """Export a consolidated case report JSON (veneer + frame3d + workflow context)."""

    bl_idname = "smile.export_case_report"
    bl_label = "Export Case Report"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")

    def invoke(self, context, event):
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.filepath = bpy.path.abspath(f"//smile_case_report_{stamp}.json")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        active_obj = context.view_layer.objects.active
        source = resolve_source_obj(active_obj)
        target_id = _int_or_default(
            (
                active_obj.get(
                    "SMILE_VENEER_TOOTH_ID", p.ven_target_tooth_id or p.target_tooth_id
                )
                if active_obj
                else (p.ven_target_tooth_id or p.target_tooth_id)
            ),
            p.ven_target_tooth_id or p.target_tooth_id,
        )

        veneer = None
        if source and source.type == "MESH":
            veneer = _find_veneer_by_tooth_id(source, target_id)
        if (
            not veneer
            and active_obj
            and active_obj.type == "MESH"
            and active_obj.name.startswith("VENEER_")
        ):
            veneer = active_obj

        recipe = None
        if source and source.type == "MESH":
            recipe = get_saved_veneer_recipe(source, target_id)
        if not recipe and veneer:
            recipe = _json_obj(veneer.get("SMILE_VENEER_RECIPE", "{}"), default={})
        if not isinstance(recipe, dict):
            recipe = {}

        validation = (
            _json_obj(veneer.get("SMILE_VENEER_VALIDATION", "{}"), default={})
            if veneer
            else {}
        )
        frame3d_sum = _get_frame3d_apply_summary(scene)
        align_state = _json_obj(scene.get("SMILE_NO_PREP_LAST_ALIGN", "{}"), default={})

        current_sig = (
            _mesh_signature(source) if source and source.type == "MESH" else ""
        )
        saved_sig = str(
            recipe.get(
                "source_signature",
                veneer.get("SMILE_VENEER_SOURCE_SIG", "") if veneer else "",
            )
        )
        saved_checksum = str(
            recipe.get(
                "input_checksum",
                veneer.get(KEY_VENEER_INPUT_CHECKSUM, "") if veneer else "",
            )
        )
        current_checksum = (
            compute_input_checksum(source, recipe, align_state)
            if source and source.type == "MESH"
            else ""
        )
        stale_sig = bool(saved_sig and current_sig and saved_sig != current_sig)
        stale_checksum = bool(
            saved_checksum and current_checksum and saved_checksum != current_checksum
        )

        payload = {
            "report_version": 1,
            "exported_utc": datetime.utcnow().isoformat() + "Z",
            "scene_name": str(scene.name),
            "active_object": str(active_obj.name) if active_obj else "",
            "targets": {
                "face": str(p.face_target),
                "max": str(p.max_target),
                "man": str(p.man_target),
                "photo": str(p.photo_target),
                "source_object": str(source.name) if source else "",
                "target_tooth_id": int(target_id),
                "target_tooth_notation": "UNIVERSAL",
                "target_tooth_fdi_id": int(universal_to_fdi(int(target_id)) or 0),
                "veneer_object": str(veneer.name) if veneer else "",
            },
            "workflow": {
                "state": str(p.workflow_state),
                "design_step": str(p.design_step),
                "enforce_step_lock": bool(p.enforce_step_lock),
                "step1_done": bool(p.step1_done),
                "step2_done": bool(p.step2_done),
                "step3_done": bool(p.step3_done),
                "step4_done": bool(p.step4_done),
                "step5_done": bool(p.step5_done),
                "step6_done": bool(p.step6_done),
            },
            "veneer_recipe": recipe,
            "veneer_validation": validation if isinstance(validation, dict) else {},
            "veneer_staleness": {
                "source_signature_saved": saved_sig,
                "source_signature_current": current_sig,
                "input_checksum_saved": saved_checksum,
                "input_checksum_current": current_checksum,
                "is_stale": bool(stale_sig or stale_checksum),
                "reasons": [
                    r
                    for r in [
                        "source_signature_changed" if stale_sig else "",
                        "input_checksum_changed" if stale_checksum else "",
                    ]
                    if r
                ],
            },
            "frame3d_last_apply": frame3d_sum if isinstance(frame3d_sum, dict) else {},
            "alignment_state": align_state if isinstance(align_state, dict) else {},
            "settings_snapshot": {
                "ven_mode": str(p.ven_mode),
                "ven_min_thickness_mm": float(p.ven_min_thickness_mm),
                "ven_max_thickness_mm": float(p.ven_max_thickness_mm),
                "ven_spacer_internal_mm": float(p.ven_spacer_internal_mm),
                "ven_spacer_margin_mm": float(p.ven_spacer_margin_mm),
                "ven_border_taper_mm": float(p.ven_border_taper_mm),
                "ven_border_seal_mm": float(p.ven_border_seal_mm),
                "ven_facial_cutback_enabled": bool(p.ven_facial_cutback_enabled),
                "ven_facial_coverage": float(p.ven_facial_coverage),
                "ven_facial_lingual_pad_mm": float(p.ven_facial_lingual_pad_mm),
                "ven_insertion_axis_mode": str(p.ven_insertion_axis_mode),
                "ven_undercut_allow_deg": float(p.ven_undercut_allow_deg),
                "ven_boolean_solver": str(p.ven_boolean_solver),
                "ven_occlusion_threshold_mm": float(p.ven_occlusion_threshold_mm),
                "ven_validation_sample_limit": int(p.ven_validation_sample_limit),
                "sf_curve_source": str(getattr(p, "sf_curve_source", "AUTO")),
                "sf_selected_curve_name": str(getattr(p, "sf_selected_curve_name", "")),
                "sf_apply3d_preview_only": bool(
                    getattr(p, "sf_apply3d_preview_only", False)
                ),
                "sf_apply3d_height_strength": float(
                    getattr(p, "sf_apply3d_height_strength", 0.0)
                ),
                "sf_apply3d_xy_strength": float(
                    getattr(p, "sf_apply3d_xy_strength", 0.0)
                ),
                "sf_apply3d_rotate_enabled": bool(
                    getattr(p, "sf_apply3d_rotate_enabled", False)
                ),
                "sf_apply3d_rotate_strength": float(
                    getattr(p, "sf_apply3d_rotate_strength", 0.0)
                ),
                "sf_apply3d_max_rotate_deg": float(
                    getattr(p, "sf_apply3d_max_rotate_deg", 0.0)
                ),
                "sf_apply3d_max_move_mm": float(
                    getattr(p, "sf_apply3d_max_move_mm", 0.0)
                ),
            },
        }
        diag_payload = _case_report_diagnostics(payload, scene)
        payload["diagnostics"] = diag_payload

        target = str(self.filepath or "").strip()
        if not target:
            self.report({"ERROR"}, "Choose an output filepath.")
            return {"CANCELLED"}
        if not target.lower().endswith(".json"):
            target = target + ".json"

        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
        except Exception as e:
            _store_case_report_diagnostics(
                scene, diag_payload, action="export", status="error", filepath=target
            )
            self.report({"ERROR"}, f"Case report export failed: {e}")
            return {"CANCELLED"}

        _store_case_report_diagnostics(
            scene, diag_payload, action="export", status="ok", filepath=target
        )
        self.report({"INFO"}, f"Case report exported: {target}")
        return {"FINISHED"}


class SMILE_OT_import_case_report(bpy.types.Operator):
    """Import a consolidated case report JSON and restore key review state."""

    bl_idname = "smile.import_case_report"
    bl_label = "Import Case Report"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        target = str(self.filepath or "").strip()
        if not target:
            self.report({"ERROR"}, "Choose a report JSON file.")
            return {"CANCELLED"}

        try:
            with open(target, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to read report: {e}")
            return {"CANCELLED"}

        if not isinstance(payload, dict):
            self.report({"ERROR"}, "Invalid report format.")
            return {"CANCELLED"}

        applied = 0
        warnings = []
        diag = _case_report_diagnostics(payload, scene)
        strict_mode = bool(getattr(p, "sf_case_import_strict", False))
        hard_fail_reasons = []
        if not bool(diag.get("schema_ok", False)):
            hard_fail_reasons.append("schema_version_mismatch")
        critical_sections = {
            "report_version",
            "workflow",
            "targets",
            "settings_snapshot",
        }
        missing_sections = diag.get("missing_sections", [])
        if isinstance(missing_sections, list):
            crit_missing = [s for s in missing_sections if s in critical_sections]
            if crit_missing:
                hard_fail_reasons.append(
                    "missing_critical_sections:" + ",".join(crit_missing[:6])
                )
        if strict_mode and hard_fail_reasons:
            _store_case_report_diagnostics(
                scene, diag, action="import", status="blocked_strict", filepath=target
            )
            self.report(
                {"ERROR"}, f"Strict import blocked: {'; '.join(hard_fail_reasons)}"
            )
            return {"CANCELLED"}

        if not bool(diag.get("schema_ok", False)):
            warnings.append("schema_version_mismatch")
        ms = diag.get("missing_sections", [])
        if isinstance(ms, list) and ms:
            warnings.append("missing_sections:" + ",".join(ms[:6]))
        mf = diag.get("missing_fields", [])
        if isinstance(mf, list) and mf:
            warnings.append("missing_fields:" + ",".join(mf[:6]))
        if bool(diag.get("stale", {}).get("is_stale", False)):
            reasons = diag.get("stale", {}).get("reasons", [])
            if isinstance(reasons, list) and reasons:
                warnings.append("stale:" + ",".join([str(r) for r in reasons[:4]]))
            else:
                warnings.append("stale:true")
        orefs = diag.get("object_refs", {})
        if isinstance(orefs, dict):
            unresolved = [
                k
                for k, v in orefs.items()
                if isinstance(v, dict)
                and v.get("name")
                and not bool(v.get("exists", False))
            ]
            if unresolved:
                warnings.append("unresolved_refs:" + ",".join(unresolved[:6]))

        def _set_prop(attr, value, cast=None):
            nonlocal applied
            if value is None or not hasattr(p, attr):
                return
            try:
                setattr(p, attr, cast(value) if cast else value)
                applied += 1
            except Exception:
                warnings.append(f"prop:{attr}")

        workflow = payload.get("workflow", {})
        if isinstance(workflow, dict):
            _set_prop("workflow_state", workflow.get("state"), str)
            _set_prop("design_step", workflow.get("design_step"), str)
            _set_prop("enforce_step_lock", workflow.get("enforce_step_lock"), bool)
            _set_prop("step1_done", workflow.get("step1_done"), bool)
            _set_prop("step2_done", workflow.get("step2_done"), bool)
            _set_prop("step3_done", workflow.get("step3_done"), bool)
            _set_prop("step4_done", workflow.get("step4_done"), bool)
            _set_prop("step5_done", workflow.get("step5_done"), bool)
            _set_prop("step6_done", workflow.get("step6_done"), bool)
            wf_sync = _sync_workflow_progress(p)
            if wf_sync.get("changed", False):
                applied += 1

        targets = payload.get("targets", {})
        if isinstance(targets, dict):
            _set_prop("face_target", targets.get("face"), str)
            _set_prop("max_target", targets.get("max"), str)
            _set_prop("man_target", targets.get("man"), str)
            _set_prop("photo_target", targets.get("photo"), str)
            if targets.get("target_tooth_id") is not None:
                notation = str(
                    targets.get("target_tooth_notation", "AUTO") or "AUTO"
                ).upper()
                raw_tid = targets.get("target_tooth_id")
                norm_tid = _normalize_tooth_id_universal(
                    raw_tid, notation_hint=notation
                )
                if norm_tid is None:
                    # Backward-compatible fallback for older report payloads.
                    norm_tid = _int_or_default(raw_tid, 0)
                if norm_tid > 0:
                    _set_prop("ven_target_tooth_id", norm_tid, int)

        snap = payload.get("settings_snapshot", {})
        if isinstance(snap, dict):
            _set_prop("ven_mode", snap.get("ven_mode"), str)
            _set_prop("ven_min_thickness_mm", snap.get("ven_min_thickness_mm"), float)
            _set_prop("ven_max_thickness_mm", snap.get("ven_max_thickness_mm"), float)
            _set_prop(
                "ven_spacer_internal_mm", snap.get("ven_spacer_internal_mm"), float
            )
            _set_prop("ven_spacer_margin_mm", snap.get("ven_spacer_margin_mm"), float)
            _set_prop("ven_border_taper_mm", snap.get("ven_border_taper_mm"), float)
            _set_prop("ven_border_seal_mm", snap.get("ven_border_seal_mm"), float)
            _set_prop(
                "ven_facial_cutback_enabled",
                snap.get("ven_facial_cutback_enabled"),
                bool,
            )
            _set_prop("ven_facial_coverage", snap.get("ven_facial_coverage"), float)
            _set_prop(
                "ven_facial_lingual_pad_mm",
                snap.get("ven_facial_lingual_pad_mm"),
                float,
            )
            _set_prop(
                "ven_insertion_axis_mode", snap.get("ven_insertion_axis_mode"), str
            )
            _set_prop(
                "ven_undercut_allow_deg", snap.get("ven_undercut_allow_deg"), float
            )
            _set_prop("ven_boolean_solver", snap.get("ven_boolean_solver"), str)
            _set_prop(
                "ven_occlusion_threshold_mm",
                snap.get("ven_occlusion_threshold_mm"),
                float,
            )
            _set_prop(
                "ven_validation_sample_limit",
                snap.get("ven_validation_sample_limit"),
                int,
            )
            _set_prop("sf_curve_source", snap.get("sf_curve_source"), str)
            _set_prop("sf_selected_curve_name", snap.get("sf_selected_curve_name"), str)
            _set_prop(
                "sf_apply3d_preview_only", snap.get("sf_apply3d_preview_only"), bool
            )
            _set_prop(
                "sf_apply3d_height_strength",
                snap.get("sf_apply3d_height_strength"),
                float,
            )
            _set_prop(
                "sf_apply3d_xy_strength", snap.get("sf_apply3d_xy_strength"), float
            )
            _set_prop(
                "sf_apply3d_rotate_enabled", snap.get("sf_apply3d_rotate_enabled"), bool
            )
            _set_prop(
                "sf_apply3d_rotate_strength",
                snap.get("sf_apply3d_rotate_strength"),
                float,
            )
            _set_prop(
                "sf_apply3d_max_rotate_deg",
                snap.get("sf_apply3d_max_rotate_deg"),
                float,
            )
            _set_prop(
                "sf_apply3d_max_move_mm", snap.get("sf_apply3d_max_move_mm"), float
            )

        frame3d = payload.get("frame3d_last_apply", {})
        if isinstance(frame3d, dict) and frame3d:
            frame_copy = dict(frame3d)
            frame_copy["imported_utc"] = datetime.utcnow().isoformat() + "Z"
            scene[KEY_FRAME3D_LAST_APPLY_JSON] = json.dumps(
                frame_copy, sort_keys=True, separators=(",", ":")
            )
            scene[KEY_FRAME3D_LAST_APPLY_TS] = str(frame_copy.get("timestamp_utc", ""))
            applied += 1

        align_state = payload.get("alignment_state", {})
        if isinstance(align_state, dict) and align_state:
            scene["SMILE_NO_PREP_LAST_ALIGN"] = json.dumps(align_state, sort_keys=True)
            sv = align_state.get("state_version")
            if sv is not None:
                try:
                    scene[KEY_NO_PREP_ALIGN_STATE_VER] = int(sv)
                except Exception:
                    pass
            p.no_prep_camera_calibrated = True
            applied += 1

        recipe = payload.get("veneer_recipe", {})
        if isinstance(recipe, dict) and recipe:
            src_name = ""
            if isinstance(targets, dict):
                src_name = str(targets.get("source_object", "")).strip()
            if not src_name:
                src_name = str(recipe.get("source_object", "")).strip()
            tid_raw = recipe.get(
                "ven_target_tooth_id",
                targets.get(
                    "target_tooth_id",
                    p.ven_target_tooth_id
                    if isinstance(targets, dict)
                    else p.ven_target_tooth_id,
                ),
            )
            notation = str(
                targets.get("target_tooth_notation", "AUTO")
                if isinstance(targets, dict)
                else "AUTO"
            ).upper()
            tid_norm = _normalize_tooth_id_universal(tid_raw, notation_hint=notation)
            tid = (
                int(tid_norm)
                if tid_norm is not None
                else _int_or_default(tid_raw, p.ven_target_tooth_id)
            )
            src_obj = bpy.data.objects.get(src_name) if src_name else None
            if src_obj and src_obj.type == "MESH" and src_obj.data and tid > 0:
                try:
                    src_obj.data[_recipe_key_for_tooth(int(tid))] = json.dumps(
                        recipe, sort_keys=True
                    )
                    applied += 1
                except Exception:
                    warnings.append("recipe_bind_failed")

            ven_obj_name = (
                str(targets.get("veneer_object", "")).strip()
                if isinstance(targets, dict)
                else ""
            )
            ven_obj = bpy.data.objects.get(ven_obj_name) if ven_obj_name else None
            if ven_obj and ven_obj.type == "MESH":
                try:
                    ven_obj["SMILE_VENEER_RECIPE"] = json.dumps(recipe, sort_keys=True)
                    val = payload.get("veneer_validation", {})
                    if isinstance(val, dict) and val:
                        ven_obj["SMILE_VENEER_VALIDATION"] = json.dumps(
                            val, sort_keys=True
                        )
                    applied += 1
                except Exception:
                    warnings.append("veneer_bind_failed")

        if warnings:
            _store_case_report_diagnostics(
                scene, diag, action="import", status="warning", filepath=target
            )
            self.report(
                {"WARNING"},
                f"Case report imported with warnings: {', '.join(warnings[:5])}",
            )
        else:
            _store_case_report_diagnostics(
                scene, diag, action="import", status="ok", filepath=target
            )
            self.report({"INFO"}, f"Case report imported. Applied updates: {applied}")
        return {"FINISHED"}


class SMILE_OT_case_report_copy_diagnostics(bpy.types.Operator):
    """Copy current case-report diagnostics payload to clipboard."""

    bl_idname = "smile.case_report_copy_diagnostics"
    bl_label = "Copy Diagnostics"
    bl_options = {"REGISTER"}

    pretty: bpy.props.BoolProperty(
        name="Pretty JSON",
        default=True,
        description="Format copied diagnostics with indentation",
    )

    def execute(self, context):
        scene = context.scene
        diag = _get_case_report_diagnostics(scene)
        if not isinstance(diag, dict) or not diag:
            self.report({"ERROR"}, "No diagnostics available to copy.")
            return {"CANCELLED"}
        try:
            txt = (
                json.dumps(diag, indent=2, sort_keys=True)
                if bool(self.pretty)
                else json.dumps(diag, sort_keys=True, separators=(",", ":"))
            )
            context.window_manager.clipboard = txt
        except Exception as e:
            self.report({"ERROR"}, f"Clipboard copy failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Copied diagnostics to clipboard ({len(txt)} chars).")
        return {"FINISHED"}


class SMILE_OT_case_report_copy_support_bundle(bpy.types.Operator):
    """Copy compact markdown support bundle (diagnostics + frame3d + staleness)."""

    bl_idname = "smile.case_report_copy_support_bundle"
    bl_label = "Copy Support Bundle"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        active_obj = context.view_layer.objects.active
        source = resolve_source_obj(active_obj)
        tooth_id = _int_or_default(
            (
                active_obj.get(
                    "SMILE_VENEER_TOOTH_ID", p.ven_target_tooth_id or p.target_tooth_id
                )
                if active_obj
                else (p.ven_target_tooth_id or p.target_tooth_id)
            ),
            p.ven_target_tooth_id or p.target_tooth_id,
        )
        diag = _get_case_report_diagnostics(scene)
        frame = _get_frame3d_apply_summary(scene)
        staleness = _collect_live_veneer_staleness(scene, source, tooth_id)

        txt = _build_support_bundle_markdown_text(
            scene, p, active_obj, source, tooth_id, diag, frame, staleness
        )
        try:
            context.window_manager.clipboard = txt
        except Exception as e:
            self.report({"ERROR"}, f"Clipboard copy failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Copied support bundle to clipboard ({len(txt)} chars).")
        return {"FINISHED"}


class SMILE_OT_case_report_copy_support_bundle_json(bpy.types.Operator):
    """Copy machine-readable JSON support bundle (diagnostics + frame3d + staleness)."""

    bl_idname = "smile.case_report_copy_support_bundle_json"
    bl_label = "Copy Bundle JSON"
    bl_options = {"REGISTER"}

    pretty: bpy.props.BoolProperty(
        name="Pretty JSON",
        default=True,
        description="Format copied support bundle JSON with indentation",
    )

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        active_obj = context.view_layer.objects.active
        source = resolve_source_obj(active_obj)
        tooth_id = _int_or_default(
            (
                active_obj.get(
                    "SMILE_VENEER_TOOTH_ID", p.ven_target_tooth_id or p.target_tooth_id
                )
                if active_obj
                else (p.ven_target_tooth_id or p.target_tooth_id)
            ),
            p.ven_target_tooth_id or p.target_tooth_id,
        )
        diag = _get_case_report_diagnostics(scene)
        frame = _get_frame3d_apply_summary(scene)

        staleness = _collect_live_veneer_staleness(scene, source, tooth_id)

        payload = _build_support_bundle_json_payload(
            scene, p, active_obj, source, tooth_id, diag, frame, staleness
        )

        try:
            txt = (
                json.dumps(payload, indent=2, sort_keys=True)
                if bool(self.pretty)
                else json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )
            context.window_manager.clipboard = txt
        except Exception as e:
            self.report({"ERROR"}, f"Clipboard copy failed: {e}")
            return {"CANCELLED"}

        self.report(
            {"INFO"}, f"Copied support bundle JSON to clipboard ({len(txt)} chars)."
        )
        return {"FINISHED"}


class SMILE_OT_case_report_export_support_bundle(bpy.types.Operator):
    """Export support bundle as markdown or JSON file."""

    bl_idname = "smile.case_report_export_support_bundle"
    bl_label = "Export Support Bundle"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")
    bundle_format: bpy.props.EnumProperty(
        name="Bundle Format",
        items=[
            ("MARKDOWN", "Markdown", "Export markdown support bundle (.md)"),
            ("JSON", "JSON", "Export machine-readable support bundle (.json)"),
        ],
        default="MARKDOWN",
    )
    pretty_json: bpy.props.BoolProperty(
        name="Pretty JSON",
        default=True,
        description="Pretty-print JSON support bundle output",
    )

    def invoke(self, context, event):
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        ext = "md" if self.bundle_format == "MARKDOWN" else "json"
        self.filepath = bpy.path.abspath(f"//smile_support_bundle_{stamp}.{ext}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        active_obj = context.view_layer.objects.active
        source = resolve_source_obj(active_obj)
        tooth_id = _int_or_default(
            (
                active_obj.get(
                    "SMILE_VENEER_TOOTH_ID", p.ven_target_tooth_id or p.target_tooth_id
                )
                if active_obj
                else (p.ven_target_tooth_id or p.target_tooth_id)
            ),
            p.ven_target_tooth_id or p.target_tooth_id,
        )
        diag = _get_case_report_diagnostics(scene)
        frame = _get_frame3d_apply_summary(scene)
        staleness = _collect_live_veneer_staleness(scene, source, tooth_id)

        target = str(self.filepath or "").strip()
        if not target:
            self.report({"ERROR"}, "Choose an output filepath.")
            return {"CANCELLED"}

        is_md = self.bundle_format == "MARKDOWN"
        want_ext = ".md" if is_md else ".json"
        if not target.lower().endswith(want_ext):
            target = target + want_ext

        try:
            os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
            if is_md:
                txt = _build_support_bundle_markdown_text(
                    scene, p, active_obj, source, tooth_id, diag, frame, staleness
                )
                with open(target, "w", encoding="utf-8") as f:
                    f.write(txt)
            else:
                payload = _build_support_bundle_json_payload(
                    scene, p, active_obj, source, tooth_id, diag, frame, staleness
                )
                with open(target, "w", encoding="utf-8") as f:
                    if bool(self.pretty_json):
                        json.dump(payload, f, indent=2, sort_keys=True)
                    else:
                        json.dump(payload, f, sort_keys=True, separators=(",", ":"))
        except Exception as e:
            self.report({"ERROR"}, f"Support bundle export failed: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Support bundle exported: {target}")
        return {"FINISHED"}


class SMILE_OT_case_report_export_support_bundle_pair(bpy.types.Operator):
    """Export both markdown and JSON support bundles using one base filepath."""

    bl_idname = "smile.case_report_export_support_bundle_pair"
    bl_label = "Export Support Bundle Pair"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")
    pretty_json: bpy.props.BoolProperty(
        name="Pretty JSON", default=True, description="Pretty-print JSON bundle output"
    )

    def invoke(self, context, event):
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.filepath = bpy.path.abspath(f"//smile_support_bundle_{stamp}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        active_obj = context.view_layer.objects.active
        source = resolve_source_obj(active_obj)
        tooth_id = _int_or_default(
            (
                active_obj.get(
                    "SMILE_VENEER_TOOTH_ID", p.ven_target_tooth_id or p.target_tooth_id
                )
                if active_obj
                else (p.ven_target_tooth_id or p.target_tooth_id)
            ),
            p.ven_target_tooth_id or p.target_tooth_id,
        )
        diag = _get_case_report_diagnostics(scene)
        frame = _get_frame3d_apply_summary(scene)
        staleness = _collect_live_veneer_staleness(scene, source, tooth_id)

        target = str(self.filepath or "").strip()
        if not target:
            self.report({"ERROR"}, "Choose an output filepath base.")
            return {"CANCELLED"}

        root, ext = os.path.splitext(target)
        base = root if ext.lower() in {".md", ".json"} else target
        md_target = base + ".md"
        json_target = base + ".json"

        try:
            os.makedirs(os.path.dirname(os.path.abspath(base)), exist_ok=True)
            txt = _build_support_bundle_markdown_text(
                scene, p, active_obj, source, tooth_id, diag, frame, staleness
            )
            with open(md_target, "w", encoding="utf-8") as f:
                f.write(txt)

            payload = _build_support_bundle_json_payload(
                scene, p, active_obj, source, tooth_id, diag, frame, staleness
            )
            with open(json_target, "w", encoding="utf-8") as f:
                if bool(self.pretty_json):
                    json.dump(payload, f, indent=2, sort_keys=True)
                else:
                    json.dump(payload, f, sort_keys=True, separators=(",", ":"))
        except Exception as e:
            self.report({"ERROR"}, f"Support bundle pair export failed: {e}")
            return {"CANCELLED"}

        self.report(
            {"INFO"}, f"Support bundle pair exported: {md_target} + {json_target}"
        )
        return {"FINISHED"}


# --- WORKSPACE SETUP & REGISTRATION HELPERS ---
def _set_preferred_matcap(shading, preferred_name="clay_brown.exr"):
    """Set a preferred MatCap, then gracefully fall back to any available MatCap."""
    try:
        shading.studio_light = preferred_name
        return preferred_name
    except Exception:
        pass
    try:
        prefs = getattr(bpy.context, "preferences", None)
        lights = getattr(prefs, "studio_lights", None)
        if lights:
            for light in lights:
                if getattr(light, "type", "") == "MATCAP":
                    name = str(getattr(light, "name", "") or "")
                    if name:
                        shading.studio_light = name
                        return name
    except Exception:
        pass
    return None


def setup_dental_workspace():
    """Configure all 3D Viewports in all workspaces for optimal dental clinical visibility."""
    # Apply to all screens (Layout, Modeling, Sculpting tabs)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        shading = space.shading
                        # 1. Solid Matcap shading
                        shading.type = "SOLID"
                        shading.light = "MATCAP"
                        # Use high-contrast clay matcap when available.
                        _set_preferred_matcap(shading, "clay_brown.exr")
                        shading.color_type = (
                            "OBJECT"  # Show object colors (Cyan for margins, etc.)
                        )

                        # 2. Enable Cavity (Crucial for seeing margins)
                        shading.show_cavity = True
                        shading.cavity_type = "BOTH"
                        shading.cavity_ridge_factor = 2.0
                        shading.cavity_valley_factor = 2.0

                        # 3. Sidebar visibility
                        space.show_region_ui = True

                        # 4. Set our category active in this screen
                        try:
                            # Use the category name from the panel registration
                            area.spaces.active.active_category = "Smile"
                        except Exception:
                            pass

    # Redraw to reflect changes immediately
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def _ensure_veneer_import_path():
    """Load blendersmile_veneer_import.py as a module using importlib.
    Works for standalone scripts where __file__ is not defined."""
    import sys, os, importlib, importlib.util

    # Already loaded
    if "blendersmile_veneer_import" in sys.modules:
        return

    # Find the module file
    module_file = None
    search_dirs = []

    # Strategy 1: __file__ (addon mode)
    try:
        search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass

    # Strategy 2: Blend file directory
    try:
        bd = os.path.dirname(bpy.data.filepath)
        if bd:
            search_dirs.append(bd)
    except Exception:
        pass

    # Strategy 3: Known script location
    search_dirs.append(os.path.expanduser("~/Desktop/blendersmile"))

    # Strategy 4: Blender text block — check if text names give us a path hint
    try:
        for txt in bpy.data.texts:
            if txt.filepath:
                search_dirs.append(os.path.dirname(os.path.abspath(txt.filepath)))
    except Exception:
        pass

    for d in search_dirs:
        candidate = os.path.join(d, "blendersmile_veneer_import.py")
        if os.path.isfile(candidate):
            module_file = candidate
            break

    if not module_file:
        raise ImportError(
            "blendersmile_veneer_import.py not found in: " + ", ".join(search_dirs)
        )

    # Load module by absolute path using importlib
    spec = importlib.util.spec_from_file_location(
        "blendersmile_veneer_import", module_file
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blendersmile_veneer_import"] = mod
    spec.loader.exec_module(mod)
    print(f"[BlenderSmile] Loaded veneer module from: {module_file}")


def _ensure_prepless_veneer_path():
    """Load blendersmile_prepless_veneer.py as a module using importlib."""
    import sys, os, importlib, importlib.util

    if "blendersmile_prepless_veneer" in sys.modules:
        return

    module_file = None
    search_dirs = []

    try:
        search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass

    try:
        bd = os.path.dirname(bpy.data.filepath)
        if bd:
            search_dirs.append(bd)
    except Exception:
        pass

    search_dirs.append(os.path.expanduser("~/Desktop/blendersmile"))

    try:
        for txt in bpy.data.texts:
            if txt.filepath:
                search_dirs.append(os.path.dirname(os.path.abspath(txt.filepath)))
    except Exception:
        pass

    for d in search_dirs:
        candidate = os.path.join(d, "blendersmile_prepless_veneer.py")
        if os.path.isfile(candidate):
            module_file = candidate
            break

    if not module_file:
        raise ImportError(
            "blendersmile_prepless_veneer.py not found in: " + ", ".join(search_dirs)
        )

    spec = importlib.util.spec_from_file_location(
        "blendersmile_prepless_veneer", module_file
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blendersmile_prepless_veneer"] = mod
    spec.loader.exec_module(mod)
    print(f"[BlenderSmile] Loaded prepless veneer module from: {module_file}")


def _dedupe_registration_classes():
    """Return classes tuple de-duplicated by class object and operator bl_idname."""
    out = []
    seen_cls = set()
    seen_id = {}
    for cls in classes:
        if cls in seen_cls:
            print(
                f"[BlenderSmile][Register] skip duplicate class object: {getattr(cls, '__name__', str(cls))}"
            )
            continue
        bid = str(getattr(cls, "bl_idname", "") or "").strip()
        if bid:
            prev = seen_id.get(bid)
            if prev is not None and prev is not cls:
                print(
                    f"[BlenderSmile][Register] skip duplicate bl_idname '{bid}': "
                    f"{getattr(cls, '__name__', str(cls))} (kept {getattr(prev, '__name__', str(prev))})"
                )
                continue
            seen_id[bid] = cls
        seen_cls.add(cls)
        out.append(cls)
    return out


def _quarantine_unregistered_operator_classes():
    """
    Quarantine operator classes that are not in `classes` by moving them to a legacy idname namespace.
    This prevents accidental future registration collisions from stale/legacy operator blocks.
    """
    reg_set = set(_dedupe_registration_classes())
    taken = set()
    for cls in reg_set:
        bid = str(getattr(cls, "bl_idname", "") or "").strip()
        if bid:
            taken.add(bid)

    renamed = 0
    for _name, obj in sorted(globals().items()):
        if not isinstance(obj, type):
            continue
        try:
            is_op = issubclass(obj, bpy.types.Operator)
        except Exception:
            is_op = False
        if not is_op or obj in reg_set:
            continue
        bid = str(getattr(obj, "bl_idname", "") or "").strip()
        if not bid.startswith("smile."):
            continue
        suffix = bid.split(".", 1)[1] if "." in bid else bid
        if suffix.startswith("legacy_"):
            taken.add(bid)
            continue
        base = f"smile.legacy_{suffix}"
        new_bid = base
        n = 2
        while new_bid in taken:
            new_bid = f"{base}_{n}"
            n += 1
        try:
            setattr(obj, "bl_idname", new_bid)
            taken.add(new_bid)
            renamed += 1
            print(
                f"[BlenderSmile][Register] quarantined legacy operator {obj.__name__}: {bid} -> {new_bid}"
            )
        except Exception as e:
            print(
                f"[BlenderSmile][Register] quarantine failed for {obj.__name__} ({bid}): {e}"
            )
    return renamed


def _safe_register_class(cls):
    cls_name = str(getattr(cls, "__name__", cls))
    prev = getattr(bpy.types, cls_name, None)
    if prev is cls:
        print(f"[BlenderSmile][Register] already registered: {cls_name}")
        return True
    if prev is not None and prev is not cls:
        try:
            bpy.utils.unregister_class(prev)
            print(f"[BlenderSmile][Register] replaced stale class object: {cls_name}")
        except Exception as e:
            print(
                f"[BlenderSmile][Register] failed to unregister stale class {cls_name}: {e}"
            )
    try:
        bpy.utils.register_class(cls)
        return True
    except Exception as e:
        msg = str(e)
        if "already registered as a subclass" in msg:
            cur = getattr(bpy.types, cls_name, None)
            if cur is cls:
                print(
                    f"[BlenderSmile][Register] already registered after retry: {cls_name}"
                )
                return True
            if cur is not None:
                try:
                    bpy.utils.unregister_class(cur)
                    bpy.utils.register_class(cls)
                    print(
                        f"[BlenderSmile][Register] recovered class registration: {cls_name}"
                    )
                    return True
                except Exception as e2:
                    print(
                        f"[BlenderSmile][Register] recover failed for {cls_name}: {e2}"
                    )
        print(f"[BlenderSmile][Register] FAILED {cls_name}: {e}")
        return False


def _safe_unregister_class(cls):
    cls_name = str(getattr(cls, "__name__", cls))
    prev = getattr(bpy.types, cls_name, None)
    target = prev if prev is not None else cls
    try:
        bpy.utils.unregister_class(target)
        return True
    except Exception as e:
        print(f"[BlenderSmile][Unregister] skip {cls_name}: {e}")
        return False


# --- DEPSGRAPH HANDLER ---
def smile_ruler_depsgraph_handler(scene, depsgraph):
    """Update ruler ticks when Arch curve is modified"""
    # Check if we have a ruler
    ruler = bpy.data.objects.get("SMILE_Golden_Ruler")
    if not ruler:
        return

    for update in depsgraph.updates:
        # If Arch Curve (User or Synthetic) is updated
        if update.id.name in ["SMILE_Golden_Ruler_Arch", "SMILE_Golden_Arch"]:
            # Only update if geometry changed
            if update.is_updated_geometry:
                if bpy.context.scene.smile_v2:
                    update_golden_ruler(bpy.context.scene.smile_v2, bpy.context)
                break


# Allow running as a standalone script

# --- P4 OPERATORS CLASSES LIST ---
# Only the 17 operators extracted from P4 review/workspace/case report infrastructure
P4_CLASSES_LIST = (
    SMILE_OT_apply_collection_visibility_now,
    SMILE_OT_apply_review_visibility_preset,
    SMILE_OT_export_present_snapshot,
    SMILE_OT_add_review_note,
    SMILE_OT_create_review_section_plane,
    SMILE_OT_apply_review_section_style,
    SMILE_OT_nudge_review_section_plane,
    SMILE_OT_focus_active_review_artifact,
    SMILE_OT_annotate_active_review_section,
    SMILE_OT_set_workflow_state,
    SMILE_OT_export_case_report,
    SMILE_OT_import_case_report,
    SMILE_OT_case_report_copy_diagnostics,
    SMILE_OT_case_report_copy_support_bundle,
    SMILE_OT_case_report_copy_support_bundle_json,
    SMILE_OT_case_report_export_support_bundle,
    SMILE_OT_case_report_export_support_bundle_pair,
)
