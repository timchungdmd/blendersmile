import bpy
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
        
        # 1. Create Margin Group (Using the new Geodesic Trace if available, else standard)
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
        
        self.report({'INFO'}, f"Veneer created: {ven_name}")
        return {'FINISHED'}

class SMILE_OT_MarginTraceAuto(bpy.types.Operator):
    """Uses the Core Topology Geodesic Path"""
    bl_idname = "smile.margin_trace_auto"
    bl_label = "Auto Trace Margin"
    
    def execute(self, context):
        # Implementation relying on selection
        # This assumes user selected two vertices in Edit Mode
        obj = context.active_object
        if not obj: return {'CANCELLED'}
        
        # Call core logic (conceptual)
        # path = trace_margin_path(bm, v1, v2)
        # Apply to Vertex Group...
        
        return {'FINISHED'}
