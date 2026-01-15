import bpy
import numpy as np
from mathutils import Matrix, Vector
from ..core.math_utils import solve_pnp_dlt

class SMILE_OT_Align2D(bpy.types.Operator):
    bl_idname = "smile.align_2d"
    bl_label = "Align 3D to Photo (PnP)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        cam = scene.camera
        if not cam:
            self.report({'ERROR'}, "No active camera found.")
            return {'CANCELLED'}

        # 1. Retrieve Matched Points (Face Landmarks vs Image Landmarks)
        # Assuming user placed empty objects on the Image Plane and 3D Mesh
        # For this prototype, we fetch them by name pattern "PNP_IMG_xx" and "PNP_3D_xx"
        
        pts_3d = []
        pts_2d = []
        
        for i in range(1, 6): # Require at least 4-5 points
            obj_3d = bpy.data.objects.get(f"PNP_3D_{i:02d}")
            obj_2d = bpy.data.objects.get(f"PNP_IMG_{i:02d}")
            
            if obj_3d and obj_2d:
                pts_3d.append(obj_3d.location)
                # Convert 3D world location of the marker on the image plane to pixel/NDC
                co_2d = context.region.view2d.view_to_region(obj_2d.location[0], obj_2d.location[1], clip=False)
                # Simplification: Assume markers are in camera space or strictly 2D
                # Ideally, we read the x/y of the Empty in screen space.
                pts_2d.append([obj_2d.location.x, obj_2d.location.y])

        if len(pts_3d) < 4:
            self.report({'ERROR'}, "Need at least 4 point pairs (PNP_3D_xx / PNP_IMG_xx)")
            return {'CANCELLED'}

        # 2. Get Camera Intrinsic Matrix (K) from Blender
        render = scene.render
        w = render.resolution_x
        h = render.resolution_y
        f_mm = cam.data.lens
        sensor_w = cam.data.sensor_width
        
        fx = f_mm * w / sensor_w
        fy = f_mm * w / sensor_w # Assuming square pixels
        cx = w / 2
        cy = h / 2
        
        K = np.array([
            [fx, 0, cx],
            [0, fy, cy],
            [0,  0,  1]
        ])

        # 3. Solve PnP
        try:
            P_3d = np.array(pts_3d)
            P_2d = np.array(pts_2d)
            
            R, t = solve_pnp_dlt(P_3d, P_2d, K)
            
            # 4. Apply Inverse Transform to Camera
            # We move the camera, not the mesh (standard photogrammetry workflow)
            
            # Convert Numpy R/t to Blender Matrix
            R_b = Matrix(R.tolist())
            t_b = Vector(t.tolist())
            
            # Construct World Matrix: [R|t]^-1
            # Note: Coordinate system conversion (OpenCV -> Blender) needed here
            # OpenCV: X-right, Y-down, Z-forward
            # Blender: X-right, Y-up, Z-back
            # This requires a basis swizzle matrix.
            
            mat_cv = Matrix.Identity(4)
            mat_cv[0][0:3] = R_b[0]
            mat_cv[1][0:3] = R_b[1]
            mat_cv[2][0:3] = R_b[2]
            mat_cv[0][3] = t_b[0]
            mat_cv[1][3] = t_b[1]
            mat_cv[2][3] = t_b[2]
            
            cam.matrix_world = mat_cv.inverted()
            
            self.report({'INFO'}, "Camera Aligned via PnP")
            
        except Exception as e:
            self.report({'ERROR'}, f"PnP Failed: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}
