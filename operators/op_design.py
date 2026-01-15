import bpy
from ..core.constants import COL_SILHOUETTE, COL_TEETH

# ------------------------------------------------------------------------
# Chain Mode (Drivers)
# ------------------------------------------------------------------------
class SMILE_OT_ChainMode(bpy.types.Operator):
    bl_idname = "smile.chain_mode_toggle"
    bl_label = "Toggle Chain Symmetry"
    bl_options = {'REGISTER', 'UNDO'}

    enable: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        # Finds pairs like "Tooth_11" and "Tooth_21"
        # Adds drivers to 21 to follow 11 (inverted X)
        
        col = bpy.data.collections.get(COL_TEETH)
        if not col: return {'CANCELLED'}
        
        pairs = {} # '11': obj
        
        for obj in col.objects:
            # Assuming naming convention ending in FDI number
            # Using simple splitting for demo
            name_parts = obj.name.split('_')
            if len(name_parts) > 1 and name_parts[-1].isdigit():
                fdi = name_parts[-1]
                pairs[fdi] = obj
                
        # Map 1x -> 2x
        for i in range(1, 8):
            right = f"1{i}" # 11, 12...
            left  = f"2{i}" # 21, 22...
            
            if right in pairs and left in pairs:
                target = pairs[right]
                follower = pairs[left]
                
                if self.enable:
                    # Add Driver Location X (Inverted)
                    d = follower.driver_add("location", 0).driver
                    d.expression = "-var"
                    var = d.variables.new()
                    var.name = "var"
                    var.type = 'TRANSFORMS'
                    var.targets[0].id = target
                    var.targets[0].transform_type = 'LOC_X'
                    var.targets[0].transform_space = 'LOCAL_SPACE'
                    
                    # Scale (Copy)
                    for idx in [0,1,2]:
                        d = follower.driver_add("scale", idx).driver
                        d.expression = "var"
                        var = d.variables.new()
                        var.name = "var"
                        var.type = 'TRANSFORMS'
                        var.targets[0].id = target
                        var.targets[0].transform_type = f'SCALE_{"XYZ"[idx]}'
                        var.targets[0].transform_space = 'LOCAL_SPACE'
                else:
                    # Remove Drivers
                    follower.driver_remove("location", 0)
                    follower.driver_remove("scale")
                    
        self.report({'INFO'}, f"Symmetry {'Enabled' if self.enable else 'Disabled'}")
        return {'FINISHED'}

# ------------------------------------------------------------------------
# 2D Silhouette (Screen Space Lattice)
# ------------------------------------------------------------------------
class SMILE_OT_CreateSilhouette(bpy.types.Operator):
    bl_idname = "smile.create_silhouette"
    bl_label = "Edit 2D Silhouette"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        cam = context.scene.camera
        if not obj or not cam: return {'CANCELLED'}
        
        # Create Lattice
        lat_data = bpy.data.lattices.new("Silhouette_Lat")
        lat = bpy.data.objects.new(f"Sil_{obj.name}", lat_data)
        
        col = bpy.data.collections.get(COL_SILHOUETTE)
        if not col:
            col = bpy.data.collections.new(COL_SILHOUETTE)
            context.scene.collection.children.link(col)
        col.objects.link(lat)
        
        # Align to Camera
        lat.matrix_world = cam.matrix_world
        lat.location = obj.location # Center on object but oriented to cam
        
        # Scale lattice to cover object screen projection
        # (Simplified: fixed scale for prototype)
        lat.scale = (10, 10, 1) 
        
        lat_data.points_u = 4
        lat_data.points_v = 4
        lat_data.points_w = 1
        
        # Add modifier
        mod = obj.modifiers.new("Silhouette", 'LATTICE')
        mod.object = lat
        
        # Enter Edit Mode
        context.view_layer.objects.active = lat
        bpy.ops.object.mode_set(mode='EDIT')
        
        return {'FINISHED'}
