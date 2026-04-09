"""BlenderSmile SETUP Tab Module"""

import bpy
import os
import math
import traceback
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector, Matrix

COL_SCANS = "Scans"
DOMAIN_FACE = "FACE"
DOMAIN_MAX = "MAX"
DOMAIN_MAN = "MAN"
DOMAIN_PHOTO = "PHOTO"


def _op_props(op):
    """Get operator properties dict."""
    try:
        return op.get_rna_type().properties
    except Exception:
        return {}


def _import_with_operator(op, kwargs):
    """Import using Blender operator with safe kwargs."""
    props = _op_props(op)
    safe = {k: v for k, v in kwargs.items() if k in props}
    return op(**safe)


def ensure_collection(name):
    """Get or create collection by name."""
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def link_to_collection(obj, col):
    """Link object to collection if not already there."""
    if obj.name not in col.objects:
        col.objects.link(obj)


def import_mesh_file(filepath):
    """Import mesh file and return list of mesh objects."""
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


def calculate_pca_basis(obj):
    """Calculate PCA basis vectors for mesh orientation."""
    import numpy as np

    if not obj or obj.type != "MESH":
        return None

    mesh = obj.data
    if len(mesh.vertices) < 3:
        return None

    verts = np.array([v.co for v in mesh.vertices])

    if len(verts) > 1000:
        verts = verts[:: int(len(verts) / 1000)]

    mean = np.mean(verts, axis=0)
    centered = verts - mean
    cov = np.cov(centered.T)
    evals, evecs = np.linalg.eigh(cov)

    order = evals.argsort()[::-1]

    vec1 = Vector(evecs[:, order[0]])
    vec2 = Vector(evecs[:, order[1]])
    vec3 = Vector(evecs[:, order[2]])

    center = Vector(mean)

    return vec1, vec2, vec3, center


def align_object_to_frame(obj, vec_z, vec_x):
    """Rotate object so vec_z aligns with Local Z and vec_x aligns with Local X."""
    if vec_z.length_squared > 1e-12:
        vec_z.normalize()
    _cross_y = vec_z.cross(vec_x)
    vec_y = _cross_y.normalized() if _cross_y.length_squared > 1e-12 else Vector((0, 1, 0))
    _cross_x = vec_y.cross(vec_z)
    vec_x = _cross_x.normalized() if _cross_x.length_squared > 1e-12 else Vector((1, 0, 0))

    src_mat = Matrix((vec_x, vec_y, vec_z)).transposed().to_4x4()
    align_rot = src_mat.inverted()
    obj.matrix_world = obj.matrix_world @ align_rot

    return align_rot


def curve_world_points(curve_obj, samples=64):
    """Get world space points from curve object."""
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


class SMILE_OT_import_photo(bpy.types.Operator, ImportHelper):
    bl_idname = "smile.import_photo"
    bl_label = "Import Photo (Plane)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: bpy.props.StringProperty(
        default="*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp",
        options={"HIDDEN"},
    )

    def execute(self, context):
        ensure_collection(COL_SCANS)
        obj = None

        try:
            if hasattr(bpy.ops, "import_image") and hasattr(
                bpy.ops.import_image, "to_plane"
            ):
                bpy.ops.import_image.to_plane(
                    files=[{"name": os.path.basename(self.filepath)}],
                    directory=os.path.dirname(self.filepath),
                    relative=False,
                )
                obj = context.view_layer.objects.active
        except Exception:
            obj = None

        if not obj:
            try:
                img = bpy.data.images.load(self.filepath)
            except Exception:
                self.report({"ERROR"}, "Could not load image.")
                return {"CANCELLED"}

            bg_empty = bpy.data.objects.new("PNP_PHOTO_EMPTY", None)
            context.collection.objects.link(bg_empty)
            bg_empty.empty_display_type = "IMAGE"
            bg_empty.empty_display_size = 1.0
            bg_empty.data = img

            photo_width = img.size[0]
            photo_height = img.size[1]

            if photo_width > 0 and photo_height > 0:
                context.scene.render.resolution_x = photo_width
                context.scene.render.resolution_y = photo_height
                context.scene.render.resolution_percentage = 100

                if context.scene.camera:
                    cam = context.scene.camera.data
                    aspect_ratio = photo_width / photo_height

                    if aspect_ratio > 1.0:
                        cam.sensor_fit = "HORIZONTAL"
                        cam.sensor_width = 36.0
                    else:
                        cam.sensor_fit = "VERTICAL"
                        cam.sensor_height = 36.0

                print(f"Camera and render set to: {photo_width}x{photo_height}")

            w, h = img.size
            aspect = w / h if h > 0 else 1.0

            bpy.ops.mesh.primitive_plane_add(size=2.0)
            obj = context.view_layer.objects.active
            obj.dimensions = Vector((2.0 * aspect, 2.0, 0.0))

            mat = bpy.data.materials.new(name=os.path.basename(self.filepath) + "_MAT")
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex.image = img
            if bsdf:
                mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
                if "Emission Strength" in bsdf.inputs:
                    bsdf.inputs["Emission Strength"].default_value = 1.0
                if "Emission Color" in bsdf.inputs:
                    mat.node_tree.links.new(
                        tex.outputs["Color"], bsdf.inputs["Emission Color"]
                    )
                elif "Emission" in bsdf.inputs:
                    mat.node_tree.links.new(
                        tex.outputs["Color"], bsdf.inputs["Emission"]
                    )

            obj.data.materials.append(mat)

        if obj:
            obj.name = "PHOTO_" + os.path.basename(self.filepath)
            link_to_collection(obj, ensure_collection(COL_SCANS))
            obj.rotation_euler.x = math.radians(90)
            context.scene.smile_v2.photo_target = obj.name

        self.report({"INFO"}, "Imported photo plane.")
        return {"FINISHED"}


class SMILE_OT_upright_model(bpy.types.Operator):
    bl_idname = "smile.upright_model"
    bl_label = "Auto-Upright (Z-Up)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh.")
            return {"CANCELLED"}

        basis = calculate_pca_basis(obj)
        if not basis:
            self.report({"ERROR"}, "Could not calculate PCA (mesh too small?)")
            return {"CANCELLED"}

        vec1, vec2, vec3, center = basis

        align_object_to_frame(obj, vec_z=vec1, vec_x=vec2)

        self.report({"INFO"}, "Model Uprighted to Z-axis.")
        return {"FINISHED"}


class SMILE_OT_set_domain_target(bpy.types.Operator):
    bl_idname = "smile.set_domain_target"
    bl_label = "Set Domain Target From Selection"
    bl_options = {"REGISTER", "UNDO"}

    domain: EnumProperty(
        items=[
            (DOMAIN_FACE, "FACE", ""),
            (DOMAIN_MAX, "MAX", ""),
            (DOMAIN_MAN, "MAN", ""),
            (DOMAIN_PHOTO, "PHOTO", ""),
        ],
        default=DOMAIN_FACE,
    )

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first (active object).")
            return {"CANCELLED"}
        p = context.scene.smile_v2
        if self.domain == DOMAIN_FACE:
            p.face_target = obj.name
        elif self.domain == DOMAIN_MAX:
            p.max_target = obj.name
        elif self.domain == DOMAIN_MAN:
            p.man_target = obj.name
        else:
            p.photo_target = obj.name

        link_to_collection(obj, ensure_collection(COL_SCANS))
        self.report({"INFO"}, f"{self.domain} target = {obj.name}")
        return {"FINISHED"}


class SMILE_OT_set_hinge_axis(bpy.types.Operator):
    bl_idname = "smile.set_hinge_axis"
    bl_label = "Toggle Hinge Axis"
    bl_options = {"REGISTER", "UNDO"}

    axis: EnumProperty(
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
    )

    def execute(self, context):
        guide = context.view_layer.objects.active
        if not guide or guide.type != "CURVE":
            self.report({"ERROR"}, "Select a Guide Line first.")
            return {"CANCELLED"}

        parent = guide.parent
        if not parent:
            self.report({"ERROR"}, "Guide must be attached to a Model (Parent).")
            return {"CANCELLED"}

        is_locked = any(parent.lock_rotation)

        if is_locked:
            parent.lock_rotation = (False, False, False)
            self.report({"INFO"}, "Hinge Unlocked (Free Rotation).")
            return {"FINISHED"}

        pts = curve_world_points(guide)
        if len(pts) < 2:
            return {"CANCELLED"}

        _guide_diff = pts[1] - pts[0]
        guide_vec = _guide_diff.normalized() if _guide_diff.length_squared > 1e-12 else Vector((1, 0, 0))
        guide_center = (pts[0] + pts[1]) * 0.5

        saved_loc = context.scene.cursor.location.copy()
        context.scene.cursor.location = guide_center

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        parent.select_set(True)
        context.view_layer.objects.active = parent

        bpy.ops.object.origin_set(type="ORIGIN_CURSOR", center="MEDIAN")

        context.scene.cursor.location = saved_loc

        mat = parent.matrix_world.to_3x3()
        if self.axis == "X":
            current_vec = mat @ Vector((1, 0, 0))
        elif self.axis == "Y":
            current_vec = mat @ Vector((0, 1, 0))
        else:
            current_vec = mat @ Vector((0, 0, 1))

        rot_quat = current_vec.rotation_difference(guide_vec)

        parent.rotation_mode = "QUATERNION"
        parent.rotation_quaternion = rot_quat @ parent.rotation_quaternion
        parent.lock_rotation = (True, True, False)

        self.report({"INFO"}, f"Hinge locked to {self.axis}-axis.")
        return {"FINISHED"}


def draw_orientation_panel(layout):
    """Draw orientation and hinge controls."""
    box = layout.box()
    box.label(text="Orientation & Hinge")

    # TODO: Add align_model_to_guide operator
    # row = box.row(align=True)
    # row.operator("smile.align_model_to_guide", text="Align Horiz").target_axis = "X"
    # row.operator("smile.align_model_to_guide", text="Align Vert").target_axis = "Z"

    row = box.row(align=True)
    row.label(text="Toggle Hinge:")
    row.operator("smile.set_hinge_axis", text="X").axis = "X"
    row.operator("smile.set_hinge_axis", text="Y").axis = "Y"
    row.operator("smile.set_hinge_axis", text="Z").axis = "Z"


def open3d_status_string():
    """Get Open3D installation status string."""
    try:
        import open3d as o3d

        return f"Open3D {o3d.__version__} ready"
    except ImportError:
        return "Open3D not installed"


CLASSES = [
    SMILE_OT_import_scan,
    SMILE_OT_import_photo,
    SMILE_OT_upright_model,
    SMILE_OT_set_domain_target,
    SMILE_OT_set_hinge_axis,
]


def draw_setup_tab(context, layout, props):
    """Draw the SETUP tab UI."""
    p = props
    p_v2 = context.scene.smile_v2

    if hasattr(p, "ui_tab_setup_main") and not getattr(p, "ui_tab_setup_main", True):
        return

    box = layout.box()
    box.label(text="Import Data", icon="IMPORT")
    box.operator("smile.import_scan", text="Import 3D Mesh (.obj/.stl)")
    box.operator("smile.import_photo", text="Import Photo (.jpg/.png)")
    box.separator()

    # TODO: Add occlusal plane operators
    # op_box = box.box()
    # op_box.label(text="Step 1: Define Occlusal Plane", icon="ORIENTATION_GLOBAL")
    # op_box.label(text="Sets the global Z-axis (Up) and Midline (Y-axis).", icon="INFO")
    # mid_set = bool(p_v2.align_pt_1_mid)
    # lm_set = bool(p_v2.align_pt_2_lm)
    # rm_set = bool(p_v2.align_pt_3_rm)
    # row = op_box.row()
    # row.label(text=f"Midline: {'V' if mid_set else 'X'}")
    # row.label(text=f"L-Molar: {'V' if lm_set else 'X'}")
    # row.label(text=f"R-Molar: {'V' if rm_set else 'X'}")
    # row = op_box.row(align=True)
    # op = row.operator("smile.capture_occlusal_plane_point", text="Mark Midline", icon="TRACKER")
    # op.point_id = "MID"
    # op = row.operator("smile.capture_occlusal_plane_point", text="Mark L. Molar", icon="TRACKER")
    # op.point_id = "LM"
    # op = row.operator("smile.capture_occlusal_plane_point", text="Mark R. Molar", icon="TRACKER")
    # op.point_id = "RM"
    # row = op_box.row(align=True)
    # row.scale_y = 1.2
    # row.operator("smile.apply_occlusal_plane_alignment", text="Align Case to World Zero", icon="SNAP_ON")
    # row.operator("smile.clear_occlusal_plane_points", text="", icon="TRASH")

    target_box = layout.box()
    target_box.label(text="Set Targets", icon="OUTLINER_OB_MESH")
    target_box.label(text="Select Object First, then click Set", icon="INFO")

    row = target_box.row(align=True)
    row.prop(p, "face_target", text="FACE")
    op = row.operator("smile.set_domain_target", text="Set")
    op.domain = DOMAIN_FACE

    row = target_box.row(align=True)
    row.prop(p, "max_target", text="MAX")
    op = row.operator("smile.set_domain_target", text="Set")
    op.domain = DOMAIN_MAX

    row = target_box.row(align=True)
    row.prop(p, "man_target", text="MAN")
    op = row.operator("smile.set_domain_target", text="Set")
    op.domain = DOMAIN_MAN

    row = target_box.row(align=True)
    row.prop(p, "photo_target", text="PHOTO")
    op = row.operator("smile.set_domain_target", text="Set")
    op.domain = DOMAIN_PHOTO

    draw_orientation_panel(layout)

    dep_box = layout.box()
    dep_box.label(text="Python Dependencies (Optional)", icon="PREFERENCES")
    dep_box.label(text="Open3D is only needed for ICP refinement.", icon="INFO")
    dep_box.prop(p, "auto_install_python_dependencies", text="Allow Auto-Install")
    dep_box.label(text=open3d_status_string())


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
