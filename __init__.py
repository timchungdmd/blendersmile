bl_info = {
    "name": "Smile Design Pro (Enterprise)",
    "author": "Polymath Architect",
    "version": (2, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Smile",
    "description": "Advanced DSD workflow: PnP, Analysis, Gingiva, Veneers.",
    "category": "3D View",
}

import bpy
from .operators import op_fabrication  # <--- NEW
from .operators import op_library  # <--- NEW IMPORT
# Import Modules
from .core import constants, math_utils, topology, registration
from .operators import op_align_2d, op_segmentation, op_veneer, op_rig, op_standard
from .operators import op_analysis, op_design, op_gingiva, op_rendering # NEW MODULES
from .ui import panels

# Property Group
class SmileProps(bpy.types.PropertyGroup):
    workflow_state: bpy.props.EnumProperty(
        items=[
            ('IMPORT', "1. Import", ""),
            ('ALIGN', "2. Analysis", ""),
            ('SEGMENT', "3. Gingiva", ""),
            ('DESIGN', "4. Design", ""),
            ('EXPORT', "5. Export", "")
        ],
        default='IMPORT'
    )
    
    # Segmentation Props
    segmentation_sensitivity: bpy.props.FloatProperty(name="Sensitivity", default=0.5, min=0, max=1)
    
    # Veneer Props
    veneer_thickness: bpy.props.FloatProperty(name="Thickness (mm)", default=0.5, min=0.1)
    
    # Analysis Props (From legacy file, kept for compatibility)
    face_target: bpy.props.StringProperty(name="FACE target", default="")
    max_target:  bpy.props.StringProperty(name="MAX target", default="")
    man_target:  bpy.props.StringProperty(name="MAN target", default="")
    
    # Landmark Props
    marker_size: bpy.props.FloatProperty(name="Size", default=1.5)
    snap_to_vertex: bpy.props.BoolProperty(name="Snap", default=False)
    lm_sticky_lock: bpy.props.BoolProperty(default=True)
    lm_prevent_overwrite: bpy.props.BoolProperty(default=True)
    
    # Pairing
    pair_domain_a: bpy.props.EnumProperty(items=[(d,d,"") for d in constants.DOMAINS], default=constants.DOMAIN_FACE)
    pair_domain_b: bpy.props.EnumProperty(items=[(d,d,"") for d in constants.DOMAINS], default=constants.DOMAIN_MAX)
    pair_start_with_b: bpy.props.BoolProperty(default=False)
    
    # ICP
    icp_enable: bpy.props.BoolProperty(default=True)
    icp_samples: bpy.props.IntProperty(default=20000)
    icp_threshold: bpy.props.FloatProperty(default=1.0)
    icp_normal_radius: bpy.props.FloatProperty(default=2.0)
    
    # Alignment Stats
    align_source_domain: bpy.props.EnumProperty(items=[(d,d,"") for d in constants.DOMAINS])
    align_target_domain: bpy.props.EnumProperty(items=[(d,d,"") for d in constants.DOMAINS])
    last_align_count: bpy.props.IntProperty()
    last_align_rms: bpy.props.FloatProperty()
    last_align_max: bpy.props.FloatProperty()
    
    # Rig
    rig_size_pad: bpy.props.FloatProperty(default=1.15)


# Registry List
classes = (
    SmileProps,
    op_standard.SMILE_OT_ImportScan,
    op_standard.SMILE_OT_PlaceLandmark,
    op_standard.SMILE_OT_ArchTrace,
    op_align_2d.SMILE_OT_Align2D,
    op_segmentation.SMILE_OT_AutoSegment,
    op_veneer.SMILE_OT_MakeVeneer,
    op_veneer.SMILE_OT_MarginTraceAuto,
    op_veneer.SMILE_OT_ExportVeneerActive, # Ensure this class is in op_veneer
    op_rig.SMILE_OT_CreateRig,
    # NEW OPERATORS
    op_analysis.SMILE_OT_DrawGoldenGrid,
    op_analysis.SMILE_OT_CreateFaceFrame,
    op_design.SMILE_OT_ChainMode,
    op_design.SMILE_OT_CreateSilhouette,
    op_gingiva.SMILE_OT_AutoGingiva,
    op_rendering.SMILE_OT_CreateShaders,
    op_fabrication.SMILE_OT_GenerateShell, # <--- NEW
    panels.SMILE_PT_Wizard,
)
classes = (
    # ... existing classes ...
    op_library.SMILE_OT_ImportLibrary,  # <--- NEW CLASS
    op_library.SMILE_OT_AutoDistribute, # <--- NEW CLASS
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.smile_props = bpy.props.PointerProperty(type=SmileProps)

def unregister():
    del bpy.types.Scene.smile_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
