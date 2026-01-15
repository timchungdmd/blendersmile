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
        elif props.workflow_state == 'EXPORT':
            self.draw_export(layout)

    def draw_import(self, layout):
        box = layout.box()
        box.label(text="Import Data")
        box.operator("smile.import_scan", icon='IMPORT')
        box.operator("smile.import_teeth_folder", icon='FILE_FOLDER')

    def draw_align(self, layout):
        box = layout.box()
        box.label(text="Photogrammetry")
        box.operator("smile.align_2d", icon='CAMERA_DATA', text="Align 2D Photo (PnP)")
        
        box.separator()
        box.label(text="Facial Analysis")
        box.operator("smile.draw_golden_grid", icon='GRID', text="Toggle Golden Grid")
        box.operator("smile.create_face_frame", icon='EMPTY_AXIS', text="Create Face Frame")
        
        box.separator()
        box.label(text="Scan Registration")
        box.operator("smile.place_landmark", text="Place Landmarks")
        box.operator("smile.align_by_landmarks", text="Run Alignment (ICP)")

    def draw_segment(self, layout):
        box = layout.box()
        box.label(text="Intelligent Segmentation")
        box.prop(bpy.context.scene.smile_props, "segmentation_sensitivity")
        box.operator("smile.auto_segment", icon='SCULPTMODE_HLT')
        
        box.separator()
        box.label(text="Auto-Gingiva")
        box.operator("smile.auto_gingiva", icon='NODETREE')

    def draw_design(self, layout):
        box = layout.box()
        box.label(text="Parametric Design")
        box.operator("smile.chain_mode_toggle", icon='LINK_BLEND', text="Toggle Symmetry (Chain)")
        
        box.separator()
        box.label(text="Refinement")
        box.operator("smile.create_silhouette", icon='MOD_LATTICE', text="2D Silhouette Edit")
        box.operator("smile.make_veneer", icon='MOD_SOLIDIFY')
        
        box.separator()
        box.label(text="Visualization")
        box.operator("smile.create_shaders", icon='SHADING_RENDERED', text="Apply TruSmile Shaders")
        box.operator("smile.create_rig", icon='LATTICE_DATA', text="Rig Selected")

    def draw_export(self, layout):
        box = layout.box()
        box.label(text="Fabrication")
        box.operator("smile.export_veneer_active", icon='EXPORT')
