"""BlenderSmile Properties Module - All addon properties"""

import bpy
from bpy.props import *


COL_LM = "SmileLandmarks"
DOMAIN_FACE = "FACE"
DOMAIN_MAX = "MAX"
DOMAIN_MAN = "MAN"
DOMAIN_PHOTO = "PHOTO"


def _sync_workflow_progress(props):
    """Sync step completion flags based on workflow state transitions."""
    state = props.workflow_state

    step_map = {
        "SETUP": ["1"],
        "ANALYSIS": ["2"],
        "MOCKUP": ["3"],
        "PRODUCTION": ["4"],
        "NO_PREP": ["5"],
        "VENEER_IMPORT": ["6"],
        "GUIDED": ["1"],
    }

    target_steps = step_map.get(state, ["1"])
    for i in range(1, 7):
        step_attr = f"step{i}_done"
        if hasattr(props, step_attr):
            setattr(props, step_attr, str(i) in target_steps)


def _apply_workflow_collection_visibility(scene, workflow_state, context=None):
    """Optionally show/hide core collections based on workflow tab."""
    pass


def update_surface_alpha(self, context):
    """Update lip surface transparency."""
    plane = bpy.data.objects.get("SMILE_Lip_Surface")
    if plane and plane.data.materials:
        mat = plane.data.materials[0]
        if mat and mat.use_nodes:
            nodes = mat.node_tree.nodes
            for node in nodes:
                if node.type == "BSDF_PRINCIPLED":
                    node.inputs["Alpha"].default_value = self.surface_opacity


def update_golden_ruler(self, context=None):
    """Update golden ruler geometry when properties change."""
    ruler_obj = bpy.data.objects.get("SMILE_Golden_Ruler")
    if not ruler_obj:
        return

    p1 = Vector(ruler_obj.get("SMILE_P1", (0, 0, 0)))
    p2 = Vector(ruler_obj.get("SMILE_P2", (0, 0, 0)))

    if p1.length < 0.001 or p2.length < 0.001:
        return

    direction = p2 - p1
    length = direction.length
    midpoint = (p1 + p2) * 0.5

    depth = self.golden_arch_depth
    tick_vec = Vector(ruler_obj.get("SMILE_TICK_VEC", (0, 0, 1)))

    if ruler_obj.type == "CURVE" and ruler_obj.data.splines:
        spline = ruler_obj.data.splines[0]
        steps = len(spline.bezier_points)

        forward_n = direction.cross(tick_vec).normalized()
        ray_dir = -forward_n
        ray_start_off = forward_n * 20.0

        try:
            if context and hasattr(context, "scene") and context.scene:
                deps = context.evaluated_depsgraph_get()

                for i in range(steps):
                    t = i / max(steps - 1, 1)

                    base_pt = p1.lerp(p2, t)

                    offset_vec = tick_vec * depth * (1 - abs(t - 0.5) * 2)
                    pt_shifted = base_pt + offset_vec

                    ray_origin = pt_shifted + ray_start_off
                    hit, loc, _, _, _, _ = context.scene.ray_cast(
                        deps, ray_origin, ray_dir
                    )

                    if i < len(spline.bezier_points):
                        if hit:
                            spline.bezier_points[i].co = loc
                        else:
                            spline.bezier_points[i].co = pt_shifted
        except (AttributeError, RuntimeError):
            pass


def update_photo_scale(self, context):
    """Update photo plane scale when percentage changes."""
    if not self.plane_name:
        return

    plane = bpy.data.objects.get(self.plane_name)
    if not plane:
        return

    w = max(int(self.width), 1)
    h = max(int(self.height), 1)
    aspect = w / h

    scale_factor = self.photo_scale_percent / 100.0
    plane.scale = (aspect * scale_factor, 1.0 * scale_factor, 1.0)


class SmileLibraryItem(bpy.types.PropertyGroup):
    name: StringProperty()
    tooth_id: IntProperty()
    selected: BoolProperty(default=True)
    filepath: StringProperty()


class SMILE_UL_asset_list(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.prop(item, "selected", text="")
            layout.label(text=f"#{item.tooth_id} : {item.name}")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=f"#{item.tooth_id}")


class SmileImportedMDCItem(bpy.types.PropertyGroup):
    tooth_id: IntProperty(name="Tooth ID", default=0)
    obj_name: StringProperty(name="Object Name", default="")
    mdc_marked: BoolProperty(name="MDC Marked", default=False)


class SMILE_UL_imported_mdc_list(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(
                text="",
                icon=("CHECKBOX_HLT" if bool(item.mdc_marked) else "CHECKBOX_DEHLT"),
            )
            row.label(text=f"#{int(item.tooth_id)} : {str(item.obj_name)}")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(
                text=f"#{int(item.tooth_id)}",
                icon=("CHECKBOX_HLT" if bool(item.mdc_marked) else "CHECKBOX_DEHLT"),
            )


class SmilePhotoLandmark2D(bpy.types.PropertyGroup):
    idx: IntProperty(name="Index", default=1, min=1, max=999)
    u: FloatProperty(name="U", default=0.5, min=0.0, max=1.0, subtype="FACTOR")
    v: FloatProperty(name="V", default=0.5, min=0.0, max=1.0, subtype="FACTOR")


class SmilePhotoSlot(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Photo")
    image_path: StringProperty(name="Image Path", subtype="FILE_PATH", default="")
    image_name: StringProperty(name="Image Name", default="")
    camera_name: StringProperty(name="Camera", default="")
    plane_name: StringProperty(name="Plane", default="")
    width: IntProperty(name="Width", default=0, min=0)
    height: IntProperty(name="Height", default=0, min=0)
    landmarks: CollectionProperty(type=SmilePhotoLandmark2D)

    photo_scale_percent: FloatProperty(
        name="Photo Size",
        description="Photo plane size as percentage of camera view",
        default=100.0,
        min=10.0,
        max=100.0,
        subtype="PERCENTAGE",
        update=update_photo_scale,
    )


class SMILE_UL_photo_slots(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        slot = item
        ic = "CAMERA_DATA" if slot.camera_name else "IMAGE_DATA"
        row = layout.row(align=True)
        row.label(text=slot.name, icon=ic)
        if slot.image_name:
            row.label(text=slot.image_name, icon="IMAGE_DATA")


class SmileAddonStateV2(bpy.types.PropertyGroup):
    ui_cad_step1_open: BoolProperty(name="Step 1 Tools", default=True)
    ui_cad_step2_open: BoolProperty(name="Step 2 Tools", default=False)
    ui_cad_step3_open: BoolProperty(name="Step 3 Tools", default=False)
    ui_cad_step4_open: BoolProperty(name="Step 4 Tools", default=False)
    ui_guided_sec_setup: BoolProperty(name="Tab7 Setup", default=True)

    align_pt_1_mid: StringProperty(name="Align Midline", default="")
    align_pt_2_lm: StringProperty(name="Align Left Molar", default="")
    align_pt_3_rm: StringProperty(name="Align Right Molar", default="")

    def update_photo_opacity(self, context):
        try:
            if not context or not hasattr(context, "scene") or context.scene is None:
                return
        except (AttributeError, RuntimeError):
            return

        plane = bpy.data.objects.get("Photo_Mockup_Plane")
        if plane and plane.data.materials:
            mat = plane.data.materials[0]
            if mat and mat.use_nodes:
                nodes = mat.node_tree.nodes
                mix = nodes.get("Photo_Mix_Alpha")
                if mix:
                    mix.inputs[0].default_value = 1.0 - self.photo_opacity

    photo_opacity: FloatProperty(
        name="Photo Opacity", default=0.5, min=0.0, max=1.0, update=update_photo_opacity
    )

    face_target: StringProperty(name="FACE target", default="")
    max_target: StringProperty(name="MAX target", default="")
    man_target: StringProperty(name="MAN target", default="")
    photo_target: StringProperty(name="PHOTO target", default="")

    library_assets: CollectionProperty(type=SmileLibraryItem)
    active_asset_index: IntProperty()
    imported_mdc_items: CollectionProperty(type=SmileImportedMDCItem)
    imported_mdc_active_index: IntProperty(default=0)

    def update_marker_size(self, context):
        col = bpy.data.collections.get(COL_LM)
        if col:
            s = self.marker_size
            for obj in col.objects:
                obj.scale = (s, s, s)

    marker_size: FloatProperty(
        name="Landmark Size",
        default=0.001,
        min=0.0001,
        max=1.0,
        update=update_marker_size,
    )
    snap_to_vertex: BoolProperty(name="Snap to nearest vertex", default=False)
    lm_sticky_lock: BoolProperty(name="Sticky Lock to surface", default=True)
    lm_prevent_overwrite: BoolProperty(name="Prevent overwrite", default=True)

    pair_domain_a: EnumProperty(
        name="Pair A",
        items=[
            (DOMAIN_FACE, "FACE", ""),
            (DOMAIN_MAX, "MAX", ""),
            (DOMAIN_MAN, "MAN", ""),
            (DOMAIN_PHOTO, "PHOTO", ""),
        ],
        default=DOMAIN_FACE,
    )
    pair_domain_b: EnumProperty(
        name="Pair B",
        items=[
            (DOMAIN_FACE, "FACE", ""),
            (DOMAIN_MAX, "MAX", ""),
            (DOMAIN_MAN, "MAN", ""),
            (DOMAIN_PHOTO, "PHOTO", ""),
        ],
        default=DOMAIN_MAX,
    )
    pair_start_with_b: BoolProperty(name="Start with B", default=False)
    pair_workflow_mode: EnumProperty(
        name="Mode",
        items=[
            ("ALTERNATE", "Alternate (A->B)", "Click A then B for each point"),
            (
                "SEQUENTIAL",
                "Sequential (All A -> All B)",
                "Finish one domain then the other",
            ),
        ],
        default="ALTERNATE",
    )

    import_mask: BoolVectorProperty(name="Teeth", size=32, default=[False] * 32)

    segmentation_threshold: FloatProperty(
        name="Curvature Sens.",
        default=0.02,
        min=0.001,
        max=0.5,
        precision=3,
        description="Higher = Detects only sharp crevices. Lower = Detects gentle slopes.",
    )
    seed_marker_size: FloatProperty(name="Seed Size", default=0.1, min=0.01, max=5.0)
    segmentation_hide_original_after_extract: BoolProperty(
        name="Hide Original After Extract",
        default=False,
        description="After successful segment extraction, hide the original monolithic scan",
    )

    lm_index_mode: EnumProperty(
        name="Indexing",
        items=[("CONTINUE", "Continue", ""), ("FILL_MISSING", "Fill Missing", "")],
        default="FILL_MISSING",
    )
    lm_lock_index: BoolProperty(name="Lock Index", default=False)
    lm_index_override: IntProperty(name="Index Override", default=1, min=1, max=999)
    lm_lock_stay: BoolProperty(name="Stay on locked index", default=True)

    align_source_domain: EnumProperty(
        name="Source",
        items=[
            (DOMAIN_FACE, "FACE", ""),
            (DOMAIN_MAX, "MAX", ""),
            (DOMAIN_MAN, "MAN", ""),
            (DOMAIN_PHOTO, "PHOTO", ""),
        ],
        default=DOMAIN_FACE,
    )
    align_target_domain: EnumProperty(
        name="Target",
        items=[
            (DOMAIN_FACE, "FACE", ""),
            (DOMAIN_MAX, "MAX", ""),
            (DOMAIN_MAN, "MAN", ""),
            (DOMAIN_PHOTO, "PHOTO", ""),
        ],
        default=DOMAIN_MAX,
    )
    align_allow_scale: BoolProperty(
        name="Allow Scaling",
        default=False,
        description="Allow scaling source to match target size",
    )
    last_align_count: IntProperty(name="Matched", default=0)
    last_align_rms: FloatProperty(name="RMS", default=0.0, precision=6)
    last_align_max: FloatProperty(name="Max", default=0.0, precision=6)

    def update_workflow_state(self, context):
        """Optionally synchronize collection visibility to the current workflow tab."""
        try:
            if not context or not hasattr(context, "scene") or context.scene is None:
                return
        except (AttributeError, RuntimeError):
            return

        _sync_workflow_progress(self)
        if not bool(getattr(self, "auto_manage_collection_visibility", False)):
            return
        _apply_workflow_collection_visibility(
            context.scene, self.workflow_state, context=context
        )

    workflow_state: EnumProperty(
        name="Workflow",
        items=[
            ("SETUP", "1. Setup", "Import, Alignment, and Orientation"),
            ("ANALYSIS", "2. Analysis", "Facial Analysis and Guides"),
            ("MOCKUP", "3. Mockup", "Smile Design and Library"),
            ("PRODUCTION", "4. Production", "Models, Dies, and Export"),
            ("NO_PREP", "5. No-Prep", "No-Prep Veneer Design (2D Photo-Based)"),
            ("VENEER_IMPORT", "6. Veneer Lab", "Import Tooth + Boolean Veneer"),
            ("GUIDED", "7. Guided", "Step-by-Step Crown/Veneer Generation"),
        ],
        default="SETUP",
        update=update_workflow_state,
    )
    auto_manage_collection_visibility: BoolProperty(
        name="Auto Collection Visibility",
        default=True,
        description="When enabled, tab switches will hide/show core collections automatically",
    )

    design_step: EnumProperty(
        name="Guided Step",
        items=[
            ("1", "Step 1", "Calibration and setup"),
            ("2", "Step 2", "2D smile frame"),
            ("3", "Step 3", "3D smile frame"),
            ("4", "Step 4", "Design and fabrication setup"),
            ("5", "Step 5", "Validation and analysis"),
            ("6", "Step 6", "Export and delivery"),
        ],
        default="1",
    )
    enforce_step_lock: BoolProperty(
        name="Enforce Guided Lock",
        default=False,
        description="When enabled, key operators require minimum guided step",
    )
    step1_done: BoolProperty(name="Step 1 Done", default=False)
    step2_done: BoolProperty(name="Step 2 Done", default=False)
    step3_done: BoolProperty(name="Step 3 Done", default=False)
    step4_done: BoolProperty(name="Step 4 Done", default=False)
    step5_done: BoolProperty(name="Step 5 Done", default=False)
    step6_done: BoolProperty(name="Step 6 Done", default=False)
    auto_install_python_dependencies: BoolProperty(
        name="Auto-Install Python Dependencies",
        default=False,
        description="Allow BlenderSmile to install missing OpenCV/Open3D into Blender Python",
    )
    show_legacy_blocked_workflow_sidecar: BoolProperty(
        name="Show Legacy Blocked Workflow Sidecar",
        default=False,
        description="Expose the legacy sidecar panel in BlenderSmile CAD",
    )

    active_library_index: IntProperty(name="Library Index", default=0)
    active_library_name: StringProperty(name="Active Set", default="None")

    tooth_gap_mm: FloatProperty(name="Tooth Gap (mm)", default=0.1, min=0.0, max=5.0)

    lib_import_scale: FloatProperty(
        name="Import Scale",
        default=1.0,
        min=0.001,
        max=1000.0,
        description="Global Scale Multiplier for Library Assets",
    )

    lib_use_manual_orient: BoolProperty(
        name="Use Manual Orientation",
        default=False,
        description="Override Auto-PCA with fixed axis mapping",
    )

    lib_forward_axis: EnumProperty(
        name="Source Forward",
        items=[
            ("POS_X", "+X", ""),
            ("POS_Y", "+Y", ""),
            ("POS_Z", "+Z", ""),
            ("NEG_X", "-X", ""),
            ("NEG_Y", "-Y", ""),
            ("NEG_Z", "-Z", ""),
        ],
        default="NEG_Y",
    )

    lib_up_axis: EnumProperty(
        name="Source Up",
        items=[
            ("POS_X", "+X", ""),
            ("POS_Y", "+Y", ""),
            ("POS_Z", "+Z", ""),
            ("NEG_X", "-X", ""),
            ("NEG_Y", "-Y", ""),
            ("NEG_Z", "-Z", ""),
        ],
        default="POS_Z",
    )

    lib_spawn_mode: EnumProperty(
        name="Spawn Location",
        items=[
            ("ARCH", "Arch Tracer", "Place on the designated Arch Curve"),
            ("CURSOR", "3D Cursor", "Place at 3D Cursor"),
            ("ORIGIN", "World Origin", "Place at (0,0,0)"),
        ],
        default="ARCH",
    )
    import_use_anchor_calibration: BoolProperty(
        name="Use Anchor Calibration",
        default=True,
        description="Apply saved manual anchor correction during Import & Place Selected",
    )
    import_calibration_tooth_id: IntProperty(
        name="Calibration Tooth #",
        default=8,
        min=1,
        max=32,
        description="Tooth ID used for 3-point scan/import matching",
    )

    use_target_dims: BoolProperty(
        name="Calibrate Dimensions",
        default=False,
        description="Scale imported tooth to match exact MM",
    )
    target_width_mm: FloatProperty(
        name="Target Width",
        default=8.5,
        min=1.0,
        max=20.0,
        description="Desired Mesiodistal Width (mm)",
    )
    target_height_mm: FloatProperty(
        name="Target Height",
        default=10.5,
        min=1.0,
        max=20.0,
        description="Desired Incisogingival Height (mm)",
    )
    lock_scale_ratio: BoolProperty(
        name="Lock Ratio",
        default=False,
        description="Apply Uniform Scale based on Width",
    )

    icp_enable: BoolProperty(name="Use ICP refine (Open3D)", default=True)
    icp_samples: IntProperty(name="ICP Samples", default=20000, min=1000, max=200000)
    icp_threshold: FloatProperty(
        name="ICP Threshold (scene units)", default=1.0, min=1e-6, max=1000.0
    )
    icp_normal_radius: FloatProperty(
        name="ICP Normal Radius (scene units)", default=2.0, min=0.0, max=1000.0
    )

    arch_marker_size: FloatProperty(
        name="Arch Marker Size", default=0.0025, min=0.001, max=50.0
    )
    arch_curve_type: EnumProperty(
        name="Curve Type",
        items=[("BEZIER", "Bezier", ""), ("POLY", "Poly", "")],
        default="BEZIER",
    )
    arch_resolution: IntProperty(name="Resolution", default=24, min=2, max=128)
    arch_smooth_strength: FloatProperty(
        name="Smooth Strength", default=0.35, min=0.0, max=1.0
    )

    reference_length_mm: FloatProperty(
        name="Ref. Length (mm)",
        default=10.5,
        min=1.0,
        max=20.0,
        description="Target height for Central Incisor",
    )

    golden_ruler_mode: EnumProperty(
        name="Ruler Ratio",
        items=[
            ("PERCENT", "Gauge 12-15-23", "Use 12%-15%-23% proportion"),
            ("CLASSIC", "1.618 : 1.0", "Use classic Golden Ratio"),
        ],
        default="PERCENT",
        update=update_golden_ruler,
    )

    golden_arch_depth: FloatProperty(
        name="Smile Depth (mm)",
        description="Depth of the Golden Ruler Smile Arc in Millimeters",
        default=0.0,
        min=-10.0,
        max=30.0,
        step=5,
        precision=2,
        update=update_golden_ruler,
    )

    golden_ruler_thickness: FloatProperty(
        name="Line Thickness (mm)",
        description="Thickness of the Golden Ruler line in millimeters",
        default=0.05,
        min=0.05,
        max=10.0,
        step=1,
        precision=2,
        update=update_golden_ruler,
    )

    use_existing_tooth_angulation: BoolProperty(
        name="Match Existing Teeth",
        description="Copy rotation/angulation from adjacent existing teeth during Golden Import",
        default=True,
    )

    golden_import_lateral_curve: EnumProperty(
        name="Lateral Curve",
        description="Curve to use for X/Y positioning in Golden Import",
        items=[
            ("AUTO", "Auto Priority", "ARCH_MAX_CURVE > Golden Arch > Ruler"),
            ("ARCH", "Manual Arch", "Use ARCH_MAX_CURVE only"),
            ("GOLDEN", "Golden Ruler", "Use Golden Ruler/Arch only"),
        ],
        default="AUTO",
    )

    golden_import_depth_curve: EnumProperty(
        name="Depth Curve",
        description="Curve to use for Z-height (smile depth) in Golden Import",
        items=[
            ("AUTO", "Auto Priority", "Smile Arch > Lip Line > Lateral"),
            ("SMILE", "Smile Depth", "Use SMILE_Golden_Arch only"),
            ("LIP", "Lip Line", "Use SMILE_Lip_Curve only"),
            ("LATERAL", "Same as Lateral", "No separate depth curve"),
        ],
        default="AUTO",
    )

    golden_auto_orient: BoolProperty(
        name="Auto-Detect Orientation",
        description="Automatically detect and correct facial/incisal orientation using geometry analysis",
        default=True,
    )

    golden_verify_orientation: BoolProperty(
        name="Verify Orientation (2-Click)",
        description="Manually verify orientation on first tooth",
        default=False,
    )

    golden_angulation_preset: EnumProperty(
        name="Angulation Preset",
        description="Apply preset angulation adjustments to imported teeth",
        items=[
            ("NONE", "None", "No angulation adjustment"),
            ("NATURAL", "Natural", "Slight lingual tilt (~2-3°)"),
            ("AGGRESSIVE", "Aggressive", "More visible from front (~5-7°)"),
            ("CONSERVATIVE", "Conservative", "Tucked in (~0-1°)"),
            ("CUSTOM", "Custom", "User-defined angle"),
        ],
        default="NATURAL",
    )

    golden_custom_angulation: FloatProperty(
        name="Custom Angle",
        description="Custom angulation angle in degrees",
        default=3.0,
        min=-15.0,
        max=15.0,
        unit="ROTATION",
    )

    golden_show_axis_preview: BoolProperty(
        name="Show Axis Preview",
        description="Display RGB axes on imported teeth for 3 seconds",
        default=True,
    )

    library_orientation_preset: EnumProperty(
        name="Library Orientation",
        description="Orientation convention of the current tooth library",
        items=[
            (
                "STANDARD",
                "Standard (Incisal -Z, Facial -Y)",
                "Standard dental orientation",
            ),
            (
                "INVERTED_Z",
                "Inverted Z (Incisal +Z)",
                "Library has incisal edges pointing up",
            ),
            (
                "INVERTED_Y",
                "Inverted Y (Facial +Y)",
                "Library has facial pointing backward",
            ),
            ("ROTATED_90X", "Rotated 90° X-axis", "Library rotated 90° around X"),
            ("ROTATED_90Y", "Rotated 90° Y-axis", "Library rotated 90° around Y"),
            (
                "ROTATED_180Y",
                "Rotated 180° Y-axis (Mirrored)",
                "Library mirrored left-right",
            ),
            ("CUSTOM", "Custom...", "Use custom rotation angles"),
        ],
        default="STANDARD",
    )

    library_custom_rotation_x: FloatProperty(
        name="Custom X Rotation",
        description="Custom rotation around X-axis in degrees",
        default=0.0,
        min=-180.0,
        max=180.0,
        unit="ROTATION",
    )

    library_custom_rotation_y: FloatProperty(
        name="Custom Y Rotation",
        description="Custom rotation around Y-axis in degrees",
        default=0.0,
        min=-180.0,
        max=180.0,
        unit="ROTATION",
    )

    library_custom_rotation_z: FloatProperty(
        name="Custom Z Rotation",
        description="Custom rotation around Z-axis in degrees",
        default=0.0,
        min=-180.0,
        max=180.0,
        unit="ROTATION",
    )

    surface_opacity: FloatProperty(
        name="Surface Opacity",
        default=0.5,
        min=0.0,
        max=1.0,
        update=update_surface_alpha,
        description="Opacity of the lip surface and tangent plane",
    )

    tooth_library_folder: StringProperty(
        name="Tooth Library",
        subtype="DIR_PATH",
        description="Path to the folder containing tooth assets",
    )

    veneer_set_name_hint: StringProperty(
        name="Set Name",
        default="",
        description="Optional label used when importing a multi-unit veneer set",
    )
    veneer_set_auto_align: BoolProperty(
        name="Auto-Align Set on Import",
        default=True,
        description="Automatically align each imported tooth to matching seed/ROI",
    )
    veneer_set_apply_pca: BoolProperty(
        name="Auto-Orient Set (PCA)",
        default=True,
        description="Normalize each imported tooth orientation before alignment",
    )
    align_set_mdc_first: BoolProperty(
        name="MDC-First Align",
        default=True,
        description="For set alignment, use MDC/arch-reference alignment first",
    )
    align_set_fallback_seed_roi: BoolProperty(
        name="Fallback Seed/ROI",
        default=True,
        description="If MDC is unavailable/fails, fallback to seed/ROI auto-align",
    )

    ui_tab6_sec_library: BoolProperty(name="Tab6 Library", default=True)
    ui_tab6_sec_mdc: BoolProperty(name="Tab6 MDC", default=True)
    ui_tab6_sec_autodie: BoolProperty(name="Tab6 AutoDie", default=False)
    ui_tab6_sec_shell: BoolProperty(name="Tab6 Shell", default=False)
    ui_tab6_sec_crown_edit: BoolProperty(name="Tab6 Crown Edit", default=True)
    ui_tab6_sec_cadwizard: BoolProperty(name="Tab6 CAD Wizard", default=True)
    ui_tab6_sec_blockffd: BoolProperty(name="Tab6 BlockFFD", default=False)
    ui_tab6_sec_mirror: BoolProperty(name="Tab6 Mirror", default=False)
    ui_tab6_sec_interprox: BoolProperty(name="Tab6 Interprox", default=False)
    ui_tab6_sec_generate: BoolProperty(name="Tab6 Generate", default=False)

    ui_tab_setup_main: BoolProperty(name="Tab Setup Main", default=True)
    ui_tab_analysis_main: BoolProperty(name="Tab Analysis Main", default=True)
    ui_tab_mockup_main: BoolProperty(name="Tab Mockup Main", default=True)
    ui_tab_production_main: BoolProperty(name="Tab Production Main", default=True)
    ui_tab_noprep_main: BoolProperty(name="Tab NoPrep Main", default=True)
    ui_review_sec_workspace: BoolProperty(name="Review Workspace", default=True)

    ui_setup_sec_import: BoolProperty(name="Setup Import", default=True)
    ui_setup_sec_pnp: BoolProperty(name="Setup Photo PnP", default=True)
    ui_setup_sec_tools: BoolProperty(name="Setup Tools", default=True)
    ui_setup_sec_targets: BoolProperty(name="Setup Targets", default=True)
    ui_setup_sec_deps: BoolProperty(name="Setup Dependencies", default=False)

    ui_analysis_sec_core: BoolProperty(name="Analysis Core", default=True)
    ui_analysis_sec_smilefy: BoolProperty(name="Analysis Smilefy", default=False)

    ui_mockup_sec_library: BoolProperty(name="Mockup Library", default=True)
    ui_mockup_sec_arch_seg: BoolProperty(name="Mockup ArchSeg", default=True)
    ui_mockup_sec_tools_adv: BoolProperty(name="Mockup ToolsAdv", default=False)

    ui_prod_sec_margin: BoolProperty(name="Prod Margin", default=True)
    ui_prod_sec_interprox: BoolProperty(name="Prod Interprox", default=False)
    ui_prod_sec_die: BoolProperty(name="Prod Die", default=True)
    ui_prod_sec_multiunit: BoolProperty(name="Prod Multiunit", default=False)
    ui_prod_sec_utils: BoolProperty(name="Prod Utils", default=False)
    ui_prod_sec_fabrication: BoolProperty(name="Prod Fabrication", default=False)
    ui_prod_sec_validation: BoolProperty(name="Prod Validation", default=False)
    ui_prod_margin_sec_autodie: BoolProperty(name="Prod Margin AutoDie", default=False)
    ui_prod_margin_sec_smooth: BoolProperty(name="Prod Margin Smooth", default=False)
    ui_prod_margin_sec_precision: BoolProperty(
        name="Prod Margin Precision", default=False
    )
    ui_prod_margin_sec_snake: BoolProperty(name="Prod Margin Snake", default=False)

    ui_noprep_sec_1_import: BoolProperty(name="NoPrep Import", default=True)
    ui_noprep_sec_2_calib: BoolProperty(name="NoPrep Calib", default=True)
    ui_noprep_sec_3_position: BoolProperty(name="NoPrep Position", default=False)
    ui_noprep_sec_4_generate: BoolProperty(name="NoPrep Generate", default=True)
    ui_noprep_sec_5_export: BoolProperty(name="NoPrep Export", default=False)

    review_workspace_preset: EnumProperty(
        name="Review Preset",
        items=[
            ("ALL", "All Layers", "Show all review layers"),
            ("ALIGN", "Alignment", "Focus on scan and alignment context"),
            ("DESIGN", "Design", "Focus on design layers"),
            ("VALIDATE", "Validate", "Focus on validation layers"),
            ("EXPORT", "Export", "Focus on export-ready layers"),
        ],
        default="VALIDATE",
    )
    review_note_text: StringProperty(
        name="Review Note",
        default="",
        description="Short local note to place in the 3D review scene",
    )
    review_section_plane_size_mm: FloatProperty(
        name="Section Plane Size",
        default=24.0,
        min=4.0,
        max=120.0,
        description="Displayed size of review section scaffold plane in mm",
    )
    review_section_style: EnumProperty(
        name="Section Style",
        items=[
            ("OUTLINE", "Outline", "High-contrast wireframe section guide"),
            ("CLINICAL", "Clinical", "Semi-transparent blue review plane"),
            ("PRESENT", "Present", "Soft presentation-style plane"),
        ],
        default="CLINICAL",
    )
    review_section_step_mm: FloatProperty(
        name="Section Step",
        default=0.5,
        min=0.1,
        max=10.0,
        description="Distance in mm to nudge the active review section plane",
    )

    def update_ruler_width(self, context):
        """Update ruler width by scaling P2 from P1"""
        ruler_obj = bpy.data.objects.get("SMILE_Golden_Ruler")
        if not ruler_obj or "SMILE_P1" not in ruler_obj or "SMILE_P2" not in ruler_obj:
            return

        if "SMILE_P1_BASE" in ruler_obj and "SMILE_P2_BASE" in ruler_obj:
            p1_base = Vector(ruler_obj["SMILE_P1_BASE"])
            p2_base = Vector(ruler_obj["SMILE_P2_BASE"])
        else:
            p1_base = Vector(ruler_obj["SMILE_P1"])
            p2_base = Vector(ruler_obj["SMILE_P2"])
            ruler_obj["SMILE_P1_BASE"] = p1_base
            ruler_obj["SMILE_P2_BASE"] = p2_base

        direction = p2_base - p1_base
        base_length = direction.length
        midpoint = (p1_base + p2_base) * 0.5

        new_half_length = (base_length * self.golden_ruler_width_scale) * 0.5
        dir_norm = direction.normalized()

        p1_new = midpoint - dir_norm * new_half_length
        p2_new = midpoint + dir_norm * new_half_length

        ruler_obj["SMILE_P1"] = p1_new
        ruler_obj["SMILE_P2"] = p2_new

        p1 = p1_new
        tick_vec = Vector(ruler_obj.get("SMILE_TICK_VEC", (0, 0, 1)))
        offsets = list(ruler_obj.get("SMILE_OFFSETS", []))

        if not offsets:
            return

        if p1.length < 0.001 or p2_new.length < 0.001:
            return

        if ruler_obj.type == "CURVE" and ruler_obj.data.splines:
            spline = ruler_obj.data.splines[0]
            steps = len(spline.bezier_points)

            tick_vec = Vector(ruler_obj.get("SMILE_TICK_VEC", (0, 0, 1)))
            line_vec = p2_new - p1

            forward_n = line_vec.cross(tick_vec).normalized()
            ray_dir = -forward_n
            ray_start_off = forward_n * 20.0

            try:
                if context and hasattr(context, "scene") and context.scene:
                    deps = context.evaluated_depsgraph_get()

                    spline.bezier_points[0].co = p1
                    spline.bezier_points[steps - 1].co = p2_new

                    for i in range(1, steps - 1):
                        t = i / (steps - 1)
                        pt_linear = p1.lerp(p2_new, t)

                        ray_origin = pt_linear + ray_start_off
                        hit, loc, _, _, _, _ = context.scene.ray_cast(
                            deps, ray_origin, ray_dir
                        )

                        if hit:
                            spline.bezier_points[i].co = loc
                        else:
                            spline.bezier_points[i].co = pt_linear

                        spline.bezier_points[i].handle_left_type = "AUTO"
                        spline.bezier_points[i].handle_right_type = "AUTO"
            except (AttributeError, RuntimeError):
                pass

        try:
            update_golden_ruler(self, context)
        except (AttributeError, RuntimeError):
            pass

    def update_margin_line_thickness(self, context):
        """Apply margin line thickness to all visible margin curves."""
        th = max(0.001, float(getattr(self, "margin_line_thickness", 0.03)))
        for obj in bpy.data.objects:
            if obj.type == "CURVE" and obj.name.startswith("MARGIN_") and obj.data:
                obj.data.bevel_depth = th

    def update_blockffd_handle_size(self, context):
        """Live-resize existing Block FFD sphere handles when slider changes."""
        size_abs = float(
            max(0.001, min(5.0, getattr(self, "blockffd_handle_size", 0.05)))
        )
        gap = float(max(0.0, min(5.0, getattr(self, "blockffd_sphere_gap", 0.1))))
        changed = 0
        for obj in bpy.data.objects:
            try:
                if obj.type != "MESH" or not bool(
                    obj.get("SMILE_BLOCKFFD_HANDLE", False)
                ):
                    continue
                owner_name = str(obj.get("SMILE_BLOCKFFD_OWNER", "") or "").strip()
                owner = bpy.data.objects.get(owner_name) if owner_name else None
                s = float(size_abs)
                if owner and owner.type == "MESH":
                    divs = int(owner.get("SMILE_BLOCKFFD_DIVS", 3) or 3)
                    lat = None
                    if lat and lat.type == "LATTICE":
                        min_step = 0.1
                        s = min(s, max(0.001, float(min_step - gap)))
                obj.scale = (s, s, s)
                changed += 1
            except Exception:
                continue
        if changed and context:
            try:
                for win in context.window_manager.windows:
                    for area in win.screen.areas:
                        if area.type == "VIEW_3D":
                            area.tag_redraw()
            except Exception:
                pass

    def update_blockffd_pad(self, context):
        """Live-update lattice cage size from pad slider."""
        pad = float(max(0.05, min(2.5, getattr(self, "blockffd_size_pad", 0.1))))
        changed = 0
        for obj in bpy.data.objects:
            try:
                if obj.type != "MESH" or bool(obj.get("SMILE_BLOCKFFD_HANDLE", False)):
                    continue
                lat = None
                if not lat or lat.type != "LATTICE":
                    continue
                c_local = Vector((0, 0, 0))
                d_local = Vector((1, 1, 1))
                d_local = d_local * (1.0 + pad)
                M = obj.matrix_world.copy()
                T_local = Matrix.Translation(c_local)
                S_local = Matrix.Diagonal((d_local.x, d_local.y, d_local.z, 1.0))
                lat.matrix_world = M @ T_local @ S_local
                obj["SMILE_BLOCKFFD_PAD"] = float(pad)
                changed += 1
            except Exception:
                continue
        if changed:
            self.update_blockffd_handle_size(context)

    golden_ruler_width_scale: FloatProperty(
        name="Ruler Width Scale",
        description="Scale factor for tooth widths derived from Golden Ruler segments",
        default=1.0,
        min=0.5,
        max=2.0,
        step=5,
        precision=2,
        subtype="FACTOR",
        update=update_ruler_width,
    )

    golden_enable_embedding: BoolProperty(
        name="Enable Tooth Embedding",
        description="Position teeth with bucco-lingual embedding in underlying model",
        default=True,
    )

    golden_embedding_depth: FloatProperty(
        name="Embedding Depth",
        description="How much of tooth is embedded",
        default=0.5,
        min=0.0,
        max=1.0,
        step=5,
        precision=2,
    )

    tweak_width: FloatProperty(name="Width Scale", default=1.0, min=0.5, max=1.5)
    tweak_length: FloatProperty(name="Length Scale", default=1.0, min=0.5, max=1.7)
    tweak_cant: FloatProperty(name="Cant (deg)", default=0.0, min=-20.0, max=20.0)
    tweak_midline: FloatProperty(name="Midline (mm)", default=0.0, min=-5.0, max=5.0)

    target_tooth_id: IntProperty(
        name="Target Tooth #",
        default=8,
        min=1,
        max=32,
        description="Universal Tooth Number for the margin being drawn",
    )

    margin_marker_size: FloatProperty(
        name="Marker Size", default=0.006, min=0.001, max=5.0
    )
    margin_line_thickness: FloatProperty(
        name="Line Thickness",
        default=0.03,
        min=0.001,
        max=0.2,
        precision=3,
        description="Displayed thickness of the traced margin curve",
        update=update_margin_line_thickness,
    )
    margin_show_crosshair: BoolProperty(name="Show Crosshair", default=True)
    margin_min_spacing: FloatProperty(
        name="Min Point Spacing",
        default=0.5,
        min=0.1,
        max=5.0,
        description="Minimum distance between control points",
    )
    margin_drag_smooth_effect: FloatProperty(
        name="Drag Smooth Effect",
        default=0.35,
        min=0.0,
        max=1.0,
        precision=3,
        description="Smoothing strength used by Tab4 Drag Smooth trace finalization",
    )
    margin_magnet_strength: FloatProperty(
        name="Edge Magnet Strength",
        default=0.45,
        min=0.0,
        max=1.0,
        precision=3,
        description="Strength of soft-edge magnet snap during margin finalization",
    )
    margin_closing_smooth_window: IntProperty(
        name="Closing Smooth Window",
        default=8,
        min=2,
        max=20,
        description="Gaussian smooth half-window for the closing region",
    )
    margin_simplify_tolerance: FloatProperty(
        name="Curve Smoothness",
        default=0.15,
        min=0.01,
        max=1.0,
        description="Simplification tolerance (mm)",
    )
    margin_auto_smooth: BoolProperty(
        name="Auto-Smooth on Place",
        default=True,
        description="Automatically smooth placed points to reduce jaggedness",
    )
    margin_snake_iterations: IntProperty(
        name="Snake Iterations", default=20, min=1, max=100
    )
    margin_snake_alpha: FloatProperty(
        name="Attraction",
        default=0.5,
        min=0.0,
        max=1.0,
        description="How strongly the traced line is pulled toward likely margin edges",
    )
    margin_snake_beta: FloatProperty(
        name="Smoothing",
        default=0.5,
        min=0.0,
        max=1.0,
        description="How much the traced line softens small wiggles",
    )
    margin_viewport_contrast_assist: BoolProperty(
        name="Viewport Contrast Assist",
        default=True,
        description="Use viewport lighting contrast as a secondary magnetic cue",
    )
    margin_viewport_contrast_weight: FloatProperty(
        name="Contrast Weight",
        default=0.12,
        min=0.0,
        max=0.5,
        precision=3,
        description="Blend amount for viewport-contrast assist during magnetic drag tracing",
    )
    margin_solver_mode: EnumProperty(
        name="Trace Solver",
        items=[
            ("PRECISION", "Precision", "Edge-evidence driven precision click tracing"),
            ("LEGACY", "Legacy", "Use legacy click-trace behavior"),
        ],
        default="PRECISION",
    )
    margin_corridor_mm: FloatProperty(
        name="Corridor Width (mm)",
        default=1.2,
        min=0.2,
        max=5.0,
        precision=3,
        description="Local solve corridor around each anchor-to-anchor segment",
    )
    margin_turn_penalty: FloatProperty(
        name="Turn Penalty",
        default=0.25,
        min=0.0,
        max=2.0,
        precision=3,
        description="Higher values reduce zig-zag turns in solved margin path",
    )
    margin_evidence_gamma: FloatProperty(
        name="Evidence Gamma",
        default=1.8,
        min=0.5,
        max=6.0,
        precision=3,
        description="Exponent for edge-confidence weighting in segment solve",
    )
    margin_opt_iters: IntProperty(
        name="Loop Optimize Iters",
        default=12,
        min=0,
        max=128,
        description="Closed-loop optimization iterations for precision trace",
    )
    margin_anchor_weight: FloatProperty(
        name="Anchor Weight",
        default=0.35,
        min=0.0,
        max=1.0,
        precision=3,
        description="How strongly optimized loop follows user anchor clicks",
    )
    margin_show_confidence: BoolProperty(
        name="Show Confidence",
        default=True,
        description="Display confidence diagnostics for precision trace segments",
    )
    margin_precision_help_expanded: BoolProperty(
        name="Show Help",
        default=False,
        description="Show simple explanations for Precision Click Trace controls",
    )
    margin_precision_smooth: BoolProperty(
        name="Smooth Version",
        default=False,
        description="Apply additional constrained smoothing to precision click-trace path",
    )
    margin_precision_smooth_iters: IntProperty(
        name="Smooth Iters",
        default=2,
        min=1,
        max=30,
        description="Number of smoothing passes for precision smooth version",
    )
    margin_precision_smooth_strength: FloatProperty(
        name="Smooth Strength",
        default=0.28,
        min=0.0,
        max=1.0,
        precision=3,
        description="Smoothing blend strength for precision smooth version",
    )
    margin_precision_preserve_preview: BoolProperty(
        name="Preserve Traced Shape",
        default=True,
        description="Keep the final curve as close as possible to the magnetic traced path on Enter",
    )
    margin_precision_enforce_spacing: BoolProperty(
        name="Enforce Fixed Spacing",
        default=False,
        description="Resample finalized precision curve to fixed point spacing",
    )
    margin_precision_seam_blend: BoolProperty(
        name="Closure Seam Blend",
        default=False,
        description="Apply seam blending at loop closure to soften closure kink",
    )
    margin_confidence_warn_threshold: FloatProperty(
        name="Warn Threshold",
        default=0.45,
        min=0.0,
        max=1.0,
        precision=3,
        description="Confidence below this threshold is highlighted as risky",
    )
    margin_evidence_w_dihedral: FloatProperty(
        name="W Dihedral",
        default=0.65,
        min=0.0,
        max=1.0,
        precision=3,
        description="Weight for dihedral ridge evidence in precision solver",
    )
    margin_evidence_w_curvature: FloatProperty(
        name="W Curvature",
        default=0.25,
        min=0.0,
        max=1.0,
        precision=3,
        description="Weight for curvature evidence in precision solver",
    )
    margin_evidence_w_normal_var: FloatProperty(
        name="W Normal Var",
        default=0.07,
        min=0.0,
        max=1.0,
        precision=3,
        description="Weight for normal-variation evidence in precision solver",
    )
    margin_evidence_w_depth: FloatProperty(
        name="W Depth",
        default=0.03,
        min=0.0,
        max=1.0,
        precision=3,
        description="Weight for depth discontinuity evidence in precision solver",
    )
    margin_click_live_preview_quality: EnumProperty(
        name="Preview Quality",
        items=[
            ("FAST", "Fast", "Lower-latency preview while tracing"),
            ("HIGH", "High", "Higher-quality preview with more refinement"),
        ],
        default="FAST",
    )
    margin_point_spacing_mm: FloatProperty(
        name="Final Point Spacing (mm)",
        default=0.40,
        min=0.30,
        max=0.50,
        precision=3,
        description="Fixed arc-length spacing for finalized margin points",
    )
    margin_edit_marker_count: IntProperty(
        name="Edit Marker Count",
        default=96,
        min=16,
        max=400,
        description="Number of edit gizmo markers shown around the margin loop",
    )
    margin_trace_color: EnumProperty(
        name="Trace Line Color",
        items=[
            ("NEON_BLUE", "Neon Blue", "Bright blue tracing line"),
            ("NEON_YELLOW", "Neon Yellow", "Bright yellow tracing line"),
            ("NEON_PINK", "Neon Pink", "Bright pink tracing line"),
            ("NEON_CYAN", "Neon Cyan", "Bright cyan tracing line"),
            ("NEON_GREEN", "Neon Green", "Bright green tracing line"),
        ],
        default="NEON_BLUE",
        description="Neon color for margin tracing line visibility",
    )
    margin_trace_benchmark_log: BoolProperty(
        name="Trace Benchmark Log",
        default=False,
        description="Print drag-trace edge detection/snap performance statistics to console",
    )
    margin_trace_benchmark_interval: IntProperty(
        name="Benchmark Interval",
        default=60,
        min=10,
        max=500,
        description="Number of snap updates between benchmark log lines",
    )
    margin_trace_benchmark_export_json: BoolProperty(
        name="Export Benchmark JSON",
        default=False,
        description="Export drag-trace benchmark summaries as JSON on session end",
    )
    margin_trace_benchmark_export_dir: StringProperty(
        name="Benchmark Export Dir",
        subtype="DIR_PATH",
        default="//margin_bench",
        description="Directory for drag-trace benchmark JSON exports",
    )
    margin_native_curve_edit: BoolProperty(
        name="Native Curve Edit",
        default=True,
        description="Use Blender native curve point editing for margin adjustments",
    )
    margin_surface_lock_live: BoolProperty(
        name="Surface Lock (Live)",
        default=True,
        description="Enable face/project snapping during native curve edit",
    )
    margin_minimal_visual_style: BoolProperty(
        name="Minimal Visual Style",
        default=True,
        description="Use thin dark margin line and tiny unobtrusive point style",
    )
    margin_auto_create_die_on_close: BoolProperty(
        name="Auto-Create Die on Loop Close",
        default=False,
        description="When a margin loop is finalized, queue Create Die automatically",
    )
    margin_auto_create_die_tab6_deferred: BoolProperty(
        name="Deferred via Tab 6 Function",
        default=True,
        description="Run queued auto-die jobs through dedicated Tab 6 runner for modal stability",
    )

    rig_size_pad: FloatProperty(name="Rig Size Pad", default=1.15, min=1.0, max=1.6)
    blockffd_divisions: IntProperty(
        name="FFD Divisions",
        default=3,
        min=2,
        max=6,
        description="Lattice resolution per axis",
    )
    blockffd_size_pad: FloatProperty(
        name="FFD Size Pad",
        default=0.1,
        min=0.05,
        max=2.5,
        precision=3,
        description="Additive lattice cage padding ratio (0.1 = +10%)",
        update=update_blockffd_pad,
    )
    blockffd_handle_size: FloatProperty(
        name="Sphere Size",
        default=0.05,
        min=0.001,
        max=5.0,
        precision=3,
        description="Sphere diameter in scene units",
        update=update_blockffd_handle_size,
    )
    blockffd_sphere_gap: FloatProperty(
        name="Sphere Gap",
        default=0.1,
        min=0.0,
        max=5.0,
        precision=3,
        description="Minimum gap between neighboring sphere surfaces",
        update=update_blockffd_handle_size,
    )
    blockffd_surface_handles_only: BoolProperty(
        name="Surface Handles Only",
        default=True,
        description="Show only outer lattice markers for cleaner view",
    )
    blockffd_simple_mode: BoolProperty(
        name="Simple Mode (8 Corners)",
        default=False,
        description="Use only 8 corner handles for a minimal interface",
    )
    blockffd_hide_relationship_lines: BoolProperty(
        name="Hide Relationship Lines in FFD",
        default=True,
        description="Temporarily hide Blender relationship lines while editing Block FFD",
    )
    blockffd_restore_relationship_lines: BoolProperty(
        name="Restore Relationship Lines",
        default=True,
        description="Restore prior relationship-line visibility on Apply/Remove",
    )
    blockffd_cleanup_after_apply: BoolProperty(
        name="Cleanup Rig on Apply",
        default=True,
        description="Delete lattice/handles automatically after apply",
    )

    multires_view: IntProperty(name="View", default=1, min=0, max=6)
    multires_sculpt: IntProperty(name="Sculpt", default=2, min=0, max=6)
    multires_render: IntProperty(name="Render", default=2, min=0, max=6)

    cement_gap_slider: FloatProperty(
        name="Cement Gap",
        default=0.06,
        min=0.01,
        max=0.5,
        description="Internal offset for passive fit (mm)",
    )
    show_traditional_die: BoolProperty(
        name="Show Traditional Die",
        default=False,
        description="Toggle a traditional extruded die stump to visualize margin end",
    )

    no_prep_thickness: FloatProperty(
        name="Veneer Thickness",
        default=0.4,
        min=0.3,
        max=0.8,
        description="Ultra-thin veneer thickness for no-prep cases (mm)",
    )

    no_prep_mockup_image: PointerProperty(
        name="2D Mockup",
        type=bpy.types.Image,
        description="Smile photo with 2D veneer mockup (patient-approved)",
    )

    no_prep_camera_calibrated: BoolProperty(
        name="Camera Calibrated",
        default=False,
        description="Whether camera has been calibrated to photo",
    )

    ven_mode: EnumProperty(
        name="Veneer Mode",
        items=[
            ("CLASSIC", "Classic", "Margin-driven veneer workflow"),
            ("NO_PREP", "No-Prep", "Photo/mockup driven no-prep workflow"),
        ],
        default="CLASSIC",
    )
    ven_target_tooth_id: IntProperty(name="Recipe Tooth #", default=8, min=1, max=32)
    ven_min_thickness_mm: FloatProperty(
        name="Min Thickness", default=0.30, min=0.1, max=2.0, precision=3
    )
    ven_max_thickness_mm: FloatProperty(
        name="Max Thickness", default=0.70, min=0.1, max=3.0, precision=3
    )
    ven_border_taper_mm: FloatProperty(
        name="Border Taper", default=0.20, min=0.0, max=2.0, precision=3
    )
    ven_border_seal_mm: FloatProperty(
        name="Border Seal", default=0.01, min=0.0, max=0.2, precision=3
    )
    ven_spacer_internal_mm: FloatProperty(
        name="Internal Spacer", default=0.06, min=0.0, max=0.5, precision=3
    )
    ven_spacer_margin_mm: FloatProperty(
        name="Margin Spacer", default=0.00, min=0.0, max=0.2, precision=3
    )
    ven_facial_cutback_enabled: BoolProperty(
        name="Facial Cutback",
        default=True,
        description="Trim veneer to facial printable domain",
    )
    ven_facial_coverage: FloatProperty(
        name="Facial Coverage",
        default=0.62,
        min=0.35,
        max=1.0,
        subtype="FACTOR",
        precision=3,
        description="Portion of buccal-lingual span to keep toward facial side",
    )
    ven_facial_lingual_pad_mm: FloatProperty(
        name="Lingual Pad",
        default=0.0,
        min=0.0,
        max=2.0,
        precision=3,
        description="Extra lingual allowance added to facial domain cutoff (mm)",
    )
    ven_insertion_axis_mode: EnumProperty(
        name="Insertion Axis",
        items=[
            ("AUTO", "Auto", "Auto-detect insertion axis with minimal undercuts"),
            ("MANUAL", "Manual", "Use manual insertion axis vector"),
        ],
        default="AUTO",
    )
    ven_insertion_axis_vec: FloatVectorProperty(
        name="Manual Axis", subtype="DIRECTION", default=(0.0, 0.0, 1.0), size=3
    )
    ven_undercut_allow_deg: FloatProperty(
        name="Undercut Allowance", default=0.0, min=0.0, max=30.0, precision=2
    )
    ven_boolean_solver: EnumProperty(
        name="Boolean Solver",
        items=[
            ("EXACT", "Exact", "More robust and slower"),
            ("FAST", "Fast", "Faster and less robust"),
        ],
        default="EXACT",
    )
    ven_use_interprox_divider: BoolProperty(
        name="Use Interprox Divider",
        default=True,
        description="Clip generated veneer mesial/distal extents using saved divider points",
    )
    ven_interprox_pad_mm: FloatProperty(
        name="Interprox Stop Padding",
        default=0.05,
        min=0.0,
        max=1.0,
        precision=3,
        description="Extra padding beyond mesial/distal divider planes (mm)",
    )
    ven_interprox_preview_size_mm: FloatProperty(
        name="Interprox Preview Size",
        default=10.0,
        min=2.0,
        max=40.0,
        precision=2,
        description="Visual size of mesial/distal divider preview planes (mm)",
    )
    ven_interprox_preview_show: BoolProperty(
        name="Auto Show Interprox Preview",
        default=True,
        description="Automatically show divider preview planes after marking points",
    )
    ven_occlusion_threshold_mm: FloatProperty(
        name="Occlusion Threshold", default=0.10, min=0.01, max=1.0, precision=3
    )
    adj_contact_tight_mm: FloatProperty(
        name="Adj Tight Threshold",
        default=0.05,
        min=0.005,
        max=1.0,
        precision=3,
        description="Very tight adjacent contact threshold (mm)",
    )
    adj_contact_threshold_mm: FloatProperty(
        name="Adj Contact Threshold",
        default=0.10,
        min=0.005,
        max=2.0,
        precision=3,
        description="Adjacent contact threshold for contact map pass/fail (mm)",
    )
    adj_contact_max_mm: FloatProperty(
        name="Adj Max Visual",
        default=0.30,
        min=0.02,
        max=5.0,
        precision=3,
        description="Upper distance bound for adjacent contact map colors (mm)",
    )
    adj_contact_max_samples: IntProperty(
        name="Adj Max Samples",
        default=120000,
        min=1000,
        max=2000000,
        description="Max sampled vertices for adjacent contact solve",
    )
    adj_contact_neighbors_only: BoolProperty(
        name="Adjacent IDs Only",
        default=True,
        description="Prefer mesial/distal neighboring tooth IDs when available",
    )
    adj_contact_max_candidates: IntProperty(
        name="Adj Candidate Limit",
        default=8,
        min=2,
        max=64,
        description="Maximum candidate adjacent meshes to compare against",
    )
    adj_contact_write_vertex_group: BoolProperty(
        name="Write Contact Vertex Group",
        default=True,
        description="Write SMILE_ADJ_CONTACT vertex group for downstream workflows",
    )
    ven_validation_sample_limit: IntProperty(
        name="Validation Samples",
        default=25000,
        min=2000,
        max=200000,
        description="Higher improves accuracy but is slower on dense meshes",
    )

    symmetry_enabled: BoolProperty(
        name="Symmetry Enabled",
        default=False,
        description="Mirror paired anterior teeth edits",
    )

    sf_symmetry_mode: BoolProperty(name="Frame Symmetry", default=True)
    sf_picture_rotation_deg: FloatProperty(
        name="Picture Rotation", default=0.0, min=-30.0, max=30.0
    )
    sf_facial_thirds: BoolProperty(name="Facial Thirds", default=False)
    sf_facial_flow_offset_mm: FloatProperty(
        name="Facial Flow", default=0.0, min=-5.0, max=5.0, precision=2
    )
    sf_ratio_hw_right: FloatProperty(
        name="H/W Right", default=80.0, min=70.0, max=90.0, precision=1
    )
    sf_ratio_hw_left: FloatProperty(
        name="H/W Left", default=80.0, min=70.0, max=90.0, precision=1
    )
    sf_buccal_corridor_right: FloatProperty(
        name="Buccal Right", default=0.5, min=0.0, max=1.0, subtype="FACTOR"
    )
    sf_buccal_corridor_left: FloatProperty(
        name="Buccal Left", default=0.5, min=0.0, max=1.0, subtype="FACTOR"
    )
    sf_curve_source: EnumProperty(
        name="Curve Source",
        items=[
            ("AUTO", "Auto", "Build patient curve from visible teeth"),
            ("SELECTED", "Selected", "Use manually selected curve object"),
        ],
        default="AUTO",
    )
    sf_selected_curve_name: StringProperty(
        name="Selected Curve",
        default="",
        description="Curve object used for Smile Frame 3D when source=Selected",
    )
    sf_apply3d_height_strength: FloatProperty(
        name="Apply3D Height",
        default=0.75,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Vertical influence when applying Frame 3D curve to teeth",
    )
    sf_apply3d_xy_strength: FloatProperty(
        name="Apply3D XY",
        default=0.45,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Horizontal influence when applying Frame 3D curve to teeth",
    )
    sf_apply3d_rotate_enabled: BoolProperty(
        name="Apply3D Rotate",
        default=True,
        description="Rotate teeth around world Z toward ideal curve tangent",
    )
    sf_apply3d_rotate_strength: FloatProperty(
        name="Apply3D Rot Strength",
        default=0.40,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Rotation influence when applying Frame 3D",
    )
    sf_apply3d_max_rotate_deg: FloatProperty(
        name="Apply3D Max Rot",
        default=4.0,
        min=0.1,
        max=45.0,
        precision=2,
        description="Maximum rotation per tooth (degrees) for one apply pass",
    )
    sf_apply3d_preview_only: BoolProperty(
        name="Preview Only",
        default=False,
        description="Visualize apply-to-teeth deltas without moving teeth",
    )
    sf_case_import_strict: BoolProperty(
        name="Strict Import Mode",
        default=False,
        description="Block case-report import when diagnostics detect schema mismatch",
    )
    sf_apply3d_max_move_mm: FloatProperty(
        name="Apply3D Max Move",
        default=1.5,
        min=0.1,
        max=10.0,
        precision=3,
        description="Maximum translation per tooth (mm) for one apply pass",
    )
    sf_occlusal_curve_mode: EnumProperty(
        name="Occlusal Curve",
        items=[
            ("IDEAL", "Ideal", "Use ideal curve"),
            ("MATCH_PATIENT", "Match Patient", "Match patient curve"),
        ],
        default="IDEAL",
    )
    sf_curve_accuracy: FloatProperty(
        name="Curve Accuracy", default=0.5, min=0.0, max=1.0, subtype="FACTOR"
    )
    sf_superimpose: BoolProperty(name="Superimpose", default=False)
    sf_grid_enabled: BoolProperty(name="Grid", default=True)
    sf_liquify_enabled: BoolProperty(name="Liquify", default=False)
    sf_liquify_brush: EnumProperty(
        name="Liquify Brush",
        items=[
            ("INFLATE", "Inflate", ""),
            ("FLATTEN", "Flatten", ""),
            ("DEFORM", "Deform", ""),
            ("EDGES", "Edges", ""),
            ("SMOOTH", "Smooth", ""),
        ],
        default="DEFORM",
    )
    sf_liquify_size: FloatProperty(name="Brush Size", default=40.0, min=1.0, max=300.0)
    sf_liquify_intensity: FloatProperty(
        name="Brush Intensity", default=0.5, min=0.01, max=1.0, subtype="FACTOR"
    )

    crown_edit_show_outline: BoolProperty(
        name="Show Margin Outline",
        default=True,
        description="Show and emphasize traced margin curve during crown shape editing",
    )
    crown_edit_outline_thickness_mm: FloatProperty(
        name="Outline Thickness (mm)",
        default=0.05,
        min=0.01,
        max=0.50,
        precision=3,
        description="Displayed margin-outline thickness in crown edit mode",
    )
    crown_edit_show_wire_overlay: BoolProperty(
        name="Wire Overlay",
        default=True,
        description="Show restoration wire overlay while sculpting",
    )
    crown_edit_show_xray: BoolProperty(
        name="X-Ray",
        default=True,
        description="Enable translucent x-ray shading in 3D views during crown editing",
    )
    crown_edit_xray_alpha: FloatProperty(
        name="X-Ray Alpha",
        default=0.40,
        min=0.05,
        max=1.0,
        precision=2,
        subtype="FACTOR",
        description="X-ray opacity while crown edit mode is active",
    )
    crown_edit_show_in_front: BoolProperty(
        name="Show In Front",
        default=True,
        description="Draw active restoration in front while editing",
    )
    crown_edit_brush: EnumProperty(
        name="Brush",
        items=[
            ("GRAB", "Grab", "Move local crown shape with direct drag"),
            ("ELASTIC", "Elastic", "Elastic local deformation"),
            ("DRAW", "Draw", "Add/subtract local volume"),
            ("INFLATE", "Inflate", "Inflate/deflate local anatomy"),
            ("SMOOTH", "Smooth", "Smooth local irregularities"),
        ],
        default="ELASTIC",
    )
    crown_edit_response_profile: EnumProperty(
        name="Response",
        items=[
            ("SOFT", "Soft", "Very gentle edits, safest for small corrections"),
            ("CLINICAL", "Clinical", "Balanced clinical push/pull behavior"),
            ("FIRM", "Firm", "Faster larger edits with stronger response"),
        ],
        default="CLINICAL",
    )
    crown_edit_direction: EnumProperty(
        name="Direction",
        items=[
            ("PULL", "Pull", "Add/outward direction"),
            ("PUSH", "Push", "Subtract/inward direction"),
        ],
        default="PULL",
    )
    crown_edit_brush_size: FloatProperty(
        name="Brush Size",
        default=34.0,
        min=1.0,
        max=300.0,
        precision=1,
        description="Sculpt brush size for crown shape edit mode",
    )
    crown_edit_brush_strength: FloatProperty(
        name="Brush Strength",
        default=0.32,
        min=0.01,
        max=1.0,
        precision=2,
        subtype="FACTOR",
        description="Sculpt brush intensity for crown shape edit mode",
    )
    crown_edit_auto_smooth: FloatProperty(
        name="Auto Smooth",
        default=0.12,
        min=0.0,
        max=1.0,
        precision=2,
        subtype="FACTOR",
        description="Smooths brush strokes while dragging",
    )
    crown_edit_hardness: FloatProperty(
        name="Falloff Hardness",
        default=0.40,
        min=0.0,
        max=1.0,
        precision=2,
        subtype="FACTOR",
        description="Brush falloff hardness",
    )
    crown_edit_normal_radius_factor: FloatProperty(
        name="Normal Radius",
        default=0.35,
        min=0.0,
        max=2.0,
        precision=2,
        description="Normal sampling radius factor for smoother local pull/push",
    )
    crown_edit_tip_roundness: FloatProperty(
        name="Tip Roundness",
        default=0.95,
        min=0.0,
        max=1.0,
        precision=2,
        subtype="FACTOR",
        description="Brush tip roundness",
    )
    crown_edit_front_faces_only: BoolProperty(
        name="Front Faces Only",
        default=True,
        description="Prevent through-object edits on opposite surfaces",
    )

    cad_wizard_enabled: BoolProperty(
        name="Enable CAD Wizard",
        default=True,
        description="Show and use stage-locked CAD workflow in Tab 6",
    )
    cad_stage_lock_enforced: BoolProperty(
        name="Enforce Stage Lock",
        default=True,
        description="Require prior stage PASS before next stage can run",
    )
    cad_wizard_stage: EnumProperty(
        name="CAD Stage",
        items=[
            ("A_MARGIN", "A. Trace Margin", ""),
            ("B_SURVEY_BLOCKOUT", "B. Survey + Blockout", ""),
            ("C_SUPPORT_MARGIN", "C. Build Support Margin", ""),
            ("D_SPACER_SAFETY", "D. Spacer + Safety", ""),
            ("E_ADAPT_OUTER", "E. Adapt Outer Shell", ""),
            ("F_FINALIZE_INTAGLIO", "F. Finalize Intaglio", ""),
            ("G_VALIDATE", "G. Validate Restoration", ""),
            ("H_EXPORT", "H. Export Files", ""),
        ],
        default="A_MARGIN",
    )
    cad_case_mode: EnumProperty(
        name="CAD Mode",
        items=[
            ("VENEER", "Veneer", "Single-unit veneer workflow"),
            ("CROWN", "Crown", "Single-unit full crown workflow"),
            ("BRIDGE", "Bridge", "Bridge mode (Phase 2)"),
        ],
        default="VENEER",
    )
    cad_target_tooth_id: IntProperty(name="CAD Tooth #", default=8, min=1, max=32)
    cad_insertion_axis_mode: EnumProperty(
        name="Insertion Axis",
        items=[
            (
                "AUTO",
                "Auto Suggest",
                "System auto-detects insertion axis to minimize undercuts",
            ),
            ("MANUAL", "Locked Axis", "Use a fixed axis vector from assistant tools"),
        ],
        default="AUTO",
    )
    cad_insertion_axis_vec: FloatVectorProperty(
        name="Axis Vec", subtype="DIRECTION", size=3, default=(0.0, 0.0, 1.0)
    )
    cad_axis_auto_tune_manual: BoolProperty(
        name="Auto-Tune Manual Axis",
        default=True,
        description="When using Locked Axis, fine-tune direction toward lower undercut",
    )
    cad_min_thickness_mm: FloatProperty(
        name="Minimum Thickness (A) [mm]",
        description="Thinnest wall allowed anywhere on the restoration",
        default=0.20,
        min=0.05,
        max=2.0,
        precision=3,
    )
    cad_spacer_internal_um: FloatProperty(
        name="Cement Gap (C) [µm]",
        description="Space between tooth prep and restoration interior for cement",
        default=50.0,
        min=0.0,
        max=500.0,
        precision=1,
    )
    cad_extra_cement_gap_um: FloatProperty(
        name="Extra Cement Gap (B) [µm]",
        description="Additional gap beyond the main cement gap for passive fit",
        default=20.0,
        min=0.0,
        max=200.0,
        precision=1,
    )
    cad_smooth_distance_mm: FloatProperty(
        name="Smooth Distance (E) [mm]",
        description="Transition zone where cement gap blends to margin edge",
        default=0.20,
        min=0.0,
        max=2.0,
        precision=3,
    )
    cad_safety_zone_mm: FloatProperty(
        name="Distance to Margin (D) [mm]",
        description="Distance from restoration edge to the traced margin line",
        default=0.5,
        min=0.0,
        max=3.0,
        precision=3,
    )
    cad_spacer_margin_um: FloatProperty(
        name="Margin Line Offset (H) [µm]",
        description="Lateral offset applied to the traced margin line",
        default=0.0,
        min=0.0,
        max=200.0,
        precision=1,
    )
    cad_extension_offset_mm: FloatProperty(
        name="Extension Offset (I) [mm]",
        description="How far the restoration extends beyond the margin edge",
        default=0.001,
        min=0.0,
        max=1.0,
        precision=3,
    )
    cad_offset_angle_deg: FloatProperty(
        name="Offset Angle (J) [°]",
        description="Angle of the restoration wall at the margin",
        default=55.0,
        min=0.0,
        max=90.0,
        precision=1,
        subtype="FACTOR",
    )
    cad_support_margin_diameter_mm: FloatProperty(
        name="Support Margin Size [mm]",
        description="Diameter of the support structure at the margin line",
        default=0.10,
        min=0.05,
        max=1.0,
        precision=3,
    )
    cad_support_margin_profile: EnumProperty(
        name="Support Profile",
        items=[
            ("ROUND", "Round", "Rounded support profile"),
            ("SHARP", "Sharp", "Sharper profile"),
        ],
        default="ROUND",
    )
    cad_support_margin_height_mm: FloatProperty(
        name="Support Margin Height [mm]",
        description="Extrusion height of the chamfer/shoulder band above the traced margin",
        default=0.3,
        min=0.05,
        max=2.0,
        precision=3,
    )
    cad_use_remesh_before_boolean: BoolProperty(
        name="Remesh Before Boolean",
        default=True,
        description="Apply Voxel Remesh (0.1 mm) before boolean operations to prevent non-manifold artifacts",
    )
    cad_blockout_clearance_mm: FloatProperty(
        name="Undercut Blockout Clearance [mm]",
        description="How far undercut vertices are pushed along the insertion axis",
        default=0.05,
        min=0.0,
        max=1.0,
        precision=3,
    )
    cad_max_undercut_ratio: FloatProperty(
        name="Max Undercut Allowed",
        description="Maximum ratio of undercut area to total surface",
        default=0.25,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
    )
    cad_max_contact_count: IntProperty(
        name="Max Contact Points",
        description="Maximum number of occlusal contact points allowed",
        default=25,
        min=0,
        max=500,
    )
    cad_enable_mill_comp: BoolProperty(
        name="Enable Milling Compensation",
        description="Show drill/mill parameters",
        default=False,
    )
    cad_drill_radius_mm: FloatProperty(
        name="Drill Radius (F) [mm]",
        description="Radius of the smallest milling bur",
        default=0.0,
        min=0.0,
        max=3.0,
        precision=3,
    )
    cad_drill_comp_offset_mm: FloatProperty(
        name="Drill Compensation Offset (G) [mm]",
        description="Additional offset for milling tool wear",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=3,
    )
    cad_drill_tool_shape: EnumProperty(
        name="Tool Shape",
        description="Shape of the milling bur for drill compensation",
        items=[
            ("SPHERICAL", "Spherical", "Ball-end mill"),
            ("CYLINDRICAL", "Cylindrical", "Flat-end mill"),
        ],
        default="SPHERICAL",
    )
    cad_trim_interprox_enabled: BoolProperty(
        name="Trim by Interprox Divider", default=True
    )
    cad_outer_overlap_min_ratio: FloatProperty(
        name="Outer Overlap Min",
        default=0.18,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
        description="Stage E minimum acceptable margin-overlap ratio",
    )
    cad_outer_source_name: StringProperty(
        name="Reference Tooth Mesh",
        default="",
        description="Pinned restoration/library mesh used as Step E reference tooth",
    )
    cad_auto_pin_reference_on_import: BoolProperty(
        name="Auto-Pin Reference on Import",
        default=True,
        description="When imported tooth ID matches target tooth, pin it automatically",
    )
    cad_export_fmt: EnumProperty(
        name="CAD Export", items=[("STL", "STL", ""), ("OBJ", "OBJ", "")], default="STL"
    )
    cad_show_advanced_params: BoolProperty(
        name="Show Advanced CAD Parameters",
        default=False,
        description="Reveal advanced manufacturing and QA parameters",
    )
    cad_dummyproof_auto_export: BoolProperty(
        name="Auto Export After Validate",
        default=False,
        description="When running full CAD pipeline, auto-run Stage H export after Stage G passes",
    )
    cad_dummyproof_export_dir: StringProperty(
        name="CAD Export Directory",
        subtype="DIR_PATH",
        default="//",
        description="Folder used by dummy-proof full-run export output",
    )

    copy_mode: EnumProperty(
        name="Copy Mode",
        items=[
            ("TOOTH", "Tooth Only", "Copy only the tooth library object"),
            ("VENEER", "Veneer Only", "Copy only the generated veneer"),
            ("MARGIN", "Margin Only", "Copy only the margin curve"),
            ("ALL", "All", "Copy tooth, veneer, and margin together"),
        ],
        default="ALL",
        description="What to copy to contralateral side",
    )
    mirror_quadrant_direction: EnumProperty(
        name="Mirror Direction",
        items=[
            ("AUTO", "Auto", "Detect side from active/selection"),
            (
                "RIGHT_TO_LEFT",
                "Right -> Left",
                "Mirror right quadrant teeth to left side",
            ),
            (
                "LEFT_TO_RIGHT",
                "Left -> Right",
                "Mirror left quadrant teeth to right side",
            ),
        ],
        default="AUTO",
    )
    mirror_quadrant_replace_existing: BoolProperty(
        name="Replace Contralateral",
        default=True,
        description="Delete existing contralateral imported tooth before creating mirrored copy",
    )
    mirror_snap_to_occlusal_curve: BoolProperty(
        name="Snap Incisal/Cusp to Occlusal Arch",
        default=True,
        description="After mirror, fit tooth so incisal/cusp follows the mirrored position on occlusal arch tracer",
    )
    mirror_fit_mode: EnumProperty(
        name="Mirror Fit Mode",
        items=[
            (
                "EXACT_MIRROR",
                "Exact Mirror",
                "Keep strict mirror symmetry around midline plane",
            ),
            (
                "MIRROR_PLUS_GLOBAL_ARCH_SNAP",
                "Mirror + Global Arch Snap",
                "One rigid fit per arch to follow occlusal tracer",
            ),
        ],
        default="EXACT_MIRROR",
    )
    mirror_fit_require_mdc: BoolProperty(
        name="Require MDC Marks",
        default=True,
        description="Use only teeth with MDC marks as anchors for global arch snap",
    )
    mirror_use_manual_midline: BoolProperty(
        name="Use Manual Midline Point",
        default=True,
        description="Use user-saved midline point as mirror plane center",
    )

    photo_slots: CollectionProperty(type=SmilePhotoSlot)

    def update_active_photo(self, context):
        try:
            if not context or not hasattr(context, "scene") or context.scene is None:
                return
        except (AttributeError, RuntimeError):
            return

        slot = None
        if hasattr(context.scene, "smile_props"):
            props = context.scene.smile_props
            if 0 <= props.active_photo_slot_index < len(props.photo_slots):
                slot = props.photo_slots[props.active_photo_slot_index]

        if slot:
            if slot.camera_name:
                cam = bpy.data.objects.get(slot.camera_name)
                if cam:
                    context.scene.camera = cam

    active_photo_slot_index: IntProperty(
        name="Active Photo", default=0, min=0, update=update_active_photo
    )

    pnp_focal_mm: FloatProperty(
        name="Focal (mm)",
        default=50.0,
        min=1.0,
        max=300.0,
        description="Approx camera focal length used to build intrinsics",
    )
    pnp_sensor_width_mm: FloatProperty(
        name="Sensor Width (mm)",
        default=36.0,
        min=1.0,
        max=100.0,
        description="Camera sensor width for intrinsics conversion",
    )

    def update_photo_alpha(self, context):
        try:
            if not context or not hasattr(context, "scene") or context.scene is None:
                return
        except (AttributeError, RuntimeError):
            return

        alpha = self.pnp_bg_alpha

        try:
            slot = None
            if hasattr(context.scene, "smile_props"):
                props = context.scene.smile_props
                if 0 <= props.active_photo_slot_index < len(props.photo_slots):
                    slot = props.photo_slots[props.active_photo_slot_index]

            if slot:
                plane = (
                    bpy.data.objects.get(slot.plane_name) if slot.plane_name else None
                )
                if plane and plane.data.materials:
                    mat = plane.data.materials[0]
                    if mat and mat.use_nodes:
                        nodes = mat.node_tree.nodes
                        for node in nodes:
                            if node.type == "MIX_SHADER":
                                node.inputs[0].default_value = float(alpha)
                                break
        except Exception as e:
            print(f"Error updating photo alpha: {e}")

    pnp_bg_alpha: FloatProperty(
        name="Photo Alpha",
        default=0.65,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=update_photo_alpha,
    )
    pnp_plane_distance_mm: FloatProperty(
        name="Overlay Distance (mm)",
        default=1000.0,
        min=50.0,
        max=5000.0,
        description="Distance of the photo overlay plane in front of the camera",
    )
    pnp_use_ransac: BoolProperty(
        name="Use RANSAC",
        default=True,
        description="Use solvePnPRansac for outlier rejection",
    )
    pnp_ransac_reproj_px: FloatProperty(
        name="RANSAC Reproj (px)",
        default=8.0,
        min=1.0,
        max=50.0,
        description="RANSAC reprojection error in pixels",
    )
    pnp_use_photo_plane_markers: BoolProperty(
        name="Use PHOTO markers (plane)",
        default=True,
        description="If no click-based 2D landmarks exist, use PHOTO-domain markers on the photo plane",
    )

    mockup_depth_mm: FloatProperty(
        name="Placement Depth (mm)",
        default=1000.0,
        min=100.0,
        max=5000.0,
        description="Distance from camera for tooth placement in mm",
    )

    mockup_show_guides: BoolProperty(
        name="Show Proportion Guides",
        default=True,
        description="Display golden ratio guides during placement",
    )

    mockup_active_tooth: PointerProperty(
        type=bpy.types.Object,
        name="Active Mockup Tooth",
        description="Currently active tooth for mockup placement",
    )

    mockup_show_calibration_help: BoolProperty(
        name="Show Calibration Help",
        default=True,
        description="Show step-by-step calibration instructions",
    )

    mockup_show_advanced: BoolProperty(
        name="Show Advanced Settings",
        default=False,
        description="Show advanced placement options",
    )

    mockup_first_time_user: BoolProperty(
        name="First Time User",
        default=True,
        description="Show extra guidance for new users",
    )

    mockup_lock_to_surface: BoolProperty(
        name="Lock to Surface",
        default=False,
        description="Lock tooth position/rotation to surface attachment point",
    )


CLASSES = [
    SmileLibraryItem,
    SmileImportedMDCItem,
    SmilePhotoLandmark2D,
    SmilePhotoSlot,
    SmileAddonStateV2,
    SMILE_UL_asset_list,
    SMILE_UL_imported_mdc_list,
    SMILE_UL_photo_slots,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.smile_v2 = bpy.props.PointerProperty(type=SmileAddonStateV2)


def unregister():
    del bpy.types.Scene.smile_v2
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
