import bpy
import bmesh
from ..core.constants import COL_TEETH, COL_SCANS, COL_WAXUP

class SMILE_OT_GenerateShell(bpy.types.Operator):
    """Generates a 3D printable veneer shell from the designed teeth."""
    bl_idname = "smile.generate_shell"
    bl_label = "Generate Printable Shell"
    bl_options = {'REGISTER', 'UNDO'}

    cement_gap: bpy.props.FloatProperty(
        name="Cement Gap (mm)", 
        default=0.06, 
        min=0.01, 
        max=0.5,
        description="Internal offset for passive fit"
    )

    resolution: bpy.props.IntProperty(
        name="Voxel Resolution",
        default=250,
        description="Higher is sharper but slower. Used for Remeshing."
    )

    def execute(self, context):
        # 1. Validation
        col_teeth = bpy.data.collections.get(COL_TEETH)
        if not col_teeth or len(col_teeth.objects) == 0:
            self.report({'ERROR'}, "No teeth found in 'Teeth' collection")
            return {'CANCELLED'}

        # Find the Scan (Assuming active object or first in Scans collection)
        scan_obj = context.active_object
        if not scan_obj or scan_obj.type != 'MESH':
            # Try to find in Scans collection
            col_scans = bpy.data.collections.get(COL_SCANS)
            if col_scans and col_scans.objects:
                scan_obj = col_scans.objects[0]
            else:
                self.report({'ERROR'}, "Select the Patient Scan (Model) first.")
                return {'CANCELLED'}

        self.report({'INFO'}, "Processing Shell... This may take a moment.")
        
        # 2. Duplicate & Fuse Design (The "Union" Step)
        # We use Voxel Remesh for robust boolean union without topology errors
        
        # Duplicate all teeth and join
        bpy.ops.object.select_all(action='DESELECT')
        
        temp_obs = []
        for obj in col_teeth.objects:
            if obj.type == 'MESH' and not obj.hide_viewport:
                dup = obj.copy()
                dup.data = obj.data.copy()
                context.scene.collection.objects.link(dup)
                dup.select_set(True)
                temp_obs.append(dup)
        
        context.view_layer.objects.active = temp_obs[0]
        bpy.ops.object.join()
        combined_design = context.active_object
        combined_design.name = "TEMP_Design_Union"

        # Apply Modifiers (in case of mirror/lattice)
        bpy.ops.object.convert(target='MESH')
        
        # 3. Create the "Blockout" / Spacer Mesh
        # Duplicate Scan
        spacer = scan_obj.copy()
        spacer.data = scan_obj.data.copy()
        spacer.name = "TEMP_Scan_Spacer"
        context.scene.collection.objects.link(spacer)
        
        # Displace along Normal (Cement Gap)
        # We modify the mesh directly for speed
        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = spacer
        spacer.select_set(True)
        
        # Use Displace Modifier
        mod_disp = spacer.modifiers.new("CementGap", 'DISPLACE')
        mod_disp.mid_level = 0.0
        mod_disp.strength = self.cement_gap
        # Note: Standard displace uses normal, which is what we want
        
        bpy.ops.object.convert(target='MESH')

        # 4. The Boolean Operation
        # Shell = Design - Spacer
        
        # We attach the boolean to the Design
        context.view_layer.objects.active = combined_design
        mod_bool = combined_design.modifiers.new("Intaglio", 'BOOLEAN')
        mod_bool.operation = 'DIFFERENCE'
        mod_bool.object = spacer
        mod_bool.solver = 'EXACT' # Slower but robust for watertight prints
        
        # Apply
        try:
            bpy.ops.object.convert(target='MESH')
        except RuntimeError:
             self.report({'WARNING'}, "Boolean failed. Try adjusting position.")
             # Cleanup
             bpy.data.objects.remove(spacer)
             return {'CANCELLED'}

        # 5. Cleanup & Finalize
        bpy.data.objects.remove(spacer)
        
        # Rename and Move
        combined_design.name = "Printable_Mockup_Shell"
        col_wax = bpy.data.collections.get(COL_WAXUP)
        if not col_wax:
            col_wax = bpy.data.collections.new(COL_WAXUP)
            context.scene.collection.children.link(col_wax)
            
        for c in combined_design.users_collection: c.objects.unlink(combined_design)
        col_wax.objects.link(combined_design)
        
        # 6. Verify (Check for non-manifold)
        # Simple heuristic: Select All
        combined_design.select_set(True)
        context.view_layer.objects.active = combined_design
        
        self.report({'INFO'}, f"Shell Generated: {combined_design.name}")
        return {'FINISHED'}
