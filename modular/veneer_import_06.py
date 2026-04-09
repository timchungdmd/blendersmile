"""BlenderSmile VENEER_IMPORT Tab Module

This module contains operators and UI for the VENEER_IMPORT workflow tab:
- Crown editing operators (shape edit, push/pull)
- Frame 2D/3D operators
- Calibration and PnP capture operators
- Import/guided workflow operators
- Measurement operators
- Seed placement operators
"""

__all__ = [
    "CLASSES",
    "draw_veneer_import_tab",
    "register",
    "unregister",
]

import bpy
import os
import re
import math
import blf
import json
import csv
import traceback
from datetime import datetime
from mathutils import Vector, Matrix

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None

from bpy_extras.io_utils import ImportHelper
from bpy_extras.view3d_utils import region_2d_to_vector_3d, region_2d_to_origin_3d

COL_SCANS = "Scans"
COL_TEETH = "Teeth"
COL_LM = "SmileLandmarks"
COL_ARCH = "SmileArch"
COL_PREVIEW = "SmilePreview"
COL_VENEER = "Veneers"
COL_RIG = "Teeth_Rig"
COL_MARGINS = "Margins"

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

DOMAIN_MAX = "MAX"
DOMAIN_MAN = "MAN"
DOMAIN_FACE = "FACE"
DOMAIN_PHOTO = "PHOTO"

ARCH_CURVE_OCCLUSAL = "OCCLUSAL"
ARCH_CURVE_CERVICAL = "CERVICAL"

KEY_FRAME3D_ORIG_MW = "SMILE_FRAME3D_ORIG_MW"
KEY_FRAME3D_LAST_APPLY_JSON = "SMILE_FRAME3D_LAST_APPLY_JSON"
KEY_FRAME3D_LAST_APPLY_TS = "SMILE_FRAME3D_LAST_APPLY_TS"
KEY_CASE_REPORT_DIAG_JSON = "SMILE_CASE_REPORT_DIAG_JSON"
KEY_CASE_REPORT_DIAG_TS = "SMILE_CASE_REPORT_DIAG_TS"
KEY_CROWN_EDIT_ACTIVE_OBJ = "SMILE_CROWN_EDIT_ACTIVE_OBJ"
KEY_CROWN_EDIT_OUTLINE = "SMILE_CROWN_EDIT_OUTLINE"

_CROWN_EDIT_VIEW_STATE = {}

NEON = [
    (1.0, 0.0, 0.5, 1.0),
    (0.0, 1.0, 0.0, 1.0),
    (0.0, 0.5, 1.0, 1.0),
    (1.0, 1.0, 0.0, 1.0),
    (1.0, 0.5, 0.0, 1.0),
    (0.0, 1.0, 1.0, 1.0),
    (0.5, 0.0, 1.0, 1.0),
    (1.0, 1.0, 1.0, 1.0),
]


def _lazy_import_core():
    """Lazy import from core module when running in Blender."""
    import bpy
    import sys

    try:
        from . import _00_core as core

        return core
    except ImportError:
        pass
    try:
        sys.path.insert(0, __file__.rsplit("/", 1)[0])
        import _00_core as core

        return core
    except ImportError:
        pass
    return None


def _lazy_import_mockup():
    """Lazy import from mockup module when running in Blender."""
    import bpy
    import sys

    try:
        from . import _04_mockup as mockup

        return mockup
    except ImportError:
        pass
    try:
        sys.path.insert(0, __file__.rsplit("/", 1)[0])
        import _04_mockup as mockup

        return mockup
    except ImportError:
        pass
    return None


def _lazy_import_properties():
    """Lazy import from properties module when running in Blender."""
    import bpy
    import sys

    try:
        from . import _01_properties as props

        return props
    except ImportError:
        pass
    try:
        sys.path.insert(0, __file__.rsplit("/", 1)[0])
        import _01_properties as props

        return props
    except ImportError:
        pass
    return None


_core = None
_mockup = None
_props = None


def _get_core():
    global _core
    if _core is None:
        _core = _lazy_import_core()
    return _core


def _get_mockup():
    global _mockup
    if _mockup is None:
        _mockup = _lazy_import_mockup()
    return _mockup


def _get_props():
    global _props
    if _props is None:
        _props = _lazy_import_properties()
    return _props


def ensure_collection(name):
    if bpy.data.collections.get(name):
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def ensure_active(obj):
    if obj and obj.name in bpy.data.objects:
        bpy.context.view_layer.objects.active = obj


def delete_object(obj):
    if not obj:
        return
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def link_to_collection(obj, col):
    if not obj or not col:
        return
    if obj.name not in col.objects:
        col.objects.link(obj)


def parse_tooth_id_from_name(name: str):
    if not name:
        return None
    patterns = [
        r"Tooth_?(\d+)",
        r"T(\d+)",
        r"#(\d+)",
        r"_(\d{2})_",
        r"_U(\d)_",
        r"_L(\d)_",
    ]
    for pat in patterns:
        m = re.search(pat, name, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def bbox_world(obj):
    if not obj or obj.type != "MESH":
        return (Vector((-1, -1, -1)), Vector((1, 1, 1)))
    mw = obj.matrix_world
    bbox = obj.bound_box
    pts = [mw @ Vector(p) for p in bbox]
    mins = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    maxs = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return (mins, maxs)


def arch_curve_name(domain: str, curve_role: str = ARCH_CURVE_OCCLUSAL):
    role_suffix = "" if curve_role == ARCH_CURVE_OCCLUSAL else f"_{curve_role}"
    return f"ARCH_{domain}_CURVE{role_suffix}"


def detect_incisal_edge_by_geometry(obj):
    if not obj or obj.type != "MESH":
        return (Vector((0, 0, 0)), None, None)
    mw = obj.matrix_world
    verts = [mw @ v.co for v in obj.data.vertices]
    if not verts:
        return (mw.translation.copy(), None, None)
    incisal = max(verts, key=lambda v: v.z)
    cervical = min(verts, key=lambda v: v.z)
    x_sorted = sorted(verts, key=lambda v: v.x)
    facial_pt = max(x_sorted[: len(x_sorted) // 3], key=lambda v: v.y)
    lingual_pt = min(x_sorted[-len(x_sorted) // 3 :], key=lambda v: v.y)
    return (incisal, facial_pt, lingual_pt)


def normalize_tooth_model(tooth_obj):
    """Normalize imported tooth to unit scale (1.0 x 1.0 x 1.0 bounding box)."""
    if not tooth_obj or tooth_obj.type != "MESH":
        return

    def bbox_local(obj):
        pts = [Vector(v) for v in obj.bound_box]
        mins = Vector(
            (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
        )
        maxs = Vector(
            (max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
        )
        return (mins, maxs)

    bbox_min, bbox_max = bbox_local(tooth_obj)
    bbox_size = bbox_max - bbox_min
    max_dim = max(bbox_size.x, bbox_size.y, bbox_size.z)
    if max_dim > 0:
        scale_factor = 1.0 / max_dim
        tooth_obj.scale = (scale_factor, scale_factor, scale_factor)
        bpy.context.view_layer.update()

    try:
        lb_min, lb_max = bbox_local(tooth_obj)
        center_local = (lb_min + lb_max) * 0.5
        if center_local.length > 1.0e-9:
            tooth_obj.data.transform(Matrix.Translation(-center_local))
            tooth_obj.location += tooth_obj.matrix_world.to_3x3() @ center_local
            tooth_obj.data.update()
            bpy.context.view_layer.update()
    except Exception:
        pass


def auto_orient_tooth_to_camera_pca(tooth_obj, camera):
    """Auto-orient tooth using PCA to align principal axes with camera frame."""
    if not tooth_obj or tooth_obj.type != "MESH" or not camera:
        return
    try:
        import numpy as np

        verts = np.array([v.co.to_tuple() for v in tooth_obj.data.vertices])
        if len(verts) < 3:
            return
        centroid = verts.mean(axis=0)
        centered = verts - centroid
        cov = np.cov(centered.T)
        eigenvalues, eigenvectors = np.linalg.eig(cov)
        idx = eigenvalues.argsort()[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]
        vec1 = Vector(eigenvectors[:, 0])
        vec2 = Vector(eigenvectors[:, 1])
        vec3 = Vector(eigenvectors[:, 2])
        cam_mat = camera.matrix_world
        cam_right = cam_mat.col[0].to_vector().normalized()
        cam_up = cam_mat.col[1].to_vector().normalized()
        cam_forward = cam_mat.col[2].to_vector().normalized()
        frame = Matrix(
            [
                [cam_right.x, cam_up.x, -cam_forward.x, 0],
                [cam_right.y, cam_up.y, -cam_forward.y, 0],
                [cam_right.z, cam_up.z, -cam_forward.z, 0],
                [0, 0, 0, 1],
            ]
        )
        obj_frame = Matrix(
            [
                [vec1.x, vec2.x, vec3.x, 0],
                [vec1.y, vec2.y, vec3.y, 0],
                [vec1.z, vec2.z, vec3.z, 0],
                [0, 0, 0, 1],
            ]
        )
        R = frame @ obj_frame.inverted()
        mw = tooth_obj.matrix_world
        tooth_obj.matrix_world = R @ mw
    except Exception:
        pass


def _center_trackball_on_object(context, obj, focus_view=False):
    """Center view on an object."""
    if not obj or not context:
        return
    ensure_active(obj)
    try:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        override = context.copy()
                        override["area"] = area
                        override["region"] = region
                        override["selected_objects"] = [obj]
                        with context.temp_override(**override):
                            bpy.ops.view3d.view_selected()
                        break
    except Exception:
        pass


def _step_gate_error(context, required_step: int, action_label: str):
    scene = context.scene if context else None
    p = scene.smile_v2 if scene else None
    if not p:
        return None
    if not getattr(p, "enforce_step_lock", False):
        return None
    cur = int(getattr(p, "design_step", "1") or "1")
    if cur < int(required_step):
        return (
            f"{action_label} requires Step {int(required_step)}+ (current: Step {cur})."
        )
    return None


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = int(getattr(props, "design_step", "1") or "1")
    if tgt > cur:
        props.design_step = str(tgt)


def _get_or_create_polyline_curve(name: str, points_world, collection_name=COL_PREVIEW):
    """Create/update a 3D poly curve object with the given world points."""
    obj = bpy.data.objects.get(name)
    if obj and obj.type == "CURVE":
        curve_data = obj.data
        while curve_data.splines:
            curve_data.splines.remove(curve_data.splines[0])
    else:
        curve_data = bpy.data.curves.new(f"{name}_Data", "CURVE")
        curve_data.dimensions = "3D"
        obj = bpy.data.objects.new(name, curve_data)
        link_to_collection(obj, ensure_collection(collection_name))
    pts = [Vector(p) for p in points_world]
    if len(pts) < 2:
        return obj
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        spline.points[i].co = (float(p.x), float(p.y), float(p.z), 1.0)
    curve_data.bevel_depth = 0.0004
    curve_data.bevel_resolution = 2
    obj.show_in_front = True
    return obj


def _sample_curve_world_points(curve_obj, max_points=120):
    """Collect ordered world-space points from a curve object."""
    if not curve_obj or curve_obj.type != "CURVE" or not curve_obj.data:
        return []
    pts = []
    mw = curve_obj.matrix_world
    for spline in curve_obj.data.splines:
        if spline.type == "BEZIER":
            for bp in spline.bezier_points:
                pts.append(mw @ bp.co)
        else:
            for p in spline.points:
                pts.append(mw @ Vector((float(p.co.x), float(p.co.y), float(p.co.z))))
    if len(pts) > int(max_points):
        stride = max(1, len(pts) // int(max_points))
        pts = [pts[i] for i in range(0, len(pts), stride)]
    return pts


def _closest_point_and_tangent_on_polyline_world(point_world: Vector, poly_points):
    pts = [Vector(p) for p in (poly_points or [])]
    if not pts:
        return None, Vector((1.0, 0.0, 0.0)), float("inf")
    if len(pts) == 1:
        return pts[0], Vector((1.0, 0.0, 0.0)), (point_world - pts[0]).length
    best_q = pts[0]
    best_tan = pts[1] - pts[0] if len(pts) > 1 else Vector((1.0, 0.0, 0.0))
    if best_tan.length < 1e-8:
        best_tan = Vector((1.0, 0.0, 0.0))
    best_tan.normalize()
    best_d2 = (point_world - best_q).length_squared
    for i in range(len(pts) - 1):
        a = pts[i]
        b = pts[i + 1]
        ab = b - a
        ab_len2 = ab.length_squared
        if ab_len2 < 1e-12:
            q = a
            tan = best_tan
        else:
            t = max(0.0, min(1.0, (point_world - a).dot(ab) / ab_len2))
            q = a + ab * t
            tan = ab.normalized()
        d2 = (point_world - q).length_squared
        if d2 < best_d2:
            best_d2 = d2
            best_q = q
            best_tan = tan
    return best_q, best_tan, math.sqrt(best_d2)


def _matrix_from_prop(raw):
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
        except Exception:
            return None
    else:
        arr = raw
    if not isinstance(arr, (list, tuple)) or len(arr) != 4:
        return None
    try:
        m = Matrix(arr)
        if m and len(m.col) == 4:
            return m
    except Exception:
        return None
    return None


def _clear_frame3d_preview_objects(
    prefixes=("SMILE_FRAME3D_DELTA_", "SMILE_FRAME3D_TAN_"),
):
    to_del = []
    for obj in bpy.data.objects:
        nm = str(obj.name)
        for pref in prefixes:
            if nm.startswith(pref):
                to_del.append(obj)
                break
    for obj in to_del:
        try:
            delete_object(obj)
        except Exception:
            pass
    return len(to_del)


def _json_obj(v, default=None):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            pass
    return default


def _store_frame3d_apply_summary(scene, summary_payload):
    if not scene:
        return
    payload = _json_obj(summary_payload, default={})
    if not isinstance(payload, dict):
        payload = {"value": payload}
    ts = datetime.utcnow().isoformat() + "Z"
    payload["timestamp_utc"] = ts
    scene[KEY_FRAME3D_LAST_APPLY_TS] = ts
    scene[KEY_FRAME3D_LAST_APPLY_JSON] = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )


def _get_frame3d_apply_summary(scene):
    if not scene:
        return {}
    return _json_obj(scene.get(KEY_FRAME3D_LAST_APPLY_JSON, "{}"), default={})


def _frame3d_summary_rows(summary):
    s = _json_obj(summary, default={})
    rows = s.get("tooth_metrics", [])
    if not isinstance(rows, list):
        rows = []
    out = []
    for rec in rows:
        if not isinstance(rec, dict):
            continue
        out.append(
            {
                "tooth_id": rec.get("tooth_id", ""),
                "tooth_name": rec.get("tooth_name", ""),
                "move_mm": float(rec.get("move_mm", 0.0)),
                "rot_deg": float(rec.get("rot_deg", 0.0)),
                "move_clamped": bool(rec.get("move_clamped", False)),
                "rot_clamped": bool(rec.get("rot_clamped", False)),
                "preview_only": bool(rec.get("preview_only", False)),
            }
        )
    return out


def _collect_view3d_spaces(context):
    out = []
    try:
        wm = context.window_manager
        for win in wm.windows:
            scr = win.screen
            if not scr:
                continue
            for area in scr.areas:
                if area.type != "VIEW_3D":
                    continue
                for sp in area.spaces:
                    if sp.type == "VIEW_3D":
                        out.append((win, area, sp))
                        break
    except Exception:
        pass
    return out


def _ensure_crown_outline_material():
    name = "SMILE_CROWN_OUTLINE_MAT"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
        nt = mat.node_tree
        if nt:
            nodes = nt.nodes
            links = nt.links
            nodes.clear()
            out = nodes.new("ShaderNodeOutputMaterial")
            em = nodes.new("ShaderNodeEmission")
            em.inputs["Color"].default_value = (0.08, 0.38, 1.0, 1.0)
            em.inputs["Strength"].default_value = 1.6
            links.new(em.outputs["Emission"], out.inputs["Surface"])
    except Exception:
        pass
    return mat


def _apply_crown_outline_style(curve_obj, thickness_mm=0.05):
    if not curve_obj or curve_obj.type != "CURVE" or not curve_obj.data:
        return False
    try:
        d = curve_obj.data
        d.dimensions = "3D"
        d.fill_mode = "FULL"
        d.bevel_resolution = 1
        d.resolution_u = max(8, int(getattr(d, "resolution_u", 12)))
        d.bevel_depth = max(0.0001, float(thickness_mm) / 1000.0)
        mat = _ensure_crown_outline_material()
        if mat:
            if len(d.materials) == 0:
                d.materials.append(mat)
            else:
                d.materials[0] = mat
        curve_obj.show_in_front = True
        return True
    except Exception:
        return False


def _find_margin_curve_for_object(context, obj):
    if not obj:
        return None
    scene = context.scene
    p = scene.smile_v2
    tid = (
        parse_tooth_id_from_name(obj.name)
        or int(obj.get("SMILE_TOOTH_ID", 0) or 0)
        or int(getattr(p, "target_tooth_id", 0) or 0)
    )
    cands = []
    suffix = f"_T{int(tid)}"
    canonical_name = f"MARGIN_{obj.name}{suffix}" if tid > 0 else f"MARGIN_{obj.name}"
    for o in bpy.data.objects:
        if o.type != "CURVE" or not o.name.startswith("MARGIN_"):
            continue
        if tid > 0 and suffix not in o.name:
            continue
        cands.append(o)
    if cands:
        cands.sort(
            key=lambda x: (
                0
                if x.name == canonical_name
                else (1 if x.name.endswith("_Curve") else 2),
                x.name,
            )
        )
        return cands[0]
    fallback = [
        o
        for o in bpy.data.objects
        if o.type == "CURVE" and o.name.startswith("MARGIN_") and obj.name in o.name
    ]
    if fallback:
        fallback.sort(key=lambda x: x.name)
        return fallback[0]
    return None


def _crown_edit_apply_brush(context, props, direction=None):
    if context.mode != "SCULPT":
        return None
    brush_map = {
        "GRAB": ["Grab", "Elastic Deform", "Draw"],
        "ELASTIC": ["Elastic Deform", "Grab", "Draw"],
        "DRAW": ["Draw", "Inflate/Deflate"],
        "INFLATE": ["Inflate/Deflate", "Inflate", "Draw"],
        "SMOOTH": ["Smooth", "Draw"],
    }
    names = brush_map.get(
        str(getattr(props, "crown_edit_brush", "GRAB")), ["Grab", "Draw"]
    )
    sc = context.tool_settings.sculpt
    selected = None
    for nm in names:
        b = bpy.data.brushes.get(nm)
        if b:
            selected = b
            break
    if not selected:
        return None
    brush_kind = str(getattr(props, "crown_edit_brush", "GRAB"))
    active_brush = selected
    brush_set_ok = False
    try:
        sc.brush = selected
        brush_set_ok = True
    except Exception:
        try:
            sculpt_tool = str(getattr(selected, "sculpt_tool", "") or "")
            if sculpt_tool:
                try:
                    bpy.ops.paint.brush_select(sculpt_tool=sculpt_tool, toggle=False)
                except TypeError:
                    bpy.ops.paint.brush_select(sculpt_tool=sculpt_tool)
                brush_set_ok = True
        except Exception:
            brush_set_ok = False

    if not brush_set_ok:
        tool_id_map = {
            "GRAB": "builtin_brush.Grab",
            "ELASTIC": "builtin_brush.ElasticDeform",
            "DRAW": "builtin_brush.Draw",
            "INFLATE": "builtin_brush.Inflate",
            "SMOOTH": "builtin_brush.Smooth",
        }
        tid = tool_id_map.get(brush_kind)
        if tid:
            try:
                bpy.ops.wm.tool_set_by_id(name=tid)
                brush_set_ok = True
            except Exception:
                pass

    try:
        b = getattr(sc, "brush", None)
        if b is not None:
            active_brush = b
    except Exception:
        active_brush = selected

    profile = str(getattr(props, "crown_edit_response_profile", "CLINICAL"))
    base_strength = float(
        max(0.001, min(1.0, float(getattr(props, "crown_edit_brush_strength", 0.45))))
    )
    tuned_strength = base_strength
    if profile == "SOFT":
        if brush_kind in {"GRAB", "ELASTIC"}:
            tuned_strength = base_strength * 0.55
        elif brush_kind in {"DRAW", "INFLATE"}:
            tuned_strength = base_strength * 0.35
        else:
            tuned_strength = base_strength * 0.80
    elif profile == "FIRM":
        if brush_kind in {"GRAB", "ELASTIC"}:
            tuned_strength = base_strength * 0.85
        elif brush_kind in {"DRAW", "INFLATE"}:
            tuned_strength = base_strength * 0.60
        else:
            tuned_strength = base_strength * 1.05
    else:
        if brush_kind in {"GRAB", "ELASTIC"}:
            tuned_strength = base_strength * 0.70
        elif brush_kind in {"DRAW", "INFLATE"}:
            tuned_strength = base_strength * 0.45
        else:
            tuned_strength = base_strength * 0.95

    size_val = int(max(1, float(getattr(props, "crown_edit_brush_size", 42.0))))
    strength_val = float(max(0.001, min(1.0, tuned_strength)))
    ups = getattr(context.tool_settings, "unified_paint_settings", None)
    try:
        if ups and bool(getattr(ups, "use_unified_size", False)):
            ups.size = int(size_val)
        else:
            active_brush.size = int(size_val)
    except Exception:
        pass
    try:
        if ups and bool(getattr(ups, "use_unified_strength", False)):
            ups.strength = float(strength_val)
        else:
            active_brush.strength = float(strength_val)
    except Exception:
        pass
    try:
        active_brush.use_accumulate = False
    except Exception:
        pass
    try:
        active_brush.use_frontface = bool(
            getattr(props, "crown_edit_front_faces_only", True)
        )
    except Exception:
        pass
    if direction:
        try:
            if hasattr(active_brush, "direction"):
                active_brush.direction = str(direction)
        except Exception:
            pass
    auto_smooth = float(getattr(props, "crown_edit_auto_smooth", 0.0))
    try:
        active_brush.auto_smooth_factor = float(auto_smooth)
    except Exception:
        pass
    hardness = float(getattr(props, "crown_edit_hardness", 0.5))
    try:
        if hasattr(active_brush, "hardness"):
            active_brush.hardness = float(hardness)
    except Exception:
        pass
    return active_brush


def _collect_frame3d_points_from_teeth():
    col = bpy.data.collections.get(COL_TEETH)
    pts = []
    if not col:
        return pts
    for obj in col.objects:
        if not obj or obj.type != "MESH" or obj.hide_viewport:
            continue
        try:
            incisal_world, _, _ = detect_incisal_edge_by_geometry(obj)
            pts.append((float(incisal_world.x), incisal_world))
        except Exception:
            loc = obj.matrix_world.translation.copy()
            pts.append((float(loc.x), loc))
    pts.sort(key=lambda k: k[0])
    return [p for _, p in pts]


def _active_photo_slot(scene):
    p = scene.smile_v2
    idx = int(getattr(p, "active_photo_slot_index", 0) or 0)
    slots = list(getattr(p, "photo_slots", []) or [])
    if 0 <= idx < len(slots):
        return slots[idx]
    return slots[0] if slots else None


def _get_or_load_image(slot):
    if not slot or not slot.image_path:
        return None
    img_path = bpy.path.abspath(slot.image_path)
    if not os.path.isfile(img_path):
        return None
    img = bpy.data.images.get(os.path.basename(img_path))
    if not img:
        try:
            img = bpy.data.images.load(img_path)
        except Exception:
            return None
    return img


def _ensure_camera(slot):
    if not slot:
        return None
    cam_name = getattr(slot, "camera_name", "") or ""
    if cam_name and cam_name in bpy.data.objects:
        cam = bpy.data.objects[cam_name]
        if cam.type == "CAMERA":
            return cam
    scene = bpy.context.scene
    if scene.camera and scene.camera.type == "CAMERA":
        return scene.camera
    for obj in bpy.data.objects:
        if obj.type == "CAMERA":
            return obj
    return None


def _ensure_photo_plane(slot, cam, img, alpha=0.5, distance_mm=1000.0):
    if not slot or not cam or not img:
        return None
    plane_name = f"PHOTO_{slot.name}"
    plane = bpy.data.objects.get(plane_name)
    if not plane:
        mesh = bpy.data.meshes.new(f"{plane_name}_Mesh")
        mesh.from_pydata(
            [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], [], [[0, 1, 2, 3]]
        )
        plane = bpy.data.objects.new(plane_name, mesh)
        ensure_collection(COL_PREVIEW).objects.link(plane)
    plane.location = cam.matrix_world.translation
    aspect = img.size[0] / max(img.size[1], 1)
    plane.scale = (aspect, 1.0, 1.0)
    depth_m = float(distance_mm) / 1000.0
    forward = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
    plane.location = cam.matrix_world.translation + forward * depth_m
    plane.rotation_euler = cam.rotation_euler
    if not plane.data.materials:
        mat = bpy.data.materials.new(f"{plane_name}_Mat")
        mat.use_nodes = True
        plane.data.materials.append(mat)
        nt = mat.node_tree
        try:
            img_node = nt.nodes.new("ShaderNodeTexImage")
            img_node.image = img
            principled = nt.nodes.get("Principled BSDF")
            if principled and img_node:
                nt.links.new(img_node.outputs["Color"], principled.inputs["Base Color"])
                principled.inputs["Alpha"].default_value = alpha
                principled.inputs["Blend Method"].default_value = (
                    "CLIP" if alpha < 1.0 else "OPAQUE"
                )
            mat.blend_method = "CLIP" if alpha < 1.0 else "OPAQUE"
        except Exception:
            pass
    return plane


def choose_next_pair_index(p, domain_3d, domain_2d, active_domain=None):
    existing_3d = []
    existing_2d = []
    for slot in getattr(p, "photo_slots", []) or []:
        for lm in slot.landmarks or []:
            idx = int(getattr(lm, "idx", 0) or 0)
            dm = str(getattr(lm, "domain", "") or "")
            if dm == domain_3d:
                existing_3d.append(idx)
            elif dm == domain_2d:
                existing_2d.append(idx)
    for i in range(100):
        if i not in existing_3d and i not in existing_2d:
            return i
    return 0


def _draw_interprox_divider_section(layout, context, p, enabled=True):
    core = _get_core()
    if core and hasattr(core, "get_interprox_divider"):
        try:
            core.get_interprox_divider(layout, context, p, enabled=enabled)
            return
        except Exception:
            pass
    box = layout.box()
    box.label(
        text="Interproximal dividers are managed in Tab 7 (Production).", icon="INFO"
    )


class SMILE_OT_place_tooth_seed_on_curve(bpy.types.Operator):
    bl_idname = "smile.place_tooth_seed_on_curve"
    bl_label = "Place Tooth Seed (Visual)"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth ID", default=8)

    _handle = None
    _start_mouse = None
    _current_mouse = None
    _start_co_3d = None
    _is_dragging = False

    def invoke(self, context, event):
        self._start_mouse = (event.mouse_region_x, event.mouse_region_y)
        self._current_mouse = self._start_mouse
        self._is_dragging = False
        self._start_co_3d = None

        args = (self, context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback_px, args, "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)

        self.report(
            {"INFO"}, f"Click on Arch Curve to set CENTER. Then Drag to set SIZE."
        )
        return {"RUNNING_MODAL"}

    def draw_callback_px(self, op, context):
        if not self._is_dragging or not self._start_mouse:
            return

        font_id = 0
        blf.size(font_id, 16, 72)
        blf.color(font_id, 1, 1, 1, 1)

        mx, my = self._current_mouse
        sx, sy = self._start_mouse

        width_px = abs(mx - sx) * 2
        height_px = abs(my - sy) * 2

        x_min = sx - width_px / 2
        x_max = sx + width_px / 2
        y_min = sy - height_px / 2
        y_max = sy + height_px / 2

        coords = [
            (x_min, y_min),
            (x_max, y_min),
            (x_max, y_min),
            (x_max, y_max),
            (x_max, y_max),
            (x_min, y_max),
            (x_min, y_max),
            (x_min, y_min),
            (sx, y_min),
            (sx, y_max),
            (x_min, sy),
            (x_max, sy),
        ]

        if gpu:
            shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
            batch = batch_for_shader(shader, "LINES", {"pos": coords})
            shader.bind()
            shader.uniform_float("color", (1.0, 0.8, 0.2, 1.0))
            batch.draw(shader)

        if self._start_co_3d:
            region = context.region
            rv3d = context.region_data
            curr_vec = region_2d_to_vector_3d(region, rv3d, (mx, my))
            start_vec = region_2d_to_vector_3d(region, rv3d, (sx, sy))
            origin = region_2d_to_origin_3d(region, rv3d, (sx, sy))
            dist = (self._start_co_3d - origin).length
            p1 = origin + start_vec * dist
            p2 = origin + curr_vec * dist

            view_inv = rv3d.view_matrix.inverted()
            cam_right = view_inv.to_3x3().col[0].normalized()
            cam_up = view_inv.to_3x3().col[1].normalized()

            delta = p2 - p1
            w_mm = abs(delta.dot(cam_right)) * 2 * 1000
            h_mm = abs(delta.dot(cam_up)) * 2 * 1000

            blf.position(font_id, x_max + 10, sy, 0)
            blf.draw(font_id, f"W: {w_mm:.1f}mm")
            blf.position(font_id, x_max + 10, sy - 20, 0)
            blf.draw(font_id, f"H: {h_mm:.1f}mm")

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._current_mouse = (event.mouse_region_x, event.mouse_region_y)

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                region = context.region
                rv3d = context.region_data
                coord = (event.mouse_region_x, event.mouse_region_y)
                view_vector = region_2d_to_vector_3d(region, rv3d, coord)
                ray_origin = region_2d_to_origin_3d(region, rv3d, coord)

                hit, loc, norm, idx, obj, mat = context.scene.ray_cast(
                    context.view_layer.depsgraph, ray_origin, view_vector
                )

                if hit:
                    self._start_co_3d = loc
                else:
                    cursor_loc = context.scene.cursor.location
                    self._start_co_3d = ray_origin + view_vector * 100

                self._start_mouse = coord
                self._is_dragging = True
                return {"RUNNING_MODAL"}

            elif event.value == "RELEASE":
                if self._is_dragging:
                    mx, my = self._current_mouse
                    sx, sy = self._start_mouse

                    region = context.region
                    rv3d = context.region_data

                    curr_vec = region_2d_to_vector_3d(region, rv3d, (mx, my))
                    origin = region_2d_to_origin_3d(region, rv3d, (sx, sy))
                    dist = (self._start_co_3d - origin).length
                    p1 = origin + curr_vec * dist
                    p2 = origin + curr_vec * dist

                    view_inv = rv3d.view_matrix.inverted()
                    cam_right = view_inv.to_3x3().col[0].normalized()
                    cam_up = view_inv.to_3x3().col[1].normalized()

                    delta = p2 - p1
                    w_mm = abs(delta.dot(cam_right)) * 2 * 1000
                    h_mm = abs(delta.dot(cam_up)) * 2 * 1000

                    p = context.scene.smile_v2
                    p.target_width_mm = max(1.0, w_mm)
                    p.target_height_mm = max(1.0, h_mm)
                    p.use_target_dims = True

                    seed_name = f"SEED_T{self.tooth_id}"
                    seed = bpy.data.objects.get(seed_name)
                    if not seed:
                        seed = bpy.data.objects.new(seed_name, None)
                        context.collection.objects.link(seed)
                        ensure_collection(COL_LM).objects.link(seed)
                        context.collection.objects.unlink(seed)

                    seed.location = self._start_co_3d
                    seed.empty_display_type = "SINGLE_ARROW"
                    seed.empty_display_size = getattr(p, "marker_size", 0.01) * 5

                    bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
                    self.report({"INFO"}, f"Set Target Steps: {w_mm:.1f}x{h_mm:.1f}mm")
                    return {"FINISHED"}

        if event.type == "ESC" or event.type == "RIGHTMOUSE":
            if self._handle:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}


class SMILE_OT_measure_dimension(bpy.types.Operator):
    bl_idname = "smile.measure_dimension"
    bl_label = "Measure Dimension"
    bl_options = {"REGISTER", "UNDO"}

    target_property: bpy.props.StringProperty()

    _handle = None
    _p1 = None
    _p2 = None
    _mouse_loc = None

    def invoke(self, context, event):
        self._p1 = None
        self._p2 = None
        self._mouse_loc = (event.mouse_region_x, event.mouse_region_y)

        args = (self, context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback_px, args, "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)

        prop_name = (
            self.target_property.replace("target_", "").replace("_mm", "").title()
        )
        self.report({"INFO"}, f"Click Start Point for {prop_name}...")
        return {"RUNNING_MODAL"}

    def draw_callback_px(self, op, context):
        if not self._p1:
            return

        font_id = 0
        blf.size(font_id, 20, 72)
        blf.color(font_id, 1, 1, 1, 1)

        region = context.region
        rv3d = context.region_data

        p1_2d = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, self._p1)
        if not p1_2d:
            return

        p2_3d = self._p2 if self._p2 else None
        p2_2d = None

        if p2_3d:
            p2_2d = bpy_extras.view3d_utils.location_3d_to_region_2d(
                region, rv3d, p2_3d
            )
        elif self._mouse_loc:
            p2_2d = Vector(self._mouse_loc)

        if p1_2d and p2_2d:
            if gpu:
                shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
                batch = batch_for_shader(shader, "LINES", {"pos": [p1_2d, p2_2d]})
                shader.bind()
                shader.uniform_float("color", (0.2, 1.0, 0.5, 1.0))
                batch.draw(shader)

            mid = (p1_2d + p2_2d) * 0.5

            dist = 0.0
            if p2_3d:
                dist = (p2_3d - self._p1).length * 1000

            if p2_3d:
                blf.position(font_id, mid.x + 10, mid.y + 10, 0)
                blf.draw(font_id, f"{dist:.1f}mm")

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._mouse_loc = (event.mouse_region_x, event.mouse_region_y)

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            view_vector = region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = region_2d_to_origin_3d(region, rv3d, coord)

            hit, loc, norm, idx, obj, mat = context.scene.ray_cast(
                context.view_layer.depsgraph, ray_origin, view_vector
            )

            if hit:
                if not self._p1:
                    self._p1 = loc
                    self.report({"INFO"}, "Start Point set. Click End Point.")
                else:
                    self._p2 = loc
                    dist_mm = (self._p2 - self._p1).length * 1000

                    p = context.scene.smile_v2
                    if hasattr(p, self.target_property):
                        setattr(p, self.target_property, dist_mm)
                        p.use_target_dims = True

                    bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
                    self.report({"INFO"}, f"Measured: {dist_mm:.1f}mm")
                    return {"FINISHED"}
            else:
                self.report({"WARNING"}, "Click on a surface (scan/tooth).")

        if event.type == "ESC" or event.type == "RIGHTMOUSE":
            if self._handle:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}


class SMILE_OT_pnp_capture_2d_landmark(bpy.types.Operator):
    """Click on the photo in camera view to add a 2D landmark (u,v)."""

    bl_idname = "smile.pnp_capture_2d_landmark"
    bl_label = "Add Photo 2D Landmark (Click)"
    bl_options = {"REGISTER", "UNDO"}

    def modal(self, context, event):
        scene = context.scene
        p = scene.smile_v2
        slot = _active_photo_slot(scene)

        if not slot:
            self.report({"ERROR"}, "No active photo slot.")
            return {"FINISHED"}

        region = context.region
        rv3d = context.region_data
        if not rv3d or rv3d.view_perspective != "CAMERA":
            self.report({"ERROR"}, "You MUST be in Camera View (Numpad 0).")
            return {"FINISHED"}

        if event.type in {"RET", "NUMPAD_ENTER", "ESC", "RIGHTMOUSE"}:
            return {"FINISHED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            try:
                from bpy_extras.object_utils import world_to_camera_view
            except ImportError:
                self.report({"ERROR"}, "Could not import bpy_extras.object_utils.")
                return {"FINISHED"}

            coord = (event.mouse_region_x, event.mouse_region_y)
            cam = scene.camera

            ray_origin = region_2d_to_origin_3d(region, rv3d, coord)
            ray_vector = region_2d_to_vector_3d(region, rv3d, coord)
            p_world = ray_origin + ray_vector * 10.0

            uv_vec = world_to_camera_view(scene, cam, p_world)
            u, v = uv_vec.x, uv_vec.y

            if not (0 <= u <= 1 and 0 <= v <= 1):
                self.report({"WARNING"}, "Click was outside the camera frame.")
                return {"RUNNING_MODAL"}

            idx = choose_next_pair_index(
                p, DOMAIN_FACE, DOMAIN_PHOTO, active_domain=DOMAIN_PHOTO
            )
            it = slot.landmarks.add()
            it.idx = int(idx)
            it.u = float(u)
            it.v = float(v)
            it.domain = DOMAIN_PHOTO

            self.report({"INFO"}, f"Marked Point #{idx} (u={u:.3f}, v={v:.3f})")
            return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


class SMILE_OT_import_tooth_for_mockup(bpy.types.Operator, ImportHelper):
    """Import 3D tooth model for quick mockup with auto-normalization and orientation."""

    bl_idname = "smile.import_tooth_for_mockup"
    bl_label = "Import Tooth for Mockup"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: bpy.props.StringProperty(
        default="*.obj;*.stl;*.ply;*.fbx;*.gltf;*.glb", options={"HIDDEN"}
    )

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2

        if not self.filepath:
            self.report({"ERROR"}, "No file selected.")
            return {"CANCELLED"}

        ext = os.path.splitext(self.filepath)[1].lower()

        try:
            if ext == ".obj":
                bpy.ops.wm.obj_import(filepath=self.filepath)
            elif ext == ".stl":
                bpy.ops.wm.stl_import(filepath=self.filepath)
            elif ext == ".ply":
                bpy.ops.wm.ply_import(filepath=self.filepath)
            elif ext in {".fbx", ".gltf", ".glb"}:
                if ext == ".fbx":
                    bpy.ops.import_scene.fbx(filepath=self.filepath)
                else:
                    bpy.ops.import_scene.gltf(filepath=self.filepath)
            else:
                self.report({"ERROR"}, f"Unsupported file type: {ext}")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Import failed: {e}")
            return {"CANCELLED"}

        tooth_obj = context.view_layer.objects.active
        if not tooth_obj or tooth_obj.type != "MESH":
            self.report({"ERROR"}, "No mesh object imported.")
            return {"CANCELLED"}

        base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        tooth_obj.name = f"MOCKUP_{base_name}"

        normalize_tooth_model(tooth_obj)

        if scene.camera:
            auto_orient_tooth_to_camera_pca(tooth_obj, scene.camera)

        if scene.camera:
            cam = scene.camera
            forward = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
            default_depth_mm = getattr(p, "mockup_depth_mm", 800.0)
            depth_bu = default_depth_mm / 1000.0
            tooth_obj.location = cam.matrix_world.translation + (forward * depth_bu)
        else:
            tooth_obj.location = Vector((0, 0, 0))

        col_teeth = ensure_collection(COL_TEETH)
        if tooth_obj.name not in col_teeth.objects:
            col_teeth.objects.link(tooth_obj)

        p.mockup_active_tooth = tooth_obj
        tooth_obj["MOCKUP_NEEDS_CALIBRATION"] = True
        tooth_obj["MOCKUP_NORMALIZED_SCALE"] = 1.0

        try:
            for o in context.selected_objects:
                o.select_set(False)
            tooth_obj.select_set(True)
            context.view_layer.objects.active = tooth_obj
        except Exception:
            pass

        _center_trackball_on_object(context, tooth_obj, focus_view=True)

        mockup = _get_mockup()
        if mockup and hasattr(mockup, "_cad_autopin_reference_from_import"):
            try:
                pinned_ok, pinned_name = mockup._cad_autopin_reference_from_import(
                    context, [tooth_obj], preferred_obj=tooth_obj, force_replace=False
                )
            except Exception:
                pinned_ok, pinned_name = False, None
        else:
            pinned_ok, pinned_name = False, None

        msg = f"Imported and normalized: {tooth_obj.name}. Next: Calibrate scale."
        if pinned_ok and pinned_name:
            msg += f" CAD reference pinned: {pinned_name}."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SMILE_OT_snap_mockup_to_arch(bpy.types.Operator):
    """Snap selected mockup teeth to dental arch curve"""

    bl_idname = "smile.snap_mockup_to_arch"
    bl_label = "Snap to Arch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arch_curve = None
        for obj in context.scene.objects:
            if obj.type == "CURVE" and "arch" in obj.name.lower():
                arch_curve = obj
                break

        if not arch_curve:
            self.report({"ERROR"}, "No arch curve found. Create one first.")
            return {"CANCELLED"}

        mockup_teeth = []
        for obj in context.selected_objects:
            if obj.type == "MESH":
                if "MOCKUP" in obj.name.upper() or obj.name in [
                    o.name for o in ensure_collection(COL_TEETH).objects
                ]:
                    mockup_teeth.append(obj)

        if not mockup_teeth:
            self.report({"WARNING"}, "No mockup teeth selected")
            return {"CANCELLED"}

        for tooth_obj in mockup_teeth:
            bbox_min, bbox_max = bbox_world(tooth_obj)
            incisal_z = bbox_max.z
            incisal_location = Vector(
                (tooth_obj.location.x, tooth_obj.location.y, incisal_z)
            )

            closest_point, closest_param = self.find_closest_point_on_curve(
                arch_curve, incisal_location
            )

            if closest_point:
                offset = closest_point - incisal_location
                tooth_obj.location += offset
                self.report({"INFO"}, f"Snapped {tooth_obj.name} to arch")

        context.view_layer.update()
        self.report({"INFO"}, f"Snapped {len(mockup_teeth)} teeth to arch curve")
        return {"FINISHED"}

    def find_closest_point_on_curve(self, curve_obj, target_location):
        if not curve_obj.data.splines:
            return None, 0.0

        spline = curve_obj.data.splines[0]
        samples = 100
        closest_dist = float("inf")
        closest_point = None
        closest_param = 0.0

        for i in range(samples + 1):
            t = i / samples

            if spline.type == "BEZIER":
                point = self.evaluate_bezier_at_t(spline, t)
            else:
                num_points = len(spline.points)
                if num_points < 2:
                    continue
                idx = int(t * (num_points - 1))
                if idx >= num_points - 1:
                    point = Vector(spline.points[-1].co[:3])
                else:
                    p1 = Vector(spline.points[idx].co[:3])
                    p2 = Vector(spline.points[idx + 1].co[:3])
                    local_t = (t * (num_points - 1)) - idx
                    point = p1.lerp(p2, local_t)

            point_world = curve_obj.matrix_world @ point

            dist = (
                Vector((point_world.x, point_world.y, target_location.z))
                - target_location
            ).length

            if dist < closest_dist:
                closest_dist = dist
                closest_point = point_world
                closest_param = t

        return closest_point, closest_param

    def evaluate_bezier_at_t(self, spline, t):
        points = spline.bezier_points
        num_segments = len(points) - 1

        if num_segments < 1:
            return Vector((0, 0, 0))

        segment_idx = int(t * num_segments)
        if segment_idx >= num_segments:
            segment_idx = num_segments - 1

        local_t = (t * num_segments) - segment_idx

        p0 = points[segment_idx].co
        p1 = points[segment_idx].handle_right
        p2 = points[segment_idx + 1].handle_left
        p3 = points[segment_idx + 1].co

        s = 1 - local_t
        result = (
            s**3 * p0
            + 3 * s**2 * local_t * p1
            + 3 * s * local_t**2 * p2
            + local_t**3 * p3
        )

        return result


class SMILE_OT_delete_mockup_tooth(bpy.types.Operator):
    """Delete a mockup tooth"""

    bl_idname = "smile.delete_mockup_tooth"
    bl_label = "Delete Mockup Tooth"
    bl_options = {"REGISTER", "UNDO"}

    tooth_name: bpy.props.StringProperty()

    def execute(self, context):
        tooth_obj = bpy.data.objects.get(self.tooth_name)

        if not tooth_obj:
            self.report({"WARNING"}, f"Tooth '{self.tooth_name}' not found")
            return {"CANCELLED"}

        props = context.scene.smile_v2
        if getattr(props, "mockup_active_tooth", None) == tooth_obj:
            props.mockup_active_tooth = None

        bpy.data.objects.remove(tooth_obj, do_unlink=True)
        self.report({"INFO"}, f"Deleted: {self.tooth_name}")
        return {"FINISHED"}


class SMILE_OT_frame2d_apply(bpy.types.Operator):
    """Commit Smile Frame 2D scaffold settings and advance guided workflow."""

    bl_idname = "smile.frame2d_apply"
    bl_label = "Apply Frame 2D"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 2, "Frame 2D apply")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        scene = context.scene
        p = scene.smile_v2
        slot = _active_photo_slot(scene)
        if not slot:
            self.report({"ERROR"}, "No active photo slot.")
            return {"CANCELLED"}
        cam = _ensure_camera(slot)
        img = _get_or_load_image(slot)
        plane = _ensure_photo_plane(
            slot,
            cam,
            img,
            alpha=float(getattr(p, "pnp_bg_alpha", 0.5)),
            distance_mm=float(getattr(p, "pnp_plane_distance_mm", 1000.0)),
        )
        if not plane:
            self.report({"ERROR"}, "Photo plane unavailable.")
            return {"CANCELLED"}

        plane.rotation_euler.z = math.radians(
            float(getattr(p, "sf_picture_rotation_deg", 0.0))
        )
        x_ext = max(1e-6, abs(float(plane.scale.x)))
        y_ext = max(1e-6, abs(float(plane.scale.y)))

        def _line_local(name, p0_local, p1_local, rgba=(1, 1, 1, 1), hide=False):
            p0w = plane.matrix_world @ Vector(p0_local)
            p1w = plane.matrix_world @ Vector(p1_local)
            obj = _get_or_create_polyline_curve(name, [p0w, p1w], COL_PREVIEW)
            obj.parent = plane
            obj.matrix_parent_inverse = plane.matrix_world.inverted()
            try:
                obj.color = rgba
            except Exception:
                pass
            obj.hide_viewport = bool(hide)
            obj.hide_render = bool(hide)
            return obj

        def _rect_local(name, x0, x1, y0, y1, rgba=(1, 1, 1, 1), hide=False):
            pts = [
                (x0, y0, 0.0),
                (x1, y0, 0.0),
                (x1, y1, 0.0),
                (x0, y1, 0.0),
                (x0, y0, 0.0),
            ]
            pts_w = [plane.matrix_world @ Vector(pt) for pt in pts]
            obj = _get_or_create_polyline_curve(name, pts_w, COL_PREVIEW)
            obj.parent = plane
            obj.matrix_parent_inverse = plane.matrix_world.inverted()
            try:
                obj.color = rgba
            except Exception:
                pass
            obj.hide_viewport = bool(hide)
            obj.hide_render = bool(hide)
            return obj

        thirds = bool(getattr(p, "sf_facial_thirds", False))
        _line_local(
            "SMILE_FRAME2D_MIDLINE",
            (0.0, -y_ext, 0.0),
            (0.0, y_ext, 0.0),
            (1.0, 0.2, 0.2, 1.0),
            hide=not thirds,
        )
        _line_local(
            "SMILE_FRAME2D_THIRD_L",
            (-x_ext / 3.0, -y_ext, 0.0),
            (-x_ext / 3.0, y_ext, 0.0),
            (1.0, 1.0, 0.2, 1.0),
            hide=not thirds,
        )
        _line_local(
            "SMILE_FRAME2D_THIRD_R",
            (x_ext / 3.0, -y_ext, 0.0),
            (x_ext / 3.0, y_ext, 0.0),
            (1.0, 1.0, 0.2, 1.0),
            hide=not thirds,
        )

        flow_y = max(
            -y_ext,
            min(y_ext, float(getattr(p, "sf_facial_flow_offset_mm", 0.0)) / 1000.0),
        )
        _line_local(
            "SMILE_FRAME2D_FLOW",
            (-x_ext, flow_y, 0.0),
            (x_ext, flow_y, 0.0),
            (0.2, 1.0, 0.8, 1.0),
            hide=False,
        )

        x_buccal_r = max(
            0.0, min(x_ext, x_ext * float(getattr(p, "sf_buccal_corridor_right", 0.0)))
        )
        x_buccal_l = max(
            -x_ext, min(0.0, -x_ext * float(getattr(p, "sf_buccal_corridor_left", 0.0)))
        )
        _line_local(
            "SMILE_FRAME2D_BUCCAL_R",
            (x_buccal_r, -0.35 * y_ext, 0.0),
            (x_buccal_r, 0.35 * y_ext, 0.0),
            (0.2, 0.8, 1.0, 1.0),
            hide=False,
        )
        _line_local(
            "SMILE_FRAME2D_BUCCAL_L",
            (x_buccal_l, -0.35 * y_ext, 0.0),
            (x_buccal_l, 0.35 * y_ext, 0.0),
            (0.2, 0.8, 1.0, 1.0),
            hide=False,
        )

        ratio_r = max(
            0.50, min(1.20, float(getattr(p, "sf_ratio_hw_right", 80.0)) / 100.0)
        )
        ratio_l = max(
            0.50, min(1.20, float(getattr(p, "sf_ratio_hw_left", 80.0)) / 100.0)
        )
        min_w = max(0.06 * x_ext, 1e-5)
        w_r = max(min_w, abs(x_buccal_r))
        w_l = max(min_w, abs(x_buccal_l))
        h_r = min(1.6 * y_ext, w_r * ratio_r)
        h_l = min(1.6 * y_ext, w_l * ratio_l)

        y_bot_nom = flow_y - 0.18 * y_ext
        y_bot_r = max(-0.90 * y_ext, min(0.90 * y_ext - h_r, y_bot_nom))
        y_bot_l = max(-0.90 * y_ext, min(0.90 * y_ext - h_l, y_bot_nom))
        y_top_r = y_bot_r + h_r
        y_top_l = y_bot_l + h_l

        _rect_local(
            "SMILE_FRAME2D_RATIO_BOX_R",
            0.0,
            w_r,
            y_bot_r,
            y_top_r,
            (1.0, 0.82, 0.2, 1.0),
            hide=False,
        )
        _rect_local(
            "SMILE_FRAME2D_RATIO_BOX_L",
            -w_l,
            0.0,
            y_bot_l,
            y_top_l,
            (1.0, 0.82, 0.2, 1.0),
            hide=False,
        )

        p.step2_done = True
        _set_min_design_step(p, 3)
        self.report({"INFO"}, "Frame 2D applied (rotation and guide overlays updated).")
        return {"FINISHED"}


class SMILE_OT_frame3d_apply(bpy.types.Operator):
    """Commit Smile Frame 3D scaffold settings and advance guided workflow."""

    bl_idname = "smile.frame3d_apply"
    bl_label = "Apply Frame 3D"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 3, "Frame 3D apply")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        scene = context.scene
        p = scene.smile_v2
        pts_patient = []
        source_mode = str(getattr(p, "sf_curve_source", "AUTO"))
        if source_mode == "SELECTED":
            cobj = bpy.data.objects.get(
                str(getattr(p, "sf_selected_curve_name", "")).strip()
            )
            if not cobj or cobj.type != "CURVE":
                self.report(
                    {"ERROR"},
                    "Selected curve not found. Pick a curve and click 'Use Active Curve'.",
                )
                return {"CANCELLED"}
            pts_patient = _sample_curve_world_points(cobj, max_points=120)
            if len(pts_patient) < 3:
                self.report(
                    {"ERROR"}, "Selected curve has insufficient points (need >= 3)."
                )
                return {"CANCELLED"}
        else:
            pts_patient = _collect_frame3d_points_from_teeth()
        if len(pts_patient) < 3:
            self.report({"ERROR"}, "Need at least 3 visible tooth points for 3D frame.")
            return {"CANCELLED"}

        if len(pts_patient) > 24:
            stride = max(1, len(pts_patient) // 24)
            pts_patient = [pts_patient[i] for i in range(0, len(pts_patient), stride)]
            if len(pts_patient) < 3:
                pts_patient = _collect_frame3d_points_from_teeth()[:3]

        n = len(pts_patient)
        c = (n - 1) * 0.5
        z0 = float(pts_patient[0].z)
        zn = float(pts_patient[-1].z)
        zc = float(pts_patient[int(round(c))].z)
        base_delta = zc - (0.5 * (z0 + zn))
        if abs(base_delta) < 1e-6:
            base_delta = -0.001
        ideal_scale = 0.6 + 0.8 * float(getattr(p, "sf_curve_accuracy", 0.5))
        ideal_delta = base_delta * ideal_scale

        ratio_r = max(0.70, min(0.90, float(getattr(p, "sf_ratio_hw_right", 80.0))))
        ratio_l = max(0.70, min(0.90, float(getattr(p, "sf_ratio_hw_left", 80.0))))
        corr_r = max(0.0, min(1.0, float(getattr(p, "sf_buccal_corridor_right", 0.5))))
        corr_l = max(0.0, min(1.0, float(getattr(p, "sf_buccal_corridor_left", 0.5))))
        if bool(getattr(p, "sf_symmetry_mode", False)):
            ratio_avg = 0.5 * (ratio_r + ratio_l)
            corr_avg = 0.5 * (corr_r + corr_l)
            ratio_r = ratio_l = ratio_avg
            corr_r = corr_l = corr_avg

        ratio_scale_r = max(0.75, min(1.25, ratio_r / 80.0))
        ratio_scale_l = max(0.75, min(1.25, ratio_l / 80.0))
        corridor_gain_r = 0.22 * corr_r
        corridor_gain_l = 0.22 * corr_l

        centroid = Vector((0.0, 0.0, 0.0))
        for pp in pts_patient:
            centroid += pp
        centroid /= float(max(1, n))
        span = (pts_patient[-1] - pts_patient[0]).length if n > 1 else 0.04
        half_span = max(1e-6, 0.5 * float(span))

        pts_ideal = []
        for i, pp in enumerate(pts_patient):
            t = float(i) / float(max(1, n - 1))
            z_lin = (1.0 - t) * z0 + t * zn
            u = 0.0 if c == 0 else (float(i) - c) / c
            bow = max(0.0, 1.0 - (u * u))
            side_amp = abs(u) ** 1.4
            is_right = bool(float(pp.x) >= float(centroid.x))
            ratio_scale_side = ratio_scale_r if is_right else ratio_scale_l
            corridor_gain_side = corridor_gain_r if is_right else corridor_gain_l

            to_center = Vector(
                (float(centroid.x - pp.x), float(centroid.y - pp.y), 0.0)
            )
            if to_center.length < 1e-8:
                to_center = Vector((-1.0 if is_right else 1.0, 0.0, 0.0))
            to_center.normalize()
            shift_mag = corridor_gain_side * half_span * side_amp
            pp_adj = pp + to_center * shift_mag

            z = z_lin + (ideal_delta * ratio_scale_side) * bow
            pts_ideal.append(Vector((float(pp_adj.x), float(pp_adj.y), float(z))))

        obj_patient = _get_or_create_polyline_curve(
            "SMILE_FRAME3D_Curve_Patient", pts_patient, COL_ARCH
        )
        obj_ideal = _get_or_create_polyline_curve(
            "SMILE_FRAME3D_Curve_Ideal", pts_ideal, COL_ARCH
        )
        try:
            obj_patient.color = (0.9, 0.2, 0.2, 1.0)
            obj_ideal.color = (0.2, 0.9, 0.2, 1.0)
        except Exception:
            pass
        obj_patient.show_in_front = True
        obj_ideal.show_in_front = True
        obj_ideal["SMILE_FRAME3D_HW_R"] = float(ratio_r)
        obj_ideal["SMILE_FRAME3D_HW_L"] = float(ratio_l)
        obj_ideal["SMILE_FRAME3D_BCORR_R"] = float(corr_r)
        obj_ideal["SMILE_FRAME3D_BCORR_L"] = float(corr_l)
        obj_ideal["SMILE_FRAME3D_CURVE_SOURCE"] = str(source_mode)

        grid_name = "SMILE_FRAME3D_GRID"
        grid_obj = bpy.data.objects.get(grid_name)
        if bool(getattr(p, "sf_grid_enabled", False)):
            if not grid_obj:
                mesh = bpy.data.meshes.new(f"{grid_name}_Mesh")
                steps = 16
                half = 1.0
                verts = []
                edges = []
                for i in range(steps + 1):
                    t = -half + (2.0 * half * float(i) / float(max(1, steps)))
                    a = len(verts)
                    verts.append((-half, t, 0.0))
                    b = len(verts)
                    verts.append((half, t, 0.0))
                    edges.append((a, b))
                    c = len(verts)
                    verts.append((t, -half, 0.0))
                    d = len(verts)
                    verts.append((t, half, 0.0))
                    edges.append((c, d))
                mesh.from_pydata(verts, edges, [])
                mesh.update()
                grid_obj = bpy.data.objects.new(grid_name, mesh)
                grid_obj.display_type = "WIRE"
                link_to_collection(grid_obj, ensure_collection(COL_PREVIEW))
            centroid = Vector((0.0, 0.0, 0.0))
            for pnt in pts_patient:
                centroid += pnt
            centroid /= float(max(1, len(pts_patient)))
            grid_obj.location = centroid
            span = (
                (pts_patient[-1] - pts_patient[0]).length
                if len(pts_patient) > 1
                else 0.04
            )
            scl = max(0.01, float(span) * 0.75)
            grid_obj.scale = (scl, scl, 1.0)
            grid_obj.hide_viewport = False
            grid_obj.hide_render = True
        elif grid_obj:
            grid_obj.hide_viewport = True
            grid_obj.hide_render = True

        mode = str(getattr(p, "sf_occlusal_curve_mode", "IDEAL"))
        superimpose = bool(getattr(p, "sf_superimpose", False))
        if superimpose:
            obj_patient.hide_viewport = False
            obj_ideal.hide_viewport = False
        elif mode == "IDEAL":
            obj_patient.hide_viewport = True
            obj_ideal.hide_viewport = False
        else:
            obj_patient.hide_viewport = False
            obj_ideal.hide_viewport = True

        p.step3_done = True
        _set_min_design_step(p, 4)
        self.report({"INFO"}, "Frame 3D applied (occlusal curve objects updated).")
        return {"FINISHED"}


class SMILE_OT_frame3d_select_curve(bpy.types.Operator):
    """Bind active curve object to Smile Frame 3D selected-curve source."""

    bl_idname = "smile.frame3d_select_curve"
    bl_label = "Use Active Curve"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 3, "Frame 3D curve selection")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        p = context.scene.smile_v2
        obj = context.view_layer.objects.active
        if not obj or obj.type != "CURVE":
            self.report(
                {"ERROR"}, "Select a curve object in the viewport/outliner first."
            )
            return {"CANCELLED"}
        pts = _sample_curve_world_points(obj, max_points=120)
        if len(pts) < 3:
            self.report({"ERROR"}, "Active curve does not contain enough points.")
            return {"CANCELLED"}
        p.sf_selected_curve_name = str(obj.name)
        p.sf_curve_source = "SELECTED"
        self.report({"INFO"}, f"Selected 3D curve source: {obj.name} ({len(pts)} pts)")
        return {"FINISHED"}


class SMILE_OT_frame3d_apply_to_teeth(bpy.types.Operator):
    """Apply ideal Frame3D curve as a positioning target for teeth objects."""

    bl_idname = "smile.frame3d_apply_to_teeth"
    bl_label = "Apply 3D to Teeth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 3, "Apply 3D to teeth")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}

        scene = context.scene
        p = scene.smile_v2
        curve_obj = bpy.data.objects.get("SMILE_FRAME3D_Curve_Ideal")
        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"ERROR"}, "Missing ideal 3D curve. Run 'Apply 3D' first.")
            return {"CANCELLED"}
        curve_pts = _sample_curve_world_points(curve_obj, max_points=240)
        if len(curve_pts) < 2:
            self.report({"ERROR"}, "Ideal curve has insufficient points.")
            return {"CANCELLED"}

        col = bpy.data.collections.get(COL_TEETH)
        if not col:
            self.report({"ERROR"}, "No Teeth collection found.")
            return {"CANCELLED"}

        h_gain = max(
            0.0, min(1.0, float(getattr(p, "sf_apply3d_height_strength", 0.8)))
        )
        xy_gain = max(0.0, min(1.0, float(getattr(p, "sf_apply3d_xy_strength", 0.8))))
        use_rot = bool(getattr(p, "sf_apply3d_rotate_enabled", True))
        rot_gain = max(
            0.0, min(1.0, float(getattr(p, "sf_apply3d_rotate_strength", 0.4)))
        )
        max_rot = math.radians(
            max(0.1, float(getattr(p, "sf_apply3d_max_rotate_deg", 4.0)))
        )
        preview_only = bool(getattr(p, "sf_apply3d_preview_only", False))
        max_move = max(
            0.0001, float(getattr(p, "sf_apply3d_max_move_mm", 5.0)) / 1000.0
        )

        def _signed_angle_xy(a: Vector, b: Vector):
            return math.atan2((a.x * b.y) - (a.y * b.x), (a.x * b.x) + (a.y * b.y))

        _clear_frame3d_preview_objects()

        moved = 0
        total_mm = 0.0
        rotated = 0
        total_rot_deg = 0.0
        preview_count = 0
        per_tooth = []
        for obj in col.objects:
            if not obj or obj.type != "MESH" or obj.hide_viewport:
                continue
            tid = parse_tooth_id_from_name(obj.name)
            try:
                incisal_world, _, _ = detect_incisal_edge_by_geometry(obj)
            except Exception:
                incisal_world = obj.matrix_world.translation.copy()

            target_pt, target_tan, _ = _closest_point_and_tangent_on_polyline_world(
                incisal_world, curve_pts
            )
            if target_pt is None:
                continue

            delta = target_pt - incisal_world
            move = Vector(
                (
                    float(delta.x) * xy_gain,
                    float(delta.y) * xy_gain,
                    float(delta.z) * h_gain,
                )
            )
            mlen_raw = move.length
            mlen = mlen_raw
            move_clamped = False
            if mlen > max_move:
                move = move.normalized() * max_move
                mlen = max_move
                move_clamped = True

            raw_ang = 0.0
            ang = 0.0
            rot_clamped = False
            if use_rot and rot_gain > 0.0:
                cur_x = obj.matrix_world.to_3x3() @ Vector((1.0, 0.0, 0.0))
                cur_xy = Vector((float(cur_x.x), float(cur_x.y), 0.0))
                tan_xy = Vector((float(target_tan.x), float(target_tan.y), 0.0))
                if cur_xy.length > 1e-8 and tan_xy.length > 1e-8:
                    cur_xy.normalize()
                    tan_xy.normalize()
                    ang_a = _signed_angle_xy(cur_xy, tan_xy)
                    ang_b = _signed_angle_xy(cur_xy, -tan_xy)
                    raw_ang = (ang_a if abs(ang_a) <= abs(ang_b) else ang_b) * rot_gain
                    ang = max(-max_rot, min(max_rot, raw_ang))
                    rot_clamped = abs(raw_ang) > max_rot + 1e-9

            if mlen < 1e-6 and abs(ang) < 1e-6:
                continue
            if preview_only:
                safe_name = re.sub(r"[^A-Za-z0-9_]+", "_", str(obj.name))
                if mlen >= 1e-6:
                    delta_name = f"SMILE_FRAME3D_DELTA_{safe_name}"
                    lobj = _get_or_create_polyline_curve(
                        delta_name, [incisal_world, incisal_world + move], COL_PREVIEW
                    )
                    try:
                        lobj.color = (1.0, 0.6, 0.1, 1.0)
                    except Exception:
                        pass
                    lobj.show_in_front = True
                    preview_count += 1
                if abs(ang) >= 1e-6:
                    tan_len = max(0.0015, 0.2 * max_move)
                    tan_name = f"SMILE_FRAME3D_TAN_{safe_name}"
                    tan_dir = Vector((float(target_tan.x), float(target_tan.y), 0.0))
                    if tan_dir.length < 1e-8:
                        tan_dir = Vector((1.0, 0.0, 0.0))
                    tan_dir.normalize()
                    center = target_pt
                    p0 = center - tan_dir * tan_len
                    p1 = center + tan_dir * tan_len
                    tobj = _get_or_create_polyline_curve(
                        tan_name, [p0, p1], COL_PREVIEW
                    )
                    try:
                        tobj.color = (0.2, 1.0, 0.9, 1.0)
                    except Exception:
                        pass
                    tobj.show_in_front = True
                    preview_count += 1
                per_tooth.append(
                    {
                        "tooth_name": str(obj.name),
                        "tooth_id": int(tid) if tid else None,
                        "move_mm": float(mlen * 1000.0),
                        "rot_deg": float(abs(math.degrees(float(ang)))),
                        "move_clamped": bool(move_clamped),
                        "rot_clamped": bool(rot_clamped),
                        "preview_only": True,
                    }
                )
                continue

            if KEY_FRAME3D_ORIG_MW not in obj:
                obj[KEY_FRAME3D_ORIG_MW] = json.dumps(
                    [[float(c) for c in row] for row in obj.matrix_world],
                    separators=(",", ":"),
                )

            if mlen >= 1e-6:
                mw = obj.matrix_world.copy()
                mw.translation = mw.translation + move
                obj.matrix_world = mw
                moved += 1
                total_mm += float(mlen * 1000.0)

            if abs(ang) >= 1e-6:
                mw2 = obj.matrix_world.copy()
                pivot = mw2.translation.copy()
                rot_m = Matrix.Rotation(float(ang), 4, Vector((0.0, 0.0, 1.0)))
                obj.matrix_world = (
                    Matrix.Translation(pivot) @ rot_m @ Matrix.Translation(-pivot) @ mw2
                )
                rotated += 1
                total_rot_deg += abs(math.degrees(float(ang)))
            per_tooth.append(
                {
                    "tooth_name": str(obj.name),
                    "tooth_id": int(tid) if tid else None,
                    "move_mm": float(mlen * 1000.0),
                    "rot_deg": float(abs(math.degrees(float(ang)))),
                    "move_clamped": bool(move_clamped),
                    "rot_clamped": bool(rot_clamped),
                    "preview_only": False,
                }
            )

        if preview_only:
            if preview_count <= 0:
                _store_frame3d_apply_summary(
                    scene,
                    {
                        "mode": "preview",
                        "status": "empty",
                        "preview_objects": int(preview_count),
                        "tooth_metrics": [],
                    },
                )
                self.report({"WARNING"}, "Preview produced no visible deltas.")
                return {"CANCELLED"}
            _store_frame3d_apply_summary(
                scene,
                {
                    "mode": "preview",
                    "status": "ok",
                    "preview_objects": int(preview_count),
                    "tooth_count": int(len(per_tooth)),
                    "avg_move_mm": float(
                        sum(t["move_mm"] for t in per_tooth) / max(1, len(per_tooth))
                    ),
                    "avg_rot_deg": float(
                        sum(t["rot_deg"] for t in per_tooth) / max(1, len(per_tooth))
                    ),
                    "move_clamped_count": int(
                        sum(1 for t in per_tooth if t.get("move_clamped"))
                    ),
                    "rot_clamped_count": int(
                        sum(1 for t in per_tooth if t.get("rot_clamped"))
                    ),
                    "tooth_metrics": per_tooth[:128],
                },
            )
            self.report(
                {"INFO"}, f"Preview generated: {preview_count} Frame3D guide object(s)."
            )
            return {"FINISHED"}

        if moved <= 0 and rotated <= 0:
            _store_frame3d_apply_summary(
                scene,
                {
                    "mode": "apply",
                    "status": "no_effect",
                    "moved_count": 0,
                    "rotated_count": 0,
                    "tooth_metrics": per_tooth[:128],
                },
            )
            self.report({"WARNING"}, "No visible teeth moved/rotated.")
            return {"CANCELLED"}

        p.step3_done = True
        _set_min_design_step(p, 4)
        avg_move = (total_mm / moved) if moved > 0 else 0.0
        avg_rot = (total_rot_deg / rotated) if rotated > 0 else 0.0
        _store_frame3d_apply_summary(
            scene,
            {
                "mode": "apply",
                "status": "ok",
                "moved_count": int(moved),
                "rotated_count": int(rotated),
                "avg_move_mm": float(avg_move),
                "avg_rot_deg": float(avg_rot),
                "move_clamped_count": int(
                    sum(1 for t in per_tooth if t.get("move_clamped"))
                ),
                "rot_clamped_count": int(
                    sum(1 for t in per_tooth if t.get("rot_clamped"))
                ),
                "tooth_count": int(len(per_tooth)),
                "tooth_metrics": per_tooth[:128],
            },
        )
        self.report(
            {"INFO"},
            f"Applied 3D targets: move {moved} teeth (avg {avg_move:.2f} mm), rotate {rotated} teeth (avg {avg_rot:.2f} deg).",
        )
        return {"FINISHED"}


class SMILE_OT_frame3d_clear_preview(bpy.types.Operator):
    """Clear temporary Frame3D preview vectors/tangent guides."""

    bl_idname = "smile.frame3d_clear_preview"
    bl_label = "Clear 3D Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = _clear_frame3d_preview_objects()
        self.report({"INFO"}, f"Removed {removed} preview object(s).")
        return {"FINISHED"}


class SMILE_OT_frame3d_export_summary(bpy.types.Operator):
    """Export latest Frame3D apply summary to JSON or CSV."""

    bl_idname = "smile.frame3d_export_summary"
    bl_label = "Export Frame3D Summary"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")
    export_format: bpy.props.EnumProperty(
        name="Format",
        items=[
            ("JSON", "JSON", "Structured summary"),
            ("CSV", "CSV", "Per-tooth metrics table"),
        ],
        default="JSON",
    )

    def invoke(self, context, event):
        scene = context.scene
        summary = _get_frame3d_apply_summary(scene)
        if not isinstance(summary, dict) or not summary:
            self.report(
                {"ERROR"}, "No Frame3D summary available. Run apply/preview first."
            )
            return {"CANCELLED"}
        ext = ".json" if str(self.export_format) == "JSON" else ".csv"
        self.filepath = bpy.path.abspath(f"//frame3d_apply_summary{ext}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_format", text="Format")

    def execute(self, context):
        scene = context.scene
        summary = _get_frame3d_apply_summary(scene)
        if not isinstance(summary, dict) or not summary:
            self.report({"ERROR"}, "No Frame3D summary available.")
            return {"CANCELLED"}

        target = str(self.filepath or "").strip()
        if not target:
            self.report({"ERROR"}, "Choose an output filepath.")
            return {"CANCELLED"}

        fmt = str(self.export_format).upper()
        low = target.lower()
        if low.endswith(".csv"):
            fmt = "CSV"
        elif low.endswith(".json"):
            fmt = "JSON"
        else:
            target = target + (".csv" if fmt == "CSV" else ".json")

        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        rows = _frame3d_summary_rows(summary)

        try:
            if fmt == "CSV":
                with open(target, "w", newline="", encoding="utf-8") as f:
                    fieldnames = [
                        "scene_name",
                        "mode",
                        "status",
                        "summary_timestamp_utc",
                        "tooth_id",
                        "tooth_name",
                        "move_mm",
                        "rot_deg",
                        "move_clamped",
                        "rot_clamped",
                        "preview_only",
                        "moved_count",
                        "rotated_count",
                        "avg_move_mm",
                        "avg_rot_deg",
                        "move_clamped_count",
                        "rot_clamped_count",
                    ]
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    base = {
                        "scene_name": str(scene.name),
                        "mode": str(summary.get("mode", "")),
                        "status": str(summary.get("status", "")),
                        "summary_timestamp_utc": str(summary.get("timestamp_utc", "")),
                        "moved_count": int(summary.get("moved_count", 0)),
                        "rotated_count": int(summary.get("rotated_count", 0)),
                        "avg_move_mm": float(summary.get("avg_move_mm", 0.0)),
                        "avg_rot_deg": float(summary.get("avg_rot_deg", 0.0)),
                        "move_clamped_count": int(summary.get("move_clamped_count", 0)),
                        "rot_clamped_count": int(summary.get("rot_clamped_count", 0)),
                    }
                    if rows:
                        for r in rows:
                            out = dict(base)
                            out.update(r)
                            w.writerow(out)
                    else:
                        out = dict(base)
                        out.update(
                            {
                                "tooth_id": "",
                                "tooth_name": "",
                                "move_mm": 0.0,
                                "rot_deg": 0.0,
                                "move_clamped": False,
                                "rot_clamped": False,
                                "preview_only": bool(
                                    summary.get("mode", "") == "preview"
                                ),
                            }
                        )
                        w.writerow(out)
            else:
                payload = {
                    "exported_utc": datetime.utcnow().isoformat() + "Z",
                    "scene_name": str(scene.name),
                    "frame3d_summary": summary,
                    "tooth_metrics": rows,
                }
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, sort_keys=True)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to export summary: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Frame3D summary exported: {target}")
        return {"FINISHED"}


class SMILE_OT_frame3d_reset_teeth(bpy.types.Operator):
    """Restore tooth transforms captured before Apply 3D to Teeth."""

    bl_idname = "smile.frame3d_reset_teeth"
    bl_label = "Reset 3D Teeth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        col = bpy.data.collections.get(COL_TEETH)
        if not col:
            self.report({"ERROR"}, "No Teeth collection found.")
            return {"CANCELLED"}

        restored = 0
        for obj in col.objects:
            if not obj or obj.type != "MESH":
                continue
            raw = obj.get(KEY_FRAME3D_ORIG_MW)
            if raw is None:
                continue
            m = _matrix_from_prop(raw)
            if m is None:
                continue
            obj.matrix_world = m
            try:
                del obj[KEY_FRAME3D_ORIG_MW]
            except Exception:
                pass
            restored += 1

        if restored <= 0:
            _store_frame3d_apply_summary(
                context.scene,
                {
                    "mode": "reset",
                    "status": "empty",
                    "restored_count": 0,
                },
            )
            self.report({"WARNING"}, "No saved Frame3D transforms to restore.")
            return {"CANCELLED"}
        _store_frame3d_apply_summary(
            context.scene,
            {
                "mode": "reset",
                "status": "ok",
                "restored_count": int(restored),
            },
        )
        self.report({"INFO"}, f"Reset {restored} teeth to pre-Frame3D transforms.")
        return {"FINISHED"}


class SMILE_OT_crown_shape_edit_start(bpy.types.Operator):
    """Start B4D-style crown shape edit session on active restoration mesh."""

    bl_idname = "smile.crown_shape_edit_start"
    bl_label = "Start Crown Shape Edit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select an imported crown/tooth mesh first.")
            return {"CANCELLED"}

        p = context.scene.smile_v2
        global _CROWN_EDIT_VIEW_STATE
        _CROWN_EDIT_VIEW_STATE = {}
        for win, area, sp in _collect_view3d_spaces(context):
            try:
                key = f"{int(win.as_pointer())}:{int(area.as_pointer())}"
                _CROWN_EDIT_VIEW_STATE[key] = {
                    "show_wireframes": bool(
                        getattr(sp.overlay, "show_wireframes", False)
                    ),
                    "show_xray": bool(getattr(sp.shading, "show_xray", False)),
                    "xray_alpha": float(getattr(sp.shading, "xray_alpha", 0.5)),
                }
                sp.overlay.show_wireframes = bool(
                    getattr(p, "crown_edit_show_wire_overlay", True)
                )
                sp.shading.show_xray = bool(getattr(p, "crown_edit_show_xray", True))
                sp.shading.xray_alpha = float(getattr(p, "crown_edit_xray_alpha", 0.40))
                area.tag_redraw()
            except Exception:
                pass

        try:
            obj["SMILE_CROWN_PREV_SHOW_WIRE"] = bool(getattr(obj, "show_wire", False))
            obj["SMILE_CROWN_PREV_SHOW_ALL_EDGES"] = bool(
                getattr(obj, "show_all_edges", False)
            )
            obj["SMILE_CROWN_PREV_IN_FRONT"] = bool(
                getattr(obj, "show_in_front", False)
            )
        except Exception:
            pass
        try:
            obj.show_wire = True
            obj.show_all_edges = True
            obj.show_in_front = bool(getattr(p, "crown_edit_show_in_front", True))
        except Exception:
            pass

        outline_name = ""
        if bool(getattr(p, "crown_edit_show_outline", True)):
            curve = _find_margin_curve_for_object(context, obj)
            if curve and _apply_crown_outline_style(
                curve,
                thickness_mm=float(getattr(p, "crown_edit_outline_thickness_mm", 0.05)),
            ):
                outline_name = curve.name

        ensure_active(obj)
        try:
            if obj.mode != "SCULPT":
                bpy.ops.object.mode_set(mode="SCULPT")
        except Exception:
            self.report({"ERROR"}, "Could not enter Sculpt mode.")
            return {"CANCELLED"}

        selected = _crown_edit_apply_brush(
            context, p, direction=str(getattr(p, "crown_edit_direction", "PULL"))
        )
        context.scene[KEY_CROWN_EDIT_ACTIVE_OBJ] = obj.name
        if outline_name:
            context.scene[KEY_CROWN_EDIT_OUTLINE] = outline_name

        nm = selected.name if selected else "default"
        self.report(
            {"INFO"}, f"Crown shape edit started on '{obj.name}' (brush: {nm})."
        )
        return {"FINISHED"}


class SMILE_OT_crown_shape_edit_stop(bpy.types.Operator):
    """Stop crown shape edit and restore viewport state."""

    bl_idname = "smile.crown_shape_edit_stop"
    bl_label = "Stop Crown Shape Edit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        obj_name = str(scene.get(KEY_CROWN_EDIT_ACTIVE_OBJ, "") or "")
        obj = (
            bpy.data.objects.get(obj_name)
            if obj_name
            else context.view_layer.objects.active
        )
        if obj and obj.type == "MESH":
            ensure_active(obj)
        try:
            if context.mode == "SCULPT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        if obj and obj.type == "MESH":
            try:
                if "SMILE_CROWN_PREV_SHOW_WIRE" in obj:
                    obj.show_wire = bool(obj["SMILE_CROWN_PREV_SHOW_WIRE"])
                    del obj["SMILE_CROWN_PREV_SHOW_WIRE"]
                if "SMILE_CROWN_PREV_SHOW_ALL_EDGES" in obj:
                    obj.show_all_edges = bool(obj["SMILE_CROWN_PREV_SHOW_ALL_EDGES"])
                    del obj["SMILE_CROWN_PREV_SHOW_ALL_EDGES"]
                if "SMILE_CROWN_PREV_IN_FRONT" in obj:
                    obj.show_in_front = bool(obj["SMILE_CROWN_PREV_IN_FRONT"])
                    del obj["SMILE_CROWN_PREV_IN_FRONT"]
            except Exception:
                pass

        global _CROWN_EDIT_VIEW_STATE
        for win, area, sp in _collect_view3d_spaces(context):
            key = f"{int(win.as_pointer())}:{int(area.as_pointer())}"
            st = _CROWN_EDIT_VIEW_STATE.get(key)
            if not st:
                continue
            try:
                sp.overlay.show_wireframes = bool(st.get("show_wireframes", False))
                sp.shading.show_xray = bool(st.get("show_xray", False))
                sp.shading.xray_alpha = float(st.get("xray_alpha", 0.5))
                area.tag_redraw()
            except Exception:
                pass
        _CROWN_EDIT_VIEW_STATE = {}

        try:
            if KEY_CROWN_EDIT_ACTIVE_OBJ in scene:
                del scene[KEY_CROWN_EDIT_ACTIVE_OBJ]
            if KEY_CROWN_EDIT_OUTLINE in scene:
                del scene[KEY_CROWN_EDIT_OUTLINE]
        except Exception:
            pass

        self.report({"INFO"}, "Crown shape edit stopped.")
        return {"FINISHED"}


class SMILE_OT_crown_shape_edit_apply_brush(bpy.types.Operator):
    """Apply selected crown edit brush/size/strength in current sculpt session."""

    bl_idname = "smile.crown_shape_edit_apply_brush"
    bl_label = "Apply Crown Brush"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh restoration first.")
            return {"CANCELLED"}
        try:
            if obj.mode != "SCULPT":
                bpy.ops.object.mode_set(mode="SCULPT")
        except Exception:
            self.report({"ERROR"}, "Could not enter Sculpt mode.")
            return {"CANCELLED"}

        p = context.scene.smile_v2
        selected = _crown_edit_apply_brush(
            context, p, direction=str(getattr(p, "crown_edit_direction", "PULL"))
        )
        if bool(getattr(p, "crown_edit_show_outline", True)):
            curve = _find_margin_curve_for_object(context, obj)
            if curve:
                _apply_crown_outline_style(
                    curve,
                    thickness_mm=float(
                        getattr(p, "crown_edit_outline_thickness_mm", 0.05)
                    ),
                )
        if not selected:
            self.report(
                {"WARNING"}, "Brush apply fallback used (no matching brush found)."
            )
            return {"FINISHED"}
        self.report({"INFO"}, f"Crown brush set: {selected.name}.")
        return {"FINISHED"}


class SMILE_OT_crown_shape_edit_set_direction(bpy.types.Operator):
    """Quick pull/push direction for crown sculpting."""

    bl_idname = "smile.crown_shape_edit_set_direction"
    bl_label = "Set Crown Push/Pull"
    bl_options = {"REGISTER", "UNDO"}

    direction: bpy.props.EnumProperty(
        name="Direction",
        items=[
            ("PULL", "Pull", "Outward/additive"),
            ("PUSH", "Push", "Inward/subtractive"),
        ],
        default="PULL",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        p.crown_edit_direction = str(self.direction)
        if context.mode == "SCULPT":
            _crown_edit_apply_brush(context, p, direction=str(self.direction))
        self.report({"INFO"}, f"Crown direction: {self.direction}.")
        return {"FINISHED"}


class SMILE_OT_crown_shape_edit_set_mode(bpy.types.Operator):
    """Quick mode switch for crown shape workflow."""

    bl_idname = "smile.crown_shape_edit_set_mode"
    bl_label = "Set Crown Edit Mode"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ("SCULPT", "Edit Mesh", "Sculpt mesh directly with mouse drag"),
            ("OBJECT", "Object Mode", "Exit sculpt and inspect"),
        ],
        default="SCULPT",
    )

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}
        ensure_active(obj)
        try:
            bpy.ops.object.mode_set(mode=str(self.mode))
            if str(self.mode) == "SCULPT":
                _crown_edit_apply_brush(context, context.scene.smile_v2)
        except Exception as e:
            self.report({"ERROR"}, f"Mode switch failed: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


def _draw_crown_edit_section(ebox, p):
    ebox.label(
        text="Select tooth/crown mesh, click Start Edit, then drag to shape.",
        icon="INFO",
    )
    row = ebox.row(align=True)
    row.scale_y = 1.15
    row.operator(
        "smile.crown_shape_edit_start", text="Start Shaping", icon="SCULPTMODE_HLT"
    )
    row.operator(
        "smile.crown_shape_edit_stop", text="Stop Shaping", icon="OBJECT_DATAMODE"
    )

    row = ebox.row(align=True)
    op = row.operator(
        "smile.crown_shape_edit_set_mode", text="Sculpt Mode", icon="EDITMODE_HLT"
    )
    op.mode = "SCULPT"
    op = row.operator(
        "smile.crown_shape_edit_set_mode", text="View Mode", icon="OBJECT_DATAMODE"
    )
    op.mode = "OBJECT"

    row = ebox.row(align=True)
    row.prop(p, "crown_edit_brush", text="Tool")
    row.prop(p, "crown_edit_response_profile", text="Feel")
    row.prop(p, "crown_edit_direction", text="")
    ebox.prop(p, "crown_edit_brush_size", text="Tool Size")
    ebox.prop(p, "crown_edit_brush_strength", text="Tool Strength", slider=True)
    row = ebox.row(align=True)
    row.prop(p, "crown_edit_auto_smooth", text="Auto Smooth", slider=True)
    row.prop(p, "crown_edit_hardness", text="Edge Hardness", slider=True)
    row = ebox.row(align=True)
    row.prop(p, "crown_edit_normal_radius_factor", text="Smoothing Radius")
    row.prop(p, "crown_edit_tip_roundness", text="Tip Roundness", slider=True)
    ebox.prop(p, "crown_edit_front_faces_only", text="Edit Front Surface Only")

    row = ebox.row(align=True)
    op = row.operator(
        "smile.crown_shape_edit_set_direction", text="Pull Out", icon="TRIA_UP"
    )
    op.direction = "PULL"
    op = row.operator(
        "smile.crown_shape_edit_set_direction", text="Push In", icon="TRIA_DOWN"
    )
    op.direction = "PUSH"
    row.operator(
        "smile.crown_shape_edit_apply_brush",
        text="Apply Current Tool",
        icon="BRUSH_DATA",
    )

    row = ebox.row(align=True)
    row.prop(p, "crown_edit_show_outline", text="Outline")
    row.prop(p, "crown_edit_show_wire_overlay", text="Wire")
    row.prop(p, "crown_edit_show_xray", text="X-Ray")
    ebox.prop(p, "crown_edit_outline_thickness_mm", text="Outline Thickness (mm)")
    ebox.prop(p, "crown_edit_xray_alpha", text="X-Ray Alpha")
    ebox.prop(p, "crown_edit_show_in_front", text="Show In Front")


def _autodie_queue_count(scene):
    mockup = _get_mockup()
    if mockup and hasattr(mockup, "_autodie_queue_count"):
        try:
            return mockup._autodie_queue_count(scene)
        except Exception:
            pass
    return 0


def _import_calib_arch_for_tooth_id(tooth_id: int) -> str:
    mockup = _get_mockup()
    if mockup and hasattr(mockup, "_import_calib_arch_for_tooth_id"):
        try:
            return mockup._import_calib_arch_for_tooth_id(tooth_id)
        except Exception:
            pass
    return "MAX"


def _has_import_arch_reference(scene, arch: str) -> bool:
    mockup = _get_mockup()
    if mockup and hasattr(mockup, "_has_import_arch_reference"):
        try:
            return mockup._has_import_arch_reference(scene, arch)
        except Exception:
            pass
    return False


def _has_import_tooth_lm3_local(obj) -> bool:
    mockup = _get_mockup()
    if mockup and hasattr(mockup, "_has_import_tooth_lm3_local"):
        try:
            return mockup._has_import_tooth_lm3_local(obj)
        except Exception:
            pass
    return False


def _has_import_scan_lm3(scene, tooth_id: int) -> bool:
    mockup = _get_mockup()
    if mockup and hasattr(mockup, "_has_import_scan_lm3"):
        try:
            return mockup._has_import_scan_lm3(scene, tooth_id)
        except Exception:
            pass
    return False


def _ui_fold_header(parent, prop_name, label, icon="NONE"):
    is_open = bool(getattr(parent, prop_name, False))
    tri = "TRIA_DOWN" if is_open else "TRIA_RIGHT"
    row = parent.row(align=True)
    op = row.operator("wm.context_toggle", text=label, icon=tri, emboss=False)
    op.data_path = f"scene.smile_v2.{prop_name}"
    if icon and icon != "NONE":
        row.label(text="", icon=icon)
    return is_open


def draw_veneer_import_tab(context, layout, props):
    """Draw the VENEER_IMPORT tab UI."""
    scene = context.scene
    p = props

    def fold_header(parent, prop_name, label, icon="NONE"):
        return _ui_fold_header(parent, prop_name, label, icon)

    layout.label(text="Tab 6: Crown/Veneer Lab (Step-by-Step)", icon="TOOL_SETTINGS")
    layout.label(
        text="Work top to bottom. If one step fails, fix that step first.", icon="INFO"
    )

    tid_cal = int(getattr(p, "import_calibration_tooth_id", 0) or 0)
    arch_cal = _import_calib_arch_for_tooth_id(tid_cal if tid_cal > 0 else 8)
    ref_ok = _has_import_arch_reference(scene, arch_cal)
    active_tooth = (
        context.view_layer.objects.active
        if context.view_layer.objects.active
        and context.view_layer.objects.active.type == "MESH"
        else None
    )
    src_ok = False
    if active_tooth and _has_import_tooth_lm3_local(active_tooth):
        atid = parse_tooth_id_from_name(active_tooth.name) or int(
            active_tooth.get("SMILE_TOOTH_ID", 0) or 0
        )
        src_ok = atid == tid_cal

    if fold_header(
        layout,
        "ui_tab6_sec_library",
        "Import Tooth Library + Place Teeth",
        icon="ASSET_MANAGER",
    ):
        box = layout.box()
        box.label(
            text="Pick tooth files, import them, then align to scan.", icon="INFO"
        )
        box.operator(
    # "smile.import_biometric_library",  # MISSING OPERATOR
            text="1) Load Tooth Library Folder",
            icon="FILE_FOLDER",
        )
        row = box.row(align=True)
    # row.operator("smile.cycle_library", text="<").direction = "PREV"  # MISSING OPERATOR
        row.prop(p, "active_library_name", text="")
    # row.operator("smile.cycle_library", text=">").direction = "NEXT"  # MISSING OPERATOR
        pr = box.row(align=True)
    # pr.operator("smile.select_teeth_preset", text="All").preset = "ALL"  # MISSING OPERATOR
    # pr.operator("smile.select_teeth_preset", text="Max Ant").preset = "ANT_UP"  # MISSING OPERATOR
    # pr.operator("smile.select_teeth_preset", text="Man Ant").preset = "ANT_LOW"  # MISSING OPERATOR
    # pr.operator("smile.select_teeth_preset", text="None").preset = "NONE"  # MISSING OPERATOR
        box.template_list(
            "SMILE_UL_asset_list",
            "",
            p,
            "library_assets",
            p,
            "active_asset_index",
            rows=5,
        )
        row = box.row(align=True)
        row.operator(
    # "smile.import_selected_teeth",  # MISSING OPERATOR
            text="2) Import Selected Teeth",
            icon="IMPORT",
        )
        row.operator(
            "smile.import_multi_veneer_set",
            text="Import Multi-Tooth File Set",
            icon="MESH_GRID",
        )
        row = box.row(align=True)
        row.operator(
            "smile.align_multi_veneer_set",
            text="Auto-Align Imported Set",
            icon="CON_TRANSFORM_CACHE",
        )
        row.operator(
    # "smile.auto_align_library_tooth",  # MISSING OPERATOR
            text="Align Selected Tooth",
            icon="OBJECT_ORIGIN",
        )
        row = box.row(align=True)
        row.prop(p, "align_set_mdc_first", text="Try 3-Point Match First")
        row.prop(p, "align_set_fallback_seed_roi", text="Use Seed Fallback")

        seed_box = box.box()
        seed_box.label(text="Backup Seed Tools (if auto-align misses)", icon="TRACKER")
        row = seed_box.row(align=True)
        row.prop(p, "import_calibration_tooth_id", text="Tooth #")
        row.prop(p, "seed_marker_size", text="Seed Size")
        row = seed_box.row(align=True)
        op = row.operator(
    # "smile.place_segmentation_seed", text="Place Seed on Scan", icon="TRACKING"  # MISSING OPERATOR
        )
        op.tooth_id = int(
            getattr(p, "import_calibration_tooth_id", 0)
            or getattr(p, "target_tooth_id", 8)
            or 8
        )
    # row.operator("smile.clear_segmentation_seeds", text="Clear Seeds", icon="TRASH")  # MISSING OPERATOR
        seed_box.label(
            text="Select scan first, then click the spot where tooth should sit.",
            icon="INFO",
        )

    if fold_header(
        layout,
        "ui_tab6_sec_mdc",
        "3-Point Matching (M-D-C) Setup",
        icon="ORIENTATION_GIMBAL",
    ):
        cbox = layout.box()
        cbox.label(
            text="Use 3 points to match imported tooth to scan: Mesial, Distal, Cervical.",
            icon="INFO",
        )

        sbox = cbox.box()
        sbox.label(text="Single-Tooth 3-Point Match", icon="OBJECT_DATA")
        sbox.prop(p, "import_calibration_tooth_id", text="Tooth #")
        scan_ok = _has_import_scan_lm3(scene, tid_cal if tid_cal > 0 else 0)
        sbox.label(
            text=f"{arch_cal} Arch Ref: {'Saved' if ref_ok else 'Not set'}",
            icon="CHECKMARK" if ref_ok else "INFO",
        )
        sbox.label(
            text=f"Active T#{tid_cal} MDC: {'Saved' if src_ok else 'Not set'}",
            icon="CHECKMARK" if src_ok else "INFO",
        )
        sbox.label(
            text=f"Scan T#{tid_cal} M-D-C: {'Saved' if scan_ok else 'Not set'}",
            icon="CHECKMARK" if scan_ok else "INFO",
        )
        row = sbox.row(align=True)
        op = row.operator(
            "smile.capture_arch_reference_mdc", text="1) Mark Arch Midline + Cervical"
        )
        op.arch = "AUTO"
        op = row.operator("smile.clear_arch_reference_mdc", text="Clear Arch Ref")
        op.arch = "AUTO"
        row = sbox.row(align=True)
        row.operator(
            "smile.capture_import_tooth_landmarks_3pt",
            text="2) Mark Active Tooth (M-D-C)",
            icon="TRACKER",
        )
        row.operator(
            "smile.clear_import_tooth_landmarks_3pt",
            text="Clear Tooth Points",
            icon="CANCEL",
        )
        row = sbox.row(align=True)
        row.operator(
            "smile.capture_scan_landmarks_3pt",
            text="3) Mark Scan (M-D-C)",
            icon="MESH_DATA",
        )
        row.operator(
            "smile.clear_import_scan_landmarks_3pt", text="Clear Scan Points", icon="CANCEL"
        )
        row = sbox.row(align=True)
        op = row.operator(
            "smile.align_imported_to_scan_landmarks",
            text="4) Align Active Tooth to Scan",
            icon="CON_TRACKTO",
        )
        op.scope = "ACTIVE"
        op.with_scaling = False
        sbox.label(
            text="For one-piece scan, click M-D-C directly on scan surface.",
            icon="INFO",
        )
        sbox.label(text="Saved scan points are reused automatically.", icon="DOT")

        mbox = cbox.box()
        mbox.label(text="Multi-Tooth 3-Point Match", icon="OUTLINER_COLLECTION")
        row = mbox.row(align=True)
        row.operator(
            "smile.refresh_imported_mdc_list",
            text="Refresh Imported Tooth List",
            icon="FILE_REFRESH",
        )
        row.operator(
            "smile.import_multi_veneer_set",
            text="Import Multi-Tooth Set",
            icon="IMPORT",
        )
        mbox.template_list(
            "SMILE_UL_imported_mdc_list",
            "",
            p,
            "imported_mdc_items",
            p,
            "imported_mdc_active_index",
            rows=5,
        )
        row = mbox.row(align=True)
        row.operator("smile.select_imported_mdc_item", text="Select Tooth from List")
        row.operator(
            "smile.mark_imported_mdc_from_list", text="Mark Tooth M-D-C (List)"
        )
        row = mbox.row(align=True)
        row.operator(
            "smile.capture_scan_landmarks_3pt",
            text="Mark Scan M-D-C (List)",
            icon="MESH_DATA",
        )
        row.operator(
            "smile.clear_import_scan_landmarks_3pt", text="Clear Scan Points", icon="CANCEL"
        )
        row = mbox.row(align=True)
        row.operator(
            "smile.align_imported_to_scan_landmarks", text="Align Selected Tooth"
        )
        row.operator(
            "smile.align_multi_veneer_set",
            text="Align Whole Imported Set",
            icon="CON_TRANSFORM_CACHE",
        )
        row = mbox.row(align=True)
        row.prop(p, "align_set_mdc_first", text="Try 3-Point Match First")
        row.prop(p, "align_set_fallback_seed_roi", text="Use Seed Fallback")

    if fold_header(layout, "ui_tab6_sec_autodie", "Auto Die Queue", icon="MESH_PLANE"):
        adbox = layout.box()
        adbox.label(
            text="After margin is closed, queue die creation jobs here.", icon="INFO"
        )
        adbox.prop(
            p,
            "margin_auto_create_die_on_close",
            text="Auto-Create Die After Margin Close",
        )
        adbox.prop(
            p,
            "margin_auto_create_die_tab6_deferred",
            text="Run in Background (Recommended)",
        )
        qcount = _autodie_queue_count(scene)
        adbox.label(text=f"Jobs waiting: {qcount}", icon="TIME")
        row = adbox.row(align=True)
        op = row.operator(
    # "smile.run_pending_autodie_tab6", text="Run Next Job", icon="PLAY"  # MISSING OPERATOR
        )
        op.run_all = False
        op = row.operator(
    # "smile.run_pending_autodie_tab6", text="Run All Jobs", icon="FILE_REFRESH"  # MISSING OPERATOR
        )
        op.run_all = True
        adbox.operator(
    # "smile.clear_pending_autodie_tab6", text="Clear Job Queue", icon="TRASH"  # MISSING OPERATOR
        )

    if fold_header(
        layout,
        "ui_tab6_sec_cadwizard",
        "Guided Crown/Veneer Builder (A-H)",
        icon="TOOL_SETTINGS",
    ):
        cw = layout.box()
        cw.label(text="Step-by-Step Generation", icon="SEQUENCE")
        cw.label(text="Wizard moved to Tab 7 (Guided Workflow).", icon="INFO")

    if fold_header(
        layout, "ui_tab6_sec_shell", "One-Click Shell Builder", icon="MESH_CUBE"
    ):
        shell_box = layout.box()
        shell_box.label(
            text="Select tooth mesh first. This builds a printable shell from margin + die + spacer.",
            icon="INFO",
        )
        row = shell_box.row(align=True)
        row.scale_y = 1.2
        row.operator(
    # "smile.build_shell_from_die_space",  # MISSING OPERATOR
            text="Build Printable Shell",
            icon="MOD_BOOLEAN",
        )
        shell_box.label(
            text="Behind the scenes: Create Die -> Spacer -> Final Shell.", icon="INFO"
        )

    if fold_header(
        layout,
        "ui_tab6_sec_crown_edit",
        "Shape Editing (Push/Pull)",
        icon="SCULPTMODE_HLT",
    ):
        ebox = layout.box()
        _draw_crown_edit_section(ebox, p)

    if fold_header(
        layout,
        "ui_tab6_sec_blockffd",
        "Local Push/Pull Cage (Advanced)",
        icon="MOD_LATTICE",
    ):
        ffd_box = layout.box()
        ffd_box.label(
            text="Create a control cage to push/pull only a local area.", icon="INFO"
        )
        row = ffd_box.row(align=True)
        row.prop(p, "blockffd_divisions", text="Divisions")
        row.prop(p, "blockffd_size_pad", text="Pad", slider=True)
        row = ffd_box.row(align=True)
        row.prop(p, "blockffd_handle_size", text="Sphere Size", slider=True)
        row.prop(p, "blockffd_sphere_gap", text="Gap", slider=True)
        row = ffd_box.row(align=True)
        row.prop(p, "blockffd_cleanup_after_apply", text="Cleanup")
        ffd_box.prop(p, "blockffd_simple_mode", text="Simple Mode (8 Corners)")
        ffd_box.prop(p, "blockffd_surface_handles_only", text="Surface Handles Only")
        row = ffd_box.row(align=True)
        row.prop(p, "blockffd_hide_relationship_lines", text="Hide Rel. Lines")
        row.prop(p, "blockffd_restore_relationship_lines", text="Restore Rel. Lines")
        row = ffd_box.row(align=True)
        op = row.operator(
    # "smile.blockffd_create", text="Create Active", icon="MOD_LATTICE"  # MISSING OPERATOR
        )
        op.scope = "ACTIVE"
        op = row.operator(
    # "smile.blockffd_create",  # MISSING OPERATOR
            text="Create Selected",
            icon="OUTLINER_OB_GROUP_INSTANCE",
        )
        op.scope = "SELECTED"
        row = ffd_box.row(align=True)
    # op = row.operator("smile.blockffd_apply", text="Apply Active", icon="CHECKMARK")  # MISSING OPERATOR
        op.scope = "ACTIVE"
        op = row.operator(
    # "smile.blockffd_apply", text="Apply Selected", icon="CHECKMARK"  # MISSING OPERATOR
        )
        op.scope = "SELECTED"
        row = ffd_box.row(align=True)
    # op = row.operator("smile.blockffd_remove", text="Remove Active", icon="CANCEL")  # MISSING OPERATOR
        op.scope = "ACTIVE"
    # op = row.operator("smile.blockffd_remove", text="Remove Selected", icon="TRASH")  # MISSING OPERATOR
        op.scope = "SELECTED"
        if bool(getattr(p, "blockffd_simple_mode", False)):
            ffd_box.label(
                text="Simple Mode ON: only 8 corner handles.", icon="CHECKMARK"
            )
        else:
            ffd_box.label(text="Simple Mode OFF: full/surface handle set.", icon="INFO")
        ffd_box.label(
            text="Use Object mode: move solid sphere markers for local edits.",
            icon="ORIENTATION_GLOBAL",
        )

    if fold_header(
        layout, "ui_tab6_sec_mirror", "Mirror to Other Side", icon="MOD_MIRROR"
    ):
        mbox = layout.box()
        mbox.label(
            text="Copy selected side to the opposite side in one click.", icon="INFO"
        )
        mid_ok = False
        mbox.prop(p, "mirror_use_manual_midline", text="Use Manual Midline Point")
        mbox.label(
            text=f"{arch_cal} Midline Point: {'Saved' if mid_ok else 'Not set (auto center)'}",
            icon="CHECKMARK" if mid_ok else "INFO",
        )
        row = mbox.row(align=True)
        op = row.operator(
            "smile.capture_mirror_midline_point", text="Set Midline", icon="TRACKER"
        )
        op.arch = "AUTO"
        op = row.operator(
            "smile.clear_mirror_midline_point", text="Clear Midline", icon="CANCEL"
        )
        op.arch = "AUTO"
        mbox.prop(p, "mirror_fit_mode", text="Fit Mode")
        mbox.prop(p, "mirror_snap_to_occlusal_curve", text="Legacy Snap Toggle")
        mbox.prop(p, "mirror_quadrant_direction", text="Direction")
        mbox.prop(p, "mirror_quadrant_replace_existing", text="Replace Existing")
        mbox.operator(
            "smile.mirror_quadrant_set",
            text="Mirror Selected Quadrant",
            icon="MOD_MIRROR",
        )

    if fold_header(
        layout,
        "ui_tab6_sec_interprox",
        "Side Stop Lines (Interprox)",
        icon="GP_SELECT_STROKES",
    ):
        _draw_interprox_divider_section(layout, context, p, enabled=True)

    if fold_header(
        layout, "ui_tab6_sec_generate", "Quick Generate + Export", icon="MOD_THICKNESS"
    ):
        gbox = layout.box()
        gbox.label(text="Fast buttons for quick generation and export.", icon="INFO")
        row = gbox.row(align=True)
        row.prop(p, "no_prep_thickness", text="No-Prep Thickness (mm)", slider=True)
        row = gbox.row(align=True)
        row.scale_y = 1.2
        row.operator(
    # "smile.generate_no_prep_veneer",  # MISSING OPERATOR
            text="Generate No-Prep Veneer",
            icon="MESH_CUBE",
        )
        row.operator(
    # "smile.make_veneer_active",  # MISSING OPERATOR
            text="Generate Veneer (Classic)",
            icon="MOD_BOOLEAN",
        )
        row = gbox.row(align=True)
        row.operator(
    # "smile.export_veneer_active",  # MISSING OPERATOR
            text="Export Veneer File + Report",
            icon="EXPORT",
        )


# === P1: Import Calibration & MDC Operators ===
# All operators and helpers below are registered via the CLASSES list at end of file.
class SMILE_OT_import_multi_veneer_set(bpy.types.Operator, ImportHelper):
    """Import multiple tooth meshes as one veneer set and optionally auto-align each by tooth ID."""

    bl_idname = "smile.import_multi_veneer_set"
    bl_label = "Import Multi-Unit Veneer Set"
    bl_options = {"REGISTER", "UNDO"}

    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_glob: bpy.props.StringProperty(
        default="*.obj;*.stl;*.ply;*.fbx;*.gltf;*.glb;*.usd;*.usda;*.usdc;*.usdz;*.abc;*.dae",
        options={"HIDDEN"},
    )
    set_name: bpy.props.StringProperty(
        name="Set Name",
        description="Optional label for this imported veneer set",
        default="",
    )
    auto_align_on_import: bpy.props.BoolProperty(
        name="Auto-Align to Seeds",
        description="Run per-tooth seed/ROI auto-align after import",
        default=True,
    )
    apply_pca_orient: bpy.props.BoolProperty(
        name="Auto-Orient (PCA)",
        description="Normalize imported tooth orientation before alignment",
        default=True,
    )

    def invoke(self, context, event):
        p = context.scene.smile_v2
        self.set_name = str(getattr(p, "veneer_set_name_hint", "") or "")
        self.auto_align_on_import = bool(getattr(p, "veneer_set_auto_align", True))
        self.apply_pca_orient = bool(getattr(p, "veneer_set_apply_pca", True))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        p = context.scene.smile_v2

        def _extract_tid(filename_no_ext):
            tid = parse_tooth_id_from_name(filename_no_ext)
            if tid:
                return int(tid)
            # Fallback for plain numbered file names like "08.stl", "11.obj"
            m = re.fullmatch(r"\s*0*([1-9]|[12][0-9]|3[0-2])\s*", str(filename_no_ext))
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            return None

        # ImportHelper can expose either `directory`+`files` or only `filepath`
        # depending on Blender version/operator context.
        base_dir = str(getattr(self, "directory", "") or "").strip()
        if not base_dir:
            fp0 = str(getattr(self, "filepath", "") or "").strip()
            if fp0:
                try:
                    base_dir = os.path.dirname(fp0)
                except Exception:
                    base_dir = ""

        filepaths = []
        files_sel = list(getattr(self, "files", []) or [])
        if files_sel:
            for f in files_sel:
                name = str(getattr(f, "name", "") or "").strip()
                if not name:
                    continue
                fp = os.path.join(base_dir, name) if base_dir else name
                if os.path.isfile(fp):
                    filepaths.append(fp)
        else:
            fp = str(getattr(self, "filepath", "") or "").strip()
            if fp and os.path.isfile(fp):
                filepaths.append(fp)

        if not filepaths:
            self.report({"ERROR"}, "No valid files selected.")
            return {"CANCELLED"}

        # Persist UI defaults for next run.
        p.veneer_set_name_hint = str(self.set_name or "")
        p.veneer_set_auto_align = bool(self.auto_align_on_import)
        p.veneer_set_apply_pca = bool(self.apply_pca_orient)

        set_label = str(self.set_name or "").strip()
        if not set_label:
            set_label = datetime.now().strftime("%Y%m%d_%H%M%S")
        set_token = re.sub(r"[^A-Za-z0-9_]+", "_", set_label).strip("_")
        if not set_token:
            set_token = datetime.now().strftime("%Y%m%d_%H%M%S")
        set_id = f"VS_{set_token}_{int(time.time())}"

        col_teeth = ensure_collection(COL_TEETH)
        root_name = f"VENEER_SET_{set_token}"
        root = bpy.data.objects.new(root_name, None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 4.0
        context.scene.collection.objects.link(root)
        link_to_collection(root, col_teeth)
        root["SMILE_VENEER_SET_ID"] = set_id
        root["SMILE_VENEER_SET_NAME"] = set_label

        imported = 0
        aligned = 0
        failed = 0
        no_tid = []
        no_align = []
        member_names = []
        imported_meshes = []

        prev_active = context.view_layer.objects.active
        prev_selected = list(context.selected_objects)

        for fp in filepaths:
            base = os.path.splitext(os.path.basename(fp))[0]
            tid_hint = _extract_tid(base)
            try:
                meshes = import_mesh_file(fp)
            except Exception as e:
                failed += 1
                print(f"[VeneerSet] Import failed for '{fp}': {e}")
                continue

            for obj in meshes:
                imported += 1
                try:
                    link_to_collection(obj, col_teeth)
                    ensure_tooth_params(obj)
                except Exception:
                    pass

                tid = tid_hint or parse_tooth_id_from_name(obj.name)
                if tid:
                    try:
                        tid = int(tid)
                    except Exception:
                        tid = None

                if self.apply_pca_orient:
                    try:
                        align_tooth_by_pca(obj)
                    except Exception as e:
                        print(
                            f"[VeneerSet] PCA orientation skipped for {obj.name}: {e}"
                        )

                obj["SMILE_VENEER_SET_ID"] = set_id
                obj["SMILE_VENEER_SET_NAME"] = set_label
                obj["SMILE_IS_VENEER_SET_MEMBER"] = True
                obj["SMILE_IMPORT_SOURCE_FILE"] = fp
                if tid:
                    obj["SMILE_TOOTH_ID"] = int(tid)
                    obj["SMILE_VENEER_TOOTH_ID"] = int(tid)
                    safe_base = (
                        re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "Tooth"
                    )
                    obj.name = f"{safe_base}_T{int(tid)}"
                else:
                    no_tid.append(os.path.basename(fp))

                # Parent to set root while preserving world transform.
                try:
                    mw = obj.matrix_world.copy()
                    obj.parent = root
                    obj.matrix_parent_inverse = root.matrix_world.inverted()
                    obj.matrix_world = mw
                except Exception:
                    pass

                member_names.append(str(obj.name))
                imported_meshes.append(obj)

                if self.auto_align_on_import and tid:
                    try:
                        bpy.ops.object.select_all(action="DESELECT")
                        obj.select_set(True)
                        context.view_layer.objects.active = obj
                        aligned_ok = False
                        if bool(getattr(p, "align_set_mdc_first", True)):
                            mdc_ready, _mdc_reason = _mdc_ready_for_obj(
                                context.scene, obj
                            )
                            if mdc_ready:
                                try:
                                    res = (
                                        bpy.ops.smile.align_imported_to_scan_landmarks(
                                            "EXEC_DEFAULT",
                                            scope="ACTIVE",
                                            with_scaling=False,
                                        )
                                    )
                                    if "FINISHED" in set(res):
                                        aligned_ok = True
                                except Exception as e_mdc:
                                    print(
                                        f"[VeneerSet] MDC align failed for {obj.name}: {e_mdc}"
                                    )

                        if (not aligned_ok) and bool(
                            getattr(p, "align_set_fallback_seed_roi", True)
                        ):
                            res = bpy.ops.smile.auto_align_library_tooth("EXEC_DEFAULT")
                            if "FINISHED" in set(res):
                                aligned_ok = True

                        if aligned_ok:
                            aligned += 1
                        else:
                            no_align.append(str(obj.name))
                    except Exception as e:
                        no_align.append(str(obj.name))
                        print(f"[VeneerSet] Auto-align failed for {obj.name}: {e}")

        # Restore selection context.
        try:
            bpy.ops.object.select_all(action="DESELECT")
            for o in prev_selected:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects[o.name].select_set(True)
            if prev_active and prev_active.name in bpy.data.objects:
                context.view_layer.objects.active = bpy.data.objects[prev_active.name]
        except Exception:
            pass

        root["SMILE_VENEER_SET_MEMBERS"] = json.dumps(member_names)

        if imported == 0:
            try:
                delete_object(root)
            except Exception:
                pass
            self.report({"ERROR"}, "No mesh objects were imported.")
            return {"CANCELLED"}

        msg = f"Imported set '{set_label}': {imported} meshes"
        pinned_ok, pinned_name = _cad_autopin_reference_from_import(
            context,
            imported_meshes,
            preferred_obj=context.view_layer.objects.active,
            force_replace=False,
        )
        if pinned_ok and pinned_name:
            msg += f", reference pinned {pinned_name}"
        if self.auto_align_on_import:
            msg += f", aligned {aligned}"
        if no_tid:
            msg += f", no-ID {len(no_tid)}"
        if no_align:
            msg += f", align-fail {len(no_align)}"
        _refresh_imported_mdc_status_list(context.scene)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def _collect_set_members_for_align(context):
    """Resolve veneer-set members from active set id, or selected set members."""
    act = context.view_layer.objects.active
    set_id = ""
    if act:
        set_id = str(act.get("SMILE_VENEER_SET_ID", "") or "")
        if not set_id and act.parent:
            set_id = str(act.parent.get("SMILE_VENEER_SET_ID", "") or "")

    if set_id:
        members = [
            o
            for o in bpy.data.objects
            if o.type == "MESH"
            and str(o.get("SMILE_VENEER_SET_ID", "") or "") == set_id
        ]
    else:
        members = [
            o
            for o in context.selected_objects
            if o.type == "MESH" and bool(o.get("SMILE_IS_VENEER_SET_MEMBER", False))
        ]
    members.sort(
        key=lambda o: int(
            o.get("SMILE_TOOTH_ID", parse_tooth_id_from_name(o.name) or 0) or 0
        )
    )
    return members


def _mdc_ready_for_obj(scene, obj):
    """Readiness gate for curve-driven MDC alignment."""
    if not obj or obj.type != "MESH":
        return False, "invalid_obj"
    tid = int(obj.get("SMILE_TOOTH_ID", parse_tooth_id_from_name(obj.name) or 0) or 0)
    if tid <= 0:
        return False, "missing_tooth_id"
    if not _has_import_tooth_lm3_local(obj):
        return False, "missing_tooth_mdc"
    arch = _arch_of_tooth_id(tid)
    if not _has_import_arch_reference(scene, arch):
        return False, "missing_arch_reference"
    domain = DOMAIN_MAX if arch == "MAX" else DOMAIN_MAN
    inc_curve = bpy.data.objects.get(arch_curve_name(domain, ARCH_CURVE_OCCLUSAL))
    cerv_curve = bpy.data.objects.get(arch_curve_name(domain, ARCH_CURVE_CERVICAL))
    if (not inc_curve) or inc_curve.type != "CURVE":
        return False, "missing_curve_occlusal"
    if (not cerv_curve) or cerv_curve.type != "CURVE":
        return False, "missing_curve_cervical"
    return True, "ok"


class SMILE_OT_align_multi_veneer_set(bpy.types.Operator):
    """Align imported veneer set members with MDC-first policy and optional fallback."""

    bl_idname = "smile.align_multi_veneer_set"
    bl_label = "Align Veneer Set"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        do_mdc_first = bool(getattr(p, "align_set_mdc_first", True))
        do_fallback = bool(getattr(p, "align_set_fallback_seed_roi", True))
        members = _collect_set_members_for_align(context)

        if not members:
            self.report(
                {"ERROR"},
                "No veneer set members found. Select set members or activate one set object.",
            )
            return {"CANCELLED"}

        prev_active = context.view_layer.objects.active
        prev_selected = list(context.selected_objects)

        mdc_members = []
        fallback_members = []
        readiness_fail = {}
        skipped = 0
        failed = 0
        mdc_aligned = 0
        fallback_aligned = 0

        for obj in members:
            tid = int(
                obj.get("SMILE_TOOTH_ID", parse_tooth_id_from_name(obj.name) or 0) or 0
            )
            if tid <= 0:
                skipped += 1
                readiness_fail["missing_tooth_id"] = (
                    readiness_fail.get("missing_tooth_id", 0) + 1
                )
                continue
            if not parse_tooth_id_from_name(obj.name):
                obj.name = f"{obj.name}_T{tid}"
            if do_mdc_first:
                ready, why = _mdc_ready_for_obj(context.scene, obj)
                if ready:
                    mdc_members.append(obj)
                else:
                    fallback_members.append(obj)
                    readiness_fail[why] = readiness_fail.get(why, 0) + 1
            else:
                fallback_members.append(obj)

        # MDC pass for all ready members.
        if do_mdc_first and mdc_members:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for obj in mdc_members:
                    if obj and obj.name in bpy.data.objects:
                        obj.select_set(True)
                context.view_layer.objects.active = mdc_members[0]
                res = bpy.ops.smile.align_imported_to_scan_landmarks(
                    "EXEC_DEFAULT", scope="SELECTED", with_scaling=False
                )
                if "FINISHED" in set(res):
                    mdc_aligned = len(mdc_members)
                else:
                    fallback_members.extend(mdc_members)
            except Exception as e:
                print(f"[VeneerSet] MDC set-align failed: {e}")
                fallback_members.extend(mdc_members)

        # Seed/ROI fallback pass.
        if do_fallback:
            seen = set()
            uniq_fallback = []
            for obj in fallback_members:
                if not obj or obj.name in seen:
                    continue
                seen.add(obj.name)
                uniq_fallback.append(obj)
            for obj in uniq_fallback:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    res = bpy.ops.smile.auto_align_library_tooth("EXEC_DEFAULT")
                    if "FINISHED" in set(res):
                        fallback_aligned += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    print(f"[VeneerSet] Fallback align failed for {obj.name}: {e}")
        else:
            unresolved = len({o.name for o in fallback_members if o})
            skipped += unresolved

        try:
            bpy.ops.object.select_all(action="DESELECT")
            for o in prev_selected:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects[o.name].select_set(True)
            if prev_active and prev_active.name in bpy.data.objects:
                context.view_layer.objects.active = bpy.data.objects[prev_active.name]
        except Exception:
            pass

        mdc_attempted = len(mdc_members) if do_mdc_first else 0
        fallback_attempted = (
            len({o.name for o in fallback_members if o}) if do_fallback else 0
        )
        total = len(members)
        details = []
        if readiness_fail:
            for k, v in sorted(
                readiness_fail.items(), key=lambda kv: kv[1], reverse=True
            )[:3]:
                details.append(f"{k}:{v}")
        detail_txt = f" Reasons[{', '.join(details)}]" if details else ""
        self.report(
            {"INFO"},
            f"Veneer set align (MDC-first={do_mdc_first}, fallback={do_fallback}): "
            f"total {total}, MDC {mdc_aligned}/{mdc_attempted}, "
            f"fallback {fallback_aligned}/{fallback_attempted}, skipped {skipped}, failed {failed}.{detail_txt}",
        )
        return {"FINISHED"}


def align_tooth_by_pca(obj):
    """
    Auto-orient a tooth mesh so its Principal Axes match Blender Standard:
    Z = Long Axis (Vertical, pointing towards Incisal/Occlusal)
    X = Wide Axis (Mesial-Distal)
    Y = Short Axis (Facial-Lingual, pointing towards Facial)
    """
    import numpy as np
    from mathutils import Vector, Matrix

    mesh = obj.data
    if len(mesh.vertices) < 10:
        return

    # 1. Sample Points (World space points relative to center)
    verts = np.array([v.co for v in mesh.vertices])
    if len(verts) > 1000:
        verts = verts[:: max(1, len(verts) // 1000)]

    mean = np.mean(verts, axis=0)
    centered = verts - mean

    # 2. PCA
    cov = np.cov(centered.T)
    evals, evecs = np.linalg.eigh(cov)

    # Sort: Largest Eigenvalue = Primary Axis (Length)
    order = evals.argsort()[::-1]
    vec_long = Vector(evecs[:, order[0]])  # Longest (Z candidate)
    vec_wide = Vector(evecs[:, order[1]])  # Mid (X candidate)
    vec_deep = Vector(evecs[:, order[2]])  # Shortest (Y candidate)

    # 3. Handedness Correction
    if vec_wide.cross(vec_deep).dot(vec_long) < 0:
        vec_deep = -vec_deep

    # 4. Construct Rotation Matrix R mapping (Wide, Deep, Long) -> (X, Y, Z)
    basis = Matrix((vec_wide, vec_deep, vec_long)).transposed()
    R = basis.inverted().to_4x4()

    # Apply to mesh data
    obj.data.transform(R)
    obj.data.update()

    # 5. Flip Heuristics (Ensuring Z is Occlusal and Y is Facial)
    # Re-calculate centered verts after rotation
    verts_rot = np.array([v.co for v in mesh.vertices])
    mean_rot = np.mean(verts_rot, axis=0)
    centered_rot = verts_rot - mean_rot

    # A. Z-Flip (Teeth are usually wider at the incisal edge than at the root)
    # Measure variance/width in X at Z-max vs Z-min
    z_mid = (np.min(centered_rot[:, 2]) + np.max(centered_rot[:, 2])) * 0.5
    top_half = centered_rot[centered_rot[:, 2] > z_mid]
    bot_half = centered_rot[centered_rot[:, 2] < z_mid]

    if len(top_half) > 0 and len(bot_half) > 0:
        width_top = np.max(top_half[:, 0]) - np.min(top_half[:, 0])
        width_bot = np.max(bot_half[:, 0]) - np.min(bot_half[:, 0])

        # If bottom is wider, it's upside down
        if width_bot > width_top:
            R_flip = Matrix.Rotation(math.pi, 4, "X")
            obj.data.transform(R_flip)

    # B. Y-Flip (Ensure +Y = Facial/Labial direction)
    # The facial surface of a tooth protrudes farther from the centroid
    # than the lingual surface (more convex labial contour).
    # Re-read verts after potential Z-flip.
    verts_rot2 = np.array([v.co for v in mesh.vertices])
    mean_rot2 = np.mean(verts_rot2, axis=0)
    centered_rot2 = verts_rot2 - mean_rot2

    max_y_extent = np.max(centered_rot2[:, 1])
    min_y_extent = np.min(centered_rot2[:, 1])

    if abs(min_y_extent) > abs(max_y_extent) * 1.05:
        # -Y has more protrusion → facial is in -Y → flip 180° around Z
        # (This flips both X and Y while preserving Z — proper rotation, det=1)
        R_flip_y = Matrix.Rotation(math.pi, 4, "Z")
        obj.data.transform(R_flip_y)

    obj.data.update()
    bpy.context.view_layer.update()


class SMILE_OT_import_procrustes(bpy.types.Operator):
    bl_idname = "smile.import_procrustes"
    bl_label = "3-Point Import (Procrustes)"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(default=8)

    def invoke(self, context, event):
        p = context.scene.smile_v2
        sel = [a for a in p.library_assets if a.selected]
        if not sel:
            self.report({"WARNING"}, "Select a tooth in the library list first!")
            return {"CANCELLED"}
        self.tooth_id = sel[0].tooth_id

        self._points = []
        self._handles = []
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"Importing #{self.tooth_id}. Step 1/3: Click MESIAL-INCISAL corner",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self.cleanup(context)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Raycast
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()

            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

            hit, loc, norm, _, obj, _ = context.scene.ray_cast(
                deps, ray_origin, ray_dir
            )

            if hit:
                self._points.append(loc)
                self.add_visual_marker(context, loc, len(self._points))

                if len(self._points) == 1:
                    self.report(
                        {"INFO"},
                        "Step 2/3: Click DISTAL-INCISAL corner (Away from center)",
                    )
                elif len(self._points) == 2:
                    self.report({"INFO"}, "Step 3/3: Click CERVICAL/GINGIVAL Center")
                elif len(self._points) == 3:
                    self.execute_import(context)
                    self.cleanup(context)
                    return {"FINISHED"}
            else:
                self.report({"WARNING"}, "Missed! Click on the scan surface.")

        return {"RUNNING_MODAL"}

    def add_visual_marker(self, context, loc, idx):
        # Simple empty creation for visual feedback
        # We'll delete them in cleanup
        name = f"TEMP_Procrustes_P{idx}"
        o = bpy.data.objects.new(name, None)
        o.location = loc
        context.collection.objects.link(o)
        self._handles.append(o)

    def cleanup(self, context):
        for o in self._handles:
            bpy.data.objects.remove(o, do_unlink=True)
        self._handles = []

    def execute_import(self, context):
        p = context.scene.smile_v2

        # 1. Find Asset File
        set_name = p.active_library_name
        assets = LibraryManager.sets.get(set_name, [])
        asset = next((a for a in assets if a.tooth_id == self.tooth_id), None)

        if not asset:
            self.report(
                {"ERROR"}, f"Tooth #{self.tooth_id} not found in library {set_name}"
            )
            return

        filepath = asset.filepath
        if not os.path.exists(filepath):
            self.report({"ERROR"}, f"File not found: {filepath}")
            return

        # 2. Import Object
        meshes = import_mesh_file(filepath)
        if not meshes:
            return
        obj = meshes[0]
        link_to_collection(obj, ensure_collection(COL_TEETH))
        ensure_tooth_params(obj)
        ensure_active(obj)

        # 3. Calculate Source Points (Bounding Box Corners)
        # P1 (Mesial): X_Min, Y_Fwd (Min), Z_Inc (Min)
        # P2 (Distal): X_Max, Y_Fwd (Min), Z_Inc (Min)
        # P3 (Cervical): X_Mid, Y_Fwd (Min), Z_Cerv (Max)

        mn, mx = bbox_world(obj)  # Local/World identity for now

        src_p1 = Vector((mn.x, mn.y, mn.z))  # Mesial (Left/MinX)
        src_p2 = Vector((mx.x, mn.y, mn.z))  # Distal (Right/MaxX)
        src_p3 = Vector(((mn.x + mx.x) / 2, mn.y, mx.z))  # Cervical (Top/MaxZ)

        # Source Points
        src = [src_p1, src_p2, src_p3]
        dst = self._points

        # 4. Solve
        try:
            R, T, s = procrustes_solver(src, dst, with_scaling=True)

            # 5. Apply
            # Construct transform matrix
            M = Matrix.Identity(4)
            M_3x3 = R * s
            for i in range(3):
                for j in range(3):
                    M[i][j] = M_3x3[i][j]
            M[0][3], M[1][3], M[2][3] = T

            obj.matrix_world = M @ obj.matrix_world

            self.report({"INFO"}, f"Auto-Matched #{self.tooth_id}!")

        except Exception as e:
            self.report({"ERROR"}, f"Procrustes Failed: {e}")


class SMILE_OT_capture_arch_reference_mdc(bpy.types.Operator):
    """Capture 2 scan reference points for curve-driven MDC alignment."""

    bl_idname = "smile.capture_arch_reference_mdc"
    bl_label = "Capture Arch MDC Reference"
    bl_options = {"REGISTER", "UNDO"}

    arch: bpy.props.EnumProperty(
        name="Arch",
        items=[
            ("AUTO", "Auto", "Infer arch from Tooth #"),
            ("MAX", "MAX", "Upper arch reference"),
            ("MAN", "MAN", "Lower arch reference"),
        ],
        default="AUTO",
    )

    def invoke(self, context, event):
        p = context.scene.smile_v2
        tid = int(getattr(p, "import_calibration_tooth_id", 8) or 8)
        if self.arch == "AUTO":
            self._arch = _import_calib_arch_for_tooth_id(tid)
        else:
            self._arch = str(self.arch).upper()
        self._points = []
        self._handles = []
        self._skip_obj = (
            context.view_layer.objects.active
            if context.view_layer.objects.active
            and context.view_layer.objects.active.type == "MESH"
            else None
        )
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"[{self._arch}] Click 1) Midline mesial (between centrals) on occlusal line, 2) Mid-cervical point.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "MOUSEROTATE",
            "MOUSESMARTZOOM",
        } or bool(getattr(event, "alt", False)):
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup_markers()
            self.report({"INFO"}, f"[{self._arch}] Arch MDC reference cancelled.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            ok, loc, _hit_name, why = _raycast_scan_under_cursor(
                context, event, obj_skip=self._skip_obj
            )
            if not ok or loc is None:
                if why == "no_view3d_region":
                    self.report(
                        {"WARNING"}, "Move cursor over 3D viewport and click the scan."
                    )
                elif why == "no_scan_targets":
                    self.report({"WARNING"}, "Set MAX/MAN scan targets first.")
                else:
                    self.report(
                        {"WARNING"}, "Missed scan surface. Click directly on scan."
                    )
                return {"RUNNING_MODAL"}

            self._points.append(loc.copy())
            self._add_marker(context, loc, len(self._points))
            if len(self._points) == 1:
                self.report({"INFO"}, "Point 2/2: click mid-cervical point.")
            elif len(self._points) >= 2:
                _save_import_arch_reference(
                    context.scene, self._arch, self._points[0], self._points[1]
                )
                self._cleanup_markers()
                self.report({"INFO"}, f"[{self._arch}] Arch reference saved.")
                return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _add_marker(self, context, loc, idx):
        name = f"TEMP_ARCH_REF_{self._arch}_{idx}"
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = 0.35
        o.location = loc
        target_col = getattr(context, "collection", None) or context.scene.collection
        target_col.objects.link(o)
        self._handles.append(o)

    def _cleanup_markers(self):
        for o in getattr(self, "_handles", []):
            try:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects.remove(bpy.data.objects[o.name], do_unlink=True)
            except Exception:
                pass
        self._handles = []


class SMILE_OT_clear_arch_reference_mdc(bpy.types.Operator):
    """Clear saved 2-point arch MDC reference."""

    bl_idname = "smile.clear_arch_reference_mdc"
    bl_label = "Clear Arch MDC Reference"
    bl_options = {"REGISTER", "UNDO"}

    arch: bpy.props.EnumProperty(
        name="Arch",
        items=[
            ("AUTO", "Auto", "Infer arch from Tooth #"),
            ("MAX", "MAX", "Upper arch"),
            ("MAN", "MAN", "Lower arch"),
            ("BOTH", "Both", "Clear both"),
        ],
        default="AUTO",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        arch = str(self.arch).upper()
        if arch == "AUTO":
            tid = int(getattr(p, "import_calibration_tooth_id", 8) or 8)
            arch = _import_calib_arch_for_tooth_id(tid)
        if arch == "BOTH":
            _clear_import_arch_reference(context.scene, "MAX")
            _clear_import_arch_reference(context.scene, "MAN")
        else:
            _clear_import_arch_reference(context.scene, arch)
        self.report({"INFO"}, f"Cleared arch MDC reference: {arch}.")
        return {"FINISHED"}


class SMILE_OT_capture_mirror_midline_point(bpy.types.Operator):
    """Capture one scan point defining midline center for mirror plane (per arch)."""

    bl_idname = "smile.capture_mirror_midline_point"
    bl_label = "Set Mirror Midline Point"
    bl_options = {"REGISTER", "UNDO"}

    arch: bpy.props.EnumProperty(
        name="Arch",
        items=[
            ("AUTO", "Auto", "Infer arch from Tooth #"),
            ("MAX", "MAX", "Upper arch midline point"),
            ("MAN", "MAN", "Lower arch midline point"),
        ],
        default="AUTO",
    )

    def invoke(self, context, event):
        p = context.scene.smile_v2
        tid = int(getattr(p, "import_calibration_tooth_id", 8) or 8)
        if self.arch == "AUTO":
            self._arch = _import_calib_arch_for_tooth_id(tid)
        else:
            self._arch = str(self.arch).upper()
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, f"[{self._arch}] Click one point on scan at facial midline."
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "MOUSEROTATE",
            "MOUSESMARTZOOM",
        } or bool(getattr(event, "alt", False)):
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self.report({"INFO"}, f"[{self._arch}] Midline capture cancelled.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            ok, loc, _hit_name, why = _raycast_scan_under_cursor(
                context, event, obj_skip=None
            )
            if not ok or loc is None:
                if why == "no_view3d_region":
                    self.report(
                        {"WARNING"}, "Move cursor over 3D viewport and click the scan."
                    )
                elif why == "no_scan_targets":
                    self.report({"WARNING"}, "Set MAX/MAN scan targets first.")
                else:
                    self.report(
                        {"WARNING"}, "Missed scan surface. Click directly on scan."
                    )
                return {"RUNNING_MODAL"}
            _save_mirror_midline_point(context.scene, self._arch, loc)
            self.report({"INFO"}, f"[{self._arch}] Mirror midline point saved.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}


class SMILE_OT_clear_mirror_midline_point(bpy.types.Operator):
    """Clear saved mirror midline point."""

    bl_idname = "smile.clear_mirror_midline_point"
    bl_label = "Clear Mirror Midline Point"
    bl_options = {"REGISTER", "UNDO"}

    arch: bpy.props.EnumProperty(
        name="Arch",
        items=[
            ("AUTO", "Auto", "Infer arch from Tooth #"),
            ("MAX", "MAX", "Upper arch"),
            ("MAN", "MAN", "Lower arch"),
            ("BOTH", "Both", "Clear both"),
        ],
        default="AUTO",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        arch = str(self.arch).upper()
        if arch == "AUTO":
            tid = int(getattr(p, "import_calibration_tooth_id", 8) or 8)
            arch = _import_calib_arch_for_tooth_id(tid)
        if arch == "BOTH":
            _clear_mirror_midline_point(context.scene, "MAX")
            _clear_mirror_midline_point(context.scene, "MAN")
        else:
            _clear_mirror_midline_point(context.scene, arch)
        self.report({"INFO"}, f"Cleared mirror midline point: {arch}.")
        return {"FINISHED"}


class SMILE_OT_refresh_imported_mdc_list(bpy.types.Operator):
    bl_idname = "smile.refresh_imported_mdc_list"
    bl_label = "Refresh Imported MDC List"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = _refresh_imported_mdc_status_list(context.scene)
        self.report({"INFO"}, f"Imported MDC list refreshed ({n} teeth).")
        return {"FINISHED"}


class SMILE_OT_select_imported_mdc_item(bpy.types.Operator):
    bl_idname = "smile.select_imported_mdc_item"
    bl_label = "Select Imported Tooth (List)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        idx = int(getattr(p, "imported_mdc_active_index", 0) or 0)
        if idx < 0 or idx >= len(p.imported_mdc_items):
            self.report({"ERROR"}, "No imported tooth selected in list.")
            return {"CANCELLED"}
        item = p.imported_mdc_items[idx]
        obj = bpy.data.objects.get(str(item.obj_name))
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Listed object no longer exists. Refresh list.")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj
        p.import_calibration_tooth_id = int(
            item.tooth_id or p.import_calibration_tooth_id
        )
        self.report(
            {"INFO"}, f"Active imported tooth: #{int(item.tooth_id)} ({obj.name})"
        )
        return {"FINISHED"}


class SMILE_OT_mark_imported_mdc_from_list(bpy.types.Operator):
    bl_idname = "smile.mark_imported_mdc_from_list"
    bl_label = "Mark MDC (List Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = bpy.ops.smile.select_imported_mdc_item("EXEC_DEFAULT")
        if "FINISHED" not in set(res):
            return {"CANCELLED"}
        bpy.ops.smile.capture_import_tooth_landmarks_3pt("INVOKE_DEFAULT")
        return {"FINISHED"}

        return {"FINISHED"}


class SMILE_OT_capture_scan_landmarks_3pt(bpy.types.Operator):
    """Capture 3 scan landmarks (Mesial, Distal, Cervical) for a tooth ID."""

    bl_idname = "smile.capture_scan_landmarks_3pt"
    bl_label = "Capture Scan Landmarks (M-D-C)"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=0, min=0, max=32)

    def invoke(self, context, event):
        p = context.scene.smile_v2
        tid = int(self.tooth_id or 0)
        if tid <= 0:
            obj = context.view_layer.objects.active
            try:
                tid = (
                    int(parse_tooth_id_from_name(obj.name) or 0)
                    if (obj and obj.type == "MESH")
                    else 0
                )
            except Exception:
                tid = 0
        if tid <= 0:
            tid = int(getattr(p, "import_calibration_tooth_id", 0) or 0)
        if tid <= 0:
            tid = int(getattr(p, "target_tooth_id", 8) or 8)

        self._tooth_id = int(tid)
        p.import_calibration_tooth_id = int(tid)
        self._points = []
        self._handles = []
        self._skip_obj = (
            context.view_layer.objects.active
            if context.view_layer.objects.active
            and context.view_layer.objects.active.type == "MESH"
            else None
        )

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"[Scan T#{tid}] Click 1) Mesial  2) Distal  3) Cervical on scan mesh.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # Allow viewport navigation while calibrating (orbit/pan/zoom).
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "MOUSEROTATE",
            "MOUSESMARTZOOM",
        } or bool(getattr(event, "alt", False)):
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup_markers()
            self.report({"INFO"}, f"Scan landmarks cancelled for T#{self._tooth_id}.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            ok, loc, _hit_name, why = _raycast_scan_under_cursor(
                context, event, obj_skip=self._skip_obj
            )
            if not ok or loc is None:
                if why == "no_view3d_region":
                    self.report(
                        {"WARNING"},
                        "Move cursor over a 3D viewport and click the scan.",
                    )
                elif why == "no_scan_targets":
                    self.report({"WARNING"}, "Set MAX/MAN scan targets first.")
                else:
                    self.report(
                        {"WARNING"}, "Missed scan surface. Click directly on the scan."
                    )
                return {"RUNNING_MODAL"}

            self._points.append(loc.copy())
            self._add_marker(context, loc, len(self._points))
            if len(self._points) == 1:
                self.report({"INFO"}, "Point 2/3: click Distal landmark.")
            elif len(self._points) == 2:
                self.report({"INFO"}, "Point 3/3: click Cervical landmark.")
            elif len(self._points) >= 3:
                _save_import_scan_lm3(context.scene, self._tooth_id, self._points[:3])
                self._cleanup_markers()
                self.report({"INFO"}, f"Saved scan landmarks for T#{self._tooth_id}.")
                return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def _add_marker(self, context, loc, idx):
        name = f"TEMP_SCAN_LM_T{self._tooth_id}_{idx}"
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = 0.3
        o.location = loc
        target_col = getattr(context, "collection", None) or context.scene.collection
        target_col.objects.link(o)
        self._handles.append(o)

    def _cleanup_markers(self):
        for o in getattr(self, "_handles", []):
            try:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects.remove(bpy.data.objects[o.name], do_unlink=True)
            except Exception:
                pass
        self._handles = []


class SMILE_OT_capture_import_tooth_landmarks_3pt(bpy.types.Operator):
    """Capture 3 landmarks on active imported tooth (Mesial, Distal, Cervical)."""

    bl_idname = "smile.capture_import_tooth_landmarks_3pt"
    bl_label = "Capture Imported Tooth Landmarks (M-D-C)"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the imported tooth mesh first.")
            return {"CANCELLED"}

        tid = parse_tooth_id_from_name(obj.name) or int(
            obj.get("SMILE_TOOTH_ID", 0) or 0
        )
        if tid <= 0:
            self.report(
                {"ERROR"}, "Could not determine tooth ID from active imported tooth."
            )
            return {"CANCELLED"}

        context.scene.smile_v2.import_calibration_tooth_id = int(tid)
        self._obj_name = obj.name
        self._tooth_id = int(tid)
        self._points_local = []
        self._handles = []

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"[Import T#{tid}] Click 1) Mesial  2) Distal  3) Cervical on imported tooth.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # Allow viewport navigation while calibrating (orbit/pan/zoom).
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "MOUSEROTATE",
            "MOUSESMARTZOOM",
        } or bool(getattr(event, "alt", False)):
            return {"PASS_THROUGH"}

        obj = bpy.data.objects.get(self._obj_name)
        if not obj or obj.type != "MESH":
            self._cleanup_markers()
            self.report({"ERROR"}, "Imported tooth is not available.")
            return {"CANCELLED"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup_markers()
            self.report(
                {"INFO"}, f"Imported-tooth landmarks cancelled for T#{self._tooth_id}."
            )
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, obj)
            if not hit:
                self.report(
                    {"WARNING"},
                    "Missed imported tooth surface. Click on the active imported tooth.",
                )
                return {"RUNNING_MODAL"}

            loc, _norm, _fi = hit
            local = obj.matrix_world.inverted() @ loc
            self._points_local.append(local.copy())
            self._add_marker(context, loc, len(self._points_local))

            if len(self._points_local) == 1:
                self.report({"INFO"}, "Point 2/3: click Distal landmark.")
            elif len(self._points_local) == 2:
                self.report({"INFO"}, "Point 3/3: click Cervical landmark.")
            elif len(self._points_local) >= 3:
                _save_import_tooth_lm3_local(obj, self._points_local[:3])
                _refresh_imported_mdc_status_list(context.scene)
                self._cleanup_markers()
                self.report(
                    {"INFO"},
                    f"Saved imported-tooth landmarks for T#{self._tooth_id} ({obj.name}).",
                )
                return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def _add_marker(self, context, loc, idx):
        name = f"TEMP_TOOTH_LM_T{self._tooth_id}_{idx}"
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = 0.3
        o.location = loc
        target_col = getattr(context, "collection", None) or context.scene.collection
        target_col.objects.link(o)
        self._handles.append(o)

    def _cleanup_markers(self):
        for o in getattr(self, "_handles", []):
            try:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects.remove(bpy.data.objects[o.name], do_unlink=True)
            except Exception:
                pass
        self._handles = []


class SMILE_OT_align_imported_to_scan_landmarks(bpy.types.Operator):
    """Align imported teeth by MDC workflow (curve-driven), with legacy scan-landmark fallback."""

    bl_idname = "smile.align_imported_to_scan_landmarks"
    bl_label = "Align Imported Tooth to Scan (M-D-C)"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Align only active imported tooth"),
            ("SELECTED", "Selected", "Align all selected imported teeth"),
        ],
        default="ACTIVE",
    )
    with_scaling: bpy.props.BoolProperty(
        name="Allow Scaling",
        default=True,
        description="Allow uniform scale during 3-point match",
    )

    def execute(self, context):
        candidates = []
        active_tid = 0
        include_names = set()
        if self.scope == "ACTIVE":
            obj = context.view_layer.objects.active
            if obj and obj.type == "MESH":
                candidates = [obj]
                active_tid = parse_tooth_id_from_name(obj.name) or int(
                    obj.get("SMILE_TOOTH_ID", 0) or 0
                )
                include_names.add(str(obj.name))
        else:
            candidates = [o for o in context.selected_objects if o and o.type == "MESH"]
            if (
                not candidates
                and context.view_layer.objects.active
                and context.view_layer.objects.active.type == "MESH"
            ):
                candidates = [context.view_layer.objects.active]
            include_names = set(str(o.name) for o in candidates if o)

        if not candidates:
            self.report({"ERROR"}, "Select imported tooth mesh(es) first.")
            return {"CANCELLED"}

        p = context.scene.smile_v2

        aligned = 0
        skipped = 0
        failures = 0
        legacy_aligned_names = set()

        # Legacy fallback pass: if per-tooth scan landmarks exist, use them.
        for obj in candidates:
            tid = parse_tooth_id_from_name(obj.name) or int(
                obj.get("SMILE_TOOTH_ID", 0) or 0
            )
            if tid <= 0:
                skipped += 1
                continue

            dst = _load_import_scan_lm3(context.scene, tid)
            src_local = _load_import_tooth_lm3_local(obj)
            if len(dst) < 3 or len(src_local) < 3:
                skipped += 1
                continue

            src_world = [obj.matrix_world @ Vector(p) for p in src_local[:3]]

            try:
                R, T, s = procrustes_solver(
                    src_world, dst[:3], with_scaling=bool(self.with_scaling)
                )
                M = Matrix.Identity(4)
                M3 = R * (float(s) if self.with_scaling else 1.0)
                for i in range(3):
                    for j in range(3):
                        M[i][j] = float(M3[i][j])
                M[0][3], M[1][3], M[2][3] = float(T.x), float(T.y), float(T.z)
                obj.matrix_world = M @ obj.matrix_world
                aligned += 1
                legacy_aligned_names.add(obj.name)
            except Exception:
                failures += 1

        # New workflow pass: curve-driven MDC auto alignment for marked teeth.
        archs = set()
        if self.scope == "ACTIVE" and active_tid > 0:
            archs.add(_arch_of_tooth_id(active_tid))
        elif self.scope == "SELECTED" and candidates:
            for obj in candidates:
                tid = parse_tooth_id_from_name(obj.name) or int(
                    obj.get("SMILE_TOOTH_ID", 0) or 0
                )
                if tid > 0:
                    archs.add(_arch_of_tooth_id(tid))
        if not archs:
            archs = {"MAX", "MAN"}

        curve_aligned = 0
        curve_missing = []
        for arch in sorted(archs):
            domain = DOMAIN_MAX if arch == "MAX" else DOMAIN_MAN
            inc_curve = bpy.data.objects.get(
                arch_curve_name(domain, ARCH_CURVE_OCCLUSAL)
            )
            cerv_curve = bpy.data.objects.get(
                arch_curve_name(domain, ARCH_CURVE_CERVICAL)
            )
            if not inc_curve or inc_curve.type != "CURVE":
                curve_missing.append(f"{arch}: missing occlusal tracer")
                continue
            if not cerv_curve or cerv_curve.type != "CURVE":
                curve_missing.append(f"{arch}: missing cervical tracer")
                continue
            if not _has_import_arch_reference(context.scene, arch):
                curve_missing.append(f"{arch}: missing 2-point arch reference")
                continue
            if _count_marked_imported_teeth_for_arch(arch) <= 0:
                curve_missing.append(f"{arch}: no imported teeth with MDC marks")
                continue

            anchor_tid = int(getattr(p, "import_calibration_tooth_id", 0) or 0)
            if _arch_of_tooth_id(anchor_tid) != arch:
                anchor_tid = 8 if arch == "MAX" else 24
            curve_aligned += _auto_calibrate_arch_mdc_from_curves(
                context,
                arch=arch,
                anchor_tooth_id=anchor_tid,
                exclude_names=set(legacy_aligned_names),
                require_marked=True,
                include_names=include_names if include_names else None,
            )

        total_aligned = int(aligned + curve_aligned)
        _refresh_imported_mdc_status_list(context.scene)

        if total_aligned <= 0:
            detail = (
                "; ".join(curve_missing[:3])
                if curve_missing
                else "no valid curve-alignment targets"
            )
            self.report(
                {"ERROR"},
                f"No teeth aligned. {detail}. Legacy skipped={skipped}, failed={failures}.",
            )
            return {"CANCELLED"}

        if curve_aligned > 0:
            if curve_missing:
                self.report(
                    {"INFO"},
                    f"MDC auto-align complete: curve-aligned {curve_aligned} tooth/teeth (legacy {aligned}). Missing: {'; '.join(curve_missing[:2])}.",
                )
            else:
                self.report(
                    {"INFO"},
                    f"MDC auto-align complete: curve-aligned {curve_aligned} tooth/teeth (legacy {aligned}).",
                )
        else:
            self.report(
                {"INFO"},
                f"Legacy scan-landmark aligned {aligned} tooth/teeth (skipped={skipped}, failed={failures}).",
            )
        return {"FINISHED"}


class SMILE_OT_mirror_quadrant_set(bpy.types.Operator):
    """Mirror selected quadrant teeth to contralateral side in one click."""

    bl_idname = "smile.mirror_quadrant_set"
    bl_label = "Mirror Quadrant Set"
    bl_options = {"REGISTER", "UNDO"}

    def _source_candidates(self, context):
        col = bpy.data.collections.get(COL_TEETH)
        col_names = set(o.name for o in col.objects) if col else set()
        out = []
        for obj in context.selected_objects:
            if not obj or obj.type != "MESH":
                continue
            if col_names and obj.name not in col_names:
                continue
            tid = parse_tooth_id_from_name(obj.name) or int(
                obj.get("SMILE_TOOTH_ID", 0) or 0
            )
            if int(tid) <= 0:
                continue
            out.append((int(tid), obj))
        if out:
            return out

        active = context.view_layer.objects.active
        if (
            active
            and active.type == "MESH"
            and (not col_names or active.name in col_names)
        ):
            tid = parse_tooth_id_from_name(active.name) or int(
                active.get("SMILE_TOOTH_ID", 0) or 0
            )
            if int(tid) > 0:
                return [(int(tid), active)]
        return []

    def _resolve_direction(self, context, rows):
        p = context.scene.smile_v2
        direction = str(getattr(p, "mirror_quadrant_direction", "AUTO") or "AUTO")
        if direction in {"RIGHT_TO_LEFT", "LEFT_TO_RIGHT"}:
            return direction

        active = context.view_layer.objects.active
        if active and active.type == "MESH":
            atid = parse_tooth_id_from_name(active.name) or int(
                active.get("SMILE_TOOTH_ID", 0) or 0
            )
            if int(atid) > 0:
                if _is_right_side_universal(int(atid)):
                    return "RIGHT_TO_LEFT"
                if _is_left_side_universal(int(atid)):
                    return "LEFT_TO_RIGHT"

        right_n = sum(1 for tid, _obj in rows if _is_right_side_universal(tid))
        left_n = sum(1 for tid, _obj in rows if _is_left_side_universal(tid))
        return "RIGHT_TO_LEFT" if right_n >= left_n else "LEFT_TO_RIGHT"

    def execute(self, context):
        rows = self._source_candidates(context)
        if not rows:
            self.report(
                {"ERROR"}, "Select imported tooth mesh(es) from Teeth collection first."
            )
            return {"CANCELLED"}

        direction = self._resolve_direction(context, rows)
        p = context.scene.smile_v2
        replace_existing = bool(getattr(p, "mirror_quadrant_replace_existing", True))
        fit_mode = str(getattr(p, "mirror_fit_mode", "") or "").upper()
        if fit_mode not in {"EXACT_MIRROR", "MIRROR_PLUS_GLOBAL_ARCH_SNAP"}:
            # Backward compatibility with older bool-only behavior.
            fit_mode = (
                "MIRROR_PLUS_GLOBAL_ARCH_SNAP"
                if bool(getattr(p, "mirror_snap_to_occlusal_curve", True))
                else "EXACT_MIRROR"
            )
        require_mdc = bool(getattr(p, "mirror_fit_require_mdc", True))

        if direction == "RIGHT_TO_LEFT":
            rows = [(tid, obj) for tid, obj in rows if _is_right_side_universal(tid)]
        else:
            rows = [(tid, obj) for tid, obj in rows if _is_left_side_universal(tid)]
        if not rows:
            if direction == "RIGHT_TO_LEFT":
                self.report({"ERROR"}, "No right-side source teeth found in selection.")
            else:
                self.report({"ERROR"}, "No left-side source teeth found in selection.")
            return {"CANCELLED"}

        rows.sort(key=lambda it: it[0])
        made = []
        skipped = 0
        plane_q = []
        by_arch = {"MAX": [], "MAN": []}
        fit_results = []
        for tid, src_obj in rows:
            target_tid = _contralateral_universal_tooth_id(tid)
            if target_tid <= 0:
                skipped += 1
                continue
            dup, quality = _mirror_duplicate_imported_tooth(
                context.scene,
                source_obj=src_obj,
                source_tid=tid,
                target_tid=target_tid,
                replace_existing=replace_existing,
            )
            if dup:
                made.append((tid, target_tid, dup))
                arch = _arch_of_tooth_id(tid)
                if arch in by_arch:
                    by_arch[arch].append((tid, src_obj, dup))
                if quality:
                    plane_q.append(str(quality))
            else:
                skipped += 1

        if not made:
            self.report(
                {"ERROR"},
                "Mirror set failed. Check selected imported teeth and arch tracer/reference.",
            )
            return {"CANCELLED"}

        if fit_mode == "MIRROR_PLUS_GLOBAL_ARCH_SNAP":
            for arch in ("MAX", "MAN"):
                rows_arch = by_arch.get(arch, [])
                if not rows_arch:
                    continue
                ok_fit, meta = _mirror_group_fit_to_occlusal_arch(
                    context.scene,
                    arch=arch,
                    group_rows=rows_arch,
                    require_marked=require_mdc,
                )
                fit_results.append((arch, bool(ok_fit), dict(meta or {})))

        try:
            ensure_active(made[-1][2])
        except Exception:
            pass
        _refresh_imported_mdc_status_list(context.scene)
        uq = sorted(set(plane_q))
        qtxt = f" | Plane: {', '.join(uq[:2])}" if uq else ""
        fit_txt = " | Fit: exact_mirror"
        if fit_mode == "MIRROR_PLUS_GLOBAL_ARCH_SNAP":
            parts = []
            for arch, ok_flag, meta in fit_results:
                if ok_flag:
                    parts.append(
                        f"{arch}:ok used={int(meta.get('used', 0))} mode={str(meta.get('mode', ''))}"
                    )
                else:
                    parts.append(
                        f"{arch}:skip {str(meta.get('reason', ''))} (used={int(meta.get('used', 0))}, "
                        f"unmarked={int(meta.get('skipped_unmarked', 0))}, invalid={int(meta.get('skipped_invalid', 0))})"
                    )
            if parts:
                fit_txt = " | Fit: " + " ; ".join(parts[:2])
            else:
                fit_txt = " | Fit: global_arch_snap(no_arch_rows)"
        self.report(
            {"INFO"},
            f"Mirrored {len(made)} tooth/teeth ({'R→L' if direction == 'RIGHT_TO_LEFT' else 'L→R'})"
            f"{' with replace' if replace_existing else ''}. Skipped {skipped}.{qtxt}{fit_txt}",
        )
        return {"FINISHED"}


class SMILE_OT_clear_import_scan_landmarks_3pt(bpy.types.Operator):
    """Clear saved scan landmarks (M-D-C) for one tooth ID."""

    bl_idname = "smile.clear_import_scan_landmarks_3pt"
    bl_label = "Clear Scan Landmarks (M-D-C)"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=0, min=0, max=32)

    def execute(self, context):
        p = context.scene.smile_v2
        tid = int(self.tooth_id or 0) or int(
            getattr(p, "import_calibration_tooth_id", 0) or 0
        )
        if tid <= 0:
            self.report({"ERROR"}, "Set a valid tooth ID first.")
            return {"CANCELLED"}
        _clear_import_scan_lm3(context.scene, tid)
        self.report({"INFO"}, f"Cleared scan landmarks for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_clear_import_tooth_landmarks_3pt(bpy.types.Operator):
    """Clear saved imported-tooth landmarks (M-D-C) for active tooth."""

    bl_idname = "smile.clear_import_tooth_landmarks_3pt"
    bl_label = "Clear Imported Tooth Landmarks (M-D-C)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the imported tooth mesh first.")
            return {"CANCELLED"}
        tid = parse_tooth_id_from_name(obj.name) or int(
            obj.get("SMILE_TOOTH_ID", 0) or 0
        )
        _clear_import_tooth_lm3_local(obj)
        _refresh_imported_mdc_status_list(context.scene)
        if int(tid or 0) > 0:
            self.report(
                {"INFO"},
                f"Cleared imported-tooth MDC landmarks for T#{int(tid)} ({obj.name}).",
            )
        else:
            self.report(
                {"INFO"}, f"Cleared imported-tooth MDC landmarks for {obj.name}."
            )
        return {"FINISHED"}


class SMILE_OT_calibrate_import_anchor(bpy.types.Operator):
    """Capture one anchor-tooth correction (3 scan clicks) and reuse it for future imports."""

    bl_idname = "smile.calibrate_import_anchor"
    bl_label = "Calibrate Import Anchor (3 Clicks)"
    bl_options = {"REGISTER", "UNDO"}

    arch: bpy.props.EnumProperty(
        name="Arch",
        items=[
            ("AUTO", "Auto", "Use active tooth ID to choose MAX/MAN"),
            ("MAX", "MAX", "Save calibration for upper arch imports"),
            ("MAN", "MAN", "Save calibration for lower arch imports"),
        ],
        default="AUTO",
    )

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select an imported tooth mesh first.")
            return {"CANCELLED"}

        tid = (
            parse_tooth_id_from_name(obj.name)
            or int(obj.get("SMILE_TOOTH_ID", 0) or 0)
            or int(context.scene.smile_v2.target_tooth_id)
        )
        if tid <= 0:
            self.report({"ERROR"}, "Cannot determine tooth ID from active object.")
            return {"CANCELLED"}

        if self.arch == "AUTO":
            self._arch = _import_calib_arch_for_tooth_id(tid)
        else:
            self._arch = str(self.arch)
        self._tooth_name = obj.name
        self._tooth_id = int(tid)
        self._points = []
        self._handles = []

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"[{self._arch}] Click 3 scan points: 1) Mesial-Incisal  2) Distal-Incisal  3) Cervical Center",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # Allow viewport navigation while calibrating (orbit/pan/zoom).
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "MOUSEROTATE",
            "MOUSESMARTZOOM",
        } or bool(getattr(event, "alt", False)):
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup_markers(context)
            self.report({"INFO"}, "Anchor calibration cancelled.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            ok, loc, hit_name, why = self._raycast_scan_under_cursor(context, event)
            if not ok or loc is None:
                if why == "no_view3d_region":
                    self.report(
                        {"WARNING"},
                        "Move cursor over the 3D viewport and click the scan.",
                    )
                else:
                    self.report(
                        {"WARNING"},
                        "Missed scan mesh. Click directly on target scan surface.",
                    )
                return {"RUNNING_MODAL"}

            self._points.append(loc.copy())
            self._add_marker(context, loc, len(self._points))
            if len(self._points) == 1:
                self.report({"INFO"}, "Point 2/3: click Distal-Incisal corner.")
            elif len(self._points) == 2:
                self.report({"INFO"}, "Point 3/3: click Cervical Center.")
            elif len(self._points) >= 3:
                try:
                    self._finalize(context)
                    self._cleanup_markers(context)
                    return {"FINISHED"}
                except Exception as e:
                    self._cleanup_markers(context)
                    self.report({"ERROR"}, f"Calibration failed: {e}")
                    return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _resolve_view3d_pick_context(self, context, event):
        """Return (region_window, region_3d, coord) for raycast under mouse."""
        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None) if window else None
        if not screen:
            return None, None, None

        # Prefer current VIEW_3D area if mouse is inside.
        area_candidates = []
        if context.area and context.area.type == "VIEW_3D":
            area_candidates.append(context.area)
        for a in screen.areas:
            if a.type == "VIEW_3D" and a not in area_candidates:
                area_candidates.append(a)

        for area in area_candidates:
            if not (
                area.x <= event.mouse_x < area.x + area.width
                and area.y <= event.mouse_y < area.y + area.height
            ):
                continue
            region_win = next((r for r in area.regions if r.type == "WINDOW"), None)
            if not region_win:
                continue
            rx = int(event.mouse_x - region_win.x)
            ry = int(event.mouse_y - region_win.y)
            if rx < 0 or ry < 0 or rx >= region_win.width or ry >= region_win.height:
                continue
            space = next((s for s in area.spaces if s.type == "VIEW_3D"), None)
            rv3d = space.region_3d if space else None
            if rv3d is None:
                continue
            return region_win, rv3d, (rx, ry)
        return None, None, None

    def _scan_candidates(self, context):
        p = context.scene.smile_v2
        names = set()
        for nm in (
            str(getattr(p, "max_target", "") or "").strip(),
            str(getattr(p, "man_target", "") or "").strip(),
        ):
            if nm:
                o = bpy.data.objects.get(nm)
                if o and o.type == "MESH":
                    names.add(o.name)
        col_scans = bpy.data.collections.get(COL_SCANS)
        if col_scans:
            for o in col_scans.objects:
                if o and o.type == "MESH":
                    names.add(o.name)
        return names

    def _raycast_scan_under_cursor(self, context, event):
        region, rv3d, coord = self._resolve_view3d_pick_context(context, event)
        if not region or not rv3d:
            return False, None, "", "no_view3d_region"

        v3d = _view3d_utils()
        deps = context.evaluated_depsgraph_get()
        ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
        ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()
        obj_skip = bpy.data.objects.get(str(self._tooth_name))
        scan_names = self._scan_candidates(context)

        cast_origin = ray_origin.copy()
        for _ in range(20):
            h, l, _n, _fi, o, _m = context.scene.ray_cast(deps, cast_origin, ray_dir)
            if not h:
                return False, None, "", "ray_miss"
            cast_origin = l + ray_dir * 1.0e-4
            if not o or o.type != "MESH":
                continue
            if obj_skip and o == obj_skip:
                continue
            if scan_names and o.name not in scan_names:
                continue
            return True, l.copy(), o.name, ""

        return False, None, "", "no_scan_hit"

    def _add_marker(self, context, loc, idx):
        name = f"TEMP_IMPORT_CAL_P{idx}"
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = 0.3
        o.location = loc
        target_col = getattr(context, "collection", None) or context.scene.collection
        target_col.objects.link(o)
        self._handles.append(o)

    def _cleanup_markers(self, context):
        for o in getattr(self, "_handles", []):
            try:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects.remove(bpy.data.objects[o.name], do_unlink=True)
            except Exception:
                pass
        self._handles = []

    def _finalize(self, context):
        scene = context.scene
        obj = bpy.data.objects.get(str(self._tooth_name))
        if not obj or obj.type != "MESH":
            raise RuntimeError("Active anchor tooth is no longer available.")
        if len(self._points) < 3:
            raise RuntimeError("Need 3 scan points.")

        mn, mx = bbox_world(obj)
        src_p1 = Vector((mn.x, mn.y, mn.z))
        src_p2 = Vector((mx.x, mn.y, mn.z))
        src_p3 = Vector(((mn.x + mx.x) * 0.5, mn.y, mx.z))
        src = [src_p1, src_p2, src_p3]
        dst = [Vector(p) for p in self._points[:3]]

        R, T, s = procrustes_solver(src, dst, with_scaling=True)

        M = Matrix.Identity(4)
        M3 = R * s
        for i in range(3):
            for j in range(3):
                M[i][j] = float(M3[i][j])
        M[0][3], M[1][3], M[2][3] = float(T.x), float(T.y), float(T.z)
        obj.matrix_world = M @ obj.matrix_world
        bpy.context.view_layer.update()

        # Store only rotation+scale correction for batch imports.
        RS = Matrix.Identity(4)
        for i in range(3):
            for j in range(3):
                RS[i][j] = float(M3[i][j])
        _save_import_calibration(
            scene, self._arch, RS, anchor_tooth_id=self._tooth_id, anchor_name=obj.name
        )
        self.report(
            {"INFO"},
            f"[{self._arch}] anchor calibration saved (scale {float(s):.3f}) from {obj.name}.",
        )


class SMILE_OT_clear_import_calibration(bpy.types.Operator):
    """Clear saved import calibration for MAX/MAN arches."""

    bl_idname = "smile.clear_import_calibration"
    bl_label = "Clear Import Calibration"
    bl_options = {"REGISTER", "UNDO"}

    arch: bpy.props.EnumProperty(
        name="Arch",
        items=[
            ("MAX", "MAX", "Clear upper arch calibration"),
            ("MAN", "MAN", "Clear lower arch calibration"),
            ("BOTH", "Both", "Clear both arch calibrations"),
        ],
        default="BOTH",
    )

    def execute(self, context):
        scene = context.scene
        if self.arch in {"MAX", "BOTH"}:
            _clear_import_calibration(scene, "MAX")
        if self.arch in {"MAN", "BOTH"}:
            _clear_import_calibration(scene, "MAN")
        self.report({"INFO"}, f"Import calibration cleared: {self.arch}")
        return {"FINISHED"}


# ============================================================
# PHASE 3: TOOTH ORIENTATION ENHANCEMENT
# ============================================================


def import_mesh_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    pre = set(bpy.data.objects)

    ops_map = {
        ".obj": [("wm", "obj_import"), ("import_scene", "obj")],
        ".stl": [("wm", "stl_import"), ("import_mesh", "stl")],
        ".ply": [("wm", "ply_import"), ("import_mesh", "ply")],
        ".gltf": [("import_scene", "gltf")],
        ".glb": [("import_scene", "gltf")],
        ".fbx": [("import_scene", "fbx")],
        ".usd": [("wm", "usd_import"), ("import_scene", "usd")],
        ".usda": [("wm", "usd_import"), ("import_scene", "usd")],
        ".usdc": [("wm", "usd_import"), ("import_scene", "usd")],
        ".usdz": [("wm", "usd_import"), ("import_scene", "usd")],
        ".abc": [("wm", "alembic_import"), ("import_scene", "alembic")],
        ".dae": [("wm", "collada_import"), ("import_scene", "dae")],
    }

    if ext not in ops_map:
        raise RuntimeError(f"Unsupported extension: {ext}")

    success = False
    for mod_name, op_name in ops_map[ext]:
        mod = getattr(bpy.ops, mod_name, None)
        if mod and hasattr(mod, op_name):
            op = getattr(mod, op_name)
            _import_with_operator(op, {"filepath": filepath})
            success = True
            break

    if not success:
        raise RuntimeError(f"Importer not available for {ext}")

    bpy.context.view_layer.update()
    post = set(bpy.data.objects)
    return [o for o in (post - pre) if o.type == "MESH"]


# ============================================================
# LANDMARKS: naming, indexing, matching
# ============================================================


def indices_in_domain(domain: str):
    inds = set()
    for o in bpy.data.objects:
        if o.get("SMILE_LM_DOMAIN") == domain and o.get("SMILE_LM_INDEX") is not None:
            inds.add(int(o["SMILE_LM_INDEX"]))

    if domain == DOMAIN_PHOTO:
        # Also check property collection in the active photo slot
        try:
            # We use bpy.context.scene directly as this is called during UI/Modal ops
            scene = bpy.context.scene
            slot = _active_photo_slot(scene)
            if slot:
                for lm in slot.landmarks:
                    inds.add(int(lm.idx))
        except Exception:
            pass

    return inds


def get_landmark_obj(domain: str, idx: int):
    return bpy.data.objects.get(lm_name(domain, idx))


def find_arch_incisal_curve(domain: str):
    for nm in arch_incisal_curve_candidates(domain):
        o = bpy.data.objects.get(nm)
        if o and o.type == "CURVE" and not o.hide_viewport:
            return o
    return None


def curve_world_points(curve_obj, samples=64):
    if not curve_obj or curve_obj.type != "CURVE":
        return []
    deps = bpy.context.evaluated_depsgraph_get()
    eobj = curve_obj.evaluated_get(deps)
    pts = []
    try:
        me = eobj.to_mesh()
        mw = curve_obj.matrix_world
        for v in me.vertices:
            pts.append(mw @ v.co)
        eobj.to_mesh_clear()
        if len(pts) >= 2:
            return pts
    except Exception:
        traceback.print_exc()

    # Curve object may exist temporarily without any splines while tracing/editing.
    if not getattr(eobj.data, "splines", None) or len(eobj.data.splines) == 0:
        return []

    mw = curve_obj.matrix_world
    spl = eobj.data.splines[0]
    if spl.type == "POLY":
        pts = [mw @ Vector((p.co.x, p.co.y, p.co.z)) for p in spl.points]
    else:
        pts = [mw @ bp.co for bp in spl.bezier_points]
    return pts


def ensure_tooth_params(obj):
    if obj.get("SMILE_TWEAK_INIT") == 1:
        return
    obj["SMILE_TWEAK_INIT"] = 1
    obj["SMILE_W_SCALE"] = 1.0
    obj["SMILE_L_SCALE"] = 1.0
    obj["SMILE_CANT_DEG"] = 0.0
    obj["SMILE_MIDLINE_MM"] = 0.0
    obj["SMILE_GHOST"] = 0
    obj["SMILE_BRIDGE_ID"] = 0
    obj["SMILE_CONTACT_THICK_MM"] = 0.15


# ============================================================
# ARCH-GEOMETRY TOOTH ORIENTATION SYSTEM
# ============================================================
# Replaces PCA + hardcoded up-vector with arch-curve-derived
# orientation: centroid → outward = facial, tangent = mesio-distal,
# cross product = long axis. Per-tooth Andrews angulation overlay.

# Andrews Six Keys angulation table: (tip_degrees, torque_degrees)
# Tip = rotation around mesio-distal axis (crown mesial tilt)
# Torque = rotation around long axis (crown labial tilt if positive)
_ANGULATION_TABLE = {
    "CENTRAL": (3.0, 7.0),
    "LATERAL": (5.0, 3.0),
    "CANINE": (8.0, -7.0),
    "PREMOLAR": (2.0, -7.0),
    "MOLAR": (0.0, -9.0),
}


def _interprox_project_to_polyline(point_world, polyline_world):
    pts = [Vector(p) for p in (polyline_world or [])]
    if len(pts) < 2:
        return None, Vector((1.0, 0.0, 0.0)), 0.0
    p = Vector(point_world)
    best_q = pts[0].copy()
    best_t = (pts[1] - pts[0]).normalized()
    best_u = 0.0
    best_d2 = (p - best_q).length_squared
    seg_lens = []
    total = 0.0
    for i in range(len(pts) - 1):
        seg_len = (pts[i + 1] - pts[i]).length
        seg_lens.append(seg_len)
        total += seg_len
    if total < 1.0e-12:
        return best_q, best_t, 0.0
    run = 0.0
    for i in range(len(pts) - 1):
        a = pts[i]
        b = pts[i + 1]
        ab = b - a
        ab_len2 = ab.length_squared
        if ab_len2 < 1.0e-12:
            run += seg_lens[i]
            continue
        t = max(0.0, min(1.0, (p - a).dot(ab) / ab_len2))
        q = a + ab * t
        d2 = (p - q).length_squared
        if d2 < best_d2:
            best_d2 = d2
            best_q = q
            best_t = ab.normalized()
            best_u = (run + seg_lens[i] * t) / total
        run += seg_lens[i]
    return best_q, best_t, max(0.0, min(1.0, best_u))


def _interprox_occlusal_curve_points(scene, tooth_id: int):
    """
    Resolve occlusal arch tracer points robustly.
    Returns (points, source_tag, domain_used).
    """
    primary_domain = _interprox_arch_domain_for_tooth(tooth_id)
    secondary_domain = DOMAIN_MAN if primary_domain == DOMAIN_MAX else DOMAIN_MAX

    def _resolve_for_domain(domain: str):
        # Rebuild canonical curve from saved points when possible.
        rebuilt = ensure_arch_curve_from_saved_points(
            scene, domain, ARCH_CURVE_OCCLUSAL, force_rebuild=False
        )
        if rebuilt and rebuilt.type == "CURVE":
            pts = curve_world_points(rebuilt, samples=320)
            if len(pts) >= 2:
                return pts, f"curve:{rebuilt.name}", domain

        candidates = []
        # Canonical names.
        candidates.append(arch_curve_name(domain, ARCH_CURVE_OCCLUSAL))
        # Compatibility aliases seen in older scenes.
        candidates.extend(
            [
                f"ARCH_{domain}_OCCLUSAL_CURVE",
                f"ARCH_{domain}_INCISAL_CURVE",
                f"ARCH_{domain}_CUSP_CURVE",
                f"SMILE_{domain}_INCISAL_CURVE",
                f"ARCH_{domain}_CURVE",
            ]
        )
        # Dedupe while preserving order.
        seen = set()
        ordered = [
            nm for nm in candidates if nm and (nm not in seen and not seen.add(nm))
        ]
        for nm in ordered:
            cobj = bpy.data.objects.get(nm)
            if cobj and cobj.type == "CURVE":
                pts = curve_world_points(cobj, samples=320)
                if len(pts) >= 2:
                    return pts, f"curve:{nm}", domain

        # Try helper that scans incisal candidates.
        cobj = find_arch_incisal_curve(domain)
        if cobj and cobj.type == "CURVE":
            pts = curve_world_points(cobj, samples=320)
            if len(pts) >= 2:
                return pts, f"curve:{cobj.name}", domain

        # Fallback to stored scene points.
        raw = get_arch_points(scene, domain, ARCH_CURVE_OCCLUSAL)
        if len(raw) >= 2:
            return [Vector(v) for v in raw], f"scene_key:{domain}", domain

        return [], "", domain

    pts, src_tag, used_domain = _resolve_for_domain(primary_domain)
    if len(pts) >= 2:
        return pts, src_tag, used_domain

    # Soft fallback to opposite arch only if primary is missing completely.
    pts2, src_tag2, used_domain2 = _resolve_for_domain(secondary_domain)
    if len(pts2) >= 2:
        return pts2, src_tag2, used_domain2

    return [], "", primary_domain


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


def _cad_autopin_reference_from_import(
    context, imported_objs, preferred_obj=None, force_replace=False
):
    """
    Auto-pin Stage E reference from imported objects when tooth ID matches CAD target.
    Conservative by design: no ID match => no auto-pin.
    """
    if not context or not context.scene:
        return False, ""
    scene = context.scene
    p = scene.smile_v2
    if (not bool(getattr(p, "cad_auto_pin_reference_on_import", True))) and (
        not bool(force_replace)
    ):
        return False, ""

    tid = _cad_target_tid(scene)
    if tid <= 0:
        return False, ""

    imported = [
        o
        for o in (imported_objs or [])
        if o and o.type == "MESH" and o.name in bpy.data.objects
    ]
    if not imported:
        return False, ""

    # Keep explicit user pin unless invalid or force requested.
    cur_pin = str(getattr(p, "cad_outer_source_name", "") or "").strip()
    if cur_pin and not bool(force_replace):
        cur = bpy.data.objects.get(cur_pin)
        if cur and cur.type == "MESH" and _cad_tooth_id_from_obj(cur) == int(tid):
            return False, ""

    pref = preferred_obj if (preferred_obj and preferred_obj.type == "MESH") else None
    best = None
    best_score = -99999
    for o in imported:
        oid = _cad_tooth_id_from_obj(o)
        if int(oid) != int(tid):
            continue
        s = _cad_outer_source_score(o, tid, active=pref)
        if s > best_score:
            best_score = s
            best = o
    if not best:
        return False, ""

    try:
        p.cad_outer_source_name = str(best.name)
    except Exception:
        return False, ""
    return True, str(best.name)


def _import_calib_key_for_arch(arch: str) -> str:
    a = str(arch or "").upper()
    return KEY_IMPORT_CALIB_MAX if a == "MAX" else KEY_IMPORT_CALIB_MAN


def _save_import_scan_lm3(scene, tooth_id: int, points_world):
    if not scene or int(tooth_id) <= 0:
        return
    pts = []
    for p in (points_world or [])[:3]:
        v = Vector(p)
        pts.append([float(v.x), float(v.y), float(v.z)])
    payload = {
        "tooth_id": int(tooth_id),
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "points_world": pts,
    }
    scene[_import_scan_lm3_key(tooth_id)] = json.dumps(payload, sort_keys=True)


def _load_import_scan_lm3(scene, tooth_id: int):
    if not scene or int(tooth_id) <= 0:
        return []
    raw = scene.get(_import_scan_lm3_key(tooth_id), "")
    payload = _json_obj(raw, default={})
    pts = []
    if isinstance(payload, dict):
        for p in payload.get("points_world", [])[:3]:
            try:
                pts.append(Vector((float(p[0]), float(p[1]), float(p[2]))))
            except Exception:
                continue
    return pts


def _clear_import_scan_lm3(scene, tooth_id: int):
    if not scene or int(tooth_id) <= 0:
        return
    key = _import_scan_lm3_key(tooth_id)
    if key in scene:
        del scene[key]


def _save_import_tooth_lm3_local(obj, points_local):
    if not obj or obj.type != "MESH":
        return False
    pts = []
    for p in (points_local or [])[:3]:
        v = Vector(p)
        pts.append([float(v.x), float(v.y), float(v.z)])
    if len(pts) < 3:
        return False
    obj[KEY_IMPORT_TOOTH_LM3_LOCAL] = json.dumps({"points_local": pts}, sort_keys=True)
    return True


def _load_import_tooth_lm3_local(obj):
    if not obj or obj.type != "MESH":
        return []
    raw = obj.get(KEY_IMPORT_TOOTH_LM3_LOCAL, "")
    payload = _json_obj(raw, default={})
    pts = []
    if isinstance(payload, dict):
        for p in payload.get("points_local", [])[:3]:
            try:
                pts.append(Vector((float(p[0]), float(p[1]), float(p[2]))))
            except Exception:
                continue
    return pts


def _clear_import_tooth_lm3_local(obj):
    if not obj or obj.type != "MESH":
        return
    try:
        if KEY_IMPORT_TOOTH_LM3_LOCAL in obj:
            del obj[KEY_IMPORT_TOOTH_LM3_LOCAL]
    except Exception:
        pass


def _arch_of_tooth_id(tooth_id: int) -> str:
    tid = int(tooth_id or 0)
    return "MAX" if 1 <= tid <= 16 else "MAN"


def _sample_polyline_u(points, u):
    pts, acc, total = _polyline_prepare(points)
    if not pts:
        return None
    if len(pts) == 1 or total <= 1.0e-12:
        return pts[0]
    target = max(0.0, min(1.0, float(u))) * total
    for i in range(len(pts) - 1):
        a_len = acc[i]
        b_len = acc[i + 1]
        if target <= b_len or i == len(pts) - 2:
            span = max(b_len - a_len, 1.0e-12)
            t = (target - a_len) / span
            return pts[i].lerp(pts[i + 1], max(0.0, min(1.0, t)))
    return pts[-1]


def _estimate_tooth_src_world_mdc(obj):
    if not obj or obj.type != "MESH":
        return []
    local_pts = _load_import_tooth_lm3_local(obj)
    if len(local_pts) >= 3:
        return [obj.matrix_world @ Vector(p) for p in local_pts[:3]]

    bb_local = [Vector(c) for c in obj.bound_box] if obj.bound_box else []
    if not bb_local:
        return []
    mn = Vector(
        (
            min(v.x for v in bb_local),
            min(v.y for v in bb_local),
            min(v.z for v in bb_local),
        )
    )
    mx = Vector(
        (
            max(v.x for v in bb_local),
            max(v.y for v in bb_local),
            max(v.z for v in bb_local),
        )
    )
    p1_l = Vector((mn.x, mn.y, mn.z))
    p2_l = Vector((mx.x, mn.y, mn.z))
    p3_l = Vector(((mn.x + mx.x) * 0.5, mn.y, mx.z))
    return [obj.matrix_world @ p1_l, obj.matrix_world @ p2_l, obj.matrix_world @ p3_l]


def _auto_calibrate_arch_mdc_from_curves(
    context,
    arch: str,
    anchor_tooth_id=0,
    exclude_names=None,
    require_marked=True,
    include_names=None,
):
    if exclude_names is None:
        exclude_names = set()
    if include_names is not None:
        include_names = set(str(n) for n in include_names if n)
    scene = context.scene
    p = scene.smile_v2
    arch_u = str(arch or "").upper()
    domain = DOMAIN_MAX if arch_u == "MAX" else DOMAIN_MAN

    inc_curve = bpy.data.objects.get(arch_curve_name(domain, ARCH_CURVE_OCCLUSAL))
    cerv_curve = bpy.data.objects.get(arch_curve_name(domain, ARCH_CURVE_CERVICAL))
    if not inc_curve or inc_curve.type != "CURVE":
        return 0

    try:
        inc_pts = curve_world_points(inc_curve)
    except Exception:
        inc_pts = []
    if len(inc_pts) < 2:
        return 0

    cerv_pts = []
    if cerv_curve and cerv_curve.type == "CURVE":
        try:
            cerv_pts = curve_world_points(cerv_curve)
        except Exception:
            cerv_pts = []
    if len(cerv_pts) < 2:
        return 0

    # Preferred reference: user-marked midline/cervical 2-point arch reference.
    oc_ref, cv_ref, _meta = _load_import_arch_reference(scene, arch_u)
    if oc_ref is None:
        anchor_tid = int(anchor_tooth_id or 0)
        if anchor_tid <= 0:
            anchor_tid = 8 if arch_u == "MAX" else 24
        anchor_scan = _load_import_scan_lm3(scene, anchor_tid)
        if len(anchor_scan) >= 3:
            a_m = Vector(anchor_scan[0])
            a_d = Vector(anchor_scan[1])
            a_c = Vector(anchor_scan[2])
            oc_ref = (a_m + a_d) * 0.5
            cv_ref = a_c
    if oc_ref is None:
        oc_ref = _sample_polyline_u(inc_pts, 0.5)
    if cv_ref is None:
        cv_ref = oc_ref + Vector((0.0, 0.0, 2.0))
    if oc_ref is None:
        return 0

    anchor_ic = Vector(cv_ref) - Vector(oc_ref)
    _mid_q, _mid_tan, u_mid = _project_point_to_polyline(Vector(oc_ref), inc_pts)
    mid_on_curve = (
        _sample_polyline_u(inc_pts, u_mid) if _mid_q is not None else Vector(oc_ref)
    )

    col = bpy.data.collections.get(COL_TEETH)
    if not col:
        return 0
    changed = 0
    for obj in list(col.objects):
        if not obj or obj.type != "MESH" or obj.name in exclude_names:
            continue
        if include_names is not None and obj.name not in include_names:
            continue
        tid = parse_tooth_id_from_name(obj.name) or int(
            obj.get("SMILE_TOOTH_ID", 0) or 0
        )
        if tid <= 0 or _arch_of_tooth_id(tid) != arch_u:
            continue
        if require_marked and not _has_import_tooth_lm3_local(obj):
            continue

        src = _estimate_tooth_src_world_mdc(obj)
        if len(src) < 3:
            continue
        center = (src[0] + src[1]) * 0.5
        inc_mid, tan, u = _project_point_to_polyline(center, inc_pts)
        if inc_mid is None or tan.length < 1.0e-9:
            continue
        tan = tan.normalized()
        half_w = max((src[1] - src[0]).length * 0.5, 0.05)
        # Mesial direction points toward midline along curve tangent.
        to_mid = Vector(mid_on_curve) - Vector(inc_mid)
        mesial_sign = 1.0 if to_mid.dot(tan) >= 0.0 else -1.0
        dst_m = inc_mid + tan * (half_w * mesial_sign)
        dst_d = inc_mid - tan * (half_w * mesial_sign)
        dst_c = _sample_polyline_u(cerv_pts, u)
        if dst_c is None:
            dst_c = inc_mid + anchor_ic

        try:
            R, T, _s = procrustes_solver(src, [dst_m, dst_d, dst_c], with_scaling=False)
            M = Matrix.Identity(4)
            for i in range(3):
                for j in range(3):
                    M[i][j] = float(R[i][j])
            M[0][3], M[1][3], M[2][3] = float(T.x), float(T.y), float(T.z)
            obj.matrix_world = M @ obj.matrix_world
            changed += 1
        except Exception:
            continue
    return changed


def _scan_candidate_names(context):
    p = context.scene.smile_v2
    names = set()
    for nm in (
        str(getattr(p, "max_target", "") or "").strip(),
        str(getattr(p, "man_target", "") or "").strip(),
    ):
        if nm:
            o = bpy.data.objects.get(nm)
            if o and o.type == "MESH":
                names.add(o.name)
    col_scans = bpy.data.collections.get(COL_SCANS)
    if col_scans:
        for o in col_scans.objects:
            if o and o.type == "MESH":
                names.add(o.name)
    # Fallback for scenes where scan meshes are not linked to COL_SCANS
    # and targets are not set yet: trust current active/selected mesh(es).
    if not names:
        act = context.view_layer.objects.active
        if act and act.type == "MESH":
            names.add(act.name)
        for o in context.selected_objects:
            if o and o.type == "MESH":
                names.add(o.name)
    return names


def _matrix_to_rows4(m: Matrix):
    return [[float(m[r][c]) for c in range(4)] for r in range(4)]


def _rows4_to_matrix(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) != 4:
        return None
    try:
        m = Matrix(rows)
        if m and len(m.col) == 4:
            return m
    except Exception:
        return None
    return None


def _save_import_calibration(
    scene, arch: str, rs_matrix_4x4: Matrix, anchor_tooth_id=0, anchor_name=""
):
    if not scene or rs_matrix_4x4 is None:
        return
    key = _import_calib_key_for_arch(arch)
    payload = {
        "arch": str(arch).upper(),
        "anchor_tooth_id": int(anchor_tooth_id or 0),
        "anchor_name": str(anchor_name or ""),
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "matrix": _matrix_to_rows4(rs_matrix_4x4),
    }
    scene[key] = json.dumps(payload, sort_keys=True)


def _load_import_calibration(scene, arch: str):
    if not scene:
        return None, {}
    key = _import_calib_key_for_arch(arch)
    raw = scene.get(key, "")
    payload = _json_obj(raw, default={})
    mat = (
        _rows4_to_matrix(payload.get("matrix", []))
        if isinstance(payload, dict)
        else None
    )
    return mat, payload if isinstance(payload, dict) else {}


def _clear_import_calibration(scene, arch: str):
    if not scene:
        return
    key = _import_calib_key_for_arch(arch)
    if key in scene:
        del scene[key]


def _has_import_calibration(scene, arch: str) -> bool:
    m, _ = _load_import_calibration(scene, arch)
    return m is not None


def _import_arch_ref_key_for_arch(arch: str) -> str:
    a = str(arch or "").upper()
    return KEY_IMPORT_ARCH_REF_MAX if a == "MAX" else KEY_IMPORT_ARCH_REF_MAN


def _save_import_arch_reference(
    scene, arch: str, occlusal_mid_world, cervical_mid_world
):
    if not scene:
        return
    oc = Vector(occlusal_mid_world)
    cv = Vector(cervical_mid_world)
    payload = {
        "arch": str(arch).upper(),
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "occlusal_mid_world": [float(oc.x), float(oc.y), float(oc.z)],
        "cervical_mid_world": [float(cv.x), float(cv.y), float(cv.z)],
    }
    scene[_import_arch_ref_key_for_arch(arch)] = json.dumps(payload, sort_keys=True)


def _load_import_arch_reference(scene, arch: str):
    if not scene:
        return None, None, {}
    key = _import_arch_ref_key_for_arch(arch)
    payload = _json_obj(scene.get(key, ""), default={})
    if not isinstance(payload, dict):
        return None, None, {}
    try:
        oc = payload.get("occlusal_mid_world", None)
        cv = payload.get("cervical_mid_world", None)
        oc_v = (
            Vector((float(oc[0]), float(oc[1]), float(oc[2])))
            if oc and len(oc) >= 3
            else None
        )
        cv_v = (
            Vector((float(cv[0]), float(cv[1]), float(cv[2])))
            if cv and len(cv) >= 3
            else None
        )
        return oc_v, cv_v, payload
    except Exception:
        return None, None, payload


def _clear_import_arch_reference(scene, arch: str):
    if not scene:
        return
    key = _import_arch_ref_key_for_arch(arch)
    if key in scene:
        del scene[key]


def _has_import_arch_reference(scene, arch: str) -> bool:
    oc, cv, _ = _load_import_arch_reference(scene, arch)
    return (oc is not None) and (cv is not None)


def _mirror_midline_key_for_arch(arch: str) -> str:
    a = str(arch or "").upper()
    return KEY_MIRROR_MIDLINE_MAX if a == "MAX" else KEY_MIRROR_MIDLINE_MAN


def _save_mirror_midline_point(scene, arch: str, point_world):
    if not scene or point_world is None:
        return
    p = Vector(point_world)
    payload = {
        "arch": str(arch).upper(),
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "point_world": [float(p.x), float(p.y), float(p.z)],
    }
    scene[_mirror_midline_key_for_arch(arch)] = json.dumps(payload, sort_keys=True)


def _load_mirror_midline_point(scene, arch: str):
    if not scene:
        return None, {}
    raw = scene.get(_mirror_midline_key_for_arch(arch), "")
    payload = _json_obj(raw, default={})
    if not isinstance(payload, dict):
        return None, {}
    try:
        q = payload.get("point_world", None)
        if q and len(q) >= 3:
            return Vector((float(q[0]), float(q[1]), float(q[2]))), payload
    except Exception:
        pass
    return None, payload


def _clear_mirror_midline_point(scene, arch: str):
    if not scene:
        return
    k = _mirror_midline_key_for_arch(arch)
    if k in scene:
        del scene[k]


def _has_mirror_midline_point(scene, arch: str) -> bool:
    p, _ = _load_mirror_midline_point(scene, arch)
    return p is not None


def _iter_imported_teeth_objects():
    col = bpy.data.collections.get(COL_TEETH)
    objs = list(col.objects) if col else []
    out = []
    for obj in objs:
        if not obj or obj.type != "MESH":
            continue
        tid = parse_tooth_id_from_name(obj.name) or int(
            obj.get("SMILE_TOOTH_ID", 0) or 0
        )
        if tid <= 0:
            continue
        out.append((int(tid), obj))
    out.sort(key=lambda it: (it[0], str(it[1].name)))
    return out


def _refresh_imported_mdc_status_list(scene):
    if not scene or not hasattr(scene, "smile_v2"):
        return 0
    p = scene.smile_v2
    p.imported_mdc_items.clear()
    rows = _iter_imported_teeth_objects()
    for tid, obj in rows:
        it = p.imported_mdc_items.add()
        it.tooth_id = int(tid)
        it.obj_name = str(obj.name)
        it.mdc_marked = bool(_has_import_tooth_lm3_local(obj))
    if len(p.imported_mdc_items) > 0:
        p.imported_mdc_active_index = max(
            0, min(int(p.imported_mdc_active_index), len(p.imported_mdc_items) - 1)
        )
    else:
        p.imported_mdc_active_index = 0
    return len(rows)


def _count_marked_imported_teeth_for_arch(arch: str) -> int:
    a = str(arch or "").upper()
    n = 0
    for tid, obj in _iter_imported_teeth_objects():
        if _arch_of_tooth_id(tid) != a:
            continue
        if _has_import_tooth_lm3_local(obj):
            n += 1
    return n


def _contralateral_universal_tooth_id(tid: int) -> int:
    """Universal numbering contralateral map.
    Upper: 1<->16 ... 8<->9 (17 - tid)
    Lower: 17<->32 ... 24<->25 (49 - tid)
    """
    t = int(tid or 0)
    if 1 <= t <= 16:
        return 17 - t
    if 17 <= t <= 32:
        return 49 - t
    return 0


def _is_right_side_universal(tid: int) -> bool:
    t = int(tid or 0)
    return (1 <= t <= 8) or (25 <= t <= 32)


def _is_left_side_universal(tid: int) -> bool:
    t = int(tid or 0)
    return (9 <= t <= 16) or (17 <= t <= 24)


def _mirror_matrix_about_plane(plane_point: Vector, plane_normal: Vector) -> Matrix:
    """Build 4x4 world reflection matrix about a plane."""
    p = Vector(plane_point)
    n = Vector(plane_normal)
    if n.length < 1.0e-12:
        n = Vector((1.0, 0.0, 0.0))
    else:
        n.normalize()

    # R = I - 2*n*n^T
    r00 = 1.0 - 2.0 * n.x * n.x
    r01 = -2.0 * n.x * n.y
    r02 = -2.0 * n.x * n.z
    r10 = -2.0 * n.y * n.x
    r11 = 1.0 - 2.0 * n.y * n.y
    r12 = -2.0 * n.y * n.z
    r20 = -2.0 * n.z * n.x
    r21 = -2.0 * n.z * n.y
    r22 = 1.0 - 2.0 * n.z * n.z
    R = Matrix(((r00, r01, r02), (r10, r11, r12), (r20, r21, r22)))

    # x' = R*x + (p - R*p)
    t = p - (R @ p)

    M = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            M[i][j] = R[i][j]
    M[0][3] = float(t.x)
    M[1][3] = float(t.y)
    M[2][3] = float(t.z)
    return M


def _arch_midline_mirror_plane(scene, arch: str):
    """Return (point, normal, quality_tag) for sagittal mirror plane of arch."""
    a = str(arch or "").upper()
    p = scene.smile_v2 if (scene and hasattr(scene, "smile_v2")) else None
    use_manual = bool(getattr(p, "mirror_use_manual_midline", True)) if p else True
    oc_ref, cv_ref, _meta = _load_import_arch_reference(scene, a)
    occ_pts, _src, _used = _interprox_occlusal_curve_points(
        scene, 8 if a == "MAX" else 24
    )
    manual_point, _mmeta = _load_mirror_midline_point(scene, a)

    point = manual_point.copy() if (use_manual and manual_point is not None) else None
    if point is None:
        point = oc_ref.copy() if oc_ref is not None else None
    if point is None and len(occ_pts) >= 2:
        point = _sample_polyline_u(occ_pts, 0.5)
    if point is None:
        point = Vector((0.0, 0.0, 0.0))

    normal = None
    if len(occ_pts) >= 2:
        q, tan, _u = _interprox_project_to_polyline(point, occ_pts)
        if q is not None and tan.length > 1.0e-8:
            # Mirror plane should be sagittal/vertical; keep horizontal L-R direction.
            t = tan.normalized()
            normal = Vector((t.x, t.y, 0.0))
            if normal.length > 1.0e-8:
                normal.normalize()
            else:
                normal = None
    if normal is None or normal.length < 1.0e-8:
        normal = Vector((1.0, 0.0, 0.0))
        if use_manual and manual_point is not None:
            quality = f"{a}:manual_point+fallback_world_x"
        else:
            quality = f"{a}:fallback_world_x"
    else:
        if use_manual and manual_point is not None:
            quality = f"{a}:manual_point+arch_tangent"
        else:
            quality = f"{a}:arch_tangent"

    # Keep deterministic sign convention.
    if normal.x < 0.0:
        normal = -normal

    return point, normal, quality


def _rename_with_target_tooth_id(name: str, source_tid: int, target_tid: int) -> str:
    s = str(name or "")
    st = int(source_tid or 0)
    tt = int(target_tid or 0)
    if st > 0:
        s2 = re.sub(rf"_T{st}(?!\d)", f"_T{tt}", s)
        if s2 != s:
            return s2
        s2 = re.sub(rf"#\s*{st}(?!\d)", f"#{tt}", s)
        if s2 != s:
            return s2
    if re.search(r"_T\d+(?!\d)", s):
        return re.sub(r"_T\d+(?!\d)", f"_T{tt}", s)
    return f"{s}_T{tt}"


def _is_obj_in_collection(obj, col_name: str) -> bool:
    if not obj:
        return False
    col = bpy.data.collections.get(col_name)
    if not col:
        return False
    try:
        return obj.name in col.objects
    except Exception:
        return False


def _find_imported_tooth_by_tid(tooth_id: int):
    tid = int(tooth_id or 0)
    if tid <= 0:
        return None
    col = bpy.data.collections.get(COL_TEETH)
    if not col:
        return None
    matches = []
    for obj in col.objects:
        if not obj or obj.type != "MESH":
            continue
        oid = parse_tooth_id_from_name(obj.name) or int(
            obj.get("SMILE_TOOTH_ID", 0) or 0
        )
        if int(oid) == tid:
            matches.append(obj)
    if not matches:
        return None
    matches.sort(
        key=lambda o: (
            0 if bool(o.get("SMILE_IS_TOOTH", False)) else 1,
            len(str(o.name)),
            str(o.name),
        )
    )
    return matches[0]


def _flip_mesh_winding_inplace(mesh_data):
    if not mesh_data:
        return False
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh_data)
        if bm.faces:
            bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
            bm.normal_update()
            bm.to_mesh(mesh_data)
            mesh_data.update()
        return True
    except Exception:
        return False
    finally:
        bm.free()


def _recalc_mesh_normals_outward(mesh_data):
    if not mesh_data:
        return False
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh_data)
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.normal_update()
            bm.to_mesh(mesh_data)
        try:
            mesh_data.calc_normals()
        except Exception:
            pass
        mesh_data.update()
        return True
    except Exception:
        return False
    finally:
        bm.free()


def _mirror_duplicate_imported_tooth(
    scene, source_obj, source_tid: int, target_tid: int, replace_existing=True
):
    if not source_obj or source_obj.type != "MESH":
        return None, "invalid_source"
    st = int(source_tid or 0)
    tt = int(target_tid or 0)
    if st <= 0 or tt <= 0:
        return None, "invalid_tooth_id"

    existing = _find_imported_tooth_by_tid(tt)
    if existing and replace_existing:
        try:
            bpy.data.objects.remove(existing, do_unlink=True)
        except Exception:
            return None, "remove_existing_failed"

    col = ensure_collection(COL_TEETH)
    dup = source_obj.copy()
    dup.data = source_obj.data.copy()
    dup.name = _rename_with_target_tooth_id(source_obj.name, st, tt)
    dup["SMILE_TOOTH_ID"] = int(tt)
    link_to_collection(dup, col)

    arch = _arch_of_tooth_id(st)
    plane_point, plane_normal, quality = _arch_midline_mirror_plane(scene, arch)
    M_mirror = _mirror_matrix_about_plane(plane_point, plane_normal)
    # Keep object transform non-reflected to avoid viewport/matcap shading asymmetry.
    # Bake reflection into local mesh data instead:
    #   L = inv(M_src) * M_reflect * M_src  (local-space reflection)
    # and keep matrix_world ~= source matrix.
    M_src = source_obj.matrix_world.copy()
    try:
        L_reflect_local = M_src.inverted_safe() @ M_mirror @ M_src
    except Exception:
        L_reflect_local = Matrix.Identity(4)
    dup.matrix_world = M_src.copy()
    try:
        dup.data.transform(L_reflect_local)
    except Exception:
        # Fallback to legacy world-transform mirror if local bake fails.
        dup.matrix_world = M_mirror @ source_obj.matrix_world
    _flip_mesh_winding_inplace(dup.data)
    _recalc_mesh_normals_outward(dup.data)
    try:
        if dup.parent:
            mw = dup.matrix_world.copy()
            dup.parent = None
            dup.matrix_world = mw
    except Exception:
        pass
    return dup, quality


def _cervical_curve_points_for_arch(arch: str):
    domain = DOMAIN_MAX if str(arch).upper() == "MAX" else DOMAIN_MAN
    name = arch_curve_name(domain, ARCH_CURVE_CERVICAL)
    c = bpy.data.objects.get(name)
    if not c or c.type != "CURVE":
        return []
    try:
        return curve_world_points(c)
    except Exception:
        return []


def _mirror_fit_to_occlusal_arch(scene, source_obj, mirrored_obj, source_tid: int):
    """Re-fit mirrored tooth so incisal/cusp follows mirrored position on occlusal arch tracer."""
    if not source_obj or not mirrored_obj:
        return False, "missing_obj"
    arch = _arch_of_tooth_id(source_tid)
    occ_pts, _occ_src, _occ_domain = _interprox_occlusal_curve_points(
        scene, int(source_tid or 0)
    )
    if len(occ_pts) < 2:
        return False, "missing_occlusal_curve"

    plane_point, _plane_normal, _q = _arch_midline_mirror_plane(scene, arch)
    q_mid, _tan_mid, u_mid = _interprox_project_to_polyline(plane_point, occ_pts)
    if q_mid is None:
        u_mid = 0.5

    src_world = _estimate_tooth_src_world_mdc(source_obj)
    if len(src_world) >= 2:
        src_center = (src_world[0] + src_world[1]) * 0.5
    else:
        src_center = source_obj.matrix_world.translation.copy()

    q_src, _tan_src, u_src = _interprox_project_to_polyline(src_center, occ_pts)
    if q_src is None:
        return False, "source_project_fail"
    u_dst = max(0.0, min(1.0, (2.0 * float(u_mid)) - float(u_src)))

    inc_mid = _sample_polyline_u(occ_pts, u_dst)
    if inc_mid is None:
        return False, "sample_fail"
    q_t, tan_t, _u_chk = _interprox_project_to_polyline(inc_mid, occ_pts)
    if q_t is not None:
        inc_mid = q_t
    if tan_t is None or tan_t.length < 1.0e-9:
        tan_t = Vector((1.0, 0.0, 0.0))
    else:
        tan_t = tan_t.normalized()
    mid_on_curve = _sample_polyline_u(occ_pts, u_mid) or inc_mid

    mir_world = _estimate_tooth_src_world_mdc(mirrored_obj)
    if len(mir_world) < 2:
        delta = Vector(inc_mid) - mirrored_obj.matrix_world.translation
        mw = mirrored_obj.matrix_world.copy()
        mw.translation = mw.translation + delta
        mirrored_obj.matrix_world = mw
        return True, "translate_only"

    half_w = max((mir_world[1] - mir_world[0]).length * 0.5, 0.05)
    to_mid = Vector(mid_on_curve) - Vector(inc_mid)
    mesial_sign = 1.0 if to_mid.dot(tan_t) >= 0.0 else -1.0
    dst_m = Vector(inc_mid) + tan_t * (half_w * mesial_sign)
    dst_d = Vector(inc_mid) - tan_t * (half_w * mesial_sign)

    cerv_pts = _cervical_curve_points_for_arch(arch)
    if len(mir_world) >= 3:
        dst_c = _sample_polyline_u(cerv_pts, u_dst) if len(cerv_pts) >= 2 else None
        if dst_c is None:
            cur_center = (mir_world[0] + mir_world[1]) * 0.5
            dst_c = Vector(inc_mid) + (mir_world[2] - cur_center)
        src_fit = [mir_world[0], mir_world[1], mir_world[2]]
        dst_fit = [dst_m, dst_d, dst_c]
        try:
            R, T, _s = procrustes_solver(src_fit, dst_fit, with_scaling=False)
            M = Matrix.Identity(4)
            for i in range(3):
                for j in range(3):
                    M[i][j] = float(R[i][j])
            M[0][3], M[1][3], M[2][3] = float(T.x), float(T.y), float(T.z)
            mirrored_obj.matrix_world = M @ mirrored_obj.matrix_world
            return True, "curve_fit_mdc"
        except Exception:
            pass

    cur_center = (mir_world[0] + mir_world[1]) * 0.5
    delta = Vector(inc_mid) - cur_center
    mw = mirrored_obj.matrix_world.copy()
    mw.translation = mw.translation + delta
    mirrored_obj.matrix_world = mw
    return True, "translate_md_center"


def _reflect_point_about_plane(
    point_world: Vector, plane_point: Vector, plane_normal: Vector
) -> Vector:
    p = Vector(point_world)
    c = Vector(plane_point)
    n = Vector(plane_normal)
    if n.length < 1.0e-12:
        n = Vector((1.0, 0.0, 0.0))
    else:
        n.normalize()
    d = (p - c).dot(n)
    return p - (2.0 * d) * n


def _solve_yaw_translation_transform(src_points, dst_points):
    """Best-fit yaw + translation transform mapping src->dst in world space."""
    src = [Vector(p) for p in (src_points or [])]
    dst = [Vector(p) for p in (dst_points or [])]
    n = min(len(src), len(dst))
    if n <= 0:
        return None, "no_points"
    if n == 1:
        t = dst[0] - src[0]
        M = Matrix.Identity(4)
        M[0][3], M[1][3], M[2][3] = float(t.x), float(t.y), float(t.z)
        return M, "translate_only"

    c_src = Vector((0.0, 0.0, 0.0))
    c_dst = Vector((0.0, 0.0, 0.0))
    for i in range(n):
        c_src += src[i]
        c_dst += dst[i]
    c_src /= float(n)
    c_dst /= float(n)

    num = 0.0
    den = 0.0
    for i in range(n):
        xs = src[i].x - c_src.x
        ys = src[i].y - c_src.y
        xd = dst[i].x - c_dst.x
        yd = dst[i].y - c_dst.y
        num += xs * yd - ys * xd
        den += xs * xd + ys * yd
    yaw = math.atan2(num, den) if (abs(num) > 1.0e-12 or abs(den) > 1.0e-12) else 0.0

    Rz = Matrix.Rotation(yaw, 4, "Z")
    c_src_rot = Rz @ c_src
    txy = Vector((c_dst.x - c_src_rot.x, c_dst.y - c_src_rot.y, 0.0))
    z_src_mean = sum(src[i].z for i in range(n)) / float(n)
    z_dst_mean = sum(dst[i].z for i in range(n)) / float(n)
    tz = z_dst_mean - z_src_mean

    M = Matrix.Identity(4)
    for r in range(3):
        for c in range(3):
            M[r][c] = Rz[r][c]
    M[0][3] = float(txy.x)
    M[1][3] = float(txy.y)
    M[2][3] = float(tz)
    return M, "yaw_translate"


def _mirror_group_fit_to_occlusal_arch(
    scene, arch: str, group_rows, require_marked=True
):
    """Apply one rigid transform per arch so mirrored set keeps arrangement while following occlusal curve."""
    rows = list(group_rows or [])
    if not rows:
        return False, {"reason": "empty_group"}
    occ_pts, _src, _dom = _interprox_occlusal_curve_points(
        scene, 8 if str(arch).upper() == "MAX" else 24
    )
    if len(occ_pts) < 2:
        return False, {"reason": "missing_occlusal_curve"}

    plane_point, plane_normal, _q = _arch_midline_mirror_plane(scene, arch)
    src_fit = []
    dst_fit = []
    used = 0
    skipped_unmarked = 0
    skipped_invalid = 0

    mirrored_objs = []
    for tid, src_obj, mir_obj in rows:
        if mir_obj and mir_obj.type == "MESH":
            mirrored_objs.append(mir_obj)
        if not src_obj or not mir_obj:
            skipped_invalid += 1
            continue
        if require_marked and (not _has_import_tooth_lm3_local(src_obj)):
            skipped_unmarked += 1
            continue
        src_w = _estimate_tooth_src_world_mdc(src_obj)
        mir_w = _estimate_tooth_src_world_mdc(mir_obj)
        if len(src_w) < 2 or len(mir_w) < 2:
            skipped_invalid += 1
            continue

        center_src = (src_w[0] + src_w[1]) * 0.5
        center_cur = (mir_w[0] + mir_w[1]) * 0.5
        center_ref = _reflect_point_about_plane(center_src, plane_point, plane_normal)
        q, _tan, _u = _interprox_project_to_polyline(center_ref, occ_pts)
        if q is None:
            skipped_invalid += 1
            continue
        src_fit.append(center_cur)
        dst_fit.append(q)
        used += 1

    if used <= 0:
        return False, {
            "reason": "no_valid_anchors",
            "used": 0,
            "skipped_unmarked": int(skipped_unmarked),
            "skipped_invalid": int(skipped_invalid),
        }

    M, mode = _solve_yaw_translation_transform(src_fit, dst_fit)
    if M is None:
        return False, {"reason": "solve_fail", "used": int(used)}

    for obj in mirrored_objs:
        try:
            obj.matrix_world = M @ obj.matrix_world
        except Exception:
            pass

    return True, {
        "reason": "ok",
        "used": int(used),
        "mode": str(mode),
        "skipped_unmarked": int(skipped_unmarked),
        "skipped_invalid": int(skipped_invalid),
    }


def _apply_import_calibration_to_mesh(obj, rs_matrix_4x4: Matrix):
    if not obj or obj.type != "MESH" or rs_matrix_4x4 is None:
        return False
    try:
        obj.data.transform(rs_matrix_4x4)
        obj.data.update()
        return True
    except Exception:
        return False


def procrustes_solver(src_pts_list, dst_pts_list, with_scaling=True):
    """
    Computes the optimal rigid transformation that best maps src_pts to dst_pts.
    Minimizes sum squared error (SSE): sum || s * R * (p_i - c_src) + c_dst - q_i ||^2

    Args:
        src_pts_list (list of Vector/[x,y,z]): Source points (Move this set)
        dst_pts_list (list of Vector/[x,y,z]): Destination points (Fixed target)
        with_scaling (bool): If True, computes uniform scale factor 's'. Else s=1.0.

    Returns:
        (Matrix, Matrix, float): (Rotation_3x3, Translation_Vector, Scale)

    Ref:
        Arun et al. "Least-Squares Fitting of Two 3-D Point Sets", IEEE TPAMI 1987.
        Umeyama "Least-Squares Estimation of Transformation Parameters", IEEE TPAMI 1991.
    """
    import numpy as np
    from mathutils import Matrix, Vector

    if len(src_pts_list) != len(dst_pts_list) or len(src_pts_list) < 3:
        raise ValueError(f"Need 3+ matching points. Found {len(src_pts_list)}")

    # Convert to numpy arrays (N x 3)
    P = np.array([list(v) for v in src_pts_list])  # Source
    Q = np.array([list(v) for v in dst_pts_list])  # Target

    # 1. Compute Centroids
    centroid_P = np.mean(P, axis=0)  # [x, y, z]
    centroid_Q = np.mean(Q, axis=0)

    # 2. Center the points
    P_centered = P - centroid_P
    Q_centered = Q - centroid_Q

    # 3. Compute Scale (if requested)
    # Scale s = RMS(Q_centered) / RMS(P_centered)
    scale = 1.0
    if with_scaling:
        rms_P = np.sqrt(np.sum(P_centered**2) / len(P))
        rms_Q = np.sqrt(np.sum(Q_centered**2) / len(Q))
        if rms_P > 1e-8:
            scale = rms_Q / rms_P

    # Scale source points for rotation calculation?
    # Actually standard formulation computes covariance on centered points.
    # But for scaling optimization: P_scaled = s * P_centered
    # Umeyama suggests using centered points for covariance.

    # 4. Compute Rotation Matrix (SVD)
    # Covariance Matrix H = (P_centered_Transpose) @ Q_centered
    # But wait, dimensions: P is N x 3.
    # H = (3xN) * (Nx3) = 3x3
    H = np.dot(P_centered.T, Q_centered)

    # SVD
    U, S, Vt = np.linalg.svd(H)

    # Rotation R = V @ U.T
    # Note: numpy returns Vt (V transposed), so R = Vt.T @ U.T = (U @ Vt).T ?
    # Let's verify standard: R = V @ U^T
    # Vt = V.T => V = Vt.T
    # So R = Vt.T @ U.T
    R = np.dot(Vt.T, U.T)

    # Special reflection case (det(R) < 0)
    if np.linalg.det(R) < 0:
        # Multiply 3rd column of R by -1?
        # Actually in SVD approach: Multiply 3rd column of V by -1 (or 3rd row of Vt)
        Vt[2, :] *= -1
        R = np.dot(Vt.T, U.T)

    # 5. Compute Translation
    # t = centroid_Q - s * R @ centroid_P
    # Careful with matrix multiplication order.
    # Points are row vectors in this logic? No, formulation usually assumes column vectors R @ p.
    # But my R is 3x3.
    # np.dot(R, centroid_P) is R @ p (if p is column-like or 1D array treated correctly)

    t = centroid_Q - scale * np.dot(R, centroid_P)

    # Convert to Blender types
    # R_mat is columns or rows?
    # NumPy arrays are row-major?
    # R is a rotation matrix where v_new = R @ v_old.
    # Blender Matrix() constructor takes rows by default.
    # Ideally verify: R = [[r00, r01, r02], ...]

    # Return as Matrix (3x3), Vector (translation), scale (float)
    R_blender = Matrix(R.tolist())  # Blender Matrix from rows
    # But wait, in Blender: Vector is column?
    # mat @ vec. Yes.

    T_blender = Vector(t.tolist())

    return R_blender, T_blender, scale


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

CLASSES = [
    SMILE_OT_place_tooth_seed_on_curve,
    SMILE_OT_measure_dimension,
    SMILE_OT_pnp_capture_2d_landmark,
    SMILE_OT_import_tooth_for_mockup,
    SMILE_OT_snap_mockup_to_arch,
    SMILE_OT_delete_mockup_tooth,
    SMILE_OT_frame2d_apply,
    SMILE_OT_frame3d_apply,
    SMILE_OT_frame3d_select_curve,
    SMILE_OT_frame3d_apply_to_teeth,
    SMILE_OT_frame3d_clear_preview,
    SMILE_OT_frame3d_export_summary,
    SMILE_OT_frame3d_reset_teeth,
    SMILE_OT_crown_shape_edit_start,
    SMILE_OT_crown_shape_edit_stop,
    SMILE_OT_crown_shape_edit_apply_brush,
    SMILE_OT_crown_shape_edit_set_direction,
    SMILE_OT_crown_shape_edit_set_mode,
    SMILE_OT_import_multi_veneer_set,
    SMILE_OT_align_multi_veneer_set,
    SMILE_OT_import_procrustes,
    SMILE_OT_capture_arch_reference_mdc,
    SMILE_OT_clear_arch_reference_mdc,
    SMILE_OT_capture_mirror_midline_point,
    SMILE_OT_clear_mirror_midline_point,
    SMILE_OT_refresh_imported_mdc_list,
    SMILE_OT_select_imported_mdc_item,
    SMILE_OT_mark_imported_mdc_from_list,
    SMILE_OT_capture_scan_landmarks_3pt,
    SMILE_OT_capture_import_tooth_landmarks_3pt,
    SMILE_OT_align_imported_to_scan_landmarks,
    SMILE_OT_mirror_quadrant_set,
    SMILE_OT_clear_import_scan_landmarks_3pt,
    SMILE_OT_clear_import_tooth_landmarks_3pt,
    SMILE_OT_calibrate_import_anchor,
    SMILE_OT_clear_import_calibration,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
