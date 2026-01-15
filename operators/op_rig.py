import bpy
from mathutils import Vector
from ..core.constants import COL_RIG

class SMILE_OT_CreateRig(bpy.types.Operator):
    bl_idname = "smile.create_rig"
    bl_label = "Create Lattice Rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj: return {'CANCELLED'}
        
        # Bounding Box
        bbox = [obj.matrix_world @ Vector(b) for b in obj.bound_box]
        min_v = Vector((min(v.x for v in bbox), min(v.y for v in bbox), min(v.z for v in bbox)))
        max_v = Vector((max(v.x for v in bbox), max(v.y for v in bbox), max(v.z for v in bbox)))
        center = (min_v + max_v) / 2
        size = (max_v - min_v) * 1.15 # Padding
        
        # Create Lattice
        lat_data = bpy.data.lattices.new(f"{obj.name}_LatData")
        lat = bpy.data.objects.new(f"{obj.name}_Lattice", lat_data)
        
        context.scene.collection.objects.link(lat)
        lat.location = center
        lat.scale = size / 2 # Lattice size is radius-based (-1 to 1)
        
        lat_data.points_u = 3
        lat_data.points_v = 3
        lat_data.points_w = 3
        
        # Add Modifier to Tooth
        mod = obj.modifiers.new("SmileRig", 'LATTICE')
        mod.object = lat
        
        self.report({'INFO'}, "Rig Created")
        return {'FINISHED'}
