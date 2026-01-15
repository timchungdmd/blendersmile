import bpy
import math
import traceback
import sys
import subprocess
import threading
import site
import importlib
from mathutils import Vector, Matrix
from .constants import DOMAINS, NEON

# ============================================================
# Open3D Globals & Installation Logic
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
            _o3d_log(f"ensurepip failed: {e}")

        _o3d_log("Upgrading pip…")
        try:
            subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"])
        except Exception as e:
            _o3d_log(f"pip upgrade failed: {e}")

        _o3d_log("Installing open3d…")
        subprocess.check_call([py, "-m", "pip", "install", "open3d"])

        _refresh_site_packages_paths()
        import open3d as o3d
        _O3D = o3d
        _o3d_log("Open3D installed successfully.")
    except Exception as e:
        _O3D_LAST_ERROR = str(e)
        _o3d_log(f"Open3D install failed: {_O3D_LAST_ERROR}")
        _o3d_log(traceback.format_exc())
    finally:
        _O3D_INSTALLING = False

def ensure_open3d():
    global _O3D, _O3D_INSTALLING
    if _O3D is not None: return True
    try:
        _refresh_site_packages_paths()
        import open3d as o3d
        _O3D = o3d
        return True
    except ImportError:
        if not _O3D_INSTALLING:
            threading.Thread(target=_install_open3d_worker, daemon=True).start()
        return False

# ============================================================
# Landmark Matching Helpers
# ============================================================

def lm_name(domain: str, idx: int):
    return f"{domain}_{idx:03d}"

def get_landmark_obj(domain: str, idx: int):
    return bpy.data.objects.get(lm_name(domain, idx))

def indices_in_domain(domain: str):
    inds = set()
    for o in bpy.data.objects:
        if o.get("SMILE_LM_DOMAIN") == domain and o.get("SMILE_LM_INDEX") is not None:
            inds.add(int(o["SMILE_LM_INDEX"]))
    return inds

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

# ============================================================
# Math: Kabsch & Eigen Analysis
# ============================================================

def _safe_eigenvalues_cov(points):
    if len(points) < 3: return False, [0.0]*3
    cen = sum(points, Vector()) / len(points)
    cov = Matrix(((0.0,)*3,)*3)
    for p in points:
        d = p - cen
        for r in range(3):
            for c in range(3):
                cov[r][c] += d[r]*d[c]
    try:
        _, eig_vals = cov.eigen()
        return True, sorted([float(v) for v in eig_vals])
    except:
        return False, [0.0]*3

def best_fit_plane_normal(points):
    cen = sum(points, Vector()) / len(points)
    cov = Matrix(((0.0,)*3,)*3)
    for p in points:
        d = p - cen
        for r in range(3):
            for c in range(3):
                cov[r][c] += d[r]*d[c]
    try:
        vecs, vals = cov.eigen()
        # Eigenvalues are not sorted in Blender API guaranteed, find min
        min_v = min(vals)
        min_i = list(vals).index(min_v)
        return vecs[min_i].normalized()
    except:
        return None

def kabsch_rigid(A, B):
    """
    Standard Kabsch algorithm for rigid alignment.
    A, B: Lists of Vectors
    Returns: Rotation Matrix (3x3), Translation Vector
    """
    n = len(A)
    if n < 3: raise RuntimeError("Need >= 3 points")
    
    ca = sum(A, Vector()) / n
    cb = sum(B, Vector()) / n
    
    # Covariance
    H = Matrix(((0.0,)*3,)*3)
    for i in range(n):
        a = A[i] - ca
        b = B[i] - cb
        for r in range(3):
            for c in range(3):
                H[r][c] += a[r] * b[c]

    # SVD (using Blender's Matrix/Eigen limitations or manual approx)
    # Since Blender doesn't expose full SVD for Matrix easily, 
    # we use the quaternion convergence method from your original script
    # to ensure identical behavior.
    
    # Construct 4x4 Symmetric Matrix N for quaternion extraction
    Sxx, Sxy, Sxz = H[0][0], H[0][1], H[0][2]
    Syx, Syy, Syz = H[1][0], H[1][1], H[1][2]
    Szx, Szy, Szz = H[2][0], H[2][1], H[2][2]
    
    trace = Sxx + Syy + Szz
    N = [
        [trace, Syz-Szy, Szx-Sxz, Sxy-Syx],
        [Syz-Szy, Sxx-Syy-Szz, Sxy+Syx, Szx+Sxz],
        [Szx-Sxz, Sxy+Syx, -Sxx+Syy-Szz, Syz+Szy],
        [Sxy-Syx, Szx+Sxz, Syz+Szy, -Sxx-Syy+Szz]
    ]
    
    # Power iteration to find dominant eigenvector (quaternion)
    q = [1.0, 0.0, 0.0, 0.0]
    for _ in range(30):
        nq = [0.0]*4
        for r in range(4):
            for c in range(4):
                nq[r] += N[r][c] * q[c]
        norm = math.sqrt(sum(x*x for x in nq)) + 1e-12
        q = [x/norm for x in nq]
        
    w, x, y, z = q
    R = Matrix((
        (1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
        (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
        (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y))
    ))
    
    t = cb - (R @ ca)
    return R, t

def apply_rigid_to_object(obj, R: Matrix, t: Vector):
    M = Matrix.Translation(t) @ R.to_4x4()
    obj.matrix_world = M @ obj.matrix_world

def alignment_error_stats(domain_a, domain_b):
    _, A, B = matched_landmark_points(domain_a, domain_b)
    if not A: return 0, 0.0, 0.0
    d2 = []
    d_max = 0.0
    for i in range(len(A)):
        dist = (A[i] - B[i]).length
        d2.append(dist*dist)
        if dist > d_max: d_max = dist
    rms = math.sqrt(sum(d2)/len(d2))
    return len(A), rms, d_max

# ============================================================
# Open3D ICP Wrapper
# ============================================================

def _o3d_mesh_from_blender(obj, o3d):
    import numpy as np
    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()
    me.calc_loop_triangles()
    
    verts = np.array([v.co[:] for v in me.vertices], dtype=np.float64)
    tris = np.array([lt.vertices[:] for lt in me.loop_triangles], dtype=np.int32)
    
    mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(verts),
        o3d.utility.Vector3iVector(tris)
    )
    eo.to_mesh_clear()
    return mesh

def run_open3d_icp_refine(src_obj, tgt_obj, init_matrix: Matrix, samples=20000, thresh=1.0, radius=2.0):
    if _O3D is None: raise RuntimeError("Open3D not loaded")
    o3d = _O3D
    
    mesh_s = _o3d_mesh_from_blender(src_obj, o3d)
    mesh_t = _o3d_mesh_from_blender(tgt_obj, o3d)
    
    pcd_s = mesh_s.sample_points_uniformly(number_of_points=samples)
    pcd_t = mesh_t.sample_points_uniformly(number_of_points=samples)
    
    # Estimate normals
    r = radius if radius > 0 else thresh * 2.0
    pcd_s.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=r, max_nn=30))
    pcd_t.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=r, max_nn=30))
    
    init_np = [[float(init_matrix[r][c]) for c in range(4)] for r in range(4)]
    
    res = o3d.pipelines.registration.registration_icp(
        pcd_s, pcd_t, thresh, init_np,
        o3d.pipelines.registration.TransformationEstimationPointToPlane()
    )
    return Matrix(res.transformation)
