"""BlenderSmile MOCKUP Tab Module - Complete

This module contains all MOCKUP tab operators and helpers:
- Golden Ruler system
- Golden Set import with tri-curve positioning
- Library tooth import
- Tooth placement and layout
- Lip line and smile arc
- Sculpt and eraser tools
- Frame 2D/3D operators
- Crown shape editing
"""

import bpy
import bmesh
import os
import re
import math
import json
import time
import blf
import traceback
import bpy_extras
from datetime import datetime
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_plane
from bpy_extras.io_utils import ImportHelper
from bpy_extras.view3d_utils import region_2d_to_vector_3d, region_2d_to_origin_3d

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    gpu = None

# === Import shared utilities from core_00 ===
import core_00 as core
from core_00 import (
    COL_SCANS,
    COL_TEETH,
    COL_LM,
    COL_ARCH,
    COL_PREVIEW,
    COL_VENEER,
    COL_RIG,
    COL_MARGINS,
    DOMAIN_FACE,
    DOMAIN_MAX,
    DOMAIN_MAN,
    DOMAIN_PHOTO,
    DOMAINS,
    NEON,
    MARGIN_NEON_RGBA,
    SUPPORTED_EXTS,
    TOOTH_REGEX,
    KEY_ARCH_MAX_PTS,
    KEY_ARCH_MAN_PTS,
    ARCH_CURVE_OCCLUSAL,
    ARCH_CURVE_CERVICAL,
    ensure_collection,
    ensure_active,
    delete_object,
    parse_tooth_id_from_name,
    link_to_collection,
    make_marker,
    _view3d_utils,
    _deselect_all,
    raycast_from_mouse_to_target,
    snap_to_nearest_vertex_world,
    _resolve_margin_tooth_id,
    SafeMode,
    ensure_emission_material,
)


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

            # 1. Force Selection/Activation
            if self.ctx.view_layer.objects.active != self.obj:
                # Deselect others to be safe?
                # bpy.ops.object.select_all(action='DESELECT') # Risk of poll error
                # Just ensure obj is active
                self.ctx.view_layer.objects.active = self.obj

            if not self.obj.select_get():
                self.obj.select_set(True)

            # 2. Switch Mode
            if self.obj.mode != self.target_mode:
                bpy.ops.object.mode_set(mode=self.target_mode)

        except Exception as e:
            print(f"[SafeMode] Error entering {self.target_mode}: {e}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            # Restore Mode
            if self.prev_mode and self.obj and self.obj.mode != self.prev_mode:
                # Ensure active again
                self.ctx.view_layer.objects.active = self.obj
                bpy.ops.object.mode_set(mode=self.prev_mode)

            # Restore Active Object (if it was different)
            if self.prev_active and self.prev_active != self.obj:
                self.ctx.view_layer.objects.active = self.prev_active

        except Exception as e:
            print(f"[SafeMode] Error exiting: {e}")


# ============================================================
# VIEW3D RAYCAST + VERTEX SNAP (robust)
# ============================================================

_VIEW3D_UTILS = None


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


class PRTParser:
    @staticmethod
    def parse_part_frame(prt_path):
        """Parses a 3Shape/Exocad .prt XML file to extract the PartFrame matrix."""
        if not os.path.exists(prt_path):
            return None
        try:
            tree = ET.parse(prt_path)
            root = tree.getroot()
            # Path: PartInfo -> Values -> PartFrame
            # XML structure in example: <PartInfo><Values><PartFrame>...

            # Simple recursive search for PartFrame tag
            frame_str = None
            for elem in root.iter("PartFrame"):
                frame_str = elem.text
                break

            if not frame_str:
                return None

            # Parse 16 floats (4x4 matrix usually stored as 12 values or 16?)
            # Example: 0 -1 0 0 0 1 -1 0 0 0 0 -1 -1 0 0 0 1 0 -10.6 0.00 -4.4
            # That looks like more than 16 values?
            # 0 -1 0 0 (row1?)
            # 0 1 -1 0 (row2?)
            # 0 0 0 -1 (row3?)
            # -1 0 0 0 1 0 (???)
            # -10.6... (Translation?)

            # Let's just try to parse space-separated floats
            vals = [float(x) for x in frame_str.split()]
            if len(vals) >= 16:
                # Assuming standard 4x4 row major or column major
                # Blender uses Column Major internally but constructor takes Row Major?
                # Let's try Row Major first.
                mat = Matrix([vals[i : i + 4] for i in range(0, 16, 4)])
                return mat
            elif len(vals) == 12:
                # 3x4 affine?
                mat = Matrix([vals[i : i + 4] for i in range(0, 12, 4)])
                return mat

        except Exception as e:
            print(f"PRT Parse Error: {e}")
        return None


class DentalAsset:
    def __init__(
        self, name, filepath, width=0.0, height=0.0, tooth_id=0, transform=None
    ):
        self.name = name
        self.filepath = filepath
        self.width = width
        self.height = height
        self.ratio = width / height if height > 0 else 0.0
        self.score = 0.0
        self.tooth_id = tooth_id  # Universal #1-#32
        self.transform = transform  # Matrix from .prt


class LibraryManager:
    assets = []
    sets = {}  # name -> list of DentalAssets

    @staticmethod
    def _parse_tooth_id(filename):
        # Try #8 syntax
        m = TOOTH_REGEX.search(filename)
        if m:
            return int(m.group(1))
        return 0

    @classmethod
    def sync_ui_list(cls, context):
        p = context.scene.smile_v2
        p.library_assets.clear()

        if not cls.sets:
            return

        keys = list(cls.sets.keys())
        if p.active_library_index >= len(keys):
            p.active_library_index = 0
        set_name = keys[p.active_library_index]
        p.active_library_name = set_name

        assets = cls.sets[set_name]
        # Sort by tooth ID for nice list
        assets.sort(key=lambda x: x.tooth_id)

        for a in assets:
            item = p.library_assets.add()
            item.name = a.name
            item.tooth_id = a.tooth_id
            item.filepath = a.filepath
            item.selected = (
                False  # Default off? Or True? Let's say False to force choice.
            )

    @classmethod
    def load_library(cls, directory):
        cls.assets = []
        cls.sets = {}
        if not os.path.isdir(directory):
            return

        # Walk directory
        for root, dirs, files in os.walk(directory):
            set_name = os.path.basename(root)
            current_set_assets = []

            for f in files:
                if f.lower().endswith((".obj", ".stl", ".ply")):
                    filepath = os.path.join(root, f)

                    # Metadata
                    meta_path = os.path.join(root, "meta.json")
                    prt_path = filepath + ".prt"  # Standard convention

                    width, height = 0.0, 0.0
                    transform = PRTParser.parse_part_frame(prt_path)

                    # Universal ID
                    tid = cls._parse_tooth_id(f)

                    # Width/Height from JSON if exists
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, "r") as jf:
                                data = json.load(jf)
                                dims = data.get("dimensions", {})
                                width = dims.get("width_mm", 0.0)
                                height = dims.get("height_mm", 0.0)
                        except Exception:
                            traceback.print_exc()

                    asset = DentalAsset(
                        name=f,
                        filepath=filepath,
                        width=width,
                        height=height,
                        tooth_id=tid,
                        transform=transform,
                    )
                    cls.assets.append(asset)
                    current_set_assets.append(asset)

            if current_set_assets:
                cls.sets[set_name] = current_set_assets

        # Sync UI List immediately
        if cls.sets:
            # Sort sets by name?
            # keys = sorted(list(cls.sets.keys()))
            # cls.sets is dict, iteration order preserved in Py3.7+
            pass

        # We need context to sync. But this is class method.
        # We can pass context or rely on caller.
        # Let's rely on caller or bpy.context (risky in threads but ok here).
        if bpy.context.scene:
            cls.sync_ui_list(bpy.context)

    @classmethod
    def search(cls, target_w, target_h):
        target_ratio = target_w / target_h if target_h > 0 else 0.75
        for a in cls.assets:
            # Score deviation from ideal ratio
            if a.ratio > 0:
                a.score = abs(a.ratio - target_ratio)
            else:
                a.score = 100.0  # Penalty for unknown
        cls.assets.sort(key=lambda x: x.score)
        return cls.assets[:5]


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


class SMILE_OT_import_selected_teeth(bpy.types.Operator):
    bl_idname = "smile.import_selected_teeth"
    bl_label = "Import & Place Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        if not LibraryManager.sets:
            self.report({"ERROR"}, "No library loaded.")
            return {"CANCELLED"}

        # 1. Check Arch Tracer
        # Use UI List Selection
        selected_items = [item for item in p.library_assets if item.selected]
        if not selected_items:
            self.report({"WARNING"}, "No teeth selected in the list.")
            return {"CANCELLED"}

        has_max = any(item.tooth_id <= 16 for item in selected_items)
        has_man = any(item.tooth_id >= 17 for item in selected_items)

        curve_max = bpy.data.objects.get(arch_curve_name(DOMAIN_MAX))
        curve_man = bpy.data.objects.get(arch_curve_name(DOMAIN_MAN))
        curve_max_incisal = find_arch_incisal_curve(DOMAIN_MAX)
        curve_man_incisal = find_arch_incisal_curve(DOMAIN_MAN)

        if has_max and not curve_max:
            self.report(
                {"ERROR"}, "Missing MAX Arch Tracer! Please trace the upper arch first."
            )
            return {"CANCELLED"}
        if has_man and not curve_man:
            self.report(
                {"ERROR"}, "Missing MAN Arch Tracer! Please trace the lower arch first."
            )
            return {"CANCELLED"}

        # 3. Import
        imported_max = []
        imported_man = []

        # Scale logic
        scale_factor = 1.0
        ref_len = p.reference_length_mm

        set_name = p.active_library_name
        assets = LibraryManager.sets.get(set_name, [])
        asset_map = {a.tooth_id: a for a in assets}

        lib_h = 0.0
        for a in assets:
            if a.tooth_id in [8, 9] and a.height > 0:
                lib_h = a.height
                break

        count = 0
        centrals_imported = []

        for item in selected_items:
            asset = asset_map.get(item.tooth_id)
            if not asset:
                continue

            meshes = import_mesh_file(asset.filepath)
            for obj in meshes:
                link_to_collection(obj, ensure_collection(COL_TEETH))
                ensure_tooth_params(obj)

                # CRITICAL FIX: Center Origin to Geometry
                ensure_active(obj)
                bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")

                # Clear Parent
                if obj.parent:
                    mw = obj.matrix_world.copy()
                    obj.parent = None
                    obj.matrix_world = mw

                # Reset Rotation
                obj.rotation_mode = "XYZ"
                obj.rotation_euler = (0, 0, 0)

                # --- NEW LIBRARY CONFIG: ORIENTATION ---
                if p.lib_use_manual_orient:
                    # Manual Axis Mapping
                    # Goal: Map Lib Fwd -> Blender Fwd (-Y)
                    #       Map Lib Up  -> Blender Up (+Z)

                    axis_vecs = {
                        "POS_X": Vector((1, 0, 0)),
                        "NEG_X": Vector((-1, 0, 0)),
                        "POS_Y": Vector((0, 1, 0)),
                        "NEG_Y": Vector((0, -1, 0)),
                        "POS_Z": Vector((0, 0, 1)),
                        "NEG_Z": Vector((0, 0, -1)),
                    }

                    src_fwd = axis_vecs.get(p.lib_forward_axis, Vector((0, -1, 0)))
                    src_up = axis_vecs.get(p.lib_up_axis, Vector((0, 0, 1)))

                    # Construct Source Rotation Matrix
                    # R * Src = World
                    # We want R such that Src_Fwd becomes -Y, Src_Up becomes +Z

                    # Target (Blender)
                    tgt_fwd = Vector((0, -1, 0))
                    tgt_up = Vector((0, 0, 1))
                    tgt_right = tgt_fwd.cross(tgt_up).normalized()  # (-1,0,0) approx?

                    # Source Basis
                    _cross_src = src_fwd.cross(src_up)
                    src_right = _cross_src.normalized() if _cross_src.length_squared > 1e-12 else Vector((1, 0, 0))

                    # We construct rotation relative to identity
                    # Actually simpler: Use rotation difference
                    # R_fwd = rotation to align src_fwd to tgt_fwd
                    # Then align up vector?

                    # Robust Matrix Construction:
                    # Mat_Src = [Right, Fwd, Up] (Column Major)
                    # Mat_Tgt = [Right, Fwd, Up]
                    # R = Mat_Tgt @ Mat_Src.inverted()

                    m_src = Matrix((src_right, src_fwd, src_up)).transposed().to_3x3()
                    m_tgt = Matrix((tgt_right, tgt_fwd, tgt_up)).transposed().to_3x3()

                    # --- CANONICAL SCALING (Pre-Rotation) ---
                    if p.use_target_dims:
                        # 1. Identify Dimensions along Local Axes
                        # We assume axis_vecs are unit vectors like (1,0,0) or (0,-1,0).
                        dims = obj.dimensions  # (x, y, z)

                        # Width is length projected onto src_right
                        curr_w = (
                            abs(src_right.x * dims.x)
                            + abs(src_right.y * dims.y)
                            + abs(src_right.z * dims.z)
                        )
                        curr_h = (
                            abs(src_up.x * dims.x)
                            + abs(src_up.y * dims.y)
                            + abs(src_up.z * dims.z)
                        )

                        unit_scale = context.scene.unit_settings.scale_length
                        target_bu_x = (p.target_width_mm / 1000.0) / unit_scale
                        target_bu_z = (p.target_height_mm / 1000.0) / unit_scale

                        scale_x_fac = target_bu_x / curr_w if curr_w > 0 else 1.0
                        scale_z_fac = target_bu_z / curr_h if curr_h > 0 else 1.0

                        if p.lock_scale_ratio:
                            scale_z_fac = scale_x_fac

                        # Apply to the Local Axis components
                        # If src_right has X component, scale obj.scale.x
                        # Note: This is simplified for axis-aligned.
                        # Generalized: scale vector S = (1,1,1). S += Scale_Factor * Axis_Abs?
                        # Better: Multiply the relevant scale component

                        # Apply Width Scale
                        if abs(src_right.x) > 0.9:
                            obj.scale.x *= scale_x_fac
                        if abs(src_right.y) > 0.9:
                            obj.scale.y *= scale_x_fac
                        if abs(src_right.z) > 0.9:
                            obj.scale.z *= scale_x_fac

                        # Apply Height Scale
                        if abs(src_up.x) > 0.9:
                            obj.scale.x *= scale_z_fac
                        if abs(src_up.y) > 0.9:
                            obj.scale.y *= scale_z_fac
                        if abs(src_up.z) > 0.9:
                            obj.scale.z *= scale_z_fac

                        # Thickness? Assume Fwd matches Width scale (Proportional)
                        if abs(src_fwd.x) > 0.9:
                            obj.scale.x *= scale_x_fac
                        if abs(src_fwd.y) > 0.9:
                            obj.scale.y *= scale_x_fac
                        if abs(src_fwd.z) > 0.9:
                            obj.scale.z *= scale_x_fac

                        bpy.ops.object.transform_apply(
                            location=False, rotation=False, scale=True
                        )

                    rot_mat = m_tgt @ m_src.inverted()
                    obj.matrix_world = rot_mat.to_4x4() @ obj.matrix_world

                else:
                    # AUTO-ORIENT (PCA)
                    align_tooth_by_pca(obj)

                # --- FALLBACK SCALING (If not handled above) ---
                # Only run this if we didn't do Canonical Scaling (e.g. PCA mode)
                # Or simplistic check: if manual orient, we did it.
                if p.use_target_dims and not p.lib_use_manual_orient:
                    # 1. Measure Current Dimensions (World Orientation - PCA Aligned)
                    mn, mx = bbox_world(obj)
                    cur_w = mx.x - mn.x
                    cur_h = mx.z - mn.z

                    # 2. Calculate Scale Factors (Robust to Unit Scale)
                    unit_scale = context.scene.unit_settings.scale_length
                    target_bu_x = (p.target_width_mm / 1000.0) / unit_scale
                    target_bu_z = (p.target_height_mm / 1000.0) / unit_scale

                    scale_x = target_bu_x / cur_w if cur_w > 0 else 1.0
                    scale_z = target_bu_z / cur_h if cur_h > 0 else 1.0

                    if p.lock_scale_ratio:
                        scale_z = scale_x

                    # 3. Apply (Assume Y scale matches X for thickness preservation ratio)
                    obj.scale.x *= scale_x
                    obj.scale.y *= scale_x
                    obj.scale.z *= scale_z
                    bpy.ops.object.transform_apply(
                        location=False, rotation=False, scale=True
                    )

                elif abs(p.lib_import_scale - 1.0) > 0.001 and not p.use_target_dims:
                    obj.scale *= p.lib_import_scale
                    bpy.ops.object.transform_apply(
                        location=False, rotation=False, scale=True
                    )

                # Optional manual anchor calibration correction (rotation + scale only).
                if bool(getattr(p, "import_use_anchor_calibration", True)):
                    arch = _import_calib_arch_for_tooth_id(asset.tooth_id)
                    rs_cal, _meta = _load_import_calibration(context.scene, arch)
                    if rs_cal is not None:
                        _apply_import_calibration_to_mesh(obj, rs_cal)

                if asset.tooth_id in [8, 9]:
                    centrals_imported.append((obj, asset))

                if asset.tooth_id <= 16:
                    imported_max.append(obj)
                else:
                    imported_man.append(obj)

            count += 1

        # Calculate Scale Factor now
        if lib_h <= 0.0 and centrals_imported:
            c_obj = centrals_imported[0][0]
            mn, mx = bbox_world(c_obj)
            lib_h = mx.z - mn.z

        if lib_h > 0:
            scale_factor = ref_len / lib_h
        else:
            scale_factor = 1.0

        # Apply Scale & Rig
        for objs in [imported_max, imported_man]:
            for o in objs:
                ensure_active(o)
                if abs(scale_factor - 1.0) > 0.001:
                    o.scale *= scale_factor
                    bpy.ops.object.transform_apply(
                        location=False, rotation=False, scale=True
                    )
                # create_lattice_rig_for_tooth(o) # DISABLED by user request

        # 4. Layout & Parent
        target_max = bpy.data.objects.get(p.max_target)
        target_man = bpy.data.objects.get(p.man_target)
        layout_warnings = []

        # Helper to find closest point/tangent on a sampled polyline.
        def _closest_point_and_tangent_on_polyline(point_world, poly_pts):
            pts = [Vector(p) for p in (poly_pts or [])]
            if not pts:
                return None, Vector((1.0, 0.0, 0.0))
            if len(pts) == 1:
                return pts[0], Vector((1.0, 0.0, 0.0))
            best_q = pts[0]
            best_tan = pts[1] - pts[0]
            if best_tan.length < 1e-9:
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
            return best_q, best_tan

        # Helper to resolve seed object robustly (legacy + metadata-based).
        def _resolve_seed_for_tid(tid):
            legacy = bpy.data.objects.get(f"SEED_T{tid}")
            if legacy:
                return legacy
            cands = [
                o
                for o in bpy.data.objects
                if o.get("SMILE_LM_TYPE") == "SEED"
                and int(o.get("SMILE_LM_TID", 0)) == int(tid)
            ]
            if cands:
                cands.sort(key=lambda o: float(o.get("SMILE_CREATED_AT", 0.0)))
                return cands[-1]
            pref = f"SEED_T{tid}_"
            pref_cands = [o for o in bpy.data.objects if str(o.name).startswith(pref)]
            if pref_cands:
                pref_cands.sort(key=lambda o: float(o.get("SMILE_CREATED_AT", 0.0)))
                return pref_cands[-1]
            return None

        # Helper to snap to existing segment OR seed
        def snap_to_target(
            tooth_obj, tid, curve_obj=None, scan_obj=None, incisal_curve_obj=None
        ):
            # 1. Check for Manual Seed (Highest Priority)
            seed = _resolve_seed_for_tid(tid)
            if seed:
                # Snap to seed
                loc = seed.matrix_world.translation

                # Keep orientation tied to arch tracer near the seed (do NOT align to local scan normal).
                if curve_obj and curve_obj.type == "CURVE":
                    cpts = curve_world_points(curve_obj)
                    if len(cpts) >= 2:
                        cpos, ctan = _closest_point_and_tangent_on_polyline(loc, cpts)
                        if cpos is not None:
                            is_upper = tid <= 16
                            inc_pts = None
                            if incisal_curve_obj and incisal_curve_obj.type == "CURVE":
                                inc_pts = curve_world_points(incisal_curve_obj)
                            orient_tooth_to_arch(
                                tooth_obj,
                                cpts,
                                ctan,
                                cpos,
                                tid,
                                is_upper=is_upper,
                                scan_obj=scan_obj,
                                incisal_curve_points=inc_pts
                                if inc_pts and len(inc_pts) >= 2
                                else None,
                            )

                # Center tooth geometry on seed (XY only)
                mn, mx = bbox_world(tooth_obj)
                center = (mn + mx) * 0.5
                offset = loc - center

                # Precise Incisal Edge Alignment (Z-Axis)
                # Seed is on the curve -> represents the incisal edge position.
                is_upper = tid <= 16
                # Upper: Incisal is Min Z (Roots Up). Lower: Incisal is Max Z.
                if is_upper:
                    offset.z = loc.z - mn.z
                else:
                    offset.z = loc.z - mx.z

                tooth_obj.matrix_world.translation += offset

                return True

            # 2. Look for segmented scan object (Fallback)
            target_names = [f"Tooth_{tid}", f"Scan_Tooth_{tid}", f"Tooth_{tid:02d}"]
            for name in target_names:
                seg = bpy.data.objects.get(name)
                if seg:
                    # Move to centroid
                    mn, mx = bbox_world(seg)
                    center = (mn + mx) * 0.5
                    tooth_obj.location = center

                    # Match scale (Z height)
                    seg_h = mx.z - mn.z
                    t_mn, t_mx = bbox_world(tooth_obj)
                    t_h = t_mx.z - t_mn.z
                    if t_h > 0.01 and seg_h > 0.01:
                        factor = seg_h / t_h
                        tooth_obj.scale *= factor
                        ensure_active(tooth_obj)
                        bpy.ops.object.transform_apply(
                            location=False, rotation=False, scale=True
                        )

                    return True
            return False

        if imported_max:
            imported_max = sort_teeth_by_id(imported_max)
            for t in imported_max:
                tid = parse_tooth_id_from_name(t.name)
                # Try snapping to seed/segment first
                if snap_to_target(t, tid):
                    continue  # Skip curve layout for this tooth

                # If no seed, keep for curve layout?
                # Actually, distribute_teeth_width_aware places ALL teeth in the list.
                # If we skip some, the curve layout will be gapped?
                # No, we should probably run curve layout on ALL, then override with seeds.
                pass

            # Run bulk distribution for ALL (initial guess)
            if p.lib_spawn_mode == "ARCH":
                if curve_max:
                    try:
                        distribute_teeth_width_aware(
                            curve_max,
                            imported_max,
                            scan_obj=target_max,
                            incisal_curve_obj=curve_max_incisal,
                        )
                    except Exception as e:
                        msg = f"MAX arch distribution failed: {e}"
                        print(f"[BlenderSmile][ImportSelected] {msg}")
                        layout_warnings.append(msg)

                # Re-apply Seed Snaps (Override curve layout)
                for t in imported_max:
                    tid = parse_tooth_id_from_name(t.name)
                    snap_to_target(
                        t,
                        tid,
                        curve_obj=curve_max,
                        scan_obj=target_max,
                        incisal_curve_obj=curve_max_incisal,
                    )
            elif p.lib_spawn_mode == "CURSOR":
                loc = context.scene.cursor.location
                for t in imported_max:
                    t.location = loc
            else:  # ORIGIN
                for t in imported_max:
                    t.location = (0, 0, 0)

            if target_max:
                for t in imported_max:
                    smart_parent(t, target_max)

        if imported_man:
            imported_man = sort_teeth_by_id(imported_man)

            if p.lib_spawn_mode == "ARCH":
                if curve_man:
                    try:
                        distribute_teeth_width_aware(
                            curve_man,
                            imported_man,
                            scan_obj=target_man,
                            incisal_curve_obj=curve_man_incisal,
                        )
                    except Exception as e:
                        msg = f"MAN arch distribution failed: {e}"
                        print(f"[BlenderSmile][ImportSelected] {msg}")
                        layout_warnings.append(msg)

                for t in imported_man:
                    tid = parse_tooth_id_from_name(t.name)
                    snap_to_target(
                        t,
                        tid,
                        curve_obj=curve_man,
                        scan_obj=target_man,
                        incisal_curve_obj=curve_man_incisal,
                    )
            elif p.lib_spawn_mode == "CURSOR":
                loc = context.scene.cursor.location
                for t in imported_man:
                    t.location = loc
            else:  # ORIGIN
                for t in imported_man:
                    t.location = (0, 0, 0)

            if target_man:
                for t in imported_man:
                    smart_parent(t, target_man)

        # Ensure arch curves remain visible after import
        for c_obj in [curve_max, curve_man]:
            if c_obj:
                c_obj.hide_viewport = False
                c_obj.hide_set(False)

        # Also ensure the SmileArch collection + view layer collection are visible
        arch_col = bpy.data.collections.get(COL_ARCH)
        if arch_col:
            arch_col.hide_viewport = False

            # Unhide view-layer collection (the outliner "eye" icon)
            def _unhide_layer_col(layer_col):
                if layer_col.collection == arch_col:
                    layer_col.hide_viewport = False
                    return True
                for child in layer_col.children:
                    if _unhide_layer_col(child):
                        return True
                return False

            _unhide_layer_col(bpy.context.view_layer.layer_collection)

        imported_meshes = [
            o
            for o in (imported_max + imported_man)
            if o and o.type == "MESH" and o.name in bpy.data.objects
        ]
        pinned_ok, pinned_name = _cad_autopin_reference_from_import(
            context,
            imported_meshes,
            preferred_obj=context.view_layer.objects.active,
            force_replace=False,
        )
        _refresh_imported_mdc_status_list(context.scene)
        msg = f"Imported & Placed {count} teeth (Scale {scale_factor:.2f})."
        if pinned_ok and pinned_name:
            msg += f" Reference pinned: {pinned_name}."
        if layout_warnings:
            shown = min(2, len(layout_warnings))
            for warn in layout_warnings[:shown]:
                self.report({"WARNING"}, warn)
            if len(layout_warnings) > shown:
                self.report(
                    {"WARNING"},
                    f"{len(layout_warnings) - shown} additional layout warning(s); see system console.",
                )
        self.report({"INFO"}, msg)
        return {"FINISHED"}

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


def detect_facial_surface_by_convexity(obj):
    """
    Detect which side of tooth is facial (buccal) based on surface curvature.
    Facial surface is typically more convex than lingual (which has cingulum).

    Args:
        obj: Tooth mesh object

    Returns:
        Vector pointing towards facial direction (world space)
    """
    import bmesh

    # Get mesh data in world space
    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()

    try:
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            bm.verts.ensure_lookup_table()

            # Calculate mean curvature per vertex (simplified)
            # Higher positive curvature = more convex (likely facial)
            curvatures = []
            positions = []

            for v in bm.verts:
                # Simple curvature approximation: compare vertex to neighbor average
                if len(v.link_edges) == 0:
                    continue

                neighbor_avg = Vector()
                for e in v.link_edges:
                    other = e.other_vert(v)
                    neighbor_avg += other.co
                neighbor_avg /= len(v.link_edges)

                # Distance from vertex to neighbor average (positive = convex)
                normal_dir = v.normal
                displacement = v.co - neighbor_avg
                curvature = displacement.dot(normal_dir)

                curvatures.append(curvature)
                positions.append(obj.matrix_world @ v.co)
        finally:
            bm.free()

        # Find most convex region (top 20% of curvature values)
        if not curvatures:
            return Vector((0, -1, 0))  # Default: -Y is facial

        sorted_indices = sorted(
            range(len(curvatures)), key=lambda i: curvatures[i], reverse=True
        )
        top_20_percent = int(len(sorted_indices) * 0.2)
        convex_indices = sorted_indices[: max(top_20_percent, 1)]

        # Calculate average position of convex region
        convex_center = Vector()
        for idx in convex_indices:
            convex_center += positions[idx]
        convex_center /= len(convex_indices)

        # Direction from object center to convex region
        _diff = convex_center - obj.location
        facial_dir = _diff.normalized() if _diff.length_squared > 1e-12 else Vector((0, -1, 0))

        return facial_dir

    finally:
        eo.to_mesh_clear()


def detect_incisal_edge_by_geometry(obj):
    """
    Detect incisal edge/cusp tip by finding lowest point or sharpest edge.

    Args:
        obj: Tooth mesh object

    Returns:
        (incisal_point_world, incisal_point_local, cervical_direction_vector)
    """
    # Get mesh data in world space
    deps = bpy.context.evaluated_depsgraph_get()
    eo = obj.evaluated_get(deps)
    me = eo.to_mesh()

    try:
        # Find bounding box in world space
        verts_world = [obj.matrix_world @ v.co for v in me.vertices]
        verts_local = [v.co.copy() for v in me.vertices]

        if not verts_world:
            return obj.location, Vector((0, 0, 0)), Vector((0, 0, 1))

        # Find Z-range in world space
        z_coords = [v.z for v in verts_world]
        z_min = min(z_coords)
        z_max = max(z_coords)
        z_range = z_max - z_min

        # Incisal edge is typically at lowest 20% of Z-range
        # (Standard dental: -Z is incisal, +Z is cervical)
        threshold_z = z_min + (z_range * 0.2)

        # Collect vertices in incisal region
        incisal_indices = [i for i, v in enumerate(verts_world) if v.z <= threshold_z]

        if not incisal_indices:
            incisal_indices = [0]

        # Calculate centroid of incisal vertices in world space
        incisal_point_world = Vector()
        for i in incisal_indices:
            incisal_point_world += verts_world[i]
        incisal_point_world /= len(incisal_indices)

        # Calculate centroid in local space
        incisal_point_local = Vector()
        for i in incisal_indices:
            incisal_point_local += verts_local[i]
        incisal_point_local /= len(incisal_indices)

        # Cervical direction is opposite (towards root, +Z)
        cervical_direction = Vector((0, 0, 1))

        return incisal_point_world, incisal_point_local, cervical_direction

    finally:
        eo.to_mesh_clear()


def calculate_orientation_from_anatomical_points(
    incisal_point, facial_point, tooth_center
):
    """
    Calculate rotation matrix from marked anatomical points.

    Args:
        incisal_point: 3D point on incisal edge
        facial_point: 3D point on facial/buccal surface
        tooth_center: Object origin/center

    Returns:
        4x4 rotation matrix
    """
    # Calculate direction vectors
    # C-I axis: tooth_center → incisal_point (normalized)
    _ci_diff = incisal_point - tooth_center
    ci_axis = _ci_diff.normalized() if _ci_diff.length_squared > 1e-12 else Vector((0, 0, -1))

    # B-L axis: tooth_center → facial_point (normalized)
    _bl_diff = facial_point - tooth_center
    bl_axis = _bl_diff.normalized() if _bl_diff.length_squared > 1e-12 else Vector((0, -1, 0))

    # M-D axis: cross product of C-I and B-L
    _md_cross = ci_axis.cross(bl_axis)
    md_axis = _md_cross.normalized() if _md_cross.length_squared > 1e-12 else Vector((1, 0, 0))

    # Rebuild B-L axis to ensure orthogonality
    _bl_cross = md_axis.cross(ci_axis)
    bl_axis = _bl_cross.normalized() if _bl_cross.length_squared > 1e-12 else Vector((0, -1, 0))

    # Build rotation matrix
    # Standard dental coordinates:
    #   X = Mesial/Distal (md_axis)
    #   Y = Lingual/Facial (bl_axis, but facial is -Y)
    #   Z = Cervical/Incisal (ci_axis, but incisal is -Z)

    rot_matrix = Matrix.Identity(4)
    rot_matrix[0][0:3] = md_axis
    rot_matrix[1][0:3] = -bl_axis  # Facial is -Y
    rot_matrix[2][0:3] = -ci_axis  # Incisal is -Z

    return rot_matrix


def apply_angulation_preset(rot_matrix, preset="Natural", custom_angle=0.0):
    """
    Apply preset angulation adjustments to tooth orientation.

    Presets:
        - Natural: Slight lingual tilt (~2-3 degrees)
        - Aggressive: More visible from front (~5-7 degrees)
        - Conservative: Tucked in (~0-1 degree)
        - Custom: User-defined angle

    Args:
        rot_matrix: Base rotation matrix (3x3 or 4x4)
        preset: Preset name
        custom_angle: Custom angulation angle in radians (if preset='Custom')

    Returns:
        Adjusted rotation matrix (4x4)
    """
    import math

    # Convert to 4x4 if needed
    if rot_matrix.row_size == 3:
        mat_4x4 = Matrix.Identity(4)
        mat_4x4[0][0:3] = rot_matrix[0]
        mat_4x4[1][0:3] = rot_matrix[1]
        mat_4x4[2][0:3] = rot_matrix[2]
        rot_matrix = mat_4x4

    # Determine angulation angle based on preset
    angle_map = {
        "NONE": 0.0,
        "NATURAL": math.radians(2.5),
        "AGGRESSIVE": math.radians(6.0),
        "CONSERVATIVE": math.radians(1.0),
        "CUSTOM": custom_angle,
    }

    angle = angle_map.get(preset, 0.0)

    if abs(angle) < 0.001:  # No rotation needed
        return rot_matrix

    # Apply rotation around X-axis (mesial-distal axis)
    # Positive angle = lingual tilt (tooth leans back)
    angulation_rot = Matrix.Rotation(angle, 4, "X")

    return angulation_rot @ rot_matrix


def create_axis_gizmo(obj, size=0.005, auto_delete_seconds=3):
    """
    Create RGB axis gizmo on object for orientation visualization.

    Args:
        obj: Object to attach gizmo to
        size: Arrow length in scene units
        auto_delete_seconds: Auto-delete after this time (0 = manual)

    Returns:
        List of arrow objects created
    """
    arrows = []
    colors = [
        (1, 0, 0, 1),  # X = Red
        (0, 1, 0, 1),  # Y = Green
        (0, 0, 1, 1),  # Z = Blue
    ]
    axes = ["X", "Y", "Z"]
    directions = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]

    for i, axis in enumerate(axes):
        # Create arrow as simple line mesh
        name = f"{obj.name}_Axis_{axis}"

        # Remove existing if present
        existing = bpy.data.objects.get(name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)

        # Create mesh for arrow (cylinder + cone)
        mesh_data = bpy.data.meshes.new(name + "_mesh")
        arrow_obj = bpy.data.objects.new(name, mesh_data)
        bpy.context.scene.collection.objects.link(arrow_obj)

        # Create simple line geometry
        import bmesh

        bm = bmesh.new()
        try:
            # Line from origin to direction
            v1 = bm.verts.new((0, 0, 0))
            v2 = bm.verts.new(directions[i] * size)
            bm.edges.new([v1, v2])

            bm.to_mesh(mesh_data)
        finally:
            bm.free()

        # Position at object location
        arrow_obj.location = obj.location
        arrow_obj.rotation_euler = obj.rotation_euler
        arrow_obj.parent = obj

        # Create emission material for color
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

        # Mark for auto-deletion
        if auto_delete_seconds > 0:
            arrow_obj["AUTO_DELETE_TIME"] = time.time() + auto_delete_seconds

    return arrows


# ============================================================
# TRI-CURVE SYSTEM: Golden Ruler Import Enhancement
# ============================================================


def find_curve_with_priority(curve_names, context_msg=""):
    """
    Find first existing curve from priority list.

    Args:
        curve_names: List of curve object names in priority order
        context_msg: Context message for debug output

    Returns:
        (curve_obj, curve_name_found) or (None, None)
    """
    for name in curve_names:
        obj = bpy.data.objects.get(name)
        if obj and obj.type == "CURVE":
            print(f"DEBUG {context_msg}: Using '{name}'")
            return obj, name
    print(f"DEBUG {context_msg}: No curves found from {curve_names}")
    return None, None


def find_existing_tooth_for_angulation(tooth_id, collection_name=COL_TEETH):
    """
    Find adjacent existing tooth to copy rotation from.
    Priority: Immediate neighbor > Same quadrant > Any tooth

    Args:
        tooth_id: Target tooth ID (1-32)
        collection_name: Collection to search in

    Returns:
        tooth_object or None
    """
    col = bpy.data.collections.get(collection_name)
    if not col:
        return None

    # Find existing teeth with IDs
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

    # Priority 1: Immediate neighbor (±1)
    for tid, obj in existing:
        if abs(tid - tooth_id) == 1:
            return obj

    # Priority 2: Same quadrant (within 8 teeth)
    for tid, obj in existing:
        if abs(tid - tooth_id) <= 8:
            return obj

    # Priority 3: Any tooth
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
    """
    Evaluate tooth position using tri-curve system:
    - Lateral curve: X/Y arch positioning (ARCH_MAX_CURVE or Golden Ruler)
    - Depth curve: Z-height for smile depth (SMILE_Golden_Arch or Lip Line)
    - Angulation: Optional reference from existing teeth
    - Embedding: Optional bucco-lingual embedding (EMBEDDING_SYSTEM)

    Args:
        lateral_curve: Curve object for X/Y positioning
        depth_curve: Curve object for Z/depth (can be same as lateral)
        t: Parameter 0.0-1.0 along curve
        tooth_bbox: (min_vec, max_vec) bounding box of tooth in local space
        angulation_reference: Optional tooth object to copy rotation from
        incisal_point_local: Optional Vector of detected incisal point in local coordinates
        midline_local: Optional Vector of bucco-lingual midline in local coordinates (EMBEDDING_SYSTEM)
        embedding_depth: Float 0.0-1.0, how much tooth is embedded (0.5=half) (EMBEDDING_SYSTEM)
        facial_lingual_axis: Optional Vector for facial-lingual direction (world space) (EMBEDDING_SYSTEM)

    Returns:
        (position_vector, rotation_matrix, tangent_vector)
    """

    # 1. Sample lateral curve for X/Y positioning
    lateral_pos = evaluate_curve_at_parameter(lateral_curve, t)

    # Calculate tangent numerically (same as original code)
    pos_next = evaluate_curve_at_parameter(lateral_curve, min(t + 0.01, 1.0))
    pos_prev = evaluate_curve_at_parameter(lateral_curve, max(t - 0.01, 0.0))
    _tan_diff = pos_next - pos_prev
    lateral_tangent = _tan_diff.normalized() if _tan_diff.length_squared > 1e-12 else Vector((1, 0, 0))

    # 2. Sample depth curve for Z positioning (incisal edge target)
    if depth_curve and depth_curve != lateral_curve:
        depth_pos = evaluate_curve_at_parameter(depth_curve, t)
        target_z = depth_pos.z  # Use depth curve's Z coordinate
    else:
        target_z = lateral_pos.z  # Fallback to lateral curve

    # 3. Hybrid position: lateral X/Y + depth Z
    incisal_target = Vector((lateral_pos.x, lateral_pos.y, target_z))

    # 4. Calculate tooth origin position
    # Use detected incisal point if available, otherwise fall back to bbox
    if incisal_point_local:
        # Use detected incisal point (more accurate for cusps and edges)
        incisal_offset = -incisal_point_local.z  # Make positive
    else:
        # Fallback: Tooth bbox min.z is incisal edge (negative value below origin)
        incisal_offset = -tooth_bbox[0].z  # Make positive

    tooth_origin = incisal_target + Vector((0, 0, incisal_offset))

    # 5. Calculate rotation matrix
    if angulation_reference:
        # Copy rotation from existing tooth
        rot_matrix = angulation_reference.matrix_world.to_3x3().to_4x4()
    else:
        # Standard: align to lateral curve tangent
        up_vec = Vector((0, 0, 1))
        rot_x = lateral_tangent
        rot_y = up_vec.cross(rot_x).normalized()  # Lingual direction
        rot_z = rot_x.cross(rot_y).normalized()  # Up direction

        rot_matrix = Matrix.Identity(4)
        rot_matrix[0][0], rot_matrix[1][0], rot_matrix[2][0] = rot_x
        rot_matrix[0][1], rot_matrix[1][1], rot_matrix[2][1] = rot_y
        rot_matrix[0][2], rot_matrix[1][2], rot_matrix[2][2] = rot_z

    # ========== EMBEDDING_SYSTEM: Apply bucco-lingual embedding offset ==========
    # Position tooth so that the bucco-lingual midline aligns with the depth curve,
    # allowing a configurable portion of the tooth to be embedded in the underlying model
    if midline_local is not None and facial_lingual_axis is not None:
        # Calculate how far the midline is from the origin in local space
        # Positive = facial side, Negative = lingual side
        midline_offset_local = midline_local.copy()

        # Calculate embedding offset
        # embedding_depth = 0.0 → lingual surface at depth curve (fully facial/visible)
        # embedding_depth = 0.5 → midline at depth curve (half embedded) ← DEFAULT
        # embedding_depth = 1.0 → facial surface at depth curve (fully embedded)

        # We want to shift the tooth along the facial-lingual axis so that
        # the appropriate point aligns with the depth curve
        # The offset is: (0.5 - embedding_depth) * distance_from_midline_to_surface

        # Project midline offset onto facial-lingual axis
        # Use the facial_lingual_axis to determine the embedding direction
        embedding_offset_world = (
            facial_lingual_axis
            * (0.5 - embedding_depth)
            * midline_offset_local.length
            * 2.0
        )

        # Apply embedding offset to tooth origin
        tooth_origin += embedding_offset_world
    # ========== END EMBEDDING_SYSTEM ==========

    return tooth_origin, rot_matrix, lateral_tangent


# ============================================================
# PRE-IMPORT ORIENTATION CORRECTION
# ============================================================


def get_pre_import_orientation_correction(
    library_preset, custom_x=0, custom_y=0, custom_z=0
):
    """
    Get rotation matrix to correct library orientation to standard dental coordinates.

    Standard dental orientation:
    - X-axis: Mesial-Distal (left-right)
    - Y-axis: Lingual-Facial (facial is -Y)
    - Z-axis: Cervical-Incisal (incisal is -Z, down)

    Args:
        library_preset: Preset name from library_orientation_preset enum
        custom_x/y/z: Custom rotation angles in radians (if preset='CUSTOM')

    Returns:
        4x4 rotation matrix to apply to imported tooth mesh
    """
    import math
    from mathutils import Matrix, Euler

    if library_preset == "STANDARD":
        # No correction needed
        return Matrix.Identity(4)

    elif library_preset == "INVERTED_Z":
        # Incisal pointing up (+Z), need to flip upside down
        # Rotate 180° around X-axis
        return Matrix.Rotation(math.radians(180), 4, "X")

    elif library_preset == "INVERTED_Y":
        # Facial pointing backward (+Y), need to flip front-back
        # Rotate 180° around Z-axis
        return Matrix.Rotation(math.radians(180), 4, "Z")

    elif library_preset == "ROTATED_90X":
        # Rotated 90° around X
        return Matrix.Rotation(math.radians(90), 4, "X")

    elif library_preset == "ROTATED_90Y":
        # Rotated 90° around Y
        return Matrix.Rotation(math.radians(90), 4, "Y")

    elif library_preset == "ROTATED_180Y":
        # Mirrored left-right
        return Matrix.Rotation(math.radians(180), 4, "Y")

    elif library_preset == "CUSTOM":
        # Apply custom rotation using Euler angles
        euler = Euler((custom_x, custom_y, custom_z), "XYZ")
        return euler.to_matrix().to_4x4()

    else:
        # Unknown preset, return identity
        return Matrix.Identity(4)


class SMILE_OT_verify_golden_orientation(bpy.types.Operator):
    """Modal operator for 2-click orientation verification"""

    bl_idname = "smile.verify_golden_orientation"
    bl_label = "Verify Tooth Orientation (2-Click)"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    tooth_obj_name: bpy.props.StringProperty()

    _clicks = []  # Store clicked points
    _original_matrix = None  # Backup for undo
    _markers = []  # Visual markers

    def invoke(self, context, event):
        """Start modal interaction"""
        self._clicks = []
        self._markers = []
        tooth_obj = bpy.data.objects.get(self.tooth_obj_name)

        if not tooth_obj:
            self.report({"ERROR"}, "Tooth object not found")
            return {"CANCELLED"}

        # Backup original orientation
        self._original_matrix = tooth_obj.matrix_world.copy()

        # Add modal handler
        context.window_manager.modal_handler_add(self)

        # Draw temporary axis gizmo
        self._draw_axis_gizmo(tooth_obj)

        self.report({"INFO"}, "Click 1: Incisal edge, Click 2: Facial center")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        """Handle mouse clicks"""
        # Navigation pass-through
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        # Cancel
        if event.type in {"RIGHTMOUSE", "ESC"}:
            # Restore original orientation
            tooth_obj = bpy.data.objects.get(self.tooth_obj_name)
            if tooth_obj:
                tooth_obj.matrix_world = self._original_matrix
            self._cleanup_markers()
            return {"CANCELLED"}

        # Left click = mark point
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            tooth_obj = bpy.data.objects.get(self.tooth_obj_name)
            if not tooth_obj:
                return {"CANCELLED"}

            # Raycast to tooth
            hit = raycast_from_mouse_to_target(context, event, tooth_obj)
            if hit:
                loc, norm, fi = hit
                self._clicks.append(loc)

                # Visual marker
                self._add_click_marker(loc, len(self._clicks))

                if len(self._clicks) == 1:
                    self.report({"INFO"}, "Click 2: Facial center")
                elif len(self._clicks) == 2:
                    # Calculate and apply orientation
                    self._apply_orientation_from_clicks(context, tooth_obj)
                    return {"FINISHED"}

            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def _apply_orientation_from_clicks(self, context, tooth_obj):
        """Calculate orientation from 2 clicks"""
        incisal_pt = self._clicks[0]
        facial_pt = self._clicks[1]
        tooth_center = tooth_obj.location

        # Calculate rotation matrix
        rot_matrix = calculate_orientation_from_anatomical_points(
            incisal_pt, facial_pt, tooth_center
        )

        # Apply angulation preset
        p = context.scene.smile_v2
        preset = p.get("golden_angulation_preset", "NATURAL")
        custom_angle = p.get("golden_custom_angulation", 0.0)

        rot_matrix = apply_angulation_preset(rot_matrix, preset, custom_angle)

        # Apply rotation only, preserve location
        tooth_obj.matrix_world = rot_matrix
        tooth_obj.location = tooth_center

        self.report({"INFO"}, "Orientation verified and applied")
        self._cleanup_markers()

    def _add_click_marker(self, location, number):
        """Add visual marker at clicked point"""
        # Create small sphere marker
        name = f"ORIENT_MARKER_{number}"

        # Remove existing if present
        existing = bpy.data.objects.get(name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)

        # Create marker
        mesh = bpy.data.meshes.new(name + "_mesh")
        marker_obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(marker_obj)

        # Create simple UV sphere
        import bmesh

        bm = bmesh.new()
        try:
            bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=8, radius=0.001)
            bm.to_mesh(mesh)
        finally:
            bm.free()

        marker_obj.location = location

        # Color: 1=Red (incisal), 2=Green (facial)
        color = (1, 0, 0, 1) if number == 1 else (0, 1, 0, 1)

        # Create emission material
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
        """Draw RGB axes on tooth (temporary)"""
        arrows = create_axis_gizmo(tooth_obj, size=0.005, auto_delete_seconds=0)
        self._markers.extend(arrows)

    def _cleanup_markers(self):
        """Remove all visual markers"""
        for marker in self._markers:
            if marker and marker.name in bpy.data.objects:
                bpy.data.objects.remove(marker, do_unlink=True)
        self._markers.clear()


class SMILE_OT_import_golden_set(bpy.types.Operator):
    bl_idname = "smile.import_golden_set"
    bl_label = "Import Golden Set (6-11)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        print(f"DEBUG: Starting Golden Import (Active Set: {p.active_library_name})")

        # 1. Find Ruler Components
        ruler = bpy.data.objects.get("SMILE_Golden_Ruler")

        # TRI-CURVE SYSTEM: Find lateral curve (X/Y positioning)
        lateral_curve, lateral_name = find_curve_with_priority(
            [
                "ARCH_MAX_CURVE",  # Priority 1: Manual traced arch
                "SMILE_Golden_Ruler_Arch",  # Priority 2: Auto-generated arch
                "SMILE_Golden_Ruler",  # Priority 3: Linear ruler
            ],
            "Lateral Positioning",
        )

        # TRI-CURVE SYSTEM: Find depth curve (Z positioning)
        depth_curve, depth_name = find_curve_with_priority(
            [
                "SMILE_Golden_Arch",  # Priority 1: Smile depth with slider
                "SMILE_Lip_Curve",  # Priority 2: User-drawn lip line
                lateral_name,  # Priority 3: Same as lateral
            ],
            "Depth/Incisal",
        )

        if not lateral_curve:
            print("ERROR: No arch curve found!")
            self.report(
                {"ERROR"},
                "No arch curve found. Draw Golden Ruler or trace an arch first.",
            )
            return {"CANCELLED"}

        # Debug output
        print(f"DEBUG: Golden Import Tri-Curve Config:")
        print(f"  Ruler: {ruler.name if ruler else 'None (using arch curve fallback)'}")
        print(f"  Lateral: {lateral_name}")
        print(f"  Depth: {depth_name}")
        print(f"  Using tri-curve: {depth_curve != lateral_curve}")

        # 2. Get Data
        if ruler:
            # Standard path: read data from Golden Ruler object
            offsets = list(ruler.get("SMILE_OFFSETS", []))
            if len(offsets) < 7:  # Need 6 segments (7 points)
                print(f"ERROR: Offsets invalid (len={len(offsets)})")
                self.report({"ERROR"}, "Ruler data invalid/missing.")
                return {"CANCELLED"}
            else:
                print(f"DEBUG: Found {len(offsets)} offsets")
            p1 = Vector(ruler["SMILE_P1"])
            p2 = Vector(ruler["SMILE_P2"])
            total_len = (p1 - p2).length
            print(f"DEBUG: Ruler Length: {total_len:.2f}")
        else:
            # Fallback path: derive data from arch curve (e.g. ARCH_MAX_CURVE)
            # Use golden ratio proportions (same math as update_golden_ruler)
            mode = p.golden_ruler_mode
            if mode == "CLASSIC":
                tr = 6.472
                wc, wl, wk = 1.618 / tr, 1.0 / tr, 0.618 / tr
            else:
                # Gauge 12-15-23 (Default)
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
            # Derive endpoints from arch curve
            p1 = evaluate_curve_at_parameter(lateral_curve, 0.0)
            p2 = evaluate_curve_at_parameter(lateral_curve, 1.0)
            # Calculate arc length by sampling the curve (not chord distance)
            # Chord distance underestimates curved arches and makes teeth too narrow
            arc_samples = 64
            arc_len = 0.0
            prev_pt = evaluate_curve_at_parameter(lateral_curve, 0.0)
            for si in range(1, arc_samples + 1):
                st = si / arc_samples
                cur_pt = evaluate_curve_at_parameter(lateral_curve, st)
                arc_len += (cur_pt - prev_pt).length
                prev_pt = cur_pt
            total_len = arc_len
            if total_len < 0.001:
                print("ERROR: Arch curve too short or invalid!")
                self.report({"ERROR"}, "Arch curve too short or invalid.")
                return {"CANCELLED"}
            print(f"DEBUG: No ruler — derived data from {lateral_name}")
            print(f"  P1: ({p1.x:.3f}, {p1.y:.3f}, {p1.z:.3f})")
            print(f"  P2: ({p2.x:.3f}, {p2.y:.3f}, {p2.z:.3f})")
            print(f"  Chord distance: {(p1 - p2).length:.2f}")
            print(f"  Arc length: {total_len:.2f}")
            print(f"  Offsets: {[f'{o:.3f}' for o in offsets]}")

        # 3. Define Set
        # P1 (Min X) -> #6. P2 (Max X) -> #11.
        tooth_ids = [6, 7, 8, 9, 10, 11]

        # 4. Loop & Import
        cnt = 0

        # Cache active library assets for lookup
        set_name = p.active_library_name
        assets = LibraryManager.sets.get(set_name, [])
        asset_map = {a.tooth_id: a for a in assets}
        print(f"DEBUG: Assets mapped for set '{set_name}': {list(asset_map.keys())}")

        for i, tid in enumerate(tooth_ids):
            if tid not in asset_map:
                print(f"Skip #{tid}: Not in library map")
                continue

            # A. Calculate Parameters from Ruler
            t_start = offsets[i]
            t_end = offsets[i + 1]
            t_mid = (t_start + t_end) / 2.0

            # Width (Linear Approx with user scale multiplier)
            target_w = (t_end - t_start) * total_len * p.golden_ruler_width_scale

            # B. Import
            asset = asset_map[tid]
            filepath = asset.filepath
            print(f"DEBUG: Importing #{tid} from {filepath}")

            meshes = import_mesh_file(filepath)
            if not meshes:
                print(f"ERROR: Import failed for #{tid}")
                continue
            obj = meshes[0]

            # === PRE-IMPORT ORIENTATION CORRECTION ===
            # Apply library orientation correction BEFORE any other processing
            correction_matrix = get_pre_import_orientation_correction(
                p.library_orientation_preset,
                math.radians(p.library_custom_rotation_x),
                math.radians(p.library_custom_rotation_y),
                math.radians(p.library_custom_rotation_z),
            )

            if correction_matrix != Matrix.Identity(4):
                # Apply correction to mesh data (local space)
                obj.data.transform(correction_matrix)
                obj.data.update()
                print(
                    f"  Tooth #{tid}: Applied pre-import correction ({p.library_orientation_preset})"
                )
            # === END PRE-IMPORT ORIENTATION CORRECTION ===

            link_to_collection(obj, ensure_collection(COL_TEETH))
            ensure_tooth_params(obj)
            ensure_active(obj)  # for bbox

            # Mark as golden set import for deletion tracking
            obj["SMILE_GOLDEN_SET_IMPORT"] = True
            obj["SMILE_GOLDEN_SET_TOOTH_ID"] = tid
            obj["SMILE_CREATED_AT"] = float(time.time())

            # C. Scale (Canonically)
            obj.rotation_euler = (0, 0, 0)
            bpy.context.view_layer.update()

            mn, mx = bbox_world(obj)
            curr_w = mx.x - mn.x

            if curr_w > 0.1:
                scale = target_w / curr_w
                obj.scale = (scale, scale, scale)
                bpy.ops.object.transform_apply(
                    location=False, rotation=False, scale=True
                )
                print(
                    f"  Tooth #{tid}: Scaled {curr_w:.3f}mm → {target_w:.3f}mm (factor: {scale:.3f}x, width_scale: {p.golden_ruler_width_scale:.2f})"
                )
            else:
                print(
                    f"  WARNING: Tooth #{tid} width too small ({curr_w:.3f}mm), skipping scale"
                )

            # === ORIENTATION ENHANCEMENT (PHASE 3) ===
            # Step 1: Auto-detect and correct orientation
            # NOTE: Skip Phase 3 if pre-import correction was applied (mutual exclusion)
            if p.golden_auto_orient and p.library_orientation_preset == "STANDARD":
                try:
                    # Detect facial surface
                    facial_dir = detect_facial_surface_by_convexity(obj)

                    # Detect incisal edge (now returns world, local, and cervical direction)
                    incisal_pt_world, incisal_pt_local, cervical_dir = (
                        detect_incisal_edge_by_geometry(obj)
                    )

                    # Store detected incisal points for positioning
                    obj["SMILE_INCISAL_POINT_WORLD"] = tuple(incisal_pt_world)
                    obj["SMILE_INCISAL_POINT_LOCAL"] = tuple(incisal_pt_local)

                    print(f"  Tooth #{tid}: Detected incisal point")
                    print(
                        f"    World: ({incisal_pt_world.x:.3f}, {incisal_pt_world.y:.3f}, {incisal_pt_world.z:.3f})"
                    )
                    print(
                        f"    Local: ({incisal_pt_local.x:.3f}, {incisal_pt_local.y:.3f}, {incisal_pt_local.z:.3f})"
                    )

                    # Calculate correction matrix
                    correction_matrix = calculate_orientation_from_anatomical_points(
                        incisal_pt_world, obj.location + facial_dir, obj.location
                    )

                    # Apply angulation preset
                    preset = p.golden_angulation_preset
                    custom_angle = (
                        math.radians(p.golden_custom_angulation)
                        if preset == "CUSTOM"
                        else 0.0
                    )
                    correction_matrix = apply_angulation_preset(
                        correction_matrix, preset, custom_angle
                    )

                    # Apply correction to mesh data (local space)
                    obj.data.transform(
                        correction_matrix.inverted() @ obj.matrix_world.inverted()
                    )
                    obj.matrix_world = correction_matrix
                    obj.data.update()

                    # Store orientation metadata
                    obj["SMILE_ORIENTATION_METHOD"] = "AUTO"
                    obj["SMILE_ANGULATION_PRESET"] = preset
                    obj["SMILE_FACIAL_VECTOR"] = tuple(facial_dir)

                    print(
                        f"  Tooth #{tid}: Auto-oriented (facial detected, preset={preset})"
                    )

                except Exception as e:
                    print(f"  Tooth #{tid}: Auto-orientation failed: {e}")
                    # Continue without auto-orientation

            # Step 2: Optional manual verification (first tooth only)
            if p.golden_verify_orientation and i == 0:
                # Pause import, show modal
                obj["SMILE_ORIENTATION_METHOD"] = "MANUAL"

                # Show axis preview if enabled
                if p.golden_show_axis_preview:
                    create_axis_gizmo(obj, size=0.005, auto_delete_seconds=3)

                # Invoke modal verification (blocks until user completes)
                bpy.ops.smile.verify_golden_orientation(
                    "INVOKE_DEFAULT", tooth_obj_name=obj.name
                )

                # Store verification flag
                obj["SMILE_VERIFIED_ORIENTATION"] = True

                print(f"  Tooth #{tid}: Manual verification completed")

            # Step 3: Propagate orientation to subsequent teeth
            if i > 0 and p.golden_verify_orientation:
                # Find first tooth with verified orientation
                first_tooth = None
                for prev_tid in tooth_ids[:i]:
                    prev_obj = bpy.data.objects.get(f"Tooth#{prev_tid}")
                    if prev_obj and prev_obj.get("SMILE_VERIFIED_ORIENTATION"):
                        first_tooth = prev_obj
                        break

                if first_tooth:
                    # Copy mesh-space orientation (rotation only, not position)
                    # Extract rotation from first tooth's world matrix
                    first_rot = first_tooth.matrix_world.to_3x3().to_4x4()

                    # Mirror if contralateral (left vs right)
                    # Teeth #6-8 are right side, #9-11 are left side
                    first_tid = first_tooth.get("SMILE_GOLDEN_SET_TOOTH_ID")
                    if first_tid:
                        is_first_right = first_tid <= 8
                        is_current_right = tid <= 8

                        if is_first_right != is_current_right:
                            # Apply X-axis mirror for contralateral teeth
                            mirror_matrix = Matrix.Scale(-1, 4, (1, 0, 0))
                            obj.data.transform(mirror_matrix)
                            obj.data.update()
                            print(f"  Tooth #{tid}: Mirrored from Tooth #{first_tid}")
                        else:
                            print(
                                f"  Tooth #{tid}: Copied orientation from Tooth #{first_tid}"
                            )

                    obj["SMILE_ORIENTATION_METHOD"] = "REFERENCE"
                    obj["SMILE_VERIFIED_ORIENTATION"] = True

            # Show axis preview if enabled (and not already shown in verification)
            if p.golden_show_axis_preview and not (
                p.golden_verify_orientation and i == 0
            ):
                create_axis_gizmo(obj, size=0.005, auto_delete_seconds=3)

            # === END ORIENTATION ENHANCEMENT ===

            # === RAYCAST FALLBACK FOR INCISAL DETECTION ===
            # If auto-orientation was skipped, use raycast to detect incisal point
            if "SMILE_INCISAL_POINT_LOCAL" not in obj:
                # Calculate approximate target position from depth curve
                depth_pos = evaluate_curve_at_parameter(depth_curve, t_mid)

                # Try raycast detection
                hit_world, hit_local = detect_incisal_by_raycast(obj, depth_pos)

                if hit_world and hit_local:
                    obj["SMILE_INCISAL_POINT_WORLD"] = tuple(hit_world)
                    obj["SMILE_INCISAL_POINT_LOCAL"] = tuple(hit_local)
                    print(f"  Tooth #{tid}: Raycast detected incisal point")
                    print(
                        f"    World: ({hit_world.x:.3f}, {hit_world.y:.3f}, {hit_world.z:.3f})"
                    )
                    print(
                        f"    Local: ({hit_local.x:.3f}, {hit_local.y:.3f}, {hit_local.z:.3f})"
                    )
                else:
                    print(f"  Tooth #{tid}: Raycast failed, will use bbox fallback")
            # === END RAYCAST FALLBACK ===

            # ========== EMBEDDING_SYSTEM: Bucco-Lingual Embedding Detection ==========
            # Detect the bucco-lingual midline for embedding positioning
            if p.golden_enable_embedding:
                try:
                    # Get facial direction (may already be detected during orientation)
                    facial_dir = None
                    if "SMILE_FACIAL_VECTOR" in obj:
                        facial_dir = Vector(obj["SMILE_FACIAL_VECTOR"])

                    # Calculate bucco-lingual midline
                    midline_world, midline_local, bl_dimension, fl_axis = (
                        calculate_buccolingual_midline(obj, facial_dir=facial_dir)
                    )

                    # Store for positioning
                    obj["SMILE_BUCCOLINGUAL_MIDLINE_WORLD"] = tuple(midline_world)
                    obj["SMILE_BUCCOLINGUAL_MIDLINE_LOCAL"] = tuple(midline_local)
                    obj["SMILE_BUCCOLINGUAL_DIMENSION"] = bl_dimension
                    obj["SMILE_FACIAL_LINGUAL_AXIS"] = tuple(fl_axis)

                    print(f"  Tooth #{tid}: Bucco-lingual embedding detected")
                    print(
                        f"    Midline (local): ({midline_local.x:.3f}, {midline_local.y:.3f}, {midline_local.z:.3f})"
                    )
                    print(f"    BL Dimension: {bl_dimension:.3f}mm")
                    print(f"    Embedding depth: {p.golden_embedding_depth * 100:.0f}%")

                except Exception as e:
                    print(f"  Tooth #{tid}: Embedding detection failed: {e}")
                    # Continue without embedding
            # ========== END EMBEDDING_SYSTEM ==========

            # D. TRI-CURVE ALIGNMENT
            # Find existing tooth for angulation reference (optional)
            angulation_ref = None
            if p.use_existing_tooth_angulation:
                angulation_ref = find_existing_tooth_for_angulation(tid)
                if angulation_ref:
                    print(
                        f"  Tooth #{tid}: Using angulation from {angulation_ref.name}"
                    )

            # Retrieve detected incisal point if available
            incisal_local = None
            if "SMILE_INCISAL_POINT_LOCAL" in obj:
                incisal_local = Vector(obj["SMILE_INCISAL_POINT_LOCAL"])
                print(f"  Tooth #{tid}: Using detected incisal point for positioning")

            # ========== EMBEDDING_SYSTEM: Retrieve embedding parameters ==========
            midline_local = None
            fl_axis = None
            embedding_depth = 0.5  # Default

            if p.golden_enable_embedding and "SMILE_BUCCOLINGUAL_MIDLINE_LOCAL" in obj:
                midline_local = Vector(obj["SMILE_BUCCOLINGUAL_MIDLINE_LOCAL"])
                fl_axis = Vector(obj["SMILE_FACIAL_LINGUAL_AXIS"])
                embedding_depth = p.golden_embedding_depth
            # ========== END EMBEDDING_SYSTEM ==========

            # Evaluate tri-curve position and rotation
            # bbox after scaling needs to be recalculated with applied scale
            bpy.context.view_layer.update()
            mn_scaled, mx_scaled = bbox_world(obj)

            pos, rot_matrix, tangent = evaluate_tri_curve_position_for_tooth(
                lateral_curve,
                depth_curve,
                t_mid,
                (mn_scaled, mx_scaled),  # Bbox after scaling
                angulation_reference=angulation_ref,
                incisal_point_local=incisal_local,  # Pass detected incisal point
                midline_local=midline_local,  # EMBEDDING_SYSTEM
                embedding_depth=embedding_depth,  # EMBEDDING_SYSTEM
                facial_lingual_axis=fl_axis,  # EMBEDDING_SYSTEM
            )

            # Build final transform matrix
            M = Matrix.Identity(4)
            M[0][0:3] = rot_matrix[0][0:3]
            M[1][0:3] = rot_matrix[1][0:3]
            M[2][0:3] = rot_matrix[2][0:3]
            M[0][3], M[1][3], M[2][3] = pos  # Position already adjusted for incisal

            obj.matrix_world = M

            # === INCISAL CONTACT VALIDATION & AUTO-FLIP ===
            # Verify that incisal edge is at the expected depth curve position
            # If not, auto-flip as failsafe (catches cases where preset was wrong)
            bpy.context.view_layer.update()  # Update transforms before validation

            # Get the target Z from the depth curve (incisal_target from tri-curve)
            depth_pos = evaluate_curve_at_parameter(depth_curve, t_mid)
            target_incisal_z = depth_pos.z

            # Validate incisal contact
            is_correct, fix_needed, debug_info = verify_incisal_at_target(
                obj, target_incisal_z, tolerance=2.0
            )

            # Debug output
            print(f"  Tooth #{tid} Validation:")
            print(f"    Target incisal Z: {debug_info['target_z']:.3f}mm")
            print(
                f"    Actual min Z: {debug_info['min_z']:.3f}mm (diff: {debug_info['diff_min']:.3f}mm)"
            )
            print(
                f"    Actual max Z: {debug_info['max_z']:.3f}mm (diff: {debug_info['diff_max']:.3f}mm)"
            )

            if not is_correct:
                if fix_needed == "FLIP_180X":
                    print(f"  ⚠ WARNING: Tooth #{tid} appears upside down!")
                    print(f"  → Auto-flipping 180° around X-axis...")

                    # Apply 180° flip around X-axis
                    flip_matrix = Matrix.Rotation(math.radians(180), 4, "X")
                    obj.matrix_world = flip_matrix @ obj.matrix_world

                    # Re-validate after flip
                    bpy.context.view_layer.update()
                    is_correct_now, _, debug_info_after = verify_incisal_at_target(
                        obj, target_incisal_z, tolerance=2.0
                    )

                    if is_correct_now:
                        print(f"  ✓ Tooth #{tid}: Auto-flip successful!")
                        print(
                            f"    New min Z: {debug_info_after['min_z']:.3f}mm (diff: {debug_info_after['diff_min']:.3f}mm)"
                        )
                        print(f"    Incisal contact: OK")
                    else:
                        print(
                            f"  ✗ Tooth #{tid}: Auto-flip didn't fix issue (diff: {debug_info_after['diff_min']:.3f}mm)"
                        )

                    # Suggest fixing the preset
                    if p.library_orientation_preset == "STANDARD":
                        print(
                            f"  💡 TIP: Try setting Library Orientation to 'Inverted Z' for this library"
                        )

                elif fix_needed == "UNKNOWN":
                    print(f"  ⚠ WARNING: Tooth #{tid} incisal not at expected position")
                    print(
                        f"    This might indicate rotation issues or positioning errors"
                    )
                    print(
                        f"    Min Z diff: {debug_info['diff_min']:.3f}mm, Max Z diff: {debug_info['diff_max']:.3f}mm"
                    )
            else:
                print(f"    Incisal contact: ✓ OK")
            # === END INCISAL CONTACT VALIDATION ===

            # F. Final Rotation Tweaks
            # Some libraries have different defaults. If weird, we might need 180 flips.
            # But Standard Blender/Dental is usually Front=-Y, Up=Z.

            cnt += 1

        self.report({"INFO"}, f"Golden Import: {cnt} teeth imported.")
        return {"FINISHED"}


class SMILE_OT_delete_golden_set(bpy.types.Operator):
    """Delete only the imported golden set teeth (#6-#11)"""

    bl_idname = "smile.delete_golden_set"
    bl_label = "Remove Golden Set"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        deleted_count = 0
        deleted_ids = []

        col_teeth = bpy.data.collections.get(COL_TEETH)

        if col_teeth:
            for obj in list(col_teeth.objects):
                # Only delete if marked as golden set import
                if obj.get("SMILE_GOLDEN_SET_IMPORT") == True:
                    tooth_id = obj.get("SMILE_GOLDEN_SET_TOOTH_ID")
                    if tooth_id:
                        deleted_ids.append(tooth_id)
                    bpy.data.objects.remove(obj, do_unlink=True)
                    deleted_count += 1

        if deleted_count > 0:
            teeth_str = ", ".join([f"#{tid}" for tid in sorted(deleted_ids)])
            self.report(
                {"INFO"}, f"Deleted {deleted_count} golden set teeth: {teeth_str}"
            )
        else:
            self.report({"WARNING"}, "No golden set teeth found to delete")

        return {"FINISHED"}


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


def arch_curve_name(domain: str, curve_role: str = ARCH_CURVE_OCCLUSAL):
    role = (curve_role or ARCH_CURVE_OCCLUSAL).upper()
    if role == ARCH_CURVE_CERVICAL:
        return f"ARCH_{domain}_CERVICAL_CURVE"
    return f"ARCH_{domain}_CURVE"


def find_arch_incisal_curve(domain: str):
    for nm in arch_incisal_curve_candidates(domain):
        o = bpy.data.objects.get(nm)
        if o and o.type == "CURVE" and not o.hide_viewport:
            return o
    return None


def smart_parent(child, parent_obj):
    if not child or not parent_obj:
        return
    if child.parent == parent_obj:
        return
    mw = child.matrix_world.copy()
    child.parent = parent_obj
    child.matrix_parent_inverse = parent_obj.matrix_world.inverted()
    child.matrix_world = mw


def ensure_arch_tracers_visible(scene, context=None):
    """
    Best-effort restoration for arch tracer visibility.
    Rebuilds missing curves from saved points and unhides curve objects/collection.
    """
    if not scene:
        return 0
    ctx = context or bpy.context
    try:
        ensure_collection_visible(ctx, COL_ARCH)
    except Exception:
        pass
    made = 0
    for domain in (DOMAIN_MAX, DOMAIN_MAN):
        for role in (ARCH_CURVE_OCCLUSAL, ARCH_CURVE_CERVICAL):
            cobj = ensure_arch_curve_from_saved_points(
                scene, domain, role, force_rebuild=False
            )
            if not cobj:
                continue
            try:
                cobj.hide_viewport = False
                cobj.hide_render = False
                cobj.hide_set(False)
                cobj.show_in_front = True
                made += 1
            except Exception:
                pass
    return int(made)


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


# ============================================================
# TEETH helpers (unchanged)
# ============================================================


def tooth_objects_in_collection():
    col = ensure_collection(COL_TEETH)
    return [o for o in col.objects if o and o.type == "MESH"]


def sort_teeth_by_id(mesh_objs):
    items = []
    for o in mesh_objs:
        tid = parse_tooth_id_from_name(o.name)
        if tid is None:
            continue
        items.append((tid, o))
    items.sort(key=lambda x: x[0])
    return [o for _, o in items]


def bbox_world(obj):
    mw = obj.matrix_world
    corners = [mw @ Vector(c) for c in obj.bound_box]
    mn = Vector(
        (
            min(c.x for c in corners),
            min(c.y for c in corners),
            min(c.z for c in corners),
        )
    )
    mx = Vector(
        (
            max(c.x for c in corners),
            max(c.y for c in corners),
            max(c.z for c in corners),
        )
    )
    return mn, mx


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


def apply_tooth_tweaks(obj, arch_tangent: Vector, occlusal_up: Vector):
    ensure_tooth_params(obj)

    z = arch_tangent.normalized() if arch_tangent.length > 1e-9 else Vector((1, 0, 0))
    y = occlusal_up.normalized() if occlusal_up.length > 1e-9 else Vector((0, 0, 1))
    x = y.cross(z)
    if x.length < 1e-9:
        x = Vector((1, 0, 0))
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
                tan = (pts[i + 1] - pts[i]).normalized()
                return pt, tan
        return pts[-1], (pts[-1] - pts[-2]).normalized()

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


# ============================================================
# VENEER PIPELINE (unchanged from your script)
# ============================================================


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


# ============================================================
# BLOCK FFD RIG (LOCAL TOOTH CUSTOMIZATION)
# ============================================================

KEY_BLOCKFFD_LAT = "SMILE_BLOCKFFD_LATTICE"
KEY_BLOCKFFD_HANDLES = "SMILE_BLOCKFFD_HANDLES"
KEY_BLOCKFFD_REL_PREV = "SMILE_BLOCKFFD_REL_LINES_PREV"


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


def _blockffd_restore_relationship_lines(scene):
    prev = bool(scene.get(KEY_BLOCKFFD_REL_PREV, True))
    _blockffd_set_relationship_lines(scene, prev)
    try:
        if KEY_BLOCKFFD_REL_PREV in scene:
            del scene[KEY_BLOCKFFD_REL_PREV]
    except Exception:
        pass


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


# ============================================================
# ENHANCED MARGIN SYSTEM - DATA STORAGE & ALGORITHMS
# ============================================================

KEY_MARGIN_DATA_PREFIX = "SMILE_MARGIN_DATA_"


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


def set_margin_data(scene, tooth_obj, data, tooth_id=None):
    """
    Store margin data on tooth_obj.data for maximum portability.
    """
    if not tooth_obj or not tooth_obj.data:
        return

    import json
    import time

    suffix = f"_T{tooth_id}" if tooth_id else ""
    key = KEY_MARGIN_DATA_PREFIX + suffix

    # 1. Ensure Metadata
    if "created_time" not in data:
        data["created_time"] = time.time()
    data["last_modified_time"] = time.time()
    data["tooth_id"] = tooth_id

    # 2. Robust Vector-to-List conversion
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

    # Keep a local-space copy so edit markers remain aligned after model moves.
    _update_margin_local_from_world(tooth_obj, data)

    # 3. Save to Data Block
    tooth_obj.data[key] = json.dumps(data)


def update_golden_ruler(self, context=None):
    """Update the Golden Ruler Arch and Ticks live when the slider moves."""
    if not context:
        context = bpy.context

    ruler = bpy.data.objects.get("SMILE_Golden_Ruler")

    # Only update the generated Arch if it exists. DO NOT look for "Lip Line" or "SMILE_Golden_Ruler_Arch"
    # as they are separate tools.
    arch = bpy.data.objects.get("SMILE_Golden_Arch")

    if not arch:
        cdata = bpy.data.curves.new("SMILE_Golden_Arch", "CURVE")
        cdata.dimensions = "3D"
        spline = cdata.splines.new("BEZIER")
        arch = bpy.data.objects.new("SMILE_Golden_Arch", cdata)
        # arch.show_in_front = True # Optional
        if context.collection:
            context.collection.objects.link(arch)
        else:
            ensure_collection(COL_ARCH).objects.link(arch)

    ticks = bpy.data.objects.get("SMILE_Golden_Ruler_Ticks")

    if not ticks:
        # Lazy creation of Ticks Mesh if missing
        mesh = bpy.data.meshes.new("SMILE_Golden_Ruler_Ticks_Mesh")
        ticks = bpy.data.objects.new("SMILE_Golden_Ruler_Ticks", mesh)
        ticks.show_in_front = True
        if context.collection:
            context.collection.objects.link(ticks)
        else:
            ensure_collection(COL_ARCH).objects.link(ticks)

    if not ruler:
        return

    # PARENTING: Make Arch and Ticks children of Ruler so they move/rotate as one unit
    if arch and arch.parent != ruler:
        arch.parent = ruler
        arch.matrix_parent_inverse = ruler.matrix_world.inverted()

    if ticks and ticks.parent != ruler:
        ticks.parent = ruler
        ticks.matrix_parent_inverse = ruler.matrix_world.inverted()

    # Decouple failure: Continue even if Arch or Ticks are missing
    # But we need ruler because it holds the data.

    # Get parameters stored on the ruler
    p1 = Vector(ruler.get("SMILE_P1", (0, 0, 0)))
    p2 = Vector(ruler.get("SMILE_P2", (0, 0, 0)))

    # SAFETY: If P1 or P2 are zero (uninitialized), abort to prevent "Drift to Origin"
    if p1.length < 0.001 or p2.length < 0.001:
        return

    # RECALCULATE TICK VECTOR - Perpendicular to pupil line if pupils exist
    pupil_r = bpy.data.objects.get("FACE_LM_Pupil_R")
    pupil_l = bpy.data.objects.get("FACE_LM_Pupil_L")

    if pupil_r and pupil_l:
        # Use pupil line for perpendicular tick vector (2D projection)
        pr_loc = pupil_r.matrix_world.translation
        pl_loc = pupil_l.matrix_world.translation
        pupil_vec = pl_loc - pr_loc
        pupil_vec.y = 0  # Flatten to XZ plane (2D projection)

        if pupil_vec.length_squared > 1e-6:
            pupil_vec.normalize()
            # Perpendicular in XZ plane: rotate 90° around Y-axis
            tick_vec = Vector((-pupil_vec.z, 0, pupil_vec.x))
            # Ensure upward orientation
            if tick_vec.z < 0:
                tick_vec = -tick_vec
        else:
            # Fallback to stored tick vector
            tick_vec = Vector(ruler.get("SMILE_TICK_VEC", (0, 0, 1)))
    else:
        # No pupils, use stored tick vector
        tick_vec = Vector(ruler.get("SMILE_TICK_VEC", (0, 0, 1)))

    # LIVE UPDATE: Recalculate offsets based on current mode
    p_props = context.scene.smile_v2
    mode = p_props.golden_ruler_mode

    if mode == "CLASSIC":
        tr = 6.472
        wc, wl, wk = 1.618 / tr, 1.0 / tr, 0.618 / tr
    else:
        # Gauge 12-15-23 (Default)
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
    ruler["SMILE_OFFSETS"] = offsets  # Persist new offsets
    plane_n = Vector(ruler.get("SMILE_NORMAL", (0, 1, 0)))  # Load View Normal

    # Convert UI Millimeters to Blender Meters
    depth = p_props.golden_arch_depth * 0.001

    # RAYCAST TARGET SETUP (Global for function)
    target_obj = None
    scan_name = ruler.get("SMILE_SCAN_NAME", "")
    if scan_name:
        target_obj = bpy.data.objects.get(scan_name)

    if not offsets:
        return

    # Update ruler line thickness from property
    if ruler and ruler.data:
        thickness_mm = p_props.golden_ruler_thickness
        ruler.data.bevel_depth = thickness_mm * 0.001

    # 0. Update Main Ruler Curve (Yellow Line A->B)
    # Ensure it stays shrinkwrapped and has NO TAILS (VECTOR handles)
    if ruler.data.splines:
        rspline = ruler.data.splines[0]
        rsteps = 64
        if len(rspline.bezier_points) != rsteps:
            rspline.bezier_points.add(rsteps - len(rspline.bezier_points))

        # Raycast Setup (Looking Back)
        ray_dir_ruler = -plane_n
        ray_start_off_ruler = plane_n * 50.0  # 5cm out
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

            # Slightly in front for visibility
            final_pos += plane_n.normalized() * 0.0001  # 0.1mm

            rspline.bezier_points[i].co = final_pos

            # HANDLE MANAGEMENT
            # Start/End: VECTOR (No overshooting)
            # Middle: AUTO (Smooth)
            if i == 0 or i == rsteps - 1:
                rspline.bezier_points[i].handle_left_type = "VECTOR"
                rspline.bezier_points[i].handle_right_type = "VECTOR"
            else:
                rspline.bezier_points[i].handle_left_type = "AUTO"
                rspline.bezier_points[i].handle_right_type = "AUTO"

        # Force endpoints exact
        rspline.bezier_points[0].co = p1 + plane_n * 0.005
        rspline.bezier_points[rsteps - 1].co = p2 + plane_n * 0.005

    # 1. Update Arch Curve
    # 1. Update Arch Curve (SHRINKWRAPPED 3D BEZIER)
    if arch and arch.data.splines:
        spline = arch.data.splines[0]

        # Get arch object's world matrix inverse to convert world coords to local
        arch_world_inv = arch.matrix_world.inverted()

        # We need high resolution to conform to surface
        steps = 64
        if len(spline.bezier_points) != steps:
            spline.bezier_points.add(steps - len(spline.bezier_points))

        # Quadratic Bezier Logic (Floating) -> Raycast -> Surface
        midpoint = (p1 + p2) * 0.5
        apex = midpoint - (tick_vec * depth)

        # Raycast Setup
        deps = context.evaluated_depsgraph_get()
        # Raycast Setup - STRICTLY use SMILE_NORMAL (plane_n)
        if plane_n.length < 0.1:
            plane_n = Vector((0, 1, 0))  # Fallback if missing

        ray_dir = (
            -plane_n.normalized()
        )  # Look in opposite direction of View Normal (Camera->Scene)
        ray_start_off = plane_n.normalized() * 50.0  # Start 50mm out towards camera

        # Evaluate Quadratic Bezier manually for t in [0..1]
        for i in range(steps):
            t = i / (steps - 1)
            p_ctrl = (2.0 * apex) - 0.5 * (p1 + p2)

            # Curve Point (Floating)
            pt_float = (1 - t) ** 2 * p1 + 2 * (1 - t) * t * p_ctrl + t**2 * p2

            # Raycast
            ray_origin = pt_float + ray_start_off

            hit = False
            loc = Vector((0, 0, 0))
            if target_obj:
                # Fast Object Raycast (Local Space conversion needed)
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

            # Shift slightly forward
            final_pos += plane_n.normalized() * 0.0001  # 0.1mm

            # Convert world space position to arch object's local space
            # (Important now that arch is parented to ruler)
            final_pos_local = arch_world_inv @ final_pos

            spline.bezier_points[i].co = final_pos_local
            spline.bezier_points[i].handle_left_type = "AUTO"
            spline.bezier_points[i].handle_right_type = "AUTO"

    # 2. Update Ticks (Projected Proportion)
    if ticks and ticks.type == "MESH":
        bm = bmesh.new()
        try:
            tick_h = 10.0  # mm

            # Get ticks object's world matrix inverse to convert world coords to local
            ticks_world_inv = ticks.matrix_world.inverted()

            # Raycast params for Ticks
            deps = context.evaluated_depsgraph_get()
            if plane_n.length < 0.1:
                plane_n = Vector((0, 1, 0))

            ray_dir = -plane_n.normalized()
            ray_start_off = plane_n.normalized() * 50.0  # Start 50mm out

            for t in offsets:
                # 1. Calculate Linear Position on the P1->P2 Chord
                base_pos_linear = p1.lerp(p2, t)

                # 2. Raycast this point onto the surface
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

                final_pos += plane_n.normalized() * 0.0001

                # Convert world space positions to ticks object's local space
                # (Important now that ticks is parented to ruler)
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


class SMILE_OT_golden_ruler(bpy.types.Operator):
    bl_idname = "smile.golden_ruler"
    bl_label = "Golden Proportion Ruler"
    bl_options = {"REGISTER", "UNDO"}

    scan_obj_name: bpy.props.StringProperty(default="")

    _points = None
    _normal = None  # Store plane normal for tick orientation

    def invoke(self, context, event):
        self._points = []
        self._normal = Vector((0, 1, 0))  # Default

        # Find Scan Object for Precision Shrinkwrap
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
        # Navigation Pass-Through
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
                    # self._normal = norm # OLD: Unstable surface normal
                    self._normal = (
                        -ray_dir
                    )  # NEW: Stable View Direction (Towards Camera)
            else:
                # HIT MISS LOGIC
                if len(self._points) == 0:
                    # First point missed? Just project deep.
                    self._points.append(ray_origin + ray_dir * 1000.0)
                    self._normal = -ray_dir
                else:
                    # Second point missed? Project onto Plane defined by First Point!
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

        # print(f"DEBUG: Create Ruler. P1={p1}, P2={p2}")

        name = "SMILE_Golden_Ruler"
        old = bpy.data.objects.get(name)
        if old:
            delete_object(old)
        old_t = bpy.data.objects.get(name + "_Ticks")
        if old_t:
            delete_object(old_t)

        # POSITIONING
        plane_n = self._normal if self._normal else Vector((0, 1, 0))

        # Create main ruler line (Gold)
        cdata = bpy.data.curves.new(name, "CURVE")
        cdata.dimensions = "3D"
        spline = cdata.splines.new("BEZIER")

        # Subdivide
        steps = 64
        spline.bezier_points.add(steps - 1)

        # Add Material
        mat = bpy.data.materials.get("SMILE_Ruler_Gold")
        if not mat:
            mat = bpy.data.materials.new("SMILE_Ruler_Gold")
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            nodes.clear()
            emission = nodes.new("ShaderNodeEmission")
            emission.inputs["Color"].default_value = (1.0, 0.84, 0.0, 1.0)  # Gold
            emission.inputs["Strength"].default_value = 1.0
            output = nodes.new("ShaderNodeOutputMaterial")
            mat.node_tree.links.new(
                emission.outputs["Emission"], output.inputs["Surface"]
            )
            mat.use_backface_culling = False
            mat.blend_method = "OPAQUE"

        cdata.materials.append(mat)

        # Calculations
        p_props = bpy.context.scene.smile_v2
        mode = p_props.golden_ruler_mode

        vec = p2 - p1
        unit = vec.normalized()

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

        # Raycast Setup - STRICTLY use SMILE_NORMAL (plane_n)
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

            # Slightly in front for visibility
            final_pos += plane_n.normalized() * 0.0001  # 0.1mm

            spline.bezier_points[i].co = final_pos

            # HANDLE MANAGEMENT
            if i == 0 or i == steps - 1:
                spline.bezier_points[i].handle_left_type = "VECTOR"
                spline.bezier_points[i].handle_right_type = "VECTOR"
            else:
                spline.bezier_points[i].handle_left_type = "AUTO"
                spline.bezier_points[i].handle_right_type = "AUTO"

        # Force endpoints exact
        spline.bezier_points[0].co = p1 + plane_n.normalized() * 0.005
        spline.bezier_points[steps - 1].co = p2 + plane_n.normalized() * 0.005

        obj = bpy.data.objects.new(name, cdata)
        col.objects.link(obj)
        obj.show_in_front = True

        # Use thickness from property (convert mm to meters)
        thickness_mm = p_props.golden_ruler_thickness
        cdata.bevel_depth = thickness_mm * 0.001

        # Tick Vector (Initial Calc) - PERPENDICULAR TO PUPIL LINE IN 2D PROJECTION
        # Check if pupil landmarks exist for perpendicular alignment
        pupil_r = bpy.data.objects.get("FACE_LM_Pupil_R")
        pupil_l = bpy.data.objects.get("FACE_LM_Pupil_L")

        if pupil_r and pupil_l:
            # Calculate pupil line vector (flattened to XZ plane for 2D projection)
            pr_loc = pupil_r.matrix_world.translation
            pl_loc = pupil_l.matrix_world.translation
            pupil_vec = pl_loc - pr_loc
            pupil_vec.y = 0  # Flatten to 2D projection (ignore depth)

            if pupil_vec.length_squared > 1e-6:
                pupil_vec.normalize()
                # Tick vector is perpendicular to pupil line in XZ plane
                # For a vector in XZ plane (x, 0, z), perpendicular is (-z, 0, x) or (z, 0, -x)
                tick_vec = Vector((-pupil_vec.z, 0, pupil_vec.x))
                # Ensure tick points upward (positive Z component preferred)
                if tick_vec.z < 0:
                    tick_vec = -tick_vec
                print(f"DEBUG: Tick vector perpendicular to pupil line: {tick_vec}")
            else:
                # Fallback if pupils are too close
                tick_vec = unit.cross(plane_n).normalized()
                if tick_vec.z < 0:
                    tick_vec = -tick_vec
        else:
            # No pupils found, use original method
            tick_vec = unit.cross(plane_n).normalized()
            if tick_vec.z < 0:
                tick_vec = -tick_vec

        # STORE DATA ON RULER OBJECT
        obj["SMILE_P1"] = p1
        obj["SMILE_P2"] = p2
        # Store BASE points for non-destructive width scaling
        obj["SMILE_P1_BASE"] = p1
        obj["SMILE_P2_BASE"] = p2
        obj["SMILE_TICK_VEC"] = tick_vec
        obj["SMILE_OFFSETS"] = offsets
        obj["SMILE_OFFSETS"] = offsets
        obj["SMILE_NORMAL"] = plane_n
        if self.scan_obj_name:
            obj["SMILE_SCAN_NAME"] = self.scan_obj_name

        # Trigger explicit update to sync everything (and create Arch)
        update_golden_ruler(p_props, context)


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

        # Draw Box (Centered on Start)
        width_px = abs(mx - sx) * 2
        height_px = abs(my - sy) * 2

        x_min = sx - width_px / 2
        x_max = sx + width_px / 2
        y_min = sy - height_px / 2
        y_max = sy + height_px / 2

        # GPU Batch Draw Lines
        coords = [
            (x_min, y_min),
            (x_max, y_min),
            (x_max, y_min),
            (x_max, y_max),
            (x_max, y_max),
            (x_min, y_max),
            (x_min, y_max),
            (x_min, y_min),
            # Crosshair
            (sx, y_min),
            (sx, y_max),
            (x_min, sy),
            (x_max, sy),
        ]

        shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINES", {"pos": coords})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.8, 0.2, 1.0))  # Gold
        batch.draw(shader)

        # Text
        # Calculate MM roughly?
        # Provide feedback based on projected 3D distance
        if self._start_co_3d:
            region = context.region
            rv3d = context.region_data

            # Project current mouse to 3D plane at start depth
            curr_vec = bpy_extras.view3d_utils.region_2d_to_vector_3d(
                region, rv3d, (mx, my)
            )
            start_vec = bpy_extras.view3d_utils.region_2d_to_vector_3d(
                region, rv3d, (sx, sy)
            )
            origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(
                region, rv3d, (sx, sy)
            )

            # Distance from camera to start point
            dist = (self._start_co_3d - origin).length

            # 3D points at that depth
            p1 = origin + start_vec * dist
            p2 = origin + curr_vec * dist

            # World Deltas
            # Assume View-Aligned Plane or World-Aligned?
            # Visual Calibration usually assumes View-Aligned box.

            # Let's project p2 - p1 onto Camera Up/Right vectors
            view_inv = rv3d.view_matrix.inverted()
            cam_right = view_inv.to_3x3().col[0].normalized()
            cam_up = view_inv.to_3x3().col[1].normalized()

            delta = p2 - p1
            w_mm = abs(delta.dot(cam_right)) * 2 * 1000  # Radius * 2 * Meters->mm
            h_mm = abs(delta.dot(cam_up)) * 2 * 1000

            blf.position(font_id, x_max + 10, sy, 0)
            blf.draw(font_id, f"W: {w_mm:.1f}mm")
            blf.position(font_id, x_max + 10, sy - 20, 0)
            blf.position(font_id, sx, y_max + 10, 0)
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
                # FIRST CLICK: Set Center
                # Raycast to find curve depth
                p = context.scene.smile_v2
                domain = DOMAIN_MAX if self.tooth_id <= 16 else DOMAIN_MAN
                curve_name = arch_curve_name(domain)
                curve_obj = bpy.data.objects.get(curve_name)

                # If no curve, raycast against scene?
                # Best effort raycast
                region = context.region
                rv3d = context.region_data
                coord = (event.mouse_region_x, event.mouse_region_y)

                # Raycast
                view_vector = bpy_extras.view3d_utils.region_2d_to_vector_3d(
                    region, rv3d, coord
                )
                ray_origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(
                    region, rv3d, coord
                )

                # Check intersection with Curve Object (converted to mesh?)
                # Or just use cursor location as depth reference?
                # Or raycast scene.
                hit, loc, norm, idx, obj, mat = context.scene.ray_cast(
                    context.view_layer.depsgraph, ray_origin, view_vector
                )

                if hit:
                    self._start_co_3d = loc
                else:
                    # Fallback: depth of 3D cursor
                    cursor_loc = context.scene.cursor.location
                    # Projected depth
                    # Simply place at some distance?
                    self._start_co_3d = ray_origin + view_vector * 100  # arbitrary

                self._start_mouse = coord
                self._is_dragging = True
                return {"RUNNING_MODAL"}

            elif event.value == "RELEASE":
                if self._is_dragging:
                    # FINISH
                    # Calculate final MM
                    mx, my = self._current_mouse
                    sx, sy = self._start_mouse

                    region = context.region
                    rv3d = context.region_data

                    curr_vec = bpy_extras.view3d_utils.region_2d_to_vector_3d(
                        region, rv3d, (mx, my)
                    )
                    origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(
                        region, rv3d, (sx, sy)
                    )
                    dist = (self._start_co_3d - origin).length
                    p1 = (
                        origin
                        + bpy_extras.view3d_utils.region_2d_to_vector_3d(
                            region, rv3d, (sx, sy)
                        )
                        * dist
                    )
                    p2 = origin + curr_vec * dist

                    view_inv = rv3d.view_matrix.inverted()
                    cam_right = view_inv.to_3x3().col[0].normalized()
                    cam_up = view_inv.to_3x3().col[1].normalized()

                    delta = p2 - p1
                    w_mm = abs(delta.dot(cam_right)) * 2 * 1000
                    h_mm = abs(delta.dot(cam_up)) * 2 * 1000

                    # Update Props
                    p = context.scene.smile_v2
                    p.target_width_mm = max(1.0, w_mm)
                    p.target_height_mm = max(1.0, h_mm)
                    p.use_target_dims = True  # Enable it

                    # Create Seed
                    seed_name = f"SEED_T{self.tooth_id}"
                    seed = bpy.data.objects.get(seed_name)
                    if not seed:
                        seed = bpy.data.objects.new(seed_name, None)
                        context.collection.objects.link(seed)
                        ensure_collection(COL_LM).objects.link(seed)
                        context.collection.objects.unlink(seed)

                    seed.location = self._start_co_3d
                    seed.empty_display_type = "SINGLE_ARROW"
                    seed.empty_display_size = p.marker_size * 5

                    # Cleanup
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

    target_property: bpy.props.StringProperty()  # e.g. "target_width_mm"

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

        # Draw Line p1 -> p2 (or mouse)
        font_id = 0
        blf.size(font_id, 20, 72)
        blf.color(font_id, 1, 1, 1, 1)

        region = context.region
        rv3d = context.region_data

        # Project P1 to Screen
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
            # Draw Line
            shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
            batch = batch_for_shader(shader, "LINES", {"pos": [p1_2d, p2_2d]})
            shader.bind()
            shader.uniform_float("color", (0.2, 1.0, 0.5, 1.0))  # Green
            batch.draw(shader)

            # Draw Distance Text
            mid = (p1_2d + p2_2d) * 0.5

            # Calculate 3D Distance
            dist = 0.0
            if p2_3d:
                dist = (p2_3d - self._p1).length * 1000
            else:
                # Project mouse to depth of P1? Or raycast depth?
                # If we haven't clicked P2, we don't know the exact 3D point.
                # But we can assume surface raycast from modal.
                pass

            if p2_3d:
                blf.position(font_id, mid.x + 10, mid.y + 10, 0)
                blf.draw(font_id, f"{dist:.1f}mm")

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._mouse_loc = (event.mouse_region_x, event.mouse_region_y)
            # Optional: Raycast continuously for preview? Might be heavy.
            # Let's simple-draw to mouse 2D for the elastic line.

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Raycast to find surface point
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            view_vector = bpy_extras.view3d_utils.region_2d_to_vector_3d(
                region, rv3d, coord
            )
            ray_origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(
                region, rv3d, coord
            )

            hit, loc, norm, idx, obj, mat = context.scene.ray_cast(
                context.view_layer.depsgraph, ray_origin, view_vector
            )

            if hit:
                if not self._p1:
                    self._p1 = loc
                    self.report({"INFO"}, "Start Point set. Click End Point.")
                else:
                    self._p2 = loc
                    # FINISH
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


def geodesic_fill_segment(obj, start_world, end_world, prefer_ridges=True):
    """
    Live-Wire Pathfinding: Uses Dihedral Angle to snap to prep margins.
    """
    if not obj or obj.type != "MESH":
        return [start_world, end_world]

    mw = obj.matrix_world
    mw_inv = mw.inverted()

    # 1. BMesh prep
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # 2. Find closest verts
        kd = KDTree(len(bm.verts))
        for i, v in enumerate(bm.verts):
            kd.insert(v.co, i)
        kd.balance()

        _, v1_idx, _ = kd.find(mw_inv @ start_world)
        _, v2_idx, _ = kd.find(mw_inv @ end_world)
        v_start = bm.verts[v1_idx]
        v_end = bm.verts[v2_idx]

        # 3. A* Search (Heuristic = Euclidean Distance)
        # G_score: Cost from start
        # F_score: G + Heuristic

        g_score = {v_start: 0.0}
        predecessors = {v_start: None}
        pq = [(0.0, 0.0, v_start.index)]  # (F, G, idx)

        target_co = v_end.co
        max_iters = 15000  # Increased for complex paths
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

                # Live-Wire Weighting
                weight = edge_len
                if prefer_ridges:
                    # Dihedral Angle Cost (0.1 to 1.0)
                    d_cost = compute_dihedral_cost(edge)
                    weight *= d_cost

                new_g = g + weight
                if new_g < g_score.get(neighbor, float("inf")):
                    g_score[neighbor] = new_g
                    h = (neighbor.co - target_co).length  # Euclidean Heuristic
                    f_new = new_g + h
                    predecessors[neighbor] = v
                    heapq.heappush(pq, (f_new, new_g, neighbor.index))

        # 4. Reconstruct
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


def _mm_to_bu_for_obj(mm_val, obj_hint=None):
    """
    Convert mm to scene/world units with compatibility for legacy scenes where BU ~= mm.
    """
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
            # Legacy compatibility heuristic used across this addon.
            if max_dim > 5.0:
                bu = float(mm_val)
        except Exception:
            pass
    return float(bu)


def project_loop_to_surface(obj, loop_world):
    """Project full loop to mesh surface."""
    if not loop_world:
        return []
    return [_project_world_to_mesh(obj, Vector(p)) for p in loop_world]


def simplify_path_rdp(points, tolerance=0.15):
    """
    Ramer-Douglas-Peucker algorithm to simplify path.
    Removes points that don't contribute significantly to the path shape.

    Args:
        points: List of Vector points
        tolerance: Maximum distance (mm) from point to simplified line

    Returns:
        Simplified list of points
    """
    if len(points) < 3:
        return points

    def perpendicular_distance(point, line_start, line_end):
        """Calculate perpendicular distance from point to line segment"""
        line_vec = line_end - line_start
        line_len = line_vec.length
        if line_len < 0.0001:
            return (point - line_start).length

        # Project point onto line
        t = max(0, min(1, (point - line_start).dot(line_vec) / (line_len * line_len)))
        projection = line_start + t * line_vec
        return (point - projection).length

    def rdp_recursive(points, start_idx, end_idx, tolerance):
        """Recursive RDP implementation"""
        if end_idx - start_idx <= 1:
            return [start_idx, end_idx]

        # Find point with maximum distance from line
        max_dist = 0
        max_idx = start_idx
        line_start = points[start_idx]
        line_end = points[end_idx]

        for i in range(start_idx + 1, end_idx):
            dist = perpendicular_distance(points[i], line_start, line_end)
            if dist > max_dist:
                max_dist = dist
                max_idx = i

        # If max distance is greater than tolerance, recursively simplify
        if max_dist > tolerance:
            # Recursively simplify both sides
            left = rdp_recursive(points, start_idx, max_idx, tolerance)
            right = rdp_recursive(points, max_idx, end_idx, tolerance)
            # Combine results (remove duplicate middle point)
            return left[:-1] + right
        else:
            # All points between start and end can be removed
            return [start_idx, end_idx]

    # Apply RDP algorithm
    indices = rdp_recursive(points, 0, len(points) - 1, tolerance)
    return [points[i] for i in indices]


_MARGIN_TRACE_NAV_EVENTS = {
    "MIDDLEMOUSE",
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELINMOUSE",
    "WHEELOUTMOUSE",
    "NUMPAD_PERIOD",
    "PERIOD",
    "TRACKPADPAN",
    "TRACKPADZOOM",
    "MOUSEROTATE",
    "MOUSESMARTZOOM",
}
_MARGIN_TRACE_ALT_NAV_EVENTS = {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE", "Z", "B"}
_MARGIN_TRACE_TRANSFORM_KEYS = {
    "G",
    "R",
    "S",
    "X",
    "Y",
    "Z",
    "NUMPAD_1",
    "NUMPAD_3",
    "NUMPAD_7",
    "NUMPAD_2",
    "NUMPAD_4",
    "NUMPAD_6",
    "NUMPAD_8",
}
_MARGIN_TRACE_TRANSFORM_OPS = {
    "TRANSFORM_OT_translate",
    "TRANSFORM_OT_rotate",
    "TRANSFORM_OT_resize",
}


class SMILE_OT_sculpt_session_start(bpy.types.Operator):
    """Start Sculpt Session with Proximal Simulation and Confinement."""

    bl_idname = "smile.sculpt_session_start"
    bl_label = "Start Sculpt (Bio-Confined)"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _analyzer = None

    def modal(self, context, event):
        if event.type == "TIMER":
            if context.mode != "SCULPT" or not self._analyzer:
                self.cancel(context)
                return {"FINISHED"}

            self._analyzer.update_feedback(context)
            context.area.tag_redraw()

        return {"PASS_THROUGH"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH":
            return {"CANCELLED"}

        res = build_adjacent_bvhtrees(obj)
        if not res:
            self.report({"ERROR"}, "No Patient Scan found for confinement.")
            return {"CANCELLED"}

        bvh, scan = res
        self._analyzer = SMILE_ProximalAnalyzer(obj, scan, bvh)

        # Enter Sculpt Mode
        bpy.ops.object.mode_set(mode="SCULPT")

        # Shading setup for feedback
        context.space_data.shading.color_type = "VERTEX"

        self._timer = context.window_manager.event_timer_add(0.2, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        bpy.ops.object.mode_set(mode="OBJECT")
        self.report({"INFO"}, "Bio-Sculpt Session Ended.")


class SMILE_OT_add_multires_sculpt(bpy.types.Operator):
    """Add clinical multires levels for high-fidelity sculpting."""

    bl_idname = "smile.add_multires_sculpt"
    bl_label = "Add Multires Levels"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH":
            return {"CANCELLED"}
        mod = obj.modifiers.get("SMILE_MULTIRES") or obj.modifiers.new(
            "SMILE_MULTIRES", "MULTIRES"
        )
        p = context.scene.smile_v2
        mod.levels = p.multires_view
        mod.sculpt_levels = p.multires_sculpt
        mod.render_levels = p.multires_render
        return {"FINISHED"}


# ============================================================
# PROPERTIES + UI
# ============================================================


class SMILE_OT_eraser_tool(bpy.types.Operator):
    bl_idname = "smile.eraser_tool"
    bl_label = "Eraser Tool (Smooth Cut)"
    bl_options = {"REGISTER", "UNDO"}

    _points = None
    _draw_handler = None
    _shader = None

    def invoke(self, context, event):
        if (
            context.view_layer.objects.active is None
            or context.view_layer.objects.active.type != "MESH"
        ):
            self.report({"ERROR"}, "Active object must be a Mesh")
            return {"CANCELLED"}

        if not gpu:
            self.report({"ERROR"}, "GPU module not available.")
            return {"CANCELLED"}

        self._points = []
        self._shader = gpu.shader.from_builtin("UNIFORM_COLOR")

        args = (self,)
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, args, "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Eraser: Left Click & Drag to draw smooth shape. Release to Cut."
        )
        return {"RUNNING_MODAL"}

    def draw_callback(self, op):
        if not self._points:
            return
        pts = self._points[:]
        if len(pts) > 2:
            pts.append(pts[0])
        batch = batch_for_shader(self._shader, "LINE_STRIP", {"pos": pts})
        self._shader.bind()
        self._shader.uniform_float("color", (1.0, 0.0, 0.0, 1.0))
        batch.draw(self._shader)

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, "WINDOW")
            context.area.tag_redraw()
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self._points = [
                    (float(event.mouse_region_x), float(event.mouse_region_y))
                ]
                return {"RUNNING_MODAL"}
            elif event.value == "RELEASE":
                if self._points and len(self._points) > 5:
                    bpy.types.SpaceView3D.draw_handler_remove(
                        self._draw_handler, "WINDOW"
                    )
                    context.area.tag_redraw()
                    self.execute_smooth_cut(context)
                    return {"FINISHED"}
                else:
                    self._points = []
                    return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE":
            if self._points:
                self._points.append(
                    (float(event.mouse_region_x), float(event.mouse_region_y))
                )
                context.area.tag_redraw()

        return {"PASS_THROUGH"}

    def _smooth_points(self, points, iterations=5):
        if len(points) < 3:
            return points
        pts = points[:]
        for _ in range(iterations):
            smoothed = []
            n = len(pts)
            for i in range(n):
                prev = pts[i - 1]
                curr = pts[i]
                next_p = pts[(i + 1) % n]
                new_x = (prev[0] + curr[0] + next_p[0]) / 3.0
                new_y = (prev[1] + curr[1] + next_p[1]) / 3.0
                smoothed.append((new_x, new_y))
            pts = smoothed
        return pts

    def execute_smooth_cut(self, context):
        target = context.view_layer.objects.active
        if not target or target.type != "MESH":
            self.report({"ERROR"}, "Select a Mesh to erase first.")
            return

        region = context.region
        rv3d = context.region_data
        v3d = _view3d_utils()

        # 1. Smooth Points
        smoothed_points = self._smooth_points(self._points)

        # 2. Project Points to Surface (Raycast)
        pts_3d = []
        depsgraph = context.evaluated_depsgraph_get()

        # We need to Raycast against the scene (or specific object)
        # Using scene raycast allows hitting whatever is under the mouse

        for x, y in smoothed_points:
            origin = v3d.region_2d_to_origin_3d(region, rv3d, (x, y))
            vec = v3d.region_2d_to_vector_3d(region, rv3d, (x, y))

            # Raycast
            # origin + vec * large_dist
            # We use a reasonably large distance, e.g. 1000

            # scene.ray_cast(depsgraph, origin, direction, distance=1.70141e+38)
            # Returns: (result, location, normal, index, object, matrix)
            result, location, normal, index, obj_hit, matrix = context.scene.ray_cast(
                depsgraph, origin, vec
            )

            if result:
                # Hit surface!
                # Add slight offset along normal to prevent Z-fighting
                pts_3d.append(location + normal * 0.05)
            else:
                # Fallback: Just project at fixed distance (floating)
                # But typically we want to ignore if off-model, or clamp?
                # For continuity, let's fallback to current view dist or skip?
                # Better to fallback to a default depth so drawing doesn't break
                pts_3d.append(origin + vec * 10.0)  # Arbitrary depth

        if len(pts_3d) < 2:
            self.report({"WARNING"}, "Not enough points on surface")
            return

        # Create arch curve (depth curve)
        arch_curve_data = bpy.data.curves.new(
            name="SMILE_Golden_Ruler_Arch", type="CURVE"
        )
        arch_curve_data.dimensions = "3D"
        arch_curve_data.resolution_u = 12
        arch_curve_data.bevel_depth = 0.0005  # Reduced to hairline thickness

        arch_spline = arch_curve_data.splines.new(type="NURBS")
        arch_spline.points.add(len(pts_3d) - 1)

        for i, pt in enumerate(pts_3d):
            arch_spline.points[i].co = (pt.x, pt.y, pt.z, 1.0)

        # Close the loop
        arch_spline.use_cyclic_u = True
        arch_spline.use_endpoint_u = False

        # Cleanup: Delete old object if it exists to prevent "sausage" persistence
        old_arch = bpy.data.objects.get("SMILE_Golden_Ruler_Arch")
        if old_arch:
            bpy.data.objects.remove(old_arch, do_unlink=True)

        final_obj = bpy.data.objects.new("SMILE_Golden_Ruler_Arch", arch_curve_data)
        context.collection.objects.link(final_obj)
        final_obj.color = (1.0, 0.0, 0.0, 1.0)
        final_obj.show_in_front = True

        # --- VISIBLE SURFACES & TANGENT PLANE ---
        try:
            # Material: Blue-ish transparent surface
            mat_name = "SMILE_Project_Surface"
            mat = bpy.data.materials.get(mat_name)
            if not mat:
                mat = bpy.data.materials.new(mat_name)
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                nodes.clear()
                bsdf = nodes.new("ShaderNodeBsdfPrincipled")
                bsdf.inputs["Base Color"].default_value = (0.0, 0.5, 1.0, 1.0)  # Blue
                bsdf.inputs["Roughness"].default_value = 0.4
                # Alpha driven by property later, verify existing value or set default
                p = context.scene.smile_v2
                bsdf.inputs["Alpha"].default_value = getattr(p, "surface_opacity", 0.5)

                output = nodes.new("ShaderNodeOutputMaterial")
                mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
                mat.blend_method = "BLEND"
                mat.show_transparent_back = False

            # 1. Lip Surface (Inner Loop)
            surf_name = "SMILE_Lip_Surface"
            old_s = bpy.data.objects.get(surf_name)
            if old_s:
                bpy.data.objects.remove(old_s, do_unlink=True)

            smesh = bpy.data.meshes.new(surf_name)
            sobj = bpy.data.objects.new(surf_name, smesh)
            ensure_collection(COL_ARCH).objects.link(sobj)

            import bmesh

            bm = bmesh.new()
            try:
                b_verts = [bm.verts.new(p) for p in pts_3d]

                # Fan Fill
                center = Vector((0, 0, 0))
                for p in pts_3d:
                    center += p
                center /= len(pts_3d)
                c_vert = bm.verts.new(center)

                for i in range(len(b_verts)):
                    v1 = b_verts[i]
                    v2 = b_verts[(i + 1) % len(b_verts)]
                    try:
                        bm.faces.new((v1, v2, c_vert))
                    except Exception:
                        pass

                bm.to_mesh(smesh)
            finally:
                bm.free()

            smesh.materials.append(mat)
            sobj.parent = final_obj
            # ------------------------------------------------

            # 2. Tangent Plane @ Apex (Most Forward Point)
            # "Forward" = Towards Camera (Inverted View Z)
            # Use View Vector used during drawing

            # Recalculate view vector from first point drawing context?
            # Or assume current view? Ideally we stored it.
            # But the points pts_3d are in world space.
            # Usually Face is Y-Forward or Z-Forward?
            # Let's assume standard dental view (Looking at Y- or Y+)
            # OR better: use the Normal of the Best Fit Plane of the loop?

            # Calculate Best Fit Plane Normal
            bg_center = center
            # Simple covariance
            cov = Matrix(((0, 0, 0), (0, 0, 0), (0, 0, 0)))
            for p in pts_3d:
                d = p - bg_center
                cov[0][0] += d.x * d.x
                cov[0][1] += d.x * d.y
                cov[0][2] += d.x * d.z
                cov[1][1] += d.y * d.y
                cov[1][2] += d.y * d.z
                cov[2][2] += d.z * d.z
            cov[1][0] = cov[0][1]
            cov[2][0] = cov[0][2]
            cov[2][1] = cov[1][2]

            # Without eigen solver, assume View Direction is roughly -Y or what?
            # Let's use the average normal of the fan faces
            avg_normal = Vector((0, 0, 0))
            for poly in smesh.polygons:
                avg_normal += poly.normal
            if avg_normal.length > 0:
                avg_normal.normalize()
            else:
                avg_normal = Vector((0, -1, 0))  # Fallback

            # Find Apex (Point furthest in direction of normal)
            max_dist = -1e9
            apex_pt = pts_3d[0]

            for p in pts_3d:
                d = p.dot(avg_normal)
                if d > max_dist:
                    max_dist = d
                    apex_pt = p

            # Create Plane at Apex
            plane_name = "SMILE_Tangent_Plane"
            old_p = bpy.data.objects.get(plane_name)
            if old_p:
                bpy.data.objects.remove(old_p, do_unlink=True)

            pmesh = bpy.data.meshes.new(plane_name)
            pobj = bpy.data.objects.new(plane_name, pmesh)
            ensure_collection(COL_ARCH).objects.link(pobj)

            bm_p = bmesh.new()
            try:
                # 100mm x 50mm plane?
                w, h = 50.0, 25.0

                # Build rotation from normal
                # Z of plane = avg_normal
                z_axis = avg_normal
                # X axis ?
                x_axis = Vector((0, 0, 1)).cross(z_axis)
                if x_axis.length < 0.01:
                    x_axis = Vector((1, 0, 0))
                x_axis.normalize()
                y_axis = z_axis.cross(x_axis).normalize()

                # Verts relative to Apex
                v1 = bm_p.verts.new(apex_pt - x_axis * w - y_axis * h)
                v2 = bm_p.verts.new(apex_pt + x_axis * w - y_axis * h)
                v3 = bm_p.verts.new(apex_pt + x_axis * w + y_axis * h)
                v4 = bm_p.verts.new(apex_pt - x_axis * w + y_axis * h)

                bm_p.faces.new((v1, v2, v3, v4))
                bm_p.to_mesh(pmesh)
            finally:
                bm_p.free()

            pmesh.materials.append(mat)
            pobj.parent = final_obj

            print(f"✓ Created Tangent Plane at {apex_pt}")

        except Exception as e:
            print(f"Failed to create visible surfaces: {e}")
        # ------------------------------------

        arch_obj = bpy.data.objects.new("SMILE_Golden_Ruler_Arch", arch_curve_data)
        context.scene.collection.objects.link(arch_obj)
        cobj = arch_obj

        # Add Shrinkwrap modifier to make arch stick to face surface
        shrinkwrap = arch_obj.modifiers.new(name="Stick_To_Face", type="SHRINKWRAP")
        shrinkwrap.wrap_method = "PROJECT"
        shrinkwrap.wrap_mode = "OUTSIDE_SURFACE"
        shrinkwrap.use_project_z = True
        shrinkwrap.use_positive_direction = False
        shrinkwrap.use_negative_direction = True
        shrinkwrap.offset = 0.5  # Slight offset to prevent z-fighting

        # Find face mesh to use as shrinkwrap target
        face_mesh = None
        # Look for mesh with "face" or "scan" in name
        for obj in bpy.data.objects:
            if obj.type == "MESH" and any(
                keyword in obj.name.lower()
                for keyword in ["face", "scan", "head", "mesh"]
            ):
                # Prefer larger meshes (likely the face scan)
                if not face_mesh or len(obj.data.vertices) > len(
                    face_mesh.data.vertices
                ):
                    face_mesh = obj

        if face_mesh:
            shrinkwrap.target = face_mesh
            print(f"✓ Arch curve will stick to mesh: {face_mesh.name}")
        else:
            print(
                "⚠️  Warning: No face mesh found for shrinkwrap. Arch curve won't stick to surface."
            )
            print("   → Rename your face scan to include 'face' or 'scan' in the name")

        # Make arch curve follow ruler direction
        # Ensure target is active before changing mode
        context.view_layer.objects.active = target
        if context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")

        target.select_set(True)
        cobj.select_set(True)
        context.view_layer.objects.active = target

        # 4. Cut
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")

        try:
            bpy.ops.mesh.select_all(action="DESELECT")

            # Knife Project
            bpy.ops.mesh.knife_project(cut_through=False)

            # Select Inner Region
            bpy.ops.mesh.loop_to_region(select_bigger=False)

            # Aggressive Cleanup Logic:
            # 1. Switch to VERT mode to grab all vertices of these faces
            bpy.ops.mesh.select_mode(type="VERT")

            # 2. Delete Vertices (Removes all connected faces/edges)
            bpy.ops.mesh.delete(type="VERT")

            # 3. Remove "Floating" geometry that might have been missed (specks)
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)
            bpy.ops.mesh.select_all(action="DESELECT")

        except Exception as e:
            self.report({"WARNING"}, f"Cut failed: {e}")

        if target.name in bpy.data.objects:
            context.view_layer.objects.active = target
            bpy.ops.object.mode_set(mode="OBJECT")

        if cobj.name in bpy.data.objects:
            bpy.data.objects.remove(cobj, do_unlink=True)

        self.report({"INFO"}, "Smooth erase complete.")


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
                # No hit: Project onto a Virtual Plane
                # Plane is perpendicular to view? Or parallel to Front (XZ)?
                # Usually Smile Line is drawn in Front View.
                # Let's use a plane at the depth of the 3D Cursor or Active Object

                ref_point = context.scene.cursor.location
                if context.view_layer.objects.active:
                    ref_point = context.view_layer.objects.active.location

                # Project ray_origin + t * ray_dir to plane defined by ref_point
                # We want the point closest to ref_point?
                # Or intersection with plane passing through ref_point normal to view?
                # Intersection with Plane(Normal=ViewDir, Point=RefPoint)

                # (P - Ref) . Normal = 0
                # (Origin + t*Dir - Ref) . Normal = 0
                # t = (Ref - Origin) . Normal / (Dir . Normal)

                plane_normal = (
                    rv3d.view_matrix.inverted().to_3x3().col[2].normalized()
                )  # View Z axis
                # Actually, ray_dir is mostly -view_z.

                denom = ray_dir.dot(plane_normal)
                if abs(denom) > 1e-6:
                    t = (ref_point - ray_origin).dot(plane_normal) / denom
                    loc = ray_origin + ray_dir * t
                else:
                    loc = ray_origin + ray_dir * 100.0  # Fallback

                self._points.append(loc)

            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def create_curve_with_markers(self, context):
        """Create lip curve and control point markers for fine-tuning"""
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

        # Close the loop
        spline.use_cyclic_u = True

        obj = bpy.data.objects.new(name, cdata)
        col.objects.link(obj)
        obj.show_in_front = True
        obj.color = (1.0, 0.2, 0.5, 1.0)

        # Make curve a thin line (not a giant pipe)
        cdata.bevel_depth = 0.0005  # Thinned to 0.5mm
        cdata.bevel_resolution = 2

        # Parent to target if hit
        if self._target_obj:
            obj.parent = self._target_obj
            obj.matrix_parent_inverse = self._target_obj.matrix_world.inverted()
            self.report({"INFO"}, f"Lip Line locked to {self._target_obj.name}")

        # === CREATE CONTROL POINT MARKERS ===
        self.create_control_markers(context, obj, self._points, self._target_obj)

        ensure_active(obj)
        self.report(
            {"INFO"},
            "Lip Line Created with control markers. Drag markers to fine-tune, then click 'Generate Smile Arc'.",
        )

    def create_control_markers(self, context, curve_obj, points, target_obj):
        """Create draggable control point markers"""
        # Clear old markers
        old_markers = [
            obj for obj in bpy.data.objects if obj.name.startswith("SMILE_LipCtrl_")
        ]
        for marker in old_markers:
            bpy.data.objects.remove(marker, do_unlink=True)

        # Create new markers
        for i, pt in enumerate(points):
            marker_name = f"SMILE_LipCtrl_{i:02d}"

            # Create small sphere marker
            if target_obj and target_obj.type == "MESH":
                try:
                    # Use make_marker for sticky behavior if we have a target mesh
                    make_marker(
                        name=marker_name,
                        world_location=pt,
                        size=0.002,  # 2mm marker
                        target_obj=target_obj,
                        rgba=(1.0, 0.8, 0.2, 1.0),  # Yellow-orange
                        shape="SPHERE",
                        sticky=True,
                    )
                except Exception:
                    # Fallback: create simple empty
                    self.create_simple_marker(marker_name, pt, curve_obj)
            else:
                # No target mesh, create simple empty
                self.create_simple_marker(marker_name, pt, curve_obj)

            # Store marker index for curve update
            marker = bpy.data.objects.get(marker_name)
            if marker:
                marker["SMILE_LIP_CTRL_INDEX"] = i
                marker["SMILE_LIP_CURVE"] = curve_obj.name

    def create_simple_marker(self, name, location, curve_obj):
        """Create simple marker without shrinkwrap"""
        col = ensure_collection(COL_ARCH)

        # Create sphere mesh
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.002, location=location)
        marker = bpy.context.active_object
        marker.name = name

        # Link to collection
        if marker.name not in col.objects:
            col.objects.link(marker)
            bpy.context.scene.collection.objects.unlink(marker)

        # Visual properties
        marker.show_in_front = True
        marker.color = (1.0, 0.8, 0.2, 1.0)  # Yellow-orange

        # Create emission material
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
    """Update Lip Curve based on control marker positions"""

    bl_idname = "smile.update_lip_curve"
    bl_label = "Update Lip Curve from Markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Find lip curve
        curve_obj = bpy.data.objects.get("SMILE_Lip_Curve")
        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"WARNING"}, "Lip curve not found")
            return {"CANCELLED"}

        # Find all control markers
        markers = sorted(
            [obj for obj in bpy.data.objects if obj.name.startswith("SMILE_LipCtrl_")],
            key=lambda x: x.get("SMILE_LIP_CTRL_INDEX", 0),
        )

        if not markers:
            self.report({"WARNING"}, "No control markers found")
            return {"CANCELLED"}

        # Update curve points based on marker positions
        if curve_obj.data.splines:
            spline = curve_obj.data.splines[0]

            # Ensure we have correct number of points
            if len(spline.bezier_points) != len(markers):
                self.report(
                    {"ERROR"},
                    f"Point mismatch: {len(spline.bezier_points)} curve points vs {len(markers)} markers",
                )
                return {"CANCELLED"}

            # Update each bezier point position
            for i, marker in enumerate(markers):
                if i < len(spline.bezier_points):
                    # Get marker world position
                    marker_pos = marker.matrix_world.translation

                    # Convert to curve's local space if curve is parented
                    if curve_obj.parent:
                        parent_inv = curve_obj.matrix_world.inverted()
                        local_pos = parent_inv @ marker_pos
                        spline.bezier_points[i].co = local_pos
                    else:
                        spline.bezier_points[i].co = marker_pos

                    # Keep AUTO handles for smooth curvature
                    spline.bezier_points[i].handle_left_type = "AUTO"
                    spline.bezier_points[i].handle_right_type = "AUTO"

            # Update curve data
            curve_obj.data.update_tag()
            context.view_layer.update()

            self.report(
                {"INFO"}, f"Updated lip curve with {len(markers)} control points"
            )
            return {"FINISHED"}

        return {"CANCELLED"}


class SMILE_OT_clear_lip_markers(bpy.types.Operator):
    """Remove all lip curve control markers"""

    bl_idname = "smile.clear_lip_markers"
    bl_label = "Clear Lip Control Markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Find and delete all markers
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
        # Create Curve Object
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
        final_obj.color = (0.0, 0.5, 1.0, 1.0)  # Blue-ish

        # --- VISIBLE SURFACES & TANGENT PLANE ---
        try:
            # Material
            mat_name = "SMILE_Project_Surface"
            mat = bpy.data.materials.get(mat_name)
            if not mat:
                # Create if missing
                mat = bpy.data.materials.new(mat_name)
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                nodes.clear()
                bsdf = nodes.new("ShaderNodeBsdfPrincipled")
                bsdf.inputs["Base Color"].default_value = (0.0, 0.5, 1.0, 1.0)
                bsdf.inputs["Roughness"].default_value = 0.4
                p = context.scene.smile_v2
                bsdf.inputs["Alpha"].default_value = getattr(p, "surface_opacity", 0.5)
                out = nodes.new("ShaderNodeOutputMaterial")
                mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
                mat.blend_method = "BLEND"
                mat.show_transparent_back = False

            # 1. Lip Surface (Inner Loop)
            surf_name = "SMILE_Lip_Surface"
            # Remove old
            old_s = bpy.data.objects.get(surf_name)
            if old_s:
                bpy.data.objects.remove(old_s, do_unlink=True)

            smesh = bpy.data.meshes.new(surf_name)
            sobj = bpy.data.objects.new(surf_name, smesh)
            ensure_collection(COL_ARCH).objects.link(sobj)

            import bmesh

            bm = bmesh.new()
            try:
                b_verts = [bm.verts.new(p) for p in pts]

                # Fan Fill
                # (Assuming convex-ish loop for simple fan)
                center = Vector((0, 0, 0))
                for p in pts:
                    center += p
                center /= len(pts)
                c_vert = bm.verts.new(center)

                for i in range(len(b_verts)):
                    v1 = b_verts[i]
                    v2 = b_verts[(i + 1) % len(b_verts)]
                    try:
                        bm.faces.new((v1, v2, c_vert))
                    except Exception:
                        pass

                bm.to_mesh(smesh)
            finally:
                bm.free()

            smesh.materials.append(mat)
            sobj.parent = final_obj

            # 2. Tangent Plane @ Apex
            avg_normal = Vector((0, 0, 0))
            for poly in smesh.polygons:
                avg_normal += poly.normal
            if avg_normal.length > 0:
                avg_normal.normalize()
            else:
                avg_normal = Vector((0, -1, 0))  # Fallback

            # Find Apex
            max_dist = -1e9
            apex_pt = pts[0]
            for p in pts:
                d = p.dot(avg_normal)
                if d > max_dist:
                    max_dist = d
                    apex_pt = p

            # Create Plane
            plane_name = "SMILE_Tangent_Plane"
            old_p = bpy.data.objects.get(plane_name)
            if old_p:
                bpy.data.objects.remove(old_p, do_unlink=True)

            pmesh = bpy.data.meshes.new(plane_name)
            pobj = bpy.data.objects.new(plane_name, pmesh)
            ensure_collection(COL_ARCH).objects.link(pobj)

            bm_p = bmesh.new()
            try:
                w, h = 50.0, 25.0

                z_axis = avg_normal
                x_axis = Vector((0, 0, 1)).cross(z_axis)
                if x_axis.length < 0.01:
                    x_axis = Vector((1, 0, 0))
                x_axis.normalize()
                y_axis = z_axis.cross(x_axis).normalize()

                v1 = bm_p.verts.new(apex_pt - x_axis * w - y_axis * h)
                v2 = bm_p.verts.new(apex_pt + x_axis * w - y_axis * h)
                v3 = bm_p.verts.new(apex_pt + x_axis * w + y_axis * h)
                v4 = bm_p.verts.new(apex_pt - x_axis * w + y_axis * h)

                bm_p.faces.new((v1, v2, v3, v4))
                bm_p.to_mesh(pmesh)
            finally:
                bm_p.free()

            pmesh.materials.append(mat)
            pobj.parent = final_obj

            print(f"✓ Created Tangent Plane at {apex_pt}")

        except Exception as e:
            print(f"Failed to create visible surfaces in Generate Smile Arc: {e}")
            import traceback

            traceback.print_exc()

        # === CREATE ACTUAL SMILE ARC CURVE (Upper Edge Only) ===
        self.create_smile_arc_curve(context, pts, final_obj)

        # === CLINICAL ANALYSIS ===
        self.add_clinical_analysis(context, pts, final_obj, apex_pt)

        self.report({"INFO"}, "Smile Arc Generated with clinical analysis.")
        return {"FINISHED"}

    def create_smile_arc_curve(self, context, pts, parent_obj):
        """Create the actual smile arc curve (incisal edge line)"""
        try:
            # Extract upper edge points (highest Z values = incisal edge area)
            pts_with_z = [(p, p.z) for p in pts]
            pts_sorted = sorted(pts_with_z, key=lambda x: x[1], reverse=True)

            # Take top 40% as smile arc points
            arc_count = max(3, len(pts_sorted) // 3)  # At least 3 points
            arc_points = [p[0] for p in pts_sorted[:arc_count]]

            # Sort left to right for proper curve direction
            arc_points_sorted = sorted(arc_points, key=lambda p: p.x)

            if len(arc_points_sorted) < 3:
                print("Not enough points for smile arc curve")
                return

            # Create curve for smile arc (open curve, not closed)
            arc_name = "SMILE_Arc_Incisal"
            old_arc = bpy.data.objects.get(arc_name)
            if old_arc:
                bpy.data.objects.remove(old_arc, do_unlink=True)

            arc_data = bpy.data.curves.new(f"{arc_name}_Data", "CURVE")
            arc_data.dimensions = "3D"
            spline = arc_data.splines.new("BEZIER")
            spline.bezier_points.add(len(arc_points_sorted) - 1)

            for i, p in enumerate(arc_points_sorted):
                spline.bezier_points[i].co = p
                spline.bezier_points[i].handle_left_type = "AUTO"
                spline.bezier_points[i].handle_right_type = "AUTO"

            # NOT CYCLIC - this is an open arc
            spline.use_cyclic_u = False

            arc_obj = bpy.data.objects.new(arc_name, arc_data)
            ensure_collection(COL_ARCH).objects.link(arc_obj)
            arc_obj.show_in_front = True
            arc_obj.color = (1.0, 0.8, 0.0, 1.0)  # Orange/gold color

            # Make it a visible thick line
            arc_data.bevel_depth = 0.001  # 1mm thick
            arc_data.bevel_resolution = 2

            # Parent to main arc object
            arc_obj.parent = parent_obj

            print(f"✓ Created Smile Arc Curve with {len(arc_points_sorted)} points")

        except Exception as e:
            print(f"Failed to create smile arc curve: {e}")
            import traceback

            traceback.print_exc()

    def add_clinical_analysis(self, context, pts, arc_obj, apex_pt):
        """Add clinical measurements and analysis overlays"""
        try:
            # Extract the actual smile arc (upper edge of smile zone)
            # For now, we'll identify this as the points with highest Z values
            # In a clinical context, this would be the incisal edge line

            # Sort points by Z coordinate (vertical position)
            pts_with_z = [(p, p.z) for p in pts]
            pts_sorted = sorted(pts_with_z, key=lambda x: x[1], reverse=True)

            # Take top 50% as the "smile arc" (upper edge)
            arc_points = [p[0] for p in pts_sorted[: len(pts_sorted) // 2]]

            # Sort by X coordinate to get left-to-right order
            arc_points_sorted = sorted(arc_points, key=lambda p: p.x)

            if len(arc_points_sorted) < 3:
                print("Not enough points for arc analysis")
                return

            # Calculate arc measurements
            leftmost = arc_points_sorted[0]
            rightmost = arc_points_sorted[-1]
            span = (rightmost - leftmost).length

            # Find the lowest point (deepest incisal curve)
            lowest_pt = min(arc_points_sorted, key=lambda p: p.z)
            arc_depth = apex_pt.z - lowest_pt.z

            # Calculate symmetry (distance from center to apex)
            center_x = (leftmost.x + rightmost.x) / 2.0
            apex_offset = abs(apex_pt.x - center_x)
            symmetry_ratio = (apex_offset / (span / 2.0)) * 100.0 if span > 0 else 0

            # Create analysis text annotation
            info_text = (
                f"Smile Arc Analysis:\n"
                f"  Span: {span * 1000:.1f}mm\n"
                f"  Arc Depth: {arc_depth * 1000:.1f}mm\n"
                f"  Symmetry Offset: {symmetry_ratio:.1f}%\n"
                f"  Apex Position: ({apex_pt.x * 1000:.1f}, {apex_pt.y * 1000:.1f}, {apex_pt.z * 1000:.1f})"
            )

            print(f"\n{'=' * 50}")
            print(info_text)
            print(f"{'=' * 50}\n")

            # Store measurements on the arc object for later retrieval
            arc_obj["SMILE_ARC_SPAN"] = span * 1000  # Convert to mm
            arc_obj["SMILE_ARC_DEPTH"] = arc_depth * 1000
            arc_obj["SMILE_ARC_SYMMETRY"] = symmetry_ratio
            arc_obj["SMILE_ARC_APEX"] = [apex_pt.x, apex_pt.y, apex_pt.z]

        except Exception as e:
            print(f"Failed to add clinical analysis: {e}")
            import traceback

            traceback.print_exc()


class SMILE_OT_chain_move(bpy.types.Operator):
    bl_idname = "smile.chain_move"
    bl_label = "Chain Move (Linked)"
    bl_options = {"REGISTER", "UNDO"}

    _init_mouse_x = 0
    _active_tooth = None
    _teeth_sorted = []
    _init_locs = {}  # name -> vector

    def invoke(self, context, event):
        def _is_tooth_candidate(o):
            if not o or o.type != "MESH":
                return False
            if bool(o.get("SMILE_IS_TOOTH", False)):
                return True
            if "SMILE" in o.name.upper():
                return True
            return parse_tooth_id_from_name(o.name) is not None

        obj = context.view_layer.objects.active
        if not _is_tooth_candidate(obj):
            for cand in context.selected_objects:
                if _is_tooth_candidate(cand):
                    obj = cand
                    context.view_layer.objects.active = cand
                    break

        if not _is_tooth_candidate(obj):
            self.report({"ERROR"}, "Select an active tooth mesh first (e.g., T11/#8).")
            return {"CANCELLED"}

        self._active_tooth = obj
        self._init_mouse_x = event.mouse_region_x

        # Predictable behavior: if user selected teeth, operate on that set;
        # otherwise fall back to all teeth in Teeth collection.
        selected_teeth = [o for o in context.selected_objects if _is_tooth_candidate(o)]
        teeth_pool = selected_teeth if selected_teeth else tooth_objects_in_collection()
        self._teeth_sorted = sort_teeth_by_fdi(teeth_pool)

        if obj not in self._teeth_sorted:
            self._teeth_sorted.append(obj)
            self._teeth_sorted = sort_teeth_by_fdi(self._teeth_sorted)

        if not self._teeth_sorted:
            self.report({"ERROR"}, "No tooth meshes found for Chain Move.")
            return {"CANCELLED"}

        self._init_locs = {t.name: t.location.copy() for t in self._teeth_sorted}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return {"FINISHED"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            for t in self._teeth_sorted:
                if t.name in self._init_locs:
                    t.location = self._init_locs[t.name]
            return {"CANCELLED"}

        if event.type != "MOUSEMOVE":
            return {"RUNNING_MODAL"}

        if not self._teeth_sorted or not self._active_tooth:
            return {"CANCELLED"}

        try:
            idx = self._teeth_sorted.index(self._active_tooth)
        except ValueError:
            idx = 0

        # Deterministic mapping from mouse delta to global X displacement.
        # No cumulative drift: all updates are computed from initial positions.
        delta_x = (event.mouse_region_x - self._init_mouse_x) * 0.002

        for i, t in enumerate(self._teeth_sorted):
            base = self._init_locs.get(t.name, t.location.copy())
            dist = abs(i - idx)

            # Smooth falloff to neighbors (1.0 active, lower for farther teeth).
            w = max(0.0, 1.0 - 0.22 * float(dist))
            w = w * w

            t.location = Vector((base.x + delta_x * w, base.y, base.z))

        return {"RUNNING_MODAL"}


class SMILE_OT_lock_alignment(bpy.types.Operator):
    bl_idname = "smile.lock_alignment"
    bl_label = "Lock Source to Target"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2
        src_obj = get_target_object_by_domain(context, p.align_source_domain)
        tgt_obj = get_target_object_by_domain(context, p.align_target_domain)

        if not src_obj or not tgt_obj:
            self.report({"ERROR"}, "Source or Target missing")
            return {"CANCELLED"}

        # Parent src to tgt
        src_obj.parent = tgt_obj
        src_obj.matrix_parent_inverse = tgt_obj.matrix_world.inverted()

        self.report({"INFO"}, f"Locked {src_obj.name} to {tgt_obj.name}")
        return {"FINISHED"}


class SMILE_OT_unlock_alignment(bpy.types.Operator):
    bl_idname = "smile.unlock_alignment"
    bl_label = "Unlock Source"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.smile_v2

        def _get_obj(domain):
            if domain == DOMAIN_FACE:
                name = p.face_target
            elif domain == DOMAIN_MAX:
                name = p.max_target
            elif domain == DOMAIN_MAN:
                name = p.man_target
            else:
                name = p.photo_target
            return bpy.data.objects.get(name)

        src = _get_obj(p.align_source_domain)

        if not src:
            self.report({"ERROR"}, "Source missing")
            return {"CANCELLED"}

        # Clear parent but keep transform
        mw = src.matrix_world.copy()
        src.parent = None
        src.matrix_world = mw

        self.report({"INFO"}, f"Unlocked {src.name}")
        return {"FINISHED"}


def update_surface_alpha(self, context):
    try:
        val = self.surface_opacity
        # Material names to update
        mat_names = ["SMILE_Project_Surface", "SMILE_Lip_Surface_Mat"]

        for name in mat_names:
            mat = bpy.data.materials.get(name)
            if mat and mat.use_nodes:
                # Try to find Principled BSDF
                bsdf = None
                for n in mat.node_tree.nodes:
                    if n.type == "BSDF_PRINCIPLED":
                        bsdf = n
                        break

                if bsdf:
                    bsdf.inputs["Alpha"].default_value = val
                else:
                    # Fallback: Transparent BSDF Mix?
                    # If user manually edited, just try to find an input named 'Alpha'
                    for n in mat.node_tree.nodes:
                        if "Alpha" in n.inputs:
                            n.inputs["Alpha"].default_value = val

    except Exception as e:
        print(f"Alpha update failed: {e}")


# (Redundant SmileAddonStateV2 definition removed)


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
            from bpy_extras.object_utils import world_to_camera_view

            coord = (event.mouse_region_x, event.mouse_region_y)
            cam = scene.camera

            # Use Blender's native projection to find UV on the camera 'film'
            ray_origin = region_2d_to_origin_3d(region, rv3d, coord)
            ray_vector = region_2d_to_vector_3d(region, rv3d, coord)
            p_world = ray_origin + ray_vector * 10.0  # 10m depth

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

            self.report({"INFO"}, f"Marked Point #{idx} (u={u:.3f}, v={v:.3f})")
            return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


def _import_calib_arch_for_tooth_id(tooth_id: int) -> str:
    tid = int(tooth_id)
    return "MAX" if 1 <= tid <= 16 else "MAN"


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


def _has_import_tooth_lm3_local(obj) -> bool:
    return len(_load_import_tooth_lm3_local(obj)) >= 3


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


def _clear_import_arch_reference(scene, arch: str):
    if not scene:
        return
    key = _import_arch_ref_key_for_arch(arch)
    if key in scene:
        del scene[key]


def _has_import_arch_reference(scene, arch: str) -> bool:
    oc, cv, _ = _load_import_arch_reference(scene, arch)
    return (oc is not None) and (cv is not None)


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


def _clear_mirror_midline_point(scene, arch: str):
    if not scene:
        return
    k = _mirror_midline_key_for_arch(arch)
    if k in scene:
        del scene[k]


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

        # Import based on file extension
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

        # Get imported object (assume it's the active object after import)
        tooth_obj = context.view_layer.objects.active
        if not tooth_obj or tooth_obj.type != "MESH":
            self.report({"ERROR"}, "No mesh object imported.")
            return {"CANCELLED"}

        # Rename to indicate mockup
        base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        tooth_obj.name = f"MOCKUP_{base_name}"

        # Auto-normalize to unit scale
        normalize_tooth_model(tooth_obj)

        # Auto-orient to camera (if in camera view)
        if scene.camera:
            auto_orient_tooth_to_camera_pca(tooth_obj, scene.camera)

        # Position in front of camera at default depth (not AT camera)
        if scene.camera:
            cam = scene.camera
            # Get camera's forward direction (negative Z in camera space)
            forward = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
            # Place tooth at default depth in front of camera
            default_depth_mm = p.mockup_depth_mm  # Default 800mm
            # Convert mm to Blender units (assuming 1 BU = 1mm in this addon)
            depth_bu = default_depth_mm / 1000.0
            tooth_obj.location = cam.matrix_world.translation + (forward * depth_bu)
        else:
            # No camera - place at origin
            tooth_obj.location = Vector((0, 0, 0))

        # Link to TEETH collection
        col_teeth = ensure_collection(COL_TEETH)
        if tooth_obj.name not in col_teeth.objects:
            col_teeth.objects.link(tooth_obj)

        # Store as active mockup tooth
        p.mockup_active_tooth = tooth_obj

        # Mark as needing calibration
        tooth_obj["MOCKUP_NEEDS_CALIBRATION"] = True
        tooth_obj["MOCKUP_NORMALIZED_SCALE"] = 1.0

        # Keep active/selected state and center viewport orbit on imported tooth.
        try:
            for o in context.selected_objects:
                o.select_set(False)
            tooth_obj.select_set(True)
            context.view_layer.objects.active = tooth_obj
        except Exception:
            pass
        _center_trackball_on_object(context, tooth_obj, focus_view=True)
        pinned_ok, pinned_name = _cad_autopin_reference_from_import(
            context,
            [tooth_obj],
            preferred_obj=tooth_obj,
            force_replace=False,
        )

        msg = f"Imported and normalized: {tooth_obj.name}. Next: Calibrate scale."
        if pinned_ok and pinned_name:
            msg += f" CAD reference pinned: {pinned_name}."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SMILE_OT_smart_batch_import(bpy.types.Operator, ImportHelper):
    """Batch Import & Auto-Place Teeth (Smart)"""

    bl_idname = "smile.smart_batch_import"
    bl_label = "Smart Batch Import"
    bl_options = {"REGISTER", "UNDO"}

    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"}
    )
    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    filter_glob: bpy.props.StringProperty(
        default="*.obj;*.stl;*.ply",
        options={"HIDDEN"},
        maxlen=255,
    )

    def execute(self, context):
        import os

        # 1. Import Files
        folder = os.path.dirname(self.filepath) if self.filepath else self.directory

        imported_objects = []
        import_errors = []

        # Handle single vs multiple files
        file_list = self.files
        if not file_list and self.filepath:
            # Manually create list for single file
            class TempFile:
                pass

            t = TempFile()
            t.name = os.path.basename(self.filepath)
            file_list = [t]

        for file_elem in file_list:
            filepath = os.path.join(folder, file_elem.name)
            if not os.path.isfile(filepath):
                continue

            ext = os.path.splitext(filepath)[1].lower()
            if ext not in {".obj", ".stl", ".ply"}:
                import_errors.append(f"{file_elem.name}: unsupported file type '{ext}'")
                continue

            # Helper to track new objects
            old_objs = set(context.scene.objects)

            try:
                if ext == ".obj":
                    bpy.ops.import_scene.obj(
                        filepath=filepath,
                        use_split_objects=False,
                        use_split_groups=False,
                    )
                elif ext == ".stl":
                    bpy.ops.import_mesh.stl(filepath=filepath)
                elif ext == ".ply":
                    bpy.ops.import_mesh.ply(filepath=filepath)
            except Exception as e:
                import_errors.append(f"{file_elem.name}: import failed ({e})")
                continue

            new_objs = set(context.scene.objects) - old_objs

            for obj in new_objs:
                if obj.type == "MESH":
                    obj.name = os.path.splitext(file_elem.name)[
                        0
                    ]  # Rename to filename without ext
                    imported_objects.append(obj)

        if not imported_objects:
            if import_errors:
                print("[BlenderSmile][SmartBatchImport] Import errors:")
                for err in import_errors:
                    print(f"  - {err}")
                self.report({"ERROR"}, import_errors[0])
            self.report({"WARNING"}, "No meshes imported")
            return {"CANCELLED"}

        # 2. Normalize Each Object
        for obj in imported_objects:
            # A) Set Origin to Geometry
            context.view_layer.objects.active = obj
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")

            # B) PCA Upright
            basis = calculate_pca_basis(obj)
            if basis:
                # vec1 (Long) -> Z, vec2 (Wide) -> X
                vec1, vec2, vec3, center = basis
                align_object_to_frame(obj, vec_z=vec1, vec_x=vec2)

            # C) Center at Origin
            obj.location = (0, 0, 0)

            # D) Tag Properties
            obj["SMILE_IS_TOOTH"] = True
            obj["MOCKUP_NORMALIZED_SCALE"] = 1.0

            # E) Link to Collection
            link_to_collection(obj, ensure_collection(COL_TEETH))

        # 3. Call Auto-Arrange
        bpy.ops.object.select_all(action="DESELECT")
        for obj in imported_objects:
            obj.select_set(True)

        context.view_layer.objects.active = imported_objects[0]

        # Call the existing dual curve arrangement
        try:
            bpy.ops.smile.arrange_dual_curves()
        except Exception as e:
            self.report({"WARNING"}, f"Arrangement failed: {e}")

        if import_errors:
            print("[BlenderSmile][SmartBatchImport] Import errors:")
            for err in import_errors:
                print(f"  - {err}")
            shown = min(2, len(import_errors))
            for err in import_errors[:shown]:
                self.report({"WARNING"}, err)
            if len(import_errors) > shown:
                self.report(
                    {"WARNING"},
                    f"{len(import_errors) - shown} additional import error(s); see system console.",
                )

        self.report({"INFO"}, f"Imported & Arranged {len(imported_objects)} teeth.")
        return {"FINISHED"}


class SMILE_OT_snap_mockup_to_arch(bpy.types.Operator):
    """Snap selected mockup teeth to dental arch curve"""

    bl_idname = "smile.snap_mockup_to_arch"
    bl_label = "Snap to Arch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Find arch curve
        arch_curve = None
        for obj in context.scene.objects:
            if obj.type == "CURVE" and "arch" in obj.name.lower():
                arch_curve = obj
                break

        if not arch_curve:
            self.report({"ERROR"}, "No arch curve found. Create one first.")
            return {"CANCELLED"}

        # Get selected mockup teeth
        mockup_teeth = []
        for obj in context.selected_objects:
            if obj.type == "MESH":
                # Check if it's a mockup tooth
                if (
                    "MOCKUP" in obj.name.upper()
                    or obj.name
                    in bpy.data.collections.get(
                        COL_TEETH, bpy.data.collections.new("Teeth")
                    ).objects
                ):
                    mockup_teeth.append(obj)

        if not mockup_teeth:
            self.report({"WARNING"}, "No mockup teeth selected")
            return {"CANCELLED"}

        # Snap each tooth to arch
        for tooth_obj in mockup_teeth:
            # Find incisal edge (highest Z point of tooth)
            bbox_min, bbox_max = bbox_world(tooth_obj)
            incisal_z = bbox_max.z
            incisal_location = Vector(
                (tooth_obj.location.x, tooth_obj.location.y, incisal_z)
            )

            # Find closest point on arch curve
            closest_point, closest_param = self.find_closest_point_on_curve(
                arch_curve, incisal_location
            )

            if closest_point:
                # Move tooth so incisal edge aligns with curve point
                offset = closest_point - incisal_location
                tooth_obj.location += offset

                self.report({"INFO"}, f"Snapped {tooth_obj.name} to arch")

        context.view_layer.update()
        self.report({"INFO"}, f"Snapped {len(mockup_teeth)} teeth to arch curve")
        return {"FINISHED"}

    def find_closest_point_on_curve(self, curve_obj, target_location):
        """
        Find closest point on Bezier curve to target.

        Returns:
            (location: Vector, parameter: float)
        """
        if not curve_obj.data.splines:
            return None, 0.0

        spline = curve_obj.data.splines[0]

        # Sample curve at multiple points
        samples = 100
        closest_dist = float("inf")
        closest_point = None
        closest_param = 0.0

        for i in range(samples + 1):
            t = i / samples

            # Evaluate Bezier curve at parameter t
            if spline.type == "BEZIER":
                point = self.evaluate_bezier_at_t(spline, t)
            else:  # POLY or NURBS
                # For poly/NURBS, use simple linear interpolation between points
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

            # Transform to world space
            point_world = curve_obj.matrix_world @ point

            # Calculate distance (only in XY plane for arch)
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
        """Evaluate Bezier spline at parameter t [0,1]."""
        points = spline.bezier_points
        num_segments = len(points) - 1

        if num_segments < 1:
            return Vector((0, 0, 0))

        # Find which segment
        segment_idx = int(t * num_segments)
        if segment_idx >= num_segments:
            segment_idx = num_segments - 1

        # Local parameter within segment
        local_t = (t * num_segments) - segment_idx

        # Get control points
        p0 = points[segment_idx].co
        p1 = points[segment_idx].handle_right
        p2 = points[segment_idx + 1].handle_left
        p3 = points[segment_idx + 1].co

        # Cubic Bezier formula
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

        # Clear active tooth if it was this one
        props = context.scene.smile_v2
        if props.mockup_active_tooth == tooth_obj:
            # Reset mockup workflow state
            props.mockup_active_tooth = None

        # Delete the object
        bpy.data.objects.remove(tooth_obj, do_unlink=True)

        self.report({"INFO"}, f"Deleted {self.tooth_name}")
        return {"FINISHED"}


# ============================================================================
# DUAL-CURVE TOOTH ARRANGEMENT
# ============================================================================


def evaluate_curve_at_parameter(curve_obj, t):
    """Evaluate curve at parameter t [0,1], returns world space position."""
    if not curve_obj or not curve_obj.data.splines:
        return Vector((0, 0, 0))

    spline = curve_obj.data.splines[0]

    if spline.type == "BEZIER":
        points = spline.bezier_points
        num_segments = len(points) - 1

        if num_segments < 1:
            return curve_obj.matrix_world @ points[0].co

        segment_idx = int(t * num_segments)
        if segment_idx >= num_segments:
            segment_idx = num_segments - 1

        local_t = (t * num_segments) - segment_idx

        p0 = points[segment_idx].co
        p1 = points[segment_idx].handle_right
        p2 = points[segment_idx + 1].handle_left
        p3 = points[segment_idx + 1].co

        s = 1 - local_t
        local_point = (
            s**3 * p0
            + 3 * s**2 * local_t * p1
            + 3 * s * local_t**2 * p2
            + local_t**3 * p3
        )

        return curve_obj.matrix_world @ local_point

    else:  # POLY or NURBS
        num_points = len(spline.points)
        if num_points < 2:
            return curve_obj.matrix_world @ Vector(spline.points[0].co[:3])

        idx = int(t * (num_points - 1))
        if idx >= num_points - 1:
            return curve_obj.matrix_world @ Vector(spline.points[-1].co[:3])

        p1 = Vector(spline.points[idx].co[:3])
        p2 = Vector(spline.points[idx + 1].co[:3])
        local_t = (t * (num_points - 1)) - idx
        local_point = p1.lerp(p2, local_t)

        return curve_obj.matrix_world @ local_point


def curve_tangent_at_parameter(curve_obj, t, delta=0.01):
    """Calculate tangent vector at parameter t using finite difference."""
    t_before = max(0.0, t - delta)
    t_after = min(1.0, t + delta)

    p_before = evaluate_curve_at_parameter(curve_obj, t_before)
    p_after = evaluate_curve_at_parameter(curve_obj, t_after)

    tangent = (p_after - p_before).normalized()
    return tangent


def calculate_width_distribution(num_teeth):
    """Calculate distribution based on tooth widths."""
    if num_teeth == 6:
        widths = [7.5, 6.5, 8.5, 8.5, 6.5, 7.5]  # Canine to canine
    elif num_teeth == 4:
        widths = [6.5, 8.5, 8.5, 6.5]  # Lateral to lateral
    elif num_teeth == 2:
        widths = [8.5, 8.5]  # Centrals only
    else:
        return [i / (num_teeth - 1) if num_teeth > 1 else 0.5 for i in range(num_teeth)]

    total = sum(widths)
    params = []
    cumulative = 0

    for width in widths:
        params.append(cumulative / total)
        cumulative += width

    return params


def arrange_chain_on_curve(scene, teeth_objs, arch_curve):
    """
    Arrange a list of arbitrary teeth along the arch curve using a 'Chain Spread' algorithm.
    Center of the chain is placed at t=0.5 of the curve.
    """
    if not teeth_objs or not arch_curve:
        return

    # 1. Sort teeth by X-position (Left -> Right)
    # Global X usually corresponds to Right->Left or Left->Right depending on view
    # Assuming standard face view: +X is Left (Patient Left), -X is Right.
    # We want to traverse from Patient Right (-X) to Patient Left (+X)
    teeth_objs.sort(key=lambda o: o.matrix_world.translation.x)

    count = len(teeth_objs)
    mid_idx = count // 2

    # If even number, mid_idx is the first of the right half.
    # e.g. 4 teeth: indices 0,1,2,3. mid_idx=2.
    # visual: [0][1] | [2][3]
    # We want to start slightly offset from center?
    # Simpler: Start placing from the middle OUTWARDS.

    # 2. Get Golden Ruler Widths (if available)
    ruler_obj = bpy.data.objects.get("SMILE_Golden_Ruler")
    target_widths = []

    if (
        ruler_obj
        and "SMILE_OFFSETS" in ruler_obj
        and "SMILE_P1" in ruler_obj
        and "SMILE_P2" in ruler_obj
    ):
        try:
            p1 = Vector(ruler_obj["SMILE_P1"])
            p2 = Vector(ruler_obj["SMILE_P2"])
            ruler_len = (p2 - p1).length

            # Convert offsets to list
            off_prop = ruler_obj["SMILE_OFFSETS"]
            offsets = off_prop.to_list() if hasattr(off_prop, "to_list") else off_prop

            # Calculate segment widths
            # Offsets are usually [0, ..., 1].
            # Segments are between offsets.
            # Number of teeth supported by ruler = len(offsets) - 1?
            # Usually Golden Ruler supports 6 teeth (#6-#11).
            # Let's check offset count. If valid, calculating widths.

            if len(offsets) >= 2:
                for k in range(len(offsets) - 1):
                    seg_w = (offsets[k + 1] - offsets[k]) * ruler_len
                    target_widths.append(seg_w)

        except Exception as e:
            print(f"Ruler readout error: {e}")
            pass

    # Measure widths & Apply Scale if Ruler matches count
    widths = []

    # Check if we should apply ruler scaling
    # Rule: If we selected exactly the same number of teeth as ruler segments (usually 6)
    apply_ruler_scale = len(target_widths) > 0 and len(target_widths) == count

    if apply_ruler_scale:
        print(f"Aligning {count} teeth to Golden Ruler Segments...")

    for i, obj in enumerate(teeth_objs):
        # Current Width (Visual)
        # Use dimensions.x but account for current scale
        curr_w = obj.dimensions.x

        if apply_ruler_scale:
            # Target Width from Ruler
            # Ruler segments are usually ordered Left-to-Right in the offsets list?
            # Or Right-to-Left?
            # Golden Ruler logic usually starts from 0 to 1.
            # If 0 is P1 and 1 is P2.
            # P1/P2 Orientation?
            # Standard: P1 is Right Canine (#6), P2 is Left Canine (#11).
            # So offsets 0->1 go #6 -> #11.
            # Our teeth are sorted by X.
            # If +X is Left (Patient Left), then Sorted X (Low->High) is Right->Left.
            # So index 0 is Rightmost (#6), index N is Leftmost (#11).
            # Matches Ruler order!

            t_width = target_widths[i]

            # Scale Factor
            if curr_w > 0.001:
                scale_ratio = t_width / curr_w
                # Apply Uniform Scale to preserve aspect
                obj.scale *= scale_ratio
                bpy.context.view_layer.update()  # Ensure dimensions update?

                # Update curr_w for spacing calculations
                curr_w = t_width

        widths.append(curr_w)

    # Total chain length (approx)
    total_len = sum(widths)

    # Curve Length
    # Simple sampling to estimate length
    # Or use splines[0].calc_length() if available?
    curve_len = 100.0  # fallback
    if arch_curve.data.splines:
        curve_len = arch_curve.data.splines[0].calc_length()
        # Scale by object matrix
        curve_len *= (
            arch_curve.channels[0].scale.x if hasattr(arch_curve, "channels") else 1.0
        )  # Rough approx
        # Actually calc_length is local. Need world scale.
        curve_len = arch_curve.data.splines[0].calc_length() * arch_curve.scale.x

    # Mapping Function: Length -> T
    def length_to_t(l_dist):
        return max(0.0, min(1.0, l_dist / curve_len))

    # Center T
    center_t = 0.5
    center_len = curve_len * 0.5

    # Place Middle(s)
    # If odd: Middle tooth is at center.
    # If even: The gap between mid_idx-1 and mid_idx is at center.

    # Assign center positions (arc lengths)
    positions = [0.0] * count

    if count % 2 == 1:
        # Odd
        # mid_idx is exactly at center
        positions[mid_idx] = center_len
    else:
        # Even
        # mid_idx starts at center + half its width
        # mid_idx-1 starts at center - half its width
        # gap is at center_len
        positions[mid_idx] = center_len + (widths[mid_idx] * 0.5)
        # We handle the rest in the loop

    # Propagate Right (Indices > mid_idx)
    current_pos = positions[mid_idx]
    if count % 2 == 1:
        current_pos += widths[mid_idx] * 0.5  # Right edge of middle tooth

    for i in range(mid_idx + 1, count):
        # Center of next tooth = current_edge + half_width
        positions[i] = current_pos + (widths[i] * 0.5)
        current_pos += widths[i]  # Adv to right edge

    # Propagate Left (Indices < mid_idx)
    # Starting from...
    if count % 2 == 1:
        current_pos = positions[mid_idx] - (
            widths[mid_idx] * 0.5
        )  # Left edge of middle
    else:
        # Even case: mid_idx calculated above.
        # We need mid_idx-1.
        current_pos = center_len - (widths[mid_idx - 1] * 0.5)  # Center of prev
        positions[mid_idx - 1] = current_pos
        current_pos -= widths[mid_idx - 1] * 0.5  # Left edge

        # Now loop downwards from mid_idx-2
        for i in range(mid_idx - 2, -1, -1):
            positions[i] = current_pos - (widths[i] * 0.5)
            current_pos -= widths[i]

    # Odd case Left loop
    if count % 2 == 1:
        for i in range(mid_idx - 1, -1, -1):
            positions[i] = current_pos - (widths[i] * 0.5)
            current_pos -= widths[i]

    # EXECUTE PLACEMENT
    for i, obj in enumerate(teeth_objs):
        pos_len = positions[i]
        t = length_to_t(pos_len)

        # 1. Location
        world_loc = evaluate_curve_at_parameter(arch_curve, t)
        obj.location = world_loc

        # 2. Rotation (Tangent/Normal)
        # Sample slightly ahead/behind to get tangent
        curr_t = t
        delta = 0.01
        p_fwd = evaluate_curve_at_parameter(arch_curve, min(1.0, curr_t + delta))
        p_back = evaluate_curve_at_parameter(arch_curve, max(0.0, curr_t - delta))
        tangent = (p_fwd - p_back).normalized()

        # Normal (Outward)
        # Cross tangent with Up (Z)
        up = Vector((0, 0, 1))
        normal = tangent.cross(up).normalized()

        # Align:
        # Tooth Y (Front) -> Curve Normal (Outward)
        # Tooth Z (Up) -> World Z (Up)
        # Tooth X -> Tangent

        # Create Rotation Matrix from axes
        # X=Tangent, Y=Normal, Z=Up
        # Check handedness? X cross Y = Z?
        # Tangent(X) cross Normal(Y) = (Tan x (Tan x Up)) -> Up. Correct.

        # But wait, standard tooth orientation:
        # Y is Front.
        # So we want Matrix where column Y is Normal.
        # column X is Tangent?
        # column Z is Up.

        # Let's try constructing the rotation matrix
        # Matrix columns: R_x, R_y, R_z
        # target_x = tangent * -1 (if Y is normal, X is usually left?)
        # Let's refine:
        # If I look at the face, Curve goes Right(-X) to Left(+X).
        # Tangent at center points +X.
        # Normal points -Y (Forward).
        # Tooth Y is Front. So Tooth Y -> Normal.
        # Tooth X is Side.

        target_y = normal
        target_z = up
        target_x = target_y.cross(target_z).normalized()

        rot_mat = Matrix((target_x, target_y, target_z)).transposed().to_3x3()
        # Why transposed? Matrix init takes rows?
        # Blender Matrix((col1, col2, col3)) is usually rows if passed as list of vectors?
        # No, Vector((x,y,z)) are rows.
        # So Matrix((vec_x, vec_y, vec_z)) creates a matrix with rows X, Y, Z.
        # We want X, Y, Z to be columns.
        # So yes, Transpose rows to columns.

        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = rot_mat.to_quaternion()

    print(f"Arranged {count} teeth in a chain.")


def get_aligned_meshes(context):
    """
    Find meshes aligned to active photo slot for surface attachment.

    Priority system:
    1. Objects with "SMILE_ALIGNED_TO_PHOTO" custom property matching active slot
    2. Objects in COL_FACE collection
    3. Objects in COL_ARCH collection
    4. All mesh objects in scene (fallback)

    Returns:
        List of mesh objects
    """
    aligned_meshes = []

    # Get active photo slot
    p = context.scene.smile_v2
    active_slot = _active_photo_slot(context.scene)
    slot_name = active_slot.name if active_slot else None

    # Priority 1: Explicitly marked objects
    if slot_name:
        for obj in context.scene.objects:
            if obj.type == "MESH":
                aligned_to = obj.get("SMILE_ALIGNED_TO_PHOTO")
                if aligned_to == slot_name:
                    aligned_meshes.append(obj)

        if aligned_meshes:
            return aligned_meshes

    # Priority 2: Scans collection (face scans, etc.)
    col_scans = bpy.data.collections.get(COL_SCANS)
    if col_scans:
        for obj in col_scans.objects:
            if obj.type == "MESH":
                aligned_meshes.append(obj)

    if aligned_meshes:
        return aligned_meshes

    # Priority 3: Arch collection (exclude curves)
    col_arch = bpy.data.collections.get(COL_ARCH)
    if col_arch:
        for obj in col_arch.objects:
            if obj.type == "MESH" and "Curve" not in obj.name:
                aligned_meshes.append(obj)

    if aligned_meshes:
        return aligned_meshes

    # Fallback: All meshes
    return [obj for obj in context.scene.objects if obj.type == "MESH"]


def raycast_to_aligned_mesh(context, screen_coord):
    """
    Cast ray from camera through screen coordinate to find 3D surface intersection.

    Args:
        context: Blender context
        screen_coord: (x, y) tuple in region coordinates

    Returns:
        Tuple: (hit: bool, location: Vector, normal: Vector, obj: Object)
               Returns (False, None, None, None) if no hit
    """
    region = context.region
    rv3d = context.region_data

    if not region or not rv3d:
        return (False, None, None, None)

    # Get ray from screen to world
    ray_origin = region_2d_to_origin_3d(region, rv3d, screen_coord)
    ray_direction = region_2d_to_vector_3d(region, rv3d, screen_coord).normalized()

    # Get target meshes
    target_meshes = get_aligned_meshes(context)

    if not target_meshes:
        return (False, None, None, None)

    # Raycast against each mesh, find closest hit
    closest_hit = None
    closest_dist = float("inf")

    for obj in target_meshes:
        if not obj.data:
            continue

        # Transform ray to object space
        obj_mat_inv = obj.matrix_world.inverted()
        ray_origin_local = obj_mat_inv @ ray_origin
        ray_dir_local = (obj_mat_inv.to_3x3() @ ray_direction).normalized()

        # Raycast
        hit, location, normal, face_idx = obj.ray_cast(ray_origin_local, ray_dir_local)

        if hit:
            # Transform back to world space
            location_world = obj.matrix_world @ location
            normal_world = (obj.matrix_world.to_3x3() @ normal).normalized()

            dist = (location_world - ray_origin).length
            if dist < closest_dist:
                closest_dist = dist
                closest_hit = (True, location_world, normal_world, obj)

    return closest_hit if closest_hit else (False, None, None, None)


def attach_tooth_to_surface(tooth_obj, location, normal):
    """
    Position tooth to 3D surface point while preserving original orientation.

    Args:
        tooth_obj: Tooth mesh object to position
        location: World space position (Vector)
        normal: Surface normal at attachment point (Vector)
    """
    # Add small offset to prevent penetration through surface
    # Offset by 0.5mm along surface normal (outward from surface)
    offset_mm = 0.5
    adjusted_location = location + (
        normal * offset_mm / 1000.0
    )  # Convert mm to scene units

    # Position at surface (with offset)
    tooth_obj.location = adjusted_location.copy()

    # PRESERVE original orientation from PCA auto-orient
    # Do NOT change rotation_euler - tooth keeps anatomical orientation

    # Store metadata for later use
    tooth_obj["MOCKUP_SURFACE_LOCATION"] = adjusted_location
    tooth_obj["MOCKUP_SURFACE_NORMAL"] = normal
    tooth_obj["MOCKUP_LOCKED_TO_SURFACE"] = False  # Default: unlocked


class SMILE_OT_align_ruler_to_pupils(bpy.types.Operator):
    """Rotates the Golden Ruler to be parallel with the pupil line (Pupil_L - Pupil_R)."""

    bl_idname = "smile.align_ruler_to_pupils"
    bl_label = "Align Ruler to Pupils"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ruler = bpy.data.objects.get("SMILE_Golden_Ruler")
        if not ruler:
            self.report({"ERROR"}, "Golden Ruler not found")
            return {"CANCELLED"}

        # 1. Find Pupils
        pupil_r = bpy.data.objects.get("FACE_LM_Pupil_R")
        pupil_l = bpy.data.objects.get("FACE_LM_Pupil_L")

        if not pupil_r or not pupil_l:
            self.report(
                {"ERROR"},
                "Pupil landmarks (FACE_LM_Pupil_R, FACE_LM_Pupil_L) not found. Place them first.",
            )
            return {"CANCELLED"}

        # 2. Absolute Alignment (Snap to Orientation)
        # To prevent "jumping" or "toggling", we do not rotate relative to current state.
        # We construct a completely NEW rotation matrix that is guaranteed to be correct.

        pr_loc = pupil_r.matrix_world.translation
        pl_loc = pupil_l.matrix_world.translation

        # Target Vector (Left - Right) in World Space
        # We Flatten this to XZ plane to ignore depth (as requested for "Screen Look")
        target_vec = pl_loc - pr_loc
        target_vec.y = 0  # Force flat on depth for "2D Front View" parallel

        if target_vec.length_squared < 1e-6:
            self.report({"WARNING"}, "Pupils are too close or overlapping.")
            return {"CANCELLED"}

        target_right = target_vec.normalized()

        # Construct Basis Vectors
        # Forward = World Y (Depth)
        # Up = Cross Product
        # Right = Target Right

        forward = Vector((0, 1, 0))  # Standard Blender Y is depth/back.
        # Actually in Front View (-Y), Y points AWAY from viewer. (0,-1,0) is towards viewer?
        # Standard Face orientation: X=Right, Z=Up, Y=Back.
        # Let's use Y=(0,1,0) as the "Face Normal" (Backwards).

        up = target_right.cross(forward).normalized()

        # Re-orthogonalize forward just in case
        forward = up.cross(target_right).normalized()

        # Create Rotation Matrix from Column Vectors
        # Matrix((Col1, Col2, Col3)) where Cols are Right, Forward, Up (usually X, Y, Z)
        target_rot = Matrix((target_right, forward, up)).transposed().to_4x4()

        # 3. Apply to Object
        # We respect the current location, but OVERWRITE rotational component.
        loc = ruler.matrix_world.translation.copy()
        scale = ruler.scale.copy()  # Preserve scale just in case

        mat_loc = Matrix.Translation(loc)

        # Scale Matrix? Object scale is usually separate if composed.
        # Construct new world matrix: Loc * Rot
        # (ignoring scale in matrix construction, applying to obj.scale property if distinct, but matrix_world includes scale)
        # Safer to build Loc * Rot * Scale

        mat_scale = Matrix.Identity(4)
        mat_scale[0][0] = scale.x
        mat_scale[1][1] = scale.y
        mat_scale[2][2] = scale.z

        new_matrix = mat_loc @ target_rot @ mat_scale

        # Store the OLD p1/p2 before rotation
        old_p1 = Vector(ruler.get("SMILE_P1", (0, 0, 0)))
        old_p2 = Vector(ruler.get("SMILE_P2", (0, 0, 0)))

        # Apply rotation to ruler
        ruler.matrix_world = new_matrix

        # Transform p1/p2 by the same rotation (they need to rotate with the ruler)
        # Calculate rotation delta: new_rot @ old_rot_inverse
        # But since we're doing absolute rotation, we just apply target_rot to the points
        # relative to the ruler's center
        ruler_center = (old_p1 + old_p2) * 0.5
        new_p1 = target_rot.to_3x3() @ (old_p1 - ruler_center) + ruler_center
        new_p2 = target_rot.to_3x3() @ (old_p2 - ruler_center) + ruler_center

        # Update stored p1/p2 with rotated positions
        ruler["SMILE_P1"] = new_p1
        ruler["SMILE_P2"] = new_p2
        ruler["SMILE_P1_BASE"] = new_p1
        ruler["SMILE_P2_BASE"] = new_p2

        self.report({"INFO"}, "Ruler snapped to pupil line (Absolute).")
        update_golden_ruler(context.scene.smile_v2, context)
        return {"FINISHED"}


# ============================================================
# THE GIMBAL (Custom Tooth Control)
# ============================================================


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
            alpha=float(p.pnp_bg_alpha),
            distance_mm=float(p.pnp_plane_distance_mm),
        )
        if not plane:
            self.report({"ERROR"}, "Photo plane unavailable.")
            return {"CANCELLED"}

        plane.rotation_euler.z = math.radians(float(p.sf_picture_rotation_deg))
        x_ext = max(1e-6, abs(float(plane.scale.x)))
        y_ext = max(1e-6, abs(float(plane.scale.y)))

        def _line_local(name, p0_local, p1_local, rgba=(1, 1, 1, 1), hide=False):
            p0w = plane.matrix_world @ Vector(p0_local)
            p1w = plane.matrix_world @ Vector(p1_local)
            obj = _get_or_create_polyline_curve(name, [p0w, p1w], COL_PREVIEW)
            obj.parent = plane
            obj.matrix_parent_inverse = plane.matrix_world.inverted()
            obj.color = rgba
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
            obj.color = rgba
            obj.hide_viewport = bool(hide)
            obj.hide_render = bool(hide)
            return obj

        thirds = bool(p.sf_facial_thirds)
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

        flow_y = max(-y_ext, min(y_ext, float(p.sf_facial_flow_offset_mm) / 1000.0))
        _line_local(
            "SMILE_FRAME2D_FLOW",
            (-x_ext, flow_y, 0.0),
            (x_ext, flow_y, 0.0),
            (0.2, 1.0, 0.8, 1.0),
            hide=False,
        )

        x_buccal_r = max(0.0, min(x_ext, x_ext * float(p.sf_buccal_corridor_right)))
        x_buccal_l = max(-x_ext, min(0.0, -x_ext * float(p.sf_buccal_corridor_left)))
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

        # Bind H/W controls to explicit proportion guides (left/right rectangles).
        # Ratios are percentages (70-90%), interpreted as Height / Width.
        ratio_r = max(0.50, min(1.20, float(p.sf_ratio_hw_right) / 100.0))
        ratio_l = max(0.50, min(1.20, float(p.sf_ratio_hw_left) / 100.0))
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

        if bool(p.sf_symmetry_mode) and not bool(p.symmetry_enabled):
            try:
                setup_symmetry_constraints(context)
                p.symmetry_enabled = True
            except Exception:
                pass
        elif (not bool(p.sf_symmetry_mode)) and bool(p.symmetry_enabled):
            try:
                remove_symmetry_constraints(context)
                p.symmetry_enabled = False
            except Exception:
                pass

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
        ideal_scale = 0.6 + 0.8 * float(p.sf_curve_accuracy)
        ideal_delta = base_delta * ideal_scale

        ratio_r = max(0.70, min(0.90, float(p.sf_ratio_hw_right)))
        ratio_l = max(0.70, min(0.90, float(p.sf_ratio_hw_left)))
        corr_r = max(0.0, min(1.0, float(p.sf_buccal_corridor_right)))
        corr_l = max(0.0, min(1.0, float(p.sf_buccal_corridor_left)))
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
        obj_patient.color = (0.9, 0.2, 0.2, 1.0)
        obj_ideal.color = (0.2, 0.9, 0.2, 1.0)
        obj_patient.show_in_front = True
        obj_ideal.show_in_front = True
        obj_ideal["SMILE_FRAME3D_HW_R"] = float(ratio_r)
        obj_ideal["SMILE_FRAME3D_HW_L"] = float(ratio_l)
        obj_ideal["SMILE_FRAME3D_BCORR_R"] = float(corr_r)
        obj_ideal["SMILE_FRAME3D_BCORR_L"] = float(corr_l)
        obj_ideal["SMILE_FRAME3D_CURVE_SOURCE"] = str(source_mode)

        grid_name = "SMILE_FRAME3D_GRID"
        grid_obj = bpy.data.objects.get(grid_name)
        if bool(p.sf_grid_enabled):
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

        mode = str(p.sf_occlusal_curve_mode)
        superimpose = bool(p.sf_superimpose)
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

        h_gain = max(0.0, min(1.0, float(p.sf_apply3d_height_strength)))
        xy_gain = max(0.0, min(1.0, float(p.sf_apply3d_xy_strength)))
        use_rot = bool(getattr(p, "sf_apply3d_rotate_enabled", True))
        rot_gain = max(
            0.0, min(1.0, float(getattr(p, "sf_apply3d_rotate_strength", 0.4)))
        )
        max_rot = math.radians(
            max(0.1, float(getattr(p, "sf_apply3d_max_rotate_deg", 4.0)))
        )
        preview_only = bool(getattr(p, "sf_apply3d_preview_only", False))
        max_move = max(0.0001, float(p.sf_apply3d_max_move_mm) / 1000.0)

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
                    lobj.color = (1.0, 0.6, 0.1, 1.0)
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
                    tobj.color = (0.2, 1.0, 0.9, 1.0)
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


# === UI DRAW FUNCTION ===
def draw_mockup_tab(context, layout, props):
    """Draw the MOCKUP tab UI."""
    # Golden Ruler section
    box = layout.box()
    box.label(text="Golden Ruler", icon="CURVE")
    row = box.row(align=True)
    row.operator("smile.golden_ruler", text="Draw Ruler", icon="COPYDOWN")
    row.operator("smile.align_ruler_to_pupils", text="Align to Pupils", icon="SNAP_ON")

    # Golden Set section
    box = layout.box()
    box.label(text="Golden Set", icon="OUTLINER_OB_MESH")
    row = box.row(align=True)
    row.operator("smile.import_golden_set", text="Import Set", icon="IMPORT")
    row.operator("smile.delete_golden_set", text="Remove Set", icon="TRASH")

    # Tooth Placement section
    box = layout.box()
    box.label(text="Tooth Placement", icon="OUTLINER_OB_MESH")
    row = box.row(align=True)
    row.operator("smile.place_tooth_seed_on_curve", text="Place Seed", icon="PLUS")
    row.operator("smile.measure_dimension", text="Measure", icon="ARROW_LEFTRIGHT")
    row = box.row(align=True)
    row.operator(
        "smile.import_selected_teeth", text="Import Selected", icon="CHECKMARK"
    )
    row.operator("smile.smart_batch_import", text="Batch Import", icon="IMPORT")

    # Lip Line section
    box = layout.box()
    box.label(text="Lip Line & Smile Arc", icon="CURVE_DATA")
    row = box.row(align=True)
    row.operator("smile.draw_lip_line", text="Draw Lip", icon="GREASEPENCIL")
    row.operator("smile.update_lip_curve", text="Update", icon="FILE_REFRESH")
    row = box.row(align=True)
    row.operator("smile.clear_lip_markers", text="Clear Markers", icon="CANCEL")
    row.operator("smile.generate_smile_arc", text="Smile Arc", icon="MESH_DATA")

    # Chain Move section
    box = layout.box()
    box.label(text="Chain Move", icon="CON_TRANSLIKE")
    row = box.row(align=True)
    row.operator("smile.chain_move", text="Chain Move", icon="CON_TRANSLIKE")
    row = box.row(align=True)
    row.operator("smile.lock_alignment", text="Lock", icon="LOCKED")
    row.operator("smile.unlock_alignment", text="Unlock", icon="UNLOCKED")

    # Sculpt section
    box = layout.box()
    box.label(text="Sculpt Tools", icon="SCULPTMODE_HLT")
    row = box.row(align=True)
    row.operator(
        "smile.sculpt_session_start", text="Start Sculpt", icon="SCULPTMODE_HLT"
    )
    row.operator("smile.add_multires_sculpt", text="MultiRes", icon="MOD_MULTIRES")
    row = box.row(align=True)
    row.operator("smile.eraser_tool", text="Eraser", icon="CANCEL")

    # Frame 2D/3D section
    box = layout.box()
    box.label(text="Frame 2D/3D", icon="VIEW_ORTHO")
    row = box.row(align=True)
    row.operator("smile.frame2d_apply", text="Apply 2D", icon="IMAGE")
    row.operator("smile.frame3d_apply", text="Apply 3D", icon="MESH_CUBE")
    row = box.row(align=True)
    row.operator(
        "smile.frame3d_apply_to_teeth", text="Apply to Teeth", icon="OUTLINER_OB_MESH"
    )
    row.operator("smile.frame3d_clear_preview", text="Clear Preview", icon="CANCEL")
    row = box.row(align=True)
    row.operator("smile.frame3d_export_summary", text="Export Summary", icon="EXPORT")
    row.operator("smile.frame3d_reset_teeth", text="Reset Teeth", icon="LOOP_BACK")

    # Crown Shape Edit section
    box = layout.box()
    box.label(text="Crown Shape Edit", icon="MOD_SOLIDIFY")
    row = box.row(align=True)
    row.operator("smile.crown_shape_edit_start", text="Start Edit", icon="EDITMODE_HLT")
    row.operator("smile.crown_shape_edit_stop", text="Stop Edit", icon="CHECKMARK")
    row = box.row(align=True)
    row.operator(
        "smile.crown_shape_edit_set_direction",
        text="Set Direction",
        icon="ARROW_LEFTRIGHT",
    )
    row.operator("smile.crown_shape_edit_set_mode", text="Set Mode", icon="MENU_PANEL")


# === REGISTRATION ===
CLASSES = [
    SMILE_OT_import_selected_teeth,
    SMILE_OT_verify_golden_orientation,
    SMILE_OT_import_golden_set,
    SMILE_OT_delete_golden_set,
    SMILE_OT_golden_ruler,
    SMILE_OT_place_tooth_seed_on_curve,
    SMILE_OT_measure_dimension,
    SMILE_OT_sculpt_session_start,
    SMILE_OT_add_multires_sculpt,
    SMILE_OT_eraser_tool,
    SMILE_OT_draw_lip_line,
    SMILE_OT_update_lip_curve,
    SMILE_OT_clear_lip_markers,
    SMILE_OT_generate_smile_arc,
    SMILE_OT_chain_move,
    SMILE_OT_lock_alignment,
    SMILE_OT_unlock_alignment,
    SMILE_OT_pnp_capture_2d_landmark,
    SMILE_OT_import_tooth_for_mockup,
    SMILE_OT_smart_batch_import,
    SMILE_OT_snap_mockup_to_arch,
    SMILE_OT_delete_mockup_tooth,
    SMILE_OT_align_ruler_to_pupils,
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
