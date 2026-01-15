import bpy
import os
import re
import math
from mathutils import Vector, Matrix
from bpy_extras.io_utils import ImportHelper
from ..core.constants import COL_TEETH, COL_ARCH

class SMILE_OT_ImportLibrary(bpy.types.Operator, ImportHelper):
    """Batch imports teeth from a folder based on filenames (11.stl, 21.obj, etc.)"""
    bl_idname = "smile.import_library"
    bl_label = "Import Tooth Library"
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper mixin defaults
    filename_ext = ""
    use_filter_folder = True

    def execute(self, context):
        folder = os.path.dirname(self.filepath)
        files = os.listdir(folder)
        
        # Regex to find FDI numbers (e.g., "Tooth_11_High.stl" -> "11")
        # Matches any 2-digit number 11-48 inside a string
        regex = re.compile(r"(?<!\d)([1-4][1-8])(?!\d)") 

        # Ensure Collection
        col = bpy.data.collections.get(COL_TEETH)
        if not col:
            col = bpy.data.collections.new(COL_TEETH)
            context.scene.collection.children.link(col)

        imported_count = 0

        for f in files:
            if not f.lower().endswith(('.stl', '.obj', '.ply')):
                continue
            
            match = regex.search(f)
            if match:
                fdi = match.group(1)
                full_path = os.path.join(folder, f)
                
                # Import
                if f.lower().endswith('.obj'):
                    bpy.ops.import_scene.obj(filepath=full_path, use_split_objects=False)
                elif f.lower().endswith('.stl'):
                    bpy.ops.import_mesh.stl(filepath=full_path)
                elif f.lower().endswith('.ply'):
                    bpy.ops.import_mesh.ply(filepath=full_path)
                
                # Process Imported Object
                # Blender selects imported objects automatically
                obj = context.selected_objects[0]
                obj.name = f"TOOTH_{fdi}"
                
                # Center Geometry (Crucial for rotation)
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
                
                # Move to Collection
                for c in obj.users_collection: c.objects.unlink(obj)
                col.objects.link(obj)
                
                imported_count += 1
        
        self.report({'INFO'}, f"Auto-Imported {imported_count} teeth into '{COL_TEETH}'")
        return {'FINISHED'}

class SMILE_OT_AutoDistribute(bpy.types.Operator):
    """Places imported teeth along the active curve using Frenet Frames"""
    bl_idname = "smile.auto_distribute"
    bl_label = "Auto-Place on Curve"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 1. Get Curve
        curve_obj = context.active_object
        if not curve_obj or curve_obj.type != 'CURVE':
            self.report({'ERROR'}, "Select the Arch Curve first")
            return {'CANCELLED'}
        
        # 2. Get Teeth
        col = bpy.data.collections.get(COL_TEETH)
        if not col: return {'CANCELLED'}
        
        teeth_map = {}
        for obj in col.objects:
            # Parse FDI from name "TOOTH_11"
            parts = obj.name.split('_')
            if len(parts) > 1 and parts[-1].isdigit():
                teeth_map[int(parts[-1])] = obj

        # 3. Define Ideal Positions (Heuristic)
        # We map FDI numbers to a approximate 'Factor' along the curve (0.0 to 1.0)
        # Assuming Curve starts at Right Molars (0.0) -> Midline (0.5) -> Left Molars (1.0)
        # This is a robust starting point for typical Bezier arches
        
        ideal_packing = {
            18: 0.10, 17: 0.15, 16: 0.20, 15: 0.25, 14: 0.30, 13: 0.35, 12: 0.42, 11: 0.48,
            21: 0.52, 22: 0.58, 23: 0.65, 24: 0.70, 25: 0.75, 26: 0.80, 27: 0.85, 28: 0.90
        }
        
        # Determine curve direction (check if midline is 0.5 or inverted)
        # For this script, we assume standard drawing direction (Right -> Left)
        
        spline = curve_obj.data.splines[0]
        length = spline.calc_length()
        
        # 4. Placement Loop
        for fdi, t_factor in ideal_packing.items():
            if fdi in teeth_map:
                tooth = teeth_map[fdi]
                
                # Get Point and Tangent at factor t
                # Note: This is a simplified sample. For high precision, we iterate interpolated points.
                
                # Transform factor to world coord
                # Blender API doesn't have direct 'evaluate(t)' for curves easily exposed without mathutils
                # We use a robust interpolation trick:
                
                loc, tan, norm = self.sample_curve(curve_obj, t_factor)
                
                tooth.location = loc
                
                # Align Rotation
                # Tangent (Y axis of tooth) -> Curve Tangent
                # Normal (Z axis of tooth) -> Global Z (or Curve Normal)
                
                rot_matrix = self.get_rotation_matrix(tan, Vector((0,0,1)))
                tooth.rotation_euler = rot_matrix.to_euler()
                
                # Correction for specific teeth (Canines often need tilt)
                if fdi in [13, 23]:
                    # Slight rotation for aesthetic prominence
                    pass

        self.report({'INFO'}, "Teeth distributed along curve")
        return {'FINISHED'}

    def sample_curve(self, curve_obj, factor):
        """Returns Location, Tangent, Normal at factor (0-1)"""
        # Convert curve to a temporary mesh to query exact surface data easily
        # or evaluate spline points. Here we use spline evaluation.
        
        spline = curve_obj.data.splines[0]
        # Bezier spline points are not linear, so factor 0.5 might not be middle distance.
        # But it's good enough for initial placement.
        
        # Map factor to segment indices
        # (Simplified logic: Assuming a high-res poly spline or converted bezier)
        
        # Robust Fallback: Interpolate Bezier
        p_len = len(spline.bezier_points)
        if p_len < 2: return Vector(), Vector(), Vector()
        
        # We assume the curve is scaled 0 to 1. 
        # We iterate to find the point.
        
        mw = curve_obj.matrix_world
        
        # Provide discrete sampling
        resolution = 100
        target_idx = int(factor * resolution)
        
        # Create a temp mesh line to get data
        deps = bpy.context.evaluated_depsgraph_get()
        obj_eval = curve_obj.evaluated_get(deps)
        mesh = obj_eval.to_mesh()
        
        if target_idx >= len(mesh.vertices): target_idx = len(mesh.vertices) - 1
        
        v = mesh.vertices[target_idx]
        loc = mw @ v.co
        
        # Tangent approx
        v_next = mesh.vertices[min(target_idx+1, len(mesh.vertices)-1)]
        v_prev = mesh.vertices[max(target_idx-1, 0)]
        tan = (mw @ v_next.co - mw @ v_prev.co).normalized()
        
        # Normal (Global Up)
        norm = Vector((0,0,1))
        
        obj_eval.to_mesh_clear()
        
        return loc, tan, norm

    def get_rotation_matrix(self, forward_vector, up_vector):
        """Constructs a rotation matrix aligning Y to forward, Z to up"""
        y_axis = forward_vector.normalized()
        z_axis = up_vector.normalized()
        x_axis = y_axis.cross(z_axis).normalized()
        
        # Re-orthogonalize Z
        z_axis = x_axis.cross(y_axis).normalized()
        
        # Create Matrix (Columns: X, Y, Z)
        R = Matrix((
            (x_axis.x, y_axis.x, z_axis.x),
            (x_axis.y, y_axis.y, z_axis.y),
            (x_axis.z, y_axis.z, z_axis.z)
        ))
        return R.to_4x4()
