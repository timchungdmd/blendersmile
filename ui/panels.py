import bpy
from ..core.constants import *

class SMILE_PT_Wizard(bpy.types.Panel):
    bl_label = "Smile Design Pro"
    bl_idname = "SMILE_PT_wizard"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smile"

    def draw(self, context):
        layout = self.layout
        props = context.scene.smile_props
        
        # State Bar
        row = layout.row(align=True)
        row.prop(props, "workflow_state", expand=True)
        
        layout.separator()
        
        if props.workflow_state == 'IMPORT':
            self.draw_import(layout)
        elif props.workflow_state == 'ALIGN':
            self.draw_align(layout)
        elif props.workflow_state == 'SEGMENT':
            self.draw_segment(layout)
        elif props.workflow_state == 'DESIGN':
            self.draw_design(layout)

    def draw_import(self, layout):
        box = layout.box()
        box.label(text="Import Data")
        box.operator("smile.import_scan", icon='IMPORT')

    def draw_align(self, layout):
        box = layout.box()
        box.label(text="Photogrammetry")
        box.operator("smile.align_2d", icon='CAMERA_DATA', text="Align 2D Photo")
        box.separator()
        box.label(text="Scan Registration")
        box.operator("smile.place_landmark", text="Place Landmarks")
        box.operator("smile.align_by_landmarks", text="Run Alignment (ICP)")

    def draw_segment(self, layout):
        box = layout.box()
        box.label(text="Intelligent Segmentation")
        box.prop(bpy.context.scene.smile_props, "segmentation_sensitivity")
        box.operator("smile.auto_segment", icon='SCULPTMODE_HLT')

    def draw_design(self, layout):
        box = layout.box()
        box.label(text="Veneers")
        box.operator("smile.make_veneer", icon='MOD_SOLIDIFY')
        box.separator()
        box.label(text="Rigging")
        box.operator("smile.create_rig", icon='LATTICE_DATA')
