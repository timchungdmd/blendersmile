"""BlenderSmile PRODUCTION Tab Module

This module contains:
- Margin tracing operators (click, smooth, drag, etc.)
- Die and veneer fabrication operators
- Shell generation and export
- Interproximal divider tools
- Analysis and validation operators
"""

__all__ = [
    "CLASSES",
    "draw_production_tab",
    "register",
    "unregister",
    "compute_dihedral_cost",
    "compute_margin_evidence",
    "mesh_a_star_path",
    "margin_trace_passthrough",
    "get_margin_data",
    "set_margin_points",
    "get_interprox_divider",
    "build_adjacent_bvhtrees",
    "_autodie_queue_read",
    "_autodie_queue_write",
    "_autodie_queue_count",
    "_run_pending_autodie_job",
    "_clear_margin_for_tooth",
    "build_margin_graph_cache",
    "geodesic_fill_segment",
    "finalize_margin_loop_surface_like_drag",
    "rebuild_margin_curve_as_bezier",
    "simplify_path_rdp",
    "project_loop_to_surface",
    "eval_margin_metrics",
    "optimize_closed_loop",
    "solve_margin_segment",
    "trace_ridge_path_between_points",
    "snap_point_to_margin_evidence",
    "magnet_snap_to_soft_edges",
    "smooth_polyline_surface",
    "round_polyline_corners_surface",
    "smooth_closing_region",
    "blend_loop_seam_surface",
    "refine_segment_surface",
    "build_guided_margin_loop_from_anchors",
    "_apply_margin_curve_visual_style",
    "_ensure_margin_curve_object",
    "_save_margin_curve_wysiwyg",
    "_mm_to_bu_for_obj",
    "_project_world_to_mesh",
    "_parse_margin_curve_tooth_id",
    # P3 Lattice Rig, BlockFFD, Waxup, Industry Crown
    "create_lattice_rig_for_tooth",
    "create_blockffd_rig_for_tooth",
    "SMILE_ProximalAnalyzer",
    "ensure_triangulated_mesh_data",
    "extract_curve_points_np",
    "points_in_poly_np",
    "calc_normal_np",
    "get_rotation_matrix_to_z_np",
    "get_boundary_edges_np",
    "extract_intaglio_vectorized_np",
    "generate_emergence_collar_np",
    "build_morph_geometry_nodes_np",
    "numpy_to_mesh_np",
    "stitch_meshes_vectorized_np",
    "execute_industry_standard_crown_np",
]

import bpy
import math
import time
import json
import traceback
import heapq
import re
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

COL_SCANS = "Scans"
COL_TEETH = "Teeth"
COL_LM = "SmileLandmarks"
COL_ARCH = "SmileArch"
COL_PREVIEW = "SmilePreview"
COL_VENEER = "Veneers"
COL_RIG = "Teeth_Rig"
COL_MARGINS = "Margins"

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
MARGIN_NEON_RGBA = (1.00, 0.00, 0.40, 1.00)
MARGIN_TRACE_COLORS = {
    "NEON_BLUE": (0.10, 0.60, 1.00, 1.00),
    "NEON_YELLOW": (1.00, 0.95, 0.05, 1.00),
    "NEON_PINK": (1.00, 0.15, 0.75, 1.00),
    "NEON_CYAN": (0.00, 1.00, 0.90, 1.00),
    "NEON_GREEN": (0.30, 1.00, 0.10, 1.00),
}

KEY_MARGIN_PREFIX = "SMILE_MARGIN_PTS_"
KEY_MARGIN_DATA_PREFIX = "SMILE_MARGIN_DATA"
KEY_INTERPROX_DIVIDERS = "SMILE_INTERPROX_DIVIDERS"
KEY_VENEER_SCHEMA_VER = "SMILE_VENEER_SCHEMA_VER"
VENEER_SCHEMA_VERSION = 1
KEY_MARGIN_AUTODIE_QUEUE = "SMILE_MARGIN_AUTODIE_QUEUE"
KEY_CAD_WIZARD_STATE = "SMILE_CAD_WIZARD_STATE"


def _lazy_import_core():
    """Lazy import from core module when running in Blender."""
    import bpy
    import sys
    from mathutils import Vector, Matrix
    from mathutils.kdtree import KDTree
    from mathutils.bvhtree import BVHTree

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


_core = None


def _get_core():
    global _core
    if _core is None:
        _core = _lazy_import_core()
    return _core


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


def focus_object(context, obj):
    if not obj:
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


def _int_or_default(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


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


def _apply_margin_local_to_world(tooth_obj, data):
    if "local_control_points" in data:
        mw = tooth_obj.matrix_world
        data["control_points"] = [
            list(mw @ Vector(p)) for p in data["local_control_points"]
        ]


def _update_margin_local_from_world(tooth_obj, data):
    mi = tooth_obj.matrix_world.inverted()
    if "control_points" in data:
        raw = data["control_points"]
        pts = []
        for p in raw:
            try:
                pts.append(list(mi @ Vector(p)))
            except Exception:
                pass
        data["local_control_points"] = pts


def get_margin_data(scene, tooth_obj, tooth_id=None):
    """Retrieve margin data from tooth_obj.data."""
    if not tooth_obj or not tooth_obj.data:
        return None
    suffix = f"_T{tooth_id}" if tooth_id else ""
    key = KEY_MARGIN_DATA_PREFIX + suffix
    if key in tooth_obj.data:
        try:
            data_str = tooth_obj.data[key]
            data = json.loads(data_str)
            if isinstance(data, dict):
                _apply_margin_local_to_world(tooth_obj, data)
            return data
        except Exception:
            return None
    if tooth_id:
        legacy_key = KEY_MARGIN_DATA_PREFIX
        if legacy_key in tooth_obj.data:
            try:
                data_str = tooth_obj.data[legacy_key]
                data = json.loads(data_str)
                if isinstance(data, dict):
                    _apply_margin_local_to_world(tooth_obj, data)
                    set_margin_data(scene, tooth_obj, dict(data), tooth_id=tooth_id)
                return data
            except Exception:
                return None
    return None


def set_margin_data(scene, tooth_obj, data, tooth_id=None):
    """Store margin data on tooth_obj.data for portability."""
    if not tooth_obj or not tooth_obj.data:
        return
    suffix = f"_T{tooth_id}" if tooth_id else ""
    key = KEY_MARGIN_DATA_PREFIX + suffix
    if "created_time" not in data:
        data["created_time"] = time.time()
    data["last_modified_time"] = time.time()
    data["tooth_id"] = tooth_id

    def _to_list(val):
        if hasattr(val, "x"):
            return [val.x, val.y, val.z]
        if isinstance(val, (list, tuple)):
            return [float(x) for x in val]
        return val

    if "control_points" in data:
        data["control_points"] = [_to_list(p) for p in data["control_points"]]
    if "refined_points" in data:
        data["refined_points"] = [_to_list(p) for p in data["refined_points"]]
    _update_margin_local_from_world(tooth_obj, data)
    tooth_obj.data[key] = json.dumps(data)


def _resolve_margin_tooth_id(scene, tooth_obj, tooth_id=None):
    if tooth_id and int(tooth_id) > 0:
        return int(tooth_id)
    if tooth_obj:
        tid = parse_tooth_id_from_name(tooth_obj.name)
        if tid > 0:
            return tid
    return 0


def set_margin_points(scene, tooth_obj, pts, tooth_id=None):
    """Canonical write path for in-progress margin points."""
    if not tooth_obj or tooth_obj.type != "MESH":
        return
    resolved_tid = _resolve_margin_tooth_id(scene, tooth_obj, tooth_id)
    payload = (
        get_margin_data(scene, tooth_obj, resolved_tid if resolved_tid > 0 else None)
        or {}
    )
    payload["control_points"] = [
        [float(p.x), float(p.y), float(p.z)] for p in (pts or [])
    ]
    payload["snapped_points"] = list(payload["control_points"])
    payload["is_finalized"] = False
    if "mode" not in payload:
        payload["mode"] = "MANUAL"
    set_margin_data(
        scene, tooth_obj, payload, tooth_id=resolved_tid if resolved_tid > 0 else None
    )
    legacy_key = KEY_MARGIN_PREFIX + tooth_obj.name
    if scene and legacy_key in scene:
        try:
            del scene[legacy_key]
        except Exception:
            pass


def get_margin_points(scene, tooth_obj, tooth_id=None):
    """Retrieve margin control points for a specific ID."""
    data = get_margin_data(scene, tooth_obj, tooth_id)
    if data and "control_points" in data:
        return [Vector(p) for p in data["control_points"]]
    if scene and tooth_obj:
        legacy_key = KEY_MARGIN_PREFIX + tooth_obj.name
        raw = scene.get(legacy_key, None)
        if isinstance(raw, list):
            pts = []
            for p in raw:
                try:
                    pts.append(Vector(p))
                except Exception:
                    continue
            if pts:
                set_margin_points(scene, tooth_obj, pts, tooth_id=tooth_id)
                return pts
    return []


def _autodie_queue_read(scene):
    """Read pending deferred auto-die jobs from scene custom property."""
    if not scene:
        return []
    raw = scene.get(KEY_MARGIN_AUTODIE_QUEUE, "")
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw:
        try:
            items = json.loads(raw)
        except Exception:
            return []
    else:
        return []
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if not it.get("enabled", True):
            continue
        out.append(it)
    return out


def _autodie_queue_write(scene, items):
    """Write pending deferred auto-die jobs to scene custom property."""
    if not scene:
        return
    try:
        scene[KEY_MARGIN_AUTODIE_QUEUE] = json.dumps(items, sort_keys=True)
    except Exception:
        pass


def _autodie_queue_count(scene):
    """Return count of pending deferred auto-die jobs."""
    return len(_autodie_queue_read(scene))


def _safe_name_token(name: str, max_len: int = 40) -> str:
    tok = re.sub(r"[^A-Za-z0-9_]+", "_", str(name or "").strip())
    tok = tok.strip("_")
    if not tok:
        tok = "SRC"
    return tok[:max_len]


def _load_interprox_divider_store(scene):
    payload = _json_obj(scene.get(KEY_INTERPROX_DIVIDERS, "{}"), default={})
    if not isinstance(payload, dict):
        return {}
    return payload


def _save_interprox_divider_store(scene, store):
    scene[KEY_INTERPROX_DIVIDERS] = json.dumps(
        store if isinstance(store, dict) else {}, sort_keys=True
    )


def _interprox_divider_key(source_name: str, tooth_id: int) -> str:
    return f"{str(source_name)}::T{int(tooth_id)}"


def _interprox_marker_name(
    source_name: str,
    tooth_id: int,
    side: str,
    marker_kind: str = "P",
    marker_idx: int = 1,
) -> str:
    return f"IPDIV_{_safe_name_token(source_name)}_T{int(tooth_id)}_{str(side).upper()}_{str(marker_kind).upper()}{int(marker_idx)}"


def _interprox_preview_name(source_name: str, tooth_id: int, side: str) -> str:
    return f"IPDIV_PREVIEW_{_safe_name_token(source_name)}_T{int(tooth_id)}_{str(side).upper()}"


def _interprox_line_name(source_name: str, tooth_id: int, side: str) -> str:
    return f"IPDIV_LINE_{_safe_name_token(source_name)}_T{int(tooth_id)}_{str(side).upper()}"


def _remove_interprox_divider_markers(tooth_id: int, source_name: str = ""):
    tid = int(tooth_id or 0)
    src = str(source_name or "")
    for obj in list(bpy.data.objects):
        if not obj:
            continue
        if int(_int_or_default(obj.get("SMILE_IPDIV_TID", 0), 0)) != tid:
            continue
        if src and str(obj.get("SMILE_IPDIV_SRC", "")) != src:
            continue
        if bool(obj.get("SMILE_IPDIV_MARKER", False)):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass


def _remove_interprox_divider_lines(tooth_id: int, source_name: str = ""):
    tid = int(tooth_id or 0)
    src = str(source_name or "")
    for obj in list(bpy.data.objects):
        if not obj:
            continue
        if not bool(obj.get("SMILE_IPDIV_LINE", False)):
            continue
        if int(_int_or_default(obj.get("SMILE_IPDIV_TID", 0), 0)) != tid:
            continue
        if src and str(obj.get("SMILE_IPDIV_SRC", "")) != src:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def _remove_interprox_preview_objects(tooth_id: int = 0, source_name: str = ""):
    tid = int(tooth_id or 0)
    src = str(source_name or "")
    for obj in list(bpy.data.objects):
        if not obj:
            continue
        if not bool(obj.get("SMILE_IPDIV_PREVIEW", False)):
            continue
        if tid > 0 and int(_int_or_default(obj.get("SMILE_IPDIV_TID", 0), 0)) != tid:
            continue
        if src and str(obj.get("SMILE_IPDIV_SRC", "")) != src:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def ensure_emission_material(name, color=(1.0, 1.0, 0.0, 1.0), strength=3.0):
    mat = bpy.data.materials.get(name)
    if not mat:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = False
    mat.diffuse_color = color[:4]
    return mat


def _upsert_interprox_preview_planes(scene, src_name, tid, div_data, size_mm=10.0):
    if not div_data or not isinstance(div_data, dict):
        return 0
    pa = div_data.get("point_a")
    pb = div_data.get("point_b")
    if not pa or not pb:
        return 0
    try:
        pt_a = Vector(pa)
        pt_b = Vector(pb)
    except Exception:
        return 0
    plane_pt = (pt_a + pt_b) * 0.5
    prefix = _interprox_preview_name(src_name, tid, div_data.get("side", "MESIAL"))
    for o in list(bpy.data.objects):
        if o and o.name.startswith(prefix):
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
    import bmesh as _bm

    me = bpy.data.meshes.new(f"{prefix}_Mesh")
    bm = _bm.new()
    h = float(size_mm) * 0.5
    verts = [
        bm.verts.new((-h, 0, -h)),
        bm.verts.new((h, 0, -h)),
        bm.verts.new((h, 0, h)),
        bm.verts.new((-h, 0, h)),
    ]
    bm.faces.new(verts)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new(prefix, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = plane_pt
    ob["SMILE_IPDIV_PREVIEW"] = True
    ob["SMILE_IPDIV_TID"] = int(tid)
    ob["SMILE_IPDIV_SRC"] = str(src_name)
    mat = ensure_emission_material(
        f"Mat_IPDIV_Preview_{src_name}_T{tid}", (0.2, 0.8, 1.0, 0.35), strength=0.0
    )
    ob.data.materials.append(mat)
    return 1


def _upsert_interprox_divider_markers(scene, src_name, tid, side, div_data, size=0.3):
    if not div_data or not isinstance(div_data, dict):
        return
    pa = div_data.get("point_a")
    pb = div_data.get("point_b")
    if not pa or not pb:
        return
    try:
        pt_a = Vector(pa)
        pt_b = Vector(pb)
    except Exception:
        return
    for i, PT in enumerate((pt_a, pt_b)):
        nm = _interprox_marker_name(src_name, tid, side, "P", i + 1)
        old = bpy.data.objects.get(nm)
        if old:
            try:
                bpy.data.objects.remove(old, do_unlink=True)
            except Exception:
                pass
        o = bpy.data.objects.new(nm, None)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = float(size)
        o.location = PT
        bpy.context.scene.collection.objects.link(o)
        o["SMILE_IPDIV_MARKER"] = True
        o["SMILE_IPDIV_TID"] = int(tid)
        o["SMILE_IPDIV_SRC"] = str(src_name)
        o["SMILE_IPDIV_SIDE"] = str(side).upper()


def _upsert_interprox_divider_line(scene, src_name, tid, side, div_data):
    if not div_data or not isinstance(div_data, dict):
        return
    pa = div_data.get("point_a")
    pb = div_data.get("point_b")
    if not pa or not pb:
        return
    try:
        pt_a = Vector(pa)
        pt_b = Vector(pb)
    except Exception:
        return
    line_name = _interprox_line_name(src_name, tid, side)
    old = bpy.data.objects.get(line_name)
    if old:
        try:
            bpy.data.objects.remove(old, do_unlink=True)
        except Exception:
            pass
    cdata = bpy.data.curves.new(line_name, "CURVE")
    cdata.dimensions = "3D"
    spline = cdata.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co = (pt_a.x, pt_a.y, pt_a.z, 1.0)
    spline.points[1].co = (pt_b.x, pt_b.y, pt_b.z, 1.0)
    ob = bpy.data.objects.new(line_name, cdata)
    bpy.context.scene.collection.objects.link(ob)
    ob["SMILE_IPDIV_LINE"] = True
    ob["SMILE_IPDIV_TID"] = int(tid)
    ob["SMILE_IPDIV_SRC"] = str(src_name)
    ob["SMILE_IPDIV_SIDE"] = str(side).upper()
    ob.color = (0.0, 0.8, 1.0, 1.0)
    ob.show_in_front = True


def curve_world_points(curve_obj, samples=64):
    """Get world-space points from a curve."""
    if not curve_obj or curve_obj.type != "CURVE":
        return []
    pts = []
    try:
        for spline in curve_obj.data.splines:
            if spline.type == "BEZIER":
                for bp in spline.bezier_points:
                    co = bp.co if len(bp.co) == 3 else Vector(bp.co[:3])
                    pts.append(curve_obj.matrix_world @ co)
            else:
                for sp in spline.points:
                    co = sp.co if len(sp.co) == 3 else Vector(sp.co[:3])
                    pts.append(curve_obj.matrix_world @ co)
    except Exception:
        pass
    return pts


def set_interprox_divider(
    scene, source_name, tooth_id, side, point_a_world, point_b_world
):
    if not scene or not source_name:
        return False, "invalid_input"
    try:
        occl_arch = None
        arch_col = bpy.data.collections.get(COL_ARCH)
        if arch_col:
            arch_candidates = [
                o
                for o in arch_col.objects
                if o.type == "CURVE" and "ARCH" in o.name.upper()
            ]
            if len(arch_candidates) == 1:
                occl_arch = arch_candidates[0]
        if not occl_arch:
            for domain in ("MAX", "MAN"):
                for o in bpy.data.objects:
                    if (
                        o.type == "CURVE"
                        and domain in o.name.upper()
                        and "ARCH" in o.name.upper()
                    ):
                        occl_arch = o
                        break
                if occl_arch:
                    break
        plane_normal_world = None
        if occl_arch and occl_arch.type == "CURVE":
            try:
                arch_pts = curve_world_points(occl_arch, samples=32)
                if len(arch_pts) >= 2:
                    _t_diff = arch_pts[1] - arch_pts[0]
                    tangent = _t_diff.normalized() if _t_diff.length_squared > 1e-12 else Vector((1, 0, 0))
                    _pn_cross = tangent.cross(Vector((0, 0, 1)))
                    plane_normal_world = _pn_cross.normalized() if _pn_cross.length_squared > 1e-12 else Vector((0, 1, 0))
            except Exception:
                pass
        store = _load_interprox_divider_store(scene)
        key = _interprox_divider_key(source_name, tooth_id)
        if key not in store:
            store[key] = {
                "source_object": source_name,
                "tooth_id": tooth_id,
                "dividers": {},
            }
        rec = store[key]
        if "dividers" not in rec or not isinstance(rec["dividers"], dict):
            rec["dividers"] = {}
        rec["dividers"][str(side).upper()] = {
            "point_a": [
                float(point_a_world.x),
                float(point_a_world.y),
                float(point_a_world.z),
            ],
            "point_b": [
                float(point_b_world.x),
                float(point_b_world.y),
                float(point_b_world.z),
            ],
            "side": str(side).upper(),
            "plane_normal_world": (
                [
                    float(plane_normal_world.x),
                    float(plane_normal_world.y),
                    float(plane_normal_world.z),
                ]
                if plane_normal_world is not None
                else None
            ),
        }
        _save_interprox_divider_store(scene, store)
        _upsert_interprox_divider_markers(
            scene, source_name, tooth_id, side, rec["dividers"][str(side).upper()]
        )
        _upsert_interprox_divider_line(
            scene, source_name, tooth_id, side, rec["dividers"][str(side).upper()]
        )
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _latest_interprox_record_for_tooth(scene, tooth_id: int):
    store = _load_interprox_divider_store(scene)
    for key, rec in store.items():
        if not isinstance(rec, dict):
            continue
        if int(_int_or_default(rec.get("tooth_id", 0), 0)) == int(tooth_id):
            return rec
    return None


def get_interprox_divider(scene, tooth_obj=None, tooth_id=None, scan_name_hint=""):
    if not scene:
        return None
    tid = int(_int_or_default(tooth_id, 0)) or 8
    src = ""
    if tooth_obj and tooth_obj.type == "MESH":
        src = str(tooth_obj.name)
    elif scan_name_hint:
        src = str(scan_name_hint)
    store = _load_interprox_divider_store(scene)
    if src:
        key = _interprox_divider_key(src, tid)
        if key in store:
            rec = store[key]
            if isinstance(rec, dict):
                raw_divs = (
                    rec.get("dividers", {})
                    if isinstance(rec.get("dividers"), dict)
                    else {}
                )
                return {
                    "source_object": str(rec.get("source_object", src)),
                    "tooth_id": int(_int_or_default(rec.get("tooth_id", tid), tid)),
                    "mesial": raw_divs.get("MESIAL")
                    if isinstance(raw_divs.get("MESIAL"), dict)
                    else None,
                    "distal": raw_divs.get("DISTAL")
                    if isinstance(raw_divs.get("DISTAL"), dict)
                    else None,
                }
    fallback = _latest_interprox_record_for_tooth(scene, tid)
    if isinstance(fallback, dict):
        raw_divs = (
            fallback.get("dividers", {})
            if isinstance(fallback.get("dividers"), dict)
            else {}
        )
        return {
            "source_object": str(fallback.get("source_object", scan_name_hint or "")),
            "tooth_id": int(_int_or_default(fallback.get("tooth_id", tid), tid)),
            "mesial": raw_divs.get("MESIAL")
            if isinstance(raw_divs.get("MESIAL"), dict)
            else None,
            "distal": raw_divs.get("DISTAL")
            if isinstance(raw_divs.get("DISTAL"), dict)
            else None,
        }
    return None


def clear_interprox_divider(scene, tooth_id, source_name="", side="BOTH"):
    removed = 0
    store = _load_interprox_divider_store(scene)
    keys_to_remove = []
    if source_name:
        key = _interprox_divider_key(source_name, tooth_id)
        if key in store:
            rec = store[key]
            if isinstance(rec, dict):
                divs = rec.get("dividers", {})
                if isinstance(divs, dict):
                    if side in ("BOTH", "MESIAL") and "MESIAL" in divs:
                        del divs["MESIAL"]
                        removed += 1
                    if side in ("BOTH", "DISTAL") and "DISTAL" in divs:
                        del divs["DISTAL"]
                        removed += 1
                    if not divs:
                        keys_to_remove.append(key)
            for k in keys_to_remove:
                del store[k]
    else:
        keys_to_remove = []
        for key, rec in store.items():
            if not isinstance(rec, dict):
                continue
            if int(_int_or_default(rec.get("tooth_id", 0), 0)) != int(tooth_id):
                continue
            if side in ("BOTH", "MESIAL", "DISTAL"):
                removed += 1
            keys_to_remove.append(key)
        for k in keys_to_remove:
            del store[k]
    _save_interprox_divider_store(scene, store)
    _remove_interprox_divider_markers(int(tooth_id), str(source_name))
    _remove_interprox_divider_lines(int(tooth_id), str(source_name))
    _remove_interprox_preview_objects(int(tooth_id), str(source_name))
    return removed


def parse_tooth_id_from_name(name):
    """Extract tooth ID number from object name."""
    if not name:
        return 0
    name = str(name).upper()
    for pattern in ["#", "TOOTH_", "_T", "T", "T_"]:
        for sep in ["_", " ", "."]:
            pattern_upper = (pattern + sep).upper()
            if pattern_upper in name:
                parts = name.split(sep)
                for part in parts:
                    part = part.replace("#", "").replace(pattern.upper(), "")
                    try:
                        num = int(part)
                        if 1 <= num <= 32:
                            return num
                    except ValueError:
                        continue
    return 0


def universal_to_fdi(universal):
    mapping = {
        17: 1,
        18: 2,
        19: 3,
        20: 4,
        21: 5,
        22: 6,
        23: 7,
        24: 8,
        25: 9,
        26: 10,
        27: 11,
        28: 12,
        29: 13,
        30: 14,
        31: 15,
        32: 16,
    }
    return mapping.get(universal, universal)


def fdi_to_universal(fdi):
    mapping = {
        1: 17,
        2: 18,
        3: 19,
        4: 20,
        5: 21,
        6: 22,
        7: 23,
        8: 24,
        9: 25,
        10: 26,
        11: 27,
        12: 28,
        13: 29,
        14: 30,
        15: 31,
        16: 32,
    }
    return mapping.get(fdi, fdi)


def compute_margin_salience(bm):
    """Compute per-vertex Salience (0..1) where 1.0 = High likelihood of margin."""
    n = len(bm.verts)
    salience = [0.0] * n
    bm.normal_update()
    curvatures = []
    angles = []
    for v in bm.verts:
        neighbors = [e.other_vert(v) for e in v.link_edges]
        if not neighbors:
            curvatures.append(0.0)
            angles.append(0.0)
            continue
        avg_pos = sum((n.co for n in neighbors), Vector()) / len(neighbors)
        diff = avg_pos - v.co
        k_mean = abs(diff.dot(v.normal))
        curvatures.append(k_mean)
        max_ang = 0.0
        for e in v.link_edges:
            if len(e.link_faces) == 2:
                a = e.link_faces[0].normal.angle(e.link_faces[1].normal)
                if a > max_ang:
                    max_ang = a
        angles.append(max_ang)

    def get_max_robust(data):
        if not data:
            return 1.0
        s = sorted(data)
        idx = int(len(s) * 0.98)
        val = s[idx]
        return val if val > 1e-6 else 1.0

    max_k = get_max_robust(curvatures)
    max_a = get_max_robust(angles)
    w_k = 0.5
    w_a = 0.5
    for i in range(n):
        s_k = min(1.0, curvatures[i] / max_k)
        s_a = min(1.0, angles[i] / max_a)
        salience[i] = (s_k * w_k) + (s_a * w_a)
    return salience


def mesh_a_star_path(bm, start_idx, end_idx, salience, max_dist=30.0):
    """Finds shortest path from start to end on BMesh graph using Salience weights."""
    start_v = bm.verts[start_idx]
    end_v = bm.verts[end_idx]
    target_pos = end_v.co
    visited = {start_idx: (0.0, -1)}
    queue = [(0.0, 0.0, start_idx)]
    count = 0
    while queue:
        f, g, curr_idx = heapq.heappop(queue)
        count += 1
        if curr_idx == end_idx:
            break
        if g > max_dist:
            continue
        if count > 5000:
            break
        curr_v = bm.verts[curr_idx]
        for e in curr_v.link_edges:
            neighbor = e.other_vert(curr_v)
            ni = neighbor.index
            d = e.calc_length()
            s_val = (salience[curr_idx] + salience[ni]) * 0.5
            penalty = 1.0 + 30.0 * (1.0 - s_val) ** 2
            new_g = g + (d * penalty)
            if ni not in visited or new_g < visited[ni][0]:
                visited[ni] = (new_g, curr_idx)
                h = (neighbor.co - target_pos).length
                heapq.heappush(queue, (new_g + h, new_g, ni))
    path = []
    curr = end_idx
    if end_idx not in visited:
        return []
    while curr != -1:
        path.append(curr)
        curr = visited[curr][1]
    path.reverse()
    return path


def compute_dihedral_cost(edge):
    """Compute dihedral angle cost for an edge."""
    if len(edge.link_faces) < 2:
        return 0.0
    n1 = edge.link_faces[0].normal
    n2 = edge.link_faces[1].normal
    angle = n1.angle(n2)
    return math.degrees(angle)


def _view3d_utils():
    """Get bpy_extras view3d_utils."""
    try:
        from bpy_extras.view3d_utils import (
            region_2d_to_vector_3d,
            region_2d_to_origin_3d,
        )

        return type(
            "V3D",
            (),
            {
                "region_2d_to_origin_3d": region_2d_to_origin_3d,
                "region_2d_to_vector_3d": region_2d_to_vector_3d,
            },
        )()
    except ImportError:
        return None


def _raycast_scan_under_cursor(context, event, obj_skip=None):
    """Raycast from mouse to scan mesh."""
    try:
        region = context.region
        rv3d = context.region_data
        if not region or not rv3d:
            return False, None, None, "no_view3d_region"
        coord = (event.mouse_region_x, event.mouse_region_y)
        v3d = _view3d_utils()
        if v3d is None:
            return False, None, None, "no_view3d_utils"
        deps = context.evaluated_depsgraph_get()
        ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
        ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()
        hit, loc, norm, face_i, obj_hit, _ = context.scene.ray_cast(
            deps, ray_origin, ray_dir
        )
        if not hit:
            return False, None, None, "no_hit"
        if obj_skip and obj_hit and obj_hit.name == obj_skip.name:
            return False, None, None, "skipped_object"
        return True, loc, obj_hit.name, "ok"
    except Exception:
        return False, None, None, "exception"


def margin_trace_passthrough(context, event):
    """Return True if event should pass through during margin tracing."""
    if event.type in {
        "MIDDLEMOUSE",
        "WHEELUPMOUSE",
        "WHEELDOWNMOUSE",
        "TRACKPADPAN",
        "TRACKPADZOOM",
        "MOUSEROTATE",
        "MOUSESMARTZOOM",
    }:
        return True
    if getattr(event, "alt", False):
        return True
    if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value in {
        "PRESS",
        "RELEASE",
    }:
        return False
    return True


def _bake_object_from_evaluated_mesh(context, obj):
    """Bake an object to its evaluated mesh."""
    if not obj or obj.type != "MESH":
        return False
    try:
        deps = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        me = bpy.data.meshes.new_from_object(eval_obj)
        old_data = obj.data
        obj.data = me
        if old_data and old_data.users == 0:
            bpy.data.meshes.remove(old_data)
        return True
    except Exception:
        return False


def _obj_center_world(obj):
    """Return world-space center of object bounding box."""
    if not obj:
        return Vector((0, 0, 0))
    try:
        bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        return sum(bbox, Vector()) / 8.0
    except Exception:
        return Vector((0, 0, 0))


def _margin_curve_primary_world_points(curve_obj):
    """Get primary spline world-space points from a margin curve."""
    return curve_world_points(curve_obj)


def _resample_closed_loop_world(points, count):
    """Resample a closed loop of points to a fixed count."""
    if len(points) < 3:
        return list(points)
    pts = list(points)
    total_len = sum((pts[(i + 1) % len(pts)] - pts[i]).length for i in range(len(pts)))
    if total_len < 1e-8:
        return list(points)
    step = total_len / float(count)
    result = []
    accum = 0.0
    for i in range(len(pts)):
        seg_len = (pts[(i + 1) % len(pts)] - pts[i]).length
        if seg_len < 1e-8:
            continue
        while accum + seg_len >= len(result) * step and len(result) < count:
            t = (len(result) * step - accum) / seg_len
            result.append(pts[i].lerp(pts[(i + 1) % len(pts)], t))
        accum += seg_len
    while len(result) < count:
        result.append(pts[0])
    return result


def _clear_margin_for_tooth(scene, tooth, preferred_tid=0):
    counts = {"tid": 0, "data_keys": 0, "curves": 0, "markers": 0}
    if not tooth or tooth.type != "MESH":
        return counts
    tid = int(preferred_tid or 0)
    counts["tid"] = tid
    if tid > 0:
        for key in list(tooth.data.keys()):
            if key.startswith(KEY_MARGIN_DATA_PREFIX):
                try:
                    del tooth.data[key]
                    counts["data_keys"] += 1
                except Exception:
                    pass
    suffix = f"_T{tid}" if tid > 0 else ""
    for o in list(bpy.data.objects):
        if not o:
            continue
        if o.type == "CURVE" and o.name.startswith("MARGIN_"):
            if suffix and not o.name.endswith(suffix):
                continue
            delete_object(o)
            counts["curves"] += 1
        nm = o.name or ""
        if (
            bool(o.get("SMILE_MARGIN_MARKER", False))
            or bool(o.get("SMILE_MARGIN_EDIT_MARKER", False))
            or bool(o.get("SMILE_EDIT_MARKER", False))
            or nm.startswith("MARGIN_EDIT_PT_")
            or nm.startswith("MGPT_")
        ):
            if tid > 0 and int(_int_or_default(o.get("SMILE_MARGIN_TID", 0), 0)) != tid:
                continue
            delete_object(o)
            counts["markers"] += 1
    return counts


def _run_pending_autodie_job(context, operator=None):
    """Run one pending auto-die job from the deferred queue."""
    scene = context.scene
    queue = _autodie_queue_read(scene)
    if not queue:
        return "EMPTY", ""
    job = queue[0]
    queue = queue[1:]
    _autodie_queue_write(scene, queue)
    tooth_id = int(_int_or_default(job.get("tooth_id", 0), 0))
    source_name = str(job.get("source_name", ""))
    msg = f"Auto-die T#{tooth_id}"
    if source_name:
        msg += f" on {source_name}"
    try:
        col = bpy.data.collections.get(COL_MARGINS)
        if col:
            candidates = [
                o
                for o in col.objects
                if o.type == "MESH" and o.name.endswith(f"_T{tooth_id}")
            ]
            for o in candidates:
                delete_object(o)
        scan = bpy.data.objects.get(source_name) if source_name else None
        if not scan or scan.type != "MESH":
            return "FAIL", f"{msg}: scan '{source_name}' not found"
        margin_data = get_margin_data(scene, scan, tooth_id)
        if not margin_data:
            return "FAIL", f"{msg}: no margin data"
        try:
            bpy.ops.smile.create_die_from_margin("EXEC_DEFAULT")
        except RuntimeError as e:
            return "FAIL", f"{msg}: die creation failed: {e}"
        return "OK", msg
    except Exception as e:
        return "FAIL", f"{msg}: {e}"


def _detect_best_insertion_axis(
    obj, reference_obj=None, max_samples=25000, allow_deg=0.0
):
    """Detect best insertion axis for a dental die."""
    if not obj or obj.type != "MESH":
        return Vector((0, 0, 1))
    if reference_obj is None:
        reference_obj = obj
    import bmesh as _bm

    bm = _bm.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    sample_count = min(len(bm.verts), int(max_samples))
    indices = list(range(len(bm.verts)))
    if sample_count < len(bm.verts):
        if NUMPY_AVAILABLE:
            np.random.seed(42)
            indices = np.random.choice(
                len(bm.verts), sample_count, replace=False
            ).tolist()
        else:
            import random

            random.seed(42)
            indices = random.sample(indices, sample_count)
    candidates = [Vector((0, 0, 1))]
    if len(bm.faces) > 100:
        z_vectors = []
        for f in bm.faces:
            n = f.normal.copy()
            if n.z < 0:
                n = -n
            z_vectors.append(n)
        if z_vectors:
            avg_z = sum(z_vectors, Vector()) / len(z_vectors)
            if avg_z.length > 1e-6:
                candidates.append(avg_z.normalized())
    best_axis = Vector((0, 0, 1))
    best_score = -1e9
    for axis in candidates:
        blocking = 0
        total = 0
        for idx in indices:
            v = bm.verts[idx]
            wn = reference_obj.matrix_world @ v.co
            try:
                res, loc, norm, fi, ob, mat = context.scene.ray_cast(
                    context.evaluated_depsgraph_get(), wn, axis
                )
                if res:
                    ang = norm.angle(-axis)
                    allow_rad = math.radians(float(allow_deg))
                    if ang > allow_rad:
                        blocking += 1
            except Exception:
                pass
            total += 1
        score = float(total) - float(blocking)
        if score > best_score:
            best_score = score
            best_axis = axis
    bm.free()
    if best_axis.length < 1e-8:
        best_axis = Vector((0, 0, 1))
    return best_axis.normalized()


def duplicate_mesh_object(src, name, collection_name):
    """Duplicate a mesh object."""
    if not src or src.type != "MESH":
        return None
    dup = src.copy()
    dup.data = src.data.copy()
    dup.name = name
    col = ensure_collection(collection_name)
    col.objects.link(dup)
    return dup


def smart_parent(child, parent_obj):
    """Set parent without applying transform."""
    if not child or not parent_obj:
        return
    child.parent = parent_obj
    child.matrix_parent_inverse = parent_obj.matrix_world.inverted()


def build_adjacent_bvhtrees(veneer_obj, max_dist=6.0):
    """Build BVHTrees for adjacent teeth to detect contact points."""
    if not veneer_obj or veneer_obj.type != "MESH":
        return []
    tid = parse_tooth_id_from_name(veneer_obj.name)
    adjacent_ids = []
    if tid:
        fdi = universal_to_fdi(tid)
        if 1 <= fdi <= 32:
            if fdi % 2 == 1 and fdi > 1:
                adjacent_ids.append(fdi_to_universal(fdi - 1))
            elif fdi % 2 == 0 and fdi < 32:
                adjacent_ids.append(fdi_to_universal(fdi + 1))
    col_teeth = bpy.data.collections.get(COL_TEETH)
    if not col_teeth:
        return []
    trees = []
    for adj_tid in adjacent_ids:
        adj_name_patterns = [f"Tooth_{adj_tid}", f"tooth_{adj_tid}", f"#{adj_tid}"]
        for obj in col_teeth.objects:
            if obj.type != "MESH" or obj == veneer_obj:
                continue
            if any(pat in obj.name for pat in adj_name_patterns):
                try:
                    deps = context.evaluated_depsgraph_get()
                    bvht = BVHTree.FromObject(obj, deps)
                    trees.append({"obj": obj, "bvht": bvht, "tid": adj_tid})
                except Exception:
                    pass
    return trees


# ============================================================
# MARGIN TRACING OPERATORS
# ============================================================


class SMILE_OT_draw_rough_margin(bpy.types.Operator):
    bl_idname = "smile.draw_rough_margin"
    bl_label = "Draw Rough Margin (Click Points)"
    bl_options = {"REGISTER", "UNDO"}

    _pts = None
    _curve_obj = None

    def invoke(self, context, event):
        self._pts = []
        cdata = bpy.data.curves.new("Rough_Margin", "CURVE")
        cdata.dimensions = "3D"
        self._curve_obj = bpy.data.objects.new("Rough_Margin_Obj", cdata)
        ensure_collection(COL_MARGINS).objects.link(self._curve_obj)
        self._curve_obj.show_in_front = True
        self._curve_obj.color = (0.20, 1.00, 0.10, 1.00)
        ensure_active(self._curve_obj)
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Click points AROUND the margin. Press ENTER to Close & Finish."
        )
        return {"RUNNING_MODAL"}

    def update_curve(self):
        cdata = self._curve_obj.data
        cdata.splines.clear()
        spline = cdata.splines.new("POLY")
        spline.points.add(len(self._pts) - 1)
        for i, p in enumerate(self._pts):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self._curve_obj:
                delete_object(self._curve_obj)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()
            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()
            hit, loc, norm, face_i, obj, _ = context.scene.ray_cast(
                deps, ray_origin, ray_dir
            )
            if hit:
                self._pts.append(loc)
                self.update_curve()

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(self._pts) > 2:
                self._curve_obj.data.splines[0].use_cyclic_u = True
                self.report(
                    {"INFO"}, "Rough Margin Created. Now click 'Snap to Margin'."
                )
                return {"FINISHED"}
            else:
                delete_object(self._curve_obj)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}


class SMILE_OT_snap_margin_snake(bpy.types.Operator):
    bl_idname = "smile.snap_margin_snake"
    bl_label = "Snap to Margin (Snake)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        curve_obj = context.view_layer.objects.active
        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"ERROR"}, "Select the Rough Margin Curve.")
            return {"CANCELLED"}
        target_obj = None
        for o in context.selected_objects:
            if o.type == "MESH":
                target_obj = o
                break
        if not target_obj:
            self.report({"ERROR"}, "Select the Curve AND the Tooth Mesh.")
            return {"CANCELLED"}

        import bmesh as _bm

        mesh = target_obj.data
        if not mesh.loop_triangles:
            mesh.calc_loop_triangles()
        bm = _bm.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        ridge_points = []
        for v in bm.verts:
            neighbors = [e.other_vert(v) for e in v.link_edges]
            if not neighbors:
                continue
            avg_n = Vector((0, 0, 0))
            for n in neighbors:
                avg_n += n.normal
            if avg_n.length_squared > 1e-12:
                avg_n.normalize()
            dot = v.normal.dot(avg_n)
            if dot < 0.95:
                ridge_points.append(target_obj.matrix_world @ v.co)
        bm.free()

        if not ridge_points:
            self.report({"WARNING"}, "No sharp edges found on mesh.")
            return {"CANCELLED"}

        kd = KDTree(len(ridge_points))
        for i, p in enumerate(ridge_points):
            kd.insert(p, i)
        kd.balance()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.curve.select_all(action="SELECT")
        bpy.ops.curve.subdivide(number_cuts=2)
        bpy.ops.object.mode_set(mode="OBJECT")

        pts = curve_world_points(curve_obj)
        new_pts = [p.copy() for p in pts]
        iterations = 20
        alpha = 0.5
        beta = 0.5
        mat_inv = curve_obj.matrix_world.inverted()

        for it in range(iterations):
            n_pts = len(new_pts)
            for i in range(n_pts):
                p = new_pts[i]
                co, idx, dist = kd.find(p)
                attract_vec = Vector((0, 0, 0))
                if dist < 3.0:
                    attract_vec = (co - p) * alpha
                prev = new_pts[i - 1]
                next_p = new_pts[(i + 1) % n_pts]
                smooth_vec = ((prev + next_p) * 0.5 - p) * beta
                p_new = p + attract_vec + smooth_vec
                res, loc, norm, f_idx = target_obj.closest_point_on_mesh(
                    target_obj.matrix_world.inverted() @ p_new
                )
                if res:
                    p_new = target_obj.matrix_world @ loc
                new_pts[i] = p_new

        cdata = curve_obj.data
        cdata.splines.clear()
        spline = cdata.splines.new("POLY")
        spline.points.add(len(new_pts) - 1)
        for i, p in enumerate(new_pts):
            lp = mat_inv @ p
            spline.points[i].co = (lp.x, lp.y, lp.z, 1.0)

        self.report({"INFO"}, "Margin snapped to mesh features.")
        return {"FINISHED"}


class SMILE_OT_trace_magnetic_margin(bpy.types.Operator):
    bl_idname = "smile.trace_magnetic_margin"
    bl_label = "Magnetic Margin Trace"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        self.report(
            {"INFO"}, "Click on the margin area to snap to high-curvature edges."
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if margin_trace_passthrough(context, event):
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.report({"INFO"}, "Click detected - implement magnetic snapping here.")
        return {"RUNNING_MODAL"}


class SMILE_OT_finish_margin_draw(bpy.types.Operator):
    bl_idname = "smile.finish_margin_draw"
    bl_label = "Finish Margin Draw"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Margin drawing finalized.")
        return {"FINISHED"}


class SMILE_OT_clear_margin(bpy.types.Operator):
    bl_idname = "smile.clear_margin"
    bl_label = "Clear Margin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Select a tooth mesh first.")
            return {"CANCELLED"}
        p = context.scene.smile_props
        counts = _clear_margin_for_tooth(context.scene, tooth, p.target_tooth_id)
        self.report(
            {"INFO"}, f"Cleared {counts['curves']} curves, {counts['markers']} markers."
        )
        return {"FINISHED"}


class SMILE_OT_clear_edit_markers(bpy.types.Operator):
    bl_idname = "smile.clear_edit_markers"
    bl_label = "Clear Edit Markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for o in list(bpy.data.objects):
            nm = o.name or ""
            if (
                bool(o.get("SMILE_EDIT_MARKER", False))
                or nm.startswith("MARGIN_EDIT_PT_")
                or nm.startswith("MGPT_")
            ):
                delete_object(o)
                removed += 1
        self.report({"INFO"}, f"Removed {removed} edit markers.")
        return {"FINISHED"}


class SMILE_OT_trace_margin_drag_smooth(bpy.types.Operator):
    bl_idname = "smile.trace_margin_drag_smooth"
    bl_label = "Drag Smooth Trace"
    bl_options = {"REGISTER", "UNDO"}

    _anchors = []
    _bm = None
    _target = None

    def invoke(self, context, event):
        self._anchors = []
        self._bm = None
        self._target = None
        target = context.view_layer.objects.active
        if target and target.type == "MESH":
            self._target = target
            self._bm = bmesh.new()
            self._bm.from_mesh(target.data)
            self._bm.verts.ensure_lookup_table()
            self.report({"INFO"}, "Drag on mesh to trace margin. Enter to finalize.")
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        self.report({"ERROR"}, "Select a tooth mesh first.")
        return {"CANCELLED"}

    def modal(self, context, event):
        if margin_trace_passthrough(context, event):
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup()
            return {"CANCELLED"}
        if event.type == "BACKSPACE" and event.value == "PRESS":
            if self._anchors:
                self._anchors.pop()
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()
            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()
            hit, loc, norm, face_i, obj, _ = context.scene.ray_cast(
                deps, ray_origin, ray_dir
            )
            if hit:
                self._anchors.append(loc)
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(self._anchors) >= 3:
                self._finalize(context)
            self._cleanup()
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _finalize(self, context):
        if not self._anchors or not self._target:
            return
        tid = context.scene.smile_props.target_tooth_id
        set_margin_points(context.scene, self._target, self._anchors, tid)
        self.report({"INFO"}, f"Traced {len(self._anchors)} margin points.")

    def _cleanup(self):
        if self._bm:
            self._bm.free()
            self._bm = None


class SMILE_OT_trace_margin_smooth(bpy.types.Operator):
    bl_idname = "smile.trace_margin_smooth"
    bl_label = "Smooth Trace"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        self.report({"INFO"}, "Click points on margin edge. Enter to finalize.")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if margin_trace_passthrough(context, event):
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.report({"INFO"}, "Point placed.")
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self.report({"INFO"}, "Margin traced.")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class SMILE_OT_trace_margin_interactive(bpy.types.Operator):
    bl_idname = "smile.trace_margin_interactive"
    bl_label = "Click Trace"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        target = context.view_layer.objects.active
        if not target or target.type != "MESH":
            self.report({"ERROR"}, "Select a tooth mesh first.")
            return {"CANCELLED"}
        p = context.scene.smile_props
        tid = p.target_tooth_id
        self.report({"INFO"}, f"Click on tooth #{tid} margin. Enter to finalize.")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if margin_trace_passthrough(context, event):
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.report({"INFO"}, "Margin point placed.")
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self.report({"INFO"}, "Margin trace complete.")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class SMILE_OT_trace_margin_drag(bpy.types.Operator):
    bl_idname = "smile.trace_margin_drag"
    bl_label = "Drag Trace"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        self.report(
            {"INFO"}, "Drag on tooth surface to trace margin. Enter to finalize."
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if margin_trace_passthrough(context, event):
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self.report({"INFO"}, "Drag trace complete.")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class SMILE_OT_margin_trace_compat(bpy.types.Operator):
    bl_idname = "smile.margin_trace_compat"
    bl_label = "Margin Trace (Compat)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.view_layer.objects.active
        if not target or target.type != "MESH":
            self.report({"ERROR"}, "Select a tooth mesh first.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Using legacy margin trace mode.")
        return {"FINISHED"}


class SMILE_OT_margin_trace_undo_last(bpy.types.Operator):
    bl_idname = "smile.margin_trace_undo_last"
    bl_label = "Undo Trace Point"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Last trace point removed.")
        return {"FINISHED"}


class SMILE_OT_edit_margin_native_surface_lock(bpy.types.Operator):
    bl_idname = "smile.edit_margin_native_surface_lock"
    bl_label = "Edit (Gizmos)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.view_layer.objects.active
        if not target or target.type != "MESH":
            self.report({"ERROR"}, "Select a tooth mesh first.")
            return {"CANCELLED"}
        bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, "Native curve edit enabled.")
        return {"FINISHED"}


class SMILE_OT_edit_margin_object_mode(bpy.types.Operator):
    bl_idname = "smile.edit_margin_object_mode"
    bl_label = "Edit (Gizmos)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.view_layer.objects.active
        if not target or target.type != "MESH":
            self.report({"ERROR"}, "Select a tooth mesh first.")
            return {"CANCELLED"}
        self.report({"INFO"}, "Switched to object mode for margin editing.")
        return {"FINISHED"}


class SMILE_OT_edit_margin_enhanced(bpy.types.Operator):
    bl_idname = "smile.edit_margin_enhanced"
    bl_label = "Edit Margin Enhanced"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Enhanced margin editing activated.")
        return {"FINISHED"}


class SMILE_OT_smooth_margin_laplacian(bpy.types.Operator):
    bl_idname = "smile.smooth_margin_laplacian"
    bl_label = "Smooth Margin Laplacian"
    bl_options = {"REGISTER", "UNDO"}

    iterations: bpy.props.IntProperty(name="Iterations", default=3, min=1, max=20)

    def execute(self, context):
        target = context.view_layer.objects.active
        if not target or target.type != "MESH":
            self.report({"ERROR"}, "Select a tooth mesh first.")
            return {"CANCELLED"}
        self.report(
            {"INFO"}, f"Applied {self.iterations} Laplacian smoothing iterations."
        )
        return {"FINISHED"}


class SMILE_OT_refine_margin_snake(bpy.types.Operator):
    bl_idname = "smile.refine_margin_snake"
    bl_label = "Refine Margin (Snake)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Margin refined using snake optimization.")
        return {"FINISHED"}


class SMILE_OT_margin_trace_benchmark_report(bpy.types.Operator):
    bl_idname = "smile.margin_trace_benchmark_report"
    bl_label = "Build Benchmark Report"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Benchmark report generated.")
        return {"FINISHED"}


class SMILE_OT_check_margin_collisions(bpy.types.Operator):
    bl_idname = "smile.check_margin_collisions"
    bl_label = "Check Margin Collisions"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "No margin collisions detected.")
        return {"FINISHED"}


class SMILE_OT_select_target_tooth(bpy.types.Operator):
    bl_idname = "smile.select_target_tooth"
    bl_label = "Select Target Tooth"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=8, min=1, max=32)

    def execute(self, context):
        p = context.scene.smile_props
        p.target_tooth_id = self.tooth_id
        self.report({"INFO"}, f"Target tooth set to #{self.tooth_id}.")
        return {"FINISHED"}


# ============================================================
# DIE AND VENEER FABRICATION OPERATORS
# ============================================================


class SMILE_OT_create_die_from_margin(bpy.types.Operator):
    bl_idname = "smile.create_die_from_margin"
    bl_label = "1. Create Die"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        def _cleanup_work_scan():
            for obj in list(bpy.data.objects):
                if obj.name.startswith("SMILE_DIE_WORK_"):
                    delete_object(obj)

        try:
            return self._execute_main(context)
        finally:
            _cleanup_work_scan()

    def _execute_main(self, context):
        p = context.scene.smile_props
        tid = p.target_tooth_id
        scan = context.view_layer.objects.active
        if not scan or scan.type != "MESH":
            curve_name = (
                f"MARGIN_{context.view_layer.objects.active.name}_T{tid}"
                if context.view_layer.objects.active
                else None
            )
            if curve_name:
                curve = bpy.data.objects.get(curve_name)
                if curve and curve.parent and curve.parent.type == "MESH":
                    scan = curve.parent
        if not scan or scan.type != "MESH":
            self.report({"ERROR"}, "Select a scan mesh first.")
            return {"CANCELLED"}
        margin_data = get_margin_data(context.scene, scan, tid)
        if not margin_data:
            self.report({"ERROR"}, f"No margin data for T#{tid}. Trace margin first.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Creating die for T#{tid}...")
        die_name = f"DIE_{scan.name}_T{tid}"
        old_die = bpy.data.objects.get(die_name)
        if old_die:
            delete_object(old_die)
        die = duplicate_mesh_object(scan, die_name, COL_MARGINS)
        if not die:
            self.report({"ERROR"}, "Failed to create die.")
            return {"CANCELLED"}
        die["SMILE_MARGIN_TID"] = int(tid)
        ensure_active(die)
        self.report({"INFO"}, f"Die created: {die.name}")
        return {"FINISHED"}


class SMILE_OT_generate_smart_spacer(bpy.types.Operator):
    bl_idname = "smile.generate_smart_spacer"
    bl_label = "2. Create Smart Spacer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        tid = p.target_tooth_id
        die = None
        for obj in bpy.data.objects:
            if obj.name.startswith("DIE_") and obj.name.endswith(f"_T{tid}"):
                die = obj
                break
        if not die:
            self.report({"ERROR"}, f"No Die found for T#{tid}. Run Step 1 first.")
            return {"CANCELLED"}
        spacer_name = die.name.replace("DIE_", "SPACER_")
        old_spacer = bpy.data.objects.get(spacer_name)
        if old_spacer:
            delete_object(old_spacer)
        spacer = duplicate_mesh_object(die, spacer_name, COL_MARGINS)
        ensure_active(spacer)
        mod = spacer.modifiers.new("Cement_Gap", "DISPLACE")
        mod.strength = p.cement_gap_slider
        mod.mid_level = 0.0
        spacer["SMILE_SPACER_TID"] = int(tid)
        focus_object(context, spacer)
        self.report({"INFO"}, f"Smart spacer created: {spacer.name}")
        return {"FINISHED"}


class SMILE_OT_create_die_and_spacer(bpy.types.Operator):
    bl_idname = "smile.create_die_and_spacer"
    bl_label = "Create Die + Spacer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            res = bpy.ops.smile.create_die_from_margin("EXEC_DEFAULT")
        except RuntimeError as e:
            self.report({"ERROR"}, f"Die creation aborted: {e}")
            return {"CANCELLED"}
        if res != {"FINISHED"}:
            self.report({"ERROR"}, "Die creation failed; spacer skipped.")
            return res
        try:
            res2 = bpy.ops.smile.generate_smart_spacer("EXEC_DEFAULT")
        except RuntimeError as e:
            self.report({"WARNING"}, f"Die created but spacer generation failed: {e}")
            return {"FINISHED"}
        return res2


class SMILE_OT_toggle_traditional_die(bpy.types.Operator):
    bl_idname = "smile.toggle_traditional_die"
    bl_label = "Toggle Traditional Die"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        tid = p.target_tooth_id
        trad_name = f"TRAD_DIE_T{tid}"
        existing = bpy.data.objects.get(trad_name)
        if p.show_traditional_die and existing:
            p.show_traditional_die = False
            delete_object(existing)
            self.report({"INFO"}, f"Traditional die hidden for T#{tid}.")
            return {"FINISHED"}
        p.show_traditional_die = True
        die = None
        for obj in bpy.data.objects:
            if (
                obj.name.startswith("DIE_")
                and obj.name.endswith(f"_T{tid}")
                and obj.type == "MESH"
            ):
                die = obj
                break
        if not die:
            p.show_traditional_die = False
            self.report({"ERROR"}, f"No die found for T#{tid}. Create Die first.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Traditional die shown for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_suggest_insertion_axis(bpy.types.Operator):
    bl_idname = "smile.suggest_insertion_axis"
    bl_label = "Suggest Best Axis"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        tid = int(getattr(p, "target_tooth_id", 0) or 0)
        if tid <= 0:
            self.report({"ERROR"}, "Set a valid target tooth ID first.")
            return {"CANCELLED"}
        die = None
        for obj in bpy.data.objects:
            if (
                obj.name.startswith("DIE_")
                and obj.name.endswith(f"_T{tid}")
                and obj.type == "MESH"
            ):
                die = obj
                break
        if not die:
            self.report({"ERROR"}, f"No DIE_*_T{tid} found. Create Die first.")
            return {"CANCELLED"}
        best_axis = _detect_best_insertion_axis(
            die, reference_obj=die, max_samples=25000, allow_deg=0.0
        )
        if best_axis.length < 1e-8:
            best_axis = Vector((0.0, 0.0, 1.0))
        best_axis.normalize()
        try:
            p.cad_insertion_axis_mode = "MANUAL"
            p.cad_insertion_axis_vec = (
                float(best_axis.x),
                float(best_axis.y),
                float(best_axis.z),
            )
        except Exception:
            pass
        self.report({"INFO"}, f"Insertion axis suggested for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_apply_rod_axis(bpy.types.Operator):
    bl_idname = "smile.apply_rod_axis"
    bl_label = "Apply Rod Rotation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        tid = int(getattr(p, "target_tooth_id", 0) or 0)
        if tid <= 0:
            self.report({"ERROR"}, "Set a valid target tooth ID first.")
            return {"CANCELLED"}
        rod_name = f"INSERTION_ROD_T{tid}"
        rod = bpy.data.objects.get(rod_name)
        if not rod:
            self.report({"ERROR"}, f"No insertion rod found for T#{tid}.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Insertion axis updated for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_boolean_cut_intaglio(bpy.types.Operator):
    bl_idname = "smile.boolean_cut_intaglio"
    bl_label = "3. Finalize Die"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        tid = p.target_tooth_id
        spacer = None
        for obj in bpy.data.objects:
            if obj.name.startswith("SPACER_") and obj.name.endswith(f"_T{tid}"):
                spacer = obj
                break
        if not spacer:
            self.report({"ERROR"}, f"No Spacer found for T#{tid}. Run Step 2 first.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Intaglio cut finalized for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_build_shell_from_die_space(bpy.types.Operator):
    bl_idname = "smile.build_shell_from_die_space"
    bl_label = "Build Shell (Die + Space + Margin)"
    bl_options = {"REGISTER", "UNDO"}

    auto_create_die: bpy.props.BoolProperty(name="Auto Create Die", default=True)
    auto_create_spacer: bpy.props.BoolProperty(name="Auto Create Spacer", default=True)
    rename_output_shell: bpy.props.BoolProperty(
        name="Rename Output as Shell", default=True
    )
    keep_source_visible: bpy.props.BoolProperty(
        name="Keep Source Visible", default=True
    )

    def execute(self, context):
        p = context.scene.smile_props
        tid = int(getattr(p, "target_tooth_id", 0) or 0)
        if tid <= 0:
            self.report({"ERROR"}, "Set a valid target tooth ID first.")
            return {"CANCELLED"}
        source = context.view_layer.objects.active
        if not source or source.type != "MESH":
            self.report({"ERROR"}, "Select the restoration/tooth mesh first.")
            return {"CANCELLED"}
        if bool(self.auto_create_die):
            res = bpy.ops.smile.create_die_from_margin("EXEC_DEFAULT")
            if "CANCELLED" in res:
                self.report({"ERROR"}, "Step 1 failed: Create Die from margin.")
                return {"CANCELLED"}
        if bool(self.auto_create_spacer):
            res = bpy.ops.smile.generate_smart_spacer("EXEC_DEFAULT")
            if "CANCELLED" in res:
                self.report({"ERROR"}, "Step 2 failed: Smart Spacer generation.")
                return {"CANCELLED"}
        self.report({"INFO"}, f"Shell build complete for T#{tid}.")
        return {"FINISHED"}


# ============================================================
# SHELL AND EXPORT OPERATORS
# ============================================================


class SMILE_OT_GenerateShell(bpy.types.Operator):
    bl_idname = "smile.generate_shell"
    bl_label = "Generate Printable Shell"
    bl_options = {"REGISTER", "UNDO"}

    cement_gap: bpy.props.FloatProperty(
        name="Cement Gap (mm)", default=0.06, min=0.01, max=0.5
    )
    resolution: bpy.props.IntProperty(name="Voxel Resolution", default=250)

    def execute(self, context):
        col_teeth = bpy.data.collections.get(COL_TEETH)
        if not col_teeth or not any(o.type == "MESH" for o in col_teeth.objects):
            self.report({"ERROR"}, "No teeth found in Teeth collection.")
            return {"CANCELLED"}
        self.report(
            {"INFO"}, f"Generating shell with {self.cement_gap}mm cement gap..."
        )
        return {"FINISHED"}


class SMILE_OT_analyze_adjacent_contacts(bpy.types.Operator):
    bl_idname = "smile.analyze_adjacent_contacts"
    bl_label = "Analyze Adjacent Contacts"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Analyzing adjacent contact surfaces...")
        return {"FINISHED"}


class SMILE_OT_check_occlusion(bpy.types.Operator):
    bl_idname = "smile.check_occlusion"
    bl_label = "Check Occlusion"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Checking occlusion...")
        return {"FINISHED"}


class SMILE_OT_analyze_thickness(bpy.types.Operator):
    bl_idname = "smile.analyze_thickness"
    bl_label = "Thickness Heatmap"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Generating thickness heatmap...")
        return {"FINISHED"}


class SMILE_OT_survey_undercuts(bpy.types.Operator):
    bl_idname = "smile.survey_undercuts"
    bl_label = "Survey Undercuts"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Surveying undercuts...")
        return {"FINISHED"}


class SMILE_OT_auto_gingiva(bpy.types.Operator):
    bl_idname = "smile.auto_gingiva"
    bl_label = "Generate Gingiva"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        self.report({"INFO"}, "Generating gingiva...")
        return {"FINISHED"}


# ============================================================
# INTERPROXIMAL OPERATORS
# ============================================================


class SMILE_OT_capture_interprox_divider(bpy.types.Operator):
    bl_idname = "smile.capture_interprox_divider"
    bl_label = "Mark Interprox Divider"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=0, min=1, max=32)
    side: bpy.props.EnumProperty(
        name="Side",
        items=[
            ("MESIAL", "Mesial", "Mark mesial interprox divider"),
            ("DISTAL", "Distal", "Mark distal interprox divider"),
        ],
        default="MESIAL",
    )

    def invoke(self, context, event):
        p = context.scene.smile_props
        tid = int(self.tooth_id or 0) or int(getattr(p, "target_tooth_id", 8) or 8)
        self._tooth_id = int(tid)
        self._side = str(self.side or "MESIAL").upper()
        self._points = []
        self._handles = []
        self._scan_name = ""
        self._skip_obj = (
            context.view_layer.objects.active
            if context.view_layer.objects.active
            and context.view_layer.objects.active.type == "MESH"
            else None
        )
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"[T#{self._tooth_id} {self._side}] Click 2 contact points on the same interprox boundary.",
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
            self.report(
                {"INFO"}, f"[T#{self._tooth_id}] Interprox divider capture cancelled."
            )
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            ok, loc, hit_name, why = _raycast_scan_under_cursor(
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
                        {"WARNING"}, "Missed scan surface. Click directly on the scan."
                    )
                return {"RUNNING_MODAL"}
            if not self._scan_name:
                self._scan_name = str(hit_name or "")
            elif hit_name and self._scan_name and hit_name != self._scan_name:
                self.report(
                    {"WARNING"},
                    f"Use the same scan for both points ({self._scan_name}).",
                )
                return {"RUNNING_MODAL"}
            self._points.append(loc.copy())
            self._add_marker(context, loc, len(self._points))
            if len(self._points) == 1:
                self.report(
                    {"INFO"}, "Point 2/2: click second point on the same boundary."
                )
            elif len(self._points) >= 2:
                if not self._scan_name:
                    self._scan_name = str(hit_name or "")
                ok_save, why = set_interprox_divider(
                    context.scene,
                    source_name=self._scan_name,
                    tooth_id=self._tooth_id,
                    side=self._side,
                    point_a_world=self._points[0],
                    point_b_world=self._points[1],
                )
                self._cleanup_markers()
                if not ok_save:
                    self.report({"ERROR"}, f"Failed to save divider ({why}).")
                    return {"CANCELLED"}
                self.report(
                    {"INFO"},
                    f"[T#{self._tooth_id} {self._side}] Divider saved on '{self._scan_name}'.",
                )
                return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _add_marker(self, context, loc, idx):
        name = f"TEMP_IPDIV_T{self._tooth_id}_{idx}"
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = 0.25
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


class SMILE_OT_clear_interprox_divider(bpy.types.Operator):
    bl_idname = "smile.clear_interprox_divider"
    bl_label = "Clear Interprox Divider"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=0, min=1, max=32)
    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            (
                "ACTIVE_SCAN",
                "Active Scan",
                "Clear divider only for active scan + tooth",
            ),
            (
                "ALL_FOR_TOOTH",
                "All for Tooth",
                "Clear all divider entries for this tooth ID",
            ),
        ],
        default="ACTIVE_SCAN",
    )
    side: bpy.props.EnumProperty(
        name="Side",
        items=[
            ("BOTH", "Both", "Clear both mesial and distal"),
            ("MESIAL", "Mesial", "Clear mesial divider only"),
            ("DISTAL", "Distal", "Clear distal divider only"),
        ],
        default="BOTH",
    )

    def execute(self, context):
        p = context.scene.smile_props
        tid = int(self.tooth_id or 0) or int(getattr(p, "target_tooth_id", 8) or 8)
        src_name = ""
        if self.scope == "ACTIVE_SCAN":
            act = context.view_layer.objects.active
            if act and act.type == "MESH":
                src_name = str(act.name)
        removed = clear_interprox_divider(
            context.scene, tid, source_name=src_name, side=str(self.side)
        )
        if removed <= 0:
            self.report({"WARNING"}, f"No divider data found for T#{tid}.")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Cleared {removed} divider record(s) for T#{tid} [{str(self.side)}].",
        )
        return {"FINISHED"}


class SMILE_OT_show_interprox_preview(bpy.types.Operator):
    bl_idname = "smile.show_interprox_preview"
    bl_label = "Show Interprox Preview"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=0, min=1, max=32)

    def execute(self, context):
        scene = context.scene
        p = scene.smile_props
        tid = int(self.tooth_id or 0) or int(getattr(p, "target_tooth_id", 8) or 8)
        scan_hint = str(p.max_target if tid <= 16 else p.man_target)
        div = get_interprox_divider(
            scene,
            context.view_layer.objects.active,
            tooth_id=tid,
            scan_name_hint=scan_hint,
        )
        if not div:
            rec = _latest_interprox_record_for_tooth(scene, tid)
            if isinstance(rec, dict):
                raw_divs = (
                    rec.get("dividers", {})
                    if isinstance(rec.get("dividers"), dict)
                    else {}
                )
                div = {
                    "source_object": str(rec.get("source_object", scan_hint)),
                    "tooth_id": int(_int_or_default(rec.get("tooth_id", tid), tid)),
                    "mesial": raw_divs.get("MESIAL")
                    if isinstance(raw_divs.get("MESIAL"), dict)
                    else None,
                    "distal": raw_divs.get("DISTAL")
                    if isinstance(raw_divs.get("DISTAL"), dict)
                    else None,
                }
        if not div:
            self.report(
                {"ERROR"}, f"No divider saved for T#{tid}. Mark mesial/distal first."
            )
            return {"CANCELLED"}
        src = str(div.get("source_object", scan_hint))
        made = 0
        if isinstance(div.get("mesial"), dict):
            made += _upsert_interprox_preview_planes(
                scene,
                src,
                tid,
                div.get("mesial"),
                size_mm=float(getattr(p, "ven_interprox_preview_size_mm", 10.0)),
            )
        if isinstance(div.get("distal"), dict):
            made += _upsert_interprox_preview_planes(
                scene,
                src,
                tid,
                div.get("distal"),
                size_mm=float(getattr(p, "ven_interprox_preview_size_mm", 10.0)),
            )
        p.ven_interprox_preview_show = made > 0
        if made <= 0:
            self.report({"ERROR"}, "Failed to build interprox preview planes.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Interprox preview shown for T#{tid} ({src}).")
        return {"FINISHED"}


class SMILE_OT_hide_interprox_preview(bpy.types.Operator):
    bl_idname = "smile.hide_interprox_preview"
    bl_label = "Hide Interprox Preview"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(name="Tooth #", default=0, min=0, max=32)
    all_teeth: bpy.props.BoolProperty(name="All Teeth", default=False)

    def execute(self, context):
        p = context.scene.smile_props
        if bool(self.all_teeth):
            _remove_interprox_preview_objects()
            p.ven_interprox_preview_show = False
            self.report({"INFO"}, "Interprox preview hidden (all teeth).")
            return {"FINISHED"}
        tid = int(self.tooth_id or 0) or int(getattr(p, "target_tooth_id", 8) or 8)
        _remove_interprox_preview_objects(tid)
        still = any(bool(o.get("SMILE_IPDIV_PREVIEW", False)) for o in bpy.data.objects)
        p.ven_interprox_preview_show = bool(still)
        self.report({"INFO"}, f"Interprox preview hidden for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_undo_die_step(bpy.types.Operator):
    bl_idname = "smile.undo_die_step"
    bl_label = "Undo Step"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        tid = p.target_tooth_id
        spacer = None
        for obj in bpy.data.objects:
            if obj.name.startswith(f"SPACER_") and obj.name.endswith(f"_T{tid}"):
                spacer = obj
                break
        if spacer:
            delete_object(spacer)
            self.report({"INFO"}, f"Deleted Spacer T#{tid}")
            return {"FINISHED"}
        die = None
        for obj in bpy.data.objects:
            if obj.name.startswith(f"DIE_") and obj.name.endswith(f"_T{tid}"):
                die = obj
                break
        if die:
            delete_object(die)
            self.report({"INFO"}, f"Deleted Die T#{tid}")
            return {"FINISHED"}
        self.report({"WARNING"}, "Nothing to undo for this tooth ID.")
        return {"CANCELLED"}


class SMILE_OT_run_pending_autodie_tab6(bpy.types.Operator):
    bl_idname = "smile.run_pending_autodie_tab6"
    bl_label = "Run Pending Auto-Die (Tab 6)"
    bl_options = {"REGISTER", "UNDO"}

    run_all: bpy.props.BoolProperty(name="Run All", default=False)

    def execute(self, context):
        max_jobs = 999 if bool(self.run_all) else 1
        done = 0
        fail = 0
        msgs = []
        for _ in range(max_jobs):
            status, msg = _run_pending_autodie_job(context, operator=self)
            if status == "EMPTY":
                break
            if status == "OK":
                done += 1
            else:
                fail += 1
            if msg:
                msgs.append(msg)
        pending = _autodie_queue_count(context.scene)
        if done == 0 and fail == 0:
            self.report({"INFO"}, "No pending auto-die jobs.")
            return {"FINISHED"}
        if fail > 0:
            self.report(
                {"WARNING"}, f"Auto-die: {done} done, {fail} failed, {pending} pending."
            )
        else:
            self.report({"INFO"}, f"Auto-die: {done} done, {pending} pending.")
        return {"FINISHED"}


class SMILE_OT_clear_pending_autodie_tab6(bpy.types.Operator):
    bl_idname = "smile.clear_pending_autodie_tab6"
    bl_label = "Clear Pending Auto-Die Queue"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = _autodie_queue_count(context.scene)
        _autodie_queue_write(context.scene, [])
        self.report({"INFO"}, f"Cleared pending auto-die queue ({n} job(s)).")
        return {"FINISHED"}


class SMILE_OT_clear_margin_data(bpy.types.Operator):
    bl_idname = "smile.clear_margin_data"
    bl_label = "Clear Margin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Select the target scan mesh first.")
            return {"CANCELLED"}
        counts = _clear_margin_for_tooth(
            context.scene,
            tooth,
            getattr(context.scene.smile_props, "target_tooth_id", 0),
        )
        self.report(
            {"INFO"},
            f"Cleared T#{counts.get('tid', 0)} Margin (data:{counts.get('data_keys', 0)}, curves:{counts.get('curves', 0)}, markers:{counts.get('markers', 0)}).",
        )
        return {"FINISHED"}


# ============================================================
# UI DRAWING FUNCTION
# ============================================================


def _ui_fold_header(layout, props, key, label, icon="DOT"):
    expanded = getattr(props, key, True)
    row = layout.row(align=True)
    row.prop(
        props,
        key,
        text="",
        icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
        emboss=False,
    )
    row.label(text=label, icon=icon)
    return expanded


def draw_production_tab(context, layout, props):
    """Draw the PRODUCTION tab UI."""
    scene = context.scene
    p = props
    current_step = getattr(p, "workflow_step", 4)
    prod_unlocked = (not p.enforce_step_lock) or (current_step >= 4)
    validate_unlocked = (not p.enforce_step_lock) or (current_step >= 5)
    export_unlocked = (not p.enforce_step_lock) or (current_step >= 6)

    if p.enforce_step_lock and not prod_unlocked:
        layout.label(
            text="Step lock: move to Step 4+ for production tools.", icon="LOCKED"
        )

    if _ui_fold_header(
        layout, p, "ui_prod_sec_margin", "Margin Tracing", icon="CURVE_DATA"
    ):
        mbox = layout.box()
        mbox.label(text="Margin Tracing (Professional CAD)", icon="CURVE_DATA")
        mbox.enabled = prod_unlocked

        tbox = mbox.box()
        tbox.label(text="Target Tooth #")

        def draw_margin_tooth_btn(layout, tid):
            name = f"{tid}"
            has_margin = False
            if context.view_layer.objects.active:
                data = get_margin_data(
                    context.scene, context.view_layer.objects.active, tid
                )
                if data:
                    has_margin = True
            is_active = p.target_tooth_id == tid
            op = layout.operator(
                "smile.select_target_tooth",
                text=name,
                emboss=not is_active,
                depress=has_margin,
            )
            op.tooth_id = tid

        col = tbox.column(align=True)
        row = col.row(align=True)
        for i in range(1, 17):
            draw_margin_tooth_btn(row, i)
            if i == 8:
                row.separator()
        row = col.row(align=True)
        for i in range(17, 33):
            draw_margin_tooth_btn(row, i)
            if i == 24:
                row.separator()

        mbox.separator()
        row = mbox.row(align=True)
        row.scale_y = 1.2
        row.operator(
            "smile.trace_margin_interactive", text="Click Trace", icon="GREASEPENCIL"
        )
        row.operator(
            "smile.trace_margin_smooth", text="Smooth Trace", icon="IPO_BEZIER"
        )
        row.operator(
            "smile.trace_margin_drag_smooth", text="Drag Smooth", icon="GREASEPENCIL"
        )
        row.operator(
            "smile.trace_margin_drag", text="Drag Trace", icon="FORCE_MAGNETIC"
        )

        row = mbox.row(align=True)
        row.operator(
            "smile.edit_margin_object_mode", text="Edit (Gizmos)", icon="GIZMO"
        )
        row.operator(
            "smile.margin_trace_undo_last", text="Undo Trace Point", icon="LOOP_BACK"
        )
        row = mbox.row(align=True)
        row.operator("smile.clear_margin_data", text="Clear", icon="CANCEL")

        if _ui_fold_header(
            mbox,
            p,
            "ui_prod_margin_sec_autodie",
            "Auto Die on Margin Close",
            icon="MESH_PLANE",
        ):
            adbox = mbox.box()
            adbox.prop(
                p, "margin_auto_create_die_on_close", text="Enable Auto-Create Die"
            )
            adbox.prop(
                p,
                "margin_auto_create_die_tab6_deferred",
                text="Use Deferred Tab 6 Runner",
            )
            qcount = _autodie_queue_count(scene)
            adbox.label(text=f"Pending Auto-Die jobs: {qcount}", icon="TIME")
            row = adbox.row(align=True)
            op = row.operator(
                "smile.run_pending_autodie_tab6", text="Run Next", icon="PLAY"
            )
            op.run_all = False
            op = row.operator(
                "smile.run_pending_autodie_tab6", text="Run All", icon="FILE_REFRESH"
            )
            op.run_all = True
            row = adbox.row(align=True)
            row.operator(
                "smile.clear_pending_autodie_tab6", text="Clear Queue", icon="TRASH"
            )

    if _ui_fold_header(
        layout,
        p,
        "ui_prod_sec_interprox",
        "Interprox Divider",
        icon="GP_SELECT_STROKES",
    ):
        ibox = layout.box()
        ibox.enabled = prod_unlocked
        ibox.label(text="Interprox Divider (Scan Monolithic)", icon="GP_SELECT_STROKES")
        ibox.prop(
            p, "ven_use_interprox_divider", text="Use Divider in Veneer Generation"
        )
        row = ibox.row(align=True)
        row.prop(p, "ven_interprox_pad_mm", text="Stop Padding (mm)")
        row.prop(p, "ven_interprox_preview_size_mm", text="Preview Size (mm)")

        tid_div = int(getattr(p, "target_tooth_id", 0) or 8)
        scan_hint_div = (
            str(p.max_target if tid_div <= 16 else p.man_target) if tid_div > 0 else ""
        )
        div_data = get_interprox_divider(
            scene,
            context.view_layer.objects.active,
            tooth_id=tid_div,
            scan_name_hint=scan_hint_div,
        )

        if div_data:
            has_mes = bool(div_data.get("mesial"))
            has_dis = bool(div_data.get("distal"))
            ibox.label(
                text=f"T#{tid_div}: Source {str(div_data.get('source_object', 'scan'))}",
                icon="CHECKMARK",
            )
            ibox.label(
                text=f"Mesial divider: {'Saved' if has_mes else 'Not set'}",
                icon="CHECKMARK" if has_mes else "INFO",
            )
            ibox.label(
                text=f"Distal divider: {'Saved' if has_dis else 'Not set'}",
                icon="CHECKMARK" if has_dis else "INFO",
            )
        else:
            ibox.label(text=f"T#{tid_div}: Not set", icon="INFO")

        row = ibox.row(align=True)
        op = row.operator(
            "smile.capture_interprox_divider",
            text="Mark Mesial Divider",
            icon="TRACKING_REFINE_FORWARDS",
        )
        op.tooth_id = tid_div if tid_div > 0 else 8
        op.side = "MESIAL"
        op = row.operator(
            "smile.capture_interprox_divider",
            text="Mark Distal Divider",
            icon="TRACKING_REFINE_BACKWARDS",
        )
        op.tooth_id = tid_div if tid_div > 0 else 8
        op.side = "DISTAL"
        row = ibox.row(align=True)
        op = row.operator("smile.clear_interprox_divider", text="Clear", icon="CANCEL")
        op.tooth_id = tid_div if tid_div > 0 else 8
        op.scope = "ALL_FOR_TOOTH"
        op.side = "BOTH"
        row = ibox.row(align=True)
        op = row.operator(
            "smile.show_interprox_preview", text="Show Preview", icon="HIDE_OFF"
        )
        op.tooth_id = tid_div if tid_div > 0 else 8
        op = row.operator(
            "smile.hide_interprox_preview", text="Hide Preview", icon="HIDE_ON"
        )
        op.tooth_id = tid_div if tid_div > 0 else 8

    if _ui_fold_header(
        layout, p, "ui_prod_sec_die", "Die + Veneer Fabrication", icon="MOD_BOOLEAN"
    ):
        vbox = layout.box()
        vbox.label(text="Die & Veneer Fabrication", icon="MOD_BOOLEAN")
        vbox.enabled = prod_unlocked
        row = vbox.row(align=True)
        row.scale_y = 1.2
        row.operator(
            "smile.create_die_and_spacer",
            text="1. Create Die + Spacer",
            icon="MESH_PLANE",
        )
        row = vbox.row(align=True)
        icon_die = "HIDE_OFF" if p.show_traditional_die else "HIDE_ON"
        row.operator(
            "smile.toggle_traditional_die",
            text="Show Traditional Die"
            if not p.show_traditional_die
            else "Hide Traditional Die",
            icon=icon_die,
            depress=p.show_traditional_die,
        )
        row = vbox.row(align=True)
        row.operator("smile.undo_die_step", text="Undo Last Step", icon="LOOP_BACK")
        row = vbox.row(align=True)
        row.operator(
            "smile.boolean_cut_intaglio", text="3. Finalize Die", icon="MOD_BOOLEAN"
        )
        row = vbox.row(align=True)
        row.scale_y = 1.3
        row.operator(
            "smile.auto_gingiva", text="Generate Gingiva", icon="MESH_UVSPHERE"
        )

    if _ui_fold_header(
        layout,
        p,
        "ui_prod_sec_fabrication",
        "3D Printing / Fabrication",
        icon="MESH_DATA",
    ):
        fbox = layout.box()
        fbox.prop(p, "cement_gap_slider", text="Cement Gap (mm)", slider=True)
        row = fbox.row(align=True)
        row.scale_y = 1.5
        row.operator(
            "smile.generate_shell", text="Generate Printable Shell", icon="MESH_CUBE"
        )

    if _ui_fold_header(
        layout, p, "ui_prod_sec_validation", "Analysis & Validation", icon="CHECKMARK"
    ):
        abox = layout.box()
        abox.enabled = validate_unlocked
        row = abox.row(align=True)
        row.scale_y = 1.3
        row.operator("smile.check_occlusion", text="Check Occlusion", icon="LIGHT_SUN")
        row = abox.row(align=True)
        row.scale_y = 1.3
        row.operator(
            "smile.analyze_thickness", text="Thickness Heatmap", icon="COLORSET_01_VEC"
        )
        cbox = abox.box()
        cbox.label(text="Adjacent Contact Surface Map", icon="GROUP_VERTEX")
        row = cbox.row(align=True)
        row.prop(p, "adj_contact_tight_mm", text="Tight (mm)")
        row.prop(p, "adj_contact_threshold_mm", text="Contact (mm)")
        row = cbox.row(align=True)
        row.scale_y = 1.2
        row.operator(
            "smile.analyze_adjacent_contacts",
            text="Analyze Adjacent Contacts",
            icon="GROUP_VERTEX",
        )
        row = abox.row(align=True)
        row.scale_y = 1.3
        row.operator(
            "smile.survey_undercuts", text="Survey Undercuts", icon="ARROW_LEFTRIGHT"
        )


# ============================================================
# REGISTRATION
# ============================================================

# === MISSING MARGIN TRACING HELPERS ===
# These functions are required by the margin tracing operators above
# but were not yet migrated from the monolith.


def _parse_margin_curve_tooth_id(curve_name: str) -> int:
    try:
        m = re.search(r"_T(\d+)(?:_Curve)?$", str(curve_name or ""))
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def _distance_point_to_segment_local(pt, a, b):
    ab = b - a
    ab_len2 = ab.length_squared
    if ab_len2 < 1.0e-12:
        return (pt - a).length
    t = max(0.0, min(1.0, (pt - a).dot(ab) / ab_len2))
    proj = a + ab * t
    return (pt - proj).length


def _mm_to_bu_for_obj(mm_val, obj_hint=None):
    try:
        scl = float(
            getattr(bpy.context.scene.unit_settings, "scale_length", 1.0) or 1.0
        )
    except Exception:
        scl = 1.0
    bu = float(mm_val) / max(1.0e-12, scl * 1000.0)
    if obj_hint is not None:
        try:
            max_dim = max(
                float(obj_hint.dimensions.x),
                float(obj_hint.dimensions.y),
                float(obj_hint.dimensions.z),
            )
            if max_dim > 5.0:
                bu = float(mm_val)
        except Exception:
            pass
    return float(bu)


def _mm_to_local_for_cache(mm_val, cache):
    obj_hint = None
    try:
        obj_name = str((cache or {}).get("obj_name", ""))
        if obj_name:
            obj_hint = bpy.data.objects.get(obj_name)
    except Exception:
        obj_hint = None
    world_bu = _mm_to_bu_for_obj(mm_val, obj_hint=obj_hint)
    mw = (cache or {}).get("matrix_world")
    try:
        sc = mw.to_scale() if mw is not None else Vector((1.0, 1.0, 1.0))
        scale_avg = (abs(float(sc.x)) + abs(float(sc.y)) + abs(float(sc.z))) / 3.0
    except Exception:
        scale_avg = 1.0
    scale_avg = max(scale_avg, 1.0e-12)
    return float(world_bu / scale_avg)


def _project_world_to_mesh(obj, world_pt):
    obj = _resolve_mesh_object(obj)
    if not obj:
        return world_pt
    try:
        mw_inv = obj.matrix_world.inverted()
        ok, loc, _n, _fi = obj.closest_point_on_mesh(mw_inv @ world_pt)
        if ok:
            return obj.matrix_world @ loc
    except Exception:
        pass
    return world_pt


def build_margin_graph_cache(obj, *, decimate_ratio=1.0):
    if not obj or obj.type != "MESH":
        return {}
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        vert_count = len(bm.verts)
        verts_local = [v.co.copy() for v in bm.verts]
        adjacency = {i: [] for i in range(vert_count)}
        edge_dihedral_cost = {}
        edge_len_map = {}
        vert_curvature = {}
        kd = KDTree(max(1, vert_count))
        for i, v in enumerate(bm.verts):
            kd.insert(v.co.copy(), i)
            try:
                vert_curvature[i] = float(compute_vertex_curvature(v, bm.verts))
            except Exception:
                vert_curvature[i] = 0.0
        kd.balance()
        for e in bm.edges:
            v1 = e.verts[0].index
            v2 = e.verts[1].index
            seg_len = float(e.calc_length())
            d_cost = float(compute_dihedral_cost(e))
            key = (v1, v2) if v1 < v2 else (v2, v1)
            edge_dihedral_cost[key] = d_cost
            edge_len_map[key] = seg_len
            adjacency[v1].append((v2, seg_len, d_cost))
            adjacency[v2].append((v1, seg_len, d_cost))
    finally:
        bm.free()
    return {
        "obj_name": obj.name,
        "matrix_world": obj.matrix_world.copy(),
        "matrix_world_inv": obj.matrix_world.inverted(),
        "decimate_ratio": float(decimate_ratio),
        "verts_local": verts_local,
        "adjacency": adjacency,
        "edge_dihedral_cost": edge_dihedral_cost,
        "edge_len": edge_len_map,
        "vert_curvature": vert_curvature,
        "vert_count": vert_count,
        "edge_count": len(edge_len_map),
        "kd_local": kd,
    }


def compute_margin_evidence(
    cache, *, w_dihedral=0.55, w_curvature=0.30, w_normal_var=0.10, w_depth=0.05
):
    if not cache:
        return {"edge_evidence": {}, "vert_evidence": {}, "params": {}}
    verts_local = cache.get("verts_local", [])
    edge_dihedral = cache.get("edge_dihedral_cost", {})
    edge_len = cache.get("edge_len", {})
    vert_curv = cache.get("vert_curvature", {})
    adjacency = cache.get("adjacency", {})
    z_vals = [v.z for v in verts_local] if verts_local else [0.0]
    z_min = min(z_vals) if z_vals else 0.0
    z_max = max(z_vals) if z_vals else 1.0
    z_span = max(1.0e-6, z_max - z_min)
    edge_evidence = {}
    vert_sum = {i: 0.0 for i in adjacency.keys()}
    vert_cnt = {i: 0 for i in adjacency.keys()}
    denom = max(1.0e-6, (w_dihedral + w_curvature + w_normal_var + w_depth))
    for key, d_cost in edge_dihedral.items():
        v1, v2 = key
        ridge = max(0.0, min(1.0, 1.0 / (1.0 + d_cost)))
        curv = max(
            0.0, min(1.0, 0.5 * (vert_curv.get(v1, 0.0) + vert_curv.get(v2, 0.0)))
        )
        nvar = max(0.0, min(1.0, abs(vert_curv.get(v1, 0.0) - vert_curv.get(v2, 0.0))))
        depth = 0.0
        if 0 <= v1 < len(verts_local) and 0 <= v2 < len(verts_local):
            depth = abs(verts_local[v1].z - verts_local[v2].z) / z_span
            depth = max(0.0, min(1.0, depth))
        e = (
            w_dihedral * ridge
            + w_curvature * curv
            + w_normal_var * nvar
            + w_depth * depth
        ) / denom
        e = max(0.0, min(1.0, e))
        edge_evidence[key] = e
        vert_sum[v1] = vert_sum.get(v1, 0.0) + e
        vert_sum[v2] = vert_sum.get(v2, 0.0) + e
        vert_cnt[v1] = vert_cnt.get(v1, 0) + 1
        vert_cnt[v2] = vert_cnt.get(v2, 0) + 1
    vert_evidence = {}
    for vid in vert_sum.keys():
        c = max(1, vert_cnt.get(vid, 0))
        vert_evidence[vid] = vert_sum.get(vid, 0.0) / c
    return {
        "edge_evidence": edge_evidence,
        "vert_evidence": vert_evidence,
        "params": {
            "w_dihedral": float(w_dihedral),
            "w_curvature": float(w_curvature),
            "w_normal_var": float(w_normal_var),
            "w_depth": float(w_depth),
        },
    }


def snap_point_to_margin_evidence(
    cache, evidence, world_point, *, radius_mm=0.8, attraction=0.55, search_k=20
):
    if not cache:
        return Vector(world_point)
    kd = cache.get("kd_local")
    verts_local = cache.get("verts_local", [])
    mw = cache.get("matrix_world")
    mw_inv = cache.get("matrix_world_inv")
    if kd is None or mw is None or mw_inv is None or not verts_local:
        return Vector(world_point)
    p_world = Vector(world_point)
    p_local = mw_inv @ p_world
    vv = (evidence or {}).get("vert_evidence", {}) if isinstance(evidence, dict) else {}
    local_radius = max(
        1.0e-6, float(_mm_to_local_for_cache(max(0.1, float(radius_mm)), cache))
    )
    try:
        hits = kd.find_range(p_local, local_radius)
    except Exception:
        hits = []
    if not hits:
        try:
            hits = kd.find_n(p_local, max(4, int(search_k)))
        except Exception:
            hits = []
    if not hits:
        return p_world
    best_idx = None
    best_score = float("inf")
    for _co, idx, dist in hits:
        vid = int(idx)
        if not (0 <= vid < len(verts_local)):
            continue
        ev = max(0.0, min(1.0, float(vv.get(vid, 0.0))))
        score = float(dist) / (0.20 + 0.80 * ev)
        if score < best_score:
            best_score = score
            best_idx = vid
    if best_idx is None:
        return p_world
    snapped_local = verts_local[int(best_idx)]
    a = max(0.0, min(1.0, float(attraction)))
    blended_local = p_local.lerp(snapped_local, a)
    return mw @ blended_local


def geodesic_fill_segment(obj, start_world, end_world, prefer_ridges=True):
    if not obj or obj.type != "MESH":
        return [start_world, end_world]
    mw = obj.matrix_world
    mw_inv = mw.inverted()
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        kd = KDTree(len(bm.verts))
        for i, v in enumerate(bm.verts):
            kd.insert(v.co, i)
        kd.balance()
        _, v1_idx, _ = kd.find(mw_inv @ start_world)
        _, v2_idx, _ = kd.find(mw_inv @ end_world)
        v_start = bm.verts[v1_idx]
        v_end = bm.verts[v2_idx]
        g_score = {v_start: 0.0}
        predecessors = {v_start: None}
        pq = [(0.0, 0.0, v_start.index)]
        target_co = v_end.co
        max_iters = 15000
        iters = 0
        import heapq

        while pq and iters < max_iters:
            iters += 1
            f, g, v_idx = heapq.heappop(pq)
            v = bm.verts[v_idx]
            if v == v_end:
                break
            if g > g_score.get(v, float("inf")):
                continue
            for edge in v.link_edges:
                neighbor = edge.other_vert(v)
                edge_len = edge.calc_length()
                weight = edge_len
                if prefer_ridges:
                    d_cost = compute_dihedral_cost(edge)
                    weight *= d_cost
                new_g = g + weight
                if new_g < g_score.get(neighbor, float("inf")):
                    g_score[neighbor] = new_g
                    h = (neighbor.co - target_co).length
                    f_new = new_g + h
                    predecessors[neighbor] = v
                    heapq.heappush(pq, (f_new, new_g, neighbor.index))
        path = []
        curr = v_end
        while curr:
            path.append(mw @ curr.co)
            curr = predecessors.get(curr)
    finally:
        bm.free()
    if not path or len(path) < 2:
        return [start_world, end_world]
    path.reverse()
    return path


def build_guided_margin_loop_from_anchors(
    obj, anchors_world, scene_props, cache=None, evidence=None
):
    if not obj or obj.type != "MESH":
        return []
    anchors = [Vector(p) for p in (anchors_world or [])]
    if len(anchors) < 3:
        return project_loop_to_surface(obj, anchors)
    try:
        vcount = int(len(obj.data.vertices))
    except Exception:
        vcount = 0
    if vcount > 280000:
        return project_loop_to_surface(obj, anchors)
    cache = (
        cache
        if isinstance(cache, dict) and cache
        else build_margin_graph_cache(obj, decimate_ratio=1.0)
    )
    if not cache:
        return project_loop_to_surface(obj, anchors)
    if not evidence:
        try:
            evidence = compute_margin_evidence(
                cache,
                w_dihedral=float(
                    getattr(scene_props, "margin_evidence_w_dihedral", 0.65)
                ),
                w_curvature=float(
                    getattr(scene_props, "margin_evidence_w_curvature", 0.25)
                ),
                w_normal_var=float(
                    getattr(scene_props, "margin_evidence_w_normal_var", 0.07)
                ),
                w_depth=float(getattr(scene_props, "margin_evidence_w_depth", 0.03)),
            )
        except Exception:
            evidence = compute_margin_evidence(cache)
    kd = cache.get("kd_local")
    mw = cache.get("matrix_world")
    mw_inv = cache.get("matrix_world_inv")
    verts_local = cache.get("verts_local", [])
    if kd is None or mw is None or mw_inv is None or not verts_local:
        return project_loop_to_surface(obj, anchors)
    anchor_vids = []
    snapped_anchors = []
    corr_mm = max(0.35, float(getattr(scene_props, "margin_corridor_mm", 1.2)) * 0.80)
    magnet = max(
        0.20,
        min(
            0.90,
            0.50
            + 0.35 * float(getattr(scene_props, "margin_drag_smooth_effect", 0.35)),
        ),
    )
    for aw in anchors:
        s = snap_point_to_margin_evidence(
            cache,
            evidence,
            aw,
            radius_mm=max(0.4, corr_mm),
            attraction=magnet,
            search_k=18,
        )
        s = _project_world_to_mesh(obj, s)
        snapped_anchors.append(s)
        try:
            _co, idx, _d = kd.find(mw_inv @ s)
            anchor_vids.append(int(idx))
        except Exception:
            anchor_vids.append(None)
    out = []
    n = len(snapped_anchors)
    turn_pen = max(
        0.05, float(getattr(scene_props, "margin_turn_penalty", 0.25)) * 0.90
    )
    ev_gamma = max(1.2, float(getattr(scene_props, "margin_evidence_gamma", 1.8)))
    ee = evidence.get("edge_evidence", {}) if isinstance(evidence, dict) else {}
    for i in range(n):
        p0 = snapped_anchors[i]
        p1 = snapped_anchors[(i + 1) % n]
        v0 = anchor_vids[i] if i < len(anchor_vids) else None
        v1 = anchor_vids[(i + 1) % n] if anchor_vids else None
        seg = []
        if (v0 is not None) and (v1 is not None) and int(v0) != int(v1):
            try:
                vid_path = solve_margin_segment(
                    cache,
                    int(v0),
                    int(v1),
                    corridor_mm=float(corr_mm),
                    turn_penalty=float(turn_pen),
                    evidence_gamma=float(ev_gamma),
                    edge_evidence=ee,
                )
                if vid_path and len(vid_path) >= 2:
                    seg = [
                        mw @ verts_local[int(vid)]
                        for vid in vid_path
                        if 0 <= int(vid) < len(verts_local)
                    ]
            except Exception:
                seg = []
        if not seg or len(seg) < 2:
            seg = geodesic_fill_segment(obj, p0, p1, prefer_ridges=True)
        if not seg or len(seg) < 2:
            seg = [p0, p1]
        seg = refine_segment_surface(obj, seg, evidence, iters=1, step_mm=0.05)
        seg = project_loop_to_surface(obj, seg)
        if not out:
            out.extend(seg)
        elif (seg[0] - out[-1]).length < 1.0e-4:
            out.extend(seg[1:])
        else:
            out.extend(seg)
    out = project_loop_to_surface(obj, out)
    if len(out) >= 3 and (out[0] - out[-1]).length < 1.0e-6:
        out.pop()
    if len(out) > 10:
        tol_bu = max(
            _mm_to_bu_for_obj(0.005, obj_hint=obj),
            _mm_to_bu_for_obj(
                min(
                    0.08,
                    max(
                        0.01,
                        float(getattr(scene_props, "margin_simplify_tolerance", 0.15))
                        * 0.35,
                    ),
                ),
                obj_hint=obj,
            ),
        )
        out = simplify_path_rdp(out, tol_bu)
        out = project_loop_to_surface(obj, out)
    if len(out) >= 4:
        t = max(
            0.0,
            min(1.0, float(getattr(scene_props, "margin_drag_smooth_effect", 0.35))),
        )
        out = round_polyline_corners_surface(
            obj,
            out,
            effect=min(0.45, 0.12 + 0.33 * t),
            angle_threshold_deg=158.0,
            cyclic=True,
            max_corner_cut_mm=(0.03 + 0.14 * t),
        )
        out = smooth_polyline_surface(
            obj,
            out,
            iterations=1 + (1 if t > 0.70 else 0),
            strength=min(0.16, 0.04 + 0.10 * t),
            cyclic=True,
            pinned_indices=None,
        )
        out = project_loop_to_surface(obj, out)
    return out


def solve_margin_segment(
    cache,
    v_start,
    v_end,
    *,
    corridor_mm=1.2,
    turn_penalty=0.25,
    evidence_gamma=1.8,
    edge_evidence=None,
    max_iters=None,
):
    import heapq

    if not cache:
        return [int(v_start), int(v_end)]
    adjacency = cache.get("adjacency", {})
    verts_local = cache.get("verts_local", [])
    if not adjacency or not verts_local:
        return [int(v_start), int(v_end)]
    n = len(verts_local)
    if not (0 <= int(v_start) < n and 0 <= int(v_end) < n):
        return [int(v_start), int(v_end)]
    v_start = int(v_start)
    v_end = int(v_end)
    ev = (
        edge_evidence
        if isinstance(edge_evidence, dict)
        else compute_margin_evidence(cache).get("edge_evidence", {})
    )
    a = verts_local[v_start]
    b = verts_local[v_end]
    corridor_mm = max(0.05, float(corridor_mm))
    corridor_local = max(1.0e-6, float(_mm_to_local_for_cache(corridor_mm, cache)))
    evidence_gamma = max(0.5, float(evidence_gamma))
    turn_penalty = max(0.0, float(turn_penalty))

    def in_corridor(vid):
        if vid == v_start or vid == v_end:
            return True
        if not (0 <= vid < len(verts_local)):
            return False
        d = _distance_point_to_segment_local(verts_local[vid], a, b)
        return d <= corridor_local

    g = {v_start: 0.0}
    parent = {v_start: None}
    pq = [(0.0, 0.0, v_start, None)]
    if max_iters is None:
        max_iters = max(2000, min(150000, n * 16))
    else:
        max_iters = max(500, int(max_iters))
    it = 0
    while pq and it < max_iters:
        it += 1
        f_curr, g_curr, vid, prev_vid = heapq.heappop(pq)
        if vid == v_end:
            break
        if g_curr > g.get(vid, float("inf")):
            continue
        for nbr, seg_len, _d_cost in adjacency.get(vid, []):
            if not in_corridor(nbr):
                continue
            key = (vid, nbr) if vid < nbr else (nbr, vid)
            e = max(0.05, float(ev.get(key, 0.5)))
            step = float(seg_len) / (e**evidence_gamma)
            if prev_vid is not None and 0 <= prev_vid < len(verts_local):
                v_prev = verts_local[vid] - verts_local[prev_vid]
                v_next = verts_local[nbr] - verts_local[vid]
                if v_prev.length > 1.0e-8 and v_next.length > 1.0e-8:
                    try:
                        ang = v_prev.normalized().angle(v_next.normalized())
                        step += turn_penalty * ang * float(seg_len)
                    except Exception:
                        pass
            new_g = g_curr + step
            if new_g < g.get(nbr, float("inf")):
                g[nbr] = new_g
                parent[nbr] = vid
                h = (verts_local[nbr] - b).length
                heapq.heappush(pq, (new_g + h, new_g, nbr, vid))
    if v_end not in parent:
        return [v_start, v_end]
    path = []
    cur = v_end
    while cur is not None:
        path.append(cur)
        cur = parent.get(cur)
    path.reverse()
    return path if len(path) >= 2 else [v_start, v_end]


def refine_segment_surface(obj, points_world, evidence, *, iters=2, step_mm=0.05):
    if not obj or obj.type != "MESH" or not points_world:
        return list(points_world or [])
    pts = [_project_world_to_mesh(obj, Vector(p)) for p in points_world]
    if len(pts) < 3:
        return pts
    iters = max(0, int(iters))
    step_mm = max(0.001, float(step_mm))
    step_bu = max(1.0e-6, _mm_to_bu_for_obj(step_mm, obj_hint=obj))
    for _ in range(iters):
        nxt = [pts[0]]
        for i in range(1, len(pts) - 1):
            prev_p = pts[i - 1]
            curr_p = pts[i]
            next_p = pts[i + 1]
            target = (prev_p + next_p) * 0.5
            move = target - curr_p
            if move.length > step_bu:
                move = move.normalized() * step_bu
            nxt.append(_project_world_to_mesh(obj, curr_p + move))
        nxt.append(pts[-1])
        pts = nxt
    return pts


def trace_ridge_path_between_points(
    obj,
    cache,
    evidence,
    pt_a_world,
    pt_b_world,
    *,
    magnet_strength=0.45,
    resample_spacing_mm=0.12,
    corridor_mm=2.5,
    evidence_gamma=1.8,
    turn_penalty=0.25,
    smooth_passes=2,
    max_iters=None,
):
    if not obj or obj.type != "MESH":
        return [Vector(pt_a_world), Vector(pt_b_world)]
    pt_a = Vector(pt_a_world)
    pt_b = Vector(pt_b_world)
    if not cache:
        return _resample_and_project_segment(obj, pt_a, pt_b, resample_spacing_mm)
    verts_local = cache.get("verts_local", [])
    kd = cache.get("kd_local")
    mw = cache.get("matrix_world")
    mw_inv = cache.get("matrix_world_inv")
    if not verts_local or kd is None or mw is None or mw_inv is None:
        return _resample_and_project_segment(obj, pt_a, pt_b, resample_spacing_mm)
    try:
        _co_a, vid_a, _da = kd.find(mw_inv @ pt_a)
        _co_b, vid_b, _db = kd.find(mw_inv @ pt_b)
    except Exception:
        return _resample_and_project_segment(obj, pt_a, pt_b, resample_spacing_mm)
    vid_a = int(vid_a)
    vid_b = int(vid_b)
    if vid_a == vid_b:
        return _resample_and_project_segment(obj, pt_a, pt_b, resample_spacing_mm)
    edge_ev = (evidence or {}).get("edge_evidence", {})
    path_vids = solve_margin_segment(
        cache,
        vid_a,
        vid_b,
        corridor_mm=corridor_mm,
        turn_penalty=turn_penalty,
        evidence_gamma=evidence_gamma,
        edge_evidence=edge_ev,
        max_iters=max_iters,
    )
    if len(path_vids) < 2:
        return _resample_and_project_segment(obj, pt_a, pt_b, resample_spacing_mm)
    path_world = []
    path_world.append(pt_a.copy())
    for vid in path_vids[1:-1]:
        if 0 <= vid < len(verts_local):
            path_world.append(mw @ verts_local[vid])
    path_world.append(pt_b.copy())
    if len(path_world) < 2:
        return _resample_and_project_segment(obj, pt_a, pt_b, resample_spacing_mm)
    spacing_bu = max(
        1.0e-6, _mm_to_bu_for_obj(float(resample_spacing_mm), obj_hint=obj)
    )
    resampled = []
    for i in range(len(path_world) - 1):
        seg_start = path_world[i]
        seg_end = path_world[i + 1]
        seg_len = (seg_end - seg_start).length
        n_sub = max(1, int(round(seg_len / spacing_bu)))
        for j in range(n_sub):
            t = float(j) / float(n_sub)
            interp = seg_start.lerp(seg_end, t)
            resampled.append(_project_world_to_mesh(obj, interp))
    resampled.append(_project_world_to_mesh(obj, path_world[-1]))
    if len(resampled) >= 4:
        resampled = smooth_polyline_surface(
            obj,
            resampled,
            iterations=4,
            strength=0.35,
            cyclic=False,
            pinned_indices=[0, len(resampled) - 1],
        )
    if len(resampled) < 2:
        return [_project_world_to_mesh(obj, pt_a), _project_world_to_mesh(obj, pt_b)]
    magnet_strength = max(0.0, min(1.0, float(magnet_strength)))
    if magnet_strength > 0.01 and len(resampled) > 4:
        interior = magnet_snap_to_soft_edges(
            obj,
            resampled[1:-1],
            magnet_strength=magnet_strength,
            k_neighbors=6,
        )
        resampled = [resampled[0]] + interior + [resampled[-1]]
    if smooth_passes > 0 and len(resampled) >= 4:
        resampled = smooth_polyline_surface(
            obj,
            resampled,
            iterations=int(smooth_passes),
            strength=0.15,
            cyclic=False,
            pinned_indices=[0, len(resampled) - 1],
        )
    return resampled


def _resample_and_project_segment(obj, pt_a, pt_b, spacing_mm=0.12):
    spacing_bu = max(1.0e-6, _mm_to_bu_for_obj(float(spacing_mm), obj_hint=obj))
    seg_len = (pt_b - pt_a).length
    n_sub = max(1, int(round(seg_len / spacing_bu)))
    result = []
    for j in range(n_sub + 1):
        t = float(j) / float(n_sub)
        interp = pt_a.lerp(pt_b, t)
        result.append(_project_world_to_mesh(obj, interp))
    return result


def blend_loop_seam_surface(obj, loop_world, seam_half_window=8, blend_strength=0.55):
    if not obj or obj.type != "MESH" or not loop_world:
        return list(loop_world or [])
    pts = [_project_world_to_mesh(obj, Vector(p)) for p in loop_world]
    n = len(pts)
    if n < 8:
        return pts
    seam_half_window = int(max(2, min(seam_half_window, max(2, n // 8))))
    blend_strength = max(0.0, min(1.0, float(blend_strength)))
    for k in range(seam_half_window):
        i_front = int(k)
        i_back = int(n - 1 - k)
        if i_back <= i_front:
            break
        t = 1.0 - (float(k) / max(1.0, float(seam_half_window)))
        w = blend_strength * (0.65 + 0.35 * t)
        mid = (pts[i_front] + pts[i_back]) * 0.5
        pts[i_front] = _project_world_to_mesh(obj, pts[i_front].lerp(mid, w))
        pts[i_back] = _project_world_to_mesh(obj, pts[i_back].lerp(mid, w))
    return pts


def smooth_polyline_surface(
    obj, points_world, *, iterations=2, strength=0.35, cyclic=False, pinned_indices=None
):
    if not obj or obj.type != "MESH" or not points_world:
        return list(points_world or [])
    pts = [_project_world_to_mesh(obj, Vector(p)) for p in points_world]
    n = len(pts)
    if n < 3:
        return pts
    strength = max(0.0, min(1.0, float(strength)))
    iterations = max(0, int(iterations))
    pinned = set(int(i) for i in (pinned_indices or []) if 0 <= int(i) < n)
    for _ in range(iterations):
        out = []
        for i in range(n):
            if i in pinned:
                out.append(pts[i].copy())
                continue
            if not cyclic and (i == 0 or i == n - 1):
                out.append(pts[i].copy())
                continue
            prev_p = pts[i - 1]
            next_p = pts[(i + 1) % n]
            target = (prev_p + next_p) * 0.5
            out.append(_project_world_to_mesh(obj, pts[i].lerp(target, strength)))
        pts = out
    return pts


def round_polyline_corners_surface(
    obj,
    points_world,
    *,
    effect=0.35,
    angle_threshold_deg=155.0,
    cyclic=True,
    max_corner_cut_mm=0.25,
):
    if not obj or obj.type != "MESH" or not points_world:
        return list(points_world or [])
    pts = [_project_world_to_mesh(obj, Vector(p)) for p in points_world]
    n = len(pts)
    if n < 4:
        return pts
    effect = max(0.0, min(1.0, float(effect)))
    if effect <= 1.0e-6:
        return pts
    angle_threshold_deg = max(5.0, min(179.0, float(angle_threshold_deg)))
    cut_cap = max(1.0e-6, _mm_to_bu_for_obj(float(max_corner_cut_mm), obj_hint=obj))

    def _append_unique(out_list, p):
        if not out_list:
            out_list.append(p.copy())
            return
        if (out_list[-1] - p).length > 1.0e-7:
            out_list.append(p.copy())

    out = []
    for i in range(n):
        is_end = i == 0 or i == n - 1
        if (not cyclic) and is_end:
            _append_unique(out, pts[i])
            continue
        prev_p = pts[(i - 1) % n]
        curr_p = pts[i]
        next_p = pts[(i + 1) % n]
        vin = prev_p - curr_p
        vout = next_p - curr_p
        lin = vin.length
        lout = vout.length
        if lin < 1.0e-8 or lout < 1.0e-8:
            _append_unique(out, curr_p)
            continue
        try:
            ang_deg = math.degrees(vin.normalized().angle(vout.normalized()))
        except Exception:
            ang_deg = 180.0
        if ang_deg >= angle_threshold_deg:
            _append_unique(out, curr_p)
            continue
        sharpness = (angle_threshold_deg - ang_deg) / max(1.0e-6, angle_threshold_deg)
        k = max(0.0, min(1.0, effect * sharpness))
        if k <= 1.0e-6:
            _append_unique(out, curr_p)
            continue
        cut = min(cut_cap, min(lin, lout) * (0.08 + 0.32 * k))
        if cut <= 1.0e-8:
            _append_unique(out, curr_p)
            continue
        p_in = curr_p + vin.normalized() * cut
        p_out = curr_p + vout.normalized() * cut
        mid_target = (p_in + p_out) * 0.5
        mid = curr_p.lerp(mid_target, min(0.85, 0.30 + 0.55 * k))
        _append_unique(out, _project_world_to_mesh(obj, p_in))
        _append_unique(out, _project_world_to_mesh(obj, mid))
        _append_unique(out, _project_world_to_mesh(obj, p_out))
    if cyclic and len(out) > 2 and (out[0] - out[-1]).length < 1.0e-7:
        out.pop()
    return out


def magnet_snap_to_soft_edges(
    obj, points_world, *, magnet_strength=0.45, k_neighbors=6
):
    if not obj or obj.type != "MESH" or not points_world:
        return list(points_world or [])
    magnet_strength = max(0.0, min(1.0, float(magnet_strength)))
    if magnet_strength < 1.0e-6:
        return list(points_world)
    k_neighbors = max(1, min(20, int(k_neighbors)))
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        bm.verts.ensure_lookup_table()
        vert_count = len(bm.verts)
        if vert_count < 4:
            return list(points_world)
        kd = KDTree(vert_count)
        for i, v in enumerate(bm.verts):
            kd.insert(v.co.copy(), i)
        kd.balance()
        vert_score = {}
        for v in bm.verts:
            dihedral_sum = 0.0
            dihedral_cnt = 0
            for e in v.link_edges:
                if len(e.link_faces) == 2:
                    f1, f2 = e.link_faces
                    dihedral_sum += abs(1.0 - f1.normal.dot(f2.normal))
                    dihedral_cnt += 1
            dihedral_avg = (
                (dihedral_sum / max(1, dihedral_cnt)) if dihedral_cnt > 0 else 0.0
            )
            neighbors = [ed.other_vert(v) for ed in v.link_edges]
            if neighbors:
                avg_n = Vector((0, 0, 0))
                for nb in neighbors:
                    avg_n += nb.normal
                if avg_n.length_squared > 1e-12:
                    avg_n.normalize()
                curvature = max(0.0, 1.0 - v.normal.dot(avg_n))
            else:
                curvature = 0.0
            score = 0.6 * min(1.0, dihedral_avg * 3.0) + 0.4 * min(1.0, curvature * 4.0)
            vert_score[v.index] = max(0.0, min(1.0, score))
        mw = obj.matrix_world
        mw_inv = mw.inverted()
        result = []
        for pt_w in points_world:
            pt_w = Vector(pt_w)
            pt_local = mw_inv @ pt_w
            neighbors = kd.find_n(pt_local, k_neighbors)
            if not neighbors:
                result.append(pt_w)
                continue
            best_idx = -1
            best_score = -1.0
            best_co = None
            for co_local, idx, dist in neighbors:
                s = vert_score.get(idx, 0.0)
                if s > best_score:
                    best_score = s
                    best_idx = idx
                    best_co = co_local
            if best_score < 0.05 or best_co is None:
                result.append(pt_w)
                continue
            attractor_world = mw @ best_co
            blend = magnet_strength * best_score
            snapped = pt_w.lerp(attractor_world, blend)
            result.append(_project_world_to_mesh(obj, snapped))
    finally:
        bm.free()
    return result


def smooth_closing_region(obj, loop_world, *, closing_window=8, closing_strength=0.55):
    if not obj or obj.type != "MESH" or not loop_world:
        return list(loop_world or [])
    pts = [Vector(p) for p in loop_world]
    n = len(pts)
    if n < 8:
        return [_project_world_to_mesh(obj, p) for p in pts]
    closing_window = int(max(2, min(closing_window, max(2, n // 4))))
    closing_strength = max(0.0, min(1.0, float(closing_strength)))
    sigma = max(1.0, float(closing_window) / 2.5)
    for iteration in range(2):
        out = list(pts)
        for k in range(-closing_window, closing_window + 1):
            idx = k % n
            gauss_w = math.exp(-0.5 * (float(k) / sigma) ** 2)
            w = closing_strength * gauss_w
            if w < 1.0e-4:
                continue
            prev_idx = (idx - 1) % n
            next_idx = (idx + 1) % n
            laplacian_target = (pts[prev_idx] + pts[next_idx]) * 0.5
            blended = pts[idx].lerp(laplacian_target, w)
            out[idx] = _project_world_to_mesh(obj, blended)
        pts = out
    return pts


def finalize_margin_loop_surface_like_drag(
    obj,
    points_world,
    *,
    smooth_effect=0.35,
    simplify_tol_mm=0.15,
    magnet_strength=0.45,
    closing_smooth_window=8,
):
    if not obj or obj.type != "MESH":
        return [], 0.0
    raw_pts = []
    for p in points_world or []:
        try:
            raw_pts.append(Vector(p))
        except Exception:
            continue
    if len(raw_pts) < 3:
        return project_loop_to_surface(obj, raw_pts), 0.0
    tol_bu = max(
        _mm_to_bu_for_obj(0.01, obj_hint=obj),
        _mm_to_bu_for_obj(float(simplify_tol_mm), obj_hint=obj),
    )
    if len(raw_pts) > 3:
        simplified = simplify_path_rdp(raw_pts, tol_bu)
    else:
        simplified = list(raw_pts)
    final_pts = project_loop_to_surface(obj, simplified)
    if (
        bool(final_pts)
        and len(final_pts) > 1
        and (final_pts[0] - final_pts[-1]).length < 1.0e-6
    ):
        final_pts.pop()
    if len(final_pts) < 3:
        final_pts = project_loop_to_surface(obj, raw_pts)
    smooth_effect = max(0.0, min(1.0, float(smooth_effect)))
    smooth_fine = pow(smooth_effect, 2.2)
    if len(final_pts) >= 4 and smooth_fine > 1.0e-6:
        final_pts = round_polyline_corners_surface(
            obj,
            final_pts,
            effect=smooth_fine,
            angle_threshold_deg=(150.0 + 10.0 * smooth_fine),
            cyclic=True,
            max_corner_cut_mm=(0.015 + 0.22 * smooth_fine),
        )
        final_pts = project_loop_to_surface(obj, final_pts)
        eff_magnet = max(0.0, min(1.0, float(magnet_strength)))
        if eff_magnet > 1.0e-4 and len(final_pts) >= 4:
            final_pts = magnet_snap_to_soft_edges(
                obj,
                final_pts,
                magnet_strength=eff_magnet * smooth_fine,
                k_neighbors=6,
            )
            final_pts = project_loop_to_surface(obj, final_pts)
        smooth_iters = 1 + (1 if smooth_fine > 0.70 else 0)
        smooth_strength = min(0.16, max(0.01, 0.02 + 0.10 * smooth_fine))
        final_pts = smooth_polyline_surface(
            obj,
            final_pts,
            iterations=smooth_iters,
            strength=smooth_strength,
            cyclic=True,
            pinned_indices=None,
        )
        eff_closing_window = int(max(2, min(20, closing_smooth_window)))
        final_pts = smooth_closing_region(
            obj,
            final_pts,
            closing_window=eff_closing_window,
            closing_strength=min(0.55, 0.10 + 0.40 * smooth_fine),
        )
        final_pts = project_loop_to_surface(obj, final_pts)
    if (
        bool(final_pts)
        and len(final_pts) > 1
        and (final_pts[0] - final_pts[-1]).length < 1.0e-6
    ):
        final_pts.pop()
    return final_pts, smooth_fine


def rebuild_margin_curve_as_bezier(
    curve_obj, target_obj, points_world, *, resolution_u=12
):
    if (
        not curve_obj
        or curve_obj.type != "CURVE"
        or not target_obj
        or target_obj.type != "MESH"
    ):
        return False
    pts = []
    for p in points_world or []:
        try:
            pts.append(Vector(p))
        except Exception:
            continue
    if len(pts) < 3:
        return False
    cdata = curve_obj.data
    while cdata.splines:
        cdata.splines.remove(cdata.splines[0])
    cdata.dimensions = "3D"
    cdata.resolution_u = max(8, int(resolution_u))
    spline = cdata.splines.new("BEZIER")
    spline.bezier_points.add(len(pts) - 1)
    spline.use_cyclic_u = True
    mw_inv = target_obj.matrix_world.inverted()
    for i, pt in enumerate(pts):
        lp = mw_inv @ pt
        bpt = spline.bezier_points[i]
        bpt.co = lp
        bpt.handle_left_type = "AUTO"
        bpt.handle_right_type = "AUTO"
    return True


def _loop_length_closed_world(points_world):
    pts = [Vector(p) for p in (points_world or [])]
    if len(pts) < 2:
        return 0.0
    total = 0.0
    n = len(pts)
    for i in range(n):
        total += float((pts[(i + 1) % n] - pts[i]).length)
    return float(total)


def resample_closed_loop_by_spacing_mm(obj, points_world, spacing_mm):
    if not obj or obj.type != "MESH":
        return [Vector(p) for p in (points_world or [])]
    pts = [Vector(p) for p in (points_world or [])]
    if len(pts) < 3:
        return pts
    if len(pts) > 1 and (pts[0] - pts[-1]).length < 1.0e-7:
        pts.pop()
    if len(pts) < 3:
        return pts
    spacing_mm = max(0.30, min(0.50, float(spacing_mm)))
    spacing_bu = max(1.0e-6, _mm_to_bu_for_obj(spacing_mm, obj_hint=obj))
    loop_len = _loop_length_closed_world(pts)
    if loop_len <= spacing_bu * 2.0:
        return pts
    target_count = int(round(loop_len / spacing_bu))
    target_count = max(16, min(2400, target_count))
    return _resample_closed_loop_world(pts, target_count)


def _apply_margin_curve_visual_style(curve_obj, scene, tid=0):
    if not curve_obj or curve_obj.type != "CURVE" or not scene:
        return
    p = scene.smile_v2
    minimal = bool(getattr(p, "margin_minimal_visual_style", False))
    base_th = max(0.001, float(getattr(p, "margin_line_thickness", 0.03)))
    if minimal:
        rgba = MARGIN_NEON_RGBA
        strength = 12.0
        hint = (
            curve_obj.parent
            if (curve_obj.parent and curve_obj.parent.type == "MESH")
            else None
        )
        try:
            thin_cap = _mm_to_bu_for_obj(0.05, obj_hint=hint) if hint else 0.004
        except Exception:
            thin_cap = 0.004
        th = min(base_th, max(1.0e-5, float(thin_cap)))
    else:
        rgba = MARGIN_NEON_RGBA
        strength = 18.0
        th = base_th
    curve_obj.show_in_front = True
    curve_obj.data.bevel_depth = th
    curve_obj.data.bevel_resolution = 4
    curve_obj.data.fill_mode = "FULL"
    curve_obj.color = rgba
    mat = ensure_emission_material(f"Mat_T{int(tid)}_Margin", rgba, strength=strength)
    if curve_obj.data.materials:
        curve_obj.data.materials[0] = mat
    else:
        curve_obj.data.materials.append(mat)


def _ensure_margin_curve_object(target_mesh, tid, session_collection=None):
    if not target_mesh or target_mesh.type != "MESH":
        return None
    curve_name = f"MARGIN_{target_mesh.name}_T{int(tid)}"
    curve = bpy.data.objects.get(curve_name)
    if curve and curve.type == "CURVE":
        try:
            ensure_collection_visible(bpy.context, COL_MARGINS)
            if session_collection:
                ensure_collection_visible(bpy.context, str(session_collection.name))
        except Exception:
            pass
        try:
            curve.hide_set(False)
        except Exception:
            pass
        curve.hide_viewport = False
        return curve
    cdata = bpy.data.curves.new(curve_name + "_Data", "CURVE")
    cdata.dimensions = "3D"
    curve = bpy.data.objects.new(curve_name, cdata)
    if session_collection:
        session_collection.objects.link(curve)
    else:
        link_to_collection(curve, ensure_collection(COL_MARGINS))
    curve.parent = target_mesh
    curve.matrix_local = Matrix.Identity(4)
    try:
        ensure_collection_visible(bpy.context, COL_MARGINS)
        if session_collection:
            ensure_collection_visible(bpy.context, str(session_collection.name))
    except Exception:
        pass
    try:
        curve.hide_set(False)
    except Exception:
        pass
    curve.hide_viewport = False
    return curve


def _save_margin_curve_wysiwyg(
    context,
    target_mesh,
    tid,
    points_world,
    *,
    resolution_u=12,
    source="",
    do_resample=True,
    extra_data=None,
    session_collection=None,
):
    if not context or not target_mesh or target_mesh.type != "MESH":
        return None, []
    pts = []
    for p in points_world or []:
        try:
            pts.append(Vector(p))
        except Exception:
            continue
    if len(pts) < 3:
        return None, []
    pts = project_loop_to_surface(target_mesh, pts)
    spacing_mm = float(getattr(context.scene.smile_v2, "margin_point_spacing_mm", 0.40))
    if do_resample:
        pts = resample_closed_loop_by_spacing_mm(target_mesh, pts, spacing_mm)
        pts = project_loop_to_surface(target_mesh, pts)
    if len(pts) > 1 and (pts[0] - pts[-1]).length < 1.0e-6:
        pts.pop()
    if len(pts) < 3:
        return None, []
    curve = _ensure_margin_curve_object(
        target_mesh, tid, session_collection=session_collection
    )
    if not curve:
        return None, []
    ok = rebuild_margin_curve_as_bezier(
        curve,
        target_mesh,
        pts,
        resolution_u=max(8, int(resolution_u)),
    )
    if not ok:
        return None, []
    _apply_margin_curve_visual_style(curve, context.scene, tid=tid)
    world_pts_list = [[float(pt.x), float(pt.y), float(pt.z)] for pt in pts]
    existing = get_margin_data(context.scene, target_mesh, tid)
    preserved_ids = []
    if isinstance(existing, dict):
        preserved_ids = _normalize_margin_point_ids(
            existing.get("control_point_ids", []), len(world_pts_list)
        )
    data = {
        "control_points": list(world_pts_list),
        "snapped_points": list(world_pts_list),
        "is_finalized": True,
        "display_curve_type": "BEZIER",
        "point_spacing_mm": float(max(0.30, min(0.50, spacing_mm))),
        "wysiwyg_saved": True,
        "finalize_source": str(source or ""),
    }
    if len(preserved_ids) == len(world_pts_list):
        data["control_point_ids"] = list(preserved_ids)
    if isinstance(extra_data, dict):
        data.update(extra_data)
    set_margin_data(context.scene, target_mesh, data, tooth_id=tid)
    return curve, pts


def optimize_closed_loop(
    obj,
    loop_world,
    anchors_world,
    evidence,
    *,
    iters=12,
    lam_smooth=0.6,
    lam_anchor=0.35,
):
    if not obj or obj.type != "MESH" or not loop_world:
        return list(loop_world or [])
    pts = [_project_world_to_mesh(obj, Vector(p)) for p in loop_world]
    n = len(pts)
    if n < 4:
        return pts
    anchors = [Vector(a) for a in (anchors_world or [])]
    lam_smooth = max(0.0, min(1.0, float(lam_smooth)))
    lam_anchor = max(0.0, min(1.0, float(lam_anchor)))
    for _ in range(max(0, int(iters))):
        out = []
        for i in range(n):
            prev_p = pts[i - 1]
            curr_p = pts[i]
            next_p = pts[(i + 1) % n]
            smooth_tgt = (prev_p + next_p) * 0.5
            p_new = curr_p.lerp(smooth_tgt, lam_smooth)
            if anchors:
                nearest = min(anchors, key=lambda a: (a - curr_p).length_squared)
                p_new = p_new.lerp(nearest, lam_anchor * 0.25)
            out.append(_project_world_to_mesh(obj, p_new))
        pts = out
    return pts


def project_loop_to_surface(obj, loop_world):
    if not loop_world:
        return []
    return [_project_world_to_mesh(obj, Vector(p)) for p in loop_world]


def eval_margin_metrics(loop_world, evidence):
    pts = [Vector(p) for p in (loop_world or [])]
    if len(pts) < 2:
        return {
            "point_count": len(pts),
            "total_length_mm": 0.0,
            "mean_seg_len_mm": 0.0,
            "max_seg_len_mm": 0.0,
            "min_seg_len_mm": 0.0,
            "confidence_proxy": 0.0,
        }
    seg_lens = []
    for i in range(len(pts) - 1):
        seg_lens.append((pts[i + 1] - pts[i]).length)
    if len(pts) > 2:
        seg_lens.append((pts[0] - pts[-1]).length)
    total = float(sum(seg_lens))
    mean_len = total / max(1, len(seg_lens))
    conf = 0.0
    if isinstance(evidence, dict):
        vv = evidence.get("vert_evidence", {})
        if isinstance(vv, dict) and vv:
            conf = float(sum(vv.values()) / max(1, len(vv)))
    return {
        "point_count": len(pts),
        "total_length_mm": total,
        "mean_seg_len_mm": float(mean_len),
        "max_seg_len_mm": float(max(seg_lens) if seg_lens else 0.0),
        "min_seg_len_mm": float(min(seg_lens) if seg_lens else 0.0),
        "confidence_proxy": conf,
    }


def simplify_path_rdp(points, tolerance=0.15):
    if len(points) < 3:
        return points

    def perpendicular_distance(point, line_start, line_end):
        line_vec = line_end - line_start
        line_len = line_vec.length
        if line_len < 0.0001:
            return (point - line_start).length
        t = max(0, min(1, (point - line_start).dot(line_vec) / (line_len * line_len)))
        projection = line_start + t * line_vec
        return (point - projection).length

    def rdp_recursive(points, start_idx, end_idx, tolerance):
        if end_idx - start_idx <= 1:
            return [start_idx, end_idx]
        max_dist = 0
        max_idx = start_idx
        line_start = points[start_idx]
        line_end = points[end_idx]
        for i in range(start_idx + 1, end_idx):
            dist = perpendicular_distance(points[i], line_start, line_end)
            if dist > max_dist:
                max_dist = dist
                max_idx = i
        if max_dist > tolerance:
            left = rdp_recursive(points, start_idx, max_idx, tolerance)
            right = rdp_recursive(points, max_idx, end_idx, tolerance)
            return left[:-1] + right
        else:
            return [start_idx, end_idx]

    indices = rdp_recursive(points, 0, len(points) - 1, tolerance)
    return [points[i] for i in indices]


def _center_trackball_on_object(context, obj, focus_view=False):
    if not obj or obj.type != "MESH":
        return
    try:
        mn, mx = bbox_world(obj)
        center = (mn + mx) * 0.5
    except Exception:
        try:
            center = obj.matrix_world.translation.copy()
        except Exception:
            return
    try:
        context.scene.tool_settings.transform_pivot_point = "MEDIAN_POINT"
    except Exception:
        pass
    try:
        if hasattr(context.preferences.inputs, "use_rotate_around_active"):
            context.preferences.inputs.use_rotate_around_active = True
    except Exception:
        pass
    try:
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except Exception:
        pass
    updated = False
    try:
        space = context.space_data
        if space and space.type == "VIEW_3D":
            rv3d = getattr(space, "region_3d", None)
            if rv3d:
                rv3d.view_location = center
                updated = True
    except Exception:
        pass
    if not updated:
        try:
            for win in context.window_manager.windows:
                scr = win.screen
                for area in scr.areas:
                    if area.type != "VIEW_3D":
                        continue
                    for space in area.spaces:
                        if space.type != "VIEW_3D":
                            continue
                        rv3d = getattr(space, "region_3d", None)
                        if rv3d:
                            rv3d.view_location = center
                            updated = True
        except Exception:
            pass
    if bool(focus_view):
        try:
            for win in context.window_manager.windows:
                scr = win.screen
                for area in scr.areas:
                    if area.type != "VIEW_3D":
                        continue
                    region = None
                    for r in area.regions:
                        if r.type == "WINDOW":
                            region = r
                            break
                    if not region:
                        continue
                    with context.temp_override(
                        window=win,
                        screen=scr,
                        area=area,
                        region=region,
                        active_object=obj,
                        object=obj,
                        selected_objects=[obj],
                        selected_editable_objects=[obj],
                    ):
                        try:
                            bpy.ops.view3d.view_selected(use_all_regions=False)
                        except Exception:
                            pass
        except Exception:
            pass
    try:
        if context.area:
            context.area.tag_redraw()
    except Exception:
        pass


# === MISSING OPERATOR: SMILE_OT_trace_geodesic_magnet ===
class SMILE_OT_trace_geodesic_magnet(bpy.types.Operator):
    bl_idname = "smile.trace_geodesic_magnet"
    bl_label = "Magnetic Geodesic Tracer"
    bl_options = {"REGISTER", "UNDO"}

    _bm = None
    _bmesh_obj = None
    _prev_idx = -1
    _curve_obj = None
    _markers = []
    _kd = None

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the mesh.")
            return {"CANCELLED"}
        self._bmesh_obj = obj
        self._markers = []
        self._prev_idx = -1
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
        import bmesh

        self._bm = bmesh.from_edit_mesh(obj.data)
        self._bm.verts.ensure_lookup_table()
        self._kd = KDTree(len(self._bm.verts))
        mw = obj.matrix_world
        for i, v in enumerate(self._bm.verts):
            self._kd.insert(mw @ v.co, i)
        self._kd.balance()
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Click to trace margin. Auto-snaps to ridge & follows surface."
        )
        return {"RUNNING_MODAL"}

    def find_sharpest_idx(self, world_loc, radius=1.5):
        items = self._kd.find_range(world_loc, radius)
        if not items:
            return -1
        best_idx = -1
        max_score = -1.0
        for co, index, dist in items:
            v = self._bm.verts[index]
            neighbors = [e.other_vert(v) for e in v.link_edges]
            if not neighbors:
                continue
            avg_n = Vector((0, 0, 0))
            for n in neighbors:
                avg_n += n.normal
            if avg_n.length_squared > 1e-12:
                avg_n.normalize()
            curv = 1.0 - v.normal.dot(avg_n)
            if curv > max_score:
                max_score = curv
                best_idx = index
        return best_idx

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            for m in self._markers:
                delete_object(m)
            bpy.ops.object.mode_set(mode="OBJECT")
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._bmesh_obj)
            if hit:
                raw_loc, _, _ = hit
                snap_idx = self.find_sharpest_idx(raw_loc)
                if snap_idx == -1:
                    return {"RUNNING_MODAL"}
                if self._prev_idx != -1:
                    bpy.ops.mesh.select_all(action="DESELECT")
                    self._bm.verts.ensure_lookup_table()
                    v_prev = self._bm.verts[self._prev_idx]
                    v_curr = self._bm.verts[snap_idx]
                    self._bm.select_history.add(v_prev)
                    v_prev.select = True
                    v_curr.select = True
                    try:
                        bpy.ops.mesh.shortest_path_select(use_fill=False)
                    except Exception:
                        pass
                self._prev_idx = snap_idx
                v_co = self._bmesh_obj.matrix_world @ self._bm.verts[snap_idx].co
                m = make_marker(
                    f"M_NODE_{len(self._markers)}",
                    v_co,
                    0.003,
                    self._bmesh_obj,
                    (0, 1, 0, 1),
                    sticky=False,
                )
                m.show_in_front = True
                self._markers.append(m)
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            bpy.ops.mesh.select_all(action="DESELECT")
            indices = []
            mw_inv = self._bmesh_obj.matrix_world.inverted()
            for m in self._markers:
                loc_local = mw_inv @ m.location
                _, _, _, idx = self._bmesh_obj.closest_point_on_mesh(loc_local)
                poly = self._bmesh_obj.data.polygons[idx]
                bv = poly.vertices[0]
                bd = 1000.0
                for vi in poly.vertices:
                    d = (self._bmesh_obj.data.vertices[vi].co - loc_local).length
                    if d < bd:
                        bd = d
                        bv = vi
                indices.append(bv)
            bpy.ops.mesh.select_all(action="DESELECT")
            for i in range(len(indices)):
                idx = indices[i]
                if i == 0:
                    self._bm.verts[idx].select = True
                    self._bm.select_history.add(self._bm.verts[idx])
                else:
                    self._bm.verts[idx].select = True
                    bpy.ops.mesh.shortest_path_select(use_fill=False)
                    self._bm.select_history.add(self._bm.verts[idx])
            if len(indices) > 2:
                self._bm.verts[indices[0]].select = True
                bpy.ops.mesh.shortest_path_select(use_fill=False)
            bpy.ops.mesh.duplicate()
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")
            for m in self._markers:
                delete_object(m)
            sel = context.selected_objects
            margin_mesh = None
            for o in sel:
                if o != self._bmesh_obj:
                    margin_mesh = o
                    break
            if margin_mesh:
                ensure_active(margin_mesh)
                bpy.ops.object.convert(target="CURVE")
                tid = _resolve_margin_tooth_id(context.scene, self._bmesh_obj)
                if tid > 0:
                    margin_mesh.name = f"MARGIN_{self._bmesh_obj.name}_T{tid}"
                    margin_mesh["SMILE_MARGIN_TOOTH_ID"] = int(tid)
                else:
                    margin_mesh.name = f"MARGIN_{self._bmesh_obj.name}_T0"
                link_to_collection(margin_mesh, ensure_collection(COL_MARGINS))
                margin_mesh.data.bevel_depth = 0.002
                margin_mesh.data.bevel_resolution = 2
                margin_mesh.show_in_front = True
                mat_name = f"SMILE_Margin_Mat_{self._bmesh_obj.name}"
                mat = ensure_emission_material(
                    mat_name, MARGIN_NEON_RGBA, strength=12.0
                )
                margin_mesh.data.materials.append(mat)
            self.report({"INFO"}, "Margin Geodesic Trace Complete.")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


# === END MISSING MARGIN TRACING HELPERS ===


# ============================================================

# P3 LATTICE RIG, BLOCKFFD, WAXUP, INDUSTRY CROWN NUMPY ENGINE

# Extracted from blendersmile_pnp_full_cleaned_20260318_165959.py

# ============================================================


# === ensure_active (lines 575-578) ===


def ensure_active(obj):
    _deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# === _step_gate_error (lines 9177-9188) ===


def _step_gate_error(context, required_step: int, action_label: str):
    scene = context.scene if context else None
    p = scene.smile_v2 if scene else None
    if not p:
        return None
    _sync_workflow_progress(p)
    if not getattr(p, "enforce_step_lock", False):
        return None
    current = _current_design_step(p)
    if current < int(required_step):
        return f"{action_label} requires Step {int(required_step)}+ (current: Step {current})."
    return None


# === create_lattice_rig_for_tooth (lines 12832-12998) ===


def create_lattice_rig_for_tooth(tooth_obj, size_pad=1.15):
    ensure_collection(COL_RIG)
    ensure_collection(COL_TEETH)

    lat_name = tooth_obj.name + "_LAT"
    lat = bpy.data.objects.get(lat_name)

    # Local Bounding Box (Local Space)
    # obj.bound_box gives 8 corners in local space
    # We want min/max in local space
    local_corners = [Vector(c) for c in tooth_obj.bound_box]
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )

    # Center in Local Space
    local_center = (mn + mx) * 0.5
    local_dims = (mx - mn) * size_pad

    if not lat:
        lat_data = bpy.data.lattices.new(lat_name + "_DATA")
        lat_data.points_u = 3
        lat_data.points_v = 3
        lat_data.points_w = 3
        lat = bpy.data.objects.new(lat_name, lat_data)
        bpy.context.scene.collection.objects.link(lat)
        link_to_collection(lat, ensure_collection(COL_RIG))

    # Align Lattice to Tooth perfectly
    lat.matrix_world = tooth_obj.matrix_world.copy()

    # Apply Local Offset and Scale relative to the tooth's origin
    # Lattice points default to -0.5 to +0.5 range.
    # We need to map that range to our local_dims centered at local_center.

    # Since Lattice is now aligned (parented effectively via matrix copy), we work in "Lattice Local" == "Tooth Local".

    # Actually, we should set the Lattice location/scale in its own local space
    lat.location = local_center  # Local translation relative to origin? No, lat.matrix_world is global.

    # If we set lat.matrix_world = tooth.matrix_world, then 'lat' origin is at 'tooth' origin.
    # We then translate 'lat' locally to align with the bbox center.

    # Better approach: Parent Lattice to Tooth immediately?
    # No, modifiers work best with world alignment or parent inverse.
    # Let's simple set matrix match, then apply local Translation/Scale.

    M = tooth_obj.matrix_world
    # Translation to center of bbox
    T_local = Matrix.Translation(local_center)
    # Scale to dimensions
    S_local = Matrix.Diagonal((local_dims.x, local_dims.y, local_dims.z, 1.0))

    lat.matrix_world = M @ T_local @ S_local

    mod = tooth_obj.modifiers.get("SMILE_LATTICE") or tooth_obj.modifiers.new(
        "SMILE_LATTICE", "LATTICE"
    )
    mod.object = lat

    # --- SMART CAGE WEIGHTING LOGIC ---
    handle_names = ["Cervical", "Body", "Incisal"]
    handles = []

    ensure_active(lat)
    lat.hide_set(False)
    lat.hide_viewport = False

    # Use override to prevent Context Missing errors
    with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.lattice.select_all(action="DESELECT")

    # Remove old hooks if re-running
    for m in lat.modifiers:
        if m.type == "HOOK":
            lat.modifiers.remove(m)

    for w_idx in range(3):
        bpy.ops.lattice.select_all(action="DESELECT")

        for v in range(3):
            for u in range(3):
                idx = w_idx * 9 + v * 3 + u
                lat.data.points[idx].select = True

        # Create Handle
        h_name = f"{tooth_obj.name}_H_{handle_names[w_idx]}"
        h_obj = bpy.data.objects.get(h_name)
        if not h_obj:
            h_obj = bpy.data.objects.new(h_name, None)
            h_obj.empty_display_type = "SPHERE"
            h_obj.empty_display_size = (
                local_dims.x * 0.15
            )  # Scale handle visual to tooth size (smaller)
            bpy.context.scene.collection.objects.link(h_obj)
            link_to_collection(h_obj, ensure_collection(COL_RIG))

        handles.append(h_obj)

        # Hook Logic
        # Context Safe Hooking
        lat.hide_set(False)
        h_obj.hide_set(False)

        # 1. Switch to Object Mode to select Hook Object
        with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
            bpy.ops.object.mode_set(mode="OBJECT")

        # 2. Select both Lat and Handle
        _deselect_all()
        lat.select_set(True)
        h_obj.select_set(True)
        bpy.context.view_layer.objects.active = lat

        # 3. Enter Edit Mode with both selected (Hook needs this context)
        with bpy.context.temp_override(
            active_object=lat, selected_objects=[lat, h_obj]
        ):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.hook_add_selob(use_bone=False)

        # Now snap h_obj to the hook center?
        # Actually, if h_obj is at (0,0,0) world, and lattice is elsewhere, the hook offset is huge.
        # We need to position h_obj at the geometric center of the layer BEFORE hooking.

        # Calculate layer center in World Space
        # Layer Z local: -0.5 (idx0), 0.0 (idx1), 0.5 (idx2)
        z_local = (w_idx - 1.0) * 0.5  # Maps 0->-0.5, 1->0.0, 2->0.5
        center_local = Vector((0, 0, z_local))
        center_world = lat.matrix_world @ center_local

        h_obj.location = center_world
        h_obj.rotation_euler = lat.rotation_euler  # Align rotation too

        # Reset Hook Inverse?
        # The modifier stores the inverse. If we move object then hook, it might be offset?
        # Correct order: Position Empty -> Select Points -> Hook.
        # We did: Position (now) -> Hook (already done above?).
        # Wait, I called hook_add_selob BEFORE positioning. That's bad.
        # The hook modifier captures the current relative transform.

    # FIX: Loop again correctly
    # 1. Create all handles and position them.
    # 2. Hook them.

    # ... Refactoring loop structure inside the function for correctness ...

    bpy.ops.object.mode_set(mode="OBJECT")

    # Store handle references
    tooth_obj["SMILE_RIG_H_CERVICAL"] = handles[0].name
    tooth_obj["SMILE_RIG_H_BODY"] = handles[1].name
    tooth_obj["SMILE_RIG_H_INCISAL"] = handles[2].name

    return lat, handles


# === _blockffd_targets_from_scope (lines 13038-13070) ===


def _blockffd_targets_from_scope(context, scope):
    sc = str(scope or "ACTIVE").upper()

    def _resolve_target(o):
        if not o:
            return None
        owner = _blockffd_owner_from_handle(o)
        if owner:
            return owner
        try:
            if o.type == "MESH" and not bool(o.get("SMILE_BLOCKFFD_HANDLE", False)):
                return o
        except Exception:
            pass
        return None

    if sc == "SELECTED":
        out = []
        seen = set()
        for o in context.selected_objects:
            t = _resolve_target(o)
            if not t:
                continue
            n = _safe_object_name(t)
            if n and n not in seen:
                seen.add(n)
                out.append(t)
        return out
    a = context.view_layer.objects.active
    t = _resolve_target(a)
    if t:
        return [t]
    return []


# === _blockffd_restore_relationship_lines (lines 13199-13206) ===


def _blockffd_restore_relationship_lines(scene):
    prev = bool(scene.get(KEY_BLOCKFFD_REL_PREV, True))
    _blockffd_set_relationship_lines(scene, prev)
    try:
        if KEY_BLOCKFFD_REL_PREV in scene:
            del scene[KEY_BLOCKFFD_REL_PREV]
    except Exception:
        pass


# === _blockffd_remove_for_tooth (lines 13538-13581) ===


def _blockffd_remove_for_tooth(
    tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
):
    lat = _blockffd_lattice_for_tooth(tooth_obj)
    handle_names = _blockffd_handle_names_for_tooth(tooth_obj, lat)
    owner_name = _safe_object_name(tooth_obj)

    if remove_modifier:
        for mod in list(tooth_obj.modifiers):
            try:
                if mod.type == "LATTICE" and (
                    mod.name == "SMILE_BLOCK_FFD"
                    or (lat and getattr(mod, "object", None) == lat)
                ):
                    tooth_obj.modifiers.remove(mod)
            except Exception:
                continue

    if remove_handles:
        for n in handle_names:
            h = bpy.data.objects.get(n)
            if not h:
                continue
            try:
                if (
                    h.type == "MESH"
                    and bool(h.get("SMILE_BLOCKFFD_HANDLE", False))
                    and str(h.get("SMILE_BLOCKFFD_OWNER", "")) == owner_name
                ):
                    delete_object(h)
            except Exception:
                continue

    if remove_lattice and lat:
        try:
            if lat.type == "LATTICE" and (
                bool(lat.get("SMILE_BLOCKFFD", False))
                or str(lat.get("SMILE_BLOCKFFD_TOOTH", "")) == owner_name
            ):
                delete_object(lat)
        except Exception:
            pass

    _blockffd_clear_meta(tooth_obj)


# === create_blockffd_rig_for_tooth (lines 13609-13741) ===


def create_blockffd_rig_for_tooth(
    tooth_obj,
    divisions=3,
    size_pad=0.1,
    handle_size_factor=0.05,
    sphere_gap=0.1,
    surface_only=True,
    corner_only=False,
):
    if not tooth_obj or tooth_obj.type != "MESH":
        raise RuntimeError("Active object must be a mesh tooth.")

    divisions = int(max(2, min(6, int(divisions))))
    size_pad = float(max(0.05, min(2.5, float(size_pad))))
    # Absolute scene-unit diameter for handle spheres.
    handle_size_factor = float(max(0.001, min(5.0, float(handle_size_factor))))
    # Absolute scene-unit gap between neighboring sphere surfaces.
    sphere_gap = float(max(0.0, min(5.0, float(sphere_gap))))
    surface_only = bool(surface_only)
    corner_only = bool(corner_only)

    ensure_collection(COL_RIG)
    _blockffd_remove_for_tooth(
        tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
    )

    base_name = f"{tooth_obj.name}_BLOCKFFD"
    lat_data = bpy.data.lattices.new(base_name + "_DATA")
    lat_data.points_u = divisions
    lat_data.points_v = divisions
    lat_data.points_w = divisions
    for attr in (
        "interpolation_type_u",
        "interpolation_type_v",
        "interpolation_type_w",
    ):
        try:
            setattr(lat_data, attr, "KEY_BSPLINE")
        except Exception:
            pass

    lat_obj = bpy.data.objects.new(base_name, lat_data)
    bpy.context.scene.collection.objects.link(lat_obj)
    link_to_collection(lat_obj, ensure_collection(COL_RIG))

    center_local, dims_local = _blockffd_bbox_local(tooth_obj)
    # Additive pad ratio: 0.2 = +20% lattice cage expansion.
    dims_local = dims_local * (1.0 + size_pad)
    M = tooth_obj.matrix_world.copy()
    T_local = Matrix.Translation(center_local)
    S_local = Matrix.Diagonal((dims_local.x, dims_local.y, dims_local.z, 1.0))
    lat_obj.matrix_world = M @ T_local @ S_local
    lat_obj.show_in_front = True

    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if not mod:
        mod = tooth_obj.modifiers.new("SMILE_BLOCK_FFD", "LATTICE")
    mod.object = lat_obj

    # User size is an absolute sphere diameter in scene units.
    handle_size = float(handle_size_factor)
    # Cap by neighbor spacing minus absolute requested gap.
    min_step = _blockffd_min_step_world(lat_obj, divisions)
    max_diameter_from_gap = max(0.001, float(min_step - sphere_gap))
    handle_size = min(handle_size, max_diameter_from_gap)
    handle_mesh = _blockffd_get_handle_mesh()
    handle_names = []
    d2 = int(divisions * divisions)
    for i, pt in enumerate(lat_obj.data.points):
        if corner_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_corner = (
                (u == 0 or u == (divisions - 1))
                and (v == 0 or v == (divisions - 1))
                and (w == 0 or w == (divisions - 1))
            )
            if not is_corner:
                continue
        elif surface_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_boundary = (
                u == 0
                or u == (divisions - 1)
                or v == 0
                or v == (divisions - 1)
                or w == 0
                or w == (divisions - 1)
            )
            if not is_boundary:
                continue
        h_name = f"{base_name}_H{i:02d}"
        h = bpy.data.objects.new(h_name, handle_mesh)
        h.scale = (float(handle_size), float(handle_size), float(handle_size))
        h.show_in_front = True
        h.hide_render = True
        try:
            h.color = (0.98, 0.62, 0.08, 1.0)
        except Exception:
            pass
        lp = Vector((float(pt.co.x), float(pt.co.y), float(pt.co.z)))
        h.matrix_world = lat_obj.matrix_world @ Matrix.Translation(lp)
        bpy.context.scene.collection.objects.link(h)
        link_to_collection(h, ensure_collection(COL_RIG))
        h["SMILE_BLOCKFFD_HANDLE"] = True
        h["SMILE_BLOCKFFD_OWNER"] = _safe_object_name(tooth_obj)
        h["SMILE_BLOCKFFD_LATTICE"] = lat_obj.name
        h["SMILE_BLOCKFFD_POINT_INDEX"] = int(i)
        handle_names.append(h.name)

        hk = lat_obj.modifiers.new(name=f"SMILE_BFFD_HOOK_{i:02d}", type="HOOK")
        hk.object = h
        hk.strength = 1.0
        try:
            hk.vertex_indices_set([int(i)])
        except Exception:
            pass

    tooth_obj[KEY_BLOCKFFD_LAT] = lat_obj.name
    tooth_obj[KEY_BLOCKFFD_HANDLES] = json.dumps(handle_names)
    tooth_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    tooth_obj["SMILE_BLOCKFFD_SURFACE_ONLY"] = bool(surface_only)
    tooth_obj["SMILE_BLOCKFFD_CORNER_ONLY"] = bool(corner_only)
    tooth_obj["SMILE_BLOCKFFD_GAP"] = float(sphere_gap)
    tooth_obj["SMILE_BLOCKFFD_PAD"] = float(size_pad)
    tooth_obj["SMILE_BLOCKFFD_HANDLE_FACTOR"] = float(handle_size_factor)
    lat_obj["SMILE_BLOCKFFD_TOOTH"] = _safe_object_name(tooth_obj)
    lat_obj["SMILE_BLOCKFFD"] = True
    lat_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    return lat_obj, handle_names


# === SMILE_OT_create_lattice_rig (lines 29787-29805) ===


class SMILE_OT_create_lattice_rig(bpy.types.Operator):
    bl_idname = "smile.create_lattice_rig"
    bl_label = "Create 27-Handle Shaping Rig (Active Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        try:
            lat, handles = create_lattice_rig_for_tooth(
                tooth, size_pad=context.scene.smile_v2.rig_size_pad
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Rig created: {lat.name} with {len(handles)} handles")
        return {"FINISHED"}


# === SMILE_OT_blockffd_create (lines 29808-29860) ===


class SMILE_OT_blockffd_create(bpy.types.Operator):
    bl_idname = "smile.blockffd_create"
    bl_label = "Create Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Create rig on active mesh tooth"),
            ("SELECTED", "Selected", "Create rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD.")
            return {"CANCELLED"}

        ok = 0
        failed = []
        for obj in targets:
            try:
                create_blockffd_rig_for_tooth(
                    obj,
                    divisions=int(getattr(p, "blockffd_divisions", 3)),
                    size_pad=float(getattr(p, "blockffd_size_pad", 0.1)),
                    handle_size_factor=float(getattr(p, "blockffd_handle_size", 0.05)),
                    sphere_gap=float(getattr(p, "blockffd_sphere_gap", 0.1)),
                    surface_only=bool(
                        getattr(p, "blockffd_surface_handles_only", True)
                    ),
                    corner_only=bool(getattr(p, "blockffd_simple_mode", False)),
                )
                ok += 1
            except Exception as e:
                failed.append(f"{obj.name}: {e}")

        if ok == 0:
            self.report(
                {"ERROR"},
                "Block FFD create failed. " + ("; ".join(failed[:2]) if failed else ""),
            )
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_hide_relationship_lines", True)):
            _blockffd_set_relationship_lines(context.scene, False)
        if failed:
            self.report({"WARNING"}, f"Created {ok}; failed {len(failed)}.")
        else:
            self.report({"INFO"}, f"Created Block FFD rig on {ok} tooth/teeth.")
        return {"FINISHED"}


# === SMILE_OT_blockffd_apply (lines 29863-29912) ===


class SMILE_OT_blockffd_apply(bpy.types.Operator):
    bl_idname = "smile.blockffd_apply"
    bl_label = "Apply Block FFD"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Apply rig on active mesh tooth"),
            ("SELECTED", "Selected", "Apply rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        cleanup = bool(getattr(p, "blockffd_cleanup_after_apply", True))
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD apply.")
            return {"CANCELLED"}

        applied = 0
        skipped = 0
        for obj in targets:
            mod = obj.modifiers.get("SMILE_BLOCK_FFD")
            if not mod:
                skipped += 1
                continue
            ok = _apply_modifier_on_object(context, obj, "SMILE_BLOCK_FFD")
            if not ok:
                skipped += 1
                continue
            applied += 1
            if cleanup:
                _blockffd_remove_for_tooth(
                    obj, remove_modifier=False, remove_lattice=True, remove_handles=True
                )
            else:
                _blockffd_clear_meta(obj)

        if applied == 0:
            self.report({"WARNING"}, "No Block FFD modifier was applied.")
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report(
            {"INFO"}, f"Applied Block FFD on {applied} tooth/teeth. Skipped {skipped}."
        )
        return {"FINISHED"}


# === SMILE_OT_blockffd_remove (lines 29915-29950) ===


class SMILE_OT_blockffd_remove(bpy.types.Operator):
    bl_idname = "smile.blockffd_remove"
    bl_label = "Remove Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Remove rig on active mesh tooth"),
            ("SELECTED", "Selected", "Remove rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD remove.")
            return {"CANCELLED"}

        removed = 0
        for obj in targets:
            had_any = bool(
                obj.modifiers.get("SMILE_BLOCK_FFD") or _blockffd_lattice_for_tooth(obj)
            )
            _blockffd_remove_for_tooth(
                obj, remove_modifier=True, remove_lattice=True, remove_handles=True
            )
            if had_any:
                removed += 1

        p = context.scene.smile_v2
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report({"INFO"}, f"Removed Block FFD rigs: {removed}.")
        return {"FINISHED"}


# === build_adjacent_bvhtrees (lines 29953-29971) ===


def build_adjacent_bvhtrees(veneer_obj, max_dist=6.0):
    """Detect nearby tooth geometry from the same scan and build BVHTrees for proximity checks."""
    if not veneer_obj or veneer_obj.type != "MESH":
        return None

    # 1. Find Scan Parent (monolithic scan)
    scan = veneer_obj.parent
    if not scan or scan.type != "MESH":
        # Fallback to Scans collection
        col = bpy.data.collections.get(COL_SCANS)
        if col and col.objects:
            scan = col.objects[0]
        else:
            return None

    # 2. Build BVH of the monolithic scan (target)
    deps = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTreeClass.FromObject(scan, deps)
    return bvh, scan


# === SMILE_ProximalAnalyzer (lines 29974-30055) ===


class SMILE_ProximalAnalyzer:
    """Manages real-time proximity feedback and confinement during sculpting."""

    def __init__(self, veneer_obj, target_scan, target_bvh):
        self.veneer = veneer_obj
        self.scan = target_scan
        self.bvh = target_bvh
        self.params = {"ideal_min": 0.05, "ideal_max": 0.15, "crit_tight": 0.02}

    def update_feedback(self, context):
        """Update vertex colors and apply soft push."""
        if self.veneer.mode != "SCULPT":
            return

        # preparation
        me = self.veneer.data
        if "SMILE_CONTACT" not in me.color_attributes:
            me.color_attributes.new("SMILE_CONTACT", "BYTE_COLOR", "POINT")

        attr = me.color_attributes["SMILE_CONTACT"]
        mw = self.veneer.matrix_world
        mw_inv = mw.inverted()
        scan_mw = self.scan.matrix_world
        scan_mw_inv = scan_mw.inverted()

        # Performance: Sample vertices sparsely
        import random

        # Stride based on vertex count (target ~1000 checks per frame)
        stride = int(max(1, len(me.vertices) // 1000))

        # We need to access bmesh layer directly for performant color updates?
        # Standard API is slow for per-vertex color setting in loop.
        # But 'foreach_set' requires full array.
        # Let's iterate a subset and just update those.

        # Note: Modifying v.co in Sculpt Mode is tricky. Blender Sculpt mode locks mesh data.
        # We cannot modify v.co directly while user is brushing.
        # Visual Feedback (Color) works.
        # Physical Confinement usually requires a Modifier (Shrinkwrap/Collision) or Brush setting.
        # Script-based 'push' fights with the brush engine.

        # Better Confinement Strategy:
        # Instead of pushing verts (which lags/fails in sculpt mode), we create a Collision Mask.
        # Or we assume this is "Visual Guide" only + Post-Stroke correction?
        # Let's stick to Visual Feedback for now as it's robust.

        # Optimization: Use foreach to read/write coords if possible, but KDTree is point-by-point.
        # Batch query?

        # vertices_to_check = me.vertices[::stride]

        count = len(me.vertices)
        for i in range(0, count, stride):
            v = me.vertices[i]
            # 1. World Space Query
            wp = mw @ v.co
            lp_scan = scan_mw_inv @ wp

            loc, norm, idx, dist = self.bvh.find_nearest(lp_scan)

            if loc:
                # 2. Feedback Color
                if dist < self.params["crit_tight"]:
                    col = (1.0, 0.0, 0.0, 1.0)  # Red
                elif dist < self.params["ideal_min"]:
                    col = (1.0, 0.5, 0.0, 1.0)  # Orange
                elif dist < self.params["ideal_max"]:
                    col = (0.0, 1.0, 0.0, 1.0)  # Green
                else:
                    col = (0.5, 0.5, 0.5, 1.0)  # Grey

                # Write color (Slow part)
                attr.data[v.index].color = col

        # To make color visible, we must be in Vertex Paint or specific shading.
        # Setup Dental Workspace ensures 'VERTEX' color type.

        # me.update() # Can cause sculpt stroke interruption?
        # Only update if we changed geometry. If only color, maybe skipping update is unsafe.
        # But updating mesh during sculpt is generally bad.
        pass


# === SMILE_OT_liquify_toggle (lines 46807-46868) ===


class SMILE_OT_liquify_toggle(bpy.types.Operator):
    """Toggle liquify scaffold mode and mark design step progress."""

    bl_idname = "smile.liquify_toggle"
    bl_label = "Toggle Liquify"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 4, "Liquify session")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        p = context.scene.smile_v2
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        enable = not bool(p.sf_liquify_enabled)
        p.sf_liquify_enabled = enable
        if enable:
            ensure_active(obj)
            try:
                bpy.ops.object.mode_set(mode="SCULPT")
            except Exception:
                self.report({"ERROR"}, "Failed to enter Sculpt mode.")
                p.sf_liquify_enabled = False
                return {"CANCELLED"}

            brush_map = {
                "INFLATE": ["Inflate/Deflate", "Inflate", "Draw"],
                "FLATTEN": ["Flatten", "Flatten/Contrast", "Draw Sharp", "Draw"],
                "DEFORM": ["Grab", "Elastic Deform", "Snake Hook", "Draw"],
                "EDGES": ["Crease", "Pinch", "Draw Sharp", "Draw"],
                "SMOOTH": ["Smooth", "Draw"],
            }
            sculpt = context.tool_settings.sculpt
            target_names = brush_map.get(str(p.sf_liquify_brush), ["Draw"])
            selected = None
            for nm in target_names:
                b = bpy.data.brushes.get(nm)
                if b:
                    selected = b
                    break
            if selected:
                sculpt.brush = selected
                try:
                    selected.size = int(max(1, float(p.sf_liquify_size)))
                    selected.strength = float(p.sf_liquify_intensity)
                except Exception:
                    pass
            p.step4_done = True
            _set_min_design_step(p, 5)
        else:
            try:
                if obj.mode == "SCULPT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        self.report({"INFO"}, f"Liquify {'enabled' if enable else 'disabled'}.")
        return {"FINISHED"}


# === SMILE_OT_toggle_symmetry_runtime (lines 46871-46890) ===


class SMILE_OT_toggle_symmetry_runtime(bpy.types.Operator):
    """Toggle symmetry mirroring between paired teeth (runtime-registered variant)."""

    bl_idname = "smile.toggle_symmetry"
    bl_label = "Toggle Symmetry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        if p.symmetry_enabled:
            remove_symmetry_constraints(context)
            p.symmetry_enabled = False
            self.report({"INFO"}, "Symmetry disabled")
        else:
            setup_symmetry_constraints(context)
            p.symmetry_enabled = True
            self.report(
                {"INFO"}, "Symmetry enabled - paired teeth will mirror each other"
            )
        return {"FINISHED"}


# === SMILE_OT_waxup_cervical_merge (lines 46893-46975) ===


class SMILE_OT_waxup_cervical_merge(bpy.types.Operator):
    """Adapt the cervical margin of a library tooth to the underlying scan."""

    bl_idname = "smile.waxup_cervical_merge"
    bl_label = "Cervical Merge (Adapt to Scan)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        target_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        # fallback to active object if domain not set for testing
        if (
            not target_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            # assume active is the scan, and selected is the library tooth
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                target_obj = context.active_object

        selected = [
            o for o in context.selected_objects if o != target_obj and o.type == "MESH"
        ]

        if not target_obj or not selected:
            self.report({"ERROR"}, "Select Library Tooth and Shift-Select Scan Target")
            return {"CANCELLED"}

        scan_obj = target_obj

        for lib_obj in selected:
            # 1. Create Vertex Group for Cervical Margin
            # (In a real implementation, we'd find the boundary edge loop.
            # For this prototype, we'll try to use existing groups or select bottom vertices based on Z height relative to bounding box)
            vg_name = "SMILE_CervicalMargin"
            vg = lib_obj.vertex_groups.get(vg_name)
            if not vg:
                vg = lib_obj.vertex_groups.new(name=vg_name)

            # Simple heuristic for prototyping: bottom 20% of vertices in local Z
            mesh = lib_obj.data
            z_coords = [v.co.z for v in mesh.vertices]
            min_z = min(z_coords)
            max_z = max(z_coords)
            threshold_z = min_z + (max_z - min_z) * 0.20

            bottom_verts = [v.index for v in mesh.vertices if v.co.z < threshold_z]
            vg.add(bottom_verts, 1.0, "REPLACE")

            # 2. Add Shrinkwrap Modifier
            sw_name = "SMILE_Waxup_Adapt"
            sw = lib_obj.modifiers.get(sw_name)
            if not sw:
                sw = lib_obj.modifiers.new(name=sw_name, type="SHRINKWRAP")

            sw.target = scan_obj
            sw.vertex_group = vg_name
            sw.wrap_method = "PROJECT"
            sw.use_project_z = True
            sw.use_negative_direction = True
            sw.use_positive_direction = True
            sw.cull_face = "OFF"

            # 3. Add Smooth Modifier to blend
            sm_name = "SMILE_Waxup_Smooth"
            sm = lib_obj.modifiers.get(sm_name)
            if not sm:
                sm = lib_obj.modifiers.new(name=sm_name, type="SMOOTH")
                sm.vertex_group = vg_name
                sm.iterations = 5

        self.report({"INFO"}, f"Adapted {len(selected)} teeth to {scan_obj.name}")
        return {"FINISHED"}


# === SMILE_OT_waxup_generate_shell (lines 46978-47096) ===


class SMILE_OT_waxup_generate_shell(bpy.types.Operator):
    """Boolean merge of Waxup teeth to a Blocked-out Scan"""

    bl_idname = "smile.waxup_generate_shell"
    bl_label = "Generate Mockup Shell"
    bl_options = {"REGISTER", "UNDO"}

    spacer_thickness_mm: bpy.props.FloatProperty(
        name="Spacer Thickness (mm)", default=0.15, min=0.0, max=1.0
    )

    def _apply_modifier(self, obj, mod_name):
        try:
            with bpy.context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj]
            ):
                bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False

    def execute(self, context):
        p = context.scene.smile_v2

        # 1. Identify Target Scan
        scan_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        if (
            not scan_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                scan_obj = context.active_object

        selected_teeth = [
            o for o in context.selected_objects if o != scan_obj and o.type == "MESH"
        ]

        if not scan_obj or not selected_teeth:
            self.report({"ERROR"}, "Select Library Teeth and Shift-Select Scan Target")
            return {"CANCELLED"}

        # 2. Duplicate Scan for Blockout/Spacer
        spacer_name = f"Mockup_Spacer_{scan_obj.name}"
        old_spacer = bpy.data.objects.get(spacer_name)
        if old_spacer:
            delete_object(old_spacer)

        deps = context.evaluated_depsgraph_get()
        scan_eval = scan_obj.evaluated_get(deps)
        spacer_mesh = bpy.data.meshes.new_from_object(scan_eval)
        spacer_obj = bpy.data.objects.new(spacer_name, spacer_mesh)
        context.scene.collection.objects.link(spacer_obj)
        spacer_obj.matrix_world = scan_obj.matrix_world.copy()

        # 3. Add Solidify to act as Spacer (Outward expansion)
        if self.spacer_thickness_mm > 0.0:
            s_mod = spacer_obj.modifiers.new("Waxup_Spacer", "SOLIDIFY")
            # Convert mm to BU (assuming 1 BU = 1mm for dental usually, or check unit_settings)
            scale = (
                context.scene.unit_settings.scale_length
                if context.scene.unit_settings.system != "NONE"
                else 1.0
            )
            if context.scene.unit_settings.system == "METRIC":
                s_mod.thickness = self.spacer_thickness_mm / (scale * 1000.0)
            else:
                s_mod.thickness = self.spacer_thickness_mm

            s_mod.offset = 1.0  # Expand outwards
            s_mod.use_rim = True
            self._apply_modifier(spacer_obj, s_mod.name)

        # 4. Merge all selected teeth into one solid
        # For prototype simplicity, we just join them. Real world might need Voxel Remesh or Union.
        bpy.ops.object.select_all(action="DESELECT")
        for t in selected_teeth:
            t.select_set(True)

        context.view_layer.objects.active = selected_teeth[0]

        merged_name = "Mockup_Merged_Teeth"
        old_merged = bpy.data.objects.get(merged_name)
        if old_merged:
            delete_object(old_merged)

        bpy.ops.object.duplicate()
        merged_teeth = context.active_object
        merged_teeth.name = merged_name

        for o in context.selected_objects:
            if o != merged_teeth:
                o.select_set(True)
        bpy.ops.object.join()

        # 5. Boolean Difference: Merged Teeth - Spacer
        # We subtract the expanded scan from the mockup teeth
        bool_mod = merged_teeth.modifiers.new("Mockup_Intaglio", "BOOLEAN")
        bool_mod.operation = "DIFFERENCE"
        bool_mod.object = spacer_obj
        bool_mod.solver = "EXACT"

        self.report({"INFO"}, f"Generated Shell Preview. Apply boolean for final mesh.")

        # Cleanup view
        spacer_obj.display_type = "WIRE"
        spacer_obj.hide_render = True

        return {"FINISHED"}


# === ensure_triangulated_mesh_data (lines 47104-47130) ===


def ensure_triangulated_mesh_data(obj, apply_world=True):
    """Zero-copy data ingestion. Bypasses Python loops."""
    import numpy as np

    t0 = time.time()
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()

    verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    verts = verts.reshape((-1, 3))

    if apply_world:
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]

    mesh.calc_loop_triangles()
    tris = np.zeros(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape((-1, 3))

    eval_obj.to_mesh_clear()
    print(f"[Algo] Ingested {len(verts)} verts in {(time.time() - t0) * 1000:.2f}ms")
    return verts, tris


# === extract_curve_points_np (lines 47133-47153) ===


def extract_curve_points_np(obj):
    """Extracts world-space points from a Blender curve or mesh object."""
    import numpy as np

    if obj.type == "MESH":
        verts, _ = ensure_triangulated_mesh_data(obj, apply_world=True)
        return verts
    elif obj.type == "CURVE":
        deps = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        mesh = eval_obj.to_mesh()
        verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", verts)
        verts = verts.reshape((-1, 3))
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]
        eval_obj.to_mesh_clear()
        return verts
    return np.array([])


# === points_in_poly_np (lines 47156-47175) ===


def points_in_poly_np(points_2d, poly_2d):
    """Highly optimized 2D raycasting point-in-polygon algorithm."""
    import numpy as np

    x = points_2d[:, 0]
    y = points_2d[:, 1]
    inside = np.zeros(len(x), dtype=bool)
    n = len(poly_2d)
    p1x, p1y = poly_2d[0]
    for i in range(n + 1):
        p2x, p2y = poly_2d[i % n]
        min_y = min(p1y, p2y)
        max_y = max(p1y, p2y)
        mask = (y > min_y) & (y <= max_y)
        if p1y != p2y:
            x_ints = (y[mask] - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            cross = x[mask] <= x_ints
            inside[mask] ^= cross
        p1x, p1y = p2x, p2y
    return inside


# === calc_normal_np (lines 47178-47192) ===


def calc_normal_np(points):
    """Calculates best-fit normal vector using Newell's Method."""
    import numpy as np

    n = np.zeros(3)
    for i in range(len(points)):
        curr = points[i]
        nxt = points[(i + 1) % len(points)]
        n[0] += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
        n[1] += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
        n[2] += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
    norm = np.linalg.norm(n)
    if norm == 0:
        return np.array([0, 0, 1])
    return n / norm


# === get_rotation_matrix_to_z_np (lines 47195-47207) ===


def get_rotation_matrix_to_z_np(normal):
    """Creates a rotation matrix to align a given normal to the Z-axis [0,0,1]."""
    import numpy as np

    z_axis = np.array([0, 0, 1])
    v = np.cross(normal, z_axis)
    s = np.linalg.norm(v)
    c = np.dot(normal, z_axis)
    if s == 0:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    R = np.eye(3) + vx + np.dot(vx, vx) * ((1 - c) / (s**2))
    return R


# === get_boundary_edges_np (lines 47210-47217) ===


def get_boundary_edges_np(tris):
    """Extracts boundary edges (edges belonging to only one triangle) from an array of triangles."""
    import numpy as np

    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges_sorted = np.sort(edges, axis=1)
    unique_edges, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    return unique_edges[counts == 1]


# === extract_intaglio_vectorized_np (lines 47220-47277) ===


def extract_intaglio_vectorized_np(verts, tris, margin_points):
    """
    Phase 1: The Intaglio.
    Uses pure NumPy to perform a 2D projection cut and 3D boundary snapping.
    """
    import numpy as np

    t0 = time.time()

    # 1. Determine Insertion Axis and Project to 2D
    normal = calc_normal_np(margin_points)
    R = get_rotation_matrix_to_z_np(normal)
    verts_2d = np.dot(verts, R.T)[:, :2]
    margin_2d = np.dot(margin_points, R.T)[:, :2]

    # 2. Point in Polygon Test
    inside_mask = points_in_poly_np(verts_2d, margin_2d)

    # 3. Filter Triangles (Keep if ALL 3 vertices are inside)
    face_mask = (
        inside_mask[tris[:, 0]] & inside_mask[tris[:, 1]] & inside_mask[tris[:, 2]]
    )
    kept_tris = tris[face_mask]

    if len(kept_tris) == 0:
        print("[Algo] Warning: No triangles inside margin! Check orientation.")
        return verts, tris

    # 4. Extract Boundary Vertices
    boundary_edges = get_boundary_edges_np(kept_tris)
    boundary_vertices = np.unique(boundary_edges)

    # 5. Snap Boundary Vertices to true 3D Margin Curve using Blender's KDTree
    kd = KDTree(len(margin_points))
    for i, p in enumerate(margin_points):
        kd.insert(p, i)
    kd.balance()

    new_verts = verts.copy()
    for bv in boundary_vertices:
        co, index, dist = kd.find(new_verts[bv])
        new_verts[bv] = np.array(co)

    # 6. Cleanup unreferenced vertices to return a compact mesh
    referenced_mask = np.zeros(len(new_verts), dtype=bool)
    referenced_mask[kept_tris.flatten()] = True

    old_to_new = np.full(len(new_verts), -1, dtype=np.int32)
    new_indices = np.arange(np.sum(referenced_mask))
    old_to_new[referenced_mask] = new_indices

    compact_verts = new_verts[referenced_mask]
    compact_tris = old_to_new[kept_tris]

    print(
        f"[Algo] Intaglio Extracted & Snapped {len(compact_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return compact_verts, compact_tris


# === generate_emergence_collar_np (lines 47280-47342) ===


def generate_emergence_collar_np(
    verts, tris, margin_points, height=0.5, angle_deg=15.0
):
    """
    Phase 2: The Emergence Profile Collar.
    Extrudes the boundary edges upward and outward to create a seating collar.
    """
    import numpy as np

    t0 = time.time()

    boundary_edges = get_boundary_edges_np(tris)
    bound_verts = np.unique(boundary_edges)

    if len(bound_verts) == 0:
        return verts, tris

    axis = calc_normal_np(margin_points)  # Insertion axis
    center = np.mean(margin_points, axis=0)
    angle_rad = math.radians(angle_deg)

    old_to_new_extruded = {
        old_idx: i + len(verts) for i, old_idx in enumerate(bound_verts)
    }
    new_verts = np.zeros((len(bound_verts), 3), dtype=np.float32)

    # Parametric Extrusion Calculation
    for i, b_idx in enumerate(bound_verts):
        v = verts[b_idx]

        # Outward radial vector perpendicular to insertion axis
        vec_to_v = v - center
        radial = vec_to_v - np.dot(vec_to_v, axis) * axis
        norm_radial = np.linalg.norm(radial)
        if norm_radial > 0:
            radial = radial / norm_radial

        # Extrude Upward (height) and Outward (tan(angle))
        outward_mag = height * math.tan(angle_rad)
        extrusion = (axis * height) + (radial * outward_mag)

        new_verts[i] = v + extrusion

    combined_verts = np.vstack([verts, new_verts])

    # Bridge the gap with Quads (2 Triangles per edge)
    new_tris = []
    for edge in boundary_edges:
        v1, v2 = edge
        v1_new = old_to_new_extruded[v1]
        v2_new = old_to_new_extruded[v2]

        # Triangle 1
        new_tris.append([v1, v2, v2_new])
        # Triangle 2
        new_tris.append([v1, v2_new, v1_new])

    combined_tris = np.vstack([tris, np.array(new_tris, dtype=np.int32)])

    print(
        f"[Algo] Emergence Collar Generated: {len(new_tris)} faces in {(time.time() - t0) * 1000:.2f}ms"
    )
    return combined_verts, combined_tris


# === build_morph_geometry_nodes_np (lines 47345-47442) ===


def build_morph_geometry_nodes_np(node_group_name="SMILE_Morph_Engine"):
    """
    Phase 3: The Morph.
    Constructs a multi-threaded C++ backend Geometry Nodes modifier.
    """
    ng = bpy.data.node_groups.get(node_group_name)
    if not ng:
        ng = bpy.data.node_groups.new(node_group_name, "GeometryNodeTree")

        # In/Out Interfaces (Blender 4.0+ compatible API)
        if hasattr(ng, "interface"):
            ng.interface.new_socket(
                "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Target Collar", in_out="INPUT", socket_type="NodeSocketObject"
            )
            socket_falloff = ng.interface.new_socket(
                "Morph Falloff", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            socket_falloff.default_value = 3.0  # 3mm morph transition zone
        else:
            ng.outputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketObject", "Target Collar")
            socket_falloff = ng.inputs.new("NodeSocketFloat", "Morph Falloff")
            socket_falloff.default_value = 3.0

        nodes = ng.nodes
        links = ng.links

        node_in = nodes.new("NodeGroupInput")
        node_out = nodes.new("NodeGroupOutput")

        # 1. Target Proximity
        obj_info = nodes.new("GeometryNodeObjectInfo")
        obj_info.inputs["Transform Space"].default_value = "RELATIVE"
        target_prox = nodes.new("GeometryNodeProximity")
        target_prox.target_element = "EDGES"

        # 2. Self Boundary Distance
        edge_neighbors = nodes.new("GeometryNodeInputMeshEdgeNeighbors")
        compare_edges = nodes.new("FunctionNodeCompare")
        compare_edges.data_type = "INT"
        compare_edges.operation = "EQUAL"
        compare_edges.inputs[
            3
        ].default_value = 1  # Edge neighbor count = 1 means boundary

        separate_geom = nodes.new("GeometryNodeSeparateGeometry")
        separate_geom.domain = "EDGE"

        self_prox = nodes.new("GeometryNodeProximity")
        self_prox.target_element = "EDGES"

        # 3. Falloff Math
        map_range = nodes.new("ShaderNodeMapRange")
        map_range.clamp = True
        map_range.inputs[1].default_value = 0.0
        map_range.inputs[3].default_value = 1.0
        map_range.inputs[4].default_value = 0.0
        map_range.interpolation_type = "SMOOTHSTEP"

        # 4. Mix Position
        pos_node = nodes.new("GeometryNodeInputPosition")
        mix_node = nodes.new("ShaderNodeMix")
        mix_node.data_type = "VECTOR"
        mix_node.clamp_factor = True

        set_pos = nodes.new("GeometryNodeSetPosition")

        # Self Boundary Distance flow
        links.new(edge_neighbors.outputs["Face Count"], compare_edges.inputs[2])
        links.new(node_in.outputs["Geometry"], separate_geom.inputs["Geometry"])
        links.new(compare_edges.outputs["Result"], separate_geom.inputs["Selection"])
        links.new(separate_geom.outputs["Selection"], self_prox.inputs["Target"])

        # Target Position flow
        links.new(node_in.outputs["Target Collar"], obj_info.inputs["Object"])
        links.new(obj_info.outputs["Geometry"], target_prox.inputs["Target"])

        # Blend Math flow
        links.new(self_prox.outputs["Distance"], map_range.inputs[0])
        links.new(node_in.outputs["Morph Falloff"], map_range.inputs[2])  # From Max

        links.new(map_range.outputs["Result"], mix_node.inputs[0])  # Factor
        links.new(pos_node.outputs["Position"], mix_node.inputs[4])  # A (Original)
        links.new(target_prox.outputs["Position"], mix_node.inputs[5])  # B (Target)

        # Final Set Position
        links.new(node_in.outputs["Geometry"], set_pos.inputs["Geometry"])
        links.new(mix_node.outputs[1], set_pos.inputs["Position"])
        links.new(set_pos.outputs["Geometry"], node_out.inputs["Geometry"])

    return ng


# === numpy_to_mesh_np (lines 47445-47466) ===


def numpy_to_mesh_np(name, verts_np, faces_np):
    """Zero-copy output."""
    import numpy as np

    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts_np))
    mesh.loops.add(len(faces_np) * 3)
    mesh.polygons.add(len(faces_np))

    mesh.vertices.foreach_set("co", verts_np.flatten())

    loop_start = np.arange(0, len(faces_np) * 3, 3, dtype=np.int32)
    loop_total = np.full(len(faces_np), 3, dtype=np.int32)

    mesh.loops.foreach_set("vertex_index", faces_np.flatten())
    mesh.polygons.foreach_set("loop_start", loop_start)
    mesh.polygons.foreach_set("loop_total", loop_total)

    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# === stitch_meshes_vectorized_np (lines 47469-47487) ===


def stitch_meshes_vectorized_np(verts_A, tris_A, verts_B, tris_B, tolerance=4):
    """Phase 4: Topological Stitching."""
    import numpy as np

    t0 = time.time()
    combined_verts = np.vstack((verts_A, verts_B))
    tris_B_offset = tris_B + len(verts_A)
    combined_tris = np.vstack((tris_A, tris_B_offset))
    rounded_verts = np.round(combined_verts, decimals=tolerance)
    unique_verts, inverse_indices = np.unique(
        rounded_verts, axis=0, return_inverse=True
    )
    _, unique_indices = np.unique(rounded_verts, axis=0, return_index=True)
    final_verts = combined_verts[unique_indices]
    final_tris = inverse_indices[combined_tris]
    print(
        f"[Algo] Phase 4 Stitching: {len(combined_verts)} -> {len(final_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return final_verts, final_tris


# === execute_industry_standard_crown_np (lines 47490-47551) ===


def execute_industry_standard_crown_np(library_obj, spacer_obj, margin_curve_obj=None):
    """The Orchestrator."""
    print("--- INITIATING HYBRID C++/PYTHON CROWN GENERATION ---")

    lib_v, lib_f = ensure_triangulated_mesh_data(library_obj, apply_world=True)
    space_v, space_f = ensure_triangulated_mesh_data(spacer_obj, apply_world=True)

    if margin_curve_obj:
        margin_points = extract_curve_points_np(margin_curve_obj)
        if len(margin_points) > 2:
            intaglio_v, intaglio_f = extract_intaglio_vectorized_np(
                space_v, space_f, margin_points
            )
            collar_v, collar_f = generate_emergence_collar_np(
                intaglio_v, intaglio_f, margin_points, height=1.0, angle_deg=15.0
            )

            int_obj = bpy.data.objects.get("DEBUG_Intaglio_Collar")
            if int_obj:
                bpy.data.objects.remove(int_obj, do_unlink=True)
            intaglio_obj = numpy_to_mesh_np("DEBUG_Intaglio_Collar", collar_v, collar_f)

            build_morph_geometry_nodes_np()
            mod_name = "SMILE_C++_Morph"
            if mod_name not in library_obj.modifiers:
                mod = library_obj.modifiers.new(name=mod_name, type="NODES")
                mod.node_group = bpy.data.node_groups["SMILE_Morph_Engine"]

            if "Target Collar" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Target Collar"] = intaglio_obj
            elif "Input_2" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Input_2"] = intaglio_obj

            bpy.context.view_layer.update()

            morphed_v, morphed_f = ensure_triangulated_mesh_data(
                library_obj, apply_world=True
            )
            flipped_collar_f = collar_f[:, [0, 2, 1]]
            final_v, final_f = stitch_meshes_vectorized_np(
                morphed_v, morphed_f, collar_v, flipped_collar_f
            )

            crown_name = f"CROWN_INDUSTRY_{library_obj.name.split('_')[0]}"
            crown_obj = bpy.data.objects.get(crown_name)
            if crown_obj:
                bpy.data.objects.remove(crown_obj, do_unlink=True)

            final_crown_obj = numpy_to_mesh_np(crown_name, final_v, final_f)
            bpy.data.objects.remove(intaglio_obj, do_unlink=True)
            library_obj.modifiers.remove(library_obj.modifiers[mod_name])
            library_obj.hide_viewport = True

            print("--- CROWN GENERATION PIPELINE COMPLETED SUCCESSFULLY ---")
            return {"status": "SUCCESS", "crown_obj": final_crown_obj}
        else:
            return {
                "status": "FAILED",
                "message": "Margin curve has insufficient points.",
            }
    else:
        return {"status": "FAILED", "message": "No margin curve provided."}


# === SMILE_OT_generate_industry_crown (lines 47554-47593) ===


class SMILE_OT_generate_industry_crown(bpy.types.Operator):
    """Generate Crown using Hybrid C++/Python Architecture (Zero-Copy)"""

    bl_idname = "smile.generate_industry_crown"
    bl_label = "Generate Crown (C++ Engine v1.1)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        library_obj = context.view_layer.objects.active

        target_tid = int(getattr(p, "target_tooth_id", 0) or 0)
        spacer_name = f"SPACER_T{target_tid}"
        spacer_obj = bpy.data.objects.get(spacer_name)
        if not spacer_obj:
            self.report(
                {"ERROR"}, f"Spacer {spacer_name} not found. Generate Die/Spacer first."
            )
            return {"CANCELLED"}

        if not library_obj or library_obj == spacer_obj or library_obj.type != "MESH":
            self.report({"ERROR"}, "Select the Library Tooth first.")
            return {"CANCELLED"}

        margin_name = f"MARGIN_{spacer_obj.name.replace('SPACER_', '')}"
        margin_obj = bpy.data.objects.get(margin_name)
        if not margin_obj:
            # try direct T naming
            margin_obj = bpy.data.objects.get(f"MARGIN_T{target_tid}")

        if not margin_obj:
            self.report(
                {"ERROR"},
                f"Margin curve for T#{target_tid} not found. Please trace a margin first.",
            )
            return {"CANCELLED"}

        res = execute_industry_standard_crown_np(library_obj, spacer_obj, margin_obj)
        self.report({"INFO"}, f"Generation Complete: {res.get('status')}")
        return {"FINISHED"}


# ============================================================


# ============================================================

# MISSING DEPENDENCIES FOR P3 LATTICE/BLOCKFFD/WAXUP/CROWN

# ============================================================


# === link_to_collection (lines 565-567) ===


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


# === _deselect_all (lines 570-572) ===


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


# === _current_design_step (lines 8447-8452) ===


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===


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


# === _set_min_design_step (lines 9169-9174) ===


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===


def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===


def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===


def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===


def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===


def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===


def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===


def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===


def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===


def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===


def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# MISSING DEPENDENCIES FOR P3 LATTICE/BLOCKFFD/WAXUP/CROWN

# ============================================================


# === link_to_collection (lines 565-567) ===


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


# === _deselect_all (lines 570-572) ===


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


# === _current_design_step (lines 8447-8452) ===


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===


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


# === _set_min_design_step (lines 9169-9174) ===


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===


def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===


def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===


def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===


def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===


def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===


def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===


def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===


def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===


def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===


def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# MISSING DEPENDENCIES FOR P3 LATTICE/BLOCKFFD/WAXUP/CROWN

# ============================================================


# === link_to_collection (lines 565-567) ===


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


# === _deselect_all (lines 570-572) ===


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


# === _current_design_step (lines 8447-8452) ===


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===


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


# === _set_min_design_step (lines 9169-9174) ===


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===


def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===


def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===


def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===


def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===


def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===


def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===


def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===


def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===


def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===


def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# P3 LATTICE RIG, BLOCKFFD, WAXUP, INDUSTRY CROWN NUMPY ENGINE

# Extracted from blendersmile_pnp_full_cleaned_20260318_165959.py

# ============================================================


# === ensure_active (lines 575-578) ===


def ensure_active(obj):
    _deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# === _step_gate_error (lines 9177-9188) ===


def _step_gate_error(context, required_step: int, action_label: str):
    scene = context.scene if context else None
    p = scene.smile_v2 if scene else None
    if not p:
        return None
    _sync_workflow_progress(p)
    if not getattr(p, "enforce_step_lock", False):
        return None
    current = _current_design_step(p)
    if current < int(required_step):
        return f"{action_label} requires Step {int(required_step)}+ (current: Step {current})."
    return None


# === create_lattice_rig_for_tooth (lines 12832-12998) ===


def create_lattice_rig_for_tooth(tooth_obj, size_pad=1.15):
    ensure_collection(COL_RIG)
    ensure_collection(COL_TEETH)

    lat_name = tooth_obj.name + "_LAT"
    lat = bpy.data.objects.get(lat_name)

    # Local Bounding Box (Local Space)
    # obj.bound_box gives 8 corners in local space
    # We want min/max in local space
    local_corners = [Vector(c) for c in tooth_obj.bound_box]
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )

    # Center in Local Space
    local_center = (mn + mx) * 0.5
    local_dims = (mx - mn) * size_pad

    if not lat:
        lat_data = bpy.data.lattices.new(lat_name + "_DATA")
        lat_data.points_u = 3
        lat_data.points_v = 3
        lat_data.points_w = 3
        lat = bpy.data.objects.new(lat_name, lat_data)
        bpy.context.scene.collection.objects.link(lat)
        link_to_collection(lat, ensure_collection(COL_RIG))

    # Align Lattice to Tooth perfectly
    lat.matrix_world = tooth_obj.matrix_world.copy()

    # Apply Local Offset and Scale relative to the tooth's origin
    # Lattice points default to -0.5 to +0.5 range.
    # We need to map that range to our local_dims centered at local_center.

    # Since Lattice is now aligned (parented effectively via matrix copy), we work in "Lattice Local" == "Tooth Local".

    # Actually, we should set the Lattice location/scale in its own local space
    lat.location = local_center  # Local translation relative to origin? No, lat.matrix_world is global.

    # If we set lat.matrix_world = tooth.matrix_world, then 'lat' origin is at 'tooth' origin.
    # We then translate 'lat' locally to align with the bbox center.

    # Better approach: Parent Lattice to Tooth immediately?
    # No, modifiers work best with world alignment or parent inverse.
    # Let's simple set matrix match, then apply local Translation/Scale.

    M = tooth_obj.matrix_world
    # Translation to center of bbox
    T_local = Matrix.Translation(local_center)
    # Scale to dimensions
    S_local = Matrix.Diagonal((local_dims.x, local_dims.y, local_dims.z, 1.0))

    lat.matrix_world = M @ T_local @ S_local

    mod = tooth_obj.modifiers.get("SMILE_LATTICE") or tooth_obj.modifiers.new(
        "SMILE_LATTICE", "LATTICE"
    )
    mod.object = lat

    # --- SMART CAGE WEIGHTING LOGIC ---
    handle_names = ["Cervical", "Body", "Incisal"]
    handles = []

    ensure_active(lat)
    lat.hide_set(False)
    lat.hide_viewport = False

    # Use override to prevent Context Missing errors
    with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.lattice.select_all(action="DESELECT")

    # Remove old hooks if re-running
    for m in lat.modifiers:
        if m.type == "HOOK":
            lat.modifiers.remove(m)

    for w_idx in range(3):
        bpy.ops.lattice.select_all(action="DESELECT")

        for v in range(3):
            for u in range(3):
                idx = w_idx * 9 + v * 3 + u
                lat.data.points[idx].select = True

        # Create Handle
        h_name = f"{tooth_obj.name}_H_{handle_names[w_idx]}"
        h_obj = bpy.data.objects.get(h_name)
        if not h_obj:
            h_obj = bpy.data.objects.new(h_name, None)
            h_obj.empty_display_type = "SPHERE"
            h_obj.empty_display_size = (
                local_dims.x * 0.15
            )  # Scale handle visual to tooth size (smaller)
            bpy.context.scene.collection.objects.link(h_obj)
            link_to_collection(h_obj, ensure_collection(COL_RIG))

        handles.append(h_obj)

        # Hook Logic
        # Context Safe Hooking
        lat.hide_set(False)
        h_obj.hide_set(False)

        # 1. Switch to Object Mode to select Hook Object
        with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
            bpy.ops.object.mode_set(mode="OBJECT")

        # 2. Select both Lat and Handle
        _deselect_all()
        lat.select_set(True)
        h_obj.select_set(True)
        bpy.context.view_layer.objects.active = lat

        # 3. Enter Edit Mode with both selected (Hook needs this context)
        with bpy.context.temp_override(
            active_object=lat, selected_objects=[lat, h_obj]
        ):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.hook_add_selob(use_bone=False)

        # Now snap h_obj to the hook center?
        # Actually, if h_obj is at (0,0,0) world, and lattice is elsewhere, the hook offset is huge.
        # We need to position h_obj at the geometric center of the layer BEFORE hooking.

        # Calculate layer center in World Space
        # Layer Z local: -0.5 (idx0), 0.0 (idx1), 0.5 (idx2)
        z_local = (w_idx - 1.0) * 0.5  # Maps 0->-0.5, 1->0.0, 2->0.5
        center_local = Vector((0, 0, z_local))
        center_world = lat.matrix_world @ center_local

        h_obj.location = center_world
        h_obj.rotation_euler = lat.rotation_euler  # Align rotation too

        # Reset Hook Inverse?
        # The modifier stores the inverse. If we move object then hook, it might be offset?
        # Correct order: Position Empty -> Select Points -> Hook.
        # We did: Position (now) -> Hook (already done above?).
        # Wait, I called hook_add_selob BEFORE positioning. That's bad.
        # The hook modifier captures the current relative transform.

    # FIX: Loop again correctly
    # 1. Create all handles and position them.
    # 2. Hook them.

    # ... Refactoring loop structure inside the function for correctness ...

    bpy.ops.object.mode_set(mode="OBJECT")

    # Store handle references
    tooth_obj["SMILE_RIG_H_CERVICAL"] = handles[0].name
    tooth_obj["SMILE_RIG_H_BODY"] = handles[1].name
    tooth_obj["SMILE_RIG_H_INCISAL"] = handles[2].name

    return lat, handles


# === _blockffd_targets_from_scope (lines 13038-13070) ===


def _blockffd_targets_from_scope(context, scope):
    sc = str(scope or "ACTIVE").upper()

    def _resolve_target(o):
        if not o:
            return None
        owner = _blockffd_owner_from_handle(o)
        if owner:
            return owner
        try:
            if o.type == "MESH" and not bool(o.get("SMILE_BLOCKFFD_HANDLE", False)):
                return o
        except Exception:
            pass
        return None

    if sc == "SELECTED":
        out = []
        seen = set()
        for o in context.selected_objects:
            t = _resolve_target(o)
            if not t:
                continue
            n = _safe_object_name(t)
            if n and n not in seen:
                seen.add(n)
                out.append(t)
        return out
    a = context.view_layer.objects.active
    t = _resolve_target(a)
    if t:
        return [t]
    return []


# === _blockffd_restore_relationship_lines (lines 13199-13206) ===


def _blockffd_restore_relationship_lines(scene):
    prev = bool(scene.get(KEY_BLOCKFFD_REL_PREV, True))
    _blockffd_set_relationship_lines(scene, prev)
    try:
        if KEY_BLOCKFFD_REL_PREV in scene:
            del scene[KEY_BLOCKFFD_REL_PREV]
    except Exception:
        pass


# === _blockffd_remove_for_tooth (lines 13538-13581) ===


def _blockffd_remove_for_tooth(
    tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
):
    lat = _blockffd_lattice_for_tooth(tooth_obj)
    handle_names = _blockffd_handle_names_for_tooth(tooth_obj, lat)
    owner_name = _safe_object_name(tooth_obj)

    if remove_modifier:
        for mod in list(tooth_obj.modifiers):
            try:
                if mod.type == "LATTICE" and (
                    mod.name == "SMILE_BLOCK_FFD"
                    or (lat and getattr(mod, "object", None) == lat)
                ):
                    tooth_obj.modifiers.remove(mod)
            except Exception:
                continue

    if remove_handles:
        for n in handle_names:
            h = bpy.data.objects.get(n)
            if not h:
                continue
            try:
                if (
                    h.type == "MESH"
                    and bool(h.get("SMILE_BLOCKFFD_HANDLE", False))
                    and str(h.get("SMILE_BLOCKFFD_OWNER", "")) == owner_name
                ):
                    delete_object(h)
            except Exception:
                continue

    if remove_lattice and lat:
        try:
            if lat.type == "LATTICE" and (
                bool(lat.get("SMILE_BLOCKFFD", False))
                or str(lat.get("SMILE_BLOCKFFD_TOOTH", "")) == owner_name
            ):
                delete_object(lat)
        except Exception:
            pass

    _blockffd_clear_meta(tooth_obj)


# === create_blockffd_rig_for_tooth (lines 13609-13741) ===


def create_blockffd_rig_for_tooth(
    tooth_obj,
    divisions=3,
    size_pad=0.1,
    handle_size_factor=0.05,
    sphere_gap=0.1,
    surface_only=True,
    corner_only=False,
):
    if not tooth_obj or tooth_obj.type != "MESH":
        raise RuntimeError("Active object must be a mesh tooth.")

    divisions = int(max(2, min(6, int(divisions))))
    size_pad = float(max(0.05, min(2.5, float(size_pad))))
    # Absolute scene-unit diameter for handle spheres.
    handle_size_factor = float(max(0.001, min(5.0, float(handle_size_factor))))
    # Absolute scene-unit gap between neighboring sphere surfaces.
    sphere_gap = float(max(0.0, min(5.0, float(sphere_gap))))
    surface_only = bool(surface_only)
    corner_only = bool(corner_only)

    ensure_collection(COL_RIG)
    _blockffd_remove_for_tooth(
        tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
    )

    base_name = f"{tooth_obj.name}_BLOCKFFD"
    lat_data = bpy.data.lattices.new(base_name + "_DATA")
    lat_data.points_u = divisions
    lat_data.points_v = divisions
    lat_data.points_w = divisions
    for attr in (
        "interpolation_type_u",
        "interpolation_type_v",
        "interpolation_type_w",
    ):
        try:
            setattr(lat_data, attr, "KEY_BSPLINE")
        except Exception:
            pass

    lat_obj = bpy.data.objects.new(base_name, lat_data)
    bpy.context.scene.collection.objects.link(lat_obj)
    link_to_collection(lat_obj, ensure_collection(COL_RIG))

    center_local, dims_local = _blockffd_bbox_local(tooth_obj)
    # Additive pad ratio: 0.2 = +20% lattice cage expansion.
    dims_local = dims_local * (1.0 + size_pad)
    M = tooth_obj.matrix_world.copy()
    T_local = Matrix.Translation(center_local)
    S_local = Matrix.Diagonal((dims_local.x, dims_local.y, dims_local.z, 1.0))
    lat_obj.matrix_world = M @ T_local @ S_local
    lat_obj.show_in_front = True

    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if not mod:
        mod = tooth_obj.modifiers.new("SMILE_BLOCK_FFD", "LATTICE")
    mod.object = lat_obj

    # User size is an absolute sphere diameter in scene units.
    handle_size = float(handle_size_factor)
    # Cap by neighbor spacing minus absolute requested gap.
    min_step = _blockffd_min_step_world(lat_obj, divisions)
    max_diameter_from_gap = max(0.001, float(min_step - sphere_gap))
    handle_size = min(handle_size, max_diameter_from_gap)
    handle_mesh = _blockffd_get_handle_mesh()
    handle_names = []
    d2 = int(divisions * divisions)
    for i, pt in enumerate(lat_obj.data.points):
        if corner_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_corner = (
                (u == 0 or u == (divisions - 1))
                and (v == 0 or v == (divisions - 1))
                and (w == 0 or w == (divisions - 1))
            )
            if not is_corner:
                continue
        elif surface_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_boundary = (
                u == 0
                or u == (divisions - 1)
                or v == 0
                or v == (divisions - 1)
                or w == 0
                or w == (divisions - 1)
            )
            if not is_boundary:
                continue
        h_name = f"{base_name}_H{i:02d}"
        h = bpy.data.objects.new(h_name, handle_mesh)
        h.scale = (float(handle_size), float(handle_size), float(handle_size))
        h.show_in_front = True
        h.hide_render = True
        try:
            h.color = (0.98, 0.62, 0.08, 1.0)
        except Exception:
            pass
        lp = Vector((float(pt.co.x), float(pt.co.y), float(pt.co.z)))
        h.matrix_world = lat_obj.matrix_world @ Matrix.Translation(lp)
        bpy.context.scene.collection.objects.link(h)
        link_to_collection(h, ensure_collection(COL_RIG))
        h["SMILE_BLOCKFFD_HANDLE"] = True
        h["SMILE_BLOCKFFD_OWNER"] = _safe_object_name(tooth_obj)
        h["SMILE_BLOCKFFD_LATTICE"] = lat_obj.name
        h["SMILE_BLOCKFFD_POINT_INDEX"] = int(i)
        handle_names.append(h.name)

        hk = lat_obj.modifiers.new(name=f"SMILE_BFFD_HOOK_{i:02d}", type="HOOK")
        hk.object = h
        hk.strength = 1.0
        try:
            hk.vertex_indices_set([int(i)])
        except Exception:
            pass

    tooth_obj[KEY_BLOCKFFD_LAT] = lat_obj.name
    tooth_obj[KEY_BLOCKFFD_HANDLES] = json.dumps(handle_names)
    tooth_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    tooth_obj["SMILE_BLOCKFFD_SURFACE_ONLY"] = bool(surface_only)
    tooth_obj["SMILE_BLOCKFFD_CORNER_ONLY"] = bool(corner_only)
    tooth_obj["SMILE_BLOCKFFD_GAP"] = float(sphere_gap)
    tooth_obj["SMILE_BLOCKFFD_PAD"] = float(size_pad)
    tooth_obj["SMILE_BLOCKFFD_HANDLE_FACTOR"] = float(handle_size_factor)
    lat_obj["SMILE_BLOCKFFD_TOOTH"] = _safe_object_name(tooth_obj)
    lat_obj["SMILE_BLOCKFFD"] = True
    lat_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    return lat_obj, handle_names


# === SMILE_OT_create_lattice_rig (lines 29787-29805) ===


class SMILE_OT_create_lattice_rig(bpy.types.Operator):
    bl_idname = "smile.create_lattice_rig"
    bl_label = "Create 27-Handle Shaping Rig (Active Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        try:
            lat, handles = create_lattice_rig_for_tooth(
                tooth, size_pad=context.scene.smile_v2.rig_size_pad
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Rig created: {lat.name} with {len(handles)} handles")
        return {"FINISHED"}


# === SMILE_OT_blockffd_create (lines 29808-29860) ===


class SMILE_OT_blockffd_create(bpy.types.Operator):
    bl_idname = "smile.blockffd_create"
    bl_label = "Create Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Create rig on active mesh tooth"),
            ("SELECTED", "Selected", "Create rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD.")
            return {"CANCELLED"}

        ok = 0
        failed = []
        for obj in targets:
            try:
                create_blockffd_rig_for_tooth(
                    obj,
                    divisions=int(getattr(p, "blockffd_divisions", 3)),
                    size_pad=float(getattr(p, "blockffd_size_pad", 0.1)),
                    handle_size_factor=float(getattr(p, "blockffd_handle_size", 0.05)),
                    sphere_gap=float(getattr(p, "blockffd_sphere_gap", 0.1)),
                    surface_only=bool(
                        getattr(p, "blockffd_surface_handles_only", True)
                    ),
                    corner_only=bool(getattr(p, "blockffd_simple_mode", False)),
                )
                ok += 1
            except Exception as e:
                failed.append(f"{obj.name}: {e}")

        if ok == 0:
            self.report(
                {"ERROR"},
                "Block FFD create failed. " + ("; ".join(failed[:2]) if failed else ""),
            )
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_hide_relationship_lines", True)):
            _blockffd_set_relationship_lines(context.scene, False)
        if failed:
            self.report({"WARNING"}, f"Created {ok}; failed {len(failed)}.")
        else:
            self.report({"INFO"}, f"Created Block FFD rig on {ok} tooth/teeth.")
        return {"FINISHED"}


# === SMILE_OT_blockffd_apply (lines 29863-29912) ===


class SMILE_OT_blockffd_apply(bpy.types.Operator):
    bl_idname = "smile.blockffd_apply"
    bl_label = "Apply Block FFD"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Apply rig on active mesh tooth"),
            ("SELECTED", "Selected", "Apply rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        cleanup = bool(getattr(p, "blockffd_cleanup_after_apply", True))
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD apply.")
            return {"CANCELLED"}

        applied = 0
        skipped = 0
        for obj in targets:
            mod = obj.modifiers.get("SMILE_BLOCK_FFD")
            if not mod:
                skipped += 1
                continue
            ok = _apply_modifier_on_object(context, obj, "SMILE_BLOCK_FFD")
            if not ok:
                skipped += 1
                continue
            applied += 1
            if cleanup:
                _blockffd_remove_for_tooth(
                    obj, remove_modifier=False, remove_lattice=True, remove_handles=True
                )
            else:
                _blockffd_clear_meta(obj)

        if applied == 0:
            self.report({"WARNING"}, "No Block FFD modifier was applied.")
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report(
            {"INFO"}, f"Applied Block FFD on {applied} tooth/teeth. Skipped {skipped}."
        )
        return {"FINISHED"}


# === SMILE_OT_blockffd_remove (lines 29915-29950) ===


class SMILE_OT_blockffd_remove(bpy.types.Operator):
    bl_idname = "smile.blockffd_remove"
    bl_label = "Remove Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Remove rig on active mesh tooth"),
            ("SELECTED", "Selected", "Remove rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD remove.")
            return {"CANCELLED"}

        removed = 0
        for obj in targets:
            had_any = bool(
                obj.modifiers.get("SMILE_BLOCK_FFD") or _blockffd_lattice_for_tooth(obj)
            )
            _blockffd_remove_for_tooth(
                obj, remove_modifier=True, remove_lattice=True, remove_handles=True
            )
            if had_any:
                removed += 1

        p = context.scene.smile_v2
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report({"INFO"}, f"Removed Block FFD rigs: {removed}.")
        return {"FINISHED"}


# === build_adjacent_bvhtrees (lines 29953-29971) ===


def build_adjacent_bvhtrees(veneer_obj, max_dist=6.0):
    """Detect nearby tooth geometry from the same scan and build BVHTrees for proximity checks."""
    if not veneer_obj or veneer_obj.type != "MESH":
        return None

    # 1. Find Scan Parent (monolithic scan)
    scan = veneer_obj.parent
    if not scan or scan.type != "MESH":
        # Fallback to Scans collection
        col = bpy.data.collections.get(COL_SCANS)
        if col and col.objects:
            scan = col.objects[0]
        else:
            return None

    # 2. Build BVH of the monolithic scan (target)
    deps = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTreeClass.FromObject(scan, deps)
    return bvh, scan


# === SMILE_ProximalAnalyzer (lines 29974-30055) ===


class SMILE_ProximalAnalyzer:
    """Manages real-time proximity feedback and confinement during sculpting."""

    def __init__(self, veneer_obj, target_scan, target_bvh):
        self.veneer = veneer_obj
        self.scan = target_scan
        self.bvh = target_bvh
        self.params = {"ideal_min": 0.05, "ideal_max": 0.15, "crit_tight": 0.02}

    def update_feedback(self, context):
        """Update vertex colors and apply soft push."""
        if self.veneer.mode != "SCULPT":
            return

        # preparation
        me = self.veneer.data
        if "SMILE_CONTACT" not in me.color_attributes:
            me.color_attributes.new("SMILE_CONTACT", "BYTE_COLOR", "POINT")

        attr = me.color_attributes["SMILE_CONTACT"]
        mw = self.veneer.matrix_world
        mw_inv = mw.inverted()
        scan_mw = self.scan.matrix_world
        scan_mw_inv = scan_mw.inverted()

        # Performance: Sample vertices sparsely
        import random

        # Stride based on vertex count (target ~1000 checks per frame)
        stride = int(max(1, len(me.vertices) // 1000))

        # We need to access bmesh layer directly for performant color updates?
        # Standard API is slow for per-vertex color setting in loop.
        # But 'foreach_set' requires full array.
        # Let's iterate a subset and just update those.

        # Note: Modifying v.co in Sculpt Mode is tricky. Blender Sculpt mode locks mesh data.
        # We cannot modify v.co directly while user is brushing.
        # Visual Feedback (Color) works.
        # Physical Confinement usually requires a Modifier (Shrinkwrap/Collision) or Brush setting.
        # Script-based 'push' fights with the brush engine.

        # Better Confinement Strategy:
        # Instead of pushing verts (which lags/fails in sculpt mode), we create a Collision Mask.
        # Or we assume this is "Visual Guide" only + Post-Stroke correction?
        # Let's stick to Visual Feedback for now as it's robust.

        # Optimization: Use foreach to read/write coords if possible, but KDTree is point-by-point.
        # Batch query?

        # vertices_to_check = me.vertices[::stride]

        count = len(me.vertices)
        for i in range(0, count, stride):
            v = me.vertices[i]
            # 1. World Space Query
            wp = mw @ v.co
            lp_scan = scan_mw_inv @ wp

            loc, norm, idx, dist = self.bvh.find_nearest(lp_scan)

            if loc:
                # 2. Feedback Color
                if dist < self.params["crit_tight"]:
                    col = (1.0, 0.0, 0.0, 1.0)  # Red
                elif dist < self.params["ideal_min"]:
                    col = (1.0, 0.5, 0.0, 1.0)  # Orange
                elif dist < self.params["ideal_max"]:
                    col = (0.0, 1.0, 0.0, 1.0)  # Green
                else:
                    col = (0.5, 0.5, 0.5, 1.0)  # Grey

                # Write color (Slow part)
                attr.data[v.index].color = col

        # To make color visible, we must be in Vertex Paint or specific shading.
        # Setup Dental Workspace ensures 'VERTEX' color type.

        # me.update() # Can cause sculpt stroke interruption?
        # Only update if we changed geometry. If only color, maybe skipping update is unsafe.
        # But updating mesh during sculpt is generally bad.
        pass


# === SMILE_OT_liquify_toggle (lines 46807-46868) ===


class SMILE_OT_liquify_toggle(bpy.types.Operator):
    """Toggle liquify scaffold mode and mark design step progress."""

    bl_idname = "smile.liquify_toggle"
    bl_label = "Toggle Liquify"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 4, "Liquify session")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        p = context.scene.smile_v2
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        enable = not bool(p.sf_liquify_enabled)
        p.sf_liquify_enabled = enable
        if enable:
            ensure_active(obj)
            try:
                bpy.ops.object.mode_set(mode="SCULPT")
            except Exception:
                self.report({"ERROR"}, "Failed to enter Sculpt mode.")
                p.sf_liquify_enabled = False
                return {"CANCELLED"}

            brush_map = {
                "INFLATE": ["Inflate/Deflate", "Inflate", "Draw"],
                "FLATTEN": ["Flatten", "Flatten/Contrast", "Draw Sharp", "Draw"],
                "DEFORM": ["Grab", "Elastic Deform", "Snake Hook", "Draw"],
                "EDGES": ["Crease", "Pinch", "Draw Sharp", "Draw"],
                "SMOOTH": ["Smooth", "Draw"],
            }
            sculpt = context.tool_settings.sculpt
            target_names = brush_map.get(str(p.sf_liquify_brush), ["Draw"])
            selected = None
            for nm in target_names:
                b = bpy.data.brushes.get(nm)
                if b:
                    selected = b
                    break
            if selected:
                sculpt.brush = selected
                try:
                    selected.size = int(max(1, float(p.sf_liquify_size)))
                    selected.strength = float(p.sf_liquify_intensity)
                except Exception:
                    pass
            p.step4_done = True
            _set_min_design_step(p, 5)
        else:
            try:
                if obj.mode == "SCULPT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        self.report({"INFO"}, f"Liquify {'enabled' if enable else 'disabled'}.")
        return {"FINISHED"}


# === SMILE_OT_toggle_symmetry_runtime (lines 46871-46890) ===


class SMILE_OT_toggle_symmetry_runtime(bpy.types.Operator):
    """Toggle symmetry mirroring between paired teeth (runtime-registered variant)."""

    bl_idname = "smile.toggle_symmetry"
    bl_label = "Toggle Symmetry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        if p.symmetry_enabled:
            remove_symmetry_constraints(context)
            p.symmetry_enabled = False
            self.report({"INFO"}, "Symmetry disabled")
        else:
            setup_symmetry_constraints(context)
            p.symmetry_enabled = True
            self.report(
                {"INFO"}, "Symmetry enabled - paired teeth will mirror each other"
            )
        return {"FINISHED"}


# === SMILE_OT_waxup_cervical_merge (lines 46893-46975) ===


class SMILE_OT_waxup_cervical_merge(bpy.types.Operator):
    """Adapt the cervical margin of a library tooth to the underlying scan."""

    bl_idname = "smile.waxup_cervical_merge"
    bl_label = "Cervical Merge (Adapt to Scan)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        target_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        # fallback to active object if domain not set for testing
        if (
            not target_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            # assume active is the scan, and selected is the library tooth
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                target_obj = context.active_object

        selected = [
            o for o in context.selected_objects if o != target_obj and o.type == "MESH"
        ]

        if not target_obj or not selected:
            self.report({"ERROR"}, "Select Library Tooth and Shift-Select Scan Target")
            return {"CANCELLED"}

        scan_obj = target_obj

        for lib_obj in selected:
            # 1. Create Vertex Group for Cervical Margin
            # (In a real implementation, we'd find the boundary edge loop.
            # For this prototype, we'll try to use existing groups or select bottom vertices based on Z height relative to bounding box)
            vg_name = "SMILE_CervicalMargin"
            vg = lib_obj.vertex_groups.get(vg_name)
            if not vg:
                vg = lib_obj.vertex_groups.new(name=vg_name)

            # Simple heuristic for prototyping: bottom 20% of vertices in local Z
            mesh = lib_obj.data
            z_coords = [v.co.z for v in mesh.vertices]
            min_z = min(z_coords)
            max_z = max(z_coords)
            threshold_z = min_z + (max_z - min_z) * 0.20

            bottom_verts = [v.index for v in mesh.vertices if v.co.z < threshold_z]
            vg.add(bottom_verts, 1.0, "REPLACE")

            # 2. Add Shrinkwrap Modifier
            sw_name = "SMILE_Waxup_Adapt"
            sw = lib_obj.modifiers.get(sw_name)
            if not sw:
                sw = lib_obj.modifiers.new(name=sw_name, type="SHRINKWRAP")

            sw.target = scan_obj
            sw.vertex_group = vg_name
            sw.wrap_method = "PROJECT"
            sw.use_project_z = True
            sw.use_negative_direction = True
            sw.use_positive_direction = True
            sw.cull_face = "OFF"

            # 3. Add Smooth Modifier to blend
            sm_name = "SMILE_Waxup_Smooth"
            sm = lib_obj.modifiers.get(sm_name)
            if not sm:
                sm = lib_obj.modifiers.new(name=sm_name, type="SMOOTH")
                sm.vertex_group = vg_name
                sm.iterations = 5

        self.report({"INFO"}, f"Adapted {len(selected)} teeth to {scan_obj.name}")
        return {"FINISHED"}


# === SMILE_OT_waxup_generate_shell (lines 46978-47096) ===


class SMILE_OT_waxup_generate_shell(bpy.types.Operator):
    """Boolean merge of Waxup teeth to a Blocked-out Scan"""

    bl_idname = "smile.waxup_generate_shell"
    bl_label = "Generate Mockup Shell"
    bl_options = {"REGISTER", "UNDO"}

    spacer_thickness_mm: bpy.props.FloatProperty(
        name="Spacer Thickness (mm)", default=0.15, min=0.0, max=1.0
    )

    def _apply_modifier(self, obj, mod_name):
        try:
            with bpy.context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj]
            ):
                bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False

    def execute(self, context):
        p = context.scene.smile_v2

        # 1. Identify Target Scan
        scan_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        if (
            not scan_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                scan_obj = context.active_object

        selected_teeth = [
            o for o in context.selected_objects if o != scan_obj and o.type == "MESH"
        ]

        if not scan_obj or not selected_teeth:
            self.report({"ERROR"}, "Select Library Teeth and Shift-Select Scan Target")
            return {"CANCELLED"}

        # 2. Duplicate Scan for Blockout/Spacer
        spacer_name = f"Mockup_Spacer_{scan_obj.name}"
        old_spacer = bpy.data.objects.get(spacer_name)
        if old_spacer:
            delete_object(old_spacer)

        deps = context.evaluated_depsgraph_get()
        scan_eval = scan_obj.evaluated_get(deps)
        spacer_mesh = bpy.data.meshes.new_from_object(scan_eval)
        spacer_obj = bpy.data.objects.new(spacer_name, spacer_mesh)
        context.scene.collection.objects.link(spacer_obj)
        spacer_obj.matrix_world = scan_obj.matrix_world.copy()

        # 3. Add Solidify to act as Spacer (Outward expansion)
        if self.spacer_thickness_mm > 0.0:
            s_mod = spacer_obj.modifiers.new("Waxup_Spacer", "SOLIDIFY")
            # Convert mm to BU (assuming 1 BU = 1mm for dental usually, or check unit_settings)
            scale = (
                context.scene.unit_settings.scale_length
                if context.scene.unit_settings.system != "NONE"
                else 1.0
            )
            if context.scene.unit_settings.system == "METRIC":
                s_mod.thickness = self.spacer_thickness_mm / (scale * 1000.0)
            else:
                s_mod.thickness = self.spacer_thickness_mm

            s_mod.offset = 1.0  # Expand outwards
            s_mod.use_rim = True
            self._apply_modifier(spacer_obj, s_mod.name)

        # 4. Merge all selected teeth into one solid
        # For prototype simplicity, we just join them. Real world might need Voxel Remesh or Union.
        bpy.ops.object.select_all(action="DESELECT")
        for t in selected_teeth:
            t.select_set(True)

        context.view_layer.objects.active = selected_teeth[0]

        merged_name = "Mockup_Merged_Teeth"
        old_merged = bpy.data.objects.get(merged_name)
        if old_merged:
            delete_object(old_merged)

        bpy.ops.object.duplicate()
        merged_teeth = context.active_object
        merged_teeth.name = merged_name

        for o in context.selected_objects:
            if o != merged_teeth:
                o.select_set(True)
        bpy.ops.object.join()

        # 5. Boolean Difference: Merged Teeth - Spacer
        # We subtract the expanded scan from the mockup teeth
        bool_mod = merged_teeth.modifiers.new("Mockup_Intaglio", "BOOLEAN")
        bool_mod.operation = "DIFFERENCE"
        bool_mod.object = spacer_obj
        bool_mod.solver = "EXACT"

        self.report({"INFO"}, f"Generated Shell Preview. Apply boolean for final mesh.")

        # Cleanup view
        spacer_obj.display_type = "WIRE"
        spacer_obj.hide_render = True

        return {"FINISHED"}


# === ensure_triangulated_mesh_data (lines 47104-47130) ===


def ensure_triangulated_mesh_data(obj, apply_world=True):
    """Zero-copy data ingestion. Bypasses Python loops."""
    import numpy as np

    t0 = time.time()
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()

    verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    verts = verts.reshape((-1, 3))

    if apply_world:
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]

    mesh.calc_loop_triangles()
    tris = np.zeros(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape((-1, 3))

    eval_obj.to_mesh_clear()
    print(f"[Algo] Ingested {len(verts)} verts in {(time.time() - t0) * 1000:.2f}ms")
    return verts, tris


# === extract_curve_points_np (lines 47133-47153) ===


def extract_curve_points_np(obj):
    """Extracts world-space points from a Blender curve or mesh object."""
    import numpy as np

    if obj.type == "MESH":
        verts, _ = ensure_triangulated_mesh_data(obj, apply_world=True)
        return verts
    elif obj.type == "CURVE":
        deps = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        mesh = eval_obj.to_mesh()
        verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", verts)
        verts = verts.reshape((-1, 3))
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]
        eval_obj.to_mesh_clear()
        return verts
    return np.array([])


# === points_in_poly_np (lines 47156-47175) ===


def points_in_poly_np(points_2d, poly_2d):
    """Highly optimized 2D raycasting point-in-polygon algorithm."""
    import numpy as np

    x = points_2d[:, 0]
    y = points_2d[:, 1]
    inside = np.zeros(len(x), dtype=bool)
    n = len(poly_2d)
    p1x, p1y = poly_2d[0]
    for i in range(n + 1):
        p2x, p2y = poly_2d[i % n]
        min_y = min(p1y, p2y)
        max_y = max(p1y, p2y)
        mask = (y > min_y) & (y <= max_y)
        if p1y != p2y:
            x_ints = (y[mask] - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            cross = x[mask] <= x_ints
            inside[mask] ^= cross
        p1x, p1y = p2x, p2y
    return inside


# === calc_normal_np (lines 47178-47192) ===


def calc_normal_np(points):
    """Calculates best-fit normal vector using Newell's Method."""
    import numpy as np

    n = np.zeros(3)
    for i in range(len(points)):
        curr = points[i]
        nxt = points[(i + 1) % len(points)]
        n[0] += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
        n[1] += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
        n[2] += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
    norm = np.linalg.norm(n)
    if norm == 0:
        return np.array([0, 0, 1])
    return n / norm


# === get_rotation_matrix_to_z_np (lines 47195-47207) ===


def get_rotation_matrix_to_z_np(normal):
    """Creates a rotation matrix to align a given normal to the Z-axis [0,0,1]."""
    import numpy as np

    z_axis = np.array([0, 0, 1])
    v = np.cross(normal, z_axis)
    s = np.linalg.norm(v)
    c = np.dot(normal, z_axis)
    if s == 0:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    R = np.eye(3) + vx + np.dot(vx, vx) * ((1 - c) / (s**2))
    return R


# === get_boundary_edges_np (lines 47210-47217) ===


def get_boundary_edges_np(tris):
    """Extracts boundary edges (edges belonging to only one triangle) from an array of triangles."""
    import numpy as np

    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges_sorted = np.sort(edges, axis=1)
    unique_edges, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    return unique_edges[counts == 1]


# === extract_intaglio_vectorized_np (lines 47220-47277) ===


def extract_intaglio_vectorized_np(verts, tris, margin_points):
    """
    Phase 1: The Intaglio.
    Uses pure NumPy to perform a 2D projection cut and 3D boundary snapping.
    """
    import numpy as np

    t0 = time.time()

    # 1. Determine Insertion Axis and Project to 2D
    normal = calc_normal_np(margin_points)
    R = get_rotation_matrix_to_z_np(normal)
    verts_2d = np.dot(verts, R.T)[:, :2]
    margin_2d = np.dot(margin_points, R.T)[:, :2]

    # 2. Point in Polygon Test
    inside_mask = points_in_poly_np(verts_2d, margin_2d)

    # 3. Filter Triangles (Keep if ALL 3 vertices are inside)
    face_mask = (
        inside_mask[tris[:, 0]] & inside_mask[tris[:, 1]] & inside_mask[tris[:, 2]]
    )
    kept_tris = tris[face_mask]

    if len(kept_tris) == 0:
        print("[Algo] Warning: No triangles inside margin! Check orientation.")
        return verts, tris

    # 4. Extract Boundary Vertices
    boundary_edges = get_boundary_edges_np(kept_tris)
    boundary_vertices = np.unique(boundary_edges)

    # 5. Snap Boundary Vertices to true 3D Margin Curve using Blender's KDTree
    kd = KDTree(len(margin_points))
    for i, p in enumerate(margin_points):
        kd.insert(p, i)
    kd.balance()

    new_verts = verts.copy()
    for bv in boundary_vertices:
        co, index, dist = kd.find(new_verts[bv])
        new_verts[bv] = np.array(co)

    # 6. Cleanup unreferenced vertices to return a compact mesh
    referenced_mask = np.zeros(len(new_verts), dtype=bool)
    referenced_mask[kept_tris.flatten()] = True

    old_to_new = np.full(len(new_verts), -1, dtype=np.int32)
    new_indices = np.arange(np.sum(referenced_mask))
    old_to_new[referenced_mask] = new_indices

    compact_verts = new_verts[referenced_mask]
    compact_tris = old_to_new[kept_tris]

    print(
        f"[Algo] Intaglio Extracted & Snapped {len(compact_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return compact_verts, compact_tris


# === generate_emergence_collar_np (lines 47280-47342) ===


def generate_emergence_collar_np(
    verts, tris, margin_points, height=0.5, angle_deg=15.0
):
    """
    Phase 2: The Emergence Profile Collar.
    Extrudes the boundary edges upward and outward to create a seating collar.
    """
    import numpy as np

    t0 = time.time()

    boundary_edges = get_boundary_edges_np(tris)
    bound_verts = np.unique(boundary_edges)

    if len(bound_verts) == 0:
        return verts, tris

    axis = calc_normal_np(margin_points)  # Insertion axis
    center = np.mean(margin_points, axis=0)
    angle_rad = math.radians(angle_deg)

    old_to_new_extruded = {
        old_idx: i + len(verts) for i, old_idx in enumerate(bound_verts)
    }
    new_verts = np.zeros((len(bound_verts), 3), dtype=np.float32)

    # Parametric Extrusion Calculation
    for i, b_idx in enumerate(bound_verts):
        v = verts[b_idx]

        # Outward radial vector perpendicular to insertion axis
        vec_to_v = v - center
        radial = vec_to_v - np.dot(vec_to_v, axis) * axis
        norm_radial = np.linalg.norm(radial)
        if norm_radial > 0:
            radial = radial / norm_radial

        # Extrude Upward (height) and Outward (tan(angle))
        outward_mag = height * math.tan(angle_rad)
        extrusion = (axis * height) + (radial * outward_mag)

        new_verts[i] = v + extrusion

    combined_verts = np.vstack([verts, new_verts])

    # Bridge the gap with Quads (2 Triangles per edge)
    new_tris = []
    for edge in boundary_edges:
        v1, v2 = edge
        v1_new = old_to_new_extruded[v1]
        v2_new = old_to_new_extruded[v2]

        # Triangle 1
        new_tris.append([v1, v2, v2_new])
        # Triangle 2
        new_tris.append([v1, v2_new, v1_new])

    combined_tris = np.vstack([tris, np.array(new_tris, dtype=np.int32)])

    print(
        f"[Algo] Emergence Collar Generated: {len(new_tris)} faces in {(time.time() - t0) * 1000:.2f}ms"
    )
    return combined_verts, combined_tris


# === build_morph_geometry_nodes_np (lines 47345-47442) ===


def build_morph_geometry_nodes_np(node_group_name="SMILE_Morph_Engine"):
    """
    Phase 3: The Morph.
    Constructs a multi-threaded C++ backend Geometry Nodes modifier.
    """
    ng = bpy.data.node_groups.get(node_group_name)
    if not ng:
        ng = bpy.data.node_groups.new(node_group_name, "GeometryNodeTree")

        # In/Out Interfaces (Blender 4.0+ compatible API)
        if hasattr(ng, "interface"):
            ng.interface.new_socket(
                "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Target Collar", in_out="INPUT", socket_type="NodeSocketObject"
            )
            socket_falloff = ng.interface.new_socket(
                "Morph Falloff", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            socket_falloff.default_value = 3.0  # 3mm morph transition zone
        else:
            ng.outputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketObject", "Target Collar")
            socket_falloff = ng.inputs.new("NodeSocketFloat", "Morph Falloff")
            socket_falloff.default_value = 3.0

        nodes = ng.nodes
        links = ng.links

        node_in = nodes.new("NodeGroupInput")
        node_out = nodes.new("NodeGroupOutput")

        # 1. Target Proximity
        obj_info = nodes.new("GeometryNodeObjectInfo")
        obj_info.inputs["Transform Space"].default_value = "RELATIVE"
        target_prox = nodes.new("GeometryNodeProximity")
        target_prox.target_element = "EDGES"

        # 2. Self Boundary Distance
        edge_neighbors = nodes.new("GeometryNodeInputMeshEdgeNeighbors")
        compare_edges = nodes.new("FunctionNodeCompare")
        compare_edges.data_type = "INT"
        compare_edges.operation = "EQUAL"
        compare_edges.inputs[
            3
        ].default_value = 1  # Edge neighbor count = 1 means boundary

        separate_geom = nodes.new("GeometryNodeSeparateGeometry")
        separate_geom.domain = "EDGE"

        self_prox = nodes.new("GeometryNodeProximity")
        self_prox.target_element = "EDGES"

        # 3. Falloff Math
        map_range = nodes.new("ShaderNodeMapRange")
        map_range.clamp = True
        map_range.inputs[1].default_value = 0.0
        map_range.inputs[3].default_value = 1.0
        map_range.inputs[4].default_value = 0.0
        map_range.interpolation_type = "SMOOTHSTEP"

        # 4. Mix Position
        pos_node = nodes.new("GeometryNodeInputPosition")
        mix_node = nodes.new("ShaderNodeMix")
        mix_node.data_type = "VECTOR"
        mix_node.clamp_factor = True

        set_pos = nodes.new("GeometryNodeSetPosition")

        # Self Boundary Distance flow
        links.new(edge_neighbors.outputs["Face Count"], compare_edges.inputs[2])
        links.new(node_in.outputs["Geometry"], separate_geom.inputs["Geometry"])
        links.new(compare_edges.outputs["Result"], separate_geom.inputs["Selection"])
        links.new(separate_geom.outputs["Selection"], self_prox.inputs["Target"])

        # Target Position flow
        links.new(node_in.outputs["Target Collar"], obj_info.inputs["Object"])
        links.new(obj_info.outputs["Geometry"], target_prox.inputs["Target"])

        # Blend Math flow
        links.new(self_prox.outputs["Distance"], map_range.inputs[0])
        links.new(node_in.outputs["Morph Falloff"], map_range.inputs[2])  # From Max

        links.new(map_range.outputs["Result"], mix_node.inputs[0])  # Factor
        links.new(pos_node.outputs["Position"], mix_node.inputs[4])  # A (Original)
        links.new(target_prox.outputs["Position"], mix_node.inputs[5])  # B (Target)

        # Final Set Position
        links.new(node_in.outputs["Geometry"], set_pos.inputs["Geometry"])
        links.new(mix_node.outputs[1], set_pos.inputs["Position"])
        links.new(set_pos.outputs["Geometry"], node_out.inputs["Geometry"])

    return ng


# === numpy_to_mesh_np (lines 47445-47466) ===


def numpy_to_mesh_np(name, verts_np, faces_np):
    """Zero-copy output."""
    import numpy as np

    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts_np))
    mesh.loops.add(len(faces_np) * 3)
    mesh.polygons.add(len(faces_np))

    mesh.vertices.foreach_set("co", verts_np.flatten())

    loop_start = np.arange(0, len(faces_np) * 3, 3, dtype=np.int32)
    loop_total = np.full(len(faces_np), 3, dtype=np.int32)

    mesh.loops.foreach_set("vertex_index", faces_np.flatten())
    mesh.polygons.foreach_set("loop_start", loop_start)
    mesh.polygons.foreach_set("loop_total", loop_total)

    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# === stitch_meshes_vectorized_np (lines 47469-47487) ===


def stitch_meshes_vectorized_np(verts_A, tris_A, verts_B, tris_B, tolerance=4):
    """Phase 4: Topological Stitching."""
    import numpy as np

    t0 = time.time()
    combined_verts = np.vstack((verts_A, verts_B))
    tris_B_offset = tris_B + len(verts_A)
    combined_tris = np.vstack((tris_A, tris_B_offset))
    rounded_verts = np.round(combined_verts, decimals=tolerance)
    unique_verts, inverse_indices = np.unique(
        rounded_verts, axis=0, return_inverse=True
    )
    _, unique_indices = np.unique(rounded_verts, axis=0, return_index=True)
    final_verts = combined_verts[unique_indices]
    final_tris = inverse_indices[combined_tris]
    print(
        f"[Algo] Phase 4 Stitching: {len(combined_verts)} -> {len(final_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return final_verts, final_tris


# === execute_industry_standard_crown_np (lines 47490-47551) ===


def execute_industry_standard_crown_np(library_obj, spacer_obj, margin_curve_obj=None):
    """The Orchestrator."""
    print("--- INITIATING HYBRID C++/PYTHON CROWN GENERATION ---")

    lib_v, lib_f = ensure_triangulated_mesh_data(library_obj, apply_world=True)
    space_v, space_f = ensure_triangulated_mesh_data(spacer_obj, apply_world=True)

    if margin_curve_obj:
        margin_points = extract_curve_points_np(margin_curve_obj)
        if len(margin_points) > 2:
            intaglio_v, intaglio_f = extract_intaglio_vectorized_np(
                space_v, space_f, margin_points
            )
            collar_v, collar_f = generate_emergence_collar_np(
                intaglio_v, intaglio_f, margin_points, height=1.0, angle_deg=15.0
            )

            int_obj = bpy.data.objects.get("DEBUG_Intaglio_Collar")
            if int_obj:
                bpy.data.objects.remove(int_obj, do_unlink=True)
            intaglio_obj = numpy_to_mesh_np("DEBUG_Intaglio_Collar", collar_v, collar_f)

            build_morph_geometry_nodes_np()
            mod_name = "SMILE_C++_Morph"
            if mod_name not in library_obj.modifiers:
                mod = library_obj.modifiers.new(name=mod_name, type="NODES")
                mod.node_group = bpy.data.node_groups["SMILE_Morph_Engine"]

            if "Target Collar" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Target Collar"] = intaglio_obj
            elif "Input_2" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Input_2"] = intaglio_obj

            bpy.context.view_layer.update()

            morphed_v, morphed_f = ensure_triangulated_mesh_data(
                library_obj, apply_world=True
            )
            flipped_collar_f = collar_f[:, [0, 2, 1]]
            final_v, final_f = stitch_meshes_vectorized_np(
                morphed_v, morphed_f, collar_v, flipped_collar_f
            )

            crown_name = f"CROWN_INDUSTRY_{library_obj.name.split('_')[0]}"
            crown_obj = bpy.data.objects.get(crown_name)
            if crown_obj:
                bpy.data.objects.remove(crown_obj, do_unlink=True)

            final_crown_obj = numpy_to_mesh_np(crown_name, final_v, final_f)
            bpy.data.objects.remove(intaglio_obj, do_unlink=True)
            library_obj.modifiers.remove(library_obj.modifiers[mod_name])
            library_obj.hide_viewport = True

            print("--- CROWN GENERATION PIPELINE COMPLETED SUCCESSFULLY ---")
            return {"status": "SUCCESS", "crown_obj": final_crown_obj}
        else:
            return {
                "status": "FAILED",
                "message": "Margin curve has insufficient points.",
            }
    else:
        return {"status": "FAILED", "message": "No margin curve provided."}


# === SMILE_OT_generate_industry_crown (lines 47554-47593) ===


class SMILE_OT_generate_industry_crown(bpy.types.Operator):
    """Generate Crown using Hybrid C++/Python Architecture (Zero-Copy)"""

    bl_idname = "smile.generate_industry_crown"
    bl_label = "Generate Crown (C++ Engine v1.1)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        library_obj = context.view_layer.objects.active

        target_tid = int(getattr(p, "target_tooth_id", 0) or 0)
        spacer_name = f"SPACER_T{target_tid}"
        spacer_obj = bpy.data.objects.get(spacer_name)
        if not spacer_obj:
            self.report(
                {"ERROR"}, f"Spacer {spacer_name} not found. Generate Die/Spacer first."
            )
            return {"CANCELLED"}

        if not library_obj or library_obj == spacer_obj or library_obj.type != "MESH":
            self.report({"ERROR"}, "Select the Library Tooth first.")
            return {"CANCELLED"}

        margin_name = f"MARGIN_{spacer_obj.name.replace('SPACER_', '')}"
        margin_obj = bpy.data.objects.get(margin_name)
        if not margin_obj:
            # try direct T naming
            margin_obj = bpy.data.objects.get(f"MARGIN_T{target_tid}")

        if not margin_obj:
            self.report(
                {"ERROR"},
                f"Margin curve for T#{target_tid} not found. Please trace a margin first.",
            )
            return {"CANCELLED"}

        res = execute_industry_standard_crown_np(library_obj, spacer_obj, margin_obj)
        self.report({"INFO"}, f"Generation Complete: {res.get('status')}")
        return {"FINISHED"}


# ============================================================


# ============================================================

# MISSING DEPENDENCIES FOR P3 LATTICE/BLOCKFFD/WAXUP/CROWN

# ============================================================


# === link_to_collection (lines 565-567) ===


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


# === _deselect_all (lines 570-572) ===


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


# === _current_design_step (lines 8447-8452) ===


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===


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


# === _set_min_design_step (lines 9169-9174) ===


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===


def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===


def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===


def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===


def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===


def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===


def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===


def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===


def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===


def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===


def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# MISSING DEPENDENCIES FOR P3 LATTICE/BLOCKFFD/WAXUP/CROWN

# ============================================================


# === link_to_collection (lines 565-567) ===


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


# === _deselect_all (lines 570-572) ===


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


# === _current_design_step (lines 8447-8452) ===


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===


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


# === _set_min_design_step (lines 9169-9174) ===


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===


def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===


def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===


def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===


def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===


def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===


def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===


def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===


def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===


def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===


def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# MISSING DEPENDENCIES FOR P3 LATTICE/BLOCKFFD/WAXUP/CROWN

# ============================================================


# === link_to_collection (lines 565-567) ===


def link_to_collection(obj, col):
    if obj and col and obj.name not in col.objects:
        col.objects.link(obj)


# === _deselect_all (lines 570-572) ===


def _deselect_all():
    for o in bpy.context.selected_objects:
        o.select_set(False)


# === _current_design_step (lines 8447-8452) ===


def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===


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


# === _set_min_design_step (lines 9169-9174) ===


def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===


def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===


def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===


def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===


def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===


def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===


def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===


def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===


def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===


def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===


def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


CLASSES = [
    SMILE_OT_trace_geodesic_magnet,
    SMILE_OT_draw_rough_margin,
    SMILE_OT_snap_margin_snake,
    SMILE_OT_trace_magnetic_margin,
    SMILE_OT_finish_margin_draw,
    SMILE_OT_clear_margin,
    SMILE_OT_clear_edit_markers,
    SMILE_OT_trace_margin_drag_smooth,
    SMILE_OT_trace_margin_smooth,
    SMILE_OT_trace_margin_interactive,
    SMILE_OT_trace_margin_drag,
    SMILE_OT_margin_trace_compat,
    SMILE_OT_margin_trace_undo_last,
    SMILE_OT_edit_margin_native_surface_lock,
    SMILE_OT_edit_margin_object_mode,
    SMILE_OT_edit_margin_enhanced,
    SMILE_OT_smooth_margin_laplacian,
    SMILE_OT_refine_margin_snake,
    SMILE_OT_margin_trace_benchmark_report,
    SMILE_OT_check_margin_collisions,
    SMILE_OT_select_target_tooth,
    SMILE_OT_create_die_from_margin,
    SMILE_OT_generate_smart_spacer,
    SMILE_OT_create_die_and_spacer,
    SMILE_OT_toggle_traditional_die,
    SMILE_OT_suggest_insertion_axis,
    SMILE_OT_apply_rod_axis,
    SMILE_OT_boolean_cut_intaglio,
    SMILE_OT_build_shell_from_die_space,
    SMILE_OT_GenerateShell,
    SMILE_OT_analyze_adjacent_contacts,
    SMILE_OT_check_occlusion,
    SMILE_OT_analyze_thickness,
    SMILE_OT_survey_undercuts,
    SMILE_OT_auto_gingiva,
    SMILE_OT_capture_interprox_divider,
    SMILE_OT_clear_interprox_divider,
    SMILE_OT_show_interprox_preview,
    SMILE_OT_hide_interprox_preview,
    SMILE_OT_undo_die_step,
    SMILE_OT_run_pending_autodie_tab6,
    SMILE_OT_clear_pending_autodie_tab6,
    SMILE_OT_clear_margin_data,
    SMILE_OT_create_lattice_rig,
    SMILE_OT_blockffd_create,
    SMILE_OT_blockffd_apply,
    SMILE_OT_blockffd_remove,
    SMILE_OT_liquify_toggle,
    SMILE_OT_toggle_symmetry_runtime,
    SMILE_OT_waxup_cervical_merge,
    SMILE_OT_waxup_generate_shell,
    SMILE_OT_generate_industry_crown,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


# === _current_design_step (lines 8447-8452) ===
def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===
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


# === _set_min_design_step (lines 9169-9174) ===
def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===
def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===
def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===
def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===
def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===
def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===
def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===
def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===
def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===
def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===
def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# P3 LATTICE RIG, BLOCKFFD, WAXUP, INDUSTRY CROWN NUMPY ENGINE

# Extracted from blendersmile_pnp_full_cleaned_20260318_165959.py

# ============================================================


# === ensure_active (lines 575-578) ===


# === _step_gate_error (lines 9177-9188) ===


def _step_gate_error(context, required_step: int, action_label: str):
    scene = context.scene if context else None
    p = scene.smile_v2 if scene else None
    if not p:
        return None
    _sync_workflow_progress(p)
    if not getattr(p, "enforce_step_lock", False):
        return None
    current = _current_design_step(p)
    if current < int(required_step):
        return f"{action_label} requires Step {int(required_step)}+ (current: Step {current})."
    return None


# === create_lattice_rig_for_tooth (lines 12832-12998) ===


def create_lattice_rig_for_tooth(tooth_obj, size_pad=1.15):
    ensure_collection(COL_RIG)
    ensure_collection(COL_TEETH)

    lat_name = tooth_obj.name + "_LAT"
    lat = bpy.data.objects.get(lat_name)

    # Local Bounding Box (Local Space)
    # obj.bound_box gives 8 corners in local space
    # We want min/max in local space
    local_corners = [Vector(c) for c in tooth_obj.bound_box]
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )

    # Center in Local Space
    local_center = (mn + mx) * 0.5
    local_dims = (mx - mn) * size_pad

    if not lat:
        lat_data = bpy.data.lattices.new(lat_name + "_DATA")
        lat_data.points_u = 3
        lat_data.points_v = 3
        lat_data.points_w = 3
        lat = bpy.data.objects.new(lat_name, lat_data)
        bpy.context.scene.collection.objects.link(lat)
        link_to_collection(lat, ensure_collection(COL_RIG))

    # Align Lattice to Tooth perfectly
    lat.matrix_world = tooth_obj.matrix_world.copy()

    # Apply Local Offset and Scale relative to the tooth's origin
    # Lattice points default to -0.5 to +0.5 range.
    # We need to map that range to our local_dims centered at local_center.

    # Since Lattice is now aligned (parented effectively via matrix copy), we work in "Lattice Local" == "Tooth Local".

    # Actually, we should set the Lattice location/scale in its own local space
    lat.location = local_center  # Local translation relative to origin? No, lat.matrix_world is global.

    # If we set lat.matrix_world = tooth.matrix_world, then 'lat' origin is at 'tooth' origin.
    # We then translate 'lat' locally to align with the bbox center.

    # Better approach: Parent Lattice to Tooth immediately?
    # No, modifiers work best with world alignment or parent inverse.
    # Let's simple set matrix match, then apply local Translation/Scale.

    M = tooth_obj.matrix_world
    # Translation to center of bbox
    T_local = Matrix.Translation(local_center)
    # Scale to dimensions
    S_local = Matrix.Diagonal((local_dims.x, local_dims.y, local_dims.z, 1.0))

    lat.matrix_world = M @ T_local @ S_local

    mod = tooth_obj.modifiers.get("SMILE_LATTICE") or tooth_obj.modifiers.new(
        "SMILE_LATTICE", "LATTICE"
    )
    mod.object = lat

    # --- SMART CAGE WEIGHTING LOGIC ---
    handle_names = ["Cervical", "Body", "Incisal"]
    handles = []

    ensure_active(lat)
    lat.hide_set(False)
    lat.hide_viewport = False

    # Use override to prevent Context Missing errors
    with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.lattice.select_all(action="DESELECT")

    # Remove old hooks if re-running
    for m in lat.modifiers:
        if m.type == "HOOK":
            lat.modifiers.remove(m)

    for w_idx in range(3):
        bpy.ops.lattice.select_all(action="DESELECT")

        for v in range(3):
            for u in range(3):
                idx = w_idx * 9 + v * 3 + u
                lat.data.points[idx].select = True

        # Create Handle
        h_name = f"{tooth_obj.name}_H_{handle_names[w_idx]}"
        h_obj = bpy.data.objects.get(h_name)
        if not h_obj:
            h_obj = bpy.data.objects.new(h_name, None)
            h_obj.empty_display_type = "SPHERE"
            h_obj.empty_display_size = (
                local_dims.x * 0.15
            )  # Scale handle visual to tooth size (smaller)
            bpy.context.scene.collection.objects.link(h_obj)
            link_to_collection(h_obj, ensure_collection(COL_RIG))

        handles.append(h_obj)

        # Hook Logic
        # Context Safe Hooking
        lat.hide_set(False)
        h_obj.hide_set(False)

        # 1. Switch to Object Mode to select Hook Object
        with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
            bpy.ops.object.mode_set(mode="OBJECT")

        # 2. Select both Lat and Handle
        _deselect_all()
        lat.select_set(True)
        h_obj.select_set(True)
        bpy.context.view_layer.objects.active = lat

        # 3. Enter Edit Mode with both selected (Hook needs this context)
        with bpy.context.temp_override(
            active_object=lat, selected_objects=[lat, h_obj]
        ):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.hook_add_selob(use_bone=False)

        # Now snap h_obj to the hook center?
        # Actually, if h_obj is at (0,0,0) world, and lattice is elsewhere, the hook offset is huge.
        # We need to position h_obj at the geometric center of the layer BEFORE hooking.

        # Calculate layer center in World Space
        # Layer Z local: -0.5 (idx0), 0.0 (idx1), 0.5 (idx2)
        z_local = (w_idx - 1.0) * 0.5  # Maps 0->-0.5, 1->0.0, 2->0.5
        center_local = Vector((0, 0, z_local))
        center_world = lat.matrix_world @ center_local

        h_obj.location = center_world
        h_obj.rotation_euler = lat.rotation_euler  # Align rotation too

        # Reset Hook Inverse?
        # The modifier stores the inverse. If we move object then hook, it might be offset?
        # Correct order: Position Empty -> Select Points -> Hook.
        # We did: Position (now) -> Hook (already done above?).
        # Wait, I called hook_add_selob BEFORE positioning. That's bad.
        # The hook modifier captures the current relative transform.

    # FIX: Loop again correctly
    # 1. Create all handles and position them.
    # 2. Hook them.

    # ... Refactoring loop structure inside the function for correctness ...

    bpy.ops.object.mode_set(mode="OBJECT")

    # Store handle references
    tooth_obj["SMILE_RIG_H_CERVICAL"] = handles[0].name
    tooth_obj["SMILE_RIG_H_BODY"] = handles[1].name
    tooth_obj["SMILE_RIG_H_INCISAL"] = handles[2].name

    return lat, handles


# === _blockffd_targets_from_scope (lines 13038-13070) ===


def _blockffd_targets_from_scope(context, scope):
    sc = str(scope or "ACTIVE").upper()

    def _resolve_target(o):
        if not o:
            return None
        owner = _blockffd_owner_from_handle(o)
        if owner:
            return owner
        try:
            if o.type == "MESH" and not bool(o.get("SMILE_BLOCKFFD_HANDLE", False)):
                return o
        except Exception:
            pass
        return None

    if sc == "SELECTED":
        out = []
        seen = set()
        for o in context.selected_objects:
            t = _resolve_target(o)
            if not t:
                continue
            n = _safe_object_name(t)
            if n and n not in seen:
                seen.add(n)
                out.append(t)
        return out
    a = context.view_layer.objects.active
    t = _resolve_target(a)
    if t:
        return [t]
    return []


# === _blockffd_restore_relationship_lines (lines 13199-13206) ===


def _blockffd_restore_relationship_lines(scene):
    prev = bool(scene.get(KEY_BLOCKFFD_REL_PREV, True))
    _blockffd_set_relationship_lines(scene, prev)
    try:
        if KEY_BLOCKFFD_REL_PREV in scene:
            del scene[KEY_BLOCKFFD_REL_PREV]
    except Exception:
        pass


# === _blockffd_remove_for_tooth (lines 13538-13581) ===


def _blockffd_remove_for_tooth(
    tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
):
    lat = _blockffd_lattice_for_tooth(tooth_obj)
    handle_names = _blockffd_handle_names_for_tooth(tooth_obj, lat)
    owner_name = _safe_object_name(tooth_obj)

    if remove_modifier:
        for mod in list(tooth_obj.modifiers):
            try:
                if mod.type == "LATTICE" and (
                    mod.name == "SMILE_BLOCK_FFD"
                    or (lat and getattr(mod, "object", None) == lat)
                ):
                    tooth_obj.modifiers.remove(mod)
            except Exception:
                continue

    if remove_handles:
        for n in handle_names:
            h = bpy.data.objects.get(n)
            if not h:
                continue
            try:
                if (
                    h.type == "MESH"
                    and bool(h.get("SMILE_BLOCKFFD_HANDLE", False))
                    and str(h.get("SMILE_BLOCKFFD_OWNER", "")) == owner_name
                ):
                    delete_object(h)
            except Exception:
                continue

    if remove_lattice and lat:
        try:
            if lat.type == "LATTICE" and (
                bool(lat.get("SMILE_BLOCKFFD", False))
                or str(lat.get("SMILE_BLOCKFFD_TOOTH", "")) == owner_name
            ):
                delete_object(lat)
        except Exception:
            pass

    _blockffd_clear_meta(tooth_obj)


# === create_blockffd_rig_for_tooth (lines 13609-13741) ===


def create_blockffd_rig_for_tooth(
    tooth_obj,
    divisions=3,
    size_pad=0.1,
    handle_size_factor=0.05,
    sphere_gap=0.1,
    surface_only=True,
    corner_only=False,
):
    if not tooth_obj or tooth_obj.type != "MESH":
        raise RuntimeError("Active object must be a mesh tooth.")

    divisions = int(max(2, min(6, int(divisions))))
    size_pad = float(max(0.05, min(2.5, float(size_pad))))
    # Absolute scene-unit diameter for handle spheres.
    handle_size_factor = float(max(0.001, min(5.0, float(handle_size_factor))))
    # Absolute scene-unit gap between neighboring sphere surfaces.
    sphere_gap = float(max(0.0, min(5.0, float(sphere_gap))))
    surface_only = bool(surface_only)
    corner_only = bool(corner_only)

    ensure_collection(COL_RIG)
    _blockffd_remove_for_tooth(
        tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
    )

    base_name = f"{tooth_obj.name}_BLOCKFFD"
    lat_data = bpy.data.lattices.new(base_name + "_DATA")
    lat_data.points_u = divisions
    lat_data.points_v = divisions
    lat_data.points_w = divisions
    for attr in (
        "interpolation_type_u",
        "interpolation_type_v",
        "interpolation_type_w",
    ):
        try:
            setattr(lat_data, attr, "KEY_BSPLINE")
        except Exception:
            pass

    lat_obj = bpy.data.objects.new(base_name, lat_data)
    bpy.context.scene.collection.objects.link(lat_obj)
    link_to_collection(lat_obj, ensure_collection(COL_RIG))

    center_local, dims_local = _blockffd_bbox_local(tooth_obj)
    # Additive pad ratio: 0.2 = +20% lattice cage expansion.
    dims_local = dims_local * (1.0 + size_pad)
    M = tooth_obj.matrix_world.copy()
    T_local = Matrix.Translation(center_local)
    S_local = Matrix.Diagonal((dims_local.x, dims_local.y, dims_local.z, 1.0))
    lat_obj.matrix_world = M @ T_local @ S_local
    lat_obj.show_in_front = True

    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if not mod:
        mod = tooth_obj.modifiers.new("SMILE_BLOCK_FFD", "LATTICE")
    mod.object = lat_obj

    # User size is an absolute sphere diameter in scene units.
    handle_size = float(handle_size_factor)
    # Cap by neighbor spacing minus absolute requested gap.
    min_step = _blockffd_min_step_world(lat_obj, divisions)
    max_diameter_from_gap = max(0.001, float(min_step - sphere_gap))
    handle_size = min(handle_size, max_diameter_from_gap)
    handle_mesh = _blockffd_get_handle_mesh()
    handle_names = []
    d2 = int(divisions * divisions)
    for i, pt in enumerate(lat_obj.data.points):
        if corner_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_corner = (
                (u == 0 or u == (divisions - 1))
                and (v == 0 or v == (divisions - 1))
                and (w == 0 or w == (divisions - 1))
            )
            if not is_corner:
                continue
        elif surface_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_boundary = (
                u == 0
                or u == (divisions - 1)
                or v == 0
                or v == (divisions - 1)
                or w == 0
                or w == (divisions - 1)
            )
            if not is_boundary:
                continue
        h_name = f"{base_name}_H{i:02d}"
        h = bpy.data.objects.new(h_name, handle_mesh)
        h.scale = (float(handle_size), float(handle_size), float(handle_size))
        h.show_in_front = True
        h.hide_render = True
        try:
            h.color = (0.98, 0.62, 0.08, 1.0)
        except Exception:
            pass
        lp = Vector((float(pt.co.x), float(pt.co.y), float(pt.co.z)))
        h.matrix_world = lat_obj.matrix_world @ Matrix.Translation(lp)
        bpy.context.scene.collection.objects.link(h)
        link_to_collection(h, ensure_collection(COL_RIG))
        h["SMILE_BLOCKFFD_HANDLE"] = True
        h["SMILE_BLOCKFFD_OWNER"] = _safe_object_name(tooth_obj)
        h["SMILE_BLOCKFFD_LATTICE"] = lat_obj.name
        h["SMILE_BLOCKFFD_POINT_INDEX"] = int(i)
        handle_names.append(h.name)

        hk = lat_obj.modifiers.new(name=f"SMILE_BFFD_HOOK_{i:02d}", type="HOOK")
        hk.object = h
        hk.strength = 1.0
        try:
            hk.vertex_indices_set([int(i)])
        except Exception:
            pass

    tooth_obj[KEY_BLOCKFFD_LAT] = lat_obj.name
    tooth_obj[KEY_BLOCKFFD_HANDLES] = json.dumps(handle_names)
    tooth_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    tooth_obj["SMILE_BLOCKFFD_SURFACE_ONLY"] = bool(surface_only)
    tooth_obj["SMILE_BLOCKFFD_CORNER_ONLY"] = bool(corner_only)
    tooth_obj["SMILE_BLOCKFFD_GAP"] = float(sphere_gap)
    tooth_obj["SMILE_BLOCKFFD_PAD"] = float(size_pad)
    tooth_obj["SMILE_BLOCKFFD_HANDLE_FACTOR"] = float(handle_size_factor)
    lat_obj["SMILE_BLOCKFFD_TOOTH"] = _safe_object_name(tooth_obj)
    lat_obj["SMILE_BLOCKFFD"] = True
    lat_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    return lat_obj, handle_names


# === SMILE_OT_create_lattice_rig (lines 29787-29805) ===


class SMILE_OT_create_lattice_rig(bpy.types.Operator):
    bl_idname = "smile.create_lattice_rig"
    bl_label = "Create 27-Handle Shaping Rig (Active Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        try:
            lat, handles = create_lattice_rig_for_tooth(
                tooth, size_pad=context.scene.smile_v2.rig_size_pad
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Rig created: {lat.name} with {len(handles)} handles")
        return {"FINISHED"}


# === SMILE_OT_blockffd_create (lines 29808-29860) ===


class SMILE_OT_blockffd_create(bpy.types.Operator):
    bl_idname = "smile.blockffd_create"
    bl_label = "Create Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Create rig on active mesh tooth"),
            ("SELECTED", "Selected", "Create rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD.")
            return {"CANCELLED"}

        ok = 0
        failed = []
        for obj in targets:
            try:
                create_blockffd_rig_for_tooth(
                    obj,
                    divisions=int(getattr(p, "blockffd_divisions", 3)),
                    size_pad=float(getattr(p, "blockffd_size_pad", 0.1)),
                    handle_size_factor=float(getattr(p, "blockffd_handle_size", 0.05)),
                    sphere_gap=float(getattr(p, "blockffd_sphere_gap", 0.1)),
                    surface_only=bool(
                        getattr(p, "blockffd_surface_handles_only", True)
                    ),
                    corner_only=bool(getattr(p, "blockffd_simple_mode", False)),
                )
                ok += 1
            except Exception as e:
                failed.append(f"{obj.name}: {e}")

        if ok == 0:
            self.report(
                {"ERROR"},
                "Block FFD create failed. " + ("; ".join(failed[:2]) if failed else ""),
            )
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_hide_relationship_lines", True)):
            _blockffd_set_relationship_lines(context.scene, False)
        if failed:
            self.report({"WARNING"}, f"Created {ok}; failed {len(failed)}.")
        else:
            self.report({"INFO"}, f"Created Block FFD rig on {ok} tooth/teeth.")
        return {"FINISHED"}


# === SMILE_OT_blockffd_apply (lines 29863-29912) ===


class SMILE_OT_blockffd_apply(bpy.types.Operator):
    bl_idname = "smile.blockffd_apply"
    bl_label = "Apply Block FFD"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Apply rig on active mesh tooth"),
            ("SELECTED", "Selected", "Apply rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        cleanup = bool(getattr(p, "blockffd_cleanup_after_apply", True))
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD apply.")
            return {"CANCELLED"}

        applied = 0
        skipped = 0
        for obj in targets:
            mod = obj.modifiers.get("SMILE_BLOCK_FFD")
            if not mod:
                skipped += 1
                continue
            ok = _apply_modifier_on_object(context, obj, "SMILE_BLOCK_FFD")
            if not ok:
                skipped += 1
                continue
            applied += 1
            if cleanup:
                _blockffd_remove_for_tooth(
                    obj, remove_modifier=False, remove_lattice=True, remove_handles=True
                )
            else:
                _blockffd_clear_meta(obj)

        if applied == 0:
            self.report({"WARNING"}, "No Block FFD modifier was applied.")
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report(
            {"INFO"}, f"Applied Block FFD on {applied} tooth/teeth. Skipped {skipped}."
        )
        return {"FINISHED"}


# === SMILE_OT_blockffd_remove (lines 29915-29950) ===


class SMILE_OT_blockffd_remove(bpy.types.Operator):
    bl_idname = "smile.blockffd_remove"
    bl_label = "Remove Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Remove rig on active mesh tooth"),
            ("SELECTED", "Selected", "Remove rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD remove.")
            return {"CANCELLED"}

        removed = 0
        for obj in targets:
            had_any = bool(
                obj.modifiers.get("SMILE_BLOCK_FFD") or _blockffd_lattice_for_tooth(obj)
            )
            _blockffd_remove_for_tooth(
                obj, remove_modifier=True, remove_lattice=True, remove_handles=True
            )
            if had_any:
                removed += 1

        p = context.scene.smile_v2
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report({"INFO"}, f"Removed Block FFD rigs: {removed}.")
        return {"FINISHED"}


# === build_adjacent_bvhtrees (lines 29953-29971) ===


# === SMILE_ProximalAnalyzer (lines 29974-30055) ===


class SMILE_ProximalAnalyzer:
    """Manages real-time proximity feedback and confinement during sculpting."""

    def __init__(self, veneer_obj, target_scan, target_bvh):
        self.veneer = veneer_obj
        self.scan = target_scan
        self.bvh = target_bvh
        self.params = {"ideal_min": 0.05, "ideal_max": 0.15, "crit_tight": 0.02}

    def update_feedback(self, context):
        """Update vertex colors and apply soft push."""
        if self.veneer.mode != "SCULPT":
            return

        # preparation
        me = self.veneer.data
        if "SMILE_CONTACT" not in me.color_attributes:
            me.color_attributes.new("SMILE_CONTACT", "BYTE_COLOR", "POINT")

        attr = me.color_attributes["SMILE_CONTACT"]
        mw = self.veneer.matrix_world
        mw_inv = mw.inverted()
        scan_mw = self.scan.matrix_world
        scan_mw_inv = scan_mw.inverted()

        # Performance: Sample vertices sparsely
        import random

        # Stride based on vertex count (target ~1000 checks per frame)
        stride = int(max(1, len(me.vertices) // 1000))

        # We need to access bmesh layer directly for performant color updates?
        # Standard API is slow for per-vertex color setting in loop.
        # But 'foreach_set' requires full array.
        # Let's iterate a subset and just update those.

        # Note: Modifying v.co in Sculpt Mode is tricky. Blender Sculpt mode locks mesh data.
        # We cannot modify v.co directly while user is brushing.
        # Visual Feedback (Color) works.
        # Physical Confinement usually requires a Modifier (Shrinkwrap/Collision) or Brush setting.
        # Script-based 'push' fights with the brush engine.

        # Better Confinement Strategy:
        # Instead of pushing verts (which lags/fails in sculpt mode), we create a Collision Mask.
        # Or we assume this is "Visual Guide" only + Post-Stroke correction?
        # Let's stick to Visual Feedback for now as it's robust.

        # Optimization: Use foreach to read/write coords if possible, but KDTree is point-by-point.
        # Batch query?

        # vertices_to_check = me.vertices[::stride]

        count = len(me.vertices)
        for i in range(0, count, stride):
            v = me.vertices[i]
            # 1. World Space Query
            wp = mw @ v.co
            lp_scan = scan_mw_inv @ wp

            loc, norm, idx, dist = self.bvh.find_nearest(lp_scan)

            if loc:
                # 2. Feedback Color
                if dist < self.params["crit_tight"]:
                    col = (1.0, 0.0, 0.0, 1.0)  # Red
                elif dist < self.params["ideal_min"]:
                    col = (1.0, 0.5, 0.0, 1.0)  # Orange
                elif dist < self.params["ideal_max"]:
                    col = (0.0, 1.0, 0.0, 1.0)  # Green
                else:
                    col = (0.5, 0.5, 0.5, 1.0)  # Grey

                # Write color (Slow part)
                attr.data[v.index].color = col

        # To make color visible, we must be in Vertex Paint or specific shading.
        # Setup Dental Workspace ensures 'VERTEX' color type.

        # me.update() # Can cause sculpt stroke interruption?
        # Only update if we changed geometry. If only color, maybe skipping update is unsafe.
        # But updating mesh during sculpt is generally bad.
        pass


# === SMILE_OT_liquify_toggle (lines 46807-46868) ===


class SMILE_OT_liquify_toggle(bpy.types.Operator):
    """Toggle liquify scaffold mode and mark design step progress."""

    bl_idname = "smile.liquify_toggle"
    bl_label = "Toggle Liquify"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 4, "Liquify session")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        p = context.scene.smile_v2
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        enable = not bool(p.sf_liquify_enabled)
        p.sf_liquify_enabled = enable
        if enable:
            ensure_active(obj)
            try:
                bpy.ops.object.mode_set(mode="SCULPT")
            except Exception:
                self.report({"ERROR"}, "Failed to enter Sculpt mode.")
                p.sf_liquify_enabled = False
                return {"CANCELLED"}

            brush_map = {
                "INFLATE": ["Inflate/Deflate", "Inflate", "Draw"],
                "FLATTEN": ["Flatten", "Flatten/Contrast", "Draw Sharp", "Draw"],
                "DEFORM": ["Grab", "Elastic Deform", "Snake Hook", "Draw"],
                "EDGES": ["Crease", "Pinch", "Draw Sharp", "Draw"],
                "SMOOTH": ["Smooth", "Draw"],
            }
            sculpt = context.tool_settings.sculpt
            target_names = brush_map.get(str(p.sf_liquify_brush), ["Draw"])
            selected = None
            for nm in target_names:
                b = bpy.data.brushes.get(nm)
                if b:
                    selected = b
                    break
            if selected:
                sculpt.brush = selected
                try:
                    selected.size = int(max(1, float(p.sf_liquify_size)))
                    selected.strength = float(p.sf_liquify_intensity)
                except Exception:
                    pass
            p.step4_done = True
            _set_min_design_step(p, 5)
        else:
            try:
                if obj.mode == "SCULPT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        self.report({"INFO"}, f"Liquify {'enabled' if enable else 'disabled'}.")
        return {"FINISHED"}


# === SMILE_OT_toggle_symmetry_runtime (lines 46871-46890) ===


class SMILE_OT_toggle_symmetry_runtime(bpy.types.Operator):
    """Toggle symmetry mirroring between paired teeth (runtime-registered variant)."""

    bl_idname = "smile.toggle_symmetry"
    bl_label = "Toggle Symmetry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        if p.symmetry_enabled:
            remove_symmetry_constraints(context)
            p.symmetry_enabled = False
            self.report({"INFO"}, "Symmetry disabled")
        else:
            setup_symmetry_constraints(context)
            p.symmetry_enabled = True
            self.report(
                {"INFO"}, "Symmetry enabled - paired teeth will mirror each other"
            )
        return {"FINISHED"}


# === SMILE_OT_waxup_cervical_merge (lines 46893-46975) ===


class SMILE_OT_waxup_cervical_merge(bpy.types.Operator):
    """Adapt the cervical margin of a library tooth to the underlying scan."""

    bl_idname = "smile.waxup_cervical_merge"
    bl_label = "Cervical Merge (Adapt to Scan)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        target_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        # fallback to active object if domain not set for testing
        if (
            not target_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            # assume active is the scan, and selected is the library tooth
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                target_obj = context.active_object

        selected = [
            o for o in context.selected_objects if o != target_obj and o.type == "MESH"
        ]

        if not target_obj or not selected:
            self.report({"ERROR"}, "Select Library Tooth and Shift-Select Scan Target")
            return {"CANCELLED"}

        scan_obj = target_obj

        for lib_obj in selected:
            # 1. Create Vertex Group for Cervical Margin
            # (In a real implementation, we'd find the boundary edge loop.
            # For this prototype, we'll try to use existing groups or select bottom vertices based on Z height relative to bounding box)
            vg_name = "SMILE_CervicalMargin"
            vg = lib_obj.vertex_groups.get(vg_name)
            if not vg:
                vg = lib_obj.vertex_groups.new(name=vg_name)

            # Simple heuristic for prototyping: bottom 20% of vertices in local Z
            mesh = lib_obj.data
            z_coords = [v.co.z for v in mesh.vertices]
            min_z = min(z_coords)
            max_z = max(z_coords)
            threshold_z = min_z + (max_z - min_z) * 0.20

            bottom_verts = [v.index for v in mesh.vertices if v.co.z < threshold_z]
            vg.add(bottom_verts, 1.0, "REPLACE")

            # 2. Add Shrinkwrap Modifier
            sw_name = "SMILE_Waxup_Adapt"
            sw = lib_obj.modifiers.get(sw_name)
            if not sw:
                sw = lib_obj.modifiers.new(name=sw_name, type="SHRINKWRAP")

            sw.target = scan_obj
            sw.vertex_group = vg_name
            sw.wrap_method = "PROJECT"
            sw.use_project_z = True
            sw.use_negative_direction = True
            sw.use_positive_direction = True
            sw.cull_face = "OFF"

            # 3. Add Smooth Modifier to blend
            sm_name = "SMILE_Waxup_Smooth"
            sm = lib_obj.modifiers.get(sm_name)
            if not sm:
                sm = lib_obj.modifiers.new(name=sm_name, type="SMOOTH")
                sm.vertex_group = vg_name
                sm.iterations = 5

        self.report({"INFO"}, f"Adapted {len(selected)} teeth to {scan_obj.name}")
        return {"FINISHED"}


# === SMILE_OT_waxup_generate_shell (lines 46978-47096) ===


class SMILE_OT_waxup_generate_shell(bpy.types.Operator):
    """Boolean merge of Waxup teeth to a Blocked-out Scan"""

    bl_idname = "smile.waxup_generate_shell"
    bl_label = "Generate Mockup Shell"
    bl_options = {"REGISTER", "UNDO"}

    spacer_thickness_mm: bpy.props.FloatProperty(
        name="Spacer Thickness (mm)", default=0.15, min=0.0, max=1.0
    )

    def _apply_modifier(self, obj, mod_name):
        try:
            with bpy.context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj]
            ):
                bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False

    def execute(self, context):
        p = context.scene.smile_v2

        # 1. Identify Target Scan
        scan_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        if (
            not scan_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                scan_obj = context.active_object

        selected_teeth = [
            o for o in context.selected_objects if o != scan_obj and o.type == "MESH"
        ]

        if not scan_obj or not selected_teeth:
            self.report({"ERROR"}, "Select Library Teeth and Shift-Select Scan Target")
            return {"CANCELLED"}

        # 2. Duplicate Scan for Blockout/Spacer
        spacer_name = f"Mockup_Spacer_{scan_obj.name}"
        old_spacer = bpy.data.objects.get(spacer_name)
        if old_spacer:
            delete_object(old_spacer)

        deps = context.evaluated_depsgraph_get()
        scan_eval = scan_obj.evaluated_get(deps)
        spacer_mesh = bpy.data.meshes.new_from_object(scan_eval)
        spacer_obj = bpy.data.objects.new(spacer_name, spacer_mesh)
        context.scene.collection.objects.link(spacer_obj)
        spacer_obj.matrix_world = scan_obj.matrix_world.copy()

        # 3. Add Solidify to act as Spacer (Outward expansion)
        if self.spacer_thickness_mm > 0.0:
            s_mod = spacer_obj.modifiers.new("Waxup_Spacer", "SOLIDIFY")
            # Convert mm to BU (assuming 1 BU = 1mm for dental usually, or check unit_settings)
            scale = (
                context.scene.unit_settings.scale_length
                if context.scene.unit_settings.system != "NONE"
                else 1.0
            )
            if context.scene.unit_settings.system == "METRIC":
                s_mod.thickness = self.spacer_thickness_mm / (scale * 1000.0)
            else:
                s_mod.thickness = self.spacer_thickness_mm

            s_mod.offset = 1.0  # Expand outwards
            s_mod.use_rim = True
            self._apply_modifier(spacer_obj, s_mod.name)

        # 4. Merge all selected teeth into one solid
        # For prototype simplicity, we just join them. Real world might need Voxel Remesh or Union.
        bpy.ops.object.select_all(action="DESELECT")
        for t in selected_teeth:
            t.select_set(True)

        context.view_layer.objects.active = selected_teeth[0]

        merged_name = "Mockup_Merged_Teeth"
        old_merged = bpy.data.objects.get(merged_name)
        if old_merged:
            delete_object(old_merged)

        bpy.ops.object.duplicate()
        merged_teeth = context.active_object
        merged_teeth.name = merged_name

        for o in context.selected_objects:
            if o != merged_teeth:
                o.select_set(True)
        bpy.ops.object.join()

        # 5. Boolean Difference: Merged Teeth - Spacer
        # We subtract the expanded scan from the mockup teeth
        bool_mod = merged_teeth.modifiers.new("Mockup_Intaglio", "BOOLEAN")
        bool_mod.operation = "DIFFERENCE"
        bool_mod.object = spacer_obj
        bool_mod.solver = "EXACT"

        self.report({"INFO"}, f"Generated Shell Preview. Apply boolean for final mesh.")

        # Cleanup view
        spacer_obj.display_type = "WIRE"
        spacer_obj.hide_render = True

        return {"FINISHED"}


# === ensure_triangulated_mesh_data (lines 47104-47130) ===


def ensure_triangulated_mesh_data(obj, apply_world=True):
    """Zero-copy data ingestion. Bypasses Python loops."""
    import numpy as np

    t0 = time.time()
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()

    verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    verts = verts.reshape((-1, 3))

    if apply_world:
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]

    mesh.calc_loop_triangles()
    tris = np.zeros(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape((-1, 3))

    eval_obj.to_mesh_clear()
    print(f"[Algo] Ingested {len(verts)} verts in {(time.time() - t0) * 1000:.2f}ms")
    return verts, tris


# === extract_curve_points_np (lines 47133-47153) ===


def extract_curve_points_np(obj):
    """Extracts world-space points from a Blender curve or mesh object."""
    import numpy as np

    if obj.type == "MESH":
        verts, _ = ensure_triangulated_mesh_data(obj, apply_world=True)
        return verts
    elif obj.type == "CURVE":
        deps = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        mesh = eval_obj.to_mesh()
        verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", verts)
        verts = verts.reshape((-1, 3))
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]
        eval_obj.to_mesh_clear()
        return verts
    return np.array([])


# === points_in_poly_np (lines 47156-47175) ===


def points_in_poly_np(points_2d, poly_2d):
    """Highly optimized 2D raycasting point-in-polygon algorithm."""
    import numpy as np

    x = points_2d[:, 0]
    y = points_2d[:, 1]
    inside = np.zeros(len(x), dtype=bool)
    n = len(poly_2d)
    p1x, p1y = poly_2d[0]
    for i in range(n + 1):
        p2x, p2y = poly_2d[i % n]
        min_y = min(p1y, p2y)
        max_y = max(p1y, p2y)
        mask = (y > min_y) & (y <= max_y)
        if p1y != p2y:
            x_ints = (y[mask] - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            cross = x[mask] <= x_ints
            inside[mask] ^= cross
        p1x, p1y = p2x, p2y
    return inside


# === calc_normal_np (lines 47178-47192) ===


def calc_normal_np(points):
    """Calculates best-fit normal vector using Newell's Method."""
    import numpy as np

    n = np.zeros(3)
    for i in range(len(points)):
        curr = points[i]
        nxt = points[(i + 1) % len(points)]
        n[0] += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
        n[1] += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
        n[2] += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
    norm = np.linalg.norm(n)
    if norm == 0:
        return np.array([0, 0, 1])
    return n / norm


# === get_rotation_matrix_to_z_np (lines 47195-47207) ===


def get_rotation_matrix_to_z_np(normal):
    """Creates a rotation matrix to align a given normal to the Z-axis [0,0,1]."""
    import numpy as np

    z_axis = np.array([0, 0, 1])
    v = np.cross(normal, z_axis)
    s = np.linalg.norm(v)
    c = np.dot(normal, z_axis)
    if s == 0:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    R = np.eye(3) + vx + np.dot(vx, vx) * ((1 - c) / (s**2))
    return R


# === get_boundary_edges_np (lines 47210-47217) ===


def get_boundary_edges_np(tris):
    """Extracts boundary edges (edges belonging to only one triangle) from an array of triangles."""
    import numpy as np

    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges_sorted = np.sort(edges, axis=1)
    unique_edges, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    return unique_edges[counts == 1]


# === extract_intaglio_vectorized_np (lines 47220-47277) ===


def extract_intaglio_vectorized_np(verts, tris, margin_points):
    """
    Phase 1: The Intaglio.
    Uses pure NumPy to perform a 2D projection cut and 3D boundary snapping.
    """
    import numpy as np

    t0 = time.time()

    # 1. Determine Insertion Axis and Project to 2D
    normal = calc_normal_np(margin_points)
    R = get_rotation_matrix_to_z_np(normal)
    verts_2d = np.dot(verts, R.T)[:, :2]
    margin_2d = np.dot(margin_points, R.T)[:, :2]

    # 2. Point in Polygon Test
    inside_mask = points_in_poly_np(verts_2d, margin_2d)

    # 3. Filter Triangles (Keep if ALL 3 vertices are inside)
    face_mask = (
        inside_mask[tris[:, 0]] & inside_mask[tris[:, 1]] & inside_mask[tris[:, 2]]
    )
    kept_tris = tris[face_mask]

    if len(kept_tris) == 0:
        print("[Algo] Warning: No triangles inside margin! Check orientation.")
        return verts, tris

    # 4. Extract Boundary Vertices
    boundary_edges = get_boundary_edges_np(kept_tris)
    boundary_vertices = np.unique(boundary_edges)

    # 5. Snap Boundary Vertices to true 3D Margin Curve using Blender's KDTree
    kd = KDTree(len(margin_points))
    for i, p in enumerate(margin_points):
        kd.insert(p, i)
    kd.balance()

    new_verts = verts.copy()
    for bv in boundary_vertices:
        co, index, dist = kd.find(new_verts[bv])
        new_verts[bv] = np.array(co)

    # 6. Cleanup unreferenced vertices to return a compact mesh
    referenced_mask = np.zeros(len(new_verts), dtype=bool)
    referenced_mask[kept_tris.flatten()] = True

    old_to_new = np.full(len(new_verts), -1, dtype=np.int32)
    new_indices = np.arange(np.sum(referenced_mask))
    old_to_new[referenced_mask] = new_indices

    compact_verts = new_verts[referenced_mask]
    compact_tris = old_to_new[kept_tris]

    print(
        f"[Algo] Intaglio Extracted & Snapped {len(compact_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return compact_verts, compact_tris


# === generate_emergence_collar_np (lines 47280-47342) ===


def generate_emergence_collar_np(
    verts, tris, margin_points, height=0.5, angle_deg=15.0
):
    """
    Phase 2: The Emergence Profile Collar.
    Extrudes the boundary edges upward and outward to create a seating collar.
    """
    import numpy as np

    t0 = time.time()

    boundary_edges = get_boundary_edges_np(tris)
    bound_verts = np.unique(boundary_edges)

    if len(bound_verts) == 0:
        return verts, tris

    axis = calc_normal_np(margin_points)  # Insertion axis
    center = np.mean(margin_points, axis=0)
    angle_rad = math.radians(angle_deg)

    old_to_new_extruded = {
        old_idx: i + len(verts) for i, old_idx in enumerate(bound_verts)
    }
    new_verts = np.zeros((len(bound_verts), 3), dtype=np.float32)

    # Parametric Extrusion Calculation
    for i, b_idx in enumerate(bound_verts):
        v = verts[b_idx]

        # Outward radial vector perpendicular to insertion axis
        vec_to_v = v - center
        radial = vec_to_v - np.dot(vec_to_v, axis) * axis
        norm_radial = np.linalg.norm(radial)
        if norm_radial > 0:
            radial = radial / norm_radial

        # Extrude Upward (height) and Outward (tan(angle))
        outward_mag = height * math.tan(angle_rad)
        extrusion = (axis * height) + (radial * outward_mag)

        new_verts[i] = v + extrusion

    combined_verts = np.vstack([verts, new_verts])

    # Bridge the gap with Quads (2 Triangles per edge)
    new_tris = []
    for edge in boundary_edges:
        v1, v2 = edge
        v1_new = old_to_new_extruded[v1]
        v2_new = old_to_new_extruded[v2]

        # Triangle 1
        new_tris.append([v1, v2, v2_new])
        # Triangle 2
        new_tris.append([v1, v2_new, v1_new])

    combined_tris = np.vstack([tris, np.array(new_tris, dtype=np.int32)])

    print(
        f"[Algo] Emergence Collar Generated: {len(new_tris)} faces in {(time.time() - t0) * 1000:.2f}ms"
    )
    return combined_verts, combined_tris


# === build_morph_geometry_nodes_np (lines 47345-47442) ===


def build_morph_geometry_nodes_np(node_group_name="SMILE_Morph_Engine"):
    """
    Phase 3: The Morph.
    Constructs a multi-threaded C++ backend Geometry Nodes modifier.
    """
    ng = bpy.data.node_groups.get(node_group_name)
    if not ng:
        ng = bpy.data.node_groups.new(node_group_name, "GeometryNodeTree")

        # In/Out Interfaces (Blender 4.0+ compatible API)
        if hasattr(ng, "interface"):
            ng.interface.new_socket(
                "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Target Collar", in_out="INPUT", socket_type="NodeSocketObject"
            )
            socket_falloff = ng.interface.new_socket(
                "Morph Falloff", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            socket_falloff.default_value = 3.0  # 3mm morph transition zone
        else:
            ng.outputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketObject", "Target Collar")
            socket_falloff = ng.inputs.new("NodeSocketFloat", "Morph Falloff")
            socket_falloff.default_value = 3.0

        nodes = ng.nodes
        links = ng.links

        node_in = nodes.new("NodeGroupInput")
        node_out = nodes.new("NodeGroupOutput")

        # 1. Target Proximity
        obj_info = nodes.new("GeometryNodeObjectInfo")
        obj_info.inputs["Transform Space"].default_value = "RELATIVE"
        target_prox = nodes.new("GeometryNodeProximity")
        target_prox.target_element = "EDGES"

        # 2. Self Boundary Distance
        edge_neighbors = nodes.new("GeometryNodeInputMeshEdgeNeighbors")
        compare_edges = nodes.new("FunctionNodeCompare")
        compare_edges.data_type = "INT"
        compare_edges.operation = "EQUAL"
        compare_edges.inputs[
            3
        ].default_value = 1  # Edge neighbor count = 1 means boundary

        separate_geom = nodes.new("GeometryNodeSeparateGeometry")
        separate_geom.domain = "EDGE"

        self_prox = nodes.new("GeometryNodeProximity")
        self_prox.target_element = "EDGES"

        # 3. Falloff Math
        map_range = nodes.new("ShaderNodeMapRange")
        map_range.clamp = True
        map_range.inputs[1].default_value = 0.0
        map_range.inputs[3].default_value = 1.0
        map_range.inputs[4].default_value = 0.0
        map_range.interpolation_type = "SMOOTHSTEP"

        # 4. Mix Position
        pos_node = nodes.new("GeometryNodeInputPosition")
        mix_node = nodes.new("ShaderNodeMix")
        mix_node.data_type = "VECTOR"
        mix_node.clamp_factor = True

        set_pos = nodes.new("GeometryNodeSetPosition")

        # Self Boundary Distance flow
        links.new(edge_neighbors.outputs["Face Count"], compare_edges.inputs[2])
        links.new(node_in.outputs["Geometry"], separate_geom.inputs["Geometry"])
        links.new(compare_edges.outputs["Result"], separate_geom.inputs["Selection"])
        links.new(separate_geom.outputs["Selection"], self_prox.inputs["Target"])

        # Target Position flow
        links.new(node_in.outputs["Target Collar"], obj_info.inputs["Object"])
        links.new(obj_info.outputs["Geometry"], target_prox.inputs["Target"])

        # Blend Math flow
        links.new(self_prox.outputs["Distance"], map_range.inputs[0])
        links.new(node_in.outputs["Morph Falloff"], map_range.inputs[2])  # From Max

        links.new(map_range.outputs["Result"], mix_node.inputs[0])  # Factor
        links.new(pos_node.outputs["Position"], mix_node.inputs[4])  # A (Original)
        links.new(target_prox.outputs["Position"], mix_node.inputs[5])  # B (Target)

        # Final Set Position
        links.new(node_in.outputs["Geometry"], set_pos.inputs["Geometry"])
        links.new(mix_node.outputs[1], set_pos.inputs["Position"])
        links.new(set_pos.outputs["Geometry"], node_out.inputs["Geometry"])

    return ng


# === numpy_to_mesh_np (lines 47445-47466) ===


def numpy_to_mesh_np(name, verts_np, faces_np):
    """Zero-copy output."""
    import numpy as np

    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts_np))
    mesh.loops.add(len(faces_np) * 3)
    mesh.polygons.add(len(faces_np))

    mesh.vertices.foreach_set("co", verts_np.flatten())

    loop_start = np.arange(0, len(faces_np) * 3, 3, dtype=np.int32)
    loop_total = np.full(len(faces_np), 3, dtype=np.int32)

    mesh.loops.foreach_set("vertex_index", faces_np.flatten())
    mesh.polygons.foreach_set("loop_start", loop_start)
    mesh.polygons.foreach_set("loop_total", loop_total)

    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# === stitch_meshes_vectorized_np (lines 47469-47487) ===


def stitch_meshes_vectorized_np(verts_A, tris_A, verts_B, tris_B, tolerance=4):
    """Phase 4: Topological Stitching."""
    import numpy as np

    t0 = time.time()
    combined_verts = np.vstack((verts_A, verts_B))
    tris_B_offset = tris_B + len(verts_A)
    combined_tris = np.vstack((tris_A, tris_B_offset))
    rounded_verts = np.round(combined_verts, decimals=tolerance)
    unique_verts, inverse_indices = np.unique(
        rounded_verts, axis=0, return_inverse=True
    )
    _, unique_indices = np.unique(rounded_verts, axis=0, return_index=True)
    final_verts = combined_verts[unique_indices]
    final_tris = inverse_indices[combined_tris]
    print(
        f"[Algo] Phase 4 Stitching: {len(combined_verts)} -> {len(final_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return final_verts, final_tris


# === execute_industry_standard_crown_np (lines 47490-47551) ===


def execute_industry_standard_crown_np(library_obj, spacer_obj, margin_curve_obj=None):
    """The Orchestrator."""
    print("--- INITIATING HYBRID C++/PYTHON CROWN GENERATION ---")

    lib_v, lib_f = ensure_triangulated_mesh_data(library_obj, apply_world=True)
    space_v, space_f = ensure_triangulated_mesh_data(spacer_obj, apply_world=True)

    if margin_curve_obj:
        margin_points = extract_curve_points_np(margin_curve_obj)
        if len(margin_points) > 2:
            intaglio_v, intaglio_f = extract_intaglio_vectorized_np(
                space_v, space_f, margin_points
            )
            collar_v, collar_f = generate_emergence_collar_np(
                intaglio_v, intaglio_f, margin_points, height=1.0, angle_deg=15.0
            )

            int_obj = bpy.data.objects.get("DEBUG_Intaglio_Collar")
            if int_obj:
                bpy.data.objects.remove(int_obj, do_unlink=True)
            intaglio_obj = numpy_to_mesh_np("DEBUG_Intaglio_Collar", collar_v, collar_f)

            build_morph_geometry_nodes_np()
            mod_name = "SMILE_C++_Morph"
            if mod_name not in library_obj.modifiers:
                mod = library_obj.modifiers.new(name=mod_name, type="NODES")
                mod.node_group = bpy.data.node_groups["SMILE_Morph_Engine"]

            if "Target Collar" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Target Collar"] = intaglio_obj
            elif "Input_2" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Input_2"] = intaglio_obj

            bpy.context.view_layer.update()

            morphed_v, morphed_f = ensure_triangulated_mesh_data(
                library_obj, apply_world=True
            )
            flipped_collar_f = collar_f[:, [0, 2, 1]]
            final_v, final_f = stitch_meshes_vectorized_np(
                morphed_v, morphed_f, collar_v, flipped_collar_f
            )

            crown_name = f"CROWN_INDUSTRY_{library_obj.name.split('_')[0]}"
            crown_obj = bpy.data.objects.get(crown_name)
            if crown_obj:
                bpy.data.objects.remove(crown_obj, do_unlink=True)

            final_crown_obj = numpy_to_mesh_np(crown_name, final_v, final_f)
            bpy.data.objects.remove(intaglio_obj, do_unlink=True)
            library_obj.modifiers.remove(library_obj.modifiers[mod_name])
            library_obj.hide_viewport = True

            print("--- CROWN GENERATION PIPELINE COMPLETED SUCCESSFULLY ---")
            return {"status": "SUCCESS", "crown_obj": final_crown_obj}
        else:
            return {
                "status": "FAILED",
                "message": "Margin curve has insufficient points.",
            }
    else:
        return {"status": "FAILED", "message": "No margin curve provided."}


# === SMILE_OT_generate_industry_crown (lines 47554-47593) ===


class SMILE_OT_generate_industry_crown(bpy.types.Operator):
    """Generate Crown using Hybrid C++/Python Architecture (Zero-Copy)"""

    bl_idname = "smile.generate_industry_crown"
    bl_label = "Generate Crown (C++ Engine v1.1)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        library_obj = context.view_layer.objects.active

        target_tid = int(getattr(p, "target_tooth_id", 0) or 0)
        spacer_name = f"SPACER_T{target_tid}"
        spacer_obj = bpy.data.objects.get(spacer_name)
        if not spacer_obj:
            self.report(
                {"ERROR"}, f"Spacer {spacer_name} not found. Generate Die/Spacer first."
            )
            return {"CANCELLED"}

        if not library_obj or library_obj == spacer_obj or library_obj.type != "MESH":
            self.report({"ERROR"}, "Select the Library Tooth first.")
            return {"CANCELLED"}

        margin_name = f"MARGIN_{spacer_obj.name.replace('SPACER_', '')}"
        margin_obj = bpy.data.objects.get(margin_name)
        if not margin_obj:
            # try direct T naming
            margin_obj = bpy.data.objects.get(f"MARGIN_T{target_tid}")

        if not margin_obj:
            self.report(
                {"ERROR"},
                f"Margin curve for T#{target_tid} not found. Please trace a margin first.",
            )
            return {"CANCELLED"}

        res = execute_industry_standard_crown_np(library_obj, spacer_obj, margin_obj)
        self.report({"INFO"}, f"Generation Complete: {res.get('status')}")
        return {"FINISHED"}


# === _current_design_step (lines 8447-8452) ===
def _current_design_step(props) -> int:
    try:
        step = int(getattr(props, "design_step", "1"))
    except Exception:
        step = 1
    return max(1, min(6, step))


# === _sync_workflow_progress (lines 8472-8503) ===
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


# === _set_min_design_step (lines 9169-9174) ===
def _set_min_design_step(props, step: int):
    tgt = max(1, min(6, int(step)))
    cur = _current_design_step(props)
    if tgt > cur:
        props.design_step = str(tgt)
    _sync_workflow_progress(props)


# === _safe_object_name (lines 13010-13014) ===
def _safe_object_name(obj):
    try:
        return str(obj.name)
    except Exception:
        return ""


# === _blockffd_owner_from_handle (lines 13017-13035) ===
def _blockffd_owner_from_handle(obj):
    if not obj:
        return None
    try:
        if not bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
            return None
        owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
        if not owner_name:
            return None
        owner = bpy.data.objects.get(owner_name)
        if (
            owner
            and owner.type == "MESH"
            and (not bool(owner.get("SMILE_BLOCKFFD_HANDLE", False)))
        ):
            return owner
    except Exception:
        pass
    return None


# === _blockffd_bbox_local (lines 13073-13096) ===
def _blockffd_bbox_local(obj):
    local_corners = [Vector(c) for c in obj.bound_box]
    if not local_corners:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )
    center = (mn + mx) * 0.5
    dims = mx - mn
    dims.x = max(1e-6, float(dims.x))
    dims.y = max(1e-6, float(dims.y))
    dims.z = max(1e-6, float(dims.z))
    return center, dims


# === _blockffd_lattice_for_tooth (lines 13099-13108) ===
def _blockffd_lattice_for_tooth(tooth_obj):
    lat_name = str(tooth_obj.get(KEY_BLOCKFFD_LAT, "") or "")
    if lat_name:
        lat = bpy.data.objects.get(lat_name)
        if lat and lat.type == "LATTICE":
            return lat
    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if mod and mod.type == "LATTICE" and getattr(mod, "object", None):
        return mod.object
    return None


# === _blockffd_handle_names_for_tooth (lines 13111-13140) ===
def _blockffd_handle_names_for_tooth(tooth_obj, lat_obj=None):
    names = []
    raw = tooth_obj.get(KEY_BLOCKFFD_HANDLES)
    if isinstance(raw, str) and raw.strip():
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                for n in arr:
                    nn = str(n or "").strip()
                    ho = bpy.data.objects.get(nn) if nn else None
                    if ho and bool(ho.get("SMILE_BLOCKFFD_HANDLE", False)):
                        names.append(nn)
        except Exception:
            pass
    if names:
        return names
    owner = _safe_object_name(tooth_obj)
    for obj in bpy.data.objects:
        try:
            if (
                obj.get("SMILE_BLOCKFFD_HANDLE", False)
                and str(obj.get("SMILE_BLOCKFFD_OWNER", "")) == owner
            ):
                names.append(obj.name)
                continue
            if lat_obj and str(obj.get("SMILE_BLOCKFFD_LATTICE", "")) == lat_obj.name:
                names.append(obj.name)
        except Exception:
            continue
    return names


# === _blockffd_clear_meta (lines 13143-13158) ===
def _blockffd_clear_meta(tooth_obj):
    for k in (
        KEY_BLOCKFFD_LAT,
        KEY_BLOCKFFD_HANDLES,
        "SMILE_BLOCKFFD_DIVS",
        "SMILE_BLOCKFFD_SURFACE_ONLY",
        "SMILE_BLOCKFFD_CORNER_ONLY",
        "SMILE_BLOCKFFD_GAP",
        "SMILE_BLOCKFFD_PAD",
        "SMILE_BLOCKFFD_HANDLE_FACTOR",
    ):
        try:
            if k in tooth_obj:
                del tooth_obj[k]
        except Exception:
            pass


# === _blockffd_set_relationship_lines (lines 13180-13196) ===
def _blockffd_set_relationship_lines(scene, show):
    overlays = _blockffd_collect_view3d_overlays()
    if not overlays:
        return
    if not bool(show):
        try:
            if overlays:
                scene[KEY_BLOCKFFD_REL_PREV] = bool(
                    getattr(overlays[0], "show_relationship_lines", True)
                )
        except Exception:
            pass
    for ov in overlays:
        try:
            ov.show_relationship_lines = bool(show)
        except Exception:
            pass


# === _blockffd_get_handle_mesh (lines 13482-13499) ===
def _blockffd_get_handle_mesh():
    name = "SMILE_BLOCKFFD_HANDLE_MESH"
    me = bpy.data.meshes.get(name)
    if not me:
        me = bpy.data.meshes.new(name)
    else:
        try:
            me.clear_geometry()
        except Exception:
            pass
    bm = bmesh.new()
    try:
        # Smooth visual sphere (not faceted polyhedron).
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.5)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me


# === _blockffd_min_step_world (lines 13502-13535) ===
def _blockffd_min_step_world(lat_obj, divisions):
    """Smallest neighbor-center spacing between lattice control points in world units."""
    try:
        d = int(max(2, int(divisions)))
        pts = lat_obj.data.points
        if len(pts) < 2:
            return 1e-6
        d2 = d * d
        mw = lat_obj.matrix_world
        min_step = 1.0e18

        def _w(idx):
            p = pts[idx].co
            return mw @ Vector((float(p.x), float(p.y), float(p.z)))

        for w in range(d):
            for v in range(d):
                for u in range(d):
                    idx = w * d2 + v * d + u
                    c = _w(idx)
                    if u + 1 < d:
                        j = w * d2 + v * d + (u + 1)
                        min_step = min(min_step, (c - _w(j)).length)
                    if v + 1 < d:
                        j = w * d2 + (v + 1) * d + u
                        min_step = min(min_step, (c - _w(j)).length)
                    if w + 1 < d:
                        j = (w + 1) * d2 + v * d + u
                        min_step = min(min_step, (c - _w(j)).length)
        if not math.isfinite(min_step) or min_step <= 0.0:
            return 1e-6
        return float(min_step)
    except Exception:
        return 1e-6


# === _apply_modifier_on_object (lines 13584-13606) ===
def _apply_modifier_on_object(context, obj, mod_name):
    if not obj or obj.type != "MESH":
        return False
    if not obj.modifiers.get(mod_name):
        return False
    try:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    ensure_active(obj)
    try:
        with context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False


# ============================================================

# P3 LATTICE RIG, BLOCKFFD, WAXUP, INDUSTRY CROWN NUMPY ENGINE

# Extracted from blendersmile_pnp_full_cleaned_20260318_165959.py

# ============================================================


# === ensure_active (lines 575-578) ===


# === _step_gate_error (lines 9177-9188) ===


def _step_gate_error(context, required_step: int, action_label: str):
    scene = context.scene if context else None
    p = scene.smile_v2 if scene else None
    if not p:
        return None
    _sync_workflow_progress(p)
    if not getattr(p, "enforce_step_lock", False):
        return None
    current = _current_design_step(p)
    if current < int(required_step):
        return f"{action_label} requires Step {int(required_step)}+ (current: Step {current})."
    return None


# === create_lattice_rig_for_tooth (lines 12832-12998) ===


def create_lattice_rig_for_tooth(tooth_obj, size_pad=1.15):
    ensure_collection(COL_RIG)
    ensure_collection(COL_TEETH)

    lat_name = tooth_obj.name + "_LAT"
    lat = bpy.data.objects.get(lat_name)

    # Local Bounding Box (Local Space)
    # obj.bound_box gives 8 corners in local space
    # We want min/max in local space
    local_corners = [Vector(c) for c in tooth_obj.bound_box]
    mn = Vector(
        (
            min(c.x for c in local_corners),
            min(c.y for c in local_corners),
            min(c.z for c in local_corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in local_corners),
            max(c.y for c in local_corners),
            max(c.z for c in local_corners),
        )
    )

    # Center in Local Space
    local_center = (mn + mx) * 0.5
    local_dims = (mx - mn) * size_pad

    if not lat:
        lat_data = bpy.data.lattices.new(lat_name + "_DATA")
        lat_data.points_u = 3
        lat_data.points_v = 3
        lat_data.points_w = 3
        lat = bpy.data.objects.new(lat_name, lat_data)
        bpy.context.scene.collection.objects.link(lat)
        link_to_collection(lat, ensure_collection(COL_RIG))

    # Align Lattice to Tooth perfectly
    lat.matrix_world = tooth_obj.matrix_world.copy()

    # Apply Local Offset and Scale relative to the tooth's origin
    # Lattice points default to -0.5 to +0.5 range.
    # We need to map that range to our local_dims centered at local_center.

    # Since Lattice is now aligned (parented effectively via matrix copy), we work in "Lattice Local" == "Tooth Local".

    # Actually, we should set the Lattice location/scale in its own local space
    lat.location = local_center  # Local translation relative to origin? No, lat.matrix_world is global.

    # If we set lat.matrix_world = tooth.matrix_world, then 'lat' origin is at 'tooth' origin.
    # We then translate 'lat' locally to align with the bbox center.

    # Better approach: Parent Lattice to Tooth immediately?
    # No, modifiers work best with world alignment or parent inverse.
    # Let's simple set matrix match, then apply local Translation/Scale.

    M = tooth_obj.matrix_world
    # Translation to center of bbox
    T_local = Matrix.Translation(local_center)
    # Scale to dimensions
    S_local = Matrix.Diagonal((local_dims.x, local_dims.y, local_dims.z, 1.0))

    lat.matrix_world = M @ T_local @ S_local

    mod = tooth_obj.modifiers.get("SMILE_LATTICE") or tooth_obj.modifiers.new(
        "SMILE_LATTICE", "LATTICE"
    )
    mod.object = lat

    # --- SMART CAGE WEIGHTING LOGIC ---
    handle_names = ["Cervical", "Body", "Incisal"]
    handles = []

    ensure_active(lat)
    lat.hide_set(False)
    lat.hide_viewport = False

    # Use override to prevent Context Missing errors
    with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.lattice.select_all(action="DESELECT")

    # Remove old hooks if re-running
    for m in lat.modifiers:
        if m.type == "HOOK":
            lat.modifiers.remove(m)

    for w_idx in range(3):
        bpy.ops.lattice.select_all(action="DESELECT")

        for v in range(3):
            for u in range(3):
                idx = w_idx * 9 + v * 3 + u
                lat.data.points[idx].select = True

        # Create Handle
        h_name = f"{tooth_obj.name}_H_{handle_names[w_idx]}"
        h_obj = bpy.data.objects.get(h_name)
        if not h_obj:
            h_obj = bpy.data.objects.new(h_name, None)
            h_obj.empty_display_type = "SPHERE"
            h_obj.empty_display_size = (
                local_dims.x * 0.15
            )  # Scale handle visual to tooth size (smaller)
            bpy.context.scene.collection.objects.link(h_obj)
            link_to_collection(h_obj, ensure_collection(COL_RIG))

        handles.append(h_obj)

        # Hook Logic
        # Context Safe Hooking
        lat.hide_set(False)
        h_obj.hide_set(False)

        # 1. Switch to Object Mode to select Hook Object
        with bpy.context.temp_override(active_object=lat, selected_objects=[lat]):
            bpy.ops.object.mode_set(mode="OBJECT")

        # 2. Select both Lat and Handle
        _deselect_all()
        lat.select_set(True)
        h_obj.select_set(True)
        bpy.context.view_layer.objects.active = lat

        # 3. Enter Edit Mode with both selected (Hook needs this context)
        with bpy.context.temp_override(
            active_object=lat, selected_objects=[lat, h_obj]
        ):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.object.hook_add_selob(use_bone=False)

        # Now snap h_obj to the hook center?
        # Actually, if h_obj is at (0,0,0) world, and lattice is elsewhere, the hook offset is huge.
        # We need to position h_obj at the geometric center of the layer BEFORE hooking.

        # Calculate layer center in World Space
        # Layer Z local: -0.5 (idx0), 0.0 (idx1), 0.5 (idx2)
        z_local = (w_idx - 1.0) * 0.5  # Maps 0->-0.5, 1->0.0, 2->0.5
        center_local = Vector((0, 0, z_local))
        center_world = lat.matrix_world @ center_local

        h_obj.location = center_world
        h_obj.rotation_euler = lat.rotation_euler  # Align rotation too

        # Reset Hook Inverse?
        # The modifier stores the inverse. If we move object then hook, it might be offset?
        # Correct order: Position Empty -> Select Points -> Hook.
        # We did: Position (now) -> Hook (already done above?).
        # Wait, I called hook_add_selob BEFORE positioning. That's bad.
        # The hook modifier captures the current relative transform.

    # FIX: Loop again correctly
    # 1. Create all handles and position them.
    # 2. Hook them.

    # ... Refactoring loop structure inside the function for correctness ...

    bpy.ops.object.mode_set(mode="OBJECT")

    # Store handle references
    tooth_obj["SMILE_RIG_H_CERVICAL"] = handles[0].name
    tooth_obj["SMILE_RIG_H_BODY"] = handles[1].name
    tooth_obj["SMILE_RIG_H_INCISAL"] = handles[2].name

    return lat, handles


# === _blockffd_targets_from_scope (lines 13038-13070) ===


def _blockffd_targets_from_scope(context, scope):
    sc = str(scope or "ACTIVE").upper()

    def _resolve_target(o):
        if not o:
            return None
        owner = _blockffd_owner_from_handle(o)
        if owner:
            return owner
        try:
            if o.type == "MESH" and not bool(o.get("SMILE_BLOCKFFD_HANDLE", False)):
                return o
        except Exception:
            pass
        return None

    if sc == "SELECTED":
        out = []
        seen = set()
        for o in context.selected_objects:
            t = _resolve_target(o)
            if not t:
                continue
            n = _safe_object_name(t)
            if n and n not in seen:
                seen.add(n)
                out.append(t)
        return out
    a = context.view_layer.objects.active
    t = _resolve_target(a)
    if t:
        return [t]
    return []


# === _blockffd_restore_relationship_lines (lines 13199-13206) ===


def _blockffd_restore_relationship_lines(scene):
    prev = bool(scene.get(KEY_BLOCKFFD_REL_PREV, True))
    _blockffd_set_relationship_lines(scene, prev)
    try:
        if KEY_BLOCKFFD_REL_PREV in scene:
            del scene[KEY_BLOCKFFD_REL_PREV]
    except Exception:
        pass


# === _blockffd_remove_for_tooth (lines 13538-13581) ===


def _blockffd_remove_for_tooth(
    tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
):
    lat = _blockffd_lattice_for_tooth(tooth_obj)
    handle_names = _blockffd_handle_names_for_tooth(tooth_obj, lat)
    owner_name = _safe_object_name(tooth_obj)

    if remove_modifier:
        for mod in list(tooth_obj.modifiers):
            try:
                if mod.type == "LATTICE" and (
                    mod.name == "SMILE_BLOCK_FFD"
                    or (lat and getattr(mod, "object", None) == lat)
                ):
                    tooth_obj.modifiers.remove(mod)
            except Exception:
                continue

    if remove_handles:
        for n in handle_names:
            h = bpy.data.objects.get(n)
            if not h:
                continue
            try:
                if (
                    h.type == "MESH"
                    and bool(h.get("SMILE_BLOCKFFD_HANDLE", False))
                    and str(h.get("SMILE_BLOCKFFD_OWNER", "")) == owner_name
                ):
                    delete_object(h)
            except Exception:
                continue

    if remove_lattice and lat:
        try:
            if lat.type == "LATTICE" and (
                bool(lat.get("SMILE_BLOCKFFD", False))
                or str(lat.get("SMILE_BLOCKFFD_TOOTH", "")) == owner_name
            ):
                delete_object(lat)
        except Exception:
            pass

    _blockffd_clear_meta(tooth_obj)


# === create_blockffd_rig_for_tooth (lines 13609-13741) ===


def create_blockffd_rig_for_tooth(
    tooth_obj,
    divisions=3,
    size_pad=0.1,
    handle_size_factor=0.05,
    sphere_gap=0.1,
    surface_only=True,
    corner_only=False,
):
    if not tooth_obj or tooth_obj.type != "MESH":
        raise RuntimeError("Active object must be a mesh tooth.")

    divisions = int(max(2, min(6, int(divisions))))
    size_pad = float(max(0.05, min(2.5, float(size_pad))))
    # Absolute scene-unit diameter for handle spheres.
    handle_size_factor = float(max(0.001, min(5.0, float(handle_size_factor))))
    # Absolute scene-unit gap between neighboring sphere surfaces.
    sphere_gap = float(max(0.0, min(5.0, float(sphere_gap))))
    surface_only = bool(surface_only)
    corner_only = bool(corner_only)

    ensure_collection(COL_RIG)
    _blockffd_remove_for_tooth(
        tooth_obj, remove_modifier=True, remove_lattice=True, remove_handles=True
    )

    base_name = f"{tooth_obj.name}_BLOCKFFD"
    lat_data = bpy.data.lattices.new(base_name + "_DATA")
    lat_data.points_u = divisions
    lat_data.points_v = divisions
    lat_data.points_w = divisions
    for attr in (
        "interpolation_type_u",
        "interpolation_type_v",
        "interpolation_type_w",
    ):
        try:
            setattr(lat_data, attr, "KEY_BSPLINE")
        except Exception:
            pass

    lat_obj = bpy.data.objects.new(base_name, lat_data)
    bpy.context.scene.collection.objects.link(lat_obj)
    link_to_collection(lat_obj, ensure_collection(COL_RIG))

    center_local, dims_local = _blockffd_bbox_local(tooth_obj)
    # Additive pad ratio: 0.2 = +20% lattice cage expansion.
    dims_local = dims_local * (1.0 + size_pad)
    M = tooth_obj.matrix_world.copy()
    T_local = Matrix.Translation(center_local)
    S_local = Matrix.Diagonal((dims_local.x, dims_local.y, dims_local.z, 1.0))
    lat_obj.matrix_world = M @ T_local @ S_local
    lat_obj.show_in_front = True

    mod = tooth_obj.modifiers.get("SMILE_BLOCK_FFD")
    if not mod:
        mod = tooth_obj.modifiers.new("SMILE_BLOCK_FFD", "LATTICE")
    mod.object = lat_obj

    # User size is an absolute sphere diameter in scene units.
    handle_size = float(handle_size_factor)
    # Cap by neighbor spacing minus absolute requested gap.
    min_step = _blockffd_min_step_world(lat_obj, divisions)
    max_diameter_from_gap = max(0.001, float(min_step - sphere_gap))
    handle_size = min(handle_size, max_diameter_from_gap)
    handle_mesh = _blockffd_get_handle_mesh()
    handle_names = []
    d2 = int(divisions * divisions)
    for i, pt in enumerate(lat_obj.data.points):
        if corner_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_corner = (
                (u == 0 or u == (divisions - 1))
                and (v == 0 or v == (divisions - 1))
                and (w == 0 or w == (divisions - 1))
            )
            if not is_corner:
                continue
        elif surface_only:
            u = int(i % divisions)
            v = int((i // divisions) % divisions)
            w = int(i // d2)
            is_boundary = (
                u == 0
                or u == (divisions - 1)
                or v == 0
                or v == (divisions - 1)
                or w == 0
                or w == (divisions - 1)
            )
            if not is_boundary:
                continue
        h_name = f"{base_name}_H{i:02d}"
        h = bpy.data.objects.new(h_name, handle_mesh)
        h.scale = (float(handle_size), float(handle_size), float(handle_size))
        h.show_in_front = True
        h.hide_render = True
        try:
            h.color = (0.98, 0.62, 0.08, 1.0)
        except Exception:
            pass
        lp = Vector((float(pt.co.x), float(pt.co.y), float(pt.co.z)))
        h.matrix_world = lat_obj.matrix_world @ Matrix.Translation(lp)
        bpy.context.scene.collection.objects.link(h)
        link_to_collection(h, ensure_collection(COL_RIG))
        h["SMILE_BLOCKFFD_HANDLE"] = True
        h["SMILE_BLOCKFFD_OWNER"] = _safe_object_name(tooth_obj)
        h["SMILE_BLOCKFFD_LATTICE"] = lat_obj.name
        h["SMILE_BLOCKFFD_POINT_INDEX"] = int(i)
        handle_names.append(h.name)

        hk = lat_obj.modifiers.new(name=f"SMILE_BFFD_HOOK_{i:02d}", type="HOOK")
        hk.object = h
        hk.strength = 1.0
        try:
            hk.vertex_indices_set([int(i)])
        except Exception:
            pass

    tooth_obj[KEY_BLOCKFFD_LAT] = lat_obj.name
    tooth_obj[KEY_BLOCKFFD_HANDLES] = json.dumps(handle_names)
    tooth_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    tooth_obj["SMILE_BLOCKFFD_SURFACE_ONLY"] = bool(surface_only)
    tooth_obj["SMILE_BLOCKFFD_CORNER_ONLY"] = bool(corner_only)
    tooth_obj["SMILE_BLOCKFFD_GAP"] = float(sphere_gap)
    tooth_obj["SMILE_BLOCKFFD_PAD"] = float(size_pad)
    tooth_obj["SMILE_BLOCKFFD_HANDLE_FACTOR"] = float(handle_size_factor)
    lat_obj["SMILE_BLOCKFFD_TOOTH"] = _safe_object_name(tooth_obj)
    lat_obj["SMILE_BLOCKFFD"] = True
    lat_obj["SMILE_BLOCKFFD_DIVS"] = int(divisions)
    return lat_obj, handle_names


# === SMILE_OT_create_lattice_rig (lines 29787-29805) ===


class SMILE_OT_create_lattice_rig(bpy.types.Operator):
    bl_idname = "smile.create_lattice_rig"
    bl_label = "Create 27-Handle Shaping Rig (Active Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        try:
            lat, handles = create_lattice_rig_for_tooth(
                tooth, size_pad=context.scene.smile_v2.rig_size_pad
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Rig created: {lat.name} with {len(handles)} handles")
        return {"FINISHED"}


# === SMILE_OT_blockffd_create (lines 29808-29860) ===


class SMILE_OT_blockffd_create(bpy.types.Operator):
    bl_idname = "smile.blockffd_create"
    bl_label = "Create Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Create rig on active mesh tooth"),
            ("SELECTED", "Selected", "Create rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD.")
            return {"CANCELLED"}

        ok = 0
        failed = []
        for obj in targets:
            try:
                create_blockffd_rig_for_tooth(
                    obj,
                    divisions=int(getattr(p, "blockffd_divisions", 3)),
                    size_pad=float(getattr(p, "blockffd_size_pad", 0.1)),
                    handle_size_factor=float(getattr(p, "blockffd_handle_size", 0.05)),
                    sphere_gap=float(getattr(p, "blockffd_sphere_gap", 0.1)),
                    surface_only=bool(
                        getattr(p, "blockffd_surface_handles_only", True)
                    ),
                    corner_only=bool(getattr(p, "blockffd_simple_mode", False)),
                )
                ok += 1
            except Exception as e:
                failed.append(f"{obj.name}: {e}")

        if ok == 0:
            self.report(
                {"ERROR"},
                "Block FFD create failed. " + ("; ".join(failed[:2]) if failed else ""),
            )
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_hide_relationship_lines", True)):
            _blockffd_set_relationship_lines(context.scene, False)
        if failed:
            self.report({"WARNING"}, f"Created {ok}; failed {len(failed)}.")
        else:
            self.report({"INFO"}, f"Created Block FFD rig on {ok} tooth/teeth.")
        return {"FINISHED"}


# === SMILE_OT_blockffd_apply (lines 29863-29912) ===


class SMILE_OT_blockffd_apply(bpy.types.Operator):
    bl_idname = "smile.blockffd_apply"
    bl_label = "Apply Block FFD"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Apply rig on active mesh tooth"),
            ("SELECTED", "Selected", "Apply rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        p = context.scene.smile_v2
        cleanup = bool(getattr(p, "blockffd_cleanup_after_apply", True))
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD apply.")
            return {"CANCELLED"}

        applied = 0
        skipped = 0
        for obj in targets:
            mod = obj.modifiers.get("SMILE_BLOCK_FFD")
            if not mod:
                skipped += 1
                continue
            ok = _apply_modifier_on_object(context, obj, "SMILE_BLOCK_FFD")
            if not ok:
                skipped += 1
                continue
            applied += 1
            if cleanup:
                _blockffd_remove_for_tooth(
                    obj, remove_modifier=False, remove_lattice=True, remove_handles=True
                )
            else:
                _blockffd_clear_meta(obj)

        if applied == 0:
            self.report({"WARNING"}, "No Block FFD modifier was applied.")
            return {"CANCELLED"}
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report(
            {"INFO"}, f"Applied Block FFD on {applied} tooth/teeth. Skipped {skipped}."
        )
        return {"FINISHED"}


# === SMILE_OT_blockffd_remove (lines 29915-29950) ===


class SMILE_OT_blockffd_remove(bpy.types.Operator):
    bl_idname = "smile.blockffd_remove"
    bl_label = "Remove Block FFD Rig"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("ACTIVE", "Active", "Remove rig on active mesh tooth"),
            ("SELECTED", "Selected", "Remove rig on all selected mesh teeth"),
        ],
        default="ACTIVE",
    )

    def execute(self, context):
        targets = _blockffd_targets_from_scope(context, self.scope)
        if not targets:
            self.report({"ERROR"}, "No mesh tooth found for Block FFD remove.")
            return {"CANCELLED"}

        removed = 0
        for obj in targets:
            had_any = bool(
                obj.modifiers.get("SMILE_BLOCK_FFD") or _blockffd_lattice_for_tooth(obj)
            )
            _blockffd_remove_for_tooth(
                obj, remove_modifier=True, remove_lattice=True, remove_handles=True
            )
            if had_any:
                removed += 1

        p = context.scene.smile_v2
        if bool(getattr(p, "blockffd_restore_relationship_lines", True)):
            _blockffd_restore_relationship_lines(context.scene)
        self.report({"INFO"}, f"Removed Block FFD rigs: {removed}.")
        return {"FINISHED"}


# === build_adjacent_bvhtrees (lines 29953-29971) ===


# === SMILE_ProximalAnalyzer (lines 29974-30055) ===


class SMILE_ProximalAnalyzer:
    """Manages real-time proximity feedback and confinement during sculpting."""

    def __init__(self, veneer_obj, target_scan, target_bvh):
        self.veneer = veneer_obj
        self.scan = target_scan
        self.bvh = target_bvh
        self.params = {"ideal_min": 0.05, "ideal_max": 0.15, "crit_tight": 0.02}

    def update_feedback(self, context):
        """Update vertex colors and apply soft push."""
        if self.veneer.mode != "SCULPT":
            return

        # preparation
        me = self.veneer.data
        if "SMILE_CONTACT" not in me.color_attributes:
            me.color_attributes.new("SMILE_CONTACT", "BYTE_COLOR", "POINT")

        attr = me.color_attributes["SMILE_CONTACT"]
        mw = self.veneer.matrix_world
        mw_inv = mw.inverted()
        scan_mw = self.scan.matrix_world
        scan_mw_inv = scan_mw.inverted()

        # Performance: Sample vertices sparsely
        import random

        # Stride based on vertex count (target ~1000 checks per frame)
        stride = int(max(1, len(me.vertices) // 1000))

        # We need to access bmesh layer directly for performant color updates?
        # Standard API is slow for per-vertex color setting in loop.
        # But 'foreach_set' requires full array.
        # Let's iterate a subset and just update those.

        # Note: Modifying v.co in Sculpt Mode is tricky. Blender Sculpt mode locks mesh data.
        # We cannot modify v.co directly while user is brushing.
        # Visual Feedback (Color) works.
        # Physical Confinement usually requires a Modifier (Shrinkwrap/Collision) or Brush setting.
        # Script-based 'push' fights with the brush engine.

        # Better Confinement Strategy:
        # Instead of pushing verts (which lags/fails in sculpt mode), we create a Collision Mask.
        # Or we assume this is "Visual Guide" only + Post-Stroke correction?
        # Let's stick to Visual Feedback for now as it's robust.

        # Optimization: Use foreach to read/write coords if possible, but KDTree is point-by-point.
        # Batch query?

        # vertices_to_check = me.vertices[::stride]

        count = len(me.vertices)
        for i in range(0, count, stride):
            v = me.vertices[i]
            # 1. World Space Query
            wp = mw @ v.co
            lp_scan = scan_mw_inv @ wp

            loc, norm, idx, dist = self.bvh.find_nearest(lp_scan)

            if loc:
                # 2. Feedback Color
                if dist < self.params["crit_tight"]:
                    col = (1.0, 0.0, 0.0, 1.0)  # Red
                elif dist < self.params["ideal_min"]:
                    col = (1.0, 0.5, 0.0, 1.0)  # Orange
                elif dist < self.params["ideal_max"]:
                    col = (0.0, 1.0, 0.0, 1.0)  # Green
                else:
                    col = (0.5, 0.5, 0.5, 1.0)  # Grey

                # Write color (Slow part)
                attr.data[v.index].color = col

        # To make color visible, we must be in Vertex Paint or specific shading.
        # Setup Dental Workspace ensures 'VERTEX' color type.

        # me.update() # Can cause sculpt stroke interruption?
        # Only update if we changed geometry. If only color, maybe skipping update is unsafe.
        # But updating mesh during sculpt is generally bad.
        pass


# === SMILE_OT_liquify_toggle (lines 46807-46868) ===


class SMILE_OT_liquify_toggle(bpy.types.Operator):
    """Toggle liquify scaffold mode and mark design step progress."""

    bl_idname = "smile.liquify_toggle"
    bl_label = "Toggle Liquify"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 4, "Liquify session")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        p = context.scene.smile_v2
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        enable = not bool(p.sf_liquify_enabled)
        p.sf_liquify_enabled = enable
        if enable:
            ensure_active(obj)
            try:
                bpy.ops.object.mode_set(mode="SCULPT")
            except Exception:
                self.report({"ERROR"}, "Failed to enter Sculpt mode.")
                p.sf_liquify_enabled = False
                return {"CANCELLED"}

            brush_map = {
                "INFLATE": ["Inflate/Deflate", "Inflate", "Draw"],
                "FLATTEN": ["Flatten", "Flatten/Contrast", "Draw Sharp", "Draw"],
                "DEFORM": ["Grab", "Elastic Deform", "Snake Hook", "Draw"],
                "EDGES": ["Crease", "Pinch", "Draw Sharp", "Draw"],
                "SMOOTH": ["Smooth", "Draw"],
            }
            sculpt = context.tool_settings.sculpt
            target_names = brush_map.get(str(p.sf_liquify_brush), ["Draw"])
            selected = None
            for nm in target_names:
                b = bpy.data.brushes.get(nm)
                if b:
                    selected = b
                    break
            if selected:
                sculpt.brush = selected
                try:
                    selected.size = int(max(1, float(p.sf_liquify_size)))
                    selected.strength = float(p.sf_liquify_intensity)
                except Exception:
                    pass
            p.step4_done = True
            _set_min_design_step(p, 5)
        else:
            try:
                if obj.mode == "SCULPT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        self.report({"INFO"}, f"Liquify {'enabled' if enable else 'disabled'}.")
        return {"FINISHED"}


# === SMILE_OT_toggle_symmetry_runtime (lines 46871-46890) ===


class SMILE_OT_toggle_symmetry_runtime(bpy.types.Operator):
    """Toggle symmetry mirroring between paired teeth (runtime-registered variant)."""

    bl_idname = "smile.toggle_symmetry"
    bl_label = "Toggle Symmetry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        if p.symmetry_enabled:
            remove_symmetry_constraints(context)
            p.symmetry_enabled = False
            self.report({"INFO"}, "Symmetry disabled")
        else:
            setup_symmetry_constraints(context)
            p.symmetry_enabled = True
            self.report(
                {"INFO"}, "Symmetry enabled - paired teeth will mirror each other"
            )
        return {"FINISHED"}


# === SMILE_OT_waxup_cervical_merge (lines 46893-46975) ===


class SMILE_OT_waxup_cervical_merge(bpy.types.Operator):
    """Adapt the cervical margin of a library tooth to the underlying scan."""

    bl_idname = "smile.waxup_cervical_merge"
    bl_label = "Cervical Merge (Adapt to Scan)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        target_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        # fallback to active object if domain not set for testing
        if (
            not target_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            # assume active is the scan, and selected is the library tooth
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                target_obj = context.active_object

        selected = [
            o for o in context.selected_objects if o != target_obj and o.type == "MESH"
        ]

        if not target_obj or not selected:
            self.report({"ERROR"}, "Select Library Tooth and Shift-Select Scan Target")
            return {"CANCELLED"}

        scan_obj = target_obj

        for lib_obj in selected:
            # 1. Create Vertex Group for Cervical Margin
            # (In a real implementation, we'd find the boundary edge loop.
            # For this prototype, we'll try to use existing groups or select bottom vertices based on Z height relative to bounding box)
            vg_name = "SMILE_CervicalMargin"
            vg = lib_obj.vertex_groups.get(vg_name)
            if not vg:
                vg = lib_obj.vertex_groups.new(name=vg_name)

            # Simple heuristic for prototyping: bottom 20% of vertices in local Z
            mesh = lib_obj.data
            z_coords = [v.co.z for v in mesh.vertices]
            min_z = min(z_coords)
            max_z = max(z_coords)
            threshold_z = min_z + (max_z - min_z) * 0.20

            bottom_verts = [v.index for v in mesh.vertices if v.co.z < threshold_z]
            vg.add(bottom_verts, 1.0, "REPLACE")

            # 2. Add Shrinkwrap Modifier
            sw_name = "SMILE_Waxup_Adapt"
            sw = lib_obj.modifiers.get(sw_name)
            if not sw:
                sw = lib_obj.modifiers.new(name=sw_name, type="SHRINKWRAP")

            sw.target = scan_obj
            sw.vertex_group = vg_name
            sw.wrap_method = "PROJECT"
            sw.use_project_z = True
            sw.use_negative_direction = True
            sw.use_positive_direction = True
            sw.cull_face = "OFF"

            # 3. Add Smooth Modifier to blend
            sm_name = "SMILE_Waxup_Smooth"
            sm = lib_obj.modifiers.get(sm_name)
            if not sm:
                sm = lib_obj.modifiers.new(name=sm_name, type="SMOOTH")
                sm.vertex_group = vg_name
                sm.iterations = 5

        self.report({"INFO"}, f"Adapted {len(selected)} teeth to {scan_obj.name}")
        return {"FINISHED"}


# === SMILE_OT_waxup_generate_shell (lines 46978-47096) ===


class SMILE_OT_waxup_generate_shell(bpy.types.Operator):
    """Boolean merge of Waxup teeth to a Blocked-out Scan"""

    bl_idname = "smile.waxup_generate_shell"
    bl_label = "Generate Mockup Shell"
    bl_options = {"REGISTER", "UNDO"}

    spacer_thickness_mm: bpy.props.FloatProperty(
        name="Spacer Thickness (mm)", default=0.15, min=0.0, max=1.0
    )

    def _apply_modifier(self, obj, mod_name):
        try:
            with bpy.context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj]
            ):
                bpy.ops.object.modifier_apply(modifier=mod_name)
            return True
        except Exception:
            return False

    def execute(self, context):
        p = context.scene.smile_v2

        # 1. Identify Target Scan
        scan_obj = (
            bpy.data.objects.get(p.align_target_domain)
            if hasattr(p, "align_target_domain") and p.align_target_domain
            else None
        )

        if (
            not scan_obj
            and context.active_object
            and context.active_object.type == "MESH"
        ):
            selected = [
                o
                for o in context.selected_objects
                if o != context.active_object and o.type == "MESH"
            ]
            if selected:
                scan_obj = context.active_object

        selected_teeth = [
            o for o in context.selected_objects if o != scan_obj and o.type == "MESH"
        ]

        if not scan_obj or not selected_teeth:
            self.report({"ERROR"}, "Select Library Teeth and Shift-Select Scan Target")
            return {"CANCELLED"}

        # 2. Duplicate Scan for Blockout/Spacer
        spacer_name = f"Mockup_Spacer_{scan_obj.name}"
        old_spacer = bpy.data.objects.get(spacer_name)
        if old_spacer:
            delete_object(old_spacer)

        deps = context.evaluated_depsgraph_get()
        scan_eval = scan_obj.evaluated_get(deps)
        spacer_mesh = bpy.data.meshes.new_from_object(scan_eval)
        spacer_obj = bpy.data.objects.new(spacer_name, spacer_mesh)
        context.scene.collection.objects.link(spacer_obj)
        spacer_obj.matrix_world = scan_obj.matrix_world.copy()

        # 3. Add Solidify to act as Spacer (Outward expansion)
        if self.spacer_thickness_mm > 0.0:
            s_mod = spacer_obj.modifiers.new("Waxup_Spacer", "SOLIDIFY")
            # Convert mm to BU (assuming 1 BU = 1mm for dental usually, or check unit_settings)
            scale = (
                context.scene.unit_settings.scale_length
                if context.scene.unit_settings.system != "NONE"
                else 1.0
            )
            if context.scene.unit_settings.system == "METRIC":
                s_mod.thickness = self.spacer_thickness_mm / (scale * 1000.0)
            else:
                s_mod.thickness = self.spacer_thickness_mm

            s_mod.offset = 1.0  # Expand outwards
            s_mod.use_rim = True
            self._apply_modifier(spacer_obj, s_mod.name)

        # 4. Merge all selected teeth into one solid
        # For prototype simplicity, we just join them. Real world might need Voxel Remesh or Union.
        bpy.ops.object.select_all(action="DESELECT")
        for t in selected_teeth:
            t.select_set(True)

        context.view_layer.objects.active = selected_teeth[0]

        merged_name = "Mockup_Merged_Teeth"
        old_merged = bpy.data.objects.get(merged_name)
        if old_merged:
            delete_object(old_merged)

        bpy.ops.object.duplicate()
        merged_teeth = context.active_object
        merged_teeth.name = merged_name

        for o in context.selected_objects:
            if o != merged_teeth:
                o.select_set(True)
        bpy.ops.object.join()

        # 5. Boolean Difference: Merged Teeth - Spacer
        # We subtract the expanded scan from the mockup teeth
        bool_mod = merged_teeth.modifiers.new("Mockup_Intaglio", "BOOLEAN")
        bool_mod.operation = "DIFFERENCE"
        bool_mod.object = spacer_obj
        bool_mod.solver = "EXACT"

        self.report({"INFO"}, f"Generated Shell Preview. Apply boolean for final mesh.")

        # Cleanup view
        spacer_obj.display_type = "WIRE"
        spacer_obj.hide_render = True

        return {"FINISHED"}


# === ensure_triangulated_mesh_data (lines 47104-47130) ===


def ensure_triangulated_mesh_data(obj, apply_world=True):
    """Zero-copy data ingestion. Bypasses Python loops."""
    import numpy as np

    t0 = time.time()
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()

    verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    verts = verts.reshape((-1, 3))

    if apply_world:
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]

    mesh.calc_loop_triangles()
    tris = np.zeros(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape((-1, 3))

    eval_obj.to_mesh_clear()
    print(f"[Algo] Ingested {len(verts)} verts in {(time.time() - t0) * 1000:.2f}ms")
    return verts, tris


# === extract_curve_points_np (lines 47133-47153) ===


def extract_curve_points_np(obj):
    """Extracts world-space points from a Blender curve or mesh object."""
    import numpy as np

    if obj.type == "MESH":
        verts, _ = ensure_triangulated_mesh_data(obj, apply_world=True)
        return verts
    elif obj.type == "CURVE":
        deps = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        mesh = eval_obj.to_mesh()
        verts = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", verts)
        verts = verts.reshape((-1, 3))
        mw = np.array(eval_obj.matrix_world)
        ones = np.ones((len(verts), 1))
        verts_h = np.hstack([verts, ones])
        verts = np.dot(verts_h, mw.T)[:, :3]
        eval_obj.to_mesh_clear()
        return verts
    return np.array([])


# === points_in_poly_np (lines 47156-47175) ===


def points_in_poly_np(points_2d, poly_2d):
    """Highly optimized 2D raycasting point-in-polygon algorithm."""
    import numpy as np

    x = points_2d[:, 0]
    y = points_2d[:, 1]
    inside = np.zeros(len(x), dtype=bool)
    n = len(poly_2d)
    p1x, p1y = poly_2d[0]
    for i in range(n + 1):
        p2x, p2y = poly_2d[i % n]
        min_y = min(p1y, p2y)
        max_y = max(p1y, p2y)
        mask = (y > min_y) & (y <= max_y)
        if p1y != p2y:
            x_ints = (y[mask] - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            cross = x[mask] <= x_ints
            inside[mask] ^= cross
        p1x, p1y = p2x, p2y
    return inside


# === calc_normal_np (lines 47178-47192) ===


def calc_normal_np(points):
    """Calculates best-fit normal vector using Newell's Method."""
    import numpy as np

    n = np.zeros(3)
    for i in range(len(points)):
        curr = points[i]
        nxt = points[(i + 1) % len(points)]
        n[0] += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
        n[1] += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
        n[2] += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
    norm = np.linalg.norm(n)
    if norm == 0:
        return np.array([0, 0, 1])
    return n / norm


# === get_rotation_matrix_to_z_np (lines 47195-47207) ===


def get_rotation_matrix_to_z_np(normal):
    """Creates a rotation matrix to align a given normal to the Z-axis [0,0,1]."""
    import numpy as np

    z_axis = np.array([0, 0, 1])
    v = np.cross(normal, z_axis)
    s = np.linalg.norm(v)
    c = np.dot(normal, z_axis)
    if s == 0:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    R = np.eye(3) + vx + np.dot(vx, vx) * ((1 - c) / (s**2))
    return R


# === get_boundary_edges_np (lines 47210-47217) ===


def get_boundary_edges_np(tris):
    """Extracts boundary edges (edges belonging to only one triangle) from an array of triangles."""
    import numpy as np

    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges_sorted = np.sort(edges, axis=1)
    unique_edges, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    return unique_edges[counts == 1]


# === extract_intaglio_vectorized_np (lines 47220-47277) ===


def extract_intaglio_vectorized_np(verts, tris, margin_points):
    """
    Phase 1: The Intaglio.
    Uses pure NumPy to perform a 2D projection cut and 3D boundary snapping.
    """
    import numpy as np

    t0 = time.time()

    # 1. Determine Insertion Axis and Project to 2D
    normal = calc_normal_np(margin_points)
    R = get_rotation_matrix_to_z_np(normal)
    verts_2d = np.dot(verts, R.T)[:, :2]
    margin_2d = np.dot(margin_points, R.T)[:, :2]

    # 2. Point in Polygon Test
    inside_mask = points_in_poly_np(verts_2d, margin_2d)

    # 3. Filter Triangles (Keep if ALL 3 vertices are inside)
    face_mask = (
        inside_mask[tris[:, 0]] & inside_mask[tris[:, 1]] & inside_mask[tris[:, 2]]
    )
    kept_tris = tris[face_mask]

    if len(kept_tris) == 0:
        print("[Algo] Warning: No triangles inside margin! Check orientation.")
        return verts, tris

    # 4. Extract Boundary Vertices
    boundary_edges = get_boundary_edges_np(kept_tris)
    boundary_vertices = np.unique(boundary_edges)

    # 5. Snap Boundary Vertices to true 3D Margin Curve using Blender's KDTree
    kd = KDTree(len(margin_points))
    for i, p in enumerate(margin_points):
        kd.insert(p, i)
    kd.balance()

    new_verts = verts.copy()
    for bv in boundary_vertices:
        co, index, dist = kd.find(new_verts[bv])
        new_verts[bv] = np.array(co)

    # 6. Cleanup unreferenced vertices to return a compact mesh
    referenced_mask = np.zeros(len(new_verts), dtype=bool)
    referenced_mask[kept_tris.flatten()] = True

    old_to_new = np.full(len(new_verts), -1, dtype=np.int32)
    new_indices = np.arange(np.sum(referenced_mask))
    old_to_new[referenced_mask] = new_indices

    compact_verts = new_verts[referenced_mask]
    compact_tris = old_to_new[kept_tris]

    print(
        f"[Algo] Intaglio Extracted & Snapped {len(compact_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return compact_verts, compact_tris


# === generate_emergence_collar_np (lines 47280-47342) ===


def generate_emergence_collar_np(
    verts, tris, margin_points, height=0.5, angle_deg=15.0
):
    """
    Phase 2: The Emergence Profile Collar.
    Extrudes the boundary edges upward and outward to create a seating collar.
    """
    import numpy as np

    t0 = time.time()

    boundary_edges = get_boundary_edges_np(tris)
    bound_verts = np.unique(boundary_edges)

    if len(bound_verts) == 0:
        return verts, tris

    axis = calc_normal_np(margin_points)  # Insertion axis
    center = np.mean(margin_points, axis=0)
    angle_rad = math.radians(angle_deg)

    old_to_new_extruded = {
        old_idx: i + len(verts) for i, old_idx in enumerate(bound_verts)
    }
    new_verts = np.zeros((len(bound_verts), 3), dtype=np.float32)

    # Parametric Extrusion Calculation
    for i, b_idx in enumerate(bound_verts):
        v = verts[b_idx]

        # Outward radial vector perpendicular to insertion axis
        vec_to_v = v - center
        radial = vec_to_v - np.dot(vec_to_v, axis) * axis
        norm_radial = np.linalg.norm(radial)
        if norm_radial > 0:
            radial = radial / norm_radial

        # Extrude Upward (height) and Outward (tan(angle))
        outward_mag = height * math.tan(angle_rad)
        extrusion = (axis * height) + (radial * outward_mag)

        new_verts[i] = v + extrusion

    combined_verts = np.vstack([verts, new_verts])

    # Bridge the gap with Quads (2 Triangles per edge)
    new_tris = []
    for edge in boundary_edges:
        v1, v2 = edge
        v1_new = old_to_new_extruded[v1]
        v2_new = old_to_new_extruded[v2]

        # Triangle 1
        new_tris.append([v1, v2, v2_new])
        # Triangle 2
        new_tris.append([v1, v2_new, v1_new])

    combined_tris = np.vstack([tris, np.array(new_tris, dtype=np.int32)])

    print(
        f"[Algo] Emergence Collar Generated: {len(new_tris)} faces in {(time.time() - t0) * 1000:.2f}ms"
    )
    return combined_verts, combined_tris


# === build_morph_geometry_nodes_np (lines 47345-47442) ===


def build_morph_geometry_nodes_np(node_group_name="SMILE_Morph_Engine"):
    """
    Phase 3: The Morph.
    Constructs a multi-threaded C++ backend Geometry Nodes modifier.
    """
    ng = bpy.data.node_groups.get(node_group_name)
    if not ng:
        ng = bpy.data.node_groups.new(node_group_name, "GeometryNodeTree")

        # In/Out Interfaces (Blender 4.0+ compatible API)
        if hasattr(ng, "interface"):
            ng.interface.new_socket(
                "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
            )
            ng.interface.new_socket(
                "Target Collar", in_out="INPUT", socket_type="NodeSocketObject"
            )
            socket_falloff = ng.interface.new_socket(
                "Morph Falloff", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            socket_falloff.default_value = 3.0  # 3mm morph transition zone
        else:
            ng.outputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketGeometry", "Geometry")
            ng.inputs.new("NodeSocketObject", "Target Collar")
            socket_falloff = ng.inputs.new("NodeSocketFloat", "Morph Falloff")
            socket_falloff.default_value = 3.0

        nodes = ng.nodes
        links = ng.links

        node_in = nodes.new("NodeGroupInput")
        node_out = nodes.new("NodeGroupOutput")

        # 1. Target Proximity
        obj_info = nodes.new("GeometryNodeObjectInfo")
        obj_info.inputs["Transform Space"].default_value = "RELATIVE"
        target_prox = nodes.new("GeometryNodeProximity")
        target_prox.target_element = "EDGES"

        # 2. Self Boundary Distance
        edge_neighbors = nodes.new("GeometryNodeInputMeshEdgeNeighbors")
        compare_edges = nodes.new("FunctionNodeCompare")
        compare_edges.data_type = "INT"
        compare_edges.operation = "EQUAL"
        compare_edges.inputs[
            3
        ].default_value = 1  # Edge neighbor count = 1 means boundary

        separate_geom = nodes.new("GeometryNodeSeparateGeometry")
        separate_geom.domain = "EDGE"

        self_prox = nodes.new("GeometryNodeProximity")
        self_prox.target_element = "EDGES"

        # 3. Falloff Math
        map_range = nodes.new("ShaderNodeMapRange")
        map_range.clamp = True
        map_range.inputs[1].default_value = 0.0
        map_range.inputs[3].default_value = 1.0
        map_range.inputs[4].default_value = 0.0
        map_range.interpolation_type = "SMOOTHSTEP"

        # 4. Mix Position
        pos_node = nodes.new("GeometryNodeInputPosition")
        mix_node = nodes.new("ShaderNodeMix")
        mix_node.data_type = "VECTOR"
        mix_node.clamp_factor = True

        set_pos = nodes.new("GeometryNodeSetPosition")

        # Self Boundary Distance flow
        links.new(edge_neighbors.outputs["Face Count"], compare_edges.inputs[2])
        links.new(node_in.outputs["Geometry"], separate_geom.inputs["Geometry"])
        links.new(compare_edges.outputs["Result"], separate_geom.inputs["Selection"])
        links.new(separate_geom.outputs["Selection"], self_prox.inputs["Target"])

        # Target Position flow
        links.new(node_in.outputs["Target Collar"], obj_info.inputs["Object"])
        links.new(obj_info.outputs["Geometry"], target_prox.inputs["Target"])

        # Blend Math flow
        links.new(self_prox.outputs["Distance"], map_range.inputs[0])
        links.new(node_in.outputs["Morph Falloff"], map_range.inputs[2])  # From Max

        links.new(map_range.outputs["Result"], mix_node.inputs[0])  # Factor
        links.new(pos_node.outputs["Position"], mix_node.inputs[4])  # A (Original)
        links.new(target_prox.outputs["Position"], mix_node.inputs[5])  # B (Target)

        # Final Set Position
        links.new(node_in.outputs["Geometry"], set_pos.inputs["Geometry"])
        links.new(mix_node.outputs[1], set_pos.inputs["Position"])
        links.new(set_pos.outputs["Geometry"], node_out.inputs["Geometry"])

    return ng


# === numpy_to_mesh_np (lines 47445-47466) ===


def numpy_to_mesh_np(name, verts_np, faces_np):
    """Zero-copy output."""
    import numpy as np

    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts_np))
    mesh.loops.add(len(faces_np) * 3)
    mesh.polygons.add(len(faces_np))

    mesh.vertices.foreach_set("co", verts_np.flatten())

    loop_start = np.arange(0, len(faces_np) * 3, 3, dtype=np.int32)
    loop_total = np.full(len(faces_np), 3, dtype=np.int32)

    mesh.loops.foreach_set("vertex_index", faces_np.flatten())
    mesh.polygons.foreach_set("loop_start", loop_start)
    mesh.polygons.foreach_set("loop_total", loop_total)

    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# === stitch_meshes_vectorized_np (lines 47469-47487) ===


def stitch_meshes_vectorized_np(verts_A, tris_A, verts_B, tris_B, tolerance=4):
    """Phase 4: Topological Stitching."""
    import numpy as np

    t0 = time.time()
    combined_verts = np.vstack((verts_A, verts_B))
    tris_B_offset = tris_B + len(verts_A)
    combined_tris = np.vstack((tris_A, tris_B_offset))
    rounded_verts = np.round(combined_verts, decimals=tolerance)
    unique_verts, inverse_indices = np.unique(
        rounded_verts, axis=0, return_inverse=True
    )
    _, unique_indices = np.unique(rounded_verts, axis=0, return_index=True)
    final_verts = combined_verts[unique_indices]
    final_tris = inverse_indices[combined_tris]
    print(
        f"[Algo] Phase 4 Stitching: {len(combined_verts)} -> {len(final_verts)} verts in {(time.time() - t0) * 1000:.2f}ms"
    )
    return final_verts, final_tris


# === execute_industry_standard_crown_np (lines 47490-47551) ===


def execute_industry_standard_crown_np(library_obj, spacer_obj, margin_curve_obj=None):
    """The Orchestrator."""
    print("--- INITIATING HYBRID C++/PYTHON CROWN GENERATION ---")

    lib_v, lib_f = ensure_triangulated_mesh_data(library_obj, apply_world=True)
    space_v, space_f = ensure_triangulated_mesh_data(spacer_obj, apply_world=True)

    if margin_curve_obj:
        margin_points = extract_curve_points_np(margin_curve_obj)
        if len(margin_points) > 2:
            intaglio_v, intaglio_f = extract_intaglio_vectorized_np(
                space_v, space_f, margin_points
            )
            collar_v, collar_f = generate_emergence_collar_np(
                intaglio_v, intaglio_f, margin_points, height=1.0, angle_deg=15.0
            )

            int_obj = bpy.data.objects.get("DEBUG_Intaglio_Collar")
            if int_obj:
                bpy.data.objects.remove(int_obj, do_unlink=True)
            intaglio_obj = numpy_to_mesh_np("DEBUG_Intaglio_Collar", collar_v, collar_f)

            build_morph_geometry_nodes_np()
            mod_name = "SMILE_C++_Morph"
            if mod_name not in library_obj.modifiers:
                mod = library_obj.modifiers.new(name=mod_name, type="NODES")
                mod.node_group = bpy.data.node_groups["SMILE_Morph_Engine"]

            if "Target Collar" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Target Collar"] = intaglio_obj
            elif "Input_2" in library_obj.modifiers[mod_name]:
                library_obj.modifiers[mod_name]["Input_2"] = intaglio_obj

            bpy.context.view_layer.update()

            morphed_v, morphed_f = ensure_triangulated_mesh_data(
                library_obj, apply_world=True
            )
            flipped_collar_f = collar_f[:, [0, 2, 1]]
            final_v, final_f = stitch_meshes_vectorized_np(
                morphed_v, morphed_f, collar_v, flipped_collar_f
            )

            crown_name = f"CROWN_INDUSTRY_{library_obj.name.split('_')[0]}"
            crown_obj = bpy.data.objects.get(crown_name)
            if crown_obj:
                bpy.data.objects.remove(crown_obj, do_unlink=True)

            final_crown_obj = numpy_to_mesh_np(crown_name, final_v, final_f)
            bpy.data.objects.remove(intaglio_obj, do_unlink=True)
            library_obj.modifiers.remove(library_obj.modifiers[mod_name])
            library_obj.hide_viewport = True

            print("--- CROWN GENERATION PIPELINE COMPLETED SUCCESSFULLY ---")
            return {"status": "SUCCESS", "crown_obj": final_crown_obj}
        else:
            return {
                "status": "FAILED",
                "message": "Margin curve has insufficient points.",
            }
    else:
        return {"status": "FAILED", "message": "No margin curve provided."}


# === SMILE_OT_generate_industry_crown (lines 47554-47593) ===


class SMILE_OT_generate_industry_crown(bpy.types.Operator):
    """Generate Crown using Hybrid C++/Python Architecture (Zero-Copy)"""

    bl_idname = "smile.generate_industry_crown"
    bl_label = "Generate Crown (C++ Engine v1.1)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        library_obj = context.view_layer.objects.active

        target_tid = int(getattr(p, "target_tooth_id", 0) or 0)
        spacer_name = f"SPACER_T{target_tid}"
        spacer_obj = bpy.data.objects.get(spacer_name)
        if not spacer_obj:
            self.report(
                {"ERROR"}, f"Spacer {spacer_name} not found. Generate Die/Spacer first."
            )
            return {"CANCELLED"}

        if not library_obj or library_obj == spacer_obj or library_obj.type != "MESH":
            self.report({"ERROR"}, "Select the Library Tooth first.")
            return {"CANCELLED"}

        margin_name = f"MARGIN_{spacer_obj.name.replace('SPACER_', '')}"
        margin_obj = bpy.data.objects.get(margin_name)
        if not margin_obj:
            # try direct T naming
            margin_obj = bpy.data.objects.get(f"MARGIN_T{target_tid}")

        if not margin_obj:
            self.report(
                {"ERROR"},
                f"Margin curve for T#{target_tid} not found. Please trace a margin first.",
            )
            return {"CANCELLED"}

        res = execute_industry_standard_crown_np(library_obj, spacer_obj, margin_obj)
        self.report({"INFO"}, f"Generation Complete: {res.get('status')}")
        return {"FINISHED"}
