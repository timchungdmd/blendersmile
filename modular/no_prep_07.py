"""BlenderSmile NO_PREP Tab Module"""

import bpy
import os
import math
import json
import traceback
from bpy.props import StringProperty, IntProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
)
from mathutils import Vector, Matrix

COL_TEETH = "Teeth"
COL_PREVIEW = "SmilePreview"
COL_ARCH = "SmileArch"
DOMAIN_FACE = "FACE"
DOMAIN_PHOTO = "PHOTO"


def _view3d_utils():
    """Get View3D utilities for ray casting."""
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    return space
    return None


def lm_name(domain: str, idx: int):
    """Generate landmark object name."""
    return f"{domain}_LM_{int(idx):02d}"


def _active_photo_slot(scene):
    """Get the active photo slot from scene properties."""
    p = scene.smile_v2
    if not hasattr(p, "photo_slots") or len(p.photo_slots) == 0:
        return None
    idx = int(p.active_photo_slot_index)
    if idx < 0 or idx >= len(p.photo_slots):
        idx = 0
        p.active_photo_slot_index = 0
    return p.photo_slots[idx]


def _get_or_load_image(slot):
    """Load image from photo slot."""
    if not slot:
        return None
    img = None
    img_name = getattr(slot, "image_name", "") or getattr(slot, "image_datablock", "")
    img_path = getattr(slot, "image_path", "") or getattr(slot, "filepath", "")

    if img_name:
        img = bpy.data.images.get(img_name)

    if img is None and img_path:
        try:
            img = bpy.data.images.load(img_path, check_existing=True)
            if hasattr(slot, "image_name"):
                slot.image_name = img.name
        except Exception:
            img = None

    if img is not None:
        try:
            if hasattr(slot, "width"):
                slot.width = int(img.size[0])
            if hasattr(slot, "height"):
                slot.height = int(img.size[1])
        except Exception:
            pass
    return img


def _ensure_camera(slot):
    """Create or get camera for photo slot."""
    cam = None
    if slot and slot.camera_name:
        cam = bpy.data.objects.get(slot.camera_name)
    if cam is None:
        cam_data = bpy.data.cameras.new(f"{slot.name}_CAM_DATA")
        cam_data.lens = 85.0
        cam = bpy.data.objects.new(f"{slot.name}_CAM", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        slot.camera_name = cam.name
    else:
        if cam.type == "CAMERA" and cam.data.lens != 85.0:
            cam.data.lens = 85.0
    return cam


def _set_camera_background(cam_obj, img, alpha=0.65):
    """Set camera background image."""
    if cam_obj is None or cam_obj.type != "CAMERA" or img is None:
        return
    camd = cam_obj.data
    try:
        camd.show_background_images = True
    except Exception:
        pass
    try:
        for b in list(camd.background_images):
            if b.image and b.image.name == img.name:
                b.alpha = float(alpha)
                b.display_depth = "FRONT"
                return
        b = camd.background_images.new()
        b.image = img
        b.alpha = float(alpha)
        b.display_depth = "FRONT"
    except Exception:
        pass


def _ensure_photo_plane(slot, cam_obj, img, alpha=0.65, distance_mm=800.0):
    """Create/update photo plane parented to camera."""
    if cam_obj is None or img is None:
        return None

    plane = bpy.data.objects.get(slot.plane_name) if slot.plane_name else None
    if plane is None:
        plane = bpy.data.objects.get("Photo_Mockup_Plane")
        if plane is None:
            bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
            plane = bpy.context.active_object
            plane.name = "Photo_Mockup_Plane"
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.subdivide(number_cuts=30)
            bpy.ops.object.mode_set(mode="OBJECT")
        slot.plane_name = plane.name

    mw = plane.matrix_world.copy()
    plane.parent = cam_obj
    plane.matrix_parent_inverse = cam_obj.matrix_world.inverted()
    plane.matrix_world = mw

    d = float(distance_mm) / 1000.0
    plane.location = (0.0, 0.0, -d)

    w = max(int(slot.width), 1)
    h = max(int(slot.height), 1)
    aspect = w / h
    photo_scale_percent = getattr(slot, "photo_scale_percent", 100.0)
    scale_factor = photo_scale_percent / 100.0
    target_scale = (aspect * scale_factor, 1.0 * scale_factor, 1.0)
    plane.scale = target_scale

    mat = bpy.data.materials.get(f"{slot.name}_PHOTO_MAT")
    if mat is None:
        mat = bpy.data.materials.new(f"{slot.name}_PHOTO_MAT")
        mat.use_nodes = True
        mat.blend_method = "BLEND"
        try:
            mat.shadow_method = "NONE"
        except Exception:
            pass

    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()

    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-500, 0)
    tex.image = img
    emit = nodes.new("ShaderNodeEmission")
    emit.location = (-200, 0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (-200, -200)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (50, -50)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, -50)

    links.new(tex.outputs["Color"], emit.inputs["Color"])
    mix.inputs[0].default_value = float(alpha)
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emit.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    if plane.data.materials:
        plane.data.materials[0] = mat
    else:
        plane.data.materials.append(mat)

    plane.show_in_front = True
    try:
        plane.display_type = "SOLID"
    except Exception:
        pass
    return plane


def indices_in_domain(domain: str):
    """Get all landmark indices for a domain."""
    inds = set()
    for o in bpy.data.objects:
        if o.get("SMILE_LM_DOMAIN") == domain and o.get("SMILE_LM_INDEX") is not None:
            inds.add(int(o["SMILE_LM_INDEX"]))

    if domain == DOMAIN_PHOTO:
        try:
            scene = bpy.context.scene
            slot = _active_photo_slot(scene)
            if slot:
                for lm in slot.landmarks:
                    inds.add(int(lm.idx))
        except Exception:
            pass
    return inds


def get_landmark_obj(domain: str, idx: int):
    """Get landmark object by domain and index."""
    return bpy.data.objects.get(lm_name(domain, idx))


def next_index_fill_missing(domain_a: str, domain_b: str, active_domain: str = None):
    """Find next available index, filling gaps."""
    a = indices_in_domain(domain_a)
    b = indices_in_domain(domain_b)
    if not a and not b:
        return 1
    max_check = (max(a.union(b)) + 1) if (a or b) else 1
    for i in range(1, max_check + 2):
        if not (i in a and i in b):
            if active_domain == domain_a and i in a:
                continue
            if active_domain == domain_b and i in b:
                continue
            return i
    return max_check + 1


def choose_next_pair_index(
    props, domain_a: str, domain_b: str, active_domain: str = None
):
    """Choose next landmark index based on mode."""
    if props.lm_lock_index:
        return int(props.lm_index_override)
    if props.lm_index_mode == "CONTINUE":
        inds = indices_in_domain(active_domain) if active_domain else set()
        return max(inds) + 1 if inds else 1
    return next_index_fill_missing(domain_a, domain_b, active_domain)


def make_marker(
    name,
    world_location,
    size,
    target_obj=None,
    rgba=(1, 0, 0, 1),
    shape="SPHERE",
    sticky=False,
):
    """Create a visual marker object."""
    bpy.ops.mesh.primitive_uv_sphere_add(radius=size, segments=16, ring_count=8)
    marker = bpy.context.active_object
    marker.name = name
    marker.location = world_location

    if target_obj and sticky:
        mod = marker.modifiers.new(name="Shrinkwrap", type="SHRINKWRAP")
        mod.target = target_obj
        mod.wrap_method = "NEAREST_VERTEX"

    mat = bpy.data.materials.new(name=f"{name}_Mat")
    mat.diffuse_color = rgba
    if marker.data.materials:
        marker.data.materials[0] = mat
    else:
        marker.data.materials.append(mat)

    return marker


def procrustes_solver(src_pts_list, dst_pts_list, with_scaling=True):
    """Compute optimal rigid transformation mapping src_pts to dst_pts."""
    import numpy as np

    if len(src_pts_list) != len(dst_pts_list) or len(src_pts_list) < 3:
        raise ValueError(f"Need 3+ matching points. Found {len(src_pts_list)}")

    P = np.array([list(v) for v in src_pts_list])
    Q = np.array([list(v) for v in dst_pts_list])

    centroid_P = np.mean(P, axis=0)
    centroid_Q = np.mean(Q, axis=0)

    P_centered = P - centroid_P
    Q_centered = Q - centroid_Q

    scale = 1.0
    if with_scaling:
        rms_P = np.sqrt(np.sum(P_centered**2) / len(P))
        rms_Q = np.sqrt(np.sum(Q_centered**2) / len(Q))
        if rms_P > 1e-8:
            scale = rms_Q / rms_P

    H = np.dot(P_centered.T, Q_centered)
    U, S, Vt = np.linalg.svd(H)
    R = np.dot(Vt.T, U.T)

    if np.linalg.det(R) < 0:
        Vt[2, :] *= -1
        R = np.dot(Vt.T, U.T)

    t = centroid_Q - scale * np.dot(R, centroid_P)

    R_blender = Matrix(R.tolist())
    T_blender = Vector(t.tolist())

    return R_blender, T_blender, scale


def _json_obj(value, default=None):
    """Parse JSON string or return default."""
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, dict):
            return parsed
        return default
    except Exception:
        return default


def _mesh_signature(obj):
    """Generate mesh signature for change detection."""
    import hashlib

    if not obj or obj.type != "MESH":
        return ""
    n = len(obj.data.vertices)
    m = len(obj.data.polygons)
    bb = [Vector(c) for c in obj.bound_box] if obj.bound_box else [Vector((0, 0, 0))]
    mn = Vector((min(c.x for c in bb), min(c.y for c in bb), min(c.z for c in bb)))
    mx = Vector((max(c.x for c in bb), max(c.y for c in bb), max(c.z for c in bb)))
    payload = f"{obj.name}|{n}|{m}|{mn.x:.6f}|{mn.y:.6f}|{mn.z:.6f}|{mx.x:.6f}|{mx.y:.6f}|{mx.z:.6f}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _step_gate_error(context, required_step: int, action_label: str):
    """Check if current step allows the action."""
    scene = context.scene if context else None
    p = scene.smile_v2 if scene else None
    if not p:
        return None
    current = int(getattr(p, "design_step", 1))
    if not getattr(p, "enforce_step_lock", False):
        return None
    if current < int(required_step):
        return f"{action_label} requires Step {int(required_step)}+ (current: Step {current})."
    return None


def _set_min_design_step(props, step: int):
    """Set minimum design step."""
    tgt = max(1, min(6, int(step)))
    cur = int(getattr(props, "design_step", 1))
    if tgt > cur:
        props.design_step = str(tgt)


def _ui_fold_header(layout, props, prop_name, label, icon="NONE"):
    """Draw collapsible section header."""
    is_open = bool(getattr(props, prop_name, False))
    tri = "TRIA_DOWN" if is_open else "TRIA_RIGHT"
    row = layout.row(align=True)
    op = row.operator("wm.context_toggle", text=label, icon=tri, emboss=False)
    op.data_path = f"scene.smile_v2.{prop_name}"
    if icon and icon != "NONE":
        row.label(text="", icon=icon)
    return is_open


# ============================================================
# PHOTO PnP LANDMARK OPERATORS
# ============================================================


class SMILE_OT_AddLandmarkPair(bpy.types.Operator):
    """Click on scan to place 3D landmark, then click on photo to place paired 2D landmark"""

    bl_idname = "smile.add_landmark_pair"
    bl_label = "Add Landmark Pair"
    bl_options = {"REGISTER", "UNDO"}

    stage: StringProperty(default="3d")
    landmark_num: IntProperty(default=1)
    marker_3d: StringProperty(default="")
    scan_obj_name: StringProperty(default="")

    def invoke(self, context, event):
        existing_nums = []
        for obj in bpy.data.objects:
            if obj.name.startswith("PNP_3D_") or obj.name.startswith("PNP_IMG_"):
                try:
                    num = int(obj.name.split("_")[-1])
                    existing_nums.append(num)
                except ValueError:
                    pass

        self.landmark_num = 1
        if existing_nums:
            self.landmark_num = max(existing_nums) + 1

        scan_mesh = None
        candidates = []
        for obj in bpy.data.objects:
            if (
                obj.type == "MESH"
                and "Photo_Mockup" not in obj.name
                and not obj.name.startswith("PNP_")
            ):
                if obj.data and len(obj.data.vertices) > 0:
                    bbox = obj.bound_box
                    min_corner = Vector(bbox[0])
                    max_corner = Vector(bbox[6])
                    size = (max_corner - min_corner).length
                    candidates.append((obj, size, len(obj.data.vertices)))

        if not candidates:
            self.report({"ERROR"}, "No scan mesh found. Import scan first.")
            return {"CANCELLED"}

        scan_mesh = max(candidates, key=lambda x: x[2])[0]
        self.scan_obj_name = scan_mesh.name

        photo_plane = bpy.data.objects.get("Photo_Mockup_Plane")
        if not photo_plane:
            self.report({"ERROR"}, "Photo plane not found. Import photo first.")
            return {"CANCELLED"}

        self.stage = "3d"
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            f"STEP 1/2: Click on SCAN to place 3D landmark #{self.landmark_num:02d}",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        sz = 0.05
        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self.stage == "2d" and self.marker_3d:
                obj_3d = bpy.data.objects.get(self.marker_3d)
                if obj_3d:
                    bpy.data.objects.remove(obj_3d, do_unlink=True)
            self.report({"INFO"}, "Cancelled landmark placement")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()

            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

            if self.stage == "3d":
                scan_obj = bpy.data.objects.get(self.scan_obj_name)
                if not scan_obj:
                    return {"CANCELLED"}

                depsgraph = context.evaluated_depsgraph_get()
                scan_eval = scan_obj.evaluated_get(depsgraph)
                mw_inv = scan_eval.matrix_world.inverted()
                ray_origin_local = mw_inv @ ray_origin
                ray_dir_local = mw_inv.to_3x3() @ ray_dir

                success, location, normal, index = scan_eval.ray_cast(
                    ray_origin_local, ray_dir_local, distance=10000.0
                )

                if success:
                    loc_world = scan_obj.matrix_world @ location
                    sz = 0.05
                    marker_3d = make_marker(
                        name=f"PNP_3D_{self.landmark_num:02d}",
                        world_location=loc_world,
                        size=sz,
                        target_obj=scan_obj,
                        rgba=(1, 0, 0, 1),
                        shape="SPHERE",
                        sticky=True,
                    )
                    marker_3d.show_name = True
                    marker_3d["original_position_local"] = location.copy()
                    marker_3d["target_scan_name"] = scan_obj.name
                    self.marker_3d = marker_3d.name

                    self.stage = "2d"
                    self.report(
                        {"INFO"},
                        f"STEP 2/2: Click on PHOTO to place 2D landmark #{self.landmark_num:02d}",
                    )
                else:
                    self.report(
                        {"WARNING"}, "Missed the scan mesh. Click on the 3D surface."
                    )

            elif self.stage == "2d":
                photo_plane = bpy.data.objects.get("Photo_Mockup_Plane")
                if not photo_plane:
                    return {"CANCELLED"}

                depsgraph = context.evaluated_depsgraph_get()
                photo_eval = photo_plane.evaluated_get(depsgraph)
                mw_inv = photo_eval.matrix_world.inverted()
                ray_origin_local = mw_inv @ ray_origin
                ray_dir_local = mw_inv.to_3x3() @ ray_dir

                success, location, normal, index = photo_eval.ray_cast(
                    ray_origin_local, ray_dir_local, distance=10000.0
                )

                if success:
                    loc_world = photo_plane.matrix_world @ location
                    marker_2d = make_marker(
                        name=f"PNP_IMG_{self.landmark_num:02d}",
                        world_location=loc_world,
                        size=sz,
                        target_obj=photo_plane,
                        rgba=(0, 1, 0, 1),
                        shape="SPHERE",
                        sticky=True,
                    )
                    marker_2d.show_name = True
                    marker_2d["landmark_pair_id"] = self.landmark_num

                    self.report(
                        {"INFO"}, f"Placed paired landmarks #{self.landmark_num:02d}"
                    )
                    return {"FINISHED"}
                else:
                    self.report({"WARNING"}, "Missed the photo plane.")

        return {"RUNNING_MODAL"}


class SMILE_OT_ShowAlignmentLines(bpy.types.Operator):
    """Show alignment lines connecting paired landmarks"""

    bl_idname = "smile.show_alignment_lines"
    bl_label = "Show Alignment Lines"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for obj in list(bpy.data.objects):
            if obj.name.startswith("ALIGNMENT_LINE_"):
                bpy.data.objects.remove(obj, do_unlink=True)

        pairs = {}
        for obj in bpy.data.objects:
            if obj.name.startswith("PNP_3D_"):
                num = obj.name.split("_")[-1]
                if num not in pairs:
                    pairs[num] = {}
                pairs[num]["3d"] = obj
            elif obj.name.startswith("PNP_IMG_"):
                num = obj.name.split("_")[-1]
                if num not in pairs:
                    pairs[num] = {}
                pairs[num]["2d"] = obj

        count = 0
        for num, pair in pairs.items():
            if "3d" in pair and "2d" in pair:
                curve_data = bpy.data.curves.new(f"ALIGNMENT_LINE_{num}", "CURVE")
                curve_data.dimensions = "3D"
                spline = curve_data.splines.new("POLY")
                spline.points.add(1)
                spline.points[0].co = (*pair["3d"].matrix_world.translation, 1)
                spline.points[1].co = (*pair["2d"].matrix_world.translation, 1)

                curve_obj = bpy.data.objects.new(f"ALIGNMENT_LINE_{num}", curve_data)
                context.collection.objects.link(curve_obj)
                curve_data.bevel_depth = 0.02

                mat = bpy.data.materials.new(f"Alignment_Mat_{num}")
                mat.diffuse_color = (1, 0, 0, 0.5)
                curve_obj.data.materials.append(mat)
                count += 1

        if count > 0:
            self.report({"INFO"}, f"Created {count} alignment lines.")
        else:
            self.report({"WARNING"}, "No landmark pairs found")
        return {"FINISHED"}


class SMILE_OT_ClearCalibrationLandmarks(bpy.types.Operator):
    """Clear all landmark pairs for camera calibration"""

    bl_idname = "smile.clear_calibration_landmarks"
    bl_label = "Clear All Landmarks"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = 0
        to_remove = []
        for obj in bpy.data.objects:
            if (
                obj.name.startswith("PNP_3D_")
                or obj.name.startswith("PNP_IMG_")
                or obj.name.startswith("ALIGNMENT_LINE_")
            ):
                to_remove.append(obj)
                count += 1

        for obj in to_remove:
            bpy.data.objects.remove(obj, do_unlink=True)

        self.report({"INFO"}, f"Removed {count} landmarks and alignment lines")
        return {"FINISHED"}


class SMILE_OT_ToggleLandmarks(bpy.types.Operator):
    """Toggle visibility of PnP landmarks"""

    bl_idname = "smile.toggle_landmarks"
    bl_label = "Toggle Landmarks"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        state = None
        count = 0
        for obj in bpy.data.objects:
            if obj.name.startswith("PNP_3D_") or obj.name.startswith("PNP_IMG_"):
                if state is None:
                    state = not obj.hide_viewport
                obj.hide_viewport = state
                count += 1

        if count > 0:
            status = "Hidden" if state else "Shown"
            self.report({"INFO"}, f"{status} {count} landmarks.")
        else:
            self.report({"WARNING"}, "No landmarks found.")
        return {"FINISHED"}


class SMILE_OT_ToggleCameraView(bpy.types.Operator):
    """Toggle between camera view and 3D view"""

    bl_idname = "smile.toggle_camera_view"
    bl_label = "Toggle Camera View"
    bl_options = {"REGISTER"}

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        if space.region_3d.view_perspective == "CAMERA":
                            space.region_3d.view_perspective = "PERSP"
                            self.report({"INFO"}, "Switched to 3D view")
                        else:
                            space.region_3d.view_perspective = "CAMERA"
                            self.report({"INFO"}, "Switched to camera view (Numpad 0)")
                        break
        return {"FINISHED"}


class SMILE_OT_PaintPhotoMask(bpy.types.Operator):
    """Enter Weight Paint mode to mask out parts of the photo"""

    bl_idname = "smile.paint_photo_mask"
    bl_label = "Paint Mask (Crop)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        plane = bpy.data.objects.get("Photo_Mockup_Plane")
        if not plane:
            self.report({"ERROR"}, "Photo plane not found")
            return {"CANCELLED"}

        context.view_layer.objects.active = plane
        plane.select_set(True)

        mod = plane.modifiers.get("Photo_Mask")
        if not mod:
            mod = plane.modifiers.new("Photo_Mask", "MASK")

        vg = plane.vertex_groups.get("MaskGroup")
        if not vg:
            vg = plane.vertex_groups.new(name="MaskGroup")
            pts = [v.index for v in plane.data.vertices]
            vg.add(pts, 1.0, "REPLACE")

        mod.vertex_group = "MaskGroup"
        mod.invert_vertex_group = False

        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")

        try:
            if hasattr(bpy.ops.paint, "brush_select"):
                bpy.ops.paint.brush_select(paint_mode="WEIGHT_PAINT", brush="Draw")
            if context.tool_settings.weight_paint.brush:
                context.tool_settings.weight_paint.brush.blend = "SUB"
                context.tool_settings.weight_paint.brush.weight = 1.0
                context.tool_settings.weight_paint.brush.strength = 1.0
        except Exception:
            traceback.print_exc()

        self.report({"INFO"}, "Paint BLUE (Subtract) to hide. Paint RED (Add) to show.")
        return {"FINISHED"}


class SMILE_OT_ImportPhotoMockup(bpy.types.Operator):
    """(Deprecated) Use smile.pnp_add_photo_slot instead."""

    bl_idname = "smile.import_photo_mockup"
    bl_label = "Import Mockup Photo"

    def execute(self, context):
        return bpy.ops.smile.pnp_add_photo_slot("INVOKE_DEFAULT")


# ============================================================
# PHOTO SLOT OPERATORS
# ============================================================


class SMILE_OT_pnp_add_photo_slot(bpy.types.Operator, ImportHelper):
    """Add a photo slot: create camera + overlay plane + camera background."""

    bl_idname = "smile.pnp_add_photo_slot"
    bl_label = "Add Photo Slot (PnP)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp", options={"HIDDEN"}
    )

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2

        slot = p.photo_slots.add()
        base = os.path.splitext(os.path.basename(self.filepath))[0]
        slot.name = base if base else "Photo"
        slot.image_path = self.filepath

        img = _get_or_load_image(slot)
        if img is None:
            self.report({"ERROR"}, "Failed to load image.")
            p.photo_slots.remove(len(p.photo_slots) - 1)
            return {"CANCELLED"}

        cam = _ensure_camera(slot)
        cam.data.type = "PERSP"
        cam.data.lens = float(p.pnp_focal_mm)
        cam.data.sensor_width = float(p.pnp_sensor_width_mm)

        cam.location = (0.0, -1.0, 0.0)
        cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)

        _set_camera_background(cam, img, alpha=float(p.pnp_bg_alpha))

        p.no_prep_mockup_image = img
        p.active_photo_slot_index = len(p.photo_slots) - 1
        scene.camera = cam
        context.view_layer.update()

        self.report({"INFO"}, f"Added Photo Slot: {slot.name}")
        return {"FINISHED"}


class SMILE_OT_pnp_view_active_camera(bpy.types.Operator):
    """Set scene camera to the active photo slot camera."""

    bl_idname = "smile.pnp_view_active_camera"
    bl_label = "View Active Photo Camera"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        slot = _active_photo_slot(scene)
        if not slot or not slot.camera_name:
            self.report({"ERROR"}, "No active photo slot / camera.")
            return {"CANCELLED"}
        cam = bpy.data.objects.get(slot.camera_name)
        if not cam:
            self.report({"ERROR"}, "Camera not found.")
            return {"CANCELLED"}
        scene.camera = cam
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for sp in area.spaces:
                    if sp.type == "VIEW_3D":
                        sp.region_3d.view_perspective = "CAMERA"
        self.report({"INFO"}, "Camera view set to active photo slot.")
        return {"FINISHED"}


class SMILE_OT_pnp_clear_2d_landmarks(bpy.types.Operator):
    """Clear 2D landmarks for the active photo slot."""

    bl_idname = "smile.pnp_clear_2d_landmarks"
    bl_label = "Clear Photo 2D Landmarks"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        slot = _active_photo_slot(context.scene)
        if not slot:
            self.report({"ERROR"}, "No active photo slot.")
            return {"CANCELLED"}
        slot.landmarks.clear()
        self.report({"INFO"}, "Cleared 2D landmarks.")
        return {"FINISHED"}


class SMILE_OT_pnp_snap_ruler_to_cam(bpy.types.Operator):
    """Parent Golden Ruler to Camera at photo depth for proportion guiding."""

    bl_idname = "smile.pnp_snap_ruler_to_cam"
    bl_label = "Snap Ruler to Camera"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        cam = scene.camera
        if not cam:
            self.report({"ERROR"}, "No active camera.")
            return {"CANCELLED"}

        ruler = bpy.data.objects.get("SMILE_Golden_Ruler")
        if not ruler:
            self.report({"ERROR"}, "Golden Ruler not found.")
            return {"CANCELLED"}

        ruler.parent = cam
        ruler.matrix_parent_inverse = cam.matrix_world.inverted()

        dist = 9.9
        ruler.location = (0, 0, -dist)
        ruler.rotation_euler = (0, 0, 0)

        p1 = Vector(ruler.get("SMILE_P1", (0, 0, 0)))
        p2 = Vector(ruler.get("SMILE_P2", (0, 0, 0)))
        curr_len = (p2 - p1).length
        if curr_len < 0.001:
            curr_len = 1.0

        sw, f = cam.data.sensor_width, cam.data.lens
        view_w = (sw * dist) / f
        s = (view_w * 0.7) / curr_len
        ruler.scale = (s, s, s)

        ruler.show_in_front = True
        for c in ruler.children:
            c.show_in_front = True

        self.report({"INFO"}, "Golden Ruler overlayed on Camera.")
        return {"FINISHED"}


class SMILE_OT_pnp_export_training_json(bpy.types.Operator, ImportHelper):
    """Export matched (3D face landmark -> 2D photo) pairs for training."""

    bl_idname = "smile.pnp_export_training_json"
    bl_label = "Export PnP Training JSON"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        scene = context.scene
        p = scene.smile_v2
        slot = _active_photo_slot(scene)
        if not slot:
            self.report({"ERROR"}, "No active photo slot.")
            return {"CANCELLED"}

        img = _get_or_load_image(slot)
        if img is None:
            self.report({"ERROR"}, "Image missing.")
            return {"CANCELLED"}

        face_inds = indices_in_domain(DOMAIN_FACE)
        photo_map = {int(lm.idx): (float(lm.u), float(lm.v)) for lm in slot.landmarks}
        matched = sorted([i for i in face_inds if i in photo_map])

        data_out = {
            "image_path": slot.image_path,
            "image_name": slot.image_name,
            "image_size": [int(slot.width), int(slot.height)],
            "intrinsics": {
                "focal_mm": float(p.pnp_focal_mm),
                "sensor_width_mm": float(p.pnp_sensor_width_mm),
            },
            "pairs": [],
        }

        for idx in matched:
            o = get_landmark_obj(DOMAIN_FACE, idx)
            if not o:
                continue
            u, v = photo_map[idx]
            data_out["pairs"].append(
                {
                    "idx": int(idx),
                    "p3_world": [
                        float(o.matrix_world.translation.x),
                        float(o.matrix_world.translation.y),
                        float(o.matrix_world.translation.z),
                    ],
                    "uv_norm": [float(u), float(v)],
                }
            )

        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data_out, f, indent=2)
            self.report(
                {"INFO"}, f"Exported {len(data_out['pairs'])} pairs to {self.filepath}"
            )
        except Exception as e:
            self.report({"ERROR"}, f"Export failed: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}


# ============================================================
# ALIGNMENT OPERATORS
# ============================================================

KEY_NO_PREP_ALIGN_STATE_VER = "SMILE_NO_PREP_ALIGN_STATE_VER"


class SMILE_OT_AlignScanToPhoto(bpy.types.Operator):
    """Align Scan to Photo landmarks using Procrustes solver."""

    bl_idname = "smile.align_scan_to_photo"
    bl_label = "Align Scan to Photo"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 1, "Scan-photo alignment")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}

        scene = context.scene
        p = scene.smile_v2

        face_inds = indices_in_domain(DOMAIN_FACE)
        photo_inds = indices_in_domain(DOMAIN_PHOTO)
        matched_indices = sorted(list(face_inds.intersection(photo_inds)))

        if len(matched_indices) < 3:
            self.report(
                {"ERROR"}, f"Need 3+ matching pairs. Found {len(matched_indices)}."
            )
            return {"CANCELLED"}

        src_pts = []
        dst_pts = []
        scan_objs_found = set()

        slot = _active_photo_slot(context.scene)
        matched_indices = sorted(list(matched_indices))

        for idx in matched_indices:
            o_src = get_landmark_obj(DOMAIN_FACE, idx)
            if o_src is None:
                continue

            loc_dst = None
            o_dst = get_landmark_obj(DOMAIN_PHOTO, idx)
            if o_dst:
                loc_dst = o_dst.matrix_world.translation.copy()
            elif slot:
                lm_data = next((lm for lm in slot.landmarks if lm.idx == idx), None)
                cam = context.scene.camera
                if lm_data and cam:
                    frame = cam.data.view_frame(scene=context.scene)
                    tr = frame[0]
                    bl = frame[2]
                    u, v = lm_data.u, lm_data.v
                    local_x = bl.x + (tr.x - bl.x) * u
                    local_y = bl.y + (tr.y - bl.y) * v
                    local_z = bl.z
                    pt_on_frame = Vector((local_x, local_y, local_z))
                    dist_m = float(p.pnp_plane_distance_mm) / 1000.0
                    scale = -dist_m / local_z
                    local_pt_scaled = pt_on_frame * scale
                    loc_dst = cam.matrix_world @ local_pt_scaled

            if loc_dst is None:
                continue

            loc_src = o_src.matrix_world.translation.copy()
            src_pts.append(loc_src)
            dst_pts.append(loc_dst)

            if "target_scan_name" in o_src:
                scan_objs_found.add(o_src["target_scan_name"])

        scan_name = None
        if scan_objs_found:
            scan_name = list(scan_objs_found)[0]
        elif p.face_target in bpy.data.objects:
            scan_name = p.face_target
        elif context.active_object and context.active_object.type == "MESH":
            scan_name = context.active_object.name

        if not scan_name:
            self.report({"ERROR"}, "Could not identify target scan.")
            return {"CANCELLED"}

        scan_obj = bpy.data.objects.get(scan_name)
        if not scan_obj:
            self.report({"ERROR"}, f"Target scan '{scan_name}' not found.")
            return {"CANCELLED"}

        try:
            R, T, s = procrustes_solver(src_pts, dst_pts, with_scaling=True)
        except Exception as e:
            self.report({"ERROR"}, f"Solver failed: {e}")
            return {"CANCELLED"}

        M_transform = Matrix.Identity(4)
        M_transform_3x3 = R * s
        for i in range(3):
            for j in range(3):
                M_transform[i][j] = M_transform_3x3[i][j]
        M_transform[0][3] = T.x
        M_transform[1][3] = T.y
        M_transform[2][3] = T.z

        scan_obj.matrix_world = M_transform @ scan_obj.matrix_world
        bpy.context.view_layer.update()

        p.no_prep_camera_calibrated = True
        align_state = {
            "state_version": 2,
            "timestamp_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "scan_name": scan_obj.name,
            "scan_signature": _mesh_signature(scan_obj),
            "pair_count": len(src_pts),
            "matched_indices": [int(i) for i in matched_indices],
            "source_points_world": [
                [float(v.x), float(v.y), float(v.z)] for v in src_pts
            ],
            "target_points_world": [
                [float(v.x), float(v.y), float(v.z)] for v in dst_pts
            ],
            "transform_matrix_world": [[float(c) for c in row] for row in M_transform],
            "scale": float(s),
            "photo_slot": int(scene.smile_v2.active_photo_slot_index),
        }
        scene["SMILE_NO_PREP_LAST_ALIGN"] = json.dumps(align_state, sort_keys=True)
        scene[KEY_NO_PREP_ALIGN_STATE_VER] = int(2)
        p.step1_done = True
        p.step2_done = True
        _set_min_design_step(p, 3)

        self.report({"INFO"}, f"Aligned Scan. Scale: {s:.2f}")
        return {"FINISHED"}


class SMILE_OT_Calibrate2DCamera(bpy.types.Operator):
    """Legacy alias - routes to AlignScanToPhoto."""

    bl_idname = "smile.calibrate_2d_camera"
    bl_label = "Move Camera to Scan"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        result = bpy.ops.smile.align_scan_to_photo()
        if "FINISHED" in result:
            context.scene.smile_v2.no_prep_camera_calibrated = True
            self.report({"INFO"}, "Calibration complete.")
            return {"FINISHED"}
        self.report({"ERROR"}, "Calibration failed.")
        return {"CANCELLED"}


# ============================================================
# NO_PREP VENEER GENERATION
# ============================================================


class SMILE_OT_GenerateNoPrepVeneer(bpy.types.Operator):
    """Generate ultra-thin veneer shell for no-prep case"""

    bl_idname = "smile.generate_no_prep_veneer"
    bl_label = "Generate No-Prep Veneer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gate = _step_gate_error(context, 4, "No-prep veneer generation")
        if gate:
            self.report({"ERROR"}, gate)
            return {"CANCELLED"}
        scene = context.scene
        p = scene.smile_v2
        source = context.active_object

        if not source or source.type != "MESH":
            self.report({"ERROR"}, "Select a library tooth first")
            return {"CANCELLED"}

        if not p.max_target and not p.face_target:
            self.report({"ERROR"}, "Set MAX or FACE target scan before no-prep build.")
            return {"CANCELLED"}

        recipe = {
            "mode": "NO_PREP",
            "source_name": source.name,
            "target_name": p.max_target or p.face_target,
            "ven_min_thickness_mm": float(p.no_prep_thickness),
            "ven_max_thickness_mm": max(
                float(p.no_prep_thickness), float(p.ven_max_thickness_mm)
            ),
        }

        try:
            import sys

            prod_mod = sys.modules.get("blendersmile.05_production") or sys.modules.get(
                "modular.05_production"
            )
            if prod_mod and hasattr(prod_mod, "build_veneer_from_recipe"):
                veneer, recipe_final = prod_mod.build_veneer_from_recipe(
                    scene, source, recipe
                )
                validation = prod_mod.validate_veneer_geometry(
                    scene, veneer, recipe_final
                )
                veneer["SMILE_VENEER_VALIDATION"] = json.dumps(
                    validation, sort_keys=True
                )
            else:
                self.report(
                    {"ERROR"},
                    "Production module not available. Use legacy veneer workflow.",
                )
                return {"CANCELLED"}
            p.no_prep_camera_calibrated = True
            p.step4_done = True
            if validation.get("pass_all"):
                p.step5_done = True
                _set_min_design_step(p, 6)
            else:
                _set_min_design_step(p, 5)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, f"No-prep veneer generated: {veneer.name}")
        return {"FINISHED"}


# ============================================================
# UI DRAWING FUNCTION
# ============================================================


def draw_no_prep_tab(context, layout, props):
    """Draw the NO_PREP tab UI."""
    scene = context.scene
    p = props

    if not _ui_fold_header(
        layout, p, "ui_tab_noprep_main", "No-Prep Controls", icon="IMAGE_DATA"
    ):
        return

    noprep_unlocked = (not p.enforce_step_lock) or (getattr(p, "design_step", 0) >= 4)
    noprep_export_unlocked = (not p.enforce_step_lock) or (
        getattr(p, "design_step", 0) >= 6
    )

    if p.enforce_step_lock and not noprep_unlocked:
        layout.label(
            text="Step lock: move to Step 4+ for no-prep generation.", icon="LOCKED"
        )

    layout.label(text="No-Prep Veneer Design", icon="LIGHT_SUN")
    layout.label(text="2D Photo-Based Workflow", icon="IMAGE_DATA")

    if _ui_fold_header(
        layout, p, "ui_noprep_sec_1_import", "1) Import 2D Mockup", icon="IMPORT"
    ):
        box1 = layout.box()
        row = box1.row(align=True)
        row.scale_y = 1.4
        row.operator(
            "smile.pnp_add_photo_slot", text="Import Mockup Photo", icon="IMAGE_DATA"
        )
        if p.no_prep_mockup_image:
            box1.label(text=f"Loaded: {p.no_prep_mockup_image.name}", icon="CHECKMARK")
            col = box1.column(align=True)
            col.prop(p, "pnp_bg_alpha", text="Opacity", slider=True)
            col.operator(
    # "smile.paint_photo_mask", text="Paint Mask (Crop)", icon="BRUSH_DATA"  # MISSING OPERATOR
            )

    if _ui_fold_header(
        layout, p, "ui_noprep_sec_2_calib", "2) Camera Calibration", icon="CAMERA_DATA"
    ):
        box2 = layout.box()
        lbox = box2.box()
        lbox.label(text="Anatomical Landmark Order:", icon="INFO")
        col = lbox.column(align=True)
        col.label(text="1: Right Eye (Pupil)")
        col.label(text="2: Left Eye (Pupil)")
        col.label(text="3: Right Commissure")
        col.label(text="4: Left Commissure")
        col.label(text="5: Glabella")
        col.label(text="6: Nose Tip")
        col.label(text="7: Chin Tip")
        col.label(text="8: Right Ala")
        col.label(text="9: Left Ala")

        box2.label(text="Place landmark pairs:", icon="INFO")
        box2.label(text="  • 4+ matching points on scan and photo", icon="DOT")
        box2.label(text="  • Use same anatomical landmarks", icon="DOT")

        row = box2.row(align=True)
    # row.operator("smile.add_landmark_pair", text="Add Landmark Pair", icon="PLUS")  # MISSING OPERATOR
    # row.operator("smile.clear_calibration_landmarks", text="Clear", icon="TRASH")  # MISSING OPERATOR

        row = box2.row(align=True)
        row.operator(
    # "smile.toggle_landmarks", text="Hide/Show Landmarks", icon="HIDE_OFF"  # MISSING OPERATOR
        )
        row.operator(
    # "smile.show_alignment_lines",  # MISSING OPERATOR
            text="Show Alignment Lines",
            icon="CON_TRACKTO",
        )

        row = box2.row(align=True)
        row.operator(
    # "smile.toggle_camera_view", text="View Through Camera", icon="VIEW_CAMERA"  # MISSING OPERATOR
        )

        box2.label(text="Choose alignment method:", icon="INFO")
        row = box2.row(align=True)
        row.scale_y = 1.4
        row.operator(
    # "smile.align_scan_to_photo",  # MISSING OPERATOR
            text="Align Scan to Photo (Recommended)",
            icon="MESH_DATA",
        )

        row = box2.row(align=True)
        row.operator(
    # "smile.calibrate_2d_camera", text="Move Camera to Scan", icon="CAMERA_DATA"  # MISSING OPERATOR
        )

        if p.no_prep_camera_calibrated:
            box2.label(text="Aligned", icon="CHECKMARK")
            box2.label(text="Press Numpad 0 to verify alignment", icon="INFO")
            align_meta = _json_obj(
                scene.get("SMILE_NO_PREP_LAST_ALIGN", "{}"), default={}
            )
            if align_meta:
                ts = str(align_meta.get("timestamp_utc", ""))
                pair_count = int(align_meta.get("pair_count", 0))
                if ts:
                    box2.label(text=f"Last align: {ts}", icon="TIME")
                box2.label(text=f"Matched pairs: {pair_count}", icon="CON_TRACKTO")

    if _ui_fold_header(
        layout, p, "ui_noprep_sec_3_position", "3) Position Teeth", icon="OBJECT_DATA"
    ):
        box3 = layout.box()
        box3.label(text="a) Import library teeth (Teeth Library tab)", icon="DOT")
        box3.label(text="b) Use G/R/S to align to 2D mockup outline", icon="DOT")
        box3.label(text="c) Ensure teeth cover mockup design", icon="DOT")

    if _ui_fold_header(
        layout,
        p,
        "ui_noprep_sec_4_generate",
        "4) Crown / Veneer Generation",
        icon="MOD_THICKNESS",
    ):
        box4 = layout.box()
        box4.enabled = noprep_unlocked

        box4.label(text="Production Methods", icon="MODIFIER")
        row = box4.row(align=True)
        row.scale_y = 1.4
        row.operator(
    # "smile.generate_industry_crown",  # MISSING OPERATOR
            text="Generate Crown (C++ Engine)",
            icon="MOD_BOOLEAN",
        )

        row = box4.row(align=True)
        row.scale_y = 1.2
        row.operator(
    # "smile.make_veneer_active",  # MISSING OPERATOR
            text="Generate Veneer (Legacy)",
            icon="MOD_BOOLEAN",
        )

        box4.separator()
        box4.label(text="Workflow Routing", icon="RIGHTARROW")
        primary_row = box4.row(align=True)
        primary_row.scale_y = 1.2
        op = primary_row.operator(
    # "smile.set_workflow_state", text="Go to 4. Production", icon="PREFERENCES"  # MISSING OPERATOR
        )
        op.target_state = "PRODUCTION"

        adv = box4.box()
        adv.label(
            text="Advanced: use Veneer Lab for imported restorations.",
            icon="TOOL_SETTINGS",
        )
        op = adv.operator(
    # "smile.set_workflow_state", text="Open 6. Veneer Lab", icon="TOOL_SETTINGS"  # MISSING OPERATOR
        )
        op.target_state = "VENEER_IMPORT"

    if _ui_fold_header(
        layout, p, "ui_noprep_sec_5_export", "5) Validate + Export", icon="EXPORT"
    ):
        box5 = layout.box()
        box5.enabled = noprep_export_unlocked
        row = box5.row(align=True)
        row.label(text="Check veneer thickness uniformity", icon="INFO")
        row = box5.row(align=True)
        row.scale_y = 1.4
        row.operator(
    # "smile.export_veneer_active",  # MISSING OPERATOR
            text="Export No-Prep Veneer STL",
            icon="EXPORT",
        )


# ============================================================
# CLASSES LIST AND REGISTRATION
# ============================================================

CLASSES = [
    SMILE_OT_AddLandmarkPair,
    SMILE_OT_ShowAlignmentLines,
    SMILE_OT_ClearCalibrationLandmarks,
    SMILE_OT_ToggleLandmarks,
    SMILE_OT_ToggleCameraView,
    SMILE_OT_PaintPhotoMask,
    SMILE_OT_ImportPhotoMockup,
    SMILE_OT_pnp_add_photo_slot,
    SMILE_OT_pnp_view_active_camera,
    SMILE_OT_pnp_clear_2d_landmarks,
    SMILE_OT_pnp_snap_ruler_to_cam,
    SMILE_OT_pnp_export_training_json,
    SMILE_OT_AlignScanToPhoto,
    SMILE_OT_Calibrate2DCamera,
    SMILE_OT_GenerateNoPrepVeneer,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
