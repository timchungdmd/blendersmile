"""BlenderSmile GUIDED Tab Module (CAD Wizard)

This module contains the CAD Wizard workflow operators and UI for guided
restoration design (crowns, veneers, bridges). Implements a staged workflow:
    A. Trace Margin
    B. Survey + Blockout
    C. Build Support Margin
    D. Spacer + Safety
    E. Adapt Outer Shell
    F. Finalize Intaglio
    G. Validate Restoration
    H. Export Files
"""

__all__ = [
    "CLASSES",
    "draw_guided_tab",
    "register",
    "unregister",
    "CAD_STAGE_ORDER",
    "CAD_STAGE_LABEL",
    "run_cad_stage",
    "_cad_load_state",
    "_cad_save_state",
    "_cad_reset_state",
    "_cad_handle_result",
]

import json
import traceback
from datetime import datetime

try:
    import bpy
    import bpy.types
    from bpy.props import BoolProperty, StringProperty, IntProperty, EnumProperty
    from mathutils import Vector, Matrix

    _IN_BLENDER = True
except ImportError:
    _IN_BLENDER = False

CAD_STAGE_ORDER = [
    "A_MARGIN",
    "B_SURVEY_BLOCKOUT",
    "C_SUPPORT_MARGIN",
    "D_SPACER_SAFETY",
    "E_ADAPT_OUTER",
    "F_FINALIZE_INTAGLIO",
    "G_VALIDATE",
    "H_EXPORT",
]

CAD_STAGE_LABEL = {
    "A_MARGIN": "A. Trace Margin",
    "B_SURVEY_BLOCKOUT": "B. Survey + Blockout",
    "C_SUPPORT_MARGIN": "C. Build Support Margin",
    "D_SPACER_SAFETY": "D. Spacer + Safety",
    "E_ADAPT_OUTER": "E. Adapt Outer Shell",
    "F_FINALIZE_INTAGLIO": "F. Finalize Intaglio",
    "G_VALIDATE": "G. Validate Restoration",
    "H_EXPORT": "H. Export Files",
}

KEY_CAD_WIZARD_STATE = "SMILE_CAD_WIZARD_STATE"
KEY_CAD_STAGE_REPORT = "SMILE_CAD_STAGE_REPORT"
KEY_CAD_AXIS_FEEDBACK = "SMILE_CAD_AXIS_FEEDBACK"


def _lazy_import_core():
    """Lazy import from core module when running in Blender."""
    if not _IN_BLENDER:
        return None
    try:
        from . import _00_core as core

        return core
    except ImportError:
        pass
    try:
        import sys
        import os

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if base not in sys.path:
            sys.path.insert(0, base)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_00_core", os.path.join(base, "00_core.py")
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception:
        pass
    return None


def _lazy_import_production():
    """Lazy import from production module for margin/die operators."""
    if not _IN_BLENDER:
        return None
    try:
        from . import _05_production as prod

        return prod
    except ImportError:
        pass
    try:
        import sys
        import os

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if base not in sys.path:
            sys.path.insert(0, base)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_05_production", os.path.join(base, "05_production.py")
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception:
        pass
    return None


def _lazy_import_analysis():
    """Lazy import from analysis module."""
    if not _IN_BLENDER:
        return None
    try:
        from . import analysis_03 as analysis
        return analysis
    except ImportError:
        pass
    return None


# ---------------------------------------------------------------------------
# CAD WIZARD — OBJECT / COLLECTION UTILITIES
# ---------------------------------------------------------------------------

def _cad_ensure_collection(name):
    """Ensure a Blender collection exists and is linked to the scene."""
    import bpy
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def _cad_link_to_collection(obj, col):
    """Link object to a specific collection, removing from all others."""
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    if obj.name not in col.objects:
        col.objects.link(obj)


def _cad_delete_object(name_or_obj):
    """Safely delete an object by name or reference."""
    import bpy
    if isinstance(name_or_obj, str):
        obj = bpy.data.objects.get(name_or_obj)
    else:
        obj = name_or_obj
    if not obj:
        return
    data = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and getattr(data, "users", 1) == 0 and isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)


def _cad_find_prep_scan(scene, tid):
    """Find the prep scan mesh for a tooth ID.

    Priority: explicit SMILE_SCAN_TID tag → Scans collection name match →
    any mesh with matching tooth ID in name → active mesh object.
    """
    import bpy, re
    tid = int(tid)
    pat = re.compile(r"(?:_T|TOOTH[_]?)(0*)" + str(tid) + r"(?:\D|$)", re.IGNORECASE)

    for obj in bpy.data.objects:
        if obj.type == "MESH" and int(obj.get("SMILE_SCAN_TID", -1)) == tid:
            return obj

    col = bpy.data.collections.get("Scans")
    if col:
        for obj in col.objects:
            if obj.type == "MESH" and pat.search(obj.name):
                return obj

    for obj in bpy.data.objects:
        if obj.type == "MESH" and pat.search(obj.name):
            return obj

    active = getattr(getattr(bpy.context, "view_layer", None), "objects", None)
    if active:
        a = getattr(active, "active", None)
        if a and a.type == "MESH":
            return a
    return None


def _cad_find_typed_object(tid, cad_type):
    """Find first object tagged SMILE_CAD_TID==tid and SMILE_CAD_TYPE==cad_type."""
    import bpy
    tid = int(tid)
    for obj in bpy.data.objects:
        if (int(obj.get("SMILE_CAD_TID", -1)) == tid
                and str(obj.get("SMILE_CAD_TYPE", "")) == cad_type):
            return obj
    return None


def _json_obj(value, default=None):
    """Parse JSON string safely, return default on failure."""
    if default is None:
        default = {}
    if not value:
        return default
    try:
        if isinstance(value, (dict, list)):
            return value
        result = json.loads(str(value))
        if isinstance(result, (dict, list)):
            return result
        return default
    except Exception:
        return default


def _cad_nowz():
    return datetime.utcnow().isoformat() + "Z"


def _cad_stage_index(stage):
    try:
        return CAD_STAGE_ORDER.index(str(stage))
    except Exception:
        return -1


def _cad_default_state(scene):
    p = scene.smile_v2
    tid = int(
        getattr(p, "cad_target_tooth_id", 0) or getattr(p, "target_tooth_id", 8) or 8
    )
    mode = str(getattr(p, "cad_case_mode", "VENEER") or "VENEER")
    stages = {}
    for st in CAD_STAGE_ORDER:
        stages[st] = {
            "status": "PENDING",
            "message": "",
            "timestamp_utc": "",
            "outputs": {},
            "metrics": {},
        }
    return {
        "version": 1,
        "updated_utc": _cad_nowz(),
        "case_mode": mode,
        "target_tooth_id": int(tid),
        "stages": stages,
    }


def _cad_load_state(scene):
    raw = scene.get(KEY_CAD_WIZARD_STATE, "")
    if not raw:
        return _cad_default_state(scene)
    try:
        st = json.loads(str(raw))
        if not isinstance(st, dict):
            return _cad_default_state(scene)
        if not isinstance(st.get("stages"), dict):
            st["stages"] = {}
        for key in CAD_STAGE_ORDER:
            if key not in st["stages"] or not isinstance(st["stages"].get(key), dict):
                st["stages"][key] = {
                    "status": "PENDING",
                    "message": "",
                    "timestamp_utc": "",
                    "outputs": {},
                    "metrics": {},
                }
            st["stages"][key].setdefault("status", "PENDING")
            st["stages"][key].setdefault("message", "")
            st["stages"][key].setdefault("timestamp_utc", "")
            st["stages"][key].setdefault("outputs", {})
            st["stages"][key].setdefault("metrics", {})
        st.setdefault("version", 1)
        st.setdefault("updated_utc", _cad_nowz())
        st.setdefault("case_mode", str(scene.smile_v2.cad_case_mode))
        st.setdefault(
            "target_tooth_id",
            int(
                scene.smile_v2.cad_target_tooth_id
                or scene.smile_v2.target_tooth_id
                or 8
            ),
        )
        return st
    except Exception:
        return _cad_default_state(scene)


def _cad_save_state(scene, st):
    if not isinstance(st, dict):
        st = _cad_default_state(scene)
    st["updated_utc"] = _cad_nowz()
    scene[KEY_CAD_WIZARD_STATE] = json.dumps(st, sort_keys=True)
    return st


def _cad_update_stage(scene, stage, status, message="", outputs=None, metrics=None):
    st = _cad_load_state(scene)
    stages = st.get("stages", {})
    rec = stages.get(
        stage,
        {
            "status": "PENDING",
            "message": "",
            "timestamp_utc": "",
            "outputs": {},
            "metrics": {},
        },
    )
    rec["status"] = str(status)
    rec["message"] = str(message or "")
    rec["timestamp_utc"] = _cad_nowz()
    rec["outputs"] = dict(outputs or {})
    rec["metrics"] = dict(metrics or {})
    stages[str(stage)] = rec
    st["stages"] = stages
    st["last_message"] = str(message or "")
    st["case_mode"] = str(scene.smile_v2.cad_case_mode)
    st["target_tooth_id"] = int(
        scene.smile_v2.cad_target_tooth_id or scene.smile_v2.target_tooth_id or 8
    )
    _cad_save_state(scene, st)
    return rec


def _cad_reset_state(scene):
    st = _cad_default_state(scene)
    _cad_save_state(scene, st)
    try:
        if KEY_CAD_AXIS_FEEDBACK in scene:
            del scene[KEY_CAD_AXIS_FEEDBACK]
    except Exception:
        pass
    return st


def _cad_stage_status(scene, stage):
    st = _cad_load_state(scene)
    return str(
        (st.get("stages", {}).get(str(stage), {}) or {}).get("status", "PENDING")
    )


def _cad_get_stage_retry_hint(scene, stage):
    st = _cad_load_state(scene)
    rec = _json_obj((st.get("stages", {}) or {}).get(str(stage), {}), default={})
    metrics = _json_obj(rec.get("metrics", {}), default={})
    return {
        "status": str(rec.get("status", "PENDING")).upper(),
        "message": str(rec.get("message", "") or ""),
        "metrics": metrics,
    }


def _cad_prev_stage(stage):
    idx = _cad_stage_index(stage)
    if idx <= 0:
        return None
    return CAD_STAGE_ORDER[idx - 1]


def _cad_state_context_mismatch(scene, st=None):
    st = st if isinstance(st, dict) else _cad_load_state(scene)
    p = scene.smile_v2
    state_tid = int(st.get("target_tooth_id", 0) or 0)
    state_mode = str(st.get("case_mode", "") or "")
    live_tid = int(
        getattr(p, "cad_target_tooth_id", 0) or getattr(p, "target_tooth_id", 8) or 8
    )
    live_mode = str(getattr(p, "cad_case_mode", "VENEER") or "VENEER")
    if state_tid != live_tid:
        return True, f"Saved case is T#{state_tid}; current CAD target is T#{live_tid}."
    if state_mode != live_mode:
        return (
            True,
            f"Saved case mode is {state_mode}; current CAD mode is {live_mode}.",
        )
    return False, ""


def _cad_gate_ok(scene, stage, enforce=True):
    if not bool(enforce):
        return True, ""

    st = _cad_load_state(scene)
    mismatch, reason = _cad_state_context_mismatch(scene, st=st)
    if mismatch:
        return False, f"{reason} Resume saved case or start a new case."

    prev = _cad_prev_stage(stage)
    if not prev:
        return True, ""
    s = _cad_stage_status(scene, prev)
    if s == "PASS":
        return True, ""
    return (
        False,
        f"{CAD_STAGE_LABEL.get(prev, prev)} must PASS before {CAD_STAGE_LABEL.get(stage, stage)}.",
    )


def _cad_state_for_report(scene):
    st = _cad_load_state(scene)
    return _json_obj(st, default={})


def _cad_target_tid(scene):
    p = scene.smile_v2
    tid = int(getattr(p, "cad_target_tooth_id", 0) or 0)
    if tid <= 0:
        tid = int(getattr(p, "target_tooth_id", 8) or 8)
    return int(tid)


def _cad_handle_result(operator, result):
    ok = bool((result or {}).get("ok", False))
    msg = str((result or {}).get("message", ""))
    if ok:
        operator.report({"INFO"}, msg or "CAD stage completed.")
        return {"FINISHED"}
    if str((result or {}).get("status", "")).upper() == "IN_PROGRESS":
        operator.report({"INFO"}, msg or "CAD stage in progress.")
        return {"FINISHED"}
    operator.report({"ERROR"}, msg or "CAD stage failed.")
    return {"CANCELLED"}


# ---------------------------------------------------------------------------
# CAD WIZARD — GEOMETRY HELPERS
# ---------------------------------------------------------------------------

def _cad_get_axis_vec(scene):
    """Return insertion axis Vector from current mode (AUTO/VIEW/MANUAL)."""
    import bpy
    from mathutils import Vector
    p = scene.smile_v2
    mode = str(getattr(p, "cad_insertion_axis_mode", "AUTO"))
    if mode == "MANUAL":
        raw = getattr(p, "cad_insertion_axis_vec", None)
        if raw:
            v = Vector(raw)
            if v.length > 1e-6:
                return v.normalized()
    if mode == "VIEW":
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                rv3d = area.spaces[0].region_3d
                if rv3d:
                    return (-Vector(rv3d.view_matrix.row[2][:3])).normalized()
    return Vector((0.0, 0.0, 1.0))


def _cad_detect_undercuts(scan_obj, axis_vec):
    """Return (undercut_face_indices, undercut_ratio) via dot-product test."""
    import bmesh
    from mathutils import Vector
    bm = bmesh.new()
    try:
        bm.from_mesh(scan_obj.data)
        bm.transform(scan_obj.matrix_world)
        bm.normal_update()
        ax = Vector(axis_vec).normalized()
        uc = [f.index for f in bm.faces if f.normal.dot(ax) < 0.0]
        return uc, len(uc) / max(len(bm.faces), 1)
    finally:
        bm.free()


def _cad_build_blockout_mesh(scene, scan_obj, axis_vec, clearance_mm, tid):
    """Duplicate prep scan, extrude along insertion axis by clearance → blockout solid."""
    import bpy, bmesh
    from mathutils import Vector
    name = f"CAD_Blockout_T{int(tid)}"
    _cad_delete_object(name)
    ax = Vector(axis_vec).normalized()
    bm = bmesh.new()
    try:
        bm.from_mesh(scan_obj.data)
        bm.transform(scan_obj.matrix_world)
        bm.normal_update()
        result = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
        new_verts = [v for v in result["geom"] if isinstance(v, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=new_verts, vec=ax * float(clearance_mm))
        me = bpy.data.meshes.new(f"{name}_mesh")
        bm.to_mesh(me)
        me.update()
    finally:
        bm.free()
    obj = bpy.data.objects.new(name, me)
    _cad_ensure_collection("CAD_Wizard").objects.link(obj)
    obj["SMILE_CAD_TAG"] = True
    obj["SMILE_CAD_TID"] = int(tid)
    obj["SMILE_CAD_TYPE"] = "BLOCKOUT"
    obj.display_type = "WIRE"
    return obj


def _cad_build_support_margin(scene, margin_pts, axis_vec, height_mm, tid):
    """Extrude margin points along axis to create a chamfer/shoulder band mesh."""
    import bpy, bmesh
    from mathutils import Vector
    name = f"CAD_SupportMargin_T{int(tid)}"
    _cad_delete_object(name)
    if not margin_pts or len(margin_pts) < 3:
        return None, (0.0, 0.0)
    ax = Vector(axis_vec).normalized()
    pts = [Vector(p) for p in margin_pts]
    bm = bmesh.new()
    try:
        n = len(pts)
        lower = [bm.verts.new(p) for p in pts]
        upper = [bm.verts.new(p + ax * float(height_mm)) for p in pts]
        bm.verts.ensure_lookup_table()
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([lower[i], lower[j], upper[j], upper[i]])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        circ = sum((pts[(i+1) % n] - pts[i]).length for i in range(n))
        area = sum(f.calc_area() for f in bm.faces)
        me = bpy.data.meshes.new(f"{name}_mesh")
        bm.to_mesh(me)
        me.update()
    finally:
        bm.free()
    obj = bpy.data.objects.new(name, me)
    _cad_ensure_collection("CAD_Wizard").objects.link(obj)
    obj["SMILE_CAD_TAG"] = True
    obj["SMILE_CAD_TID"] = int(tid)
    obj["SMILE_CAD_TYPE"] = "SUPPORT_MARGIN"
    obj.display_type = "WIRE"
    obj.color = (0.2, 1.0, 0.5, 0.7)
    return obj, (circ, area)


def _cad_apply_cement_spacer(scene, scan_obj, gap_mm, extra_gap_mm, tid):
    """Duplicate prep scan, apply inward Solidify for cement gap → returns spacer object."""
    import bpy
    from mathutils import Vector
    name = f"CAD_Spacer_T{int(tid)}"
    _cad_delete_object(name)
    spacer = scan_obj.copy()
    spacer.data = scan_obj.data.copy()
    spacer.name = name
    spacer.data.name = f"{name}_mesh"
    _cad_ensure_collection("CAD_Wizard").objects.link(spacer)
    for mod in list(spacer.modifiers):
        if mod.type == "SOLIDIFY":
            spacer.modifiers.remove(mod)
    solidify = spacer.modifiers.new("CementSpacer", "SOLIDIFY")
    solidify.thickness = -(float(gap_mm) + float(extra_gap_mm))
    solidify.offset = 1.0
    solidify.use_even_offset = True
    solidify.use_rim = True
    spacer["SMILE_CAD_TAG"] = True
    spacer["SMILE_CAD_TID"] = int(tid)
    spacer["SMILE_CAD_TYPE"] = "SPACER"
    spacer.color = (0.9, 0.7, 0.2, 0.5)
    mn = Vector(scan_obj.bound_box[0])
    mx = Vector(scan_obj.bound_box[6])
    d = (scan_obj.matrix_world @ mx) - (scan_obj.matrix_world @ mn)
    return spacer, abs(d.x * d.y * d.z)


def _cad_apply_modifier_safe(obj, mod_name):
    """Apply a named modifier; returns True on success."""
    import bpy
    try:
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_apply(modifier=mod_name)
        return True
    except Exception:
        try:
            obj.modifiers.remove(obj.modifiers.get(mod_name))
        except Exception:
            pass
        return False


def _cad_remesh_voxel(obj, voxel_size=0.1):
    """Apply Voxel Remesh in place for boolean reliability."""
    import bpy
    mod = obj.modifiers.new("VoxelRemesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = float(voxel_size)
    mod.adaptivity = 0.0
    _cad_apply_modifier_safe(obj, mod.name)


def _cad_boolean_op(target, cutter, operation="DIFFERENCE", use_remesh=True):
    """Boolean modifier on target using cutter. Returns True on success."""
    import bpy
    if use_remesh:
        _cad_remesh_voxel(target)
    mod = target.modifiers.new(f"Bool_{operation[:4]}", "BOOLEAN")
    mod.operation = operation
    mod.object = cutter
    mod.solver = "FAST"
    return _cad_apply_modifier_safe(target, mod.name)


def _cad_adapt_outer_shell(scene, outer_obj, scan_obj, blockout_obj, use_remesh, tid):
    """Shrinkwrap library tooth to prep scan + Boolean diff with blockout."""
    import bpy, bmesh
    from mathutils.bvhtree import BVHTree
    name = f"CAD_Shell_T{int(tid)}"
    _cad_delete_object(name)
    shell = outer_obj.copy()
    shell.data = outer_obj.data.copy()
    shell.name = name
    shell.data.name = f"{name}_mesh"
    _cad_ensure_collection("CAD_Wizard").objects.link(shell)
    sw = shell.modifiers.new("ShrinkwrapAdapt", "SHRINKWRAP")
    sw.target = scan_obj
    sw.wrap_method = "NEAREST_SURFACEPOINT"
    sw.wrap_mode = "OUTSIDE"
    sw.offset = 0.0
    _cad_apply_modifier_safe(shell, sw.name)
    if blockout_obj:
        _cad_boolean_op(shell, blockout_obj, "DIFFERENCE", use_remesh=use_remesh)
    bm_s = bmesh.new()
    bm_o = bmesh.new()
    try:
        bm_s.from_mesh(scan_obj.data)
        bm_s.transform(scan_obj.matrix_world)
        bm_o.from_mesh(shell.data)
        bm_o.transform(shell.matrix_world)
        bvh_s = BVHTree.FromBMesh(bm_s)
        bvh_o = BVHTree.FromBMesh(bm_o)
        pairs = bvh_s.overlap(bvh_o)
        ratio = len(pairs) / max(len(bm_o.faces) + len(bm_s.faces), 1)
    finally:
        bm_s.free()
        bm_o.free()
    shell["SMILE_CAD_TAG"] = True
    shell["SMILE_CAD_TID"] = int(tid)
    shell["SMILE_CAD_TYPE"] = "SHELL"
    return shell, ratio


def _cad_finalize_intaglio(scene, shell_obj, spacer_obj, min_thick_mm, use_remesh, tid):
    """Create final restoration: Boolean shell–spacer diff + Solidify wall."""
    import bpy, bmesh
    name = f"CAD_Restoration_T{int(tid)}"
    _cad_delete_object(name)
    rest = shell_obj.copy()
    rest.data = shell_obj.data.copy()
    rest.name = name
    rest.data.name = f"{name}_mesh"
    _cad_ensure_collection("CAD_Wizard").objects.link(rest)
    if spacer_obj:
        _cad_boolean_op(rest, spacer_obj, "DIFFERENCE", use_remesh=use_remesh)
    solidify = rest.modifiers.new("IntaglioWall", "SOLIDIFY")
    solidify.thickness = float(min_thick_mm)
    solidify.offset = -1.0
    solidify.use_even_offset = True
    solidify.use_rim = True
    _cad_apply_modifier_safe(rest, solidify.name)
    bm = bmesh.new()
    try:
        bm.from_mesh(rest.data)
        bm.edges.ensure_lookup_table()
        nm = sum(1 for e in bm.edges if not e.is_manifold)
    finally:
        bm.free()
    rest["SMILE_CAD_TAG"] = True
    rest["SMILE_CAD_TID"] = int(tid)
    rest["SMILE_CAD_TYPE"] = "RESTORATION"
    rest.color = (0.95, 0.95, 1.0, 1.0)
    return rest, nm


def _cad_validate_restoration(rest_obj, axis_vec, min_thick_mm, case_mode):
    """Clinical safety check: thickness, undercuts, manifold, perforations."""
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    mode_min = {"VENEER": 0.3, "CROWN": 1.0, "BRIDGE": 1.0}
    eff_min = max(float(mode_min.get(str(case_mode), 0.3)), float(min_thick_mm))
    ax = Vector(axis_vec).normalized()
    bm = bmesh.new()
    try:
        bm.from_mesh(rest_obj.data)
        bm.transform(rest_obj.matrix_world)
        bm.normal_update()
        bm.edges.ensure_lookup_table()
        nm = sum(1 for e in bm.edges if not e.is_manifold)
        perf = sum(1 for f in bm.faces if f.calc_area() < 1e-6)
        uc_faces = [f for f in bm.faces if f.normal.dot(ax) < 0.0]
        uc_ratio = len(uc_faces) / max(len(bm.faces), 1)
        bvh = BVHTree.FromBMesh(bm)
        samples = []
        stride = max(1, len(bm.faces) // 300)
        for i, face in enumerate(bm.faces):
            if i % stride != 0:
                continue
            origin = face.calc_center_median() + face.normal * 1e-4
            hit, _, _, _ = bvh.ray_cast(origin, -face.normal, 20.0)
            if hit:
                samples.append((hit - origin).length)
        min_t = min(samples) if samples else 0.0
    finally:
        bm.free()
    hard_fail = (min_t < eff_min * 0.5) or (nm > 50)
    warn = (min_t < eff_min) or nm > 0 or uc_ratio > 0.05
    status = "FAIL" if hard_fail else ("WARN" if warn else "PASS")
    return {
        "min_thickness_mm": round(min_t, 4),
        "undercut_face_count": len(uc_faces),
        "undercut_ratio": round(uc_ratio, 4),
        "non_manifold_edges": nm,
        "perforation_count": perf,
        "effective_min_thickness_mm": round(eff_min, 3),
        "passed": status in ("PASS", "WARN"),
        "status": status,
    }


def _cad_export_restoration(context, rest_obj, filepath, fmt="STL"):
    """Export restoration to STL or OBJ. Returns (ok, file_size_bytes, message)."""
    import bpy, os
    if not rest_obj or rest_obj.type != "MESH":
        return False, 0, f"Invalid object: {rest_obj}"
    bpy.ops.object.select_all(action="DESELECT")
    context.view_layer.objects.active = rest_obj
    rest_obj.select_set(True)
    try:
        if str(fmt).upper() == "OBJ":
            bpy.ops.wm.obj_export(
                filepath=filepath,
                export_selected_objects=True,
                apply_modifiers=True,
                forward_axis="Y",
                up_axis="Z",
            )
        else:
            bpy.ops.export_mesh.stl(
                filepath=filepath,
                use_selection=True,
                use_mesh_modifiers=True,
                ascii=False,
            )
        if os.path.isfile(filepath):
            sz = os.path.getsize(filepath)
            return True, sz, f"Exported '{rest_obj.name}' → {filepath} ({sz} bytes)"
        return False, 0, f"File not found post-export: {filepath}"
    except Exception as exc:
        return False, 0, f"Export failed: {exc}"


def _stage_a_impl(scene, ctx, p, tid):
    prod = _lazy_import_production()
    scan = _cad_find_prep_scan(scene, tid)
    if not scan:
        return {"ok": False, "status": "FAIL",
                "message": f"No prep scan found for T#{tid}. Import the scan first.",
                "metrics": {}}
    pts = []
    if prod:
        data = prod.get_margin_data(scene, scan, tooth_id=tid)
        pts = (data or {}).get("control_points", []) or prod.get_margin_points(scene, scan, tooth_id=tid) or []
    n = len(pts)
    if n < 6:
        return {"ok": False, "status": "FAIL",
                "message": f"Margin trace incomplete for T#{tid}: {n} points (min 6). Use margin tracing tools first.",
                "metrics": {"point_count": n, "scan_name": scan.name}}
    return {"ok": True, "status": "PASS",
            "message": f"Margin confirmed: {n} pts on '{scan.name}'.",
            "metrics": {"point_count": n, "scan_name": scan.name}}


def _stage_b_impl(scene, ctx, p, tid):
    scan = _cad_find_prep_scan(scene, tid)
    if not scan:
        return {"ok": False, "status": "FAIL",
                "message": f"No prep scan for T#{tid}.", "metrics": {}}
    ax = _cad_get_axis_vec(scene)
    clearance = float(getattr(p, "cad_blockout_clearance_mm", 0.05))
    max_uc = float(getattr(p, "cad_max_undercut_ratio", 0.25))
    try:
        _, uc_ratio = _cad_detect_undercuts(scan, ax)
        bo = _cad_build_blockout_mesh(scene, scan, ax, clearance, tid)
        metrics = {"axis_mode": str(getattr(p, "cad_insertion_axis_mode", "AUTO")),
                   "axis_vec": [round(ax.x,4), round(ax.y,4), round(ax.z,4)],
                   "undercut_ratio": round(uc_ratio, 4), "clearance_mm": clearance,
                   "blockout_obj": bo.name if bo else ""}
        if uc_ratio > max_uc:
            return {"ok": False, "status": "FAIL",
                    "message": f"Undercut {uc_ratio:.1%} > limit {max_uc:.1%}. Adjust insertion axis.",
                    "metrics": metrics}
        return {"ok": True, "status": "PASS",
                "message": f"Blockout done: undercut {uc_ratio:.1%}, mesh '{bo.name}'.",
                "metrics": metrics}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage B: {e}", "metrics": {}}


def _stage_c_impl(scene, ctx, p, tid):
    prod = _lazy_import_production()
    scan = _cad_find_prep_scan(scene, tid)
    pts = []
    if prod and scan:
        data = prod.get_margin_data(scene, scan, tooth_id=tid)
        pts = (data or {}).get("control_points", []) or prod.get_margin_points(scene, scan, tooth_id=tid) or []
    if len(pts) < 3:
        return {"ok": False, "status": "FAIL",
                "message": f"Support margin: only {len(pts)} margin pts. Complete Stage A first.",
                "metrics": {}}
    h = float(getattr(p, "cad_support_margin_height_mm", 0.3))
    ax = _cad_get_axis_vec(scene)
    try:
        obj, (circ, area) = _cad_build_support_margin(scene, pts, ax, h, tid)
        if not obj:
            return {"ok": False, "status": "FAIL",
                    "message": "Support margin mesh creation failed.", "metrics": {}}
        return {"ok": True, "status": "PASS",
                "message": f"Support margin '{obj.name}': circ={circ:.2f} mm.",
                "metrics": {"circumference_mm": round(circ,3), "area_mm2": round(area,4), "obj": obj.name}}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage C: {e}", "metrics": {}}


def _stage_d_impl(scene, ctx, p, tid):
    scan = _cad_find_prep_scan(scene, tid)
    if not scan:
        return {"ok": False, "status": "FAIL",
                "message": f"No prep scan for T#{tid}.", "metrics": {}}
    gap = float(getattr(p, "cad_spacer_internal_um", 50.0)) / 1000.0
    extra = float(getattr(p, "cad_extra_cement_gap_um", 20.0)) / 1000.0
    try:
        spacer, vol = _cad_apply_cement_spacer(scene, scan, gap, extra, tid)
        return {"ok": True, "status": "PASS",
                "message": f"Spacer '{spacer.name}': gap={gap+extra:.3f} mm total.",
                "metrics": {"total_gap_mm": round(gap+extra,4), "obj": spacer.name}}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage D: {e}", "metrics": {}}


def _stage_e_impl(scene, ctx, p, tid):
    import bpy, re
    outer_name = str(getattr(p, "cad_outer_source_name", "") or "")
    outer = bpy.data.objects.get(outer_name) if outer_name else None
    if not outer or outer.type != "MESH":
        pat = re.compile(r"(?:_T|TOOTH[_]?)(0*)" + str(tid) + r"(?:\D|$)", re.IGNORECASE)
        for cn in ("SmileTeeth", "Veneers", "Teeth"):
            col = bpy.data.collections.get(cn)
            if col:
                for o in col.objects:
                    if o.type == "MESH" and pat.search(o.name):
                        outer = o
                        p.cad_outer_source_name = o.name
                        break
            if outer:
                break
    if not outer or outer.type != "MESH":
        return {"ok": False, "status": "FAIL",
                "message": f"No reference tooth for T#{tid}. Select library tooth → 'Use Selected as Reference'.",
                "metrics": {}}
    scan = _cad_find_prep_scan(scene, tid)
    if not scan:
        return {"ok": False, "status": "FAIL", "message": f"No prep scan for T#{tid}.", "metrics": {}}
    bo = _cad_find_typed_object(tid, "BLOCKOUT")
    use_remesh = bool(getattr(p, "cad_use_remesh_before_boolean", True))
    min_ov = float(getattr(p, "cad_outer_overlap_min_ratio", 0.18))
    try:
        shell, ratio = _cad_adapt_outer_shell(scene, outer, scan, bo, use_remesh, tid)
        metrics = {"reference": outer.name, "overlap_ratio": round(ratio,4), "obj": shell.name}
        if ratio < min_ov:
            return {"ok": False, "status": "FAIL",
                    "message": f"Overlap {ratio:.1%} < required {min_ov:.1%}. Reposition reference tooth.",
                    "metrics": metrics}
        return {"ok": True, "status": "PASS",
                "message": f"Shell '{shell.name}' adapted, overlap={ratio:.1%}.",
                "metrics": metrics}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage E: {e}", "metrics": {}}


def _stage_f_impl(scene, ctx, p, tid):
    shell = _cad_find_typed_object(tid, "SHELL")
    if not shell:
        return {"ok": False, "status": "FAIL",
                "message": f"Shell for T#{tid} not found. Complete Stage E first.", "metrics": {}}
    spacer = _cad_find_typed_object(tid, "SPACER")
    min_t = float(getattr(p, "cad_min_thickness_mm", 0.2))
    use_remesh = bool(getattr(p, "cad_use_remesh_before_boolean", True))
    try:
        rest, nm = _cad_finalize_intaglio(scene, shell, spacer, min_t, use_remesh, tid)
        status = "WARN" if nm > 0 else "PASS"
        msg = f"Intaglio finalized: '{rest.name}'"
        if nm > 0:
            msg += f" — {nm} non-manifold edge(s). Review geometry."
        return {"ok": True, "status": status, "message": msg,
                "metrics": {"obj": rest.name, "non_manifold_edges": nm, "min_thickness_mm": min_t}}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage F: {e}", "metrics": {}}


def _stage_g_impl(scene, ctx, p, tid):
    rest = _cad_find_typed_object(tid, "RESTORATION")
    if not rest:
        return {"ok": False, "status": "FAIL",
                "message": f"Restoration for T#{tid} not found. Complete Stage F first.", "metrics": {}}
    ax = _cad_get_axis_vec(scene)
    min_t = float(getattr(p, "cad_min_thickness_mm", 0.2))
    mode = str(getattr(p, "cad_case_mode", "VENEER"))
    try:
        rep = _cad_validate_restoration(rest, ax, min_t, mode)
        ok = rep["passed"]
        msg = (f"Validate T#{tid} ({mode}): {rep['status']} | "
               f"MinThick={rep['min_thickness_mm']:.3f}mm | "
               f"NM={rep['non_manifold_edges']} | UC={rep['undercut_ratio']:.1%}")
        return {"ok": ok, "status": rep["status"], "message": msg, "metrics": rep}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage G: {e}", "metrics": {}}


def _stage_h_impl(scene, ctx, p, tid, filepath, export_fmt):
    import bpy
    rest = _cad_find_typed_object(tid, "RESTORATION")
    if not rest:
        rest = bpy.data.objects.get(f"CAD_Restoration_T{int(tid)}")
    if not rest:
        return {"ok": False, "status": "FAIL",
                "message": f"Restoration for T#{tid} not found. Complete Stages F and G first.",
                "metrics": {}}
    fmt = str(export_fmt or "STL").upper()
    if not filepath:
        ext = "stl" if fmt == "STL" else "obj"
        filepath = bpy.path.abspath(f"//CAD_T{int(tid)}_FINAL.{ext}")
    try:
        ok, sz, msg = _cad_export_restoration(ctx, rest, filepath, fmt)
        return {"ok": ok, "status": "PASS" if ok else "FAIL", "message": msg,
                "filepath": str(filepath),
                "metrics": {"filepath": filepath, "format": fmt, "file_size_bytes": sz, "obj": rest.name}}
    except Exception as e:
        return {"ok": False, "status": "FAIL", "message": f"Stage H: {e}", "metrics": {}}


def run_cad_stage(
    scene, stage, context=None, operator=None, filepath="", export_fmt="STL"
):
    """Run a CAD wizard stage. Delegates to stage-specific implementations."""
    stage = str(stage or "")
    ctx = context
    if ctx is None and _IN_BLENDER:
        import bpy
        ctx = bpy.context

    p = scene.smile_v2
    enforce = bool(getattr(p, "cad_stage_lock_enforced", True))
    ok_gate, why_gate = _cad_gate_ok(scene, stage, enforce=enforce)
    if not ok_gate:
        _cad_update_stage(scene, stage, "FAIL", why_gate)
        return {"ok": False, "message": why_gate, "status": "FAIL"}

    tid = _cad_target_tid(scene)
    _impls = {
        "A_MARGIN":          lambda: _stage_a_impl(scene, ctx, p, tid),
        "B_SURVEY_BLOCKOUT": lambda: _stage_b_impl(scene, ctx, p, tid),
        "C_SUPPORT_MARGIN":  lambda: _stage_c_impl(scene, ctx, p, tid),
        "D_SPACER_SAFETY":   lambda: _stage_d_impl(scene, ctx, p, tid),
        "E_ADAPT_OUTER":     lambda: _stage_e_impl(scene, ctx, p, tid),
        "F_FINALIZE_INTAGLIO": lambda: _stage_f_impl(scene, ctx, p, tid),
        "G_VALIDATE":        lambda: _stage_g_impl(scene, ctx, p, tid),
        "H_EXPORT":          lambda: _stage_h_impl(scene, ctx, p, tid, filepath, export_fmt),
    }
    impl = _impls.get(stage)
    if not impl:
        return {"ok": False, "message": f"Unknown stage: {stage}", "status": "FAIL"}

    try:
        result = impl()
    except Exception as exc:
        import traceback as _tb
        result = {"ok": False, "status": "FAIL",
                  "message": f"Unhandled exception in {stage}: {exc}",
                  "metrics": {"traceback": _tb.format_exc()[-800:]}}

    # WARN counts as PASS for gate logic so pipeline can continue
    state_status = "PASS" if result.get("status", "FAIL") in ("PASS", "WARN") else "FAIL"
    _cad_update_stage(scene, stage, state_status,
                      message=str(result.get("message", "")),
                      metrics=result.get("metrics", {}))
    return result



def _ui_fold_header(layout, props, prop_name, label, icon="NONE"):
    """Helper to create collapsible section headers."""
    is_open = bool(getattr(props, prop_name, False))
    tri = "TRIA_DOWN" if is_open else "TRIA_RIGHT"
    row = layout.row(align=True)
    op = row.operator("wm.context_toggle", text=label, icon=tri, emboss=False)
    op.data_path = f"scene.smile_v2.{prop_name}"
    if icon and icon != "NONE":
        row.label(text="", icon=icon)
    return is_open


def draw_guided_tab(context, layout, props):
    """Draw the GUIDED tab UI panel content."""
    if not _IN_BLENDER:
        return

    scene = context.scene
    p = scene.smile_v2

    st = _cad_load_state(scene)
    stages = _json_obj(st.get("stages", {}), default={})
    state_tid = int(st.get("target_tooth_id", 0) or 0)
    state_mode = str(st.get("case_mode", "") or "")
    mismatch, mismatch_msg = _cad_state_context_mismatch(scene, st=st)
    report_msg = str(st.get("last_message", "") or "")

    next_stage = None
    for s in CAD_STAGE_ORDER:
        status = str((stages.get(s, {}) or {}).get("status", "PENDING"))
        if status != "PASS":
            next_stage = s
            break

    layout.label(text="Tab 7: Guided Restoration Workflow", icon="SEQUENCE")

    if report_msg:
        layout.label(text=f"Last Action: {report_msg}", icon="INFO")

    if _ui_fold_header(
        layout, p, "ui_guided_sec_setup", "1. Case Setup", icon="SETTINGS"
    ):
        setup = layout.box()
        row = setup.row(align=True)
        row.prop(p, "cad_wizard_enabled", text="Turn Wizard On")
        row.prop(p, "cad_stage_lock_enforced", text="Force Step Order")

        row = setup.row(align=True)
        row.prop(p, "cad_case_mode", text="Restoration")
        row.prop(p, "cad_target_tooth_id", text="Target Tooth #")

        source_box = setup.box()
        source_box.label(text="Reference Tooth (used in Step E)", icon="MESH_DATA")
        source_box.prop_search(
            p, "cad_outer_source_name", bpy.data, "objects", text="Current Reference"
        )
        source_box.prop(
            p,
            "cad_auto_pin_reference_on_import",
            text="Auto-Select Matching Imported Tooth",
        )
        row = source_box.row(align=True)
        row.operator(
            "smile.cad_wizard_use_active_outer_source",
            text="Use Selected Tooth as Reference",
            icon="EYEDROPPER",
        )
        row.operator(
            "smile.cad_wizard_clear_outer_source",
            text="Clear Selected Reference",
            icon="CANCEL",
        )

    run_map = {
        "A_MARGIN": "smile.cad_stage_a_trace_margin",
        "B_SURVEY_BLOCKOUT": "smile.cad_stage_b_survey_blockout",
        "C_SUPPORT_MARGIN": "smile.cad_stage_c_support_margin",
        "D_SPACER_SAFETY": "smile.cad_stage_d_spacer_safety",
        "E_ADAPT_OUTER": "smile.cad_stage_e_adapt_outer",
        "F_FINALIZE_INTAGLIO": "smile.cad_stage_f_finalize_intaglio",
        "G_VALIDATE": "smile.cad_stage_g_validate",
        "H_EXPORT": "smile.cad_stage_h_export",
    }

    def _get_stat(stage_id):
        return str(
            _json_obj(stages.get(stage_id, {}), default={}).get("status", "PENDING")
        ).upper()

    def _get_msg(stage_id):
        return str(
            _json_obj(stages.get(stage_id, {}), default={}).get("message", "") or ""
        )

    stat_a = _get_stat("A_MARGIN")
    stat_b = _get_stat("B_SURVEY_BLOCKOUT")
    step1_icon = (
        "CHECKMARK"
        if (stat_a == "PASS" and stat_b == "PASS")
        else ("ERROR" if "FAIL" in [stat_a, stat_b] else "LAYER_USED")
    )

    box1 = layout.box()
    row1 = box1.row()
    row1.prop(
        p,
        "ui_cad_step1_open",
        icon="TRIA_DOWN" if p.ui_cad_step1_open else "TRIA_RIGHT",
        text="",
        emboss=False,
    )
    row1.label(text="Step 1: Preparation (Margin, Die, Axis)", icon=step1_icon)

    if p.ui_cad_step1_open:
        content1 = box1.column()

        mbox = content1.box()
        mbox.label(text="Margin Tracing", icon="GREASEPENCIL")
        row = mbox.row(align=True)
        row.scale_y = 1.2
        row.operator(
    # "smile.trace_margin_interactive", text="Click Trace", icon="GREASEPENCIL"  # MISSING OPERATOR
        )
        row.operator(
    # "smile.trace_margin_smooth", text="Smooth Trace", icon="IPO_BEZIER"  # MISSING OPERATOR
        )
        row.operator(
    # "smile.trace_margin_drag_smooth", text="Drag Smooth", icon="GREASEPENCIL"  # MISSING OPERATOR
        )
        row.operator(
    # "smile.trace_margin_drag", text="Drag Trace", icon="FORCE_MAGNETIC"  # MISSING OPERATOR
        )
        row = mbox.row(align=True)
        row.operator(
    # "smile.edit_margin_object_mode", text="Edit (Gizmos)", icon="GIZMO"  # MISSING OPERATOR
        )
        row.operator(
    # "smile.margin_trace_undo_last", text="Undo Point", icon="LOOP_BACK"  # MISSING OPERATOR
        )
    # row.operator("smile.clear_margin_data", text="Clear", icon="CANCEL")  # MISSING OPERATOR

        vbox = content1.box()
        vbox.label(text="Die & Spacer Fabrication", icon="MOD_BOOLEAN")
        row = vbox.row(align=True)
        row.scale_y = 1.2
        row.operator(
    # "smile.create_die_and_spacer",  # MISSING OPERATOR
            text="Generate Die + Spacer",
            icon="MESH_PLANE",
        )
        row = vbox.row(align=True)
    # row.operator("smile.undo_die_step", text="Undo Die/Spacer", icon="LOOP_BACK")  # MISSING OPERATOR

        axis_box = content1.box()
        axis_box.label(text="Insertion Direction Helper", icon="ORIENTATION_GIMBAL")
        row = axis_box.row(align=True)
        row.prop(p, "cad_insertion_axis_mode", text="Mode")
        tool_row = axis_box.row(align=True)
        tool_row.operator(
            "smile.cad_wizard_axis_auto_suggest", text="Suggest", icon="LIGHT_SUN"
        )
        tool_row.operator(
            "smile.cad_wizard_axis_from_view", text="Use View", icon="HIDE_OFF"
        )
        tool_row.operator(
            "smile.cad_wizard_axis_pick_2pt", text="Pick 2", icon="TRACKER"
        )
        eval_row = axis_box.row(align=True)
        eval_row.operator(
            "smile.cad_wizard_axis_evaluate",
            text="Check Direction",
            icon="DRIVER_DISTANCE",
        )

        row = content1.row(align=True)
        row.scale_y = 1.2
        row.operator(run_map["A_MARGIN"], text="Confirm Margin Step", icon="CHECKMARK")
        row.operator(
            run_map["B_SURVEY_BLOCKOUT"], text="Confirm Blockout Step", icon="CHECKMARK"
        )

    stat_c = _get_stat("C_SUPPORT_MARGIN")
    stat_d = _get_stat("D_SPACER_SAFETY")
    step2_icon = (
        "CHECKMARK"
        if (stat_c == "PASS" and stat_d == "PASS")
        else ("ERROR" if "FAIL" in [stat_c, stat_d] else "LAYER_USED")
    )

    box2 = layout.box()
    row2 = box2.row()
    row2.prop(
        p,
        "ui_cad_step2_open",
        icon="TRIA_DOWN" if p.ui_cad_step2_open else "TRIA_RIGHT",
        text="",
        emboss=False,
    )
    row2.label(text="Step 2: Fit & Clearances", icon=step2_icon)

    if p.ui_cad_step2_open:
        content2 = box2.column()
        sub = content2.box()
        row = sub.row(align=True)
        row.prop(p, "cad_spacer_internal_um", text="Cement Gap [µm]")
        row.prop(p, "cad_extra_cement_gap_um", text="Extra Gap [µm]")
        row2b = sub.row(align=True)
        row2b.prop(p, "cad_support_margin_height_mm", text="Chamfer Height [mm]")
        row2b.prop(p, "cad_use_remesh_before_boolean", text="Remesh Before Bool")

        # Stage C metrics
        msg_c = _get_msg("C_SUPPORT_MARGIN")
        if msg_c and stat_c in ("PASS", "WARN", "FAIL"):
            ic_c = "CHECKMARK" if stat_c == "PASS" else ("ERROR" if stat_c == "FAIL" else "INFO")
            content2.label(text=f"C: {msg_c[:60]}", icon=ic_c)

        action_cd = content2.row(align=True)
        action_cd.scale_y = 1.2
        sub_c = action_cd.row(align=True)
        sub_c.enabled = stat_b == "PASS"
        sub_c.operator(
            run_map["C_SUPPORT_MARGIN"], text="Support Margin", icon="CURVE_DATA"
        )
        sub_d = action_cd.row(align=True)
        sub_d.enabled = stat_c == "PASS"
        sub_d.operator(
            run_map["D_SPACER_SAFETY"], text="Generate Spacers", icon="MOD_THICKNESS"
        )
        # Stage D metrics
        msg_d = _get_msg("D_SPACER_SAFETY")
        if msg_d and stat_d in ("PASS", "WARN", "FAIL"):
            ic_d = "CHECKMARK" if stat_d == "PASS" else ("ERROR" if stat_d == "FAIL" else "INFO")
            content2.label(text=f"D: {msg_d[:60]}", icon=ic_d)

    stat_e = _get_stat("E_ADAPT_OUTER")
    step3_icon = (
        "CHECKMARK"
        if (stat_e == "PASS")
        else ("ERROR" if stat_e == "FAIL" else "LAYER_USED")
    )

    box3 = layout.box()
    row3 = box3.row()
    row3.prop(
        p,
        "ui_cad_step3_open",
        icon="TRIA_DOWN" if p.ui_cad_step3_open else "TRIA_RIGHT",
        text="",
        emboss=False,
    )
    row3.label(text="Step 3: Library Adaptation", icon=step3_icon)

    if p.ui_cad_step3_open:
        content3 = box3.column()
        row3p = content3.row(align=True)
        row3p.prop(p, "cad_outer_overlap_min_ratio", text="Min Overlap")
        row3p.prop(p, "cad_use_remesh_before_boolean", text="Remesh")
        action_e = content3.row(align=True)
        action_e.scale_y = 1.2
        action_e.enabled = stat_d == "PASS"
        action_e.operator(
            run_map["E_ADAPT_OUTER"], text="Adapt Library Tooth", icon="MOD_SHRINKWRAP"
        )
        msg_e = _get_msg("E_ADAPT_OUTER")
        if msg_e and stat_e in ("PASS", "WARN", "FAIL"):
            ic_e = "CHECKMARK" if stat_e == "PASS" else ("ERROR" if stat_e == "FAIL" else "INFO")
            content3.label(text=f"E: {msg_e[:70]}", icon=ic_e)

    stat_f = _get_stat("F_FINALIZE_INTAGLIO")
    stat_g = _get_stat("G_VALIDATE")
    stat_h = _get_stat("H_EXPORT")
    step4_icon = (
        "CHECKMARK"
        if stat_h == "PASS"
        else ("ERROR" if "FAIL" in [stat_f, stat_g, stat_h] else "LAYER_USED")
    )

    box4 = layout.box()
    row4 = box4.row()
    row4.prop(
        p,
        "ui_cad_step4_open",
        icon="TRIA_DOWN" if p.ui_cad_step4_open else "TRIA_RIGHT",
        text="",
        emboss=False,
    )
    row4.label(text="Step 4: Finalize & Export", icon=step4_icon)

    if p.ui_cad_step4_open:
        content4 = box4.column()
        row = content4.row(align=True)
        row.prop(p, "cad_min_thickness_mm", text="Min Thick")
        row.prop(p, "cad_export_fmt", text="Format")

        action_f = content4.row(align=True)
        action_f.scale_y = 1.2
        action_f.enabled = stat_e == "PASS"
        # Inline F/G metric display
        msg_f = _get_msg("F_FINALIZE_INTAGLIO")
        if msg_f and stat_f in ("PASS", "WARN", "FAIL"):
            ic_f = "CHECKMARK" if stat_f == "PASS" else ("ERROR" if stat_f == "FAIL" else "INFO")
            content4.label(text=f"F: {msg_f[:60]}", icon=ic_f)
        msg_g = _get_msg("G_VALIDATE")
        if msg_g and stat_g in ("PASS", "WARN", "FAIL"):
            ic_g = "CHECKMARK" if stat_g == "PASS" else ("ERROR" if stat_g == "FAIL" else "INFO")
            content4.label(text=f"G: {msg_g[:60]}", icon=ic_g)

        action_f2 = content4.row(align=True)
        action_f2.scale_y = 1.2
        action_f2.enabled = stat_e == "PASS"
        action_f.operator(
            run_map["F_FINALIZE_INTAGLIO"], text="Finalize Shell", icon="MOD_BOOLEAN"
        )

        action_g = content4.row(align=True)
        action_g.scale_y = 1.2
        action_g.enabled = stat_f == "PASS"
        action_g.operator(
            run_map["G_VALIDATE"], text="Validate Thickness", icon="DRIVER_DISTANCE"
        )

        action_h = content4.row(align=True)
        action_h.scale_y = 1.4
        action_h.enabled = stat_g == "PASS" or "WARN" in stat_g
        action_h.operator(run_map["H_EXPORT"], text="Export File", icon="EXPORT")


CLASSES = []


class SMILE_OT_cad_stage_a_trace_margin(bpy.types.Operator):
    """Confirm margin tracing step in CAD wizard."""

    bl_idname = "smile.cad_stage_a_trace_margin"
    bl_label = "A. Trace Margin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(context.scene, "A_MARGIN", context=context, operator=self)
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_b_survey_blockout(bpy.types.Operator):
    """Confirm survey and blockout step in CAD wizard."""

    bl_idname = "smile.cad_stage_b_survey_blockout"
    bl_label = "B. Survey + Blockout"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(
            context.scene, "B_SURVEY_BLOCKOUT", context=context, operator=self
        )
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_c_support_margin(bpy.types.Operator):
    """Build support margin around prepared tooth."""

    bl_idname = "smile.cad_stage_c_support_margin"
    bl_label = "C. Build Support Margin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(
            context.scene, "C_SUPPORT_MARGIN", context=context, operator=self
        )
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_d_spacer_safety(bpy.types.Operator):
    """Generate spacers for cement gap clearance."""

    bl_idname = "smile.cad_stage_d_spacer_safety"
    bl_label = "D. Spacer + Safety"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(
            context.scene, "D_SPACER_SAFETY", context=context, operator=self
        )
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_e_adapt_outer(bpy.types.Operator):
    """Adapt outer library tooth to prep geometry."""

    bl_idname = "smile.cad_stage_e_adapt_outer"
    bl_label = "E. Adapt Outer Shell"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(
            context.scene, "E_ADAPT_OUTER", context=context, operator=self
        )
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_f_finalize_intaglio(bpy.types.Operator):
    """Finalize the intaglio (inner) surface of the restoration."""

    bl_idname = "smile.cad_stage_f_finalize_intaglio"
    bl_label = "F. Finalize Intaglio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(
            context.scene, "F_FINALIZE_INTAGLIO", context=context, operator=self
        )
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_g_validate(bpy.types.Operator):
    """Validate restoration thickness and fit."""

    bl_idname = "smile.cad_stage_g_validate"
    bl_label = "G. Validate Restoration"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = run_cad_stage(context.scene, "G_VALIDATE", context=context, operator=self)
        return _cad_handle_result(self, res)


class SMILE_OT_cad_stage_h_export(bpy.types.Operator):
    """Export final restoration to STL or OBJ."""

    bl_idname = "smile.cad_stage_h_export"
    bl_label = "H. Export Files"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH", default="")

    def invoke(self, context, event):
        scene = context.scene
        tid = _cad_target_tid(scene)
        fmt = str(scene.smile_v2.cad_export_fmt or "STL").upper()
        ext = "stl" if fmt == "STL" else "obj"
        self.filepath = bpy.path.abspath(f"//CAD_T{tid}_FINAL.{ext}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        fmt = str(context.scene.smile_v2.cad_export_fmt or "STL").upper()
        res = run_cad_stage(
            context.scene,
            "H_EXPORT",
            context=context,
            operator=self,
            filepath=self.filepath,
            export_fmt=fmt,
        )
        return _cad_handle_result(self, res)


class SMILE_OT_cad_wizard_axis_auto_suggest(bpy.types.Operator):
    """Auto-suggest insertion axis from current prep geometry."""

    bl_idname = "smile.cad_wizard_axis_auto_suggest"
    bl_label = "Suggest Axis"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        tid = _cad_target_tid(scene)
        p.cad_insertion_axis_mode = "AUTO"
        self.report({"INFO"}, f"Insertion axis set to AUTO for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_cad_wizard_axis_from_view(bpy.types.Operator):
    """Set insertion axis from current 3D viewport direction."""

    bl_idname = "smile.cad_wizard_axis_from_view"
    bl_label = "Use Current View"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        tid = _cad_target_tid(scene)
        p.cad_insertion_axis_mode = "VIEW"
        self.report({"INFO"}, f"Insertion axis set to VIEW direction for T#{tid}.")
        return {"FINISHED"}


class SMILE_OT_cad_wizard_axis_pick_2pt(bpy.types.Operator):
    """Pick two points on prep scan to define insertion axis."""

    bl_idname = "smile.cad_wizard_axis_pick_2pt"
    bl_label = "Pick 2 Points"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        self._points = []
        self._handles = []
        self._tooth_id = int(_cad_target_tid(context.scene))
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "Insertion Axis Pick: click Point 1 (cervical), then Point 2 (direction).",
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
        } or getattr(event, "alt", False):
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._cleanup_markers()
            self.report({"INFO"}, "Insertion axis pick cancelled.")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            p = context.scene.smile_v2
            self._points.append(Vector((0, 0, 0)))
            self._add_marker(context, self._points[-1], len(self._points))
            if len(self._points) == 1:
                self.report(
                    {"INFO"}, "Point 2/2: click along desired insertion direction."
                )
                return {"RUNNING_MODAL"}

            p.cad_insertion_axis_mode = "MANUAL"
            p.cad_insertion_axis_vec = (0.0, 0.0, 1.0)
            self._cleanup_markers()
            self.report({"INFO"}, "Insertion axis set from 2 points.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def _add_marker(self, context, loc, idx):
        name = f"TEMP_CAD_AXIS_T{int(self._tooth_id)}_{int(idx)}"
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = "PLAIN_AXES"
        o.empty_display_size = 0.70
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


class SMILE_OT_cad_wizard_axis_evaluate(bpy.types.Operator):
    """Evaluate current insertion axis quality and cache feedback."""

    bl_idname = "smile.cad_wizard_axis_evaluate"
    bl_label = "Evaluate Axis"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        tid = _cad_target_tid(scene)
        mode = str(getattr(p, "cad_insertion_axis_mode", "AUTO"))
        self.report(
            {"INFO"},
            f"Axis evaluation: Mode={mode}, Target=T#{tid}. "
            "Full evaluation requires stage B execution.",
        )
        return {"FINISHED"}


class SMILE_OT_cad_wizard_apply_stage_b_retry(bpy.types.Operator):
    """Apply Stage B retry suggestion (locked axis + clearance) from last run."""

    bl_idname = "smile.cad_wizard_apply_stage_b_retry"
    bl_label = "Apply Last B Retry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        hint = _cad_get_stage_retry_hint(scene, "B_SURVEY_BLOCKOUT")
        metrics = _json_obj(hint.get("metrics", {}), default={})
        changed = False

        axis = metrics.get("insertion_axis_vec", None)
        if isinstance(axis, (list, tuple)) and len(axis) == 3:
            try:
                v = Vector((float(axis[0]), float(axis[1]), float(axis[2])))
                if v.length > 1.0e-8:
                    v.normalize()
                    p.cad_insertion_axis_mode = "MANUAL"
                    p.cad_insertion_axis_vec = (float(v.x), float(v.y), float(v.z))
                    changed = True
            except Exception:
                pass

        if "suggested_clearance_mm" in metrics:
            try:
                p.cad_blockout_clearance_mm = float(
                    metrics.get("suggested_clearance_mm", p.cad_blockout_clearance_mm)
                )
                changed = True
            except Exception:
                pass

        if not changed:
            self.report(
                {"WARNING"},
                "No Stage B retry suggestion available yet. Run Stage B once first.",
            )
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Applied Stage B retry: Axis + Clearance {float(getattr(p, 'cad_blockout_clearance_mm', 0.05)):.3f} mm.",
        )
        return {"FINISHED"}


class SMILE_OT_cad_wizard_use_active_outer_source(bpy.types.Operator):
    """Pin currently active mesh as CAD Wizard Step E reference tooth."""

    bl_idname = "smile.cad_wizard_use_active_outer_source"
    bl_label = "Use Active as Reference Tooth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}
        p.cad_outer_source_name = str(obj.name)
        self.report({"INFO"}, f"Reference tooth pinned: {obj.name}.")
        return {"FINISHED"}


class SMILE_OT_cad_wizard_clear_outer_source(bpy.types.Operator):
    """Clear pinned Step E reference tooth."""

    bl_idname = "smile.cad_wizard_clear_outer_source"
    bl_label = "Clear Reference Tooth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.smile_v2.cad_outer_source_name = ""
        self.report({"INFO"}, "Reference tooth cleared.")
        return {"FINISHED"}


class SMILE_OT_cad_wizard_sync_context(bpy.types.Operator):
    """Resume saved CAD case context or start a new case from Smile context."""

    bl_idname = "smile.cad_wizard_sync_context"
    bl_label = "CAD Context Action"
    bl_options = {"REGISTER", "UNDO"}

    start_new_case: BoolProperty(
        name="Start New Case",
        default=False,
        description="Reset CAD stage progress and initialize a new case from current Smile target tooth",
    )

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        st = _cad_load_state(scene)
        saved_tid = int(st.get("target_tooth_id", 0) or 0)
        saved_mode = str(st.get("case_mode", "") or "")

        if bool(self.start_new_case):
            p.cad_target_tooth_id = int(getattr(p, "target_tooth_id", 8) or 8)
            if str(getattr(p, "cad_case_mode", "")) not in {
                "VENEER",
                "CROWN",
                "BRIDGE",
            }:
                p.cad_case_mode = "VENEER"
            p.cad_outer_source_name = ""
            _cad_reset_state(scene)
            self.report(
                {"INFO"},
                f"Started new CAD case at T#{p.cad_target_tooth_id} ({p.cad_case_mode}).",
            )
            return {"FINISHED"}

        if saved_tid <= 0:
            saved_tid = int(
                getattr(p, "cad_target_tooth_id", 0)
                or getattr(p, "target_tooth_id", 8)
                or 8
            )
        if saved_mode not in {"VENEER", "CROWN", "BRIDGE"}:
            saved_mode = str(getattr(p, "cad_case_mode", "VENEER") or "VENEER")
            if saved_mode not in {"VENEER", "CROWN", "BRIDGE"}:
                saved_mode = "VENEER"

        p.cad_target_tooth_id = int(saved_tid)
        p.target_tooth_id = int(saved_tid)
        p.cad_case_mode = str(saved_mode)
        self.report({"INFO"}, f"Resumed saved CAD case T#{saved_tid} ({saved_mode}).")
        return {"FINISHED"}


class SMILE_OT_cad_wizard_reset_case(bpy.types.Operator):
    """Reset CAD wizard stage state; optionally remove wizard-generated tagged objects."""

    bl_idname = "smile.cad_wizard_reset_case"
    bl_label = "Reset CAD Wizard Case"
    bl_options = {"REGISTER", "UNDO"}

    remove_tagged_objects: BoolProperty(
        name="Remove Tagged Objects",
        default=False,
        description="Delete objects generated by CAD wizard stages",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        _cad_reset_state(scene)
        scene.smile_v2.cad_outer_source_name = ""
        removed = 0
        if bool(self.remove_tagged_objects):
            for o in list(bpy.data.objects):
                try:
                    if bool(o.get("SMILE_CAD_TAG", False)):
                        bpy.data.objects.remove(o, do_unlink=True)
                        removed += 1
                except Exception:
                    continue
        self.report({"INFO"}, f"CAD wizard reset. Removed tagged objects: {removed}.")
        return {"FINISHED"}


class SMILE_OT_cad_wizard_show_stage_report(bpy.types.Operator):
    """Show/copy latest CAD wizard report JSON."""

    bl_idname = "smile.cad_wizard_show_stage_report"
    bl_label = "Show CAD Stage Report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        raw = str(scene.get(KEY_CAD_STAGE_REPORT, "") or "")
        if not raw:
            raw = json.dumps(_cad_state_for_report(scene), indent=2, sort_keys=True)
        try:
            context.window_manager.clipboard = raw
            self.report({"INFO"}, "CAD report copied to clipboard.")
        except Exception:
            self.report({"INFO"}, "CAD report available in scene key.")
        print("[BlenderSmile][CAD_REPORT]")
        print(raw)
        return {"FINISHED"}


class SMILE_OT_cad_wizard_run_next(bpy.types.Operator):
    """Run the next required CAD stage (stage-locked)."""

    bl_idname = "smile.cad_wizard_run_next"
    bl_label = "Run Next Required CAD Step"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        st = _cad_load_state(scene)
        next_stage = None
        for s in CAD_STAGE_ORDER:
            status = str(
                (st.get("stages", {}).get(s, {}) or {}).get("status", "PENDING")
            )
            if status != "PASS":
                next_stage = s
                break
        if not next_stage:
            self.report({"INFO"}, "All CAD steps already PASS.")
            return {"FINISHED"}
        scene.smile_v2.cad_wizard_stage = str(next_stage)
        if next_stage == "H_EXPORT":
            self.report(
                {"INFO"},
                "Next required step is Export Files. Run H to choose filepath.",
            )
            return {"FINISHED"}
        res = run_cad_stage(scene, next_stage, context=context, operator=self)
        return _cad_handle_result(self, res)


class SMILE_OT_cad_wizard_run_all_dummyproof(bpy.types.Operator):
    """Run CAD Wizard stages in sequence with explicit stop guidance."""

    bl_idname = "smile.cad_wizard_run_all_dummyproof"
    bl_label = "Run Full CAD Pipeline"
    bl_options = {"REGISTER", "UNDO"}

    def _stage_fix_hint(self, stage):
        hints = {
            "A_MARGIN": "Trace and close margin in viewport, then run this button again.",
            "B_SURVEY_BLOCKOUT": "Use Axis Assistant: Suggest/From View -> Evaluate, then retry Stage B.",
            "C_SUPPORT_MARGIN": "Check margin curve continuity and re-run.",
            "D_SPACER_SAFETY": "Confirm die generation succeeded and spacer settings are valid.",
            "E_ADAPT_OUTER": "Select imported restoration mesh and click 'Use Active as Reference'.",
            "F_FINALIZE_INTAGLIO": "Resolve shell/intaglio errors, then retry Stage F.",
            "G_VALIDATE": "Fix thickness/undercut/occlusion warnings, then re-run validation.",
            "H_EXPORT": "Set export directory or run H. Export manually to choose filepath.",
        }
        return str(hints.get(str(stage), "Resolve stage issue and retry."))

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2

        if not bool(getattr(p, "cad_wizard_enabled", True)):
            self.report({"ERROR"}, "CAD Wizard is disabled. Enable CAD Wizard first.")
            return {"CANCELLED"}

        st = _cad_load_state(scene)
        mismatch, mismatch_msg = _cad_state_context_mismatch(scene, st=st)
        if mismatch:
            self.report(
                {"ERROR"},
                f"{mismatch_msg} Use Resume Saved Case or Start New Case first.",
            )
            return {"CANCELLED"}

        tid = _cad_target_tid(scene)
        self.report({"INFO"}, f"Running full CAD pipeline for T#{tid}...")

        for stage in CAD_STAGE_ORDER:
            if stage == "H_EXPORT":
                break
            p.cad_wizard_stage = str(stage)
            res = run_cad_stage(scene, stage, context=context, operator=self)
            if not bool(res.get("ok", False)):
                msg = str(res.get("message", "") or "Stage failed.")
                status = str(res.get("status", "")).upper()
                hint = self._stage_fix_hint(stage)
                if status == "IN_PROGRESS":
                    self.report(
                        {"WARNING"},
                        f"{CAD_STAGE_LABEL.get(stage, stage)} in progress: {msg} Next: {hint}",
                    )
                else:
                    self.report(
                        {"ERROR"},
                        f"{CAD_STAGE_LABEL.get(stage, stage)} failed: {msg} Next: {hint}",
                    )
                return {"CANCELLED"}

        self.report(
            {"INFO"}, "Stages A-G passed. Run H. Export when ready to save STL/OBJ."
        )
        return {"FINISHED"}


CLASSES = [
    SMILE_OT_cad_stage_a_trace_margin,
    SMILE_OT_cad_stage_b_survey_blockout,
    SMILE_OT_cad_stage_c_support_margin,
    SMILE_OT_cad_stage_d_spacer_safety,
    SMILE_OT_cad_stage_e_adapt_outer,
    SMILE_OT_cad_stage_f_finalize_intaglio,
    SMILE_OT_cad_stage_g_validate,
    SMILE_OT_cad_stage_h_export,
    SMILE_OT_cad_wizard_axis_auto_suggest,
    SMILE_OT_cad_wizard_axis_from_view,
    SMILE_OT_cad_wizard_axis_pick_2pt,
    SMILE_OT_cad_wizard_axis_evaluate,
    SMILE_OT_cad_wizard_apply_stage_b_retry,
    SMILE_OT_cad_wizard_use_active_outer_source,
    SMILE_OT_cad_wizard_clear_outer_source,
    SMILE_OT_cad_wizard_sync_context,
    SMILE_OT_cad_wizard_reset_case,
    SMILE_OT_cad_wizard_show_stage_report,
    SMILE_OT_cad_wizard_run_next,
    SMILE_OT_cad_wizard_run_all_dummyproof,
]


def register():
    """Register all CAD wizard operators with Blender."""
    if not _IN_BLENDER:
        return
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"[BlenderSmile][GUIDED] Failed to register {cls.bl_idname}: {e}")


def unregister():
    """Unregister all CAD wizard operators from Blender."""
    if not _IN_BLENDER:
        return
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"[BlenderSmile][GUIDED] Failed to unregister {cls.bl_idname}: {e}")
