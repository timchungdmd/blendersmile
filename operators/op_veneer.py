import bpy
import bmesh
from bpy_extras.io_utils import ExportHelper
from ..core.constants import *
from ..core.topology import trace_margin_path

class SMILE_OT_MakeVeneer(bpy.types.Operator):
    bl_idname = "smile.make_veneer"
    bl_label = "Generate Veneer"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tooth = context.active_object
        if not tooth: return {'CANCELLED'}
        
        scene = context.scene
        props = scene.smile_props
        
        # 1. Create Margin Group
        vg = tooth.vertex_groups.get("SMILE_MARGIN")
        if not vg:
            self.report({'ERROR'}, "No margin found. Trace margin first.")
            return {'CANCELLED'}
            
        # 2. Duplicate for Veneer
        ven_name = f"{tooth.name}_VENEER"
        if ven_name in bpy.data.objects:
            ven = bpy.data.objects[ven_name]
        else:
            ven = tooth.copy()
            ven.data = tooth.data.copy() # Independent mesh
            ven.name = ven_name
            context.scene.collection.objects.link(ven)
        
        # 3. Modifier Stack
        ven.modifiers.clear()
        
        # Mask
        mod_mask = ven.modifiers.new("Mask", 'MASK')
        mod_mask.vertex_group = "SMILE_MARGIN"
        
        # Solidify
        mod_solid = ven.modifiers.new("Solidify", 'SOLIDIFY')
        mod_solid.thickness = props.veneer_thickness
        mod_solid.offset = 1.0
        
        # Shrinkwrap (Intaglio)
        mod_wrap = ven.modifiers.new("Intaglio", 'SHRINKWRAP')
        mod_wrap.target = tooth
        mod_wrap.offset = 0.01
        
        # Move to Veneer Collection
        col_ven = bpy.data.collections.get(COL_VENEER)
        if not col_ven:
            col_ven = bpy.data.collections.new(COL_VENEER)
            context.scene.collection.children.link(col_ven)
        
        # Link to Veneer Collection, unlink from others
        for col in ven.users_collection:
            col.objects.unlink(ven)
        col_ven.objects.link(ven)
        
        context.view_layer.objects.active = ven
        ven.select_set(True)
        tooth.select_set(False)

        self.report({'INFO'}, f"Veneer created: {ven_name}")
        return {'FINISHED'}

class SMILE_OT_MarginTraceAuto(bpy.types.Operator):
    """Uses the Core Topology Geodesic Path (Placeholder for Future Implementation)"""
    bl_idname = "smile.margin_trace_auto"
    bl_label = "Auto Trace Margin"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        # Implementation relying on selection
        obj = context.active_object
        if not obj: return {'CANCELLED'}
        
        # In a full implementation, this calls core.topology.trace_margin_path
        self.report({'INFO'}, "Margin Auto-Trace (Placeholder Executed)")
        
        return {'FINISHED'}

class SMILE_OT_ExportVeneerActive(bpy.types.Operator, ExportHelper):
    """Exports the active veneer to STL"""
    bl_idname = "smile.export_veneer_active"
    bl_label = "Export Active Veneer"
    bl_options = {'REGISTER', 'UNDO'}

    # ExportHelper mixin class uses this
    filename_ext = ".stl"

    filter_glob: bpy.props.StringProperty(
        default="*.stl",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'WARNING'}, "No active object to export")
            return {'CANCELLED'}

        # Ensure we are in object mode
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')

        # Apply modifiers temporarily for export if needed, 
        # or use Blender's built-in export with use_selection=True
        
        try:
            bpy.ops.export_mesh.stl(
                filepath=self.filepath,
                check_existing=True,
                use_selection=True,
                use_mesh_modifiers=True,  # Important for the veneer modifier stack
                batch_mode='OFF'
            )
            self.report({'INFO'}, f"Exported: {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, f"Export Failed: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}
