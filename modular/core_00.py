"""BlenderSmile Core Module - Constants and shared utilities"""

__all__ = [
    "COL_SCANS",
    "COL_TEETH",
    "COL_LM",
    "COL_ARCH",
    "COL_PREVIEW",
    "COL_VENEER",
    "COL_RIG",
    "COL_MARGINS",
    "CORE_COLLECTIONS",
    "WORKFLOW_COLLECTION_VISIBILITY_MAP",
    "WORKFLOW_STATE_MIN_STEP",
    "DOMAIN_FACE",
    "DOMAIN_MAX",
    "DOMAIN_MAN",
    "DOMAIN_PHOTO",
    "DOMAINS",
    "DOMAIN_SHAPE",
    "NEON",
    "MARGIN_NEON_RGBA",
    "MARGIN_TRACE_COLORS",
    "SUPPORTED_EXTS",
    "TOOTH_REGEX",
    "KEY_ARCH_MAX_PTS",
    "KEY_ARCH_MAN_PTS",
    "KEY_ARCH_MAX_CERV_PTS",
    "KEY_ARCH_MAN_CERV_PTS",
    "ARCH_CURVE_OCCLUSAL",
    "ARCH_CURVE_CERVICAL",
    "KEY_MARGIN_PREFIX",
    "KEY_VENEER_RECIPE_PREFIX",
    "KEY_VENEER_SCHEMA_VER",
    "KEY_VENEER_NAME_CANONICAL",
    "KEY_VENEER_INPUT_CHECKSUM",
    "KEY_VENEER_PREVIEW",
    "KEY_NO_PREP_ALIGN_STATE_VER",
    "KEY_IMPORT_CALIB_MAX",
    "KEY_IMPORT_CALIB_MAN",
    "KEY_IMPORT_ARCH_REF_MAX",
    "KEY_IMPORT_ARCH_REF_MAN",
    "KEY_MIRROR_MIDLINE_MAX",
    "KEY_MIRROR_MIDLINE_MAN",
    "KEY_INTERPROX_DIVIDERS",
    "KEY_IMPORT_SCAN_LM3_PREFIX",
    "KEY_IMPORT_TOOTH_LM3_LOCAL",
    "KEY_FRAME3D_ORIG_MW",
    "KEY_FRAME3D_LAST_APPLY_JSON",
    "KEY_FRAME3D_LAST_APPLY_TS",
    "KEY_CASE_REPORT_DIAG_JSON",
    "KEY_CASE_REPORT_DIAG_TS",
    "KEY_MARGIN_AUTODIE_QUEUE",
    "KEY_CROWN_EDIT_ACTIVE_OBJ",
    "KEY_CROWN_EDIT_OUTLINE",
    "KEY_CAD_WIZARD_STATE",
    "KEY_CAD_INPUT_HASH",
    "KEY_CAD_OUTPUT_HASH",
    "KEY_CAD_STAGE_REPORT",
    "KEY_CAD_AXIS_FEEDBACK",
    "VENEER_SCHEMA_VERSION",
    "_KD_CACHE",
    "_SMILE_AUTODIE_TIMER_ACTIVE",
    "_CROWN_EDIT_VIEW_STATE",
    "_O3D",
    "_O3D_INSTALLING",
    "_O3D_LAST_ERROR",
    "_o3d_log",
    "_refresh_site_packages_paths",
    "_dependency_auto_install_enabled",
    "_install_open3d_worker",
    "ensure_open3d_start_install_if_missing",
    "open3d_status_string",
    "ensure_collection",
    "_find_layer_collection",
    "ensure_core_collections",
    "_apply_workflow_collection_visibility",
    "ensure_collection_visible",
    "_set_collection_viewport_state",
    "_collection_visible_in_view_layer",
    "review_section_style_preset",
    "_ensure_review_section_material",
    "_apply_review_section_style",
    "focus_object",
    "link_to_collection",
    "_deselect_all",
    "ensure_active",
    "delete_object",
    "parse_tooth_id_from_name",
    "universal_to_fdi",
    "fdi_to_universal",
    "_tooth_arch_from_universal",
    "_normalize_tooth_id_universal",
    "parse_tooth_ref_from_name",
    "parse_fdi_from_name",
    "_resolve_margin_tooth_id",
    "lm_color_for_index",
    "SafeMode",
    "_VIEW3D_UTILS",
    "_view3d_utils",
    "raycast_from_region_xy_to_target",
    "raycast_from_mouse_to_target",
    "_build_vertex_kdtree_world",
    "_matrix_world_fingerprint",
    "_mesh_fingerprint",
    "_kdtree_cache_key",
    "snap_to_nearest_vertex_world",
    "_ensure_material_node_tree",
    "ensure_emission_material",
    "get_distinct_color_for_name",
    "ensure_transparent_preview_material",
    "_mesh_primitive",
    "_set_shrinkwrap_method_safe",
    "_resolve_mesh_object",
    "make_marker",
    "_margin_trace_line_color",
]

import bpy
import os
import re
import math
import blf
import bpy_extras
import glob
import time
import importlib
import bmesh
import sys
import subprocess
import threading
import site
import traceback
import json
import hashlib
import uuid
import xml.etree.ElementTree as ET
import csv
from datetime import datetime
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree
from bpy_extras.io_utils import ImportHelper
from bpy_extras.view3d_utils import region_2d_to_vector_3d, region_2d_to_origin_3d

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None

try:
    from bpy.types import Gizmo, GizmoGroup

    GIZMOS_AVAILABLE = True
except ImportError:
    GIZMOS_AVAILABLE = False

# ============================================================
# CONSTANTS
# ============================================================

COL_SCANS = "Scans"
COL_TEETH = "Teeth"
COL_LM = "SmileLandmarks"
COL_ARCH = "SmileArch"
COL_PREVIEW = "SmilePreview"
COL_VENEER = "Veneers"
COL_RIG = "Teeth_Rig"
COL_MARGINS = "Margins"
CORE_COLLECTIONS = (
    COL_SCANS,
    COL_TEETH,
    COL_LM,
    COL_ARCH,
    COL_PREVIEW,
    COL_VENEER,
    COL_RIG,
    COL_MARGINS,
)

WORKFLOW_COLLECTION_VISIBILITY_MAP = {
    "SETUP": {
        COL_SCANS: True,
        COL_LM: True,
        COL_ARCH: True,
        COL_TEETH: False,
        COL_VENEER: False,
        COL_MARGINS: False,
    },
    "ANALYSIS": {
        COL_SCANS: True,
        COL_LM: True,
        COL_ARCH: True,
        COL_TEETH: False,
        COL_VENEER: False,
        COL_MARGINS: False,
    },
    "MOCKUP": {
        COL_SCANS: True,
        COL_LM: False,
        COL_ARCH: True,
        COL_TEETH: True,
        COL_VENEER: False,
        COL_MARGINS: False,
    },
    "PRODUCTION": {
        COL_SCANS: True,
        COL_LM: False,
        COL_ARCH: True,
        COL_TEETH: True,
        COL_VENEER: True,
        COL_MARGINS: True,
    },
    "NO_PREP": {
        COL_SCANS: True,
        COL_LM: False,
        COL_ARCH: True,
        COL_TEETH: True,
        COL_VENEER: True,
        COL_MARGINS: False,
    },
    "VENEER_IMPORT": {
        COL_SCANS: True,
        COL_LM: False,
        COL_ARCH: True,
        COL_TEETH: True,
        COL_VENEER: True,
        COL_MARGINS: True,
    },
    "GUIDED": {
        COL_SCANS: True,
        COL_LM: True,
        COL_ARCH: True,
        COL_TEETH: True,
        COL_VENEER: True,
        COL_MARGINS: True,
    },
}

WORKFLOW_STATE_MIN_STEP = {
    "SETUP": 1,
    "ANALYSIS": 2,
    "MOCKUP": 3,
    "PRODUCTION": 4,
    "NO_PREP": 5,
    "VENEER_IMPORT": 6,
    "GUIDED": 7,
}

DOMAIN_FACE = "FACE"
DOMAIN_MAX = "MAX"
DOMAIN_MAN = "MAN"
DOMAIN_PHOTO = "PHOTO"
DOMAINS = (DOMAIN_FACE, DOMAIN_MAX, DOMAIN_MAN, DOMAIN_PHOTO)

DOMAIN_SHAPE = {
    DOMAIN_FACE: "SPHERE",
    DOMAIN_MAX: "CUBE",
    DOMAIN_MAN: "CONE",
    DOMAIN_PHOTO: "CUBE",
}

NEON = [
    (1.0, 0.0, 0.5, 1.0),  # Neon Pink
    (0.0, 1.0, 0.0, 1.0),  # Neon Green
    (0.0, 0.5, 1.0, 1.0),  # Neon Blue
    (1.0, 1.0, 0.0, 1.0),  # Neon Yellow
    (1.0, 0.5, 0.0, 1.0),  # Neon Orange
    (0.0, 1.0, 1.0, 1.0),  # Neon Cyan
    (0.5, 0.0, 1.0, 1.0),  # Neon Purple
    (1.0, 1.0, 1.0, 1.0),  # Bright White
]
MARGIN_NEON_RGBA = (1.00, 0.00, 0.40, 1.00)  # bright neon pink

MARGIN_TRACE_COLORS = {
    "NEON_BLUE": (0.10, 0.60, 1.00, 1.00),
    "NEON_YELLOW": (1.00, 0.95, 0.05, 1.00),
    "NEON_PINK": (1.00, 0.15, 0.75, 1.00),
    "NEON_CYAN": (0.00, 1.00, 0.90, 1.00),
    "NEON_GREEN": (0.30, 1.00, 0.10, 1.00),
}


def _margin_trace_line_color(context=None):
    """Return the user-selected neon RGBA for margin tracing lines."""
    key = "NEON_BLUE"
    try:
        key = str(getattr(context.scene.smile_v2, "margin_trace_color", "NEON_BLUE"))
    except Exception:
        pass
    return MARGIN_TRACE_COLORS.get(key, MARGIN_TRACE_COLORS["NEON_BLUE"])


SUPPORTED_EXTS = {
    ".obj",
    ".stl",
    ".ply",
    ".fbx",
    ".gltf",
    ".glb",
    ".usd",
    ".usda",
    ".usdc",
    ".usdz",
    ".abc",
    ".dae",
}
TOOTH_REGEX = re.compile(r"#\s*(\d{1,2})")

KEY_ARCH_MAX_PTS = "SMILE_ARCH_MAX_PTS"
KEY_ARCH_MAN_PTS = "SMILE_ARCH_MAN_PTS"
KEY_ARCH_MAX_CERV_PTS = "SMILE_ARCH_MAX_CERV_PTS"
KEY_ARCH_MAN_CERV_PTS = "SMILE_ARCH_MAN_CERV_PTS"

ARCH_CURVE_OCCLUSAL = "OCCLUSAL"
ARCH_CURVE_CERVICAL = "CERVICAL"

KEY_MARGIN_PREFIX = "SMILE_MARGIN_PTS_"
KEY_VENEER_RECIPE_PREFIX = "SMILE_VENEER_RECIPE_"
KEY_VENEER_SCHEMA_VER = "SMILE_VENEER_SCHEMA_VER"
KEY_VENEER_NAME_CANONICAL = "SMILE_VENEER_NAME_CANONICAL"
KEY_VENEER_INPUT_CHECKSUM = "SMILE_VENEER_INPUT_CHECKSUM"
KEY_VENEER_PREVIEW = "SMILE_VENEER_PREVIEW"
KEY_NO_PREP_ALIGN_STATE_VER = "SMILE_NO_PREP_ALIGN_STATE_VER"
KEY_IMPORT_CALIB_MAX = "SMILE_IMPORT_CALIB_MAX"
KEY_IMPORT_CALIB_MAN = "SMILE_IMPORT_CALIB_MAN"
KEY_IMPORT_ARCH_REF_MAX = "SMILE_IMPORT_ARCH_REF_MAX"
KEY_IMPORT_ARCH_REF_MAN = "SMILE_IMPORT_ARCH_REF_MAN"
KEY_MIRROR_MIDLINE_MAX = "SMILE_MIRROR_MIDLINE_MAX"
KEY_MIRROR_MIDLINE_MAN = "SMILE_MIRROR_MIDLINE_MAN"
KEY_INTERPROX_DIVIDERS = "SMILE_INTERPROX_DIVIDERS"
KEY_IMPORT_SCAN_LM3_PREFIX = "SMILE_IMPORT_SCAN_LM3_T"
KEY_IMPORT_TOOTH_LM3_LOCAL = "SMILE_IMPORT_TOOTH_LM3_LOCAL"
KEY_FRAME3D_ORIG_MW = "SMILE_FRAME3D_ORIG_MW"
KEY_FRAME3D_LAST_APPLY_JSON = "SMILE_FRAME3D_LAST_APPLY_JSON"
KEY_FRAME3D_LAST_APPLY_TS = "SMILE_FRAME3D_LAST_APPLY_TS"
KEY_CASE_REPORT_DIAG_JSON = "SMILE_CASE_REPORT_DIAG_JSON"
KEY_CASE_REPORT_DIAG_TS = "SMILE_CASE_REPORT_DIAG_TS"
KEY_MARGIN_AUTODIE_QUEUE = "SMILE_MARGIN_AUTODIE_QUEUE"
KEY_CROWN_EDIT_ACTIVE_OBJ = "SMILE_CROWN_EDIT_ACTIVE_OBJ"
KEY_CROWN_EDIT_OUTLINE = "SMILE_CROWN_EDIT_OUTLINE"
KEY_CAD_WIZARD_STATE = "SMILE_CAD_WIZARD_STATE"
KEY_CAD_INPUT_HASH = "SMILE_CAD_INPUT_HASH"
KEY_CAD_OUTPUT_HASH = "SMILE_CAD_OUTPUT_HASH"
KEY_CAD_STAGE_REPORT = "SMILE_CAD_STAGE_REPORT"
KEY_CAD_AXIS_FEEDBACK = "SMILE_CAD_AXIS_FEEDBACK"
VENEER_SCHEMA_VERSION = 1

_KD_CACHE = {}
_SMILE_AUTODIE_TIMER_ACTIVE = False
_CROWN_EDIT_VIEW_STATE = {}

# ============================================================
# Open3D (auto install) — globals
# ============================================================

_O3D = None
_O3D_INSTALLING = False
_O3D_LAST_ERROR = ""


def _o3d_log(msg: str):
    print(f"[SmileDesign][Open3D] {msg}")


def _refresh_site_packages_paths():
    try:
        for p in site.getsitepackages():
            if p and p not in sys.path:
                site.addsitedir(p)
        importlib.invalidate_caches()
    except Exception:
        pass


def _dependency_auto_install_enabled():
    """Runtime opt-in gate for dependency installation inside Blender Python."""
    try:
        scene = getattr(bpy.context, "scene", None)
        props = getattr(scene, "smile_v2", None) if scene else None
        if props is not None:
            return bool(getattr(props, "auto_install_python_dependencies", False))
    except Exception:
        pass
    return False


def _install_open3d_worker():
    global _O3D, _O3D_INSTALLING, _O3D_LAST_ERROR
    _O3D_INSTALLING = True
    _O3D_LAST_ERROR = ""
    py = sys.executable

    try:
        _o3d_log("Bootstrapping pip (ensurepip)…")
        try:
            subprocess.check_call([py, "-m", "ensurepip"])
        except Exception as e:
            _o3d_log(f"ensurepip failed or already present: {e}")

        _o3d_log("Upgrading pip…")
        try:
            subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"])
        except Exception as e:
            _o3d_log(f"pip upgrade failed: {e}")

        _o3d_log("Installing open3d… (this can take a while)")
        subprocess.check_call([py, "-m", "pip", "install", "open3d"])

        _refresh_site_packages_paths()

        import open3d as o3d

        _O3D = o3d
        _o3d_log("Open3D installed and imported successfully.")
    except Exception as e:
        _O3D_LAST_ERROR = str(e)
        _o3d_log("Open3D install/import failed:")
        _o3d_log(_O3D_LAST_ERROR)
        _o3d_log(traceback.format_exc())
    finally:
        _O3D_INSTALLING = False


def ensure_open3d_start_install_if_missing():
    """
    Returns True if Open3D import is available now.
    If not available, starts background install thread and returns False.
    """
    global _O3D, _O3D_INSTALLING, _O3D_LAST_ERROR
    if _O3D is not None:
        return True
    try:
        _refresh_site_packages_paths()
        import open3d as o3d

        _O3D = o3d
        return True
    except Exception as e:
        _O3D_LAST_ERROR = str(e)
        if not _O3D_INSTALLING and _dependency_auto_install_enabled():
            _o3d_log("Open3D not found — starting install thread.")
            threading.Thread(target=_install_open3d_worker, daemon=True).start()
        return False


def open3d_status_string():
    if _O3D is not None:
        return "Open3D: READY"
    if _O3D_INSTALLING:
        return "Open3D: INSTALLING (see System Console)"
    if _O3D_LAST_ERROR:
        if _dependency_auto_install_enabled():
            return "Open3D: MISSING (auto-install enabled; see System Console)"
        return "Open3D: MISSING (enable auto-install or install manually)"
    if _dependency_auto_install_enabled():
        return "Open3D: MISSING (auto-install enabled)"
    return "Open3D: MISSING (auto-install disabled)"


# ============================================================
# COLLECTION HELPERS
# ============================================================


def ensure_collection(name: str):
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        try:
            bpy.context.scene.collection.children.link(col)
        except (AttributeError, RuntimeError):
            pass
    return col


def _find_layer_collection(layer_coll, coll_name: str):
    if not layer_coll:
        return None
    if layer_coll.collection and layer_coll.collection.name == coll_name:
        return layer_coll
    for child in layer_coll.children:
        hit = _find_layer_collection(child, coll_name)
        if hit:
            return hit
    return None


def ensure_core_collections():
    for name in CORE_COLLECTIONS:
        ensure_collection(name)


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
            from . import arch

            arch.ensure_arch_tracers_visible(scene, context or bpy.context)
        except Exception:
            pass


def ensure_collection_visible(context, col_name: str):
    """Best-effort: ensure collection is visible in current view layer."""
    col = bpy.data.collections.get(col_name)
    if not col:
        return None
    try:
        col.hide_viewport = False
    except Exception:
        pass
    try:
        lc_root = context.view_layer.layer_collection
        lc = _find_layer_collection(lc_root, col_name)
        if lc:
            lc.exclude = False
            lc.hide_viewport = False
    except Exception:
        pass
    return col


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


def _collection_visible_in_view_layer(context, col_name: str) -> bool:
    col = bpy.data.collections.get(col_name)
    if not col:
        return False
    hidden = bool(getattr(col, "hide_viewport", False))
    try:
        lc_root = context.view_layer.layer_collection
        lc = _find_layer_collection(lc_root, col_name)
        if lc:
            hidden = (
                hidden
                or bool(getattr(lc, "hide_viewport", False))
                or bool(getattr(lc, "exclude", False))
            )
    except Exception:
        pass
    return not hidden


# ============================================================
# REVIEW SECTION STYLE PRESETS
# ============================================================


def review_section_style_preset(style_key):
    key = str(style_key or "CLINICAL").upper()
    presets = {
        "OUTLINE": {
            "color": (1.00, 0.62, 0.10, 1.0),
            "alpha": 0.35,
            "display_type": "WIRE",
            "show_in_front": True,
        },
        "CLINICAL": {
            "color": (0.18, 0.72, 1.00, 1.0),
            "alpha": 0.20,
            "display_type": "SOLID",
            "show_in_front": True,
        },
        "PRESENT": {
            "color": (1.00, 0.95, 0.88, 1.0),
            "alpha": 0.12,
            "display_type": "SOLID",
            "show_in_front": False,
        },
    }
    return dict(presets.get(key, presets["CLINICAL"]))


def _ensure_review_section_material(style_key: str):
    preset = review_section_style_preset(style_key)
    mat_name = f"SMILE_REVIEW_SECTION_{str(style_key or 'CLINICAL').upper()}"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = _ensure_material_node_tree(mat)

    nodes = nt.nodes
    links = nt.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (320, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    rgba = tuple(preset.get("color", (0.18, 0.72, 1.0, 1.0)))
    alpha = float(preset.get("alpha", 0.2))
    try:
        bsdf.inputs["Base Color"].default_value = rgba
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = rgba
            bsdf.inputs["Emission Strength"].default_value = 0.25
        elif "Emission" in bsdf.inputs:
            bsdf.inputs["Emission"].default_value = rgba
        bsdf.inputs["Alpha"].default_value = alpha
    except Exception:
        pass
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mat.blend_method = "BLEND"
    mat.shadow_method = "NONE"
    return mat


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


# ============================================================
# OBJECT MANIPULATION
# ============================================================


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


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


def ensure_active(obj):
    _deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def delete_object(obj):
    try:
        if not obj:
            return
        name = obj.name
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    except ReferenceError:
        return
    except Exception:
        return


# ============================================================
# TOOTH UTILITIES
# ============================================================


def parse_tooth_id_from_name(name: str):
    ref = parse_tooth_ref_from_name(name)
    tid = ref.get("universal_id", None)
    if tid is None:
        return None
    try:
        return int(tid)
    except Exception:
        return None


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


def fdi_to_universal(fdi_id: int):
    """Convert FDI adult tooth ID (11..48) to Universal (1..32)."""
    try:
        fdi = int(fdi_id)
    except Exception:
        return None
    q = fdi // 10
    t = fdi % 10
    if q not in {1, 2, 3, 4} or t < 1 or t > 8:
        return None
    if q == 1:
        return int(9 - t)
    if q == 2:
        return int(8 + t)
    if q == 3:
        return int(25 - t)
    return int(24 + t)


def _tooth_arch_from_universal(tooth_id: int):
    try:
        tid = int(tooth_id)
    except Exception:
        return ""
    if 1 <= tid <= 16:
        return DOMAIN_MAX
    if 17 <= tid <= 32:
        return DOMAIN_MAN
    return ""


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
    if 1 <= tid <= 32:
        return tid
    conv = fdi_to_universal(tid)
    return conv if conv is not None else None


def parse_tooth_ref_from_name(name: str):
    """
    Parse tooth naming patterns and normalize to Universal/FDI metadata.
    Returns dict with keys: notation, raw_id, universal_id, fdi_id, arch.
    """
    out = {
        "notation": "UNKNOWN",
        "raw_id": None,
        "universal_id": None,
        "fdi_id": None,
        "arch": "",
    }
    if not name:
        return out

    txt = str(name)

    m_fdi = re.search(r"\bFDI[_\s-]?([1-4][1-8])(?=\D|$)", txt, flags=re.IGNORECASE)
    if m_fdi:
        raw = int(m_fdi.group(1))
        uni = fdi_to_universal(raw)
        out["notation"] = "FDI"
        out["raw_id"] = raw
        out["fdi_id"] = raw
        out["universal_id"] = uni
        out["arch"] = _tooth_arch_from_universal(uni) if uni is not None else ""
        return out

    m = TOOTH_REGEX.search(txt)
    if m:
        try:
            raw = int(m.group(1))
        except Exception:
            raw = None
        uni = _normalize_tooth_id_universal(raw, notation_hint="UNIVERSAL")
        out["notation"] = "UNIVERSAL" if uni is not None else "UNKNOWN"
        out["raw_id"] = raw
        out["universal_id"] = uni
        out["fdi_id"] = universal_to_fdi(uni) if uni is not None else None
        out["arch"] = _tooth_arch_from_universal(uni) if uni is not None else ""
        return out

    for pat in (
        r"(?:\bT|\btooth)[_\s-]?(\d{1,2})\b",
        r"_T(\d{1,2})\b",
    ):
        mm = re.search(pat, txt, flags=re.IGNORECASE)
        if mm:
            try:
                raw = int(mm.group(1))
            except Exception:
                raw = None
            uni = _normalize_tooth_id_universal(raw, notation_hint="UNIVERSAL")
            out["notation"] = "UNIVERSAL" if uni is not None else "UNKNOWN"
            out["raw_id"] = raw
            out["universal_id"] = uni
            out["fdi_id"] = universal_to_fdi(uni) if uni is not None else None
            out["arch"] = _tooth_arch_from_universal(uni) if uni is not None else ""
            return out

    return out


def parse_fdi_from_name(name: str):
    """Backward-compatible alias for parse_tooth_id_from_name."""
    return parse_tooth_id_from_name(name)


def _resolve_margin_tooth_id(scene=None, tooth_obj=None, preferred_id=0):
    """Resolve best available tooth ID for margin operations."""
    tid = int(preferred_id or 0)
    if tid <= 0 and tooth_obj:
        try:
            tid = int(
                tooth_obj.get(
                    "SMILE_TOOTH_ID", parse_tooth_id_from_name(tooth_obj.name) or 0
                )
                or 0
            )
        except Exception:
            tid = 0
    if tid <= 0 and scene and hasattr(scene, "smile_v2"):
        try:
            tid = int(getattr(scene.smile_v2, "target_tooth_id", 0) or 0)
        except Exception:
            tid = 0
    return int(tid)


def lm_color_for_index(idx: int):
    return NEON[(idx - 1) % len(NEON)]


# ============================================================
# SafeMode CONTEXT MANAGER
# ============================================================


class SafeMode:
    """Context manager to safely switch modes and restore state."""

    def __init__(self, obj, mode="OBJECT"):
        self.obj = obj
        self.target_mode = mode
        self.ctx = bpy.context
        self.prev_mode = None
        self.prev_active = None

    def __enter__(self):
        if not self.obj:
            return self

        try:
            self.prev_mode = self.obj.mode
            self.prev_active = self.ctx.view_layer.objects.active

            if self.ctx.view_layer.objects.active != self.obj:
                self.ctx.view_layer.objects.active = self.obj

            if not self.obj.select_get():
                self.obj.select_set(True)

            if self.obj.mode != self.target_mode:
                bpy.ops.object.mode_set(mode=self.target_mode)

        except Exception as e:
            print(f"[SafeMode] Error entering {self.target_mode}: {e}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.prev_mode and self.obj and self.obj.mode != self.prev_mode:
                self.ctx.view_layer.objects.active = self.obj
                bpy.ops.object.mode_set(mode=self.prev_mode)

            if self.prev_active and self.prev_active != self.obj:
                self.ctx.view_layer.objects.active = self.prev_active

        except Exception as e:
            print(f"[SafeMode] Error exiting: {e}")


# ============================================================
# VIEW3D RAYCAST + VERTEX SNAP
# ============================================================

_VIEW3D_UTILS = None


def _view3d_utils():
    global _VIEW3D_UTILS
    if _VIEW3D_UTILS:
        return _VIEW3D_UTILS
    try:
        from bpy_extras import view3d_utils

        _VIEW3D_UTILS = view3d_utils
    except Exception:
        _VIEW3D_UTILS = importlib.import_module("bpy_extras.view3d_utils")
    return _VIEW3D_UTILS


def raycast_from_region_xy_to_target(
    context, mouse_region_x, mouse_region_y, target_obj, max_dist=1.0e9
):
    if not target_obj or target_obj.type != "MESH":
        return None

    area = context.area
    if not area or area.type != "VIEW_3D":
        return None
    region = context.region
    rv3d = context.region_data
    if not region or not rv3d:
        return None

    v3d = _view3d_utils()
    coord = (float(mouse_region_x), float(mouse_region_y))
    ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

    deps = context.evaluated_depsgraph_get()
    hit, loc, norm, face_i, obj, _ = context.scene.ray_cast(
        deps, ray_origin, ray_dir, distance=max_dist
    )
    if hit and obj == target_obj:
        return loc, norm, face_i

    try:
        etarget = target_obj.evaluated_get(deps)
        mw = etarget.matrix_world
        mw_inv = mw.inverted()
        origin_l = mw_inv @ ray_origin
        dir_l = (mw_inv.to_3x3() @ ray_dir).normalized()
        ok, loc_l, norm_l, face_l = etarget.ray_cast(origin_l, dir_l, distance=max_dist)
        if ok:
            loc_w = mw @ loc_l
            norm_w = (mw.to_3x3() @ norm_l).normalized()
            return loc_w, norm_w, face_l
    except Exception:
        pass
    return None


def raycast_from_mouse_to_target(context, event, target_obj, max_dist=1.0e9):
    return raycast_from_region_xy_to_target(
        context,
        getattr(event, "mouse_region_x", 0.0),
        getattr(event, "mouse_region_y", 0.0),
        target_obj,
        max_dist=max_dist,
    )


def _build_vertex_kdtree_world(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    eobj = obj.evaluated_get(deps)
    me = eobj.to_mesh()
    try:
        mw = obj.matrix_world.copy()
        kd = KDTree(len(me.vertices))
        for i, v in enumerate(me.vertices):
            kd.insert(mw @ v.co, i)
        kd.balance()
        return kd
    finally:
        eobj.to_mesh_clear()


def _matrix_world_fingerprint(obj, ndigits=6):
    mw = obj.matrix_world
    return tuple(round(float(mw[r][c]), ndigits) for r in range(4) for c in range(4))


def _mesh_fingerprint(obj, sample_count=24, ndigits=6):
    me = getattr(obj, "data", None)
    if me is None or not hasattr(me, "vertices"):
        return (0, 0, 0, 0.0, 0.0, 0.0, 0)
    n_verts = len(me.vertices)
    n_edges = len(me.edges) if hasattr(me, "edges") else 0
    n_faces = len(me.polygons) if hasattr(me, "polygons") else 0
    if n_verts == 0:
        return (0, n_edges, n_faces, 0.0, 0.0, 0.0, 0)
    step = max(1, n_verts // max(1, int(sample_count)))
    sx = sy = sz = 0.0
    sampled = 0
    for i in range(0, n_verts, step):
        co = me.vertices[i].co
        sx += float(co.x)
        sy += float(co.y)
        sz += float(co.z)
        sampled += 1
        if sampled >= sample_count:
            break
    return (
        n_verts,
        n_edges,
        n_faces,
        round(sx, ndigits),
        round(sy, ndigits),
        round(sz, ndigits),
        sampled,
    )


def _kdtree_cache_key(obj):
    obj_name = str(getattr(obj, "name_full", "") or getattr(obj, "name", ""))
    data = getattr(obj, "data", None)
    data_name = str(getattr(data, "name_full", "") or getattr(data, "name", ""))
    return (obj_name, data_name, _matrix_world_fingerprint(obj), _mesh_fingerprint(obj))


def snap_to_nearest_vertex_world(obj, world_point: Vector):
    if not obj or obj.type != "MESH":
        return world_point
    ptr = int(obj.as_pointer())
    key = _kdtree_cache_key(obj)
    cached = _KD_CACHE.get(ptr)
    kd = cached.get("kd") if cached and cached.get("key") == key else None
    if kd is None:
        kd = _build_vertex_kdtree_world(obj)
        _KD_CACHE[ptr] = {"key": key, "kd": kd}
        if len(_KD_CACHE) > 512:
            live_ptrs = {int(o.as_pointer()) for o in bpy.data.objects}
            stale = [k for k in _KD_CACHE.keys() if k not in live_ptrs]
            for k in stale:
                _KD_CACHE.pop(k, None)
            if len(_KD_CACHE) > 512:
                _KD_CACHE.clear()
    co, _, _ = kd.find(world_point)
    return co


# ============================================================
# MATERIAL HELPERS
# ============================================================


def _ensure_material_node_tree(mat):
    """Return a usable node tree for material, suppressing future-use deprecation noise."""
    if not mat:
        return None
    nt = getattr(mat, "node_tree", None)
    if nt is not None:
        return nt
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            if hasattr(mat, "use_nodes"):
                mat.use_nodes = True
    except Exception:
        pass
    return getattr(mat, "node_tree", None)


def ensure_emission_material(name: str, color_rgba, strength=25.0, alpha=1.0):
    mat = bpy.data.materials.get(name)
    if mat:
        nt = _ensure_material_node_tree(mat)
        if nt is None:
            return mat
        emission = None
        out = None
        for n in nt.nodes:
            if n.type == "EMISSION":
                emission = n
            if n.type == "OUTPUT_MATERIAL":
                out = n
        if emission is None:
            emission = nt.nodes.new("ShaderNodeEmission")
        if out is None:
            out = nt.nodes.new("ShaderNodeOutputMaterial")
        emission.inputs["Color"].default_value = (
            color_rgba[0],
            color_rgba[1],
            color_rgba[2],
            alpha,
        )
        emission.inputs["Strength"].default_value = strength
        try:
            nt.links.new(emission.outputs["Emission"], out.inputs["Surface"])
        except Exception:
            traceback.print_exc()
        mat.blend_method = "BLEND" if alpha < 0.999 else "OPAQUE"
        return mat

    mat = bpy.data.materials.new(name)
    nt = _ensure_material_node_tree(mat)
    if nt is None:
        return mat
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = strength
    emit.inputs["Color"].default_value = (
        color_rgba[0],
        color_rgba[1],
        color_rgba[2],
        alpha,
    )
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    mat.blend_method = "BLEND" if alpha < 0.999 else "OPAQUE"
    return mat


def get_distinct_color_for_name(name: str):
    """Generate a consistent, bright distinct color for a given string."""
    h = int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16)
    hue = (h % 360) / 360.0
    sat = 0.9
    val = 1.0

    import colorsys

    rgb = colorsys.hsv_to_rgb(hue, sat, val)
    return (rgb[0], rgb[1], rgb[2], 1.0)


def ensure_transparent_preview_material(name="SMILE_GHOST"):
    mat = bpy.data.materials.get(name)
    if mat:
        mat.use_nodes = True
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = None
    for n in nt.nodes:
        if n.type == "BSDF_PRINCIPLED":
            bsdf = n
            break
    if bsdf:
        bsdf.inputs["Alpha"].default_value = 0.25
    mat.blend_method = "BLEND"
    return mat


# ============================================================
# MESH UTILITIES
# ============================================================


def _mesh_primitive(shape: str, name: str):
    me = bpy.data.meshes.get(name)
    if me:
        return me
    bm = bmesh.new()
    try:
        if shape == "CUBE":
            bmesh.ops.create_cube(bm, size=2.0)
        elif shape == "CONE":
            bmesh.ops.create_cone(bm, segments=24, radius1=1.0, radius2=0.0, depth=2.0)
        elif shape == "ICO":
            bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
        else:
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


def _set_shrinkwrap_method_safe(sw):
    for attr, val in (
        ("wrap_method", "NEAREST_SURFACEPOINT"),
        ("method", "NEAREST_SURFACEPOINT"),
        ("wrap_method", "NEAREST_SURFACE"),
        ("method", "NEAREST_SURFACE"),
    ):
        try:
            setattr(sw, attr, val)
            break
        except Exception:
            pass


def _resolve_mesh_object(target_obj):
    """Return a live mesh object from object-or-name input, tolerating stale RNA handles."""
    if target_obj is None:
        return None
    if isinstance(target_obj, str):
        obj = bpy.data.objects.get(target_obj)
        return obj if obj and obj.type == "MESH" else None
    try:
        obj_name = target_obj.name
        obj = bpy.data.objects.get(obj_name)
        if obj and obj.type == "MESH":
            return obj
        if getattr(target_obj, "type", None) == "MESH":
            return target_obj
    except ReferenceError:
        return None
    except Exception:
        return None
    return None


# ============================================================
# MARKER CREATION
# ============================================================


def make_marker(
    name: str,
    world_location: Vector,
    size: float,
    target_obj,
    rgba,
    shape="SPHERE",
    sticky=True,
    parent_to_target=True,
):
    target_mesh = _resolve_mesh_object(target_obj)
    if not target_mesh:
        raise RuntimeError("No valid target mesh for marker.")

    col = ensure_collection(COL_LM)
    obj = bpy.data.objects.get(name)
    mat = ensure_emission_material(name + "_MAT", rgba, strength=25.0, alpha=1.0)

    if not obj:
        me = _mesh_primitive(shape, name + "_mesh")
        obj = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(obj)
        link_to_collection(obj, col)
        obj.show_in_front = True
        obj.display_type = "SOLID"
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    else:
        if obj.type == "MESH":
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

    try:
        mw = obj.matrix_world.copy()
        mw.translation = Vector(world_location)
        obj.matrix_world = mw
    except Exception:
        obj.location = world_location
    obj.scale = (size, size, size)
    obj.show_in_front = True
    obj.color = rgba

    for c in list(obj.constraints):
        if c.type == "SHRINKWRAP" and c.name.startswith("SMILE_"):
            obj.constraints.remove(c)

    if sticky:
        sw = obj.constraints.new("SHRINKWRAP")
        sw.name = "SMILE_SurfaceLock"
        sw.target = target_mesh
        _set_shrinkwrap_method_safe(sw)
        try:
            sw.distance = 0.0
        except Exception:
            pass

    bpy.context.view_layer.update()

    if parent_to_target:
        if obj.parent != target_mesh:
            obj.parent = target_mesh
            obj.matrix_parent_inverse = target_mesh.matrix_world.inverted()
    else:
        if obj.parent is not None:
            try:
                mw = obj.matrix_world.copy()
                obj.parent = None
                obj.matrix_world = mw
            except Exception:
                pass

    obj["SMILE_ATTACH_TARGET"] = target_mesh.name
    obj["SMILE_CREATED_AT"] = float(time.time())
    bpy.context.view_layer.update()
    return obj


# ============================================================
# REGISTRATION (empty for core module)
# ============================================================

classes = ()


def register():
    pass


def unregister():
    pass
