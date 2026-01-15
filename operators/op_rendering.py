import bpy
from ..core.constants import MAT_TRUSMILE, MAT_GUM

class SMILE_OT_CreateShaders(bpy.types.Operator):
    bl_idname = "smile.create_shaders"
    bl_label = "Load TruSmile Shaders"
    
    def execute(self, context):
        self.create_enamel()
        self.create_gum()
        self.report({'INFO'}, "TruSmile Shaders Created")
        return {'FINISHED'}

    def create_enamel(self):
        if MAT_TRUSMILE in bpy.data.materials: return
        mat = bpy.data.materials.new(MAT_TRUSMILE)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        
        bsdf = nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (0.8, 0.78, 0.75, 1)
        bsdf.inputs['Subsurface'].default_value = 0.1
        bsdf.inputs['Subsurface Color'].default_value = (0.8, 0.75, 0.7, 1)
        bsdf.inputs['Roughness'].default_value = 0.05
        bsdf.inputs['Clearcoat'].default_value = 1.0
        bsdf.inputs['Transmission'].default_value = 0.2
        
    def create_gum(self):
        if MAT_GUM in bpy.data.materials: return
        mat = bpy.data.materials.new(MAT_GUM)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (0.6, 0.1, 0.1, 1)
        bsdf.inputs['Subsurface'].default_value = 0.5
        bsdf.inputs['Subsurface Color'].default_value = (0.8, 0.2, 0.2, 1)
        bsdf.inputs['Roughness'].default_value = 0.3
