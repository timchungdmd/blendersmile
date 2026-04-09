"""BlenderSmile ANALYSIS Tab Module

Operators for landmark placement, golden ruler, golden set import, lip line drawing,
and related analysis tools.
"""

import bpy
import bmesh
import math
import time
import random
import traceback
from mathutils import Vector, Matrix

# Import constants directly from modules (use sys.modules to handle numeric-named modules)
import sys

_core = sys.modules.get("blendersmile.00_core") or sys.modules.get("00_core")
_props = sys.modules.get("blendersmile.01_properties") or sys.modules.get(
    "01_properties"
)

# If modules not available, define constants here
if _core:
    COL_SCANS = _core.COL_SCANS
    COL_TEETH = _core.COL_TEETH
    COL_LM = _core.COL_LM
    COL_ARCH = _core.COL_ARCH
    COL_PREVIEW = _core.COL_PREVIEW
    COL_VENEER = _core.COL_VENEER
    COL_RIG = _core.COL_RIG
    COL_MARGINS = _core.COL_MARGINS
    DOMAIN_FACE = _core.DOMAIN_FACE
    DOMAIN_MAX = _core.DOMAIN_MAX
    DOMAIN_MAN = _core.DOMAIN_MAN
    DOMAIN_PHOTO = _core.DOMAIN_PHOTO
    DOMAINS = _core.DOMAINS
    DOMAIN_SHAPE = _core.DOMAIN_SHAPE
    ARCH_CURVE_OCCLUSAL = _core.ARCH_CURVE_OCCLUSAL
    ARCH_CURVE_CERVICAL = _core.ARCH_CURVE_CERVICAL
    NEON = _core.NEON
    ensure_collection = _core.ensure_collection
    ensure_active = _core.ensure_active
    delete_object = _core.delete_object
    parse_tooth_id_from_name = _core.parse_tooth_id_from_name
    lm_color_for_index = _core.lm_color_for_index
    make_marker = _core.make_marker
    _view3d_utils = _core._view3d_utils
    raycast_from_mouse_to_target = _core.raycast_from_mouse_to_target
    snap_to_nearest_vertex_world = _core.snap_to_nearest_vertex_world
else:
    # Fallback constant definitions for standalone use
    COL_SCANS = "Scans"
    COL_TEETH = "Teeth"
    COL_LM = "SmileLandmarks"
    COL_ARCH = "SmileArch"
    COL_PREVIEW = "SmilePreview"
    COL_VENEER = "Veneers"
    COL_RIG = "Teeth_Rig"
    COL_MARGINS = "Margins"
    DOMAIN_FACE = "FACE"
    DOMAIN_MAX = "MAX"
    DOMAIN_MAN = "MAN"
    DOMAIN_PHOTO = "PHOTO"
    DOMAINS = [DOMAIN_FACE, DOMAIN_MAX, DOMAIN_MAN, DOMAIN_PHOTO]
    DOMAIN_SHAPE = {"FACE": "SPHERE", "MAX": "CUBE", "MAN": "CONE", "PHOTO": "CIRCLE"}
    ARCH_CURVE_OCCLUSAL = "OCCLUSAL"
    ARCH_CURVE_CERVICAL = "CERVICAL"
    NEON = [(1.0, 0.05, 0.55, 1.0), (0.1, 1.0, 0.1, 1.0), (0.1, 0.65, 1.0, 1.0)]

    def ensure_collection(name):
        col = bpy.data.collections.get(name)
        if not col:
            col = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(col)
        return col

    def ensure_active(obj):
        bpy.context.view_layer.objects.active = obj

    def delete_object(obj):
        bpy.data.objects.remove(obj, do_unlink=True)

    def parse_tooth_id_from_name(name):
        import re

        match = re.search(r"#\s*(\d{2})", name)
        return int(match.group(1)) if match else None

    def lm_color_for_index(idx):
        return NEON[idx % len(NEON)]

    def make_marker(
        name, world_location, size, target_obj, rgba, shape="SPHERE", sticky=False
    ):
        return None  # Placeholder

    def _view3d_utils():
        return None

    def raycast_from_mouse_to_target(context, event, target_obj, max_dist=1.0e9):
        return None

    def snap_to_nearest_vertex_world(obj, world_point):
        return world_point


def bbox_world(obj):
    """Get bounding box in world coordinates."""
    mw = obj.matrix_world
    mn = Vector((float("inf"), float("inf"), float("inf")))
    mx = Vector((float("-inf"), float("-inf"), float("-inf")))
    for v in obj.data.vertices:
        world_coord = mw @ v.co
        mn = mn.min(world_coord)
        mx = mx.max(world_coord)
    return mn, mx


def curve_world_points(curve_obj, samples=64):
    """Get world-space points from curve object."""
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
    if not getattr(eobj.data, "splines", None) or len(eobj.data.splines) == 0:
        return []
    mw = curve_obj.matrix_world
    spl = eobj.data.splines[0]
    if spl.type == "POLY":
        pts = [mw @ Vector((p.co.x, p.co.y, p.co.z)) for p in spl.points]
    else:
        pts = [mw @ bp.co for bp in spl.bezier_points]
    return pts


def evaluate_curve_at_parameter(curve_obj, t):
    """Evaluate bezier curve at parameter t (0-1)."""
    if not curve_obj or curve_obj.type != "CURVE":
        return Vector((0, 0, 0))
    deps = bpy.context.evaluated_depsgraph_get()
    eobj = curve_obj.evaluated_get(deps)
    try:
        me = eobj.to_mesh()
        mw = curve_obj.matrix_world
        verts = [mw @ v.co for v in me.vertices]
        eobj.to_mesh_clear()
        if len(verts) >= 2:
            idx = t * (len(verts) - 1)
            i = int(idx)
            f = idx - i
            if i >= len(verts) - 1:
                return verts[-1]
            return verts[i].lerp(verts[i + 1], f)
    except Exception:
        traceback.print_exc()
    if not eobj.data.splines:
        return Vector((0, 0, 0))
    spl = eobj.data.splines[0]
    if spl.type == "POLY" and spl.points:
        idx = t * (len(spl.points) - 1)
        i = int(idx)
        f = idx - i
        if i >= len(spl.points) - 1:
            p = spl.points[-1].co
        else:
            p1 = spl.points[i].co
            p2 = spl.points[i + 1].co
            p = p1.lerp(p2, f)
        return curve_obj.matrix_world @ Vector((p.x, p.y, p.z))
    if spl.bezier_points:
        pts = [curve_obj.matrix_world @ bp.co for bp in spl.bezier_points]
        idx = t * (len(pts) - 1)
        i = int(idx)
        f = idx - i
        if i >= len(pts) - 1:
            return pts[-1]
        return pts[i].lerp(pts[i + 1], f)
    return Vector((0, 0, 0))


def get_target_object_by_domain(context, domain):
    """Get target object for a domain (FACE, MAX, MAN, PHOTO)."""
    p = context.scene.smile_v2
    if domain == DOMAIN_FACE:
        name = p.face_target
    elif domain == DOMAIN_MAX:
        name = p.max_target
    elif domain == DOMAIN_MAN:
        name = p.man_target
    else:
        name = p.photo_target
    return bpy.data.objects.get(name) if name else None


def get_landmark_obj(domain, index):
    """Get landmark object by domain and index."""
    name = lm_name(domain, index)
    return bpy.data.objects.get(name)


def lm_name(domain, index):
    """Generate landmark name."""
    return f"{domain}_LM_{index:03d}"


def indices_in_domain(domain):
    """Get set of indices that have landmarks in a domain."""
    col = bpy.data.collections.get(COL_LM)
    if not col:
        return set()
    inds = set()
    prefix = f"{domain}_LM_"
    for obj in col.objects:
        if obj.name.startswith(prefix):
            try:
                idx = int(obj.name.split("_LM_")[1])
                inds.add(idx)
            except Exception:
                pass
    return inds


def last_landmark_object():
    """Get most recently created landmark."""
    col = bpy.data.collections.get(COL_LM)
    if not col:
        return None
    max_time = 0
    last_obj = None
    for obj in col.objects:
        ts = obj.get("SMILE_CREATED_AT", 0)
        if ts > max_time:
            max_time = ts
            last_obj = obj
    return last_obj


def tooth_objects_in_collection():
    """Get all tooth objects from Teeth collection."""
    col = core.ensure_collection(COL_TEETH)
    return [o for o in col.objects if o and o.type == "MESH"]


def ensure_tooth_params(obj):
    """Ensure tooth has required custom properties."""
    if "SMILE_IS_TOOTH" not in obj:
        obj["SMILE_IS_TOOTH"] = True


def clear_arch_markers(domain, curve_role=ARCH_CURVE_OCCLUSAL):
    """Clear arch markers for a domain and curve role."""
    prefix = f"SMILE_{domain}_{curve_role}_Mark_"
    to_delete = [o for o in bpy.data.objects if o.name.startswith(prefix)]
    for obj in to_delete:
        delete_object(obj)


# ============================================================
# ORIENTATION ENHANCEMENT HELPERS (Phase 3)
# ============================================================


def detect_facial_surface_by_convexity(obj):
    """Detect which side of tooth is facial (buccal) based on surface curvature."""
    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()
    try:
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            bm.verts.ensure_lookup_table()
            curvatures = []
            positions = []
            for v in bm.verts:
                if len(v.link_edges) == 0:
                    continue
                neighbor_avg = Vector()
                for e in v.link_edges:
                    other = e.other_vert(v)
                    neighbor_avg += other.co
                neighbor_avg /= len(v.link_edges)
                normal_dir = v.normal
                displacement = v.co - neighbor_avg
                curvature = displacement.dot(normal_dir)
                curvatures.append(curvature)
                positions.append(obj.matrix_world @ v.co)
        finally:
            bm.free()
        if not curvatures:
            return Vector((0, -1, 0))
        sorted_indices = sorted(
            range(len(curvatures)), key=lambda i: curvatures[i], reverse=True
        )
        top_20_percent = int(len(sorted_indices) * 0.2)
        convex_indices = sorted_indices[: max(top_20_percent, 1)]
        convex_center = Vector()
        for idx in convex_indices:
            convex_center += positions[idx]
        convex_center /= len(convex_indices)
        facial_dir = (convex_center - obj.location).normalized()
        return facial_dir
    finally:
        eo.to_mesh_clear()


def detect_incisal_edge_by_geometry(obj):
    """Detect incisal edge/cusp tip by finding lowest point."""
    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()
    try:
        verts_world = [obj.matrix_world @ v.co for v in me.vertices]
        verts_local = [v.co.copy() for v in me.vertices]
        if not verts_world:
            return obj.location, Vector((0, 0, 0)), Vector((0, 0, 1))
        z_coords = [v.z for v in verts_world]
        z_min = min(z_coords)
        z_max = max(z_coords)
        z_range = z_max - z_min
        threshold_z = z_min + (z_range * 0.2)
        incisal_indices = [i for i, v in enumerate(verts_world) if v.z <= threshold_z]
        if not incisal_indices:
            incisal_indices = [0]
        incisal_point_world = Vector()
        for i in incisal_indices:
            incisal_point_world += verts_world[i]
        incisal_point_world /= len(incisal_indices)
        incisal_point_local = Vector()
        for i in incisal_indices:
            incisal_point_local += verts_local[i]
        incisal_point_local /= len(incisal_indices)
        cervical_direction = Vector((0, 0, 1))
        return incisal_point_world, incisal_point_local, cervical_direction
    finally:
        eo.to_mesh_clear()


def calculate_orientation_from_anatomical_points(
    incisal_point, facial_point, tooth_center
):
    """Calculate rotation matrix from marked anatomical points."""
    ci_axis = (incisal_point - tooth_center).normalized()
    bl_axis = (facial_point - tooth_center).normalized()
    md_axis = ci_axis.cross(bl_axis).normalized()
    bl_axis = md_axis.cross(ci_axis).normalized()
    rot_matrix = Matrix.Identity(4)
    rot_matrix[0][0:3] = md_axis
    rot_matrix[1][0:3] = -bl_axis
    rot_matrix[2][0:3] = -ci_axis
    return rot_matrix


def apply_angulation_preset(rot_matrix, preset="NATURAL", custom_angle=0.0):
    """Apply preset angulation adjustments to tooth orientation."""
    angle_map = {
        "NONE": 0.0,
        "NATURAL": math.radians(2.5),
        "AGGRESSIVE": math.radians(6.0),
        "CONSERVATIVE": math.radians(1.0),
        "CUSTOM": custom_angle,
    }
    angle = angle_map.get(preset, 0.0)
    if abs(angle) < 0.001:
        return rot_matrix
    angulation_rot = Matrix.Rotation(angle, 4, "X")
    return angulation_rot @ rot_matrix


def create_axis_gizmo(obj, size=0.005, auto_delete_seconds=3):
    """Create RGB axis gizmo on object for orientation visualization."""
    arrows = []
    colors = [(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1)]
    axes = ["X", "Y", "Z"]
    directions = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
    for i, axis in enumerate(axes):
        name = f"{obj.name}_Axis_{axis}"
        existing = bpy.data.objects.get(name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)
        mesh_data = bpy.data.meshes.new(name + "_mesh")
        arrow_obj = bpy.data.objects.new(name, mesh_data)
        bpy.context.scene.collection.objects.link(arrow_obj)
        bm = bmesh.new()
        try:
            v1 = bm.verts.new((0, 0, 0))
            v2 = bm.verts.new(directions[i] * size)
            bm.edges.new([v1, v2])
            bm.to_mesh(mesh_data)
        finally:
            bm.free()
        arrow_obj.location = obj.location
        arrow_obj.rotation_euler = obj.rotation_euler
        arrow_obj.parent = obj
        mat = bpy.data.materials.new(name + "_mat")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = colors[i]
        emission.inputs["Strength"].default_value = 2.0
        mat.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
        arrow_obj.data.materials.append(mat)
        arrow_obj.show_in_front = True
        arrows.append(arrow_obj)
        if auto_delete_seconds > 0:
            arrow_obj["AUTO_DELETE_TIME"] = time.time() + auto_delete_seconds
    return arrows


def detect_incisal_by_raycast(
    tooth_obj, target_position, ray_direction=Vector((0, 0, -1)), max_distance=50.0
):
    """Detect incisal contact point by raycasting from above the tooth."""
    ray_origin = target_position - (ray_direction * max_distance / 2.0)
    ray_dir = ray_direction.normalized()
    deps = bpy.context.evaluated_depsgraph_get()
    mw_inv = tooth_obj.matrix_world.inverted()
    ray_origin_local = mw_inv @ ray_origin
    ray_end_local = mw_inv @ (ray_origin + ray_dir * max_distance)
    ray_vec_local = ray_end_local - ray_origin_local
    ray_dist_local = ray_vec_local.length
    if ray_dist_local <= 1.0e-9:
        return None, None
    ray_dir_local = ray_vec_local / ray_dist_local
    hit, location, normal, face_index = tooth_obj.ray_cast(
        ray_origin_local, ray_dir_local, distance=ray_dist_local
    )
    if hit:
        hit_world = tooth_obj.matrix_world @ location
        hit_local = location.copy()
        return hit_world, hit_local
    return None, None


def detect_lingual_surface(obj):
    """Detect the lingual (tongue-side) surface of a tooth."""
    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()
    try:
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            bm.verts.ensure_lookup_table()
            curvatures = []
            positions = []
            for v in bm.verts:
                if len(v.link_edges) == 0:
                    continue
                neighbor_avg = Vector()
                for e in v.link_edges:
                    other = e.other_vert(v)
                    neighbor_avg += other.co
                neighbor_avg /= len(v.link_edges)
                normal_dir = v.normal
                displacement = v.co - neighbor_avg
                curvature = displacement.dot(normal_dir)
                curvatures.append(curvature)
                positions.append(obj.matrix_world @ v.co)
        finally:
            bm.free()
        if not curvatures:
            return Vector((0, 1, 0))
        sorted_indices = sorted(range(len(curvatures)), key=lambda i: curvatures[i])
        bottom_20_percent = int(len(sorted_indices) * 0.2)
        concave_indices = sorted_indices[: max(bottom_20_percent, 1)]
        concave_center = Vector()
        for idx in concave_indices:
            concave_center += positions[idx]
        concave_center /= len(concave_indices)
        lingual_dir = (concave_center - obj.location).normalized()
        return lingual_dir
    finally:
        eo.to_mesh_clear()


# ============================================================
# TRI-CURVE SYSTEM HELPERS
# ============================================================


def find_curve_with_priority(curve_names, context_msg=""):
    """Find first existing curve from priority list."""
    for name in curve_names:
        obj = bpy.data.objects.get(name)
        if obj and obj.type == "CURVE":
            print(f"DEBUG {context_msg}: Using '{name}'")
            return obj, name
    print(f"DEBUG {context_msg}: No curves found from {curve_names}")
    return None, None


def find_existing_tooth_for_angulation(tooth_id, collection_name=COL_TEETH):
    """Find adjacent existing tooth to copy rotation from."""
    col = bpy.data.collections.get(collection_name)
    if not col:
        return None
    existing = []
    for obj in col.objects:
        if obj.type != "MESH":
            continue
        tid = parse_tooth_id_from_name(obj.name)
        if tid:
            existing.append((tid, obj))
    if not existing:
        return None
    existing.sort(key=lambda x: x[0])
    for tid, obj in existing:
        if abs(tid - tooth_id) == 1:
            return obj
    for tid, obj in existing:
        if abs(tid - tooth_id) <= 8:
            return obj
    return existing[0][1]


def evaluate_tri_curve_position_for_tooth(
    lateral_curve,
    depth_curve,
    t,
    tooth_bbox,
    angulation_reference=None,
    incisal_point_local=None,
    midline_local=None,
    embedding_depth=0.5,
    facial_lingual_axis=None,
):
    """Evaluate tooth position using tri-curve system."""
    lateral_pos = evaluate_curve_at_parameter(lateral_curve, t)
    pos_next = evaluate_curve_at_parameter(lateral_curve, min(t + 0.01, 1.0))
    pos_prev = evaluate_curve_at_parameter(lateral_curve, max(t - 0.01, 0.0))
    lateral_tangent = (pos_next - pos_prev).normalized()
    if depth_curve and depth_curve != lateral_curve:
        depth_pos = evaluate_curve_at_parameter(depth_curve, t)
        target_z = depth_pos.z
    else:
        target_z = lateral_pos.z
    incisal_target = Vector((lateral_pos.x, lateral_pos.y, target_z))
    if incisal_point_local:
        incisal_offset = -incisal_point_local.z
    else:
        incisal_offset = -tooth_bbox[0].z
    tooth_origin = incisal_target + Vector((0, 0, incisal_offset))
    if angulation_reference:
        rot_matrix = angulation_reference.matrix_world.to_3x3().to_4x4()
    else:
        up_vec = Vector((0, 0, 1))
        rot_x = lateral_tangent
        rot_y = up_vec.cross(rot_x).normalized()
        rot_z = rot_x.cross(rot_y).normalized()
        rot_matrix = Matrix.Identity(4)
        rot_matrix[0][0], rot_matrix[1][0], rot_matrix[2][0] = rot_x
        rot_matrix[0][1], rot_matrix[1][1], rot_matrix[2][1] = rot_y
        rot_matrix[0][2], rot_matrix[1][2], rot_matrix[2][2] = rot_z
    if midline_local is not None and facial_lingual_axis is not None:
        midline_offset_local = midline_local.copy()
        embedding_offset_world = (
            facial_lingual_axis
            * (0.5 - embedding_depth)
            * midline_offset_local.length
            * 2.0
        )
        tooth_origin += embedding_offset_world
    return tooth_origin, rot_matrix, lateral_tangent


# ============================================================
# PRE-IMPORT ORIENTATION CORRECTION
# ============================================================


def get_pre_import_orientation_correction(
    library_preset, custom_x=0, custom_y=0, custom_z=0
):
    """Get rotation matrix to correct library orientation to standard dental coordinates."""
    if library_preset == "STANDARD":
        return Matrix.Identity(4)
    elif library_preset == "INVERTED_Z":
        return Matrix.Rotation(math.radians(180), 4, "X")
    elif library_preset == "INVERTED_Y":
        return Matrix.Rotation(math.radians(180), 4, "Z")
    elif library_preset == "ROTATED_90X":
        return Matrix.Rotation(math.radians(90), 4, "X")
    elif library_preset == "ROTATED_90Y":
        return Matrix.Rotation(math.radians(90), 4, "Y")
    elif library_preset == "ROTATED_180Y":
        return Matrix.Rotation(math.radians(180), 4, "Y")
    elif library_preset == "CUSTOM":
        euler = Matrix.Euler((custom_x, custom_y, custom_z), "XYZ")
        return euler.to_matrix().to_4x4()
    else:
        return Matrix.Identity(4)


def verify_incisal_at_target(tooth_obj, target_z, tolerance=1.0):
    """Check if tooth's incisal edge is at expected Z position."""
    if "SMILE_INCISAL_POINT_WORLD" in tooth_obj:
        incisal_world = Vector(tooth_obj["SMILE_INCISAL_POINT_WORLD"])
        incisal_z = incisal_world.z
        method = "DETECTED"
    else:
        mn, mx = bbox_world(tooth_obj)
        incisal_z = mn.z
        method = "BBOX"
    diff = abs(incisal_z - target_z)
    is_correct = diff <= tolerance
    suggested_fix = None if is_correct else "UNKNOWN"
    debug_info = {
        "incisal_z": incisal_z,
        "bbox_min_z": mn.z,
        "bbox_max_z": mx.z,
        "diff": diff,
        "method": method,
    }
    return is_correct, suggested_fix, debug_info


# ============================================================
# GOLDEN RULER UPDATE
# ============================================================


def update_golden_ruler(context=None, props_context=None):
    """Update the Golden Ruler Arch and Ticks live when the slider moves."""
    if not context:
        context = bpy.context
    if props_context is None:
        props_context = context.scene.smile_v2
    ruler = bpy.data.objects.get("SMILE_Golden_Ruler")
    arch = bpy.data.objects.get("SMILE_Golden_Arch")
    if not arch:
        cdata = bpy.data.curves.new("SMILE_Golden_Arch", "CURVE")
        cdata.dimensions = "3D"
        spline = cdata.splines.new("BEZIER")
        arch = bpy.data.objects.new("SMILE_Golden_Arch", cdata)
        if context.collection:
            context.collection.objects.link(arch)
        else:
            ensure_collection(COL_ARCH).objects.link(arch)
    ticks = bpy.data.objects.get("SMILE_Golden_Ruler_Ticks")
    if not ticks:
        mesh = bpy.data.meshes.new("SMILE_Golden_Ruler_Ticks_Mesh")
        ticks = bpy.data.objects.new("SMILE_Golden_Ruler_Ticks", mesh)
        ticks.show_in_front = True
        if context.collection:
            context.collection.objects.link(ticks)
        else:
            ensure_collection(COL_ARCH).objects.link(ticks)
    if not ruler:
        return
    if arch and arch.parent != ruler:
        arch.parent = ruler
        arch.matrix_parent_inverse = ruler.matrix_world.inverted()
    if ticks and ticks.parent != ruler:
        ticks.parent = ruler
        ticks.matrix_parent_inverse = ruler.matrix_world.inverted()
    p1 = Vector(ruler.get("SMILE_P1", (0, 0, 0)))
    p2 = Vector(ruler.get("SMILE_P2", (0, 0, 0)))
    if p1.length < 0.001 or p2.length < 0.001:
        return
    pupil_r = bpy.data.objects.get("FACE_LM_Pupil_R")
    pupil_l = bpy.data.objects.get("FACE_LM_Pupil_L")
    if pupil_r and pupil_l:
        pr_loc = pupil_r.matrix_world.translation
        pl_loc = pupil_l.matrix_world.translation
        pupil_vec = pl_loc - pr_loc
        pupil_vec.y = 0
        if pupil_vec.length_squared > 1e-6:
            pupil_vec.normalize()
            tick_vec = Vector((-pupil_vec.z, 0, pupil_vec.x))
            if tick_vec.z < 0:
                tick_vec = -tick_vec
        else:
            tick_vec = Vector(ruler.get("SMILE_TICK_VEC", (0, 0, 1)))
    else:
        tick_vec = Vector(ruler.get("SMILE_TICK_VEC", (0, 0, 1)))
    mode = props_context.golden_ruler_mode
    if mode == "CLASSIC":
        tr = 6.472
        wc, wl, wk = 1.618 / tr, 1.0 / tr, 0.618 / tr
    else:
        wc, wl, wk = 0.23, 0.15, 0.12
    offsets = [
        0.0,
        wk,
        wk + wl,
        wk + wl + wc,
        wk + wl + wc + wc,
        wk + wl + wc + wc + wl,
        1.0,
    ]
    ruler["SMILE_OFFSETS"] = offsets
    plane_n = Vector(ruler.get("SMILE_NORMAL", (0, 1, 0)))
    depth = props_context.golden_arch_depth * 0.001
    target_obj = None
    scan_name = ruler.get("SMILE_SCAN_NAME", "")
    if scan_name:
        target_obj = bpy.data.objects.get(scan_name)
    if not offsets:
        return
    if ruler and ruler.data:
        thickness_mm = props_context.golden_ruler_thickness
        ruler.data.bevel_depth = thickness_mm * 0.001
    if ruler.data.splines:
        rspline = ruler.data.splines[0]
        rsteps = 64
        if len(rspline.bezier_points) != rsteps:
            rspline.bezier_points.add(rsteps - len(rspline.bezier_points))
        ray_dir_ruler = -plane_n
        ray_start_off_ruler = plane_n * 50.0
        deps = context.evaluated_depsgraph_get()
        for i in range(rsteps):
            t = i / (rsteps - 1)
            pt_linear = p1.lerp(p2, t)
            ray_origin = pt_linear + ray_start_off_ruler
            hit = False
            loc = Vector((0, 0, 0))
            if target_obj:
                mw = target_obj.matrix_world
                mwi = mw.inverted()
                ray_origin_local = mwi @ ray_origin
                ray_dir_local = mwi.to_3x3() @ ray_dir_ruler
                hit, loc_local, _, _ = target_obj.ray_cast(
                    ray_origin_local, ray_dir_local
                )
                if hit:
                    loc = mw @ loc_local
            else:
                hit, loc, _, _, _, _ = context.scene.ray_cast(
                    deps, ray_origin, ray_dir_ruler
                )
            valid_hit = hit and loc.length > 0.001
            final_pos = loc if valid_hit else pt_linear
            final_pos += (plane_n.normalized() if plane_n.length_squared > 1e-12 else Vector((0, 1, 0))) * 0.0001
            rspline.bezier_points[i].co = final_pos
            if i == 0 or i == rsteps - 1:
                rspline.bezier_points[i].handle_left_type = "VECTOR"
                rspline.bezier_points[i].handle_right_type = "VECTOR"
            else:
                rspline.bezier_points[i].handle_left_type = "AUTO"
                rspline.bezier_points[i].handle_right_type = "AUTO"
        rspline.bezier_points[0].co = p1 + plane_n * 0.005
        rspline.bezier_points[rsteps - 1].co = p2 + plane_n * 0.005
    if arch and arch.data.splines:
        spline = arch.data.splines[0]
        arch_world_inv = arch.matrix_world.inverted()
        steps = 64
        if len(spline.bezier_points) != steps:
            spline.bezier_points.add(steps - len(spline.bezier_points))
        midpoint = (p1 + p2) * 0.5
        apex = midpoint - (tick_vec * depth)
        deps = context.evaluated_depsgraph_get()
        if plane_n.length < 0.1:
            plane_n = Vector((0, 1, 0))
        ray_dir = -plane_n.normalized()
        ray_start_off = plane_n.normalized() * 50.0
        for i in range(steps):
            t = i / (steps - 1)
            p_ctrl = (2.0 * apex) - 0.5 * (p1 + p2)
            pt_float = (1 - t) ** 2 * p1 + 2 * (1 - t) * t * p_ctrl + t**2 * p2
            ray_origin = pt_float + ray_start_off
            hit = False
            loc = Vector((0, 0, 0))
            if target_obj:
                mw = target_obj.matrix_world
                mwi = mw.inverted()
                ray_origin_local = mwi @ ray_origin
                ray_dir_local = mwi.to_3x3() @ ray_dir
                hit, loc_local, _, _ = target_obj.ray_cast(
                    ray_origin_local, ray_dir_local
                )
                if hit:
                    loc = mw @ loc_local
            else:
                hit, loc, _, _, _, _ = context.scene.ray_cast(deps, ray_origin, ray_dir)
            valid_hit = hit and loc.length > 0.001
            final_pos = loc if valid_hit else pt_float
            final_pos += (plane_n.normalized() if plane_n.length_squared > 1e-12 else Vector((0, 1, 0))) * 0.0001
            final_pos_local = arch_world_inv @ final_pos
            spline.bezier_points[i].co = final_pos_local
            spline.bezier_points[i].handle_left_type = "AUTO"
            spline.bezier_points[i].handle_right_type = "AUTO"
    if ticks and ticks.type == "MESH":
        bm = bmesh.new()
        try:
            tick_h = 10.0
            ticks_world_inv = ticks.matrix_world.inverted()
            deps = context.evaluated_depsgraph_get()
            if plane_n.length < 0.1:
                plane_n = Vector((0, 1, 0))
            ray_dir = -plane_n.normalized()
            ray_start_off = plane_n.normalized() * 50.0
            for t in offsets:
                base_pos_linear = p1.lerp(p2, t)
                ray_origin = base_pos_linear + ray_start_off
                if target_obj:
                    mw = target_obj.matrix_world
                    mwi = mw.inverted()
                    ray_origin_local = mwi @ ray_origin
                    ray_dir_local = mwi.to_3x3() @ ray_dir
                    hit, loc_local, _, _ = target_obj.ray_cast(
                        ray_origin_local, ray_dir_local
                    )
                    if hit:
                        loc = mw @ loc_local
                else:
                    hit, loc, _, _, _, _ = context.scene.ray_cast(deps, ray_origin, ray_dir)
                final_pos = loc if hit else base_pos_linear
                final_pos += (plane_n.normalized() if plane_n.length_squared > 1e-12 else Vector((0, 1, 0))) * 0.0001
                final_pos_local = ticks_world_inv @ final_pos
                tick_vec_local = ticks_world_inv.to_3x3() @ tick_vec
                v1 = bm.verts.new(final_pos_local - tick_vec_local * (tick_h * 0.5))
                v2 = bm.verts.new(final_pos_local + tick_vec_local * (tick_h * 0.5))
                bm.edges.new((v1, v2))
            ticks.data.clear_geometry()
            bm.to_mesh(ticks.data)
        finally:
            bm.free()
        ticks.data.update()


# ============================================================
# LANDMARK OPERATORS
# ============================================================


class SMILE_OT_clear_face_landmarks(bpy.types.Operator):
    bl_idname = "smile.clear_face_landmarks"
    bl_label = "Clear Face Markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for o in list(bpy.data.objects):
            if o.get("SMILE_IS_FACE_LM") == 1:
                delete_object(o)
        self.report({"INFO"}, "Cleared face landmarks.")
        return {"FINISHED"}


class SMILE_OT_place_named_landmark(bpy.types.Operator):
    bl_idname = "smile.place_named_landmark"
    bl_label = "Place Face Point"
    bl_options = {"REGISTER", "UNDO"}

    lm_name: bpy.props.StringProperty(name="Name", default="Point")

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, f"Click on Face/Scan to place {self.lm_name}...")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
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
                col = ensure_collection(COL_LM)
                name = f"FACE_LM_{self.lm_name}"
                if bpy.data.objects.get(name):
                    name += f"_{int(random.random() * 1000)}"
                sz = context.scene.smile_v2.marker_size
                m = make_marker(
                    name, loc, sz, obj, (1, 1, 0, 1), shape="SPHERE", sticky=True
                )
                m["SMILE_IS_FACE_LM"] = 1
                self.report({"INFO"}, f"Placed {name}")
                return {"FINISHED"}
            else:
                self.report({"WARNING"}, "Click on a mesh.")
        return {"RUNNING_MODAL"}


class SMILE_OT_create_guide_line(bpy.types.Operator):
    bl_idname = "smile.create_guide_line"
    bl_label = "Connect Selected Points"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sel = context.selected_objects
        if len(sel) != 2:
            self.report({"ERROR"}, "Select exactly 2 points to connect.")
            return {"CANCELLED"}
        p1 = sel[0]
        p2 = sel[1]
        name = f"Guide_{p1.name}_to_{p2.name}"
        cdata = bpy.data.curves.new(name, "CURVE")
        cdata.dimensions = "3D"
        spline = cdata.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (0, 0, 0, 1)
        spline.points[1].co = (0, 0, 0, 1)
        curve_obj = bpy.data.objects.new(name, cdata)
        col = ensure_collection(COL_ARCH)
        col.objects.link(curve_obj)
        curve_obj.matrix_world = Matrix.Identity(4)

        def add_hook(target, pt_index):
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action="DESELECT")
            target.select_set(True)
            curve_obj.select_set(True)
            context.view_layer.objects.active = curve_obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.curve.select_all(action="DESELECT")
            cdata.splines[0].points[pt_index].select = True
            try:
                bpy.ops.object.hook_add_selob(use_bone=False)
            except Exception as e:
                print(f"Hook Error: {e}")
            bpy.ops.object.mode_set(mode="OBJECT")

        spline.points[0].co = (p1.location.x, p1.location.y, p1.location.z, 1.0)
        spline.points[1].co = (p2.location.x, p2.location.y, p2.location.z, 1.0)
        add_hook(p1, 0)
        add_hook(p2, 1)
        if p1.parent:
            curve_obj.parent = p1.parent
            curve_obj.matrix_parent_inverse = p1.parent.matrix_world.inverted()
        ensure_active(curve_obj)
        self.report({"INFO"}, "Guide line created.")
        return {"FINISHED"}


class SMILE_OT_remove_arch_markers_only(bpy.types.Operator):
    bl_idname = "smile.remove_arch_markers_only"
    bl_label = "Delete Markers (Keep Curve)"
    bl_options = {"REGISTER", "UNDO"}

    domain: bpy.props.EnumProperty(
        items=[(DOMAIN_MAX, "MAX", ""), (DOMAIN_MAN, "MAN", "")], default=DOMAIN_MAX
    )
    curve_role: bpy.props.EnumProperty(
        name="Curve",
        items=[
            (ARCH_CURVE_OCCLUSAL, "Occlusal", ""),
            (ARCH_CURVE_CERVICAL, "Cervical", ""),
        ],
        default=ARCH_CURVE_OCCLUSAL,
    )

    def execute(self, context):
        clear_arch_markers(self.domain, self.curve_role)
        self.report(
            {"INFO"}, f"Deleted {self.domain} {self.curve_role.lower()} markers."
        )
        return {"FINISHED"}


# ============================================================
# GOLDEN RULER OPERATORS
# ============================================================


class SMILE_OT_golden_ruler(bpy.types.Operator):
    bl_idname = "smile.golden_ruler"
    bl_label = "Golden Proportion Ruler"
    bl_options = {"REGISTER", "UNDO"}

    scan_obj_name: bpy.props.StringProperty(default="")

    _points = None
    _normal = None

    def invoke(self, context, event):
        self._points = []
        self._normal = Vector((0, 1, 0))
        scan_mesh = None
        max_vo = 0
        for obj in bpy.data.objects:
            if (
                obj.type == "MESH"
                and not obj.name.startswith("PNP_")
                and "Photo" not in obj.name
                and "SMILE_" not in obj.name
            ):
                if len(obj.data.vertices) > max_vo:
                    max_vo = len(obj.data.vertices)
                    scan_mesh = obj
        if scan_mesh:
            self.scan_obj_name = scan_mesh.name
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Click Left Canine, then Right Canine to place ruler.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        is_nav = event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "NUMPAD_PERIOD",
            "PERIOD",
        }
        is_alt_nav = event.alt and (
            event.type in {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE", "Z", "B"}
        )
        if is_nav or is_alt_nav:
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()
            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()
            hit, loc, _, _, _, _ = context.scene.ray_cast(deps, ray_origin, ray_dir)
            if hit:
                self._points.append(loc)
                if len(self._points) == 1:
                    self._normal = -ray_dir
            else:
                if len(self._points) == 0:
                    self._points.append(ray_origin + ray_dir * 1000.0)
                    self._normal = -ray_dir
                else:
                    from mathutils.geometry import intersect_line_plane

                    p1 = self._points[0]
                    p2_proj = intersect_line_plane(
                        ray_origin, ray_origin + ray_dir, p1, self._normal
                    )
                    if p2_proj:
                        self._points.append(p2_proj)
                    else:
                        self._points.append(ray_origin + ray_dir * 1000.0)
            if len(self._points) == 2:
                self.create_ruler(context)
                return {"FINISHED"}
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def create_ruler(self, context=None):
        if not context:
            context = bpy.context
        col = ensure_collection(COL_ARCH)
        p1 = self._points[0]
        p2 = self._points[1]
        name = "SMILE_Golden_Ruler"
        old = bpy.data.objects.get(name)
        if old:
            delete_object(old)
        old_t = bpy.data.objects.get(name + "_Ticks")
        if old_t:
            delete_object(old_t)
        plane_n = self._normal if self._normal else Vector((0, 1, 0))
        cdata = bpy.data.curves.new(name, "CURVE")
        cdata.dimensions = "3D"
        spline = cdata.splines.new("BEZIER")
        steps = 64
        spline.bezier_points.add(steps - 1)
        mat = bpy.data.materials.get("SMILE_Ruler_Gold")
        if not mat:
            mat = bpy.data.materials.new("SMILE_Ruler_Gold")
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            nodes.clear()
            emission = nodes.new("ShaderNodeEmission")
            emission.inputs["Color"].default_value = (1.0, 0.84, 0.0, 1.0)
            emission.inputs["Strength"].default_value = 1.0
            output = nodes.new("ShaderNodeOutputMaterial")
            mat.node_tree.links.new(
                emission.outputs["Emission"], output.inputs["Surface"]
            )
            mat.use_backface_culling = False
            mat.blend_method = "OPAQUE"
        cdata.materials.append(mat)
        p_props = bpy.context.scene.smile_v2
        mode = p_props.golden_ruler_mode
        vec = p2 - p1
        unit = vec.normalized() if vec.length_squared > 1e-12 else Vector((1, 0, 0))
        if mode == "CLASSIC":
            tr = 6.472
            wc, wl, wk = 1.618 / tr, 1.0 / tr, 0.618 / tr
        else:
            wc, wl, wk = 0.23, 0.15, 0.12
        offsets = [
            0.0,
            wk,
            wk + wl,
            wk + wl + wc,
            wk + wl + wc + wc,
            wk + wl + wc + wc + wl,
            1.0,
        ]
        if plane_n.length < 0.1:
            plane_n = Vector((0, 1, 0))
        ray_dir = -plane_n.normalized()
        ray_start_off = plane_n.normalized() * 50.0
        deps = bpy.context.evaluated_depsgraph_get()
        for i in range(steps):
            t = i / (steps - 1)
            pt_linear = p1.lerp(p2, t)
            ray_origin = pt_linear + ray_start_off
            hit, loc, _, _, _, _ = bpy.context.scene.ray_cast(deps, ray_origin, ray_dir)
            valid_hit = hit and loc.length > 0.001
            final_pos = loc if valid_hit else pt_linear
            final_pos += (plane_n.normalized() if plane_n.length_squared > 1e-12 else Vector((0, 1, 0))) * 0.0001
            spline.bezier_points[i].co = final_pos
            if i == 0 or i == steps - 1:
                spline.bezier_points[i].handle_left_type = "VECTOR"
                spline.bezier_points[i].handle_right_type = "VECTOR"
            else:
                spline.bezier_points[i].handle_left_type = "AUTO"
                spline.bezier_points[i].handle_right_type = "AUTO"
        spline.bezier_points[0].co = p1 + plane_n.normalized() * 0.005
        spline.bezier_points[steps - 1].co = p2 + plane_n.normalized() * 0.005
        obj = bpy.data.objects.new(name, cdata)
        col.objects.link(obj)
        obj.show_in_front = True
        thickness_mm = p_props.golden_ruler_thickness
        cdata.bevel_depth = thickness_mm * 0.001
        pupil_r = bpy.data.objects.get("FACE_LM_Pupil_R")
        pupil_l = bpy.data.objects.get("FACE_LM_Pupil_L")
        if pupil_r and pupil_l:
            pr_loc = pupil_r.matrix_world.translation
            pl_loc = pupil_l.matrix_world.translation
            pupil_vec = pl_loc - pr_loc
            pupil_vec.y = 0
            if pupil_vec.length_squared > 1e-6:
                pupil_vec.normalize()
                tick_vec = Vector((-pupil_vec.z, 0, pupil_vec.x))
                if tick_vec.z < 0:
                    tick_vec = -tick_vec
            else:
                _cross = unit.cross(plane_n)
                tick_vec = _cross.normalized() if _cross.length_squared > 1e-12 else Vector((0, 0, 1))
                if tick_vec.z < 0:
                    tick_vec = -tick_vec
        else:
            _cross = unit.cross(plane_n)
            tick_vec = _cross.normalized() if _cross.length_squared > 1e-12 else Vector((0, 0, 1))
            if tick_vec.z < 0:
                tick_vec = -tick_vec
        obj["SMILE_P1"] = p1
        obj["SMILE_P2"] = p2
        obj["SMILE_P1_BASE"] = p1
        obj["SMILE_P2_BASE"] = p2
        obj["SMILE_TICK_VEC"] = tick_vec
        obj["SMILE_OFFSETS"] = offsets
        obj["SMILE_NORMAL"] = plane_n
        if self.scan_obj_name:
            obj["SMILE_SCAN_NAME"] = self.scan_obj_name
        update_golden_ruler(p_props, context)


class SMILE_OT_delete_golden_ruler(bpy.types.Operator):
    bl_idname = "smile.delete_golden_ruler"
    bl_label = "Remove Golden Ruler"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        deleted_count = 0
        ruler_obj = bpy.data.objects.get("SMILE_Golden_Ruler")
        if ruler_obj:
            delete_object(ruler_obj)
            deleted_count += 1
        ticks_obj = bpy.data.objects.get("SMILE_Golden_Ruler_Ticks")
        if ticks_obj:
            delete_object(ticks_obj)
            deleted_count += 1
        arch_obj = bpy.data.objects.get("SMILE_Golden_Ruler_Arch")
        if arch_obj:
            delete_object(arch_obj)
            deleted_count += 1
        if deleted_count > 0:
            self.report(
                {"INFO"},
                f"Deleted golden ruler and {deleted_count - 1} associated objects",
            )
        else:
            self.report({"WARNING"}, "No golden ruler found to delete")
        return {"FINISHED"}


class SMILE_OT_spawn_parallel_guide(bpy.types.Operator):
    bl_idname = "smile.spawn_parallel_guide"
    bl_label = "Spawn Parallel Guide"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        active = context.view_layer.objects.active
        if not active or active.type != "CURVE":
            self.report({"ERROR"}, "Select a Guide Line first.")
            return {"CANCELLED"}
        dup = active.copy()
        dup.data = active.data.copy()
        dup.name = active.name + "_Parallel"
        context.collection.objects.link(dup)
        dup.modifiers.clear()
        pts = curve_world_points(active)
        if len(pts) < 2:
            return {"CANCELLED"}
        cdata = dup.data
        spl = cdata.splines[0]
        spl.points[0].co = (pts[0].x, pts[0].y, pts[0].z, 1.0)
        spl.points[1].co = (pts[1].x, pts[1].y, pts[1].z, 1.0)
        dup.lock_rotation = (True, True, True)
        if active.parent:
            dup.parent = active.parent
            dup.matrix_parent_inverse = active.parent.matrix_world.inverted()
        region = context.region
        rv3d = context.region_data
        if rv3d:
            view_inv = rv3d.view_matrix.inverted()
            view_z = view_inv.col[2].to_3d().normalized()
            offset_vec = view_z * 30.0
            view_y = view_inv.col[1].to_3d().normalized()
            offset_vec -= view_y * 20.0
            dup.location += offset_vec
        else:
            dup.location.z += 20.0
            dup.location.y -= 20.0
        ensure_active(dup)
        self.report({"INFO"}, "Parallel guide created (Floating). Move with G.")
        return {"FINISHED"}


class SMILE_OT_remove_all_guides(bpy.types.Operator):
    bl_idname = "smile.remove_all_guides"
    bl_label = "Remove All Guides"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        to_delete = []
        for obj in bpy.data.objects:
            if obj.type == "CURVE":
                if obj.name.startswith("Guide_") or obj.name.endswith("_Parallel"):
                    to_delete.append(obj)
        count = len(to_delete)
        for obj in to_delete:
            bpy.data.objects.remove(obj, do_unlink=True)
        self.report({"INFO"}, f"Removed {count} guide(s).")
        return {"FINISHED"}


class SMILE_OT_align_ruler_to_pupils(bpy.types.Operator):
    bl_idname = "smile.align_ruler_to_pupils"
    bl_label = "Align Ruler to Pupils"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ruler = bpy.data.objects.get("SMILE_Golden_Ruler")
        if not ruler:
            self.report({"ERROR"}, "Golden Ruler not found")
            return {"CANCELLED"}
        pupil_r = bpy.data.objects.get("FACE_LM_Pupil_R")
        pupil_l = bpy.data.objects.get("FACE_LM_Pupil_L")
        if not pupil_r or not pupil_l:
            self.report({"ERROR"}, "Pupil landmarks not found. Place them first.")
            return {"CANCELLED"}
        pr_loc = pupil_r.matrix_world.translation
        pl_loc = pupil_l.matrix_world.translation
        target_vec = pl_loc - pr_loc
        target_vec.y = 0
        if target_vec.length_squared < 1e-6:
            self.report({"WARNING"}, "Pupils are too close or overlapping.")
            return {"CANCELLED"}
        target_right = target_vec.normalized()
        forward = Vector((0, 1, 0))
        _cross_up = target_right.cross(forward)
        up = _cross_up.normalized() if _cross_up.length_squared > 1e-12 else Vector((0, 0, 1))
        _cross_fwd = up.cross(target_right)
        forward = _cross_fwd.normalized() if _cross_fwd.length_squared > 1e-12 else Vector((0, 1, 0))
        target_rot = Matrix((target_right, forward, up)).transposed().to_4x4()
        loc = ruler.matrix_world.translation.copy()
        scale = ruler.scale.copy()
        mat_loc = Matrix.Translation(loc)
        mat_scale = Matrix.Identity(4)
        mat_scale[0][0] = scale.x
        mat_scale[1][1] = scale.y
        mat_scale[2][2] = scale.z
        new_matrix = mat_loc @ target_rot @ mat_scale
        old_p1 = Vector(ruler.get("SMILE_P1", (0, 0, 0)))
        old_p2 = Vector(ruler.get("SMILE_P2", (0, 0, 0)))
        ruler.matrix_world = new_matrix
        ruler_center = (old_p1 + old_p2) * 0.5
        new_p1 = target_rot.to_3x3() @ (old_p1 - ruler_center) + ruler_center
        new_p2 = target_rot.to_3x3() @ (old_p2 - ruler_center) + ruler_center
        ruler["SMILE_P1"] = new_p1
        ruler["SMILE_P2"] = new_p2
        ruler["SMILE_P1_BASE"] = new_p1
        ruler["SMILE_P2_BASE"] = new_p2
        self.report({"INFO"}, "Ruler snapped to pupil line (Absolute).")
        update_golden_ruler(context.scene.smile_v2, context)
        return {"FINISHED"}


# ============================================================
# LIP LINE OPERATORS
# ============================================================


class SMILE_OT_draw_lip_line(bpy.types.Operator):
    bl_idname = "smile.draw_lip_line"
    bl_label = "Draw Lip Line (Click Points)"
    bl_options = {"REGISTER", "UNDO"}

    _points = None
    _target_obj = None

    def invoke(self, context, event):
        self._points = []
        self._target_obj = None
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "Draw Lip Line: Left Click to add points. Enter/Space to Finish. ESC to Cancel.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
            if len(self._points) > 2:
                self.create_curve_with_markers(context)
                return {"FINISHED"}
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
                self._points.append(loc)
                if not self._target_obj and obj:
                    self._target_obj = obj
            else:
                ref_point = context.scene.cursor.location
                if context.view_layer.objects.active:
                    ref_point = context.view_layer.objects.active.location
                plane_normal = rv3d.view_matrix.inverted().to_3x3().col[2].normalized()
                denom = ray_dir.dot(plane_normal)
                if abs(denom) > 1e-6:
                    t = (ref_point - ray_origin).dot(plane_normal) / denom
                    loc = ray_origin + ray_dir * t
                else:
                    loc = ray_origin + ray_dir * 100.0
                self._points.append(loc)
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def create_curve_with_markers(self, context):
        col = ensure_collection(COL_ARCH)
        name = "SMILE_Lip_Curve"
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        cdata = bpy.data.curves.new(name, "CURVE")
        cdata.dimensions = "3D"
        spline = cdata.splines.new("BEZIER")
        spline.bezier_points.add(len(self._points) - 1)
        for i, p in enumerate(self._points):
            bp = spline.bezier_points[i]
            bp.co = p
            bp.handle_left_type = "AUTO"
            bp.handle_right_type = "AUTO"
        spline.use_cyclic_u = True
        obj = bpy.data.objects.new(name, cdata)
        col.objects.link(obj)
        obj.show_in_front = True
        obj.color = (1.0, 0.2, 0.5, 1.0)
        cdata.bevel_depth = 0.0005
        cdata.bevel_resolution = 2
        if self._target_obj:
            obj.parent = self._target_obj
            obj.matrix_parent_inverse = self._target_obj.matrix_world.inverted()
            self.report({"INFO"}, f"Lip Line locked to {self._target_obj.name}")
        self.create_control_markers(context, obj, self._points, self._target_obj)
        ensure_active(obj)
        self.report({"INFO"}, "Lip Line Created with control markers.")

    def create_control_markers(self, context, curve_obj, points, target_obj):
        old_markers = [
            obj for obj in bpy.data.objects if obj.name.startswith("SMILE_LipCtrl_")
        ]
        for marker in old_markers:
            bpy.data.objects.remove(marker, do_unlink=True)
        for i, pt in enumerate(points):
            marker_name = f"SMILE_LipCtrl_{i:02d}"
            if target_obj and target_obj.type == "MESH":
                try:
                    make_marker(
                        name=marker_name,
                        world_location=pt,
                        size=0.002,
                        target_obj=target_obj,
                        rgba=(1.0, 0.8, 0.2, 1.0),
                        shape="SPHERE",
                        sticky=True,
                    )
                except Exception:
                    self.create_simple_marker(marker_name, pt, curve_obj)
            else:
                self.create_simple_marker(marker_name, pt, curve_obj)
            marker = bpy.data.objects.get(marker_name)
            if marker:
                marker["SMILE_LIP_CTRL_INDEX"] = i
                marker["SMILE_LIP_CURVE"] = curve_obj.name

    def create_simple_marker(self, name, location, curve_obj):
        col = ensure_collection(COL_ARCH)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.002, location=location)
        marker = bpy.context.active_object
        marker.name = name
        if marker.name not in col.objects:
            col.objects.link(marker)
            bpy.context.scene.collection.objects.unlink(marker)
        marker.show_in_front = True
        marker.color = (1.0, 0.8, 0.2, 1.0)
        mat = bpy.data.materials.new(name + "_MAT")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (1.0, 0.8, 0.2, 1.0)
        emission.inputs["Strength"].default_value = 5.0
        output = nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
        if marker.data.materials:
            marker.data.materials[0] = mat
        else:
            marker.data.materials.append(mat)


class SMILE_OT_update_lip_curve(bpy.types.Operator):
    bl_idname = "smile.update_lip_curve"
    bl_label = "Update Lip Curve from Markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        curve_obj = bpy.data.objects.get("SMILE_Lip_Curve")
        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"WARNING"}, "Lip curve not found")
            return {"CANCELLED"}
        markers = sorted(
            [obj for obj in bpy.data.objects if obj.name.startswith("SMILE_LipCtrl_")],
            key=lambda x: x.get("SMILE_LIP_CTRL_INDEX", 0),
        )
        if not markers:
            self.report({"WARNING"}, "No control markers found")
            return {"CANCELLED"}
        if curve_obj.data.splines:
            spline = curve_obj.data.splines[0]
            if len(spline.bezier_points) != len(markers):
                self.report(
                    {"ERROR"},
                    f"Point mismatch: {len(spline.bezier_points)} vs {len(markers)}",
                )
                return {"CANCELLED"}
            for i, marker in enumerate(markers):
                if i < len(spline.bezier_points):
                    marker_pos = marker.matrix_world.translation
                    if curve_obj.parent:
                        parent_inv = curve_obj.matrix_world.inverted()
                        local_pos = parent_inv @ marker_pos
                        spline.bezier_points[i].co = local_pos
                    else:
                        spline.bezier_points[i].co = marker_pos
                    spline.bezier_points[i].handle_left_type = "AUTO"
                    spline.bezier_points[i].handle_right_type = "AUTO"
            curve_obj.data.update_tag()
            context.view_layer.update()
            self.report(
                {"INFO"}, f"Updated lip curve with {len(markers)} control points"
            )
            return {"FINISHED"}
        return {"CANCELLED"}


class SMILE_OT_clear_lip_markers(bpy.types.Operator):
    bl_idname = "smile.clear_lip_markers"
    bl_label = "Clear Lip Control Markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        markers = [
            obj for obj in bpy.data.objects if obj.name.startswith("SMILE_LipCtrl_")
        ]
        count = len(markers)
        for marker in markers:
            bpy.data.objects.remove(marker, do_unlink=True)
        if count > 0:
            self.report({"INFO"}, f"Removed {count} control markers")
        else:
            self.report({"INFO"}, "No markers to remove")
        return {"FINISHED"}


class SMILE_OT_generate_smile_arc(bpy.types.Operator):
    bl_idname = "smile.generate_smile_arc"
    bl_label = "Generate Ideal Smile Arc"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        lip_obj = bpy.data.objects.get("SMILE_Lip_Curve")
        if not lip_obj:
            self.report({"ERROR"}, "Draw Lip Line first.")
            return {"CANCELLED"}
        deps = context.evaluated_depsgraph_get()
        eobj = lip_obj.evaluated_get(deps)
        me = eobj.to_mesh()
        pts = [lip_obj.matrix_world @ v.co for v in me.vertices]
        eobj.to_mesh_clear()
        if not pts:
            return {"CANCELLED"}
        name = "SMILE_Arc_Ideal"
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        cdata = bpy.data.curves.new("SMILE_Arc_Ideal_Data", "CURVE")
        cdata.dimensions = "3D"
        cdata.fill_mode = "FULL"
        spline = cdata.splines.new("BEZIER")
        spline.bezier_points.add(len(pts) - 1)
        for i, p in enumerate(pts):
            spline.bezier_points[i].co = p
            spline.bezier_points[i].handle_left_type = "AUTO"
            spline.bezier_points[i].handle_right_type = "AUTO"
        spline.use_cyclic_u = True
        final_obj = bpy.data.objects.new(name, cdata)
        context.collection.objects.link(final_obj)
        final_obj.show_in_front = True
        final_obj.color = (0.0, 0.5, 1.0, 1.0)
        self.report({"INFO"}, "Smile arc generated.")
        return {"FINISHED"}


# ============================================================
# ORIENTATION VERIFICATION OPERATOR
# ============================================================


class SMILE_OT_verify_golden_orientation(bpy.types.Operator):
    bl_idname = "smile.verify_golden_orientation"
    bl_label = "Verify Tooth Orientation (2-Click)"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooth_obj_name: bpy.props.StringProperty()

    _clicks = []
    _original_matrix = None
    _markers = []

    def invoke(self, context, event):
        self._clicks = []
        self._markers = []
        tooth_obj = bpy.data.objects.get(self.tooth_obj_name)
        if not tooth_obj:
            self.report({"ERROR"}, "Tooth object not found")
            return {"CANCELLED"}
        self._original_matrix = tooth_obj.matrix_world.copy()
        context.window_manager.modal_handler_add(self)
        self._draw_axis_gizmo(tooth_obj)
        self.report({"INFO"}, "Click 1: Incisal edge, Click 2: Facial center")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            tooth_obj = bpy.data.objects.get(self.tooth_obj_name)
            if tooth_obj:
                tooth_obj.matrix_world = self._original_matrix
            self._cleanup_markers()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            tooth_obj = bpy.data.objects.get(self.tooth_obj_name)
            if not tooth_obj:
                return {"CANCELLED"}
            hit = raycast_from_mouse_to_target(context, event, tooth_obj)
            if hit:
                loc, norm, fi = hit
                self._clicks.append(loc)
                self._add_click_marker(loc, len(self._clicks))
                if len(self._clicks) == 1:
                    self.report({"INFO"}, "Click 2: Facial center")
                elif len(self._clicks) == 2:
                    self._apply_orientation_from_clicks(context, tooth_obj)
                    return {"FINISHED"}
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def _apply_orientation_from_clicks(self, context, tooth_obj):
        incisal_pt = self._clicks[0]
        facial_pt = self._clicks[1]
        tooth_center = tooth_obj.location
        rot_matrix = calculate_orientation_from_anatomical_points(
            incisal_pt, facial_pt, tooth_center
        )
        p = context.scene.smile_v2
        preset = p.get("golden_angulation_preset", "NATURAL")
        custom_angle = p.get("golden_custom_angulation", 0.0)
        rot_matrix = apply_angulation_preset(rot_matrix, preset, custom_angle)
        tooth_obj.matrix_world = rot_matrix
        tooth_obj.location = tooth_center
        self.report({"INFO"}, "Orientation verified and applied")
        self._cleanup_markers()

    def _add_click_marker(self, location, number):
        name = f"ORIENT_MARKER_{number}"
        existing = bpy.data.objects.get(name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)
        mesh = bpy.data.meshes.new(name + "_mesh")
        marker_obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(marker_obj)
        bm = bmesh.new()
        try:
            bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=8, radius=0.001)
            bm.to_mesh(mesh)
        finally:
            bm.free()
        marker_obj.location = location
        color = (1, 0, 0, 1) if number == 1 else (0, 1, 0, 1)
        mat = bpy.data.materials.new(name + "_mat")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = color
        emission.inputs["Strength"].default_value = 3.0
        mat.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
        marker_obj.data.materials.append(mat)
        marker_obj.show_in_front = True
        self._markers.append(marker_obj)

    def _draw_axis_gizmo(self, tooth_obj):
        arrows = create_axis_gizmo(tooth_obj, size=0.005, auto_delete_seconds=0)
        self._markers.extend(arrows)

    def _cleanup_markers(self):
        for marker in self._markers:
            if marker and marker.name in bpy.data.objects:
                bpy.data.objects.remove(marker, do_unlink=True)
        self._markers.clear()


# ============================================================
# P1 SEGMENTATION CODE (Extracted from monolith)
# ============================================================


def calculate_pca_basis(obj):
    """
    Calculate the Principal Component Analysis (PCA) basis vectors for a mesh object.
    Returns:
        (vec1, vec2, vec3, center)
        - vec1: Primary axis (Longest variation) -> Target Z
        - vec2: Secondary axis (Medium variation) -> Target X
        - vec3: Tertiary axis (Shortest variation) -> Target Y
        - center: Geometric centroid of the sample points
    """
    import numpy as np

    if not obj or obj.type != "MESH":
        return None

    mesh = obj.data
    if len(mesh.vertices) < 3:
        return None

    # Gather sample points
    verts = np.array([v.co for v in mesh.vertices])

    # Downsample for speed
    if len(verts) > 1000:
        verts = verts[:: int(len(verts) / 1000)]

    # Covariance
    mean = np.mean(verts, axis=0)
    centered = verts - mean
    cov = np.cov(centered.T)
    evals, evecs = np.linalg.eigh(cov)

    # Sort eigenvalues: largest is primary axis
    order = evals.argsort()[::-1]

    vec1 = Vector(evecs[:, order[0]])  # Longest
    vec2 = Vector(evecs[:, order[1]])  # Mid
    vec3 = Vector(evecs[:, order[2]])  # Shortest

    center = Vector(mean)

    return vec1, vec2, vec3, center


def align_object_to_frame(obj, vec_z, vec_x):
    """
    Rotate object so that:
    - vec_z aligns with Local Z (Up)
    - vec_x aligns with Local X (Right)
    """
    # Ensure orthogonal Z, X, Y
    if vec_z.length_squared > 1e-12:
        vec_z.normalize()
    # Y is cross(Z, X)
    _cross_y = vec_z.cross(vec_x)
    vec_y = _cross_y.normalized() if _cross_y.length_squared > 1e-12 else Vector((0, 1, 0))
    # Re-calc X to be perfectly orthogonal
    _cross_x = vec_y.cross(vec_z)
    vec_x = _cross_x.normalized() if _cross_x.length_squared > 1e-12 else Vector((1, 0, 0))

    # Source Rotation Matrix (Local -> PCA Frame)
    # The PCA vectors are in Local Space.
    # We want a rotation R such that R @ vec_z = (0,0,1)

    src_mat = Matrix((vec_x, vec_y, vec_z)).transposed().to_4x4()

    # Invert to get the alignment rotation
    align_rot = src_mat.inverted()

    # Apply to Object matrix
    obj.matrix_world = obj.matrix_world @ align_rot

    return align_rot


def compute_margin_salience(bm):
    """
    Compute per-vertex Salience (0..1) where 1.0 = High likelihood of margin.
    Combines Mean Curvature (Ridge) and Dihedral Angle (Sharp Edge).
    """
    n = len(bm.verts)
    salience = [0.0] * n

    bm.normal_update()

    # 1. Compute Raw Metrics
    curvatures = []
    angles = []

    for v in bm.verts:
        # A. Mean Curvature (Laplace-Beltrami Approx)
        # Vector sum of (neighbor - v) / count
        # Projected onto Normal
        neighbors = [e.other_vert(v) for e in v.link_edges]
        if not neighbors:
            curvatures.append(0.0)
            angles.append(0.0)
            continue

        avg_pos = sum((n.co for n in neighbors), Vector()) / len(neighbors)
        diff = avg_pos - v.co
        # Magnitude of projection onto normal
        k_mean = abs(diff.dot(v.normal))
        curvatures.append(k_mean)

        # B. Dihedral Angle (Max angle between face normals)
        # Margins are often 'corners'
        max_ang = 0.0
        # Check all pairs of faces connected to this vert? Expensive O(F^2).
        # Optimization: Check angles across linked edges.
        for e in v.link_edges:
            if len(e.link_faces) == 2:
                # Angle range 0..Pi
                a = e.link_faces[0].normal.angle(e.link_faces[1].normal)
                if a > max_ang:
                    max_ang = a
        angles.append(max_ang)

    # 2. Normalize (95th percentile to avoid outliers scaling everything down)
    import numpy as np

    def get_max_robust(data):
        if not data:
            return 1.0
        # Sort and pick 98% percentile
        # sorting is O(N log N), acceptable for 10k-50k verts
        s = sorted(data)
        idx = int(len(s) * 0.98)
        val = s[idx]
        return val if val > 1e-6 else 1.0

    max_k = get_max_robust(curvatures)
    max_a = get_max_robust(angles)

    # 3. Combine
    # Weights: Curvature is good for shoulders. Angle is good for chamfers.
    # Equal mix is robust.
    w_k = 0.5
    w_a = 0.5

    for i in range(n):
        s_k = min(1.0, curvatures[i] / max_k)
        s_a = min(1.0, angles[i] / max_a)

        # Salience = Weighted Sum
        s_total = (s_k * w_k) + (s_a * w_a)

        # Non-linear boost? Push lows down, highs up.
        # s_total = s_total ** 2 # No, linear is fine for A* cost

        salience[i] = s_total

    return salience


def mesh_a_star_path(bm, start_idx, end_idx, salience, max_dist=30.0):
    """
    Finds shortest path from start to end on BMesh graph using Salience weights.
    start_idx, end_idx: vertex indices
    salience: list of floats per vertex
    Returns list of vertex indices.
    """
    import heapq

    # Dijkstra/A*
    # Cost = Distance * (1 + 20 * (1 - salience)^2)
    # This makes flat areas extremely 'expensive'.

    start_v = bm.verts[start_idx]
    end_v = bm.verts[end_idx]
    target_pos = end_v.co

    # visited: idx -> (total_cost, prev_idx)
    visited = {start_idx: (0.0, -1)}
    queue = [(0.0, 0.0, start_idx)]  # (f_score, g_score, idx)

    count = 0
    while queue:
        f, g, curr_idx = heapq.heappop(queue)
        count += 1

        if curr_idx == end_idx:
            break
        if g > max_dist:
            continue  # Prune if path gets too long
        if count > 5000:
            break  # Hard cap for performance

        curr_v = bm.verts[curr_idx]
        for e in curr_v.link_edges:
            neighbor = e.other_vert(curr_v)
            ni = neighbor.index

            # Distance Weight
            d = e.calc_length()

            # Salience Penalty (1.0..21.0)
            s_val = (salience[curr_idx] + salience[ni]) * 0.5
            penalty = 1.0 + 30.0 * (1.0 - s_val) ** 2

            new_g = g + (d * penalty)

            if ni not in visited or new_g < visited[ni][0]:
                visited[ni] = (new_g, curr_idx)
                # Heuristic (Euclidean distance to target)
                h = (neighbor.co - target_pos).length
                heapq.heappush(queue, (new_g + h, new_g, ni))

    # Reconstruct
    path = []
    curr = end_idx
    if end_idx not in visited:
        return []  # No path found

    while curr != -1:
        path.append(curr)
        curr = visited[curr][1]

    path.reverse()
    return path


def curve_tangent_at_index(samples_pts, i):
    if len(samples_pts) < 2:
        return Vector((1, 0, 0))
    if i == 0:
        t = samples_pts[1] - samples_pts[0]
    elif i == len(samples_pts) - 1:
        t = samples_pts[-1] - samples_pts[-2]
    else:
        t = samples_pts[i + 1] - samples_pts[i - 1]
    return t if t.length > 1e-9 else Vector((1, 0, 0))


def sort_teeth_by_id(mesh_objs):
    items = []
    for o in mesh_objs:
        tid = parse_tooth_id_from_name(o.name)
        if tid is None:
            continue
        items.append((tid, o))
    items.sort(key=lambda x: x[0])
    return [o for _, o in items]


def apply_tooth_tweaks(obj, arch_tangent: Vector, occlusal_up: Vector):
    ensure_tooth_params(obj)

    z = arch_tangent.normalized() if arch_tangent.length > 1e-9 else Vector((1, 0, 0))
    y = occlusal_up.normalized() if occlusal_up.length > 1e-9 else Vector((0, 0, 1))
    x = y.cross(z)
    if x.length < 1e-9:
        x = Vector((1, 0, 0))
    x.normalize()
    _cross_y = z.cross(x)
    y = _cross_y.normalized() if _cross_y.length_squared > 1e-12 else Vector((0, 1, 0))

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


def update_ghosts():
    for o in tooth_objects_in_collection():
        ensure_tooth_params(o)
        if int(o.get("SMILE_GHOST", 0)) == 1:
            make_ghost_preview(o)
        else:
            g = bpy.data.objects.get(o.name + "_GHOST")
            if g:
                g.hide_set(True)


def distribute_teeth_width_aware(
    curve_obj,
    teeth_sorted,
    gap_mm=0.25,
    bridge_mode=False,
    scan_obj=None,
    incisal_curve_obj=None,
):
    pts = curve_world_points(curve_obj)
    if len(pts) < 2:
        raise RuntimeError("Arch curve sampling failed.")

    # Robust curve direction: use arch centroid cross-product handedness.
    # The arch forms a U/V. Centroid is inside. We need curve to go
    # Right→Left (patient's right = viewer's left = -X in standard view).
    arch_cen = sum(pts, Vector()) / max(1, len(pts))
    v_start = pts[0] - arch_cen
    v_end = pts[-1] - arch_cen

    # Cross product with UP: if start is on patient's LEFT side,
    # the cross points anteriorly (+Y in standard face-view).
    # We want start on patient's RIGHT, where cross points posteriorly.
    cross_start = v_start.cross(Vector((0, 0, 1)))
    cross_end = v_end.cross(Vector((0, 0, 1)))

    # Use the cross product Y component: positive = patient's left side.
    # If start is on left side (cross.y > 0), reverse so start = right.
    # Also fallback to X-check if cross magnitudes are too small.
    if abs(cross_start.y) > 1e-6 or abs(cross_end.y) > 1e-6:
        if cross_start.y > cross_end.y:
            pts.reverse()
    else:
        # Fallback: simple X-coordinate comparison
        if pts[0].x > pts[-1].x:
            pts.reverse()

    # Now pts[0] is patient's Right side, pts[-1] is patient's Left side.
    # Midline is at t=0.5.
    # Right Teeth (1-8) go from Midline (0.5) towards Right (0.0).
    # Left Teeth (9-16) go from Midline (0.5) towards Left (1.0).

    segL = []
    cum = [0.0]
    for i in range(len(pts) - 1):
        L = (pts[i + 1] - pts[i]).length
        segL.append(L)
        cum.append(cum[-1] + L)
    total = cum[-1]

    def point_at_distance(d):
        d = max(0.0, min(total, d))
        for i, L in enumerate(segL):
            if cum[i] + L >= d:
                t = (d - cum[i]) / L if L > 1e-9 else 0.0
                # Interpolate
                pt = pts[i].lerp(pts[i + 1], t)
                # Tangent (approx)
                _diff = pts[i + 1] - pts[i]
                tan = _diff.normalized() if _diff.length_squared > 1e-12 else Vector((1, 0, 0))
                return pt, tan
        _diff_end = pts[-1] - pts[-2]
        return pts[-1], _diff_end.normalized() if _diff_end.length_squared > 1e-12 else Vector((1, 0, 0))

    midline_d = total * 0.5

    # Optional secondary curve for incisal/cusp guidance.
    smile_arc_pts = []
    if incisal_curve_obj and incisal_curve_obj.type == "CURVE":
        smile_arc_pts = curve_world_points(incisal_curve_obj)
    else:
        smile_arc_obj = bpy.data.objects.get("SMILE_Arc_Ideal")
        if smile_arc_obj:
            smile_arc_pts = curve_world_points(smile_arc_obj)

    right_teeth = []
    left_teeth = []

    for t in teeth_sorted:
        tid = parse_tooth_id_from_name(t.name)
        if not tid:
            continue

        is_right = False
        is_left = False

        # Q1/Q4 are Right
        if 1 <= tid <= 8:
            is_right = True
        elif 25 <= tid <= 32:
            is_right = True

        # Q2/Q3 are Left
        elif 9 <= tid <= 16:
            is_left = True
        elif 17 <= tid <= 24:
            is_left = True

        if is_right:
            right_teeth.append(t)
        elif is_left:
            left_teeth.append(t)

    def get_id(o):
        return parse_tooth_id_from_name(o.name) or 0

    # Sort
    # Upper: 1-16. Right 8->1. Left 9->16.
    # Lower: 17-32. Right 25->32. Left 24->17.

    # Are we layout out Upper or Lower?
    is_upper = any((get_id(t) <= 16) for t in (right_teeth + left_teeth))

    if is_upper:
        right_teeth.sort(key=get_id, reverse=True)  # 8, 7, 6...
        left_teeth.sort(key=get_id, reverse=False)  # 9, 10, 11...
    else:
        # Lower: Right is 25-32. Left is 17-24.
        # We start from midline.
        # Midline is between 24 and 25.
        # Right (25-32): 25 is Central. 32 is Molar.
        # We want 25, 26, 27... so ASCENDING.
        right_teeth.sort(key=get_id, reverse=False)

        # Left (17-24): 24 is Central. 17 is Molar.
        # We want 24, 23, 22... so DESCENDING.
        left_teeth.sort(key=get_id, reverse=True)

    # --- PLACEMENT ---
    # Right Side: Midline -> Right (0.0)
    cursor = midline_d
    for t in right_teeth:
        w = max(0.1, mesiodistal_width_estimate(t, axis="X"))
        center_d = cursor - (w * 0.5) - (gap_mm * 0.5)

        pos, tan = point_at_distance(center_d)

        if smile_arc_pts:
            best_z = pos.z
            min_dx = 1000.0
            for sap in smile_arc_pts:
                dx = abs(sap.x - pos.x)
                if dx < min_dx:
                    min_dx = dx
                    best_z = sap.z
            pos.z = best_z

        t.matrix_world.translation = pos
        tid = get_id(t)
        orient_tooth_to_arch(
            t,
            pts,
            tan,
            pos,
            tid,
            is_upper=is_upper,
            scan_obj=scan_obj,
            incisal_curve_points=smile_arc_pts if smile_arc_pts else None,
        )
        cursor -= w + gap_mm

    # Left Side: Midline -> Left (Total)
    cursor = midline_d
    for t in left_teeth:
        w = max(0.1, mesiodistal_width_estimate(t, axis="X"))
        center_d = cursor + (w * 0.5) + (gap_mm * 0.5)

        pos, tan = point_at_distance(center_d)

        if smile_arc_pts:
            best_z = pos.z
            min_dx = 1000.0
            for sap in smile_arc_pts:
                dx = abs(sap.x - pos.x)
                if dx < min_dx:
                    min_dx = dx
                    best_z = sap.z
            pos.z = best_z

        t.matrix_world.translation = pos
        tid = get_id(t)
        orient_tooth_to_arch(
            t,
            pts,
            tan,
            pos,
            tid,
            is_upper=is_upper,
            scan_obj=scan_obj,
            incisal_curve_points=smile_arc_pts if smile_arc_pts else None,
        )
        cursor += w + gap_mm


def create_arch_from_roi(mesh_obj, vg_name="SMILE_ROI"):
    """Creates a temporary curve object fitting the ROI vertex group."""
    vg = mesh_obj.vertex_groups.get(vg_name)
    if not vg:
        return None

    # Gather points
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh_obj.data)
        bm.verts.ensure_lookup_table()
        dvert_lay = bm.verts.layers.deform.verify()

        points = []
        for v in bm.verts:
            dvert = v[dvert_lay]
            if vg.index in dvert and dvert[vg.index] > 0.1:
                points.append(mesh_obj.matrix_world @ v.co)
    finally:
        bm.free()

    if len(points) < 3:
        return None

    # Sort by X to find Left/Right/Center roughly
    points.sort(key=lambda p: p.x)
    p_right = points[0]  # Min X (Patient Right)
    p_left = points[-1]  # Max X (Patient Left)

    # Find Apex (Max Y? or Min Y? Anterior is usually Y- or Y+. Let's assume most Anterior point)
    # Standard Head: +Y is Back, -Y is Front. So Min Y.
    # But let's check distance from base line.

    # Robust Apex finding: Point furthest from the Line(Right, Left) in the forward direction.
    base_vec = p_left - p_right
    base_len = base_vec.length
    if base_len < 0.001:
        return None

    base_dir = base_vec.normalized()
    # Anterior direction is perpendicular to base_dir, roughly -Y or +Y?
    # Let's just find the point with max distance from the line segment.

    best_p = None
    max_d = -1.0

    for p in points:
        # Distance to line
        vec_to_p = p - p_right
        proj = vec_to_p.dot(base_dir)
        closest_on_line = p_right + base_dir * proj
        dist = (p - closest_on_line).length
        if dist > max_d:
            max_d = dist
            best_p = p

    p_mid = best_p if best_p else points[len(points) // 2]

    # Create Curve passing through Right -> Mid -> Left
    name = "Temp_ROI_Arch"
    cdata = bpy.data.curves.new(name, "CURVE")
    cdata.dimensions = "3D"
    spline = cdata.splines.new("BEZIER")
    spline.bezier_points.add(2)  # 3 points total

    # Right
    spline.bezier_points[0].co = p_right
    spline.bezier_points[0].handle_left_type = "AUTO"
    spline.bezier_points[0].handle_right_type = "AUTO"

    # Mid
    spline.bezier_points[1].co = p_mid
    spline.bezier_points[1].handle_left_type = "AUTO"
    spline.bezier_points[1].handle_right_type = "AUTO"

    # Left
    spline.bezier_points[2].co = p_left
    spline.bezier_points[2].handle_left_type = "AUTO"
    spline.bezier_points[2].handle_right_type = "AUTO"

    curve_obj = bpy.data.objects.new(name, cdata)
    # Don't link to scene if we just want to use it for calculation?
    # distribute_teeth_width_aware needs it in scene context? No, just data access.
    # But it calls curve_world_points which uses matrix_world.
    # So we must link it to update matrices or set matrix manually.
    ensure_collection(COL_ARCH).objects.link(curve_obj)
    curve_obj.matrix_world = Matrix.Identity(4)  # Points are already world space

    return curve_obj


class SMILE_OT_upright_model(bpy.types.Operator):
    bl_idname = "smile.upright_model"
    bl_label = "Auto-Upright (Z-Up)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh.")
            return {"CANCELLED"}

        # Use helper function to calculate PCA
        basis = calculate_pca_basis(obj)
        if not basis:
            self.report({"ERROR"}, "Could not calculate PCA (mesh too small?)")
            return {"CANCELLED"}

        vec1, vec2, vec3, center = basis

        # Logic:
        # vec1 (Longest) -> UP (Z)
        # vec2 (Widest) -> RIGHT (X)

        align_object_to_frame(obj, vec_z=vec1, vec_x=vec2)

        self.report({"INFO"}, "Model Uprighted to Z-axis.")
        return {"FINISHED"}


class SMILE_OT_lock_rotation_axis(bpy.types.Operator):
    bl_idname = "smile.lock_rotation_axis"
    bl_label = "Lock/Unlock Rotation (Z-Only)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj:
            return {"CANCELLED"}

        # Toggle
        locked = obj.lock_rotation[0]  # Check X lock
        state = not locked

        obj.lock_rotation[0] = state  # X
        obj.lock_rotation[1] = state  # Y
        obj.lock_rotation[2] = False  # Z always free

        state_str = "Locked (Z-only)" if state else "Unlocked (Free)"
        self.report({"INFO"}, f"Rotation {state_str}")
        return {"FINISHED"}


class SMILE_OT_extract_segments(bpy.types.Operator):
    bl_idname = "smile.extract_segments"
    bl_label = "Extract Segmented Teeth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active

        # If no active object, try to find a selected mesh
        if not obj:
            sel = [o for o in context.selected_objects if o.type == "MESH"]
            if sel:
                obj = sel[0]
                context.view_layer.objects.active = obj

        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        # Use SafeMode to ensure we can read attributes in OBJECT mode
        with SafeMode(obj, "OBJECT"):
            attr = obj.data.attributes.get("SMILE_TOOTH_ID")
            vg_mask = obj.vertex_groups.get("SMILE_SEGMENTS")

            if not attr or not vg_mask:
                self.report({"ERROR"}, "Run Auto-Segmentation first.")
                return {"CANCELLED"}

            # NON-DESTRUCTIVE: BACKUP
            bak_col = bpy.data.collections.get(
                "Scans_Backup"
            ) or bpy.data.collections.new("Scans_Backup")
            if bak_col.name not in context.scene.collection.children:
                context.scene.collection.children.link(bak_col)

            original = obj
            # Keep original visible during extraction so failures never appear as "model deleted".
            original.hide_viewport = False
            original.hide_render = False

            # Link original to backup if not there
            if original and original.name not in bak_col.objects:
                bak_col.objects.link(original)

            # Create Working Copy
            working_obj = original.copy()
            working_obj.data = original.data.copy()
            working_obj.name = "Segmented_Working_Model"
            working_obj["SMILE_SEGMENT_EXTRACTED"] = True
            working_obj["SMILE_SEGMENT_SOURCE"] = original.name
            ensure_collection(COL_TEETH).objects.link(working_obj)

            # Now operate on working_obj
            obj = working_obj
            attr = obj.data.attributes.get("SMILE_TOOTH_ID")
            vg_mask = obj.vertex_groups.get("SMILE_SEGMENTS")

            import numpy as np

            n_verts = len(obj.data.vertices)

            # 1. Get IDs
            labels = np.zeros(n_verts, dtype=np.int32)
            attr.data.foreach_get("value", labels)

            # 2. Get Weights (Mask)
            vg_idx = vg_mask.index
            dverts = obj.data.vertices

            def get_w(v):
                for g in v.groups:
                    if g.group == vg_idx:
                        return g.weight
                return 0.0

            weights = np.array([get_w(v) for v in dverts], dtype=np.float32)

            # 3. Filter
            valid_labels = labels.copy()
            valid_labels[weights < 0.5] = 0

            unique_ids = np.unique(valid_labels)
            unique_ids = unique_ids[unique_ids > 0]

            if len(unique_ids) == 0:
                self.report({"WARNING"}, "No teeth in mask.")
                original.hide_viewport = False
                original.hide_render = False
                bpy.data.objects.remove(working_obj)
                return {"CANCELLED"}

            # 4. Separate
            for vg in list(obj.vertex_groups):
                if vg.name.startswith("SEG_"):
                    obj.vertex_groups.remove(vg)

            for tid in unique_ids:
                vg_tmp = obj.vertex_groups.new(name=f"SEG_{tid}")
                indices = np.where(valid_labels == tid)[0]
                vg_tmp.add(indices.tolist(), 1.0, "REPLACE")

        # SafeMode exits here, restoring original object state.

        # Re-implement Separation Loop safely
        working_name = working_obj.name

        def _resolve_working():
            nonlocal working_obj
            try:
                if working_obj and working_obj.name in bpy.data.objects:
                    live = bpy.data.objects.get(working_obj.name)
                else:
                    live = bpy.data.objects.get(working_name)
            except Exception:
                live = bpy.data.objects.get(working_name)
            if live and live.type == "MESH":
                working_obj = live
                return live
            return None

        wobj = _resolve_working()
        if not wobj:
            self.report({"ERROR"}, "Could not resolve working segmentation mesh.")
            original.hide_viewport = False
            original.hide_render = False
            return {"CANCELLED"}
        context.view_layer.objects.active = wobj
        wobj.select_set(True)

        # Separation Process
        # Since we are splitting one mesh into many, the 'working_obj' will shrink.

        extracted_objects = []

        for tid in unique_ids:
            wobj = _resolve_working()
            if not wobj:
                self.report(
                    {"WARNING"},
                    "Working mesh missing during extraction; stopping early.",
                )
                break

            # Ensure we are in Object mode to set VG selection
            # CRITICAL FIX: Ensure active/selected BEFORE mode switch
            context.view_layer.objects.active = wobj
            if not wobj.select_get():
                wobj.select_set(True)

            if context.view_layer.objects.active != wobj:
                context.view_layer.objects.active = wobj

            try:
                if wobj.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                context.view_layer.objects.active = wobj
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    self.report(
                        {"WARNING"},
                        f"Could not enter OBJECT mode for T#{int(tid)}; skipping.",
                    )
                    continue

            bpy.ops.object.select_all(action="DESELECT")
            wobj.select_set(True)  # Re-select just in case
            context.view_layer.objects.active = wobj

            vg_name = f"SEG_{tid}"
            vg_idx = wobj.vertex_groups.find(vg_name)
            if vg_idx == -1:
                continue

            # Select vertices in group
            # Ensure EDIT mode
            try:
                bpy.ops.object.mode_set(mode="EDIT")
            except Exception:
                context.view_layer.objects.active = wobj
                wobj.select_set(True)
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                except Exception:
                    self.report(
                        {"WARNING"},
                        f"Could not enter EDIT mode for T#{int(tid)}; skipping.",
                    )
                    continue
            bpy.ops.mesh.select_all(action="DESELECT")
            wobj.vertex_groups.active_index = vg_idx
            bpy.ops.object.vertex_group_select()

            # 2. Separate
            pre_names = set(o.name for o in bpy.data.objects)
            try:
                bpy.ops.mesh.separate(type="SELECTED")
            except Exception:
                continue

            # Identify the new object
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                # Recover by ensuring one selected mesh is active.
                sel_mesh = [o for o in context.selected_objects if o.type == "MESH"]
                if sel_mesh:
                    context.view_layer.objects.active = sel_mesh[0]
                    try:
                        bpy.ops.object.mode_set(mode="OBJECT")
                    except Exception:
                        pass

            # The separated part is usually the *other* selected object
            sel = list(context.selected_objects)
            new_part = None
            new_names = set(o.name for o in bpy.data.objects) - pre_names
            if new_names:
                for nm in new_names:
                    cand = bpy.data.objects.get(nm)
                    if cand and cand.type == "MESH":
                        new_part = cand
                        break

            wobj = _resolve_working()
            for s in sel:
                if s.type == "MESH" and (not wobj or s != wobj):
                    new_part = s
                    break

            if new_part:
                new_part.name = f"Tooth_{tid}"
                new_part["SMILE_SEGMENT_EXTRACTED"] = True
                new_part["SMILE_SEGMENT_SOURCE"] = original.name
                new_part["SMILE_SEGMENT_TID"] = int(tid)
                extracted_objects.append(new_part)
                # Clear its VGs?
                new_part.vertex_groups.clear()

                # Center origin
                context.view_layer.objects.active = new_part
                bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")

                # Restore active for next loop
                wobj = _resolve_working()
                if wobj:
                    context.view_layer.objects.active = wobj
                    wobj.select_set(True)

        # Cleanup remainder
        wobj = _resolve_working()
        if wobj and wobj.name in bpy.data.objects:
            bpy.data.objects.remove(wobj, do_unlink=True)

        if len(extracted_objects) == 0:
            # Hard safety: never leave user with hidden/missing base scan when nothing was extracted.
            original.hide_viewport = False
            original.hide_render = False
            self.report(
                {"WARNING"},
                "No segmented parts were extracted. Original scan restored.",
            )
            return {"CANCELLED"}

        # Fill holes
        for o in extracted_objects:
            with SafeMode(o, "EDIT"):
                bpy.ops.mesh.select_all(action="DESELECT")
                bpy.ops.mesh.select_non_manifold(
                    extend=False, use_wire=True, use_boundary=True
                )
                bpy.ops.mesh.fill()
                bpy.ops.mesh.poke()  # Triangulate the fill

        hide_original = bool(
            getattr(
                context.scene.smile_v2,
                "segmentation_hide_original_after_extract",
                False,
            )
        )
        original.hide_viewport = hide_original
        original.hide_render = hide_original
        if hide_original:
            self.report(
                {"INFO"},
                f"Extracted {len(extracted_objects)} teeth. Original scan hidden (toggle enabled).",
            )
        else:
            self.report(
                {"INFO"},
                f"Extracted {len(extracted_objects)} teeth. Original scan kept visible.",
            )
        return {"FINISHED"}


class SMILE_OT_select_segment_under_mouse(bpy.types.Operator):
    bl_idname = "smile.select_segment_under_mouse"
    bl_label = "Click to Select Tooth Segment"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Click on a colored tooth segment to select it.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Raycast
            obj = context.view_layer.objects.active
            if not obj or obj.type != "MESH":
                self.report({"ERROR"}, "Active object is not a mesh.")
                return {"CANCELLED"}

            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()

            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

            hit, loc, norm, face_i, hit_obj, _ = context.scene.ray_cast(
                deps, ray_origin, ray_dir
            )

            if hit and hit_obj == obj:
                mesh = obj.data
                attr = mesh.attributes.get("SMILE_TOOTH_ID")
                if not attr:
                    self.report({"ERROR"}, "No segmentation data found.")
                    return {"CANCELLED"}

                poly = mesh.polygons[face_i]
                v_idx = poly.vertices[0]
                tid = attr.data[v_idx].value

                if tid == 0:
                    self.report({"WARNING"}, "Clicked on Gum (ID 0). Click a tooth.")
                    return {"RUNNING_MODAL"}

                # Select ID
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_mode(type="VERT")
                bpy.ops.mesh.select_all(action="DESELECT")

                bm = bmesh.from_edit_mesh(mesh)
                bm.verts.ensure_lookup_table()
                layer = bm.verts.layers.int.get("SMILE_TOOTH_ID")
                if layer:
                    count = 0
                    for v in bm.verts:
                        if v[layer] == tid:
                            v.select = True
                            count += 1
                    bmesh.update_edit_mesh(mesh)

                    # Smooth the selection boundary
                    # region_to_loop -> smooth -> loop_to_region?
                    # Or simpler: Smooth selection mask?
                    # Let's try select_more() then select_less() to smooth noise?
                    # Or 'Select Boundary' -> Smooth Vertices -> Grow?
                    # Actually, standard selection is fine if flood fill was good.
                    # But let's smooth the boundary line slightly for cleaner cut.

                    # Convert to boundary loop
                    bpy.ops.mesh.region_to_loop()
                    # Smooth the vertices of the loop
                    bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=3)
                    # Reselect inside
                    bpy.ops.mesh.loop_to_region()

                    self.report({"INFO"}, f"Selected Tooth #{tid}. Boundary Smoothed.")
                    return {"FINISHED"}
                else:
                    self.report({"ERROR"}, "Could not find ID layer in Edit Mode.")
                    return {"CANCELLED"}

            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


class SMILE_OT_manual_extract_watertight(bpy.types.Operator):
    bl_idname = "smile.manual_extract_watertight"
    bl_label = "Extract Selected (Watertight)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh.")
            return {"CANCELLED"}

        if obj.mode != "EDIT":
            self.report(
                {"ERROR"}, "Enter Edit Mode and select the tooth geometry first."
            )
            return {"CANCELLED"}

        # 1. Separate
        bpy.ops.mesh.separate(type="SELECTED")

        # 2. Identify
        bpy.ops.object.mode_set(mode="OBJECT")
        selected = context.selected_objects
        tooth_obj = None
        for o in selected:
            if o != obj:
                tooth_obj = o
                break
        if not tooth_obj:
            return {"CANCELLED"}
        tooth_obj.name = "Extracted_Tooth"

        # 3. Robust Hole Filling (Fan/Poke)
        def fill_holes_robust(target_obj):
            ensure_active(target_obj)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="EDGE")
            bpy.ops.mesh.select_all(action="DESELECT")

            # Select Boundary
            bpy.ops.mesh.select_non_manifold(
                extend=False,
                use_wire=True,
                use_boundary=True,
                use_multi_face=False,
                use_non_contiguous=False,
                use_verts=False,
            )

            # 1. Extrude Inward (Rim)
            # This helps avoid shading artifacts at the edge
            bpy.ops.mesh.extrude_region_move(
                TRANSFORM_OT_translate={"value": (0, 0, 0)}
            )
            # Scale inward slightly? Center of mass?
            # Easier: fill() then poke() is standard.
            # But let's try simple Fill first.

            bpy.ops.mesh.fill()

            # 2. Triangulate/Poke
            # The filled face is likely a huge N-Gon.
            # We must triangulate it for it to be "solid" in many engines.
            # Select the new faces (they are selected after fill)

            # Poke Face (Fan Fill) - guarantees triangles centered on a point
            bpy.ops.mesh.poke()

            bpy.ops.object.mode_set(mode="OBJECT")

        fill_holes_robust(tooth_obj)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        fill_holes_robust(obj)

        ensure_active(tooth_obj)
        self.report({"INFO"}, "Tooth extracted. Holes capped (Poke Fill).")
        return {"FINISHED"}


class SMILE_OT_clear_segmentation_data(bpy.types.Operator):
    bl_idname = "smile.clear_segmentation_data"
    bl_label = "Clear Segmentation Data"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            return {"CANCELLED"}

        mesh = obj.data

        # Remove Data
        if "SMILE_TOOTH_ID" in mesh.attributes:
            mesh.attributes.remove(mesh.attributes["SMILE_TOOTH_ID"])

        if "SMILE_VISUAL" in mesh.color_attributes:
            mesh.color_attributes.remove(mesh.color_attributes["SMILE_VISUAL"])

        vg = obj.vertex_groups.get("SMILE_SEGMENTS")
        if vg:
            obj.vertex_groups.remove(vg)

        # Reset Viewport
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.type = "SOLID"
                        space.shading.color_type = "MATERIAL"

        self.report({"INFO"}, "Segmentation data cleared. View reset.")
        return {"FINISHED"}


class SMILE_OT_place_segmentation_seed(bpy.types.Operator):
    """Click to place a starting seed for a specific tooth ID"""

    bl_idname = "smile.place_segmentation_seed"
    bl_label = "Place Tooth Seed"
    bl_options = {"REGISTER", "UNDO"}

    tooth_id: bpy.props.IntProperty(default=0)

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the scan mesh first.")
            return {"CANCELLED"}

        # Update target if set
        if self.tooth_id > 0:
            context.scene.smile_v2.target_tooth_id = self.tooth_id

        tid = context.scene.smile_v2.target_tooth_id

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"SEED MODE T#{tid}: Click to place one seed and finish. Hold Shift+Click for multi-seed. Enter/Space/Esc to finish.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC", "RET", "NUMPAD_ENTER", "SPACE"}:
            return {"FINISHED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            obj = context.view_layer.objects.active
            if not obj or obj.type != "MESH":
                self.report({"ERROR"}, "Active scan mesh missing. Seed mode cancelled.")
                return {"CANCELLED"}
            hit = raycast_from_mouse_to_target(context, event, obj)
            if hit:
                loc, _, _ = hit
                p = context.scene.smile_v2
                tid = p.target_tooth_id

                # Create unique seed marker
                # Allow multiple seeds per tooth (e.g. Buccal/Lingual)
                import time

                ts = int(time.time() * 1000)
                name = f"SEED_T{tid}_{ts}"

                # Use a distinct shape (Diamond/Octahedron)
                sz = p.seed_marker_size
                m = make_marker(
                    name, loc, sz, obj, (0, 1, 0.5, 1.0), shape="ICO", sticky=True
                )
                m["SMILE_LM_TYPE"] = "SEED"
                m["SMILE_LM_TID"] = tid

                # Move to Landmarks collection
                link_to_collection(m, ensure_collection(COL_LM))

                if getattr(event, "shift", False):
                    self.report(
                        {"INFO"},
                        f"Placed seed for Tooth #{tid}. Multi-seed mode: Shift+Click to continue, Enter/Esc to finish.",
                    )
                    return {"RUNNING_MODAL"}
                self.report(
                    {"INFO"}, f"Placed seed for Tooth #{tid}. Seed mode complete."
                )
                return {"FINISHED"}

        return {"PASS_THROUGH"}


class SMILE_OT_clear_segmentation_seeds(bpy.types.Operator):
    """Remove all manual segmentation seeds"""

    bl_idname = "smile.clear_segmentation_seeds"
    bl_label = "Clear Seeds"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        active = context.view_layer.objects.active
        all_seeds = [
            o for o in list(bpy.data.objects) if o.get("SMILE_LM_TYPE") == "SEED"
        ]
        targets = list(all_seeds)
        scoped = []

        # Prefer active-scan scoped clear when possible; fallback to global for legacy scenes.
        if active and active.type == "MESH":
            scoped = [
                s
                for s in all_seeds
                if s.parent == active
                or str(s.get("SMILE_ATTACH_TARGET", "")) == active.name
            ]
            if scoped:
                targets = scoped

        count = 0
        for o in targets:
            delete_object(o)
            count += 1

        if scoped and targets is scoped:
            self.report({"INFO"}, f"Deleted {count} seeds for active scan.")
        else:
            self.report({"INFO"}, f"Deleted {count} seeds (global).")
        return {"FINISHED"}


class SMILE_OT_auto_segmentation(bpy.types.Operator):
    bl_idname = "smile.auto_segmentation"
    bl_label = "Run Auto-Segmentation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a Mesh (Scan).")
            return {"CANCELLED"}

        import numpy as np
        import heapq

        p = context.scene.smile_v2

        # 1. Generate Crevice Map (Dirty Vertex Colors)
        # This is much more robust than local curvature for finding the sulcus
        with SafeMode(obj, "VERTEX_PAINT"):
            # Ensure a color attribute exists
            if not obj.data.vertex_colors:
                obj.data.vertex_colors.new(name="SMILE_CREVICE")

            # Use 'color_dirty_add' to highlight cavities
            # Blur strength 1.0, Iterations 1 is usually good for dental scale
            try:
                bpy.ops.geometry.color_dirty_add(
                    blur_strength=1.0, iterations=1, dirt_angle=math.radians(90)
                )
            except Exception as e:
                self.report({"WARNING"}, f"Dirty color calculation failed: {e}")

        # Access data
        mesh = obj.data
        if not mesh.loop_triangles:
            mesh.calc_loop_triangles()

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        n_verts = len(bm.verts)

        # Read Crevice Map
        # Dirty Colors are stored in loops. We need per-vertex data.
        # Average loop colors to vertex.
        crevice_map = np.ones(n_verts, dtype=np.float32)

        if mesh.vertex_colors.active:
            vcol_data = mesh.vertex_colors.active.data

            # Fast numpy aggregation? Or simpler loop.
            # Blender loop indices
            v_indices = np.zeros(len(mesh.loops), dtype=np.int32)
            mesh.loops.foreach_get("vertex_index", v_indices)

            # Get luminance/brightness (Dirty Color is White on convex, Black/Dark in concave)
            # We want Resistance = 1.0 - Brightness
            # Since vertex colors are RGBA, just take channel 0 (Greyscale)
            loop_colors = np.zeros(len(mesh.loops) * 4, dtype=np.float32)
            vcol_data.foreach_get("color", loop_colors)
            loop_colors = loop_colors.reshape((-1, 4))
            loop_vals = loop_colors[:, 0]  # Red channel is enough for greyscale

            # Aggregate to vertices (max? avg?)
            # Avg is fine.
            # Using bmesh to iterate loops is cleaner logic-wise but slower.
            # Let's assume the loop -> vert mapping.
            # Actually, curvature_resistance logic below iterates vertices.
            # Let's map vertex index to a representative color value.
            # Optimization: Just iterate bmesh loops.

            vert_accum = np.zeros(n_verts, dtype=np.float32)
            vert_count = np.zeros(n_verts, dtype=np.int32)

            # Python loop is slow for dense mesh.
            # But 'foreach_get' + numpy bincount is fast.
            # sum_vals = np.bincount(v_indices, weights=loop_vals, minlength=n_verts)
            # counts = np.bincount(v_indices, minlength=n_verts)
            # avg_vals = np.divide(sum_vals, counts, where=counts!=0)

            sum_vals = np.bincount(v_indices, weights=loop_vals, minlength=n_verts)
            counts = np.bincount(v_indices, minlength=n_verts)
            # Avoid divide by zero
            counts[counts == 0] = 1
            avg_vals = sum_vals / counts
            crevice_map = avg_vals

        # 0. Check Selection (ROI)
        has_selection = False
        selected_indices = set()

        # Check Edit Selection
        for v in bm.verts:
            if v.select:
                selected_indices.add(v.index)

        # Check SMILE_ROI Vertex Group
        vg = obj.vertex_groups.get("SMILE_ROI")
        if vg:
            dvert_lay = bm.verts.layers.deform.verify()
            for v in bm.verts:
                dvert = v[dvert_lay]
                if vg.index in dvert and dvert[vg.index] > 0.01:
                    selected_indices.add(v.index)

        if len(selected_indices) > 0:
            has_selection = True
            self.report(
                {"INFO"}, f"Restricting to {len(selected_indices)} ROI vertices."
            )

        # 1. Curvature Weight (Resistance)
        # Use user-exposed segmentation threshold to tune how aggressively
        # grooves/ridges influence the watershed competition.
        sens = max(0.001, min(0.5, float(p.segmentation_threshold)))
        low_crevice = max(0.05, 0.50 - sens * 2.0)
        high_ridge = min(0.98, 0.70 + sens * 2.0)
        ridge_geo_cut = -max(0.005, sens * 2.5)
        low_resistance = max(0.05, sens * 5.0)
        high_resistance = max(2.0, sens * 250.0)
        ridge_fence = max(20.0, sens * 5000.0)

        curvature_resistance = np.zeros(n_verts, dtype=np.float32)

        for i in range(n_verts):
            if has_selection and i not in selected_indices:
                curvature_resistance[i] = 1000.0
                continue

            # Crevice Map (AO): 0.0 = Crevice, 1.0 = Ridge
            val = crevice_map[i]

            # 1. Accelerate into pockets
            if val < low_crevice:
                # Very low resistance pulls the flood into the sulcus
                resistance = low_resistance
            elif val > high_ridge:
                # Higher resistance on ridges (tops of the gum roll)
                resistance = high_resistance
            else:
                resistance = 1.0

            # 2. Local Geometric Ridge Detection (Gingival Roll)
            v = bm.verts[i]
            neighbors = [e.other_vert(v) for e in v.link_edges]
            if neighbors:
                avg_n = sum((n.co for n in neighbors), Vector()) / len(neighbors)
                # Concavity check (val_geo > 0 is concave, < 0 is convex)
                val_geo = (avg_n - v.co).dot(v.normal)

                if val_geo < ridge_geo_cut:  # Sharp convex ridge (The "Gingival Roll")
                    resistance = ridge_fence  # Hard stop fence

            curvature_resistance[i] = resistance

        # 2. Seeds Setup
        # (0, v_idx, tid) - Priority Queue stores (Cost, VertexIndex, ToothID)
        pq = []
        distances = np.full(n_verts, np.inf, dtype=np.float32)
        labels = np.zeros(n_verts, dtype=np.int32)  # 0 = Unassigned/Gum

        seeded_teeth = set()  # Ensure only one seed per Tooth ID
        arch_pts_local = []

        # 2a. Check for MANUAL SEEDS first
        manual_seeds_all = [
            o for o in bpy.data.objects if o.get("SMILE_LM_TYPE") == "SEED"
        ]
        manual_seeds = list(manual_seeds_all)
        if manual_seeds_all:
            scoped = [
                s
                for s in manual_seeds_all
                if s.parent == obj or str(s.get("SMILE_ATTACH_TARGET", "")) == obj.name
            ]
            # Backward compatibility: if no scoped seeds are tagged, use global legacy behavior.
            if scoped:
                manual_seeds = scoped
        if manual_seeds:
            self.report({"INFO"}, f"Using {len(manual_seeds)} manual seeds.")
            mw_inv = obj.matrix_world.inverted()
            for s_obj in manual_seeds:
                tid = s_obj.get("SMILE_LM_TID", 0)
                if tid == 0:
                    continue

                # Project seed to mesh
                local_loc = mw_inv @ s_obj.location
                res, loc, norm, f_idx = obj.closest_point_on_mesh(local_loc)
                if res:
                    poly = mesh.polygons[f_idx]
                    best_v = min(
                        poly.vertices,
                        key=lambda v_idx: (mesh.vertices[v_idx].co - loc).length,
                    )

                    # Manual seeds ignore ROI check (user placed them explicitly)
                    if distances[best_v] == np.inf:
                        distances[best_v] = 0.0
                        labels[best_v] = tid
                        heapq.heappush(pq, (0.0, best_v, tid))
                        # Record that this tooth is seeded so we don't auto-seed it later
                        seeded_teeth.add(tid)

        # 2b. Fallback to Arch Curve if no manual seeds or to supplement
        # (Rest of the previous arch curve logic remains...)
        active_curves = []
        for d in [DOMAIN_MAX, DOMAIN_MAN]:
            c_obj = bpy.data.objects.get(arch_curve_name(d))
            if c_obj:
                dist = (c_obj.location - obj.location).length
                active_curves.append((dist, d, c_obj))

        active_curves.sort(key=lambda x: x[0])

        for _, d, c_obj in active_curves:
            pts = curve_world_points(c_obj)
            if pts:
                if pts[0].x > pts[-1].x:
                    pts.reverse()
                mat_inv = obj.matrix_world.inverted()

                for p in pts:
                    arch_pts_local.append(mat_inv @ p)

                num_teeth = 16
                for k in range(num_teeth):
                    tid = (1 + k) if d == DOMAIN_MAX else (32 - k)
                    if tid in seeded_teeth:
                        continue

                    t_val = (k + 0.5) / num_teeth
                    idx_f = t_val * (len(pts) - 1)
                    i_b = int(idx_f)
                    i_n = min(i_b + 1, len(pts) - 1)
                    pt_world = pts[i_b].lerp(pts[i_n], idx_f - i_b)

                    res, loc, norm, f_idx = obj.closest_point_on_mesh(
                        mat_inv @ pt_world
                    )
                    if res:
                        poly = mesh.polygons[f_idx]
                        best_v = min(
                            poly.vertices,
                            key=lambda v_idx: (mesh.vertices[v_idx].co - loc).length,
                        )

                        # Validate seed is inside ROI
                        # If NOT in ROI, search locally for a vertex that IS in ROI
                        if has_selection and best_v not in selected_indices:
                            found_in_roi = False
                            local_q = [best_v]
                            seen_local = {best_v}

                            for _ in range(50):  # Search radius approx 5-10mm
                                if not local_q:
                                    break
                                lv = local_q.pop(0)

                                if lv in selected_indices:
                                    best_v = lv
                                    found_in_roi = True
                                    break

                                v_obj = bm.verts[lv]
                                for le in v_obj.link_edges:
                                    ln = le.other_vert(v_obj).index
                                    if ln not in seen_local:
                                        seen_local.add(ln)
                                        local_q.append(ln)

                            if not found_in_roi:
                                # Still failed to find ROI nearby
                                continue

                        # OPTIMIZATION: Groove avoidance using Crevice Map
                        # If we land on a dark spot (val < 0.5), move to lighter spot
                        curr_val = crevice_map[best_v]
                        if curr_val < 0.6:  # In or near groove
                            local_q = [best_v]
                            seen_local = {best_v}
                            best_local_v = best_v
                            max_val = curr_val

                            for _ in range(30):
                                if not local_q:
                                    break
                                lv = local_q.pop(0)
                                if crevice_map[lv] > max_val:
                                    max_val = crevice_map[lv]
                                    best_local_v = lv
                                    if max_val > 0.8:
                                        break  # Found flat area

                                v_obj = bm.verts[lv]
                                for le in v_obj.link_edges:
                                    ln = le.other_vert(v_obj).index
                                    if ln not in seen_local:
                                        seen_local.add(ln)
                                        local_q.append(ln)
                            best_v = best_local_v

                        if distances[best_v] == np.inf:
                            distances[best_v] = 0.0
                            labels[best_v] = tid
                            heapq.heappush(pq, (0.0, best_v, tid))
                            seeded_teeth.add(tid)

        if not seeded_teeth:
            self.report(
                {"ERROR"},
                "No teeth seeds found! Check Arch Curve alignment or ROI Mask coverage.",
            )
            bm.free()
            return {"CANCELLED"}

        if not pq and not has_selection:
            self.report({"ERROR"}, "No Arch Tracer found.")
            bm.free()
            return {"CANCELLED"}

        # 3. Gum Seeds (Background seeds)
        if arch_pts_local:
            arch_kd = KDTree(len(arch_pts_local))
            for i, p in enumerate(arch_pts_local):
                arch_kd.insert(p, i)
            arch_kd.balance()

            sample_rate = 100
            gum_penalty = 500.0

            for i in range(0, n_verts, sample_rate):
                if has_selection and i not in selected_indices:
                    continue

                co = bm.verts[i].co
                _, idx, dist = arch_kd.find(co)

                if dist > 18.0:
                    if distances[i] == np.inf:
                        distances[i] = gum_penalty
                        labels[i] = 0
                        heapq.heappush(pq, (gum_penalty, i, 0))
                        curvature_resistance[i] = 1.0

        # 4. Competitive Watershed (Dijkstra)
        while pq:
            curr_dist, curr_idx, curr_tid = heapq.heappop(pq)
            if curr_dist > distances[curr_idx]:
                continue

            v = bm.verts[curr_idx]
            for e in v.link_edges:
                n = e.other_vert(v)
                ni = n.index

                if has_selection and ni not in selected_indices:
                    continue

                dist_step = (v.co - n.co).length
                avg_resistance = (
                    curvature_resistance[v.index] + curvature_resistance[ni]
                ) * 0.5
                new_dist = curr_dist + (dist_step * avg_resistance)

                if new_dist < distances[ni]:
                    distances[ni] = new_dist
                    labels[ni] = curr_tid
                    heapq.heappush(pq, (new_dist, ni, curr_tid))

        # 4.5 Label Dilation (Expansion)
        # Ensure we reach the very bottom of crevices and slightly beyond.
        new_labels = labels.copy()
        for i in range(n_verts):
            if labels[i] == 0:  # Only expand into gum/background
                v = bm.verts[i]
                neighbor_labels = [labels[e.other_vert(v).index] for e in v.link_edges]
                # If majority of neighbors are a specific tooth, claim it
                # Or just any tooth neighbor if we want aggressive expansion
                tooth_neighbors = [l for l in neighbor_labels if l > 0]
                if tooth_neighbors:
                    from collections import Counter

                    most_common = Counter(tooth_neighbors).most_common(1)[0][0]
                    new_labels[i] = most_common
        labels = new_labels

        # Clean up vertex colors if we made them
        if "SMILE_CREVICE" in mesh.vertex_colors:
            mesh.vertex_colors.remove(mesh.vertex_colors["SMILE_CREVICE"])

        # 5. Persistence & Visualize
        mesh.update()

        if "SMILE_TOOTH_ID" in mesh.attributes:
            mesh.attributes.remove(mesh.attributes["SMILE_TOOTH_ID"])
        attr = mesh.attributes.new(name="SMILE_TOOTH_ID", type="INT", domain="POINT")

        if len(attr.data) != len(labels):
            self.report({"WARNING"}, "Mismatch. Viz skipped.")
            bm.free()
            return {"FINISHED"}

        attr.data.foreach_set("value", labels)

        # Save to Vertex Group for extraction
        vg_mask = obj.vertex_groups.get("SMILE_SEGMENTS") or obj.vertex_groups.new(
            name="SMILE_SEGMENTS"
        )

        # We only add vertices that are NOT gum (label > 0)
        obj.vertex_groups.remove(vg_mask)
        vg_mask = obj.vertex_groups.new(name="SMILE_SEGMENTS")

        # Iterate to add
        for i in range(n_verts):
            if labels[i] > 0:
                vg_mask.add([i], 1.0, "REPLACE")

        # Visualize Colors
        if "SMILE_VISUAL" in mesh.color_attributes:
            mesh.color_attributes.remove(mesh.color_attributes["SMILE_VISUAL"])

        try:
            vcol = mesh.color_attributes.new(
                name="SMILE_VISUAL", type="BYTE_COLOR", domain="CORNER"
            )
        except Exception:
            vcol = mesh.vertex_colors.new(name="SMILE_VISUAL")

        n_loops = len(mesh.loops)
        if len(vcol.data) == n_loops:
            v_indices = np.zeros(n_loops, dtype=np.int32)
            mesh.loops.foreach_get("vertex_index", v_indices)
            loop_labels = labels[v_indices]

            col_table = np.zeros((33, 4), dtype=np.float32)
            col_table[0] = [0.1, 0.1, 0.1, 1.0]  # Grey Gum
            for i in range(1, 33):
                import colorsys

                rgb = colorsys.hsv_to_rgb((i * 0.13) % 1.0, 0.8, 1.0)
                col_table[i] = [rgb[0], rgb[1], rgb[2], 1.0]

            final_colors = col_table[loop_labels]
            vcol.data.foreach_set("color", final_colors.flatten())

            mesh.attributes.active_color = vcol

            # Set Viewport to Vertex Color
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    for space in area.spaces:
                        if space.type == "VIEW_3D":
                            space.shading.type = "SOLID"
                            space.shading.color_type = "VERTEX"

        bm.free()

        # Restore Weight Paint Mode if we started there?
        # Actually usually run from Object/Weight Paint.
        # But we switched to Vertex Paint at start (SafeMode).
        # SafeMode handles restoring original mode.

        self.report({"INFO"}, "Segmentation Done (Watershed).")
        return {"FINISHED"}


class SMILE_OT_clear_arch(bpy.types.Operator):
    bl_idname = "smile.clear_arch"
    bl_label = "Clear Arch Points + Markers"
    bl_options = {"REGISTER", "UNDO"}

    domain: bpy.props.EnumProperty(
        items=[(DOMAIN_MAX, "MAX", ""), (DOMAIN_MAN, "MAN", "")], default=DOMAIN_MAX
    )
    curve_role: bpy.props.EnumProperty(
        name="Curve",
        items=[
            (ARCH_CURVE_OCCLUSAL, "Occlusal", ""),
            (ARCH_CURVE_CERVICAL, "Cervical", ""),
        ],
        default=ARCH_CURVE_OCCLUSAL,
    )

    def execute(self, context):
        set_arch_points(context.scene, self.domain, [], self.curve_role)
        clear_arch_markers(self.domain, self.curve_role)
        obj = bpy.data.objects.get(arch_curve_name(self.domain, self.curve_role))
        if obj:
            delete_object(obj)
        self.report({"INFO"}, f"Cleared {self.domain} {self.curve_role.lower()} arch.")
        return {"FINISHED"}


class SMILE_OT_clear_all_arch(bpy.types.Operator):
    bl_idname = "smile.clear_all_arch"
    bl_label = "Clear All Arch Data"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for d in [DOMAIN_MAX, DOMAIN_MAN]:
            for role in [ARCH_CURVE_OCCLUSAL, ARCH_CURVE_CERVICAL]:
                set_arch_points(context.scene, d, [], role)
                clear_arch_markers(d, role)
                obj = bpy.data.objects.get(arch_curve_name(d, role))
                if obj:
                    delete_object(obj)
        self.report({"INFO"}, "Cleared all arch data.")
        return {"FINISHED"}


class SMILE_OT_rebuild_arch_curves_from_points(bpy.types.Operator):
    bl_idname = "smile.rebuild_arch_curves"
    bl_label = "Rebuild Arch Curves"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        rebuilt = 0
        missing = 0
        for d in [DOMAIN_MAX, DOMAIN_MAN]:
            for role in [ARCH_CURVE_OCCLUSAL, ARCH_CURVE_CERVICAL]:
                obj = ensure_arch_curve_from_saved_points(
                    scene, d, role, force_rebuild=True
                )
                if obj and obj.type == "CURVE":
                    rebuilt += 1
                else:
                    missing += 1
        if rebuilt <= 0:
            self.report(
                {"WARNING"},
                "No arch curves rebuilt. Trace MAX/MAN occlusal/cervical first.",
            )
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Rebuilt {rebuilt} arch curve(s) from saved points (missing={missing}).",
        )
        return {"FINISHED"}


class SMILE_OT_mirror_biocopy(bpy.types.Operator):
    """Mirror active tooth to create a contralateral copy (e.g. #8 -> #9)"""

    bl_idname = "smile.mirror_biocopy"
    bl_label = "Mirror Biocopy"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a tooth first.")
            return {"CANCELLED"}

        tid = parse_tooth_id_from_name(obj.name)
        target_id = 0

        if tid:
            # Universal System Logic
            if 1 <= tid <= 16:
                target_id = 17 - tid
            elif 17 <= tid <= 32:
                target_id = 49 - tid

        new_name = f"Tooth_{target_id}" if target_id > 0 else f"{obj.name}_Mirrored"

        # Duplicate
        dup = obj.copy()
        dup.data = obj.data.copy()
        dup.name = new_name
        link_to_collection(dup, ensure_collection(COL_TEETH))

        # Mirror Geometry (Scale X -1)
        # We want to mirror across World X axis (Midline)
        # Simple method: Negate World Location X and World Scale X?
        # If object has rotation, scaling -1 on X local might not be global mirror.

        # Reliable Global Mirror:
        # Apply Transform first to reset rotation?
        # Better: Use mirror modifier then apply?
        # Or: Matrix math.

        ensure_active(dup)

        # Reset Parent for clean transform
        if dup.parent:
            mw = dup.matrix_world.copy()
            dup.parent = None
            dup.matrix_world = mw

        # 1. Flip Location X
        loc = dup.location
        dup.location.x = -loc.x

        # 2. Flip Scale X (Local)
        # This flips the mesh itself.
        # But we need to handle rotation.
        # If rotation is (0,0,0), scale.x *= -1 works.
        # If rotation is present, we must check.
        # Let's apply rotation first?
        # Ideally, we want a visual mirror.

        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        dup.scale.x *= -1
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        # Fix Normals
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")

        # Auto-Rig new tooth
        # create_lattice_rig_for_tooth(dup) # DISABLED

        self.report({"INFO"}, f"Created {new_name}")
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

        # Sort Imported Teeth
        imported = sort_teeth_by_id(imported)

        # 1. ROI Analysis & Temp Curve
        temp_curve = None
        scale_factor = 1.0

        active = context.view_layer.objects.active
        if active and active.type == "MESH":
            vg = active.vertex_groups.get("SMILE_ROI")
            if vg:
                temp_curve = create_arch_from_roi(active, "SMILE_ROI")

                if temp_curve:
                    # Calculate Scale Match
                    # ROI Width
                    pts = curve_world_points(temp_curve)
                    roi_len = 0.0
                    for i in range(len(pts) - 1):
                        roi_len += (pts[i + 1] - pts[i]).length

                    # Teeth Width (Sum of bounding box X-widths)
                    teeth_len = 0.0
                    for t in imported:
                        # Ensure params to get dimensions?
                        # Or just use raw dimensions.X
                        # Assuming aligned to axes. If not, use radius.
                        # Using radius * 2 is safer if orientation is unknown.
                        # But standard lib usually X is width.
                        teeth_len += t.dimensions.x

                    if teeth_len > 0:
                        scale_factor = roi_len / teeth_len
                        # Dampen scale slightly if gaps needed?
                        # Let's trust the ratio.

        # 2. Process Teeth
        for o in imported:
            link_to_collection(o, ensure_collection(COL_TEETH))
            ensure_tooth_params(o)

            # Apply Scale
            if scale_factor != 1.0:
                o.scale *= scale_factor
                # Apply scale to data? No, keep as object scale for now.
                # But distribute uses bounding box which updates with scale.

        # 3. Distribute
        if temp_curve:
            try:
                # Force scene update for curve
                bpy.context.view_layer.update()
                distribute_teeth_width_aware(
                    temp_curve, imported, gap_mm=0.0
                )  # Gap handled by scale?

                # Cleanup Temp Curve
                bpy.data.objects.remove(temp_curve, do_unlink=True)

            except Exception as e:
                self.report({"WARNING"}, f"Distribution failed: {e}")

        # Fallback: If no ROI, just center them (removed per request)
        # else:
        #    pass # Leave at origin or imported location

        self.report(
            {"INFO"}, f"Imported {len(imported)} teeth. ROI Scale: {scale_factor:.2f}"
        )
        return {"FINISHED"}


class SMILE_OT_layout_teeth_width_aware(bpy.types.Operator):
    bl_idname = "smile.layout_teeth_width_aware"
    bl_label = "Layout Teeth (Width-aware) on MAX Arch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        curve = bpy.data.objects.get(arch_curve_name(DOMAIN_MAX))
        if not curve or curve.type != "CURVE":
            self.report({"ERROR"}, "No ARCH_MAX_CURVE. Trace MAX arch and press T.")
            return {"CANCELLED"}

        teeth = sort_teeth_by_id(tooth_objects_in_collection())
        if not teeth:
            self.report(
                {"ERROR"}, "No teeth with #xx found in names in Teeth collection."
            )
            return {"CANCELLED"}

        try:
            distribute_teeth_width_aware(
                curve, teeth, gap_mm=p.tooth_gap_mm, bridge_mode=False
            )
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
        sel = [
            o
            for o in context.selected_objects
            if o.type == "MESH" and (o in col.objects)
        ]
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
            pts = [Vector((0, 0, 0)), Vector((1, 0, 0))]
        occlusal_up = Vector((0, 0, 1))

        col = ensure_collection(COL_TEETH)
        sel = [
            o
            for o in context.selected_objects
            if o.type == "MESH" and (o in col.objects)
        ]
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


# ============================================================
# P1 SEGMENTATION CODE (Extracted from monolith)
# ============================================================

# ============================================================
# CLASSES LIST
# ============================================================


CLASSES = [
    SMILE_OT_clear_face_landmarks,
    SMILE_OT_place_named_landmark,
    SMILE_OT_create_guide_line,
    SMILE_OT_remove_arch_markers_only,
    SMILE_OT_golden_ruler,
    SMILE_OT_delete_golden_ruler,
    SMILE_OT_spawn_parallel_guide,
    SMILE_OT_remove_all_guides,
    SMILE_OT_align_ruler_to_pupils,
    SMILE_OT_draw_lip_line,
    SMILE_OT_update_lip_curve,
    SMILE_OT_clear_lip_markers,
    SMILE_OT_generate_smile_arc,
    SMILE_OT_verify_golden_orientation,
    SMILE_OT_upright_model,
    SMILE_OT_lock_rotation_axis,
    SMILE_OT_extract_segments,
    SMILE_OT_select_segment_under_mouse,
    SMILE_OT_manual_extract_watertight,
    SMILE_OT_clear_segmentation_data,
    SMILE_OT_place_segmentation_seed,
    SMILE_OT_clear_segmentation_seeds,
    SMILE_OT_auto_segmentation,
    SMILE_OT_clear_arch,
    SMILE_OT_clear_all_arch,
    SMILE_OT_rebuild_arch_curves_from_points,
    SMILE_OT_mirror_biocopy,
    SMILE_OT_import_teeth_folder,
    SMILE_OT_layout_teeth_width_aware,
    SMILE_OT_toggle_ghost_selected,
    SMILE_OT_apply_tweak_selected,
]


# ============================================================
# UI DRAWING FUNCTION
# ============================================================


def draw_analysis_tab(context, layout, props):
    """Draw the ANALYSIS tab UI."""
    try:
        box = layout.box()
        box.label(text="Landmarks", icon="LAYER_USED")
        row = box.row(align=True)
        row.operator("smile.place_named_landmark", text="Place Point", icon="PLUS")
        row.operator("smile.clear_face_landmarks", text="Clear", icon="TRASH")

        box.separator()
        box.label(text="Golden Ruler", icon="CURVE")
        row = box.row(align=True)
        row.operator("smile.golden_ruler", text="Draw Ruler", icon="COPYDOWN")
        row.operator("smile.delete_golden_ruler", text="Delete", icon="TRASH")
        row = box.row(align=True)
        row.operator(
            "smile.align_ruler_to_pupils", text="Align to Pupils", icon="SNAP_ON"
        )
        box.prop(props, "golden_arch_depth")
        box.prop(props, "golden_ruler_width_scale")

        box.separator()
        box.label(text="Lip Line", icon="CURVE_DATA")
        row = box.row(align=True)
        row.operator("smile.draw_lip_line", text="Draw", icon="GREASEPENCIL")
        row.operator("smile.update_lip_curve", text="Update", icon="FILE_REFRESH")
        row = box.row(align=True)
        row.operator("smile.clear_lip_markers", text="Clear Markers", icon="CANCEL")
        row.operator("smile.generate_smile_arc", text="Generate Arc", icon="MESH_DATA")

    except Exception as e:
        layout.label(text=f"[analysis_03] Error: {e}")


def register():
    """Register all operators in this module."""
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister all operators in this module."""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
