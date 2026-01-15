bl_info = {
    "name": "Smile Design Pro (Merged) — Arch/Teeth/Veneer/Rig/Preview + Landmarks",
    "author": "ChatGPT",
    "version": (2026, 1, 14),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Smile",
    "category": "3D View",
    "description": "Smile design workflow: scans import, FACE/MAX/MAN landmarks + drag + align, arch tracing + smoothing, width-aware tooth layout + bridge, per-tooth tweaks + ghost preview, veneer pipeline + export, 27-handle shaping rig.",
}

import bpy
import os
import re
import math
import time
import importlib
import bmesh
import sys
import subprocess
import threading
import site
import traceback
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree
from bpy_extras.io_utils import ImportHelper

# ============================================================
# CONSTANTS
# ============================================================

COL_SCANS   = "Scans"
COL_TEETH   = "Teeth"
COL_LM      = "SmileLandmarks"
COL_ARCH    = "SmileArch"
COL_PREVIEW = "SmilePreview"
COL_WAXUP   = "Waxup"
COL_VENEER  = "Veneers"
COL_RIG     = "SmileRig"
COL_MARGINS = "VeneerMargins"

DOMAIN_FACE = "FACE"
DOMAIN_MAX  = "MAX"
DOMAIN_MAN  = "MAN"
DOMAINS = (DOMAIN_FACE, DOMAIN_MAX, DOMAIN_MAN)

DOMAIN_SHAPE = {DOMAIN_FACE: "SPHERE", DOMAIN_MAX: "CUBE", DOMAIN_MAN: "CONE"}

NEON = [
    (1.00, 0.05, 0.55, 1.0),
    (0.10, 1.00, 0.10, 1.0),
    (0.10, 0.65, 1.00, 1.0),
    (1.00, 1.00, 0.10, 1.0),
    (1.00, 0.45, 0.05, 1.0),
    (0.10, 1.00, 0.95, 1.0),
    (0.75, 0.10, 1.00, 1.0),
    (1.00, 1.00, 1.00, 1.0),
]

SUPPORTED_EXTS = {
    ".obj", ".stl", ".ply", ".fbx", ".gltf", ".glb",
    ".usd", ".usda", ".usdc", ".usdz", ".abc", ".dae"
}
FDI_REGEX = re.compile(r"#\s*(\d{2})")

KEY_ARCH_MAX_PTS = "SMILE_ARCH_MAX_PTS"
KEY_ARCH_MAN_PTS = "SMILE_ARCH_MAN_PTS"

# Veneer / Margin data stored per-tooth using scene custom props keys
KEY_MARGIN_PREFIX = "SMILE_MARGIN_PTS_"  # + object.name

_KD_CACHE = {}  # (obj.name, obj.data.name, nverts) -> KDTree

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
        # Add typical site-packages for Blender's embedded python
        for p in site.getsitepackages():
            if p and p not in sys.path:
                site.addsitedir(p)
        importlib.invalidate_caches()
    except Exception:
        pass

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
        if not _O3D_INSTALLING:
            _o3d_log("Open3D not found — starting install thread.")
            threading.Thread(target=_install_open3d_worker, daemon=True).start()
        return False

def open3d_status_string():
    if _O3D is not None:
        return "Open3D: READY"
    if _O3D_INSTALLING:
        return "Open3D: INSTALLING (see System Console)"
    if _O3D_LAST_ERROR:
        return "Open3D: MISSING (will auto-install; see System Console)"
    return "Open3D: MISSING"

# ============================================================
# BASIC HELPERS
# ============================================================

def ensure_collection(name: str):
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col

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
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)

def parse_fdi_from_name(name: str):
    m = FDI_REGEX.search(name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except:
        return None

def lm_color_for_index(idx: int):
    return NEON[(idx - 1) % len(NEON)]

# ============================================================
# VIEW3D RAYCAST + VERTEX SNAP (robust)
# ============================================================

def _view3d_utils():
    try:
        from bpy_extras import view3d_utils
        return view3d_utils
    except Exception:
        return importlib.import_module("bpy_extras.view3d_utils")

def raycast_from_mouse_to_target(context, event, target_obj, max_dist=1.0e9):
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
    coord = (event.mouse_region_x, event.mouse_region_y)
    ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

    deps = context.evaluated_depsgraph_get()
    hit, loc, norm, face_i, obj, _ = context.scene.ray_cast(deps, ray_origin, ray_dir, distance=max_dist)
    if not hit or obj is None:
        return None
    # Accept if ray hit the target object (or parent relationship)
    if obj == target_obj or obj.parent == target_obj or target_obj.parent == obj:
        return loc, norm, face_i
    return None

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

def snap_to_nearest_vertex_world(obj, world_point: Vector):
    if not obj or obj.type != "MESH":
        return world_point
    key = (obj.name, obj.data.name, len(obj.data.vertices))
    kd = _KD_CACHE.get(key)
    if not kd:
        kd = _build_vertex_kdtree_world(obj)
        _KD_CACHE[key] = kd
    co, _, _ = kd.find(world_point)
    return co
# ============================================================
# MATERIALS + MARKERS
# ============================================================

def ensure_emission_material(name: str, color_rgba, strength=25.0, alpha=1.0):
    mat = bpy.data.materials.get(name)
    if mat:
        mat.use_nodes = True
        nt = mat.node_tree
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
        emission.inputs["Color"].default_value = (color_rgba[0], color_rgba[1], color_rgba[2], alpha)
        emission.inputs["Strength"].default_value = strength
        try:
            nt.links.new(emission.outputs["Emission"], out.inputs["Surface"])
        except:
            pass
        mat.blend_method = "BLEND" if alpha < 0.999 else "OPAQUE"
        return mat

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = strength
    emit.inputs["Color"].default_value = (color_rgba[0], color_rgba[1], color_rgba[2], alpha)
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    mat.blend_method = "BLEND" if alpha < 0.999 else "OPAQUE"
    return mat

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

def _mesh_primitive(shape: str, name: str):
    me = bpy.data.meshes.get(name)
    if me:
        return me
    bm = bmesh.new()
    if shape == "SPHERE":
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
    elif shape == "CUBE":
        bmesh.ops.create_cube(bm, size=2.0)
    elif shape == "CONE":
        bmesh.ops.create_cone(bm, segments=24, radius1=1.0, radius2=0.0, depth=2.0)
    elif shape == "ICO":
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    else:
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
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
        except:
            pass

def make_marker(name: str, world_location: Vector, size: float, target_obj, rgba, shape="SPHERE", sticky=True):
    if not target_obj or target_obj.type != "MESH":
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

    # parent to target while keeping transform
    if obj.parent != target_obj:
        mw = obj.matrix_world.copy()
        obj.parent = target_obj
        obj.matrix_parent_inverse = target_obj.matrix_world.inverted()
        obj.matrix_world = mw

    obj.matrix_world.translation = world_location
    obj.scale = (size, size, size)
    obj.show_in_front = True

    # remove old SMILE shrinkwrap
    for c in list(obj.constraints):
        if c.type == "SHRINKWRAP" and c.name.startswith("SMILE_"):
            obj.constraints.remove(c)

    if sticky:
        sw = obj.constraints.new("SHRINKWRAP")
        sw.name = "SMILE_SurfaceLock"
        sw.target = target_obj
        _set_shrinkwrap_method_safe(sw)
        try:
            sw.distance = 0.0
        except:
            pass

    obj["SMILE_ATTACH_TARGET"] = target_obj.name
    obj["SMILE_CREATED_AT"] = float(time.time())
    bpy.context.view_layer.update()
    return obj

# ============================================================
# IMPORT (multi-format)
# ============================================================

def _op_props(op):
    try:
        return op.get_rna_type().properties
    except:
        return {}

def _import_with_operator(op, kwargs):
    props = _op_props(op)
    safe = {k: v for k, v in kwargs.items() if k in props}
    return op(**safe)

def import_mesh_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    pre = set(bpy.data.objects)

    if ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            _import_with_operator(bpy.ops.wm.obj_import, {"filepath": filepath})
        elif hasattr(bpy.ops.import_scene, "obj"):
            _import_with_operator(bpy.ops.import_scene.obj, {"filepath": filepath})
        else:
            raise RuntimeError("OBJ importer not available.")
    elif ext == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            _import_with_operator(bpy.ops.wm.stl_import, {"filepath": filepath})
        elif hasattr(bpy.ops.import_mesh, "stl"):
            _import_with_operator(bpy.ops.import_mesh.stl, {"filepath": filepath})
        else:
            raise RuntimeError("STL importer not available.")
    elif ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            _import_with_operator(bpy.ops.wm.ply_import, {"filepath": filepath})
        elif hasattr(bpy.ops.import_mesh, "ply"):
            _import_with_operator(bpy.ops.import_mesh.ply, {"filepath": filepath})
        else:
            raise RuntimeError("PLY importer not available.")
    elif ext in {".gltf", ".glb"}:
        if hasattr(bpy.ops.import_scene, "gltf"):
            _import_with_operator(bpy.ops.import_scene.gltf, {"filepath": filepath})
        else:
            raise RuntimeError("glTF importer not available.")
    elif ext == ".fbx":
        if hasattr(bpy.ops.import_scene, "fbx"):
            _import_with_operator(bpy.ops.import_scene.fbx, {"filepath": filepath})
        else:
            raise RuntimeError("FBX importer not available.")
    elif ext in {".usd", ".usda", ".usdc", ".usdz"}:
        if hasattr(bpy.ops.wm, "usd_import"):
            _import_with_operator(bpy.ops.wm.usd_import, {"filepath": filepath})
        elif hasattr(bpy.ops.import_scene, "usd"):
            _import_with_operator(bpy.ops.import_scene.usd, {"filepath": filepath})
        else:
            raise RuntimeError("USD importer not available.")
    elif ext == ".abc":
        if hasattr(bpy.ops.wm, "alembic_import"):
            _import_with_operator(bpy.ops.wm.alembic_import, {"filepath": filepath})
        elif hasattr(bpy.ops.import_scene, "alembic"):
            _import_with_operator(bpy.ops.import_scene.alembic, {"filepath": filepath})
        else:
            raise RuntimeError("Alembic importer not available.")
    elif ext == ".dae":
        if hasattr(bpy.ops.wm, "collada_import"):
            _import_with_operator(bpy.ops.wm.collada_import, {"filepath": filepath})
        elif hasattr(bpy.ops.import_scene, "dae"):
            _import_with_operator(bpy.ops.import_scene.dae, {"filepath": filepath})
        else:
            raise RuntimeError("DAE importer not available.")
    else:
        raise RuntimeError(f"Unsupported extension: {ext}")

    bpy.context.view_layer.update()
    post = set(bpy.data.objects)
    return [o for o in (post - pre) if o.type == "MESH"]

# ============================================================
# LANDMARKS: naming, indexing, matching
# ============================================================

def lm_name(domain: str, idx: int):
    return f"{domain}_{idx:03d}"

def indices_in_domain(domain: str):
    inds = set()
    for o in bpy.data.objects:
        if o.get("SMILE_LM_DOMAIN") == domain and o.get("SMILE_LM_INDEX") is not None:
            inds.add(int(o["SMILE_LM_INDEX"]))
    return inds

def get_landmark_obj(domain: str, idx: int):
    return bpy.data.objects.get(lm_name(domain, idx))

def matched_landmark_points(domain_a: str, domain_b: str):
    pts_a, pts_b = [], []
    matched = []
    inds = indices_in_domain(domain_a)
    for idx in sorted(list(inds)):
        oa = get_landmark_obj(domain_a, idx)
        ob = get_landmark_obj(domain_b, idx)
        if oa and ob:
            matched.append(idx)
            pts_a.append(oa.matrix_world.translation.copy())
            pts_b.append(ob.matrix_world.translation.copy())
    return matched, pts_a, pts_b

def next_index_fill_missing(domain_a: str, domain_b: str):
    a = indices_in_domain(domain_a)
    b = indices_in_domain(domain_b)
    if not a and not b:
        return 1
    max_check = (max(a.union(b)) + 1) if (a or b) else 1
    for i in range(1, max_check + 2):
        if not (i in a and i in b):
            return i
    return max_check + 1

def next_index_continue(domain_a: str, domain_b: str):
    a = indices_in_domain(domain_a)
    b = indices_in_domain(domain_b)
    mx = 0
    if a: mx = max(mx, max(a))
    if b: mx = max(mx, max(b))
    return mx + 1 if mx > 0 else 1

def choose_next_pair_index(props, domain_a: str, domain_b: str):
    if props.lm_lock_index:
        return int(props.lm_index_override)
    if props.lm_index_mode == "CONTINUE":
        return next_index_continue(domain_a, domain_b)
    return next_index_fill_missing(domain_a, domain_b)

def last_landmark_object():
    cands = [o for o in bpy.data.objects if o.get("SMILE_CREATED_AT") is not None and o.get("SMILE_LM_DOMAIN") in DOMAINS]
    if not cands:
        return None
    cands.sort(key=lambda o: float(o.get("SMILE_CREATED_AT", 0.0)))
    return cands[-1]

# ============================================================
# KABSCH ALIGNMENT
# ============================================================

def kabsch_rigid(A, B):
    n = len(A)
    if n < 3:
        raise RuntimeError("Need at least 3 matched landmark pairs.")

    ca = Vector((0, 0, 0))
    cb = Vector((0, 0, 0))
    for i in range(n):
        ca += A[i]
        cb += B[i]
    ca /= n
    cb /= n

    Sxx=Sxy=Sxz=Syx=Syy=Syz=Szx=Szy=Szz=0.0
    for i in range(n):
        a = A[i] - ca
        b = B[i] - cb
        Sxx += a.x*b.x; Sxy += a.x*b.y; Sxz += a.x*b.z
        Syx += a.y*b.x; Syy += a.y*b.y; Syz += a.y*b.z
        Szx += a.z*b.x; Szy += a.z*b.y; Szz += a.z*b.z

    trace = Sxx + Syy + Szz
    N = [[0.0]*4 for _ in range(4)]
    N[0][0] = trace
    N[0][1] = Syz - Szy
    N[0][2] = Szx - Sxz
    N[0][3] = Sxy - Syx

    N[1][0] = Syz - Szy
    N[1][1] = Sxx - Syy - Szz
    N[1][2] = Sxy + Syx
    N[1][3] = Szx + Sxz

    N[2][0] = Szx - Sxz
    N[2][1] = Sxy + Syx
    N[2][2] = -Sxx + Syy - Szz
    N[2][3] = Syz + Szy

    N[3][0] = Sxy - Syx
    N[3][1] = Szx + Sxz
    N[3][2] = Syz + Szy
    N[3][3] = -Sxx - Syy + Szz

    q = [1.0, 0.0, 0.0, 0.0]
    for _ in range(30):
        x0 = N[0][0]*q[0] + N[0][1]*q[1] + N[0][2]*q[2] + N[0][3]*q[3]
        x1 = N[1][0]*q[0] + N[1][1]*q[1] + N[1][2]*q[2] + N[1][3]*q[3]
        x2 = N[2][0]*q[0] + N[2][1]*q[1] + N[2][2]*q[2] + N[2][3]*q[3]
        x3 = N[3][0]*q[0] + N[3][1]*q[1] + N[3][2]*q[2] + N[3][3]*q[3]
        norm = math.sqrt(x0*x0 + x1*x1 + x2*x2 + x3*x3) + 1e-12
        q = [x0/norm, x1/norm, x2/norm, x3/norm]

    w,x,y,z = q[0], q[1], q[2], q[3]
    R = Matrix((
        (1-2*(y*y+z*z), 2*(x*y - z*w), 2*(x*z + y*w)),
        (2*(x*y + z*w), 1-2*(x*x+z*z), 2*(y*z - x*w)),
        (2*(x*z - y*w), 2*(y*z + x*w), 1-2*(x*x+y*y)),
    ))
    t = cb - (R @ (ca))
    return R, t

def apply_rigid_to_object(obj, R: Matrix, t: Vector):
    M = Matrix.Translation(t) @ R.to_4x4()
    obj.matrix_world = M @ obj.matrix_world

def alignment_error_stats(domain_a, domain_b):
    _matched, A, B = matched_landmark_points(domain_a, domain_b)
    if not A:
        return 0, 0.0, 0.0
    d2 = []
    d = []
    for i in range(len(A)):
        dist = (A[i] - B[i]).length
        d.append(dist)
        d2.append(dist * dist)
    rms = math.sqrt(sum(d2) / len(d2))
    mx = max(d) if d else 0.0
    return len(A), rms, mx
# ============================================================
# ALIGNMENT — diagnostics + plane constraint + Open3D ICP (FIXED)
# ============================================================

def _safe_eigenvalues_cov(points):
    """
    Returns (ok, sorted_eigs) where eigs are ascending.
    If eigen fails, returns ok=False.
    """
    if len(points) < 3:
        return False, [0.0, 0.0, 0.0]
    cen = sum(points, Vector()) / len(points)
    cov = Matrix(((0.0,0.0,0.0),(0.0,0.0,0.0),(0.0,0.0,0.0)))
    for p in points:
        d = p - cen
        cov[0][0] += d.x*d.x; cov[0][1] += d.x*d.y; cov[0][2] += d.x*d.z
        cov[1][0] += d.y*d.x; cov[1][1] += d.y*d.y; cov[1][2] += d.y*d.z
        cov[2][0] += d.z*d.x; cov[2][1] += d.z*d.y; cov[2][2] += d.z*d.z
    try:
        eig_vecs, eig_vals = cov.eigen()
        vals = sorted([float(v) for v in eig_vals])
        return True, vals
    except Exception:
        return False, [0.0, 0.0, 0.0]

def landmark_condition_number(points):
    ok, vals = _safe_eigenvalues_cov(points)
    if not ok:
        return False, 0.0
    # condition ~ largest / smallest
    small = max(vals[0], 1e-12)
    cond = vals[2] / small
    # cond too large means points nearly planar/collinear
    return (cond <= 1.0e6), cond

def best_fit_plane_normal(points):
    ok, vals = _safe_eigenvalues_cov(points)
    if not ok:
        return None
    # rebuild cov to get eigenvectors (we need smallest eigenvector)
    cen = sum(points, Vector()) / len(points)
    cov = Matrix(((0.0,0.0,0.0),(0.0,0.0,0.0),(0.0,0.0,0.0)))
    for p in points:
        d = p - cen
        cov[0][0] += d.x*d.x; cov[0][1] += d.x*d.y; cov[0][2] += d.x*d.z
        cov[1][0] += d.y*d.x; cov[1][1] += d.y*d.y; cov[1][2] += d.y*d.z
        cov[2][0] += d.z*d.x; cov[2][1] += d.z*d.y; cov[2][2] += d.z*d.z
    try:
        eig_vecs, eig_vals = cov.eigen()
        min_i = list(eig_vals).index(min(eig_vals))
        n = eig_vecs[min_i].normalized()
        return n
    except Exception:
        return None

def _matrix_to_o3d_4x4(M: Matrix):
    # Open3D expects list-of-lists float
    return [[float(M[r][c]) for c in range(4)] for r in range(4)]

def _o3d_mesh_from_blender(obj, o3d):
    """
    Robust conversion:
      - evaluated mesh
      - triangulate via loop_triangles
      - return Open3D TriangleMesh
    """
    import numpy as np

    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()
    try:
        me.calc_loop_triangles()
        verts = np.array([v.co[:] for v in me.vertices], dtype=np.float64)
        tris = np.array([lt.vertices[:] for lt in me.loop_triangles], dtype=np.int32)

        mesh = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(verts),
            o3d.utility.Vector3iVector(tris)
        )
        # cleanup improves normals/ICP stability
        try:
            mesh.remove_duplicated_vertices()
            mesh.remove_degenerate_triangles()
            mesh.remove_duplicated_triangles()
        except Exception:
            pass
        try:
            mesh.compute_vertex_normals()
        except Exception:
            pass
        return mesh
    finally:
        eo.to_mesh_clear()

def run_open3d_icp_refine(source_obj, target_obj, init_total: Matrix, samples: int, threshold: float, normal_radius: float):
    """
    Returns T_icp_total (4x4 Matrix) mapping ORIGINAL source points -> target,
    using init_total as the initial guess.
    """
    if _O3D is None:
        raise RuntimeError("Open3D not available.")
    o3d = _O3D

    mesh_s = _o3d_mesh_from_blender(source_obj, o3d)
    mesh_t = _o3d_mesh_from_blender(target_obj, o3d)

    # Uniform sampling (per your choice)
    pcd_s = mesh_s.sample_points_uniformly(number_of_points=int(samples))
    pcd_t = mesh_t.sample_points_uniformly(number_of_points=int(samples))

    # Normals for point-to-plane
    r = float(normal_radius)
    if r <= 0.0:
        r = max(threshold * 2.0, 1e-6)
    try:
        pcd_s.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=r, max_nn=30))
        pcd_t.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=r, max_nn=30))
    except Exception:
        # fallback
        pcd_s.estimate_normals()
        pcd_t.estimate_normals()

    init = _matrix_to_o3d_4x4(init_total)

    res = o3d.pipelines.registration.registration_icp(
        pcd_s,
        pcd_t,
        float(threshold),
        init,
        o3d.pipelines.registration.TransformationEstimationPointToPlane()
    )

    T = Matrix(res.transformation)
    return T

# ============================================================
# ARCH / TEETH / VENEER / RIG (UNCHANGED FROM YOUR SCRIPT)
# ============================================================

def _arch_key(domain: str):
    return KEY_ARCH_MAX_PTS if domain == DOMAIN_MAX else KEY_ARCH_MAN_PTS

def get_arch_points(scene, domain: str):
    raw = scene.get(_arch_key(domain), [])
    return [Vector(v) for v in raw]

def set_arch_points(scene, domain: str, pts):
    scene[_arch_key(domain)] = [[p.x, p.y, p.z] for p in pts]

def arch_curve_name(domain: str):
    return f"ARCH_{domain}_CURVE"

def clear_arch_markers(domain: str):
    prefix = f"ARCH_{domain}_P_"
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix):
            delete_object(o)

def build_arch_curve(domain: str, pts, curve_type="BEZIER", resolution=24, smooth_strength=0.35):
    if len(pts) < 2:
        return None

    name = arch_curve_name(domain)
    curve_data = bpy.data.curves.new(name=name + "_DATA", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = int(resolution)

    if curve_type == "POLY":
        spline = curve_data.splines.new(type="POLY")
        spline.points.add(len(pts) - 1)
        for i, p in enumerate(pts):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)
    else:
        sp = [p.copy() for p in pts]
        if len(sp) >= 3 and smooth_strength > 0.0:
            s = max(0.0, min(1.0, smooth_strength))
            for _ in range(2):
                new = sp[:]
                for i in range(1, len(sp)-1):
                    avg = (sp[i-1] + sp[i] + sp[i+1]) / 3.0
                    new[i] = sp[i].lerp(avg, s)
                sp = new

        spline = curve_data.splines.new(type="BEZIER")
        spline.bezier_points.add(len(sp) - 1)
        for i, p in enumerate(sp):
            bp = spline.bezier_points[i]
            bp.co = p
            bp.handle_left_type = "AUTO"
            bp.handle_right_type = "AUTO"

    curve_obj = bpy.data.objects.get(name)
    if curve_obj:
        curve_obj.data = curve_data
    else:
        curve_obj = bpy.data.objects.new(name, curve_data)
        bpy.context.scene.collection.objects.link(curve_obj)
        link_to_collection(curve_obj, ensure_collection(COL_ARCH))
    curve_obj.show_in_front = True
    return curve_obj

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
    except:
        pass

    mw = curve_obj.matrix_world
    spl = eobj.data.splines[0]
    if spl.type == "POLY":
        pts = [mw @ Vector((p.co.x, p.co.y, p.co.z)) for p in spl.points]
    else:
        pts = [mw @ bp.co for bp in spl.bezier_points]
    return pts

def curve_tangent_at_index(samples_pts, i):
    if len(samples_pts) < 2:
        return Vector((1,0,0))
    if i == 0:
        t = samples_pts[1] - samples_pts[0]
    elif i == len(samples_pts)-1:
        t = samples_pts[-1] - samples_pts[-2]
    else:
        t = samples_pts[i+1] - samples_pts[i-1]
    return t if t.length > 1e-9 else Vector((1,0,0))

# ============================================================
# TEETH helpers (unchanged)
# ============================================================

def tooth_objects_in_collection():
    col = ensure_collection(COL_TEETH)
    return [o for o in col.objects if o and o.type == "MESH"]

def sort_teeth_by_fdi(mesh_objs):
    items = []
    for o in mesh_objs:
        fdi = parse_fdi_from_name(o.name)
        if fdi is None:
            continue
        items.append((fdi, o))
    items.sort(key=lambda x: x[0])
    return [o for _, o in items]

def bbox_world(obj):
    mw = obj.matrix_world
    corners = [mw @ Vector(c) for c in obj.bound_box]
    mn = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    mx = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return mn, mx

def mesiodistal_width_estimate(obj, axis="X"):
    mn, mx = bbox_world(obj)
    return (mx.x - mn.x) if axis == "X" else (mx.y - mn.y)

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

def apply_tooth_tweaks(obj, arch_tangent: Vector, occlusal_up: Vector):
    ensure_tooth_params(obj)

    z = arch_tangent.normalized() if arch_tangent.length > 1e-9 else Vector((1,0,0))
    y = occlusal_up.normalized() if occlusal_up.length > 1e-9 else Vector((0,0,1))
    x = y.cross(z)
    if x.length < 1e-9:
        x = Vector((1,0,0))
    x.normalize()
    y = z.cross(x).normalized()

    R = Matrix((x, y, z)).transposed().to_4x4()

    w = float(obj.get("SMILE_W_SCALE", 1.0))
    l = float(obj.get("SMILE_L_SCALE", 1.0))
    cant = math.radians(float(obj.get("SMILE_CANT_DEG", 0.0)))
    mid = float(obj.get("SMILE_MIDLINE_MM", 0.0))

    T = Matrix.Translation(obj.matrix_world.translation)
    S = Matrix.Diagonal((w, 1.0, l, 1.0))
    C = Matrix.Rotation(cant, 4, z)
    M = Matrix.Translation(x * mid)

    obj.matrix_world = T @ (R @ (M @ (C @ (S @ R.inverted()))))

def make_ghost_preview(obj):
    ensure_tooth_params(obj)
    ghost_name = obj.name + "_GHOST"
    ghost = bpy.data.objects.get(ghost_name)
    if not ghost:
        ghost = obj.copy()
        ghost.data = obj.data.copy()
        ghost.name = ghost_name
        bpy.context.scene.collection.objects.link(ghost)
        link_to_collection(ghost, ensure_collection(COL_PREVIEW))
        ghost.show_in_front = True
        ghost.display_type = "SOLID"
        ghost["SMILE_GHOST_OF"] = obj.name
        mat = ensure_transparent_preview_material()
        ghost.data.materials.clear()
        ghost.data.materials.append(mat)

    ghost.matrix_world = obj.matrix_world.copy()
    ghost.hide_set(False)
    return ghost

def update_ghosts():
    for o in tooth_objects_in_collection():
        ensure_tooth_params(o)
        if int(o.get("SMILE_GHOST", 0)) == 1:
            make_ghost_preview(o)
        else:
            g = bpy.data.objects.get(o.name + "_GHOST")
            if g:
                g.hide_set(True)

def distribute_teeth_width_aware(curve_obj, teeth_sorted, gap_mm=0.25, bridge_mode=False):
    pts = curve_world_points(curve_obj)
    if len(pts) < 2:
        raise RuntimeError("Arch curve sampling failed (need a real curve).")

    segL = []
    cum = [0.0]
    for i in range(len(pts)-1):
        L = (pts[i+1]-pts[i]).length
        segL.append(L)
        cum.append(cum[-1] + L)
    total = cum[-1]
    if total < 1e-9:
        raise RuntimeError("Arch curve too short.")

    def point_at_distance(d):
        d = max(0.0, min(total, d))
        for i, L in enumerate(segL):
            if cum[i] + L >= d:
                t = (d - cum[i]) / L if L > 1e-9 else 0.0
                return pts[i].lerp(pts[i+1], t), i
        return pts[-1], len(pts)-1

    groups = []
    if bridge_mode:
        i = 0
        while i < len(teeth_sorted):
            t = teeth_sorted[i]
            ensure_tooth_params(t)
            bid = int(t.get("SMILE_BRIDGE_ID", 0))
            if bid == 0:
                groups.append([t])
                i += 1
            else:
                g = [t]
                i += 1
                while i < len(teeth_sorted):
                    nt = teeth_sorted[i]
                    ensure_tooth_params(nt)
                    if int(nt.get("SMILE_BRIDGE_ID", 0)) == bid:
                        g.append(nt)
                        i += 1
                    else:
                        break
                groups.append(g)
    else:
        groups = [[t] for t in teeth_sorted]

    widths = []
    for g in groups:
        if len(g) == 1:
            w = max(0.1, mesiodistal_width_estimate(g[0], axis="X"))
        else:
            w = sum(max(0.1, mesiodistal_width_estimate(t, axis="X")) for t in g) + gap_mm*(len(g)-1)
        widths.append(w)

    total_w = sum(widths) + gap_mm*(len(groups)-1)
    start_d = max(0.0, (total - total_w) * 0.5)
    cursor = start_d

    occlusal_up = Vector((0,0,1))
    for gi, g in enumerate(groups):
        w = widths[gi]
        mid_d = cursor + w*0.5
        pos, sample_i = point_at_distance(mid_d)
        tan = curve_tangent_at_index(pts, sample_i)
        if len(g) == 1:
            t = g[0]
            t.matrix_world.translation = pos
            apply_tooth_tweaks(t, tan, occlusal_up)
        else:
            local_cursor = cursor
            for t in g:
                tw = max(0.1, mesiodistal_width_estimate(t, axis="X"))
                tmid = local_cursor + tw*0.5
                p2, si2 = point_at_distance(tmid)
                tan2 = curve_tangent_at_index(pts, si2)
                t.matrix_world.translation = p2
                apply_tooth_tweaks(t, tan2, occlusal_up)
                local_cursor += tw + gap_mm

        cursor += w + gap_mm

# ============================================================
# VENEER PIPELINE (unchanged from your script)
# ============================================================

def set_margin_points(scene, tooth_obj, pts):
    scene[KEY_MARGIN_PREFIX + tooth_obj.name] = [[p.x, p.y, p.z] for p in pts]

def get_margin_points(scene, tooth_obj):
    raw = scene.get(KEY_MARGIN_PREFIX + tooth_obj.name, [])
    return [Vector(v) for v in raw]

def margin_curve_name(tooth_obj):
    return f"MARGIN_{tooth_obj.name}"

def build_margin_curve(tooth_obj, pts, resolution=24):
    if len(pts) < 3:
        return None
    name = margin_curve_name(tooth_obj)
    curve_data = bpy.data.curves.new(name=name + "_DATA", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = int(resolution)

    spl = curve_data.splines.new("BEZIER")
    spl.bezier_points.add(len(pts)-1)
    for i, p in enumerate(pts):
        bp = spl.bezier_points[i]
        bp.co = p
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    spl.use_cyclic_u = True

    obj = bpy.data.objects.get(name)
    if obj:
        obj.data = curve_data
    else:
        obj = bpy.data.objects.new(name, curve_data)
        bpy.context.scene.collection.objects.link(obj)
        link_to_collection(obj, ensure_collection(COL_MARGINS))
    obj.show_in_front = True
    return obj

def nearest_distance_to_points(p: Vector, pts):
    best = 1e18
    for q in pts:
        d = (p - q).length
        if d < best:
            best = d
    return best

def create_margin_vertex_group(tooth_obj, margin_pts_world, band_mm=2.0, offset_mm=0.0, vg_name="SMILE_MARGIN_BAND"):
    if tooth_obj.type != "MESH":
        return None
    vg = tooth_obj.vertex_groups.get(vg_name)
    if not vg:
        vg = tooth_obj.vertex_groups.new(name=vg_name)

    for v in tooth_obj.data.vertices:
        try:
            vg.remove([v.index])
        except:
            pass

    mw = tooth_obj.matrix_world
    thresh = max(0.1, band_mm + max(0.0, offset_mm))

    for v in tooth_obj.data.vertices:
        wp = mw @ v.co
        d = nearest_distance_to_points(wp, margin_pts_world)
        if d <= thresh:
            w = 1.0 - (d / thresh)
            vg.add([v.index], w, "REPLACE")
    return vg

def duplicate_mesh_object(src, name, collection):
    dup = src.copy()
    dup.data = src.data.copy()
    dup.name = name
    bpy.context.scene.collection.objects.link(dup)
    link_to_collection(dup, ensure_collection(collection))
    return dup

def ensure_veneer_params(scene):
    if scene.get("SMILE_VEN_INIT") == 1:
        return
    scene["SMILE_VEN_INIT"] = 1
    scene["SMILE_VEN_THICK_MIN"] = 0.3
    scene["SMILE_VEN_THICK_MAX"] = 0.7
    scene["SMILE_VEN_MARGIN_OFFSET"] = 0.0
    scene["SMILE_VEN_MARGIN_BAND"] = 2.0
    scene["SMILE_VEN_CONTACT_THICK"] = 0.15
    scene["SMILE_VEN_BOOLEAN_MODE"] = "NONE"  # NONE / DIFFERENCE
    scene["SMILE_VEN_EXPORT_FMT"] = "STL"     # STL / OBJ

def veneer_make_for_tooth(scene, tooth_obj, use_waxup=True):
    ensure_veneer_params(scene)

    thick_min = float(scene["SMILE_VEN_THICK_MIN"])
    thick_max = float(scene["SMILE_VEN_THICK_MAX"])
    margin_offset = float(scene["SMILE_VEN_MARGIN_OFFSET"])
    margin_band = float(scene["SMILE_VEN_MARGIN_BAND"])
    contact_thick = float(scene["SMILE_VEN_CONTACT_THICK"])
    boolean_mode = scene["SMILE_VEN_BOOLEAN_MODE"]

    mpts = get_margin_points(scene, tooth_obj)
    if len(mpts) < 3:
        raise RuntimeError("No margin ring for this tooth. Trace margin first.")

    build_margin_curve(tooth_obj, mpts)
    create_margin_vertex_group(tooth_obj, mpts, band_mm=margin_band, offset_mm=margin_offset, vg_name="SMILE_MARGIN_BAND")

    base = tooth_obj
    wax_name = tooth_obj.name + "_WAX"
    wax = bpy.data.objects.get(wax_name)
    if not wax:
        wax = duplicate_mesh_object(base, wax_name, COL_WAXUP)
    wax.matrix_world = base.matrix_world.copy()

    ensure_tooth_params(wax)
    wax["SMILE_W_SCALE"] = tooth_obj.get("SMILE_W_SCALE", 1.0)
    wax["SMILE_L_SCALE"] = tooth_obj.get("SMILE_L_SCALE", 1.0)
    wax["SMILE_CANT_DEG"] = tooth_obj.get("SMILE_CANT_DEG", 0.0)
    wax["SMILE_MIDLINE_MM"] = tooth_obj.get("SMILE_MIDLINE_MM", 0.0)

    ven_name = tooth_obj.name + "_VENEER"
    ven = bpy.data.objects.get(ven_name)
    if not ven:
        ven = duplicate_mesh_object(wax, ven_name, COL_VENEER)
        ven.show_in_front = True
    ven.matrix_world = wax.matrix_world.copy()

    if "SMILE_MARGIN_BAND" in [vg.name for vg in tooth_obj.vertex_groups]:
        dst_vg = ven.vertex_groups.get("SMILE_MARGIN_BAND") or ven.vertex_groups.new(name="SMILE_MARGIN_BAND")
        for v in ven.data.vertices:
            try:
                dst_vg.remove([v.index])
            except:
                pass
        for v in tooth_obj.data.vertices:
            w = 0.0
            for g in v.groups:
                if tooth_obj.vertex_groups[g.group].name == "SMILE_MARGIN_BAND":
                    w = g.weight
                    break
            if w > 0.0:
                dst_vg.add([v.index], w, "REPLACE")

    ven.modifiers.clear()

    mask = ven.modifiers.new("SMILE_MASK", "MASK")
    mask.vertex_group = "SMILE_MARGIN_BAND"
    mask.invert_vertex_group = False

    solid = ven.modifiers.new("SMILE_SOLIDIFY", "SOLIDIFY")
    solid.thickness = max(thick_min, thick_max)
    solid.offset = 1.0
    solid.use_even_offset = True
    solid.use_quality_normals = True

    sw = ven.modifiers.new("SMILE_INTAGLIO", "SHRINKWRAP")
    sw.target = tooth_obj
    _set_shrinkwrap_method_safe(sw)
    try:
        sw.offset = float(thick_min)
    except:
        pass
    try:
        sw.wrap_mode = 'OUTSIDE'
    except:
        pass

    disp = ven.modifiers.new("SMILE_CONTACT", "DISPLACE")
    disp.strength = float(contact_thick)
    disp.vertex_group = "SMILE_MARGIN_BAND"
    try:
        tex = bpy.data.textures.get("SMILE_NOISE") or bpy.data.textures.new("SMILE_NOISE", "CLOUDS")
        disp.texture = tex
    except:
        pass

    if boolean_mode == "DIFFERENCE":
        bo = ven.modifiers.new("SMILE_BOOL", "BOOLEAN")
        bo.operation = "DIFFERENCE"
        bo.object = tooth_obj

    return ven, wax

def export_object_mesh(obj, filepath, fmt="STL"):
    ensure_active(obj)
    fmt = fmt.upper()
    if fmt == "STL":
        if hasattr(bpy.ops.wm, "stl_export"):
            bpy.ops.wm.stl_export(filepath=filepath, use_selection=True)
        elif hasattr(bpy.ops.export_mesh, "stl"):
            bpy.ops.export_mesh.stl(filepath=filepath, use_selection=True)
        else:
            raise RuntimeError("STL export operator not available.")
    elif fmt == "OBJ":
        if hasattr(bpy.ops.wm, "obj_export"):
            bpy.ops.wm.obj_export(filepath=filepath, export_selected_objects=True)
        elif hasattr(bpy.ops.export_scene, "obj"):
            bpy.ops.export_scene.obj(filepath=filepath, use_selection=True)
        else:
            raise RuntimeError("OBJ export operator not available.")
    else:
        raise RuntimeError("Unsupported export format.")

# ============================================================
# SHAPING RIG: 3×3×3 lattice with 27 empties hooks (unchanged)
# ============================================================

def create_lattice_rig_for_tooth(tooth_obj, size_pad=1.15):
    ensure_collection(COL_RIG)
    ensure_collection(COL_TEETH)

    lat_name = tooth_obj.name + "_LAT"
    lat = bpy.data.objects.get(lat_name)

    mn, mx = bbox_world(tooth_obj)
    center = (mn + mx) * 0.5
    dims = (mx - mn) * size_pad

    if not lat:
        lat_data = bpy.data.lattices.new(lat_name + "_DATA")
        lat_data.points_u = 3
        lat_data.points_v = 3
        lat_data.points_w = 3
        lat = bpy.data.objects.new(lat_name, lat_data)
        bpy.context.scene.collection.objects.link(lat)
        link_to_collection(lat, ensure_collection(COL_RIG))

    lat.location = center
    lat.scale = Vector((dims.x * 0.5, dims.y * 0.5, dims.z * 0.5))

    mod = tooth_obj.modifiers.get("SMILE_LATTICE") or tooth_obj.modifiers.new("SMILE_LATTICE", "LATTICE")
    mod.object = lat

    handles = []
    for w in range(3):
        for v in range(3):
            for u in range(3):
                idx = (w*9 + v*3 + u)
                empty_name = f"{tooth_obj.name}_H_{idx:02d}"
                e = bpy.data.objects.get(empty_name)
                if not e:
                    e = bpy.data.objects.new(empty_name, None)
                    e.empty_display_type = "SPHERE"
                    e.empty_display_size = 0.8
                    bpy.context.scene.collection.objects.link(e)
                    link_to_collection(e, ensure_collection(COL_RIG))

                fu = -1.0 + (u/2.0)*2.0
                fv = -1.0 + (v/2.0)*2.0
                fw = -1.0 + (w/2.0)*2.0
                e.location = lat.matrix_world @ Vector((fu, fv, fw))
                e["SMILE_HANDLE_FOR"] = tooth_obj.name
                e["SMILE_HANDLE_INDEX"] = idx
                handles.append(e)

    ensure_active(lat)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.lattice.select_all(action="DESELECT")

    for w in range(3):
        for v in range(3):
            for u in range(3):
                idx = w*9 + v*3 + u
                p = lat.data.points[idx]
                p.select = True
                ensure_active(lat)
                bpy.ops.object.hook_add_newob()
                hook_mod = lat.modifiers[-1]
                if hook_mod.type == "HOOK":
                    hook_mod.object = handles[idx]
                p.select = False

    bpy.ops.object.mode_set(mode="OBJECT")
    return lat, handles

# ============================================================
# OPERATORS
# ============================================================

class SMILE_OT_import_scan(bpy.types.Operator, ImportHelper):
    bl_idname = "smile.import_scan"
    bl_label = "Import Scan (mesh)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: bpy.props.StringProperty(
        default="*.obj;*.stl;*.ply;*.fbx;*.gltf;*.glb;*.usd;*.usda;*.usdc;*.usdz;*.abc;*.dae",
        options={"HIDDEN"},
    )

    def execute(self, context):
        ensure_collection(COL_SCANS)
        meshes = import_mesh_file(self.filepath)
        if not meshes:
            self.report({"ERROR"}, "No mesh imported.")
            return {"CANCELLED"}
        for o in meshes:
            link_to_collection(o, ensure_collection(COL_SCANS))
        self.report({"INFO"}, f"Imported {len(meshes)} mesh object(s).")
        return {"FINISHED"}

class SMILE_OT_set_domain_target(bpy.types.Operator):
    bl_idname = "smile.set_domain_target"
    bl_label = "Set Domain Target From Selection"
    bl_options = {"REGISTER", "UNDO"}

    domain: bpy.props.EnumProperty(
        items=[(DOMAIN_FACE, "FACE", ""), (DOMAIN_MAX, "MAX", ""), (DOMAIN_MAN, "MAN", "")],
        default=DOMAIN_FACE
    )

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first (active object).")
            return {"CANCELLED"}
        p = context.scene.smile_props
        if self.domain == DOMAIN_FACE:
            p.face_target = obj.name
        elif self.domain == DOMAIN_MAX:
            p.max_target = obj.name
        else:
            p.man_target = obj.name
        link_to_collection(obj, ensure_collection(COL_SCANS))
        self.report({"INFO"}, f"{self.domain} target = {obj.name}")
        return {"FINISHED"}

class SMILE_OT_place_paired_landmarks(bpy.types.Operator):
    bl_idname = "smile.place_paired_landmarks"
    bl_label = "Place Paired Landmarks (auto-switch)"
    bl_options = {"REGISTER", "UNDO"}

    _idx = None
    _await_domain = None
    _domain_a = None
    _domain_b = None

    def invoke(self, context, event):
        p = context.scene.smile_props
        self._domain_a = p.pair_domain_a
        self._domain_b = p.pair_domain_b
        if self._domain_a == self._domain_b:
            self.report({"ERROR"}, "Pick two different domains for pairing.")
            return {"CANCELLED"}

        self._idx = choose_next_pair_index(p, self._domain_a, self._domain_b)
        self._await_domain = self._domain_b if p.pair_start_with_b else self._domain_a

        context.window_manager.modal_handler_add(self)
        first = self._await_domain
        second = self._domain_a if first == self._domain_b else self._domain_b
        self.report({"INFO"}, f"Placing #{self._idx:03d}: click {first} then {second}. ESC cancels.")
        return {"RUNNING_MODAL"}

    def _target_obj_for_domain(self, context, domain):
        p = context.scene.smile_props
        name = p.face_target if domain == DOMAIN_FACE else (p.max_target if domain == DOMAIN_MAX else p.man_target)
        return bpy.data.objects.get(name) if name else None

    def _place_one(self, context, event, domain, idx):
        p = context.scene.smile_props
        target = self._target_obj_for_domain(context, domain)
        if not target or target.type != "MESH":
            return None, "NO_TARGET", None

        hit = raycast_from_mouse_to_target(context, event, target)
        if not hit:
            return None, "NO_HIT", target

        loc, _norm, face_i = hit
        if p.snap_to_vertex:
            loc = snap_to_nearest_vertex_world(target, loc)

        name = lm_name(domain, idx)
        if p.lm_prevent_overwrite and bpy.data.objects.get(name) is not None:
            return None, "EXISTS", target

        rgba = lm_color_for_index(idx)
        shape = DOMAIN_SHAPE.get(domain, "SPHERE")

        obj = make_marker(name, loc, p.marker_size, target, rgba, shape=shape, sticky=p.lm_sticky_lock)
        obj["SMILE_LM_DOMAIN"] = domain
        obj["SMILE_LM_INDEX"] = int(idx)
        obj["SMILE_LM_HIT_OBJECT"] = target.name
        obj["SMILE_LM_HIT_FACEI"] = int(face_i) if face_i is not None else -1
        obj["SMILE_LM_HIT_WORLD"] = [loc.x, loc.y, loc.z]
        return obj, "OK", target

    def modal(self, context, event):
        p = context.scene.smile_props
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            domain = self._await_domain
            _obj, status, _target = self._place_one(context, event, domain, self._idx)

            if status == "NO_TARGET":
                self.report({"ERROR"}, f"Missing target mesh for {domain}. Set it first.")
                return {"CANCELLED"}
            if status == "NO_HIT":
                self.report({"WARNING"}, f"No hit. Click directly on the {domain} mesh surface.")
                return {"RUNNING_MODAL"}
            if status == "EXISTS":
                self.report({"WARNING"}, f"{lm_name(domain, self._idx)} exists. Disable Prevent overwrite to replace.")
                return {"RUNNING_MODAL"}

            other = self._domain_b if domain == self._domain_a else self._domain_a
            self._await_domain = other

            start_domain = self._domain_b if p.pair_start_with_b else self._domain_a
            if self._await_domain == start_domain:
                if not (p.lm_lock_index and p.lm_lock_stay):
                    if p.lm_lock_index:
                        p.lm_index_override += 1
                        self._idx = int(p.lm_index_override)
                    else:
                        self._idx = choose_next_pair_index(p, self._domain_a, self._domain_b)
                self.report({"INFO"}, f"Next index: #{self._idx:03d}.")
            return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

class SMILE_OT_drag_landmark(bpy.types.Operator):
    bl_idname = "smile.drag_landmark"
    bl_label = "Drag Landmark (Hold LMB)"
    bl_options = {"REGISTER", "UNDO"}

    _lm = None
    _tgt = None

    def invoke(self, context, event):
        lm = context.view_layer.objects.active
        if not lm or lm.type != "MESH":
            self.report({"ERROR"}, "Select a landmark marker first.")
            return {"CANCELLED"}
        if lm.get("SMILE_LM_DOMAIN") not in DOMAINS or lm.get("SMILE_LM_INDEX") is None:
            self.report({"ERROR"}, "Active object is not a Smile landmark marker.")
            return {"CANCELLED"}

        tgt_name = lm.get("SMILE_ATTACH_TARGET")
        tgt = bpy.data.objects.get(tgt_name) if tgt_name else None
        if not tgt or tgt.type != "MESH":
            if lm.parent and lm.parent.type == "MESH":
                tgt = lm.parent
            else:
                self.report({"ERROR"}, "Landmark has no valid target mesh reference.")
                return {"CANCELLED"}

        self._lm = lm
        self._tgt = tgt

        for c in list(lm.constraints):
            if c.type == "SHRINKWRAP" and c.name.startswith("SMILE_"):
                lm.constraints.remove(c)

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Drag: move mouse over target surface. Release LMB to set. ESC cancels.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        p = context.scene.smile_props
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return {"CANCELLED"}

        if event.type == "MOUSEMOVE":
            hit = raycast_from_mouse_to_target(context, event, self._tgt)
            if hit:
                loc, _norm, face_i = hit
                if p.snap_to_vertex:
                    loc = snap_to_nearest_vertex_world(self._tgt, loc)

                self._lm.matrix_world.translation = loc
                if self._lm.parent != self._tgt:
                    mw = self._lm.matrix_world.copy()
                    self._lm.parent = self._tgt
                    self._lm.matrix_parent_inverse = self._tgt.matrix_world.inverted()
                    self._lm.matrix_world = mw

                self._lm["SMILE_ATTACH_TARGET"] = self._tgt.name
                self._lm["SMILE_LM_HIT_FACEI"] = int(face_i) if face_i is not None else -1
                self._lm["SMILE_LM_HIT_WORLD"] = [loc.x, loc.y, loc.z]
                bpy.context.view_layer.update()

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if p.lm_sticky_lock:
                sw = self._lm.constraints.new("SHRINKWRAP")
                sw.name = "SMILE_SurfaceLock"
                sw.target = self._tgt
                _set_shrinkwrap_method_safe(sw)
                try:
                    sw.distance = 0.0
                except:
                    pass
            self.report({"INFO"}, "Landmark moved.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

class SMILE_OT_undo_last_landmark(bpy.types.Operator):
    bl_idname = "smile.undo_last_landmark"
    bl_label = "Undo Last Landmark"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = last_landmark_object()
        if not obj:
            self.report({"INFO"}, "No landmarks to undo.")
            return {"CANCELLED"}
        delete_object(obj)
        self.report({"INFO"}, "Deleted last landmark.")
        return {"FINISHED"}

class SMILE_OT_clear_landmarks(bpy.types.Operator):
    bl_idname = "smile.clear_landmarks"
    bl_label = "Clear All Landmarks"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for o in list(bpy.data.objects):
            if o.get("SMILE_LM_DOMAIN") in DOMAINS and o.get("SMILE_LM_INDEX") is not None:
                delete_object(o)
                removed += 1
        self.report({"INFO"}, f"Removed {removed} landmarks.")
        return {"FINISHED"}

class SMILE_OT_align_by_landmarks(bpy.types.Operator):
    bl_idname = "smile.align_by_landmarks"
    bl_label = "Align Source → Target (Landmarks + ICP)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.smile_props

        src_domain = p.align_source_domain
        tgt_domain = p.align_target_domain
        if src_domain == tgt_domain:
            self.report({"ERROR"}, "Pick different source/target domains.")
            return {"CANCELLED"}

        def _domain_obj(domain):
            name = p.face_target if domain == DOMAIN_FACE else (p.max_target if domain == DOMAIN_MAX else p.man_target)
            return bpy.data.objects.get(name) if name else None

        src_obj = _domain_obj(src_domain)
        tgt_obj = _domain_obj(tgt_domain)
        if not src_obj or src_obj.type != "MESH":
            self.report({"ERROR"}, f"Missing source mesh: {src_domain}")
            return {"CANCELLED"}
        if not tgt_obj or tgt_obj.type != "MESH":
            self.report({"ERROR"}, f"Missing target mesh: {tgt_domain}")
            return {"CANCELLED"}

        matched, A, B = matched_landmark_points(src_domain, tgt_domain)
        if len(A) < 3:
            self.report({"ERROR"}, f"Need ≥3 matched landmark indices between {src_domain} and {tgt_domain}. Matched: {matched}")
            return {"CANCELLED"}

        okA, condA = landmark_condition_number(A)
        okB, condB = landmark_condition_number(B)
        if not (okA and okB):
            self.report({"WARNING"}, f"Landmarks ill-conditioned (condA={condA:.2e}, condB={condB:.2e}). Add a non-collinear 3rd+ point set.")

        # ---- Plane constraint pre-rotation (helps planar landmark sets)
        src_norm = best_fit_plane_normal(A)
        tgt_norm = best_fit_plane_normal(B)

        R_plane_4 = Matrix.Identity(4)
        if src_norm and tgt_norm:
            axis = src_norm.cross(tgt_norm)
            if axis.length > 1e-9:
                R_plane_4 = Matrix.Rotation(src_norm.angle(tgt_norm), 4, axis.normalized())

        A_plane = [R_plane_4 @ v for v in A]

        # ---- Kabsch rigid solve in plane-aligned space
        R_k, t_k = kabsch_rigid(A_plane, B)     # R_k is 3x3
        R_init = R_k @ R_plane_4.to_3x3()       # 3x3 total rotation
        t_init = t_k                             # translation mapping centroids

        # We'll compute init_total in world coordinates
        init_total = Matrix.Translation(t_init) @ R_init.to_4x4()

        # Apply landmark transform to src object
        apply_rigid_to_object(src_obj, R_init, t_init)
        bpy.context.view_layer.update()

        # ---- ICP refine (optional)
        if p.icp_enable:
            have_o3d = ensure_open3d_start_install_if_missing()
            if not have_o3d:
                self.report({"INFO"}, "Open3D installing… run Align again after install completes (see System Console).")
                # still update landmark-based stats
                n, rms, mx = alignment_error_stats(src_domain, tgt_domain)
                p.last_align_count = n
                p.last_align_rms = rms
                p.last_align_max = mx
                return {"FINISHED"}

            try:
                # IMPORTANT FIX: Open3D returns a TOTAL transform relative to original source.
                # Since we already applied init_total to the Blender object,
                # we apply only the DELTA: Delta = T_icp_total * inv(init_total)
                T_icp_total = run_open3d_icp_refine(
                    source_obj=src_obj,
                    target_obj=tgt_obj,
                    init_total=init_total,
                    samples=int(p.icp_samples),
                    threshold=float(p.icp_threshold),
                    normal_radius=float(p.icp_normal_radius),
                )
                Delta = T_icp_total @ init_total.inverted()
                src_obj.matrix_world = Delta @ src_obj.matrix_world
                bpy.context.view_layer.update()
            except Exception as e:
                self.report({"WARNING"}, f"ICP failed: {e} (see System Console)")
                print("[SmileDesign][ICP] Exception:", e)
                print(traceback.format_exc())

        n, rms, mx = alignment_error_stats(src_domain, tgt_domain)
        p.last_align_count = n
        p.last_align_rms = rms
        p.last_align_max = mx

        self.report({"INFO"}, f"Aligned {src_domain}→{tgt_domain} | matched={n} | RMS={rms:.4f} | Max={mx:.4f}")
        return {"FINISHED"}

# ============================================================
# Arch trace, teeth import/layout, margin trace, veneer, rig, etc.
# (same as your original script — left intact)
# ============================================================

class SMILE_OT_arch_trace(bpy.types.Operator):
    bl_idname = "smile.arch_trace"
    bl_label = "Trace Arch Points (Click) — MAX or MAN"
    bl_options = {"REGISTER", "UNDO"}

    domain: bpy.props.EnumProperty(
        items=[(DOMAIN_MAX, "MAX", ""), (DOMAIN_MAN, "MAN", "")],
        default=DOMAIN_MAX
    )

    _pts = None
    _target = None

    def invoke(self, context, event):
        p = context.scene.smile_props
        target_name = p.max_target if self.domain == DOMAIN_MAX else p.man_target
        target = bpy.data.objects.get(target_name) if target_name else None
        if not target or target.type != "MESH":
            self.report({"ERROR"}, f"Set target for {self.domain} first.")
            return {"CANCELLED"}

        self._target = target
        self._pts = get_arch_points(context.scene, self.domain)

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, f"Arch trace {self.domain}: LMB add point. Press 'T' = Tracing Complete. ESC cancels.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        p = context.scene.smile_props
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._target)
            if not hit:
                self.report({"WARNING"}, f"No hit. Click directly on the {self.domain} mesh.")
                return {"RUNNING_MODAL"}
            loc, _norm, _fi = hit
            if p.snap_to_vertex:
                loc = snap_to_nearest_vertex_world(self._target, loc)

            self._pts.append(loc)
            set_arch_points(context.scene, self.domain, self._pts)

            idx = len(self._pts)
            rgba = (1, 1, 1, 1)
            name = f"ARCH_{self.domain}_P_{idx:03d}"
            m = make_marker(name, loc, p.arch_marker_size, self._target, rgba, shape="ICO", sticky=False)
            m["SMILE_ARCH_DOMAIN"] = self.domain
            m["SMILE_ARCH_INDEX"] = idx
            return {"RUNNING_MODAL"}

        if event.type == "T" and event.value == "PRESS":
            curve = build_arch_curve(
                self.domain,
                self._pts,
                curve_type=p.arch_curve_type,
                resolution=p.arch_resolution,
                smooth_strength=p.arch_smooth_strength
            )
            if curve:
                self.report({"INFO"}, f"Tracing complete: updated {curve.name}")
            else:
                self.report({"WARNING"}, "Need at least 2 points.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

class SMILE_OT_clear_arch(bpy.types.Operator):
    bl_idname = "smile.clear_arch"
    bl_label = "Clear Arch Points + Markers"
    bl_options = {"REGISTER", "UNDO"}

    domain: bpy.props.EnumProperty(
        items=[(DOMAIN_MAX, "MAX", ""), (DOMAIN_MAN, "MAN", "")],
        default=DOMAIN_MAX
    )

    def execute(self, context):
        set_arch_points(context.scene, self.domain, [])
        clear_arch_markers(self.domain)
        obj = bpy.data.objects.get(arch_curve_name(self.domain))
        if obj:
            delete_object(obj)
        self.report({"INFO"}, f"Cleared {self.domain} arch.")
        return {"FINISHED"}

class SMILE_OT_import_teeth_folder(bpy.types.Operator):
    bl_idname = "smile.import_teeth_folder"
    bl_label = "Import Tooth Library Folder (#xx in name)"
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory or not os.path.isdir(self.directory):
            self.report({"ERROR"}, "Pick a valid folder.")
            return {"CANCELLED"}

        ensure_collection(COL_TEETH)
        imported = []
        for fn in os.listdir(self.directory):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue
            fp = os.path.join(self.directory, fn)
            try:
                meshes = import_mesh_file(fp)
                for o in meshes:
                    imported.append(o)
            except Exception as e:
                self.report({"WARNING"}, f"Skipped {fn}: {e}")

        for o in imported:
            link_to_collection(o, ensure_collection(COL_TEETH))
            ensure_tooth_params(o)

        self.report({"INFO"}, f"Imported {len(imported)} tooth mesh object(s).")
        return {"FINISHED"}

class SMILE_OT_layout_teeth_width_aware(bpy.types.Operator):
    bl_idname = "smile.layout_teeth_width_aware"
    bl_label = "Layout Teeth (Width-aware) on MAX Arch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_props
        curve = bpy.data.objects.get(arch_curve_name(DOMAIN_MAX))
        if not curve or curve.type != "CURVE":
            self.report({"ERROR"}, "No ARCH_MAX_CURVE. Trace MAX arch and press T.")
            return {"CANCELLED"}

        teeth = sort_teeth_by_fdi(tooth_objects_in_collection())
        if not teeth:
            self.report({"ERROR"}, "No teeth with #xx found in names in Teeth collection.")
            return {"CANCELLED"}

        try:
            distribute_teeth_width_aware(curve, teeth, gap_mm=p.tooth_gap_mm, bridge_mode=p.bridge_mode)
            update_ghosts()
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Laid out {len(teeth)} teeth on MAX arch (width-aware).")
        return {"FINISHED"}

class SMILE_OT_toggle_ghost_selected(bpy.types.Operator):
    bl_idname = "smile.toggle_ghost_selected"
    bl_label = "Toggle Ghost Preview (Selected Teeth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        col = ensure_collection(COL_TEETH)
        sel = [o for o in context.selected_objects if o.type == "MESH" and (o in col.objects)]
        if not sel:
            self.report({"ERROR"}, "Select tooth objects in Teeth collection.")
            return {"CANCELLED"}
        for o in sel:
            ensure_tooth_params(o)
            o["SMILE_GHOST"] = 0 if int(o.get("SMILE_GHOST", 0)) == 1 else 1
        update_ghosts()
        return {"FINISHED"}

class SMILE_OT_apply_tweak_selected(bpy.types.Operator):
    bl_idname = "smile.apply_tweak_selected"
    bl_label = "Apply Tweaks (Selected Teeth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        curve = bpy.data.objects.get(arch_curve_name(DOMAIN_MAX))
        pts = curve_world_points(curve) if curve else []
        if not pts:
            pts = [Vector((0,0,0)), Vector((1,0,0))]
        occlusal_up = Vector((0,0,1))

        col = ensure_collection(COL_TEETH)
        sel = [o for o in context.selected_objects if o.type == "MESH" and (o in col.objects)]
        if not sel:
            self.report({"ERROR"}, "Select tooth objects in Teeth collection.")
            return {"CANCELLED"}

        for o in sel:
            ensure_tooth_params(o)
            best_i = 0
            best_d = 1e18
            for i, pp in enumerate(pts):
                d = (o.matrix_world.translation - pp).length
                if d < best_d:
                    best_d = d
                    best_i = i
            tan = curve_tangent_at_index(pts, best_i)
            apply_tooth_tweaks(o, tan, occlusal_up)

        update_ghosts()
        self.report({"INFO"}, "Tweaks applied.")
        return {"FINISHED"}

class SMILE_OT_margin_trace(bpy.types.Operator):
    bl_idname = "smile.margin_trace"
    bl_label = "Trace Margin Ring (Click) for Active Tooth"
    bl_options = {"REGISTER", "UNDO"}

    _pts = None
    _target = None
    _tooth = None

    def invoke(self, context, event):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        self._tooth = tooth
        self._target = tooth
        self._pts = get_margin_points(context.scene, tooth)

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Margin trace: LMB adds point. Press 'T' = Tracing Complete. ESC cancels.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        scene = context.scene
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._target)
            if not hit:
                self.report({"WARNING"}, "No hit. Click directly on tooth surface.")
                return {"RUNNING_MODAL"}
            loc, _norm, _fi = hit
            if context.scene.smile_props.snap_to_vertex:
                loc = snap_to_nearest_vertex_world(self._target, loc)
            self._pts.append(loc)
            set_margin_points(scene, self._tooth, self._pts)

            idx = len(self._pts)
            rgba = (1, 0.2, 0.2, 1)
            name = f"MARGIN_{self._tooth.name}_P_{idx:03d}"
            m = make_marker(name, loc, context.scene.smile_props.margin_marker_size, self._target, rgba, shape="ICO", sticky=False)
            m["SMILE_MARGIN_FOR"] = self._tooth.name
            m["SMILE_MARGIN_INDEX"] = idx
            link_to_collection(m, ensure_collection(COL_MARGINS))
            return {"RUNNING_MODAL"}

        if event.type == "T" and event.value == "PRESS":
            curve = build_margin_curve(self._tooth, self._pts, resolution=context.scene.smile_props.margin_resolution)
            if curve:
                self.report({"INFO"}, f"Margin ring complete: {curve.name}")
            else:
                self.report({"WARNING"}, "Need at least 3 points.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

class SMILE_OT_clear_margin(bpy.types.Operator):
    bl_idname = "smile.clear_margin"
    bl_label = "Clear Margin Ring (Active Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}

        k = KEY_MARGIN_PREFIX + tooth.name
        if k in context.scene:
            del context.scene[k]

        prefix = f"MARGIN_{tooth.name}_P_"
        for o in list(bpy.data.objects):
            if o.name.startswith(prefix):
                delete_object(o)

        c = bpy.data.objects.get(margin_curve_name(tooth))
        if c:
            delete_object(c)

        self.report({"INFO"}, "Cleared margin.")
        return {"FINISHED"}

class SMILE_OT_make_veneer_active(bpy.types.Operator):
    bl_idname = "smile.make_veneer_active"
    bl_label = "Generate Veneer (Active Tooth)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}

        try:
            ven, wax = veneer_make_for_tooth(scene, tooth, use_waxup=True)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Generated veneer: {ven.name} (wax: {wax.name})")
        return {"FINISHED"}

class SMILE_OT_export_veneer_active(bpy.types.Operator):
    bl_idname = "smile.export_veneer_active"
    bl_label = "Export Veneer (Active Tooth)"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default="")

    def invoke(self, context, event):
        scene = context.scene
        ensure_veneer_params(scene)
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        ven = bpy.data.objects.get(tooth.name + "_VENEER")
        if not ven:
            self.report({"ERROR"}, "No veneer found. Generate veneer first.")
            return {"CANCELLED"}
        fmt = scene["SMILE_VEN_EXPORT_FMT"]
        self.filepath = bpy.path.abspath(f"//{ven.name}.{fmt.lower()}")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene
        tooth = context.view_layer.objects.active
        ven = bpy.data.objects.get(tooth.name + "_VENEER") if tooth else None
        if not ven:
            self.report({"ERROR"}, "No veneer found.")
            return {"CANCELLED"}
        fmt = scene.get("SMILE_VEN_EXPORT_FMT", "STL")
        try:
            export_object_mesh(ven, self.filepath, fmt=fmt)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported {ven.name} to {self.filepath}")
        return {"FINISHED"}

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
            lat, handles = create_lattice_rig_for_tooth(tooth, size_pad=context.scene.smile_props.rig_size_pad)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Rig created: {lat.name} with {len(handles)} handles")
        return {"FINISHED"}

class SMILE_OT_add_multires_for_sculpt(bpy.types.Operator):
    bl_idname = "smile.add_multires_sculpt"
    bl_label = "Add Multires (Sculpt Hybrid) to Active Tooth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tooth = context.view_layer.objects.active
        if not tooth or tooth.type != "MESH":
            self.report({"ERROR"}, "Set active tooth mesh first.")
            return {"CANCELLED"}
        mod = tooth.modifiers.get("SMILE_MULTIRES") or tooth.modifiers.new("SMILE_MULTIRES", "MULTIRES")
        p = context.scene.smile_props
        try:
            mod.levels = p.multires_view
            mod.sculpt_levels = p.multires_sculpt
            mod.render_levels = p.multires_render
        except:
            pass
        self.report({"INFO"}, "Multires added. Switch to Sculpt mode and sculpt on top of global tweaks.")
        return {"FINISHED"}

# ============================================================
# PROPERTIES + UI
# ============================================================

class SmileProps(bpy.types.PropertyGroup):
    # Targets
    face_target: bpy.props.StringProperty(name="FACE target", default="")
    max_target:  bpy.props.StringProperty(name="MAX target", default="")
    man_target:  bpy.props.StringProperty(name="MAN target", default="")

    # Landmark display & behavior
    marker_size: bpy.props.FloatProperty(name="Landmark Size", default=1.5, min=0.1, max=50.0)
    snap_to_vertex: bpy.props.BoolProperty(name="Snap to nearest vertex", default=False)
    lm_sticky_lock: bpy.props.BoolProperty(name="Sticky Lock to surface", default=True)
    lm_prevent_overwrite: bpy.props.BoolProperty(name="Prevent overwrite", default=True)

    pair_domain_a: bpy.props.EnumProperty(name="Pair A", items=[(DOMAIN_FACE,"FACE",""),(DOMAIN_MAX,"MAX",""),(DOMAIN_MAN,"MAN","")], default=DOMAIN_FACE)
    pair_domain_b: bpy.props.EnumProperty(name="Pair B", items=[(DOMAIN_FACE,"FACE",""),(DOMAIN_MAX,"MAX",""),(DOMAIN_MAN,"MAN","")], default=DOMAIN_MAX)
    pair_start_with_b: bpy.props.BoolProperty(name="Start with B", default=False)

    lm_index_mode: bpy.props.EnumProperty(
        name="Indexing",
        items=[("CONTINUE","Continue",""),("FILL_MISSING","Fill Missing","")],
        default="FILL_MISSING"
    )
    lm_lock_index: bpy.props.BoolProperty(name="Lock Index", default=False)
    lm_index_override: bpy.props.IntProperty(name="Index Override", default=1, min=1, max=999)
    lm_lock_stay: bpy.props.BoolProperty(name="Stay on locked index", default=True)

    # Alignment
    align_source_domain: bpy.props.EnumProperty(name="Source", items=[(DOMAIN_FACE,"FACE",""),(DOMAIN_MAX,"MAX",""),(DOMAIN_MAN,"MAN","")], default=DOMAIN_FACE)
    align_target_domain: bpy.props.EnumProperty(name="Target", items=[(DOMAIN_FACE,"FACE",""),(DOMAIN_MAX,"MAX",""),(DOMAIN_MAN,"MAN","")], default=DOMAIN_MAX)
    last_align_count: bpy.props.IntProperty(name="Matched", default=0)
    last_align_rms: bpy.props.FloatProperty(name="RMS", default=0.0, precision=6)
    last_align_max: bpy.props.FloatProperty(name="Max", default=0.0, precision=6)

    # ICP controls
    icp_enable: bpy.props.BoolProperty(name="Use ICP refine (Open3D)", default=True)
    icp_samples: bpy.props.IntProperty(name="ICP Samples", default=20000, min=1000, max=200000)
    icp_threshold: bpy.props.FloatProperty(name="ICP Threshold (scene units)", default=1.0, min=1e-6, max=1000.0)
    icp_normal_radius: bpy.props.FloatProperty(name="ICP Normal Radius (scene units)", default=2.0, min=0.0, max=1000.0)

    # Arch options
    arch_marker_size: bpy.props.FloatProperty(name="Arch Marker Size", default=1.0, min=0.1, max=50.0)
    arch_curve_type: bpy.props.EnumProperty(name="Curve Type", items=[("BEZIER","Bezier",""),("POLY","Poly","")], default="BEZIER")
    arch_resolution: bpy.props.IntProperty(name="Resolution", default=24, min=2, max=128)
    arch_smooth_strength: bpy.props.FloatProperty(name="Smooth Strength", default=0.35, min=0.0, max=1.0)

    # Teeth layout
    tooth_gap_mm: bpy.props.FloatProperty(name="Gap (mm)", default=0.25, min=0.0, max=2.0)
    bridge_mode: bpy.props.BoolProperty(name="Bridge Mode", default=False)

    # Per-tooth tweak sliders apply to ACTIVE tooth (then "Apply to Selected")
    tweak_width: bpy.props.FloatProperty(name="Width Scale", default=1.0, min=0.5, max=1.5)
    tweak_length: bpy.props.FloatProperty(name="Length Scale", default=1.0, min=0.5, max=1.7)
    tweak_cant: bpy.props.FloatProperty(name="Cant (deg)", default=0.0, min=-20.0, max=20.0)
    tweak_midline: bpy.props.FloatProperty(name="Midline (mm)", default=0.0, min=-5.0, max=5.0)

    # Margin tracing
    margin_marker_size: bpy.props.FloatProperty(name="Margin Marker Size", default=0.8, min=0.1, max=10.0)
    margin_resolution: bpy.props.IntProperty(name="Margin Resolution", default=24, min=2, max=128)

    # Rig options
    rig_size_pad: bpy.props.FloatProperty(name="Rig Size Pad", default=1.15, min=1.0, max=1.6)

    # Multires
    multires_view: bpy.props.IntProperty(name="View", default=1, min=0, max=6)
    multires_sculpt: bpy.props.IntProperty(name="Sculpt", default=2, min=0, max=6)
    multires_render: bpy.props.IntProperty(name="Render", default=2, min=0, max=6)

class SMILE_PT_panel(bpy.types.Panel):
    bl_label = "Smile Design Pro (Merged)"
    bl_idname = "SMILE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smile"

    def draw(self, context):
        scene = context.scene
        p = scene.smile_props
        ensure_veneer_params(scene)

        ensure_collection(COL_SCANS); ensure_collection(COL_TEETH); ensure_collection(COL_LM)
        ensure_collection(COL_ARCH); ensure_collection(COL_PREVIEW); ensure_collection(COL_WAXUP)
        ensure_collection(COL_VENEER); ensure_collection(COL_RIG); ensure_collection(COL_MARGINS)

        layout = self.layout

        box = layout.box()
        box.label(text="Import")
        row = box.row(align=True)
        row.operator("smile.import_scan", text="Import Scan")
        row.operator("smile.import_teeth_folder", text="Import Teeth Folder")

        box = layout.box()
        box.label(text="Targets (select mesh then set)")
        col = box.column(align=True)
        r = col.row(align=True)
        r.prop(p, "face_target", text="FACE")
        op = r.operator("smile.set_domain_target", text="Set"); op.domain = DOMAIN_FACE
        r = col.row(align=True)
        r.prop(p, "max_target", text="MAX")
        op = r.operator("smile.set_domain_target", text="Set"); op.domain = DOMAIN_MAX
        r = col.row(align=True)
        r.prop(p, "man_target", text="MAN")
        op = r.operator("smile.set_domain_target", text="Set"); op.domain = DOMAIN_MAN

        box = layout.box()
        box.label(text="Landmarks (paired, neon, draggable)")
        box.prop(p, "marker_size")
        box.prop(p, "snap_to_vertex")
        box.prop(p, "lm_sticky_lock")
        box.prop(p, "lm_prevent_overwrite")

        sub = box.box()
        sub.label(text="Paired Placement")
        rr = sub.row(align=True)
        rr.prop(p, "pair_domain_a")
        rr.prop(p, "pair_domain_b")
        sub.prop(p, "pair_start_with_b")

        sub2 = box.box()
        sub2.label(text="Indexing")
        sub2.prop(p, "lm_index_mode")
        sub2.prop(p, "lm_lock_index")
        if p.lm_lock_index:
            rr = sub2.row(align=True)
            rr.prop(p, "lm_index_override")
            rr.prop(p, "lm_lock_stay")

        row = box.row(align=True)
        row.operator("smile.place_paired_landmarks", text="Start Paired Click")
        row.operator("smile.drag_landmark", text="Drag Landmark")
        row = box.row(align=True)
        row.operator("smile.undo_last_landmark", text="Undo Last")
        row.operator("smile.clear_landmarks", text="Clear All")

        box = layout.box()
        box.label(text="Alignment (Landmarks + Open3D ICP)")
        box.label(text=open3d_status_string())
        rr = box.row(align=True)
        rr.prop(p, "align_source_domain")
        rr.prop(p, "align_target_domain")
        box.prop(p, "icp_enable")
        if p.icp_enable:
            box.prop(p, "icp_samples")
            box.prop(p, "icp_threshold")
            box.prop(p, "icp_normal_radius")
        box.operator("smile.align_by_landmarks", text="Align Source → Target")

        stat = box.box()
        stat.label(text=f"Matched: {p.last_align_count}")
        stat.label(text=f"RMS: {p.last_align_rms:.6f}")
        stat.label(text=f"Max: {p.last_align_max:.6f}")

        box = layout.box()
        box.label(text="Arch Trace + Smoothing")
        box.prop(p, "arch_marker_size")
        rr = box.row(align=True)
        rr.prop(p, "arch_curve_type", text="")
        rr.prop(p, "arch_resolution")
        box.prop(p, "arch_smooth_strength")
        rr = box.row(align=True)
        op = rr.operator("smile.arch_trace", text="Trace MAX"); op.domain = DOMAIN_MAX
        op = rr.operator("smile.arch_trace", text="Trace MAN"); op.domain = DOMAIN_MAN
        box.label(text="During trace: LMB add points, press T = Tracing Complete")
        rr = box.row(align=True)
        op = rr.operator("smile.clear_arch", text="Clear MAX"); op.domain = DOMAIN_MAX
        op = rr.operator("smile.clear_arch", text="Clear MAN"); op.domain = DOMAIN_MAN

        box = layout.box()
        box.label(text="Teeth Layout + Tweaks + Ghost")
        box.prop(p, "tooth_gap_mm")
        box.prop(p, "bridge_mode")
        box.operator("smile.layout_teeth_width_aware", text="Layout Teeth on MAX Arch (Width-aware)")

        tbox = box.box()
        tbox.label(text="Active Tooth Tweaks (store on tooth, apply to selected)")
        tbox.prop(p, "tweak_width")
        tbox.prop(p, "tweak_length")
        tbox.prop(p, "tweak_cant")
        tbox.prop(p, "tweak_midline")
        row = tbox.row(align=True)
        row.operator("smile.apply_tweak_selected", text="Apply Tweaks to Selected")
        row.operator("smile.toggle_ghost_selected", text="Toggle Ghost (Selected)")

        vbox = layout.box()
        vbox.label(text="Veneer Pipeline (Active Tooth)")
        vbox.prop(p, "margin_marker_size")
        vbox.prop(p, "margin_resolution")
        row = vbox.row(align=True)
        row.operator("smile.margin_trace", text="Trace Margin Ring")
        row.operator("smile.clear_margin", text="Clear Margin")

        vv = vbox.box()
        vv.label(text="Veneer Params (Scene-wide)")
        vv.prop(scene, '["SMILE_VEN_MARGIN_OFFSET"]', text="Margin Offset (mm)")
        vv.prop(scene, '["SMILE_VEN_MARGIN_BAND"]', text="Band (mm)")
        vv.prop(scene, '["SMILE_VEN_THICK_MIN"]', text="Thickness Min (mm)")
        vv.prop(scene, '["SMILE_VEN_THICK_MAX"]', text="Thickness Max (mm)")
        vv.prop(scene, '["SMILE_VEN_CONTACT_THICK"]', text="Contact Thick (mm)")
        vv.prop(scene, '["SMILE_VEN_BOOLEAN_MODE"]', text="Boolean")
        vv.prop(scene, '["SMILE_VEN_EXPORT_FMT"]', text="Export")

        row = vbox.row(align=True)
        row.operator("smile.make_veneer_active", text="Generate Veneer")
        row.operator("smile.export_veneer_active", text="Export Veneer")

        rbox = layout.box()
        rbox.label(text="Shaping Rig (27 handles) + Sculpt Hybrid")
        rbox.prop(p, "rig_size_pad")
        rbox.operator("smile.create_lattice_rig", text="Create 27-Handle Rig (Active Tooth)")
        rbox.separator()
        rbox.label(text="Multires (Sculpt on top of global tweaks)")
        rr = rbox.row(align=True)
        rr.prop(p, "multires_view")
        rr.prop(p, "multires_sculpt")
        rr.prop(p, "multires_render")
        rbox.operator("smile.add_multires_sculpt", text="Add Multires to Active Tooth")

def _register_scene_enum_keys():
    scene = bpy.context.scene
    ensure_veneer_params(scene)
    if scene["SMILE_VEN_BOOLEAN_MODE"] not in {"NONE", "DIFFERENCE"}:
        scene["SMILE_VEN_BOOLEAN_MODE"] = "NONE"
    if scene["SMILE_VEN_EXPORT_FMT"] not in {"STL", "OBJ"}:
        scene["SMILE_VEN_EXPORT_FMT"] = "STL"

classes = (
    SmileProps,
    SMILE_OT_import_scan,
    SMILE_OT_set_domain_target,
    SMILE_OT_place_paired_landmarks,
    SMILE_OT_drag_landmark,
    SMILE_OT_undo_last_landmark,
    SMILE_OT_clear_landmarks,
    SMILE_OT_align_by_landmarks,
    SMILE_OT_arch_trace,
    SMILE_OT_clear_arch,
    SMILE_OT_import_teeth_folder,
    SMILE_OT_layout_teeth_width_aware,
    SMILE_OT_toggle_ghost_selected,
    SMILE_OT_apply_tweak_selected,
    SMILE_OT_margin_trace,
    SMILE_OT_clear_margin,
    SMILE_OT_make_veneer_active,
    SMILE_OT_export_veneer_active,
    SMILE_OT_create_lattice_rig,
    SMILE_OT_add_multires_for_sculpt,
    SMILE_PT_panel,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.smile_props = bpy.props.PointerProperty(type=SmileProps)

    ensure_collection(COL_SCANS)
    ensure_collection(COL_TEETH)
    ensure_collection(COL_LM)
    ensure_collection(COL_ARCH)
    ensure_collection(COL_PREVIEW)
    ensure_collection(COL_WAXUP)
    ensure_collection(COL_VENEER)
    ensure_collection(COL_RIG)
    ensure_collection(COL_MARGINS)

    _register_scene_enum_keys()

def unregister():
    del bpy.types.Scene.smile_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
