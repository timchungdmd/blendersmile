import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from ..core.constants import COL_GUIDES
from mathutils import Vector, Matrix

# ------------------------------------------------------------------------
# Golden Proportion Grid (GPU Draw)
# ------------------------------------------------------------------------
class SMILE_OT_DrawGoldenGrid(bpy.types.Operator):
    bl_idname = "smile.draw_golden_grid"
    bl_label = "Golden Ratio Grid"
    bl_description = "Draws a 1.618 : 1.0 : 0.618 grid in the viewport"
    
    _handle = None
    _timer = None
    
    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type == 'ESC' or event.type == 'RIGHTMOUSE':
            self.cancel(context)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            return {'CANCELLED'}
        
        # Singleton check: remove existing handler if running
        if SMILE_OT_DrawGoldenGrid._handle:
            bpy.types.SpaceView3D.draw_handler_remove(SMILE_OT_DrawGoldenGrid._handle, 'WINDOW')
            SMILE_OT_DrawGoldenGrid._handle = None
            return {'CANCELLED'}

        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, (context,), 'WINDOW', 'POST_PIXEL')
        SMILE_OT_DrawGoldenGrid._handle = self._handle
        
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if SMILE_OT_DrawGoldenGrid._handle:
            bpy.types.SpaceView3D.draw_handler_remove(SMILE_OT_DrawGoldenGrid._handle, 'WINDOW')
            SMILE_OT_DrawGoldenGrid._handle = None

    def draw_callback(self, context):
        # Calculate screen positions
        region = context.region
        mid_x = region.width / 2
        height = region.height
        
        # Parametric width (could be linked to property)
        width_central = 100 # Pixels
        width_lateral = width_central * 0.618
        width_canine = width_lateral * 0.618
        
        x_positions = [
            mid_x, # Midline
            mid_x + width_central,
            mid_x + width_central + width_lateral,
            mid_x + width_central + width_lateral + width_canine,
            mid_x - width_central,
            mid_x - width_central - width_lateral,
            mid_x - width_central - width_lateral - width_canine,
        ]
        
        coords = []
        for x in x_positions:
            coords.append((x, 0))
            coords.append((x, height))

        shader = gpu.shader.from_builtin('UNIFORM_COLOR') if bpy.app.version >= (4,0,0) else gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})
        
        shader.bind()
        shader.uniform_float("color", (1.0, 0.84, 0.0, 0.5)) # Gold color
        batch.draw(shader)

# ------------------------------------------------------------------------
# Facial Flow Rig
# ------------------------------------------------------------------------
class SMILE_OT_CreateFaceFrame(bpy.types.Operator):
    bl_idname = "smile.create_face_frame"
    bl_label = "Create Face Frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Create Main Frame
        frame = bpy.data.objects.new("SMILE_Face_Frame", None)
        frame.empty_display_type = 'ARROWS'
        frame.show_in_front = True
        
        col = bpy.data.collections.get(COL_GUIDES)
        if not col:
            col = bpy.data.collections.new(COL_GUIDES)
            context.scene.collection.children.link(col)
        col.objects.link(frame)
        
        # Create Pupils Line
        pupils = bpy.data.objects.new("SMILE_Ref_Pupils", None)
        pupils.empty_display_type = 'PLAIN_AXES'
        pupils.parent = frame
        col.objects.link(pupils)
        
        # Instructions
        self.report({'INFO'}, "Align 'Face Frame' to head, 'Ref_Pupils' to eyes.")
        
        # Select Frame
        bpy.ops.object.select_all(action='DESELECT')
        frame.select_set(True)
        context.view_layer.objects.active = frame
        
        return {'FINISHED'}
