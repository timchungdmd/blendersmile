bl_info = {
    "name": "Smile Design Pro (Enterprise)",
    "author": "Polymath Architect",
    "version": (2, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Smile",
    "description": "Advanced DSD workflow: PnP, Segmentation, Veneers.",
    "category": "3D View",
}

import bpy

# Import Modules
from .core import constants, math_utils, topology, registration
from .operators import op_align_2d, op_segmentation, op_veneer, op_rig, op_standard
from .ui import panels

# Property Group
class SmileProps(bpy.types.PropertyGroup):
    workflow_state: bpy.props.EnumProperty(
        items=[
            ('IMPORT', "1. Import", ""),
            ('ALIGN', "2. Align", ""),
            ('SEGMENT', "3. Segment", ""),
            ('DESIGN', "4. Design", ""),
            ('EXPORT', "5. Export", "")
        ],
        default='IMPORT'
    )
    
    # Segmentation Props
    segmentation_sensitivity: bpy.props.FloatProperty(name="Sensitivity", default=0.5, min=0, max=1)
    
    # Veneer Props
    veneer_thickness: bpy.props.FloatProperty(name="Thickness (mm)", default=0.5, min=0.1)

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
    op_rig.SMILE_OT_CreateRig,
    panels.SMILE_PT_Wizard,
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
