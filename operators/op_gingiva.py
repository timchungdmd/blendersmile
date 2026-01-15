import bpy
from ..core.constants import COL_TEETH, COL_WAXUP

class SMILE_OT_AutoGingiva(bpy.types.Operator):
    bl_idname = "smile.auto_gingiva"
    bl_label = "Generate Auto-Gingiva"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 1. Collect all teeth
        col = bpy.data.collections.get(COL_TEETH)
        if not col: return {'CANCELLED'}
        
        # 2. Create Gingiva Object
        mesh = bpy.data.meshes.new("Gingiva_Mesh")
        obj = bpy.data.objects.new("Gingiva_Gen", mesh)
        
        col_wax = bpy.data.collections.get(COL_WAXUP) or bpy.data.collections.new(COL_WAXUP)
        if COL_WAXUP not in bpy.data.collections: context.scene.collection.children.link(col_wax)
        col_wax.objects.link(obj)
        
        # 3. Add Geometry Nodes Modifier
        mod = obj.modifiers.new("AutoGum", 'NODES')
        node_group = self.create_node_tree()
        mod.node_group = node_group
        
        # 4. Add teeth collection info
        # (User needs to manually assign the collection in the modifier in Blender 3.6+ script API quirks)
        # Or we script the node links:
        input_node = node_group.nodes.get('Group Input')
        # We need a Collection Info node inside
        
        self.report({'INFO'}, "Gingiva Object Created. Select 'Teeth' collection in the modifier.")
        return {'FINISHED'}

    def create_node_tree(self):
        # Basic Voxel Remesh + Smooth approach
        ng = bpy.data.node_groups.new("Smile_Gingiva_Nodes", 'GeometryNodeTree')
        
        # Interface
        ng.outputs.new('NodeSocketGeometry', "Geometry")
        
        # Nodes
        input_node = ng.nodes.new('NodeGroupInput')
        col_info = ng.nodes.new('GeometryNodeCollectionInfo')
        col_info.inputs['Collection'].default_value = bpy.data.collections.get(COL_TEETH)
        col_info.inputs['Separate Children'].default_value = True
        
        realize = ng.nodes.new('GeometryNodeRealizeInstances')
        
        # Convex Hull / Voxel Logic (Simplified for script)
        # In a real scenario, this would be a complex tree.
        # Here we use "Mesh to Volume" -> "Volume to Mesh" to fuse them
        
        m2v = ng.nodes.new('GeometryNodeMeshToVolume')
        m2v.inputs['Voxel Amount'].default_value = 128
        
        v2m = ng.nodes.new('GeometryNodeVolumeToMesh')
        
        set_mat = ng.nodes.new('GeometryNodeSetMaterial')
        
        output_node = ng.nodes.new('NodeGroupOutput')
        
        # Links
        ng.links.new(col_info.outputs['Geometry'], realize.inputs['Geometry'])
        ng.links.new(realize.outputs['Geometry'], m2v.inputs['Mesh'])
        ng.links.new(m2v.outputs['Volume'], v2m.inputs['Volume'])
        ng.links.new(v2m.outputs['Mesh'], set_mat.inputs['Geometry'])
        ng.links.new(set_mat.outputs['Geometry'], output_node.inputs['Geometry'])
        
        return ng
