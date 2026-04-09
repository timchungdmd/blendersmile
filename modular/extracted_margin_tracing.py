# ============================================================
# MARGIN TRACING CODE - Extracted from monolith backup
# Source: blendersmile_pnp_full_cleaned_20260318_165959.py
# Lines: 19091-27089 (~8000 lines total)
# ============================================================

import traceback

# ============================================================
# Section 1: SMILE_OT_trace_geodesic_magnet (lines ~19091-19390)
# ============================================================


class SMILE_OT_trace_geodesic_magnet(bpy.types.Operator):
    bl_idname = "smile.trace_geodesic_magnet"
    bl_label = "Magnetic Geodesic Tracer"
    bl_options = {"REGISTER", "UNDO"}

    _bm = None
    _bmesh_obj = None
    _prev_idx = -1
    _curve_obj = None
    _markers = []
    _kd = None

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the mesh.")
            return {"CANCELLED"}

        self._bmesh_obj = obj
        self._markers = []
        self._prev_idx = -1

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")

        import bmesh

        self._bm = bmesh.from_edit_mesh(obj.data)
        self._bm.verts.ensure_lookup_table()

        self._kd = KDTree(len(self._bm.verts))
        mw = obj.matrix_world
        for i, v in enumerate(self._bm.verts):
            self._kd.insert(mw @ v.co, i)
        self._kd.balance()

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Click to trace margin. Auto-snaps to ridge & follows surface."
        )
        return {"RUNNING_MODAL"}

    def find_sharpest_idx(self, world_loc, radius=1.5):
        items = self._kd.find_range(world_loc, radius)
        if not items:
            return -1

        best_idx = -1
        max_score = -1.0

        for co, index, dist in items:
            v = self._bm.verts[index]
            neighbors = [e.other_vert(v) for e in v.link_edges]
            if not neighbors:
                continue
            avg_n = Vector((0, 0, 0))
            for n in neighbors:
                avg_n += n.normal
            if avg_n.length_squared > 1e-12:
                avg_n.normalize()
            curv = 1.0 - v.normal.dot(avg_n)

            if curv > max_score:
                max_score = curv
                best_idx = index

        return best_idx

    def update_curve_visual(self):
        pass

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            for m in self._markers:
                delete_object(m)
            bpy.ops.object.mode_set(mode="OBJECT")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._bmesh_obj)
            if hit:
                raw_loc, _, _ = hit
                snap_idx = self.find_sharpest_idx(raw_loc)
                if snap_idx == -1:
                    return {"RUNNING_MODAL"}

                if self._prev_idx != -1:
                    bpy.ops.mesh.select_all(action="DESELECT")
                    self._bm.verts.ensure_lookup_table()
                    v_prev = self._bm.verts[self._prev_idx]
                    v_curr = self._bm.verts[snap_idx]
                    self._bm.select_history.add(v_prev)
                    v_prev.select = True
                    v_curr.select = True
                    try:
                        bpy.ops.mesh.shortest_path_select(use_fill=False)
                    except Exception:
                        traceback.print_exc()

                self._prev_idx = snap_idx

                v_co = self._bmesh_obj.matrix_world @ self._bm.verts[snap_idx].co
                m = make_marker(
                    f"M_NODE_{len(self._markers)}",
                    v_co,
                    0.003,
                    self._bmesh_obj,
                    (0, 1, 0, 1),
                    sticky=False,
                )
                m.show_in_front = True
                self._markers.append(m)

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            bpy.ops.mesh.select_all(action="DESELECT")

            indices = []
            mw_inv = self._bmesh_obj.matrix_world.inverted()
            for m in self._markers:
                loc_local = mw_inv @ m.location
                _, _, _, idx = self._bmesh_obj.closest_point_on_mesh(loc_local)
                poly = self._bmesh_obj.data.polygons[idx]
                bv = poly.vertices[0]
                bd = 1000.0
                for vi in poly.vertices:
                    d = (self._bmesh_obj.data.vertices[vi].co - loc_local).length
                    if d < bd:
                        bd = d
                        bv = vi
                indices.append(bv)

            bpy.ops.mesh.select_all(action="DESELECT")
            for i in range(len(indices)):
                idx = indices[i]
                if i == 0:
                    self._bm.verts[idx].select = True
                    self._bm.select_history.add(self._bm.verts[idx])
                else:
                    self._bm.verts[idx].select = True
                    bpy.ops.mesh.shortest_path_select(use_fill=False)
                    self._bm.select_history.add(self._bm.verts[idx])

            if len(indices) > 2:
                self._bm.verts[indices[0]].select = True
                bpy.ops.mesh.shortest_path_select(use_fill=False)

            bpy.ops.mesh.duplicate()
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")

            for m in self._markers:
                delete_object(m)

            sel = context.selected_objects
            margin_mesh = None
            for o in sel:
                if o != self._bmesh_obj:
                    margin_mesh = o
                    break

            if margin_mesh:
                ensure_active(margin_mesh)
                bpy.ops.object.convert(target="CURVE")
                tid = _resolve_margin_tooth_id(context.scene, self._bmesh_obj)
                if tid > 0:
                    margin_mesh.name = f"MARGIN_{self._bmesh_obj.name}_T{tid}"
                    margin_mesh["SMILE_MARGIN_TOOTH_ID"] = int(tid)
                else:
                    margin_mesh.name = f"MARGIN_{self._bmesh_obj.name}_T0"
                link_to_collection(margin_mesh, ensure_collection(COL_MARGINS))
                margin_mesh.data.bevel_depth = 0.002
                margin_mesh.data.bevel_resolution = 2
                margin_mesh.show_in_front = True
                mat_name = f"SMILE_Margin_Mat_{self._bmesh_obj.name}"
                mat = ensure_emission_material(
                    mat_name, MARGIN_NEON_RGBA, strength=12.0
                )
                margin_mesh.data.materials.append(mat)

            self.report({"INFO"}, "Margin Geodesic Trace Complete.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}


# ============================================================
# Section 2: SMILE_OT_draw_rough_margin (lines ~19393-19468)
# ============================================================


class SMILE_OT_draw_rough_margin(bpy.types.Operator):
    bl_idname = "smile.draw_rough_margin"
    bl_label = "Draw Rough Margin (Click Points)"
    bl_options = {"REGISTER", "UNDO"}

    _pts = None
    _curve_obj = None

    def invoke(self, context, event):
        self._pts = []

        cdata = bpy.data.curves.new("Rough_Margin", "CURVE")
        cdata.dimensions = "3D"
        self._curve_obj = bpy.data.objects.new("Rough_Margin_Obj", cdata)
        ensure_collection(COL_MARGINS).objects.link(self._curve_obj)
        self._curve_obj.show_in_front = True
        self._curve_obj.color = (0.20, 1.00, 0.10, 1.00)
        ensure_active(self._curve_obj)

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Click points AROUND the margin. Press ENTER to Close & Finish."
        )
        return {"RUNNING_MODAL"}

    def update_curve(self):
        cdata = self._curve_obj.data
        cdata.splines.clear()
        spline = cdata.splines.new("POLY")
        spline.points.add(len(self._pts) - 1)
        for i, p in enumerate(self._pts):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self._curve_obj:
                delete_object(self._curve_obj)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()

            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

            hit, loc, norm, face_i, obj, _ = context.scene.ray_cast(
                deps, ray_origin, ray_dir
            )

            if hit:
                self._pts.append(loc)
                self.update_curve()

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(self._pts) > 2:
                self._curve_obj.data.splines[0].use_cyclic_u = True
                self.report(
                    {"INFO"}, "Rough Margin Created. Now click 'Snap to Margin'."
                )
                return {"FINISHED"}
            else:
                delete_object(self._curve_obj)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}


# ============================================================
# Section 3: SMILE_OT_snap_margin_snake (lines ~19470-19619)
# ============================================================


class SMILE_OT_snap_margin_snake(bpy.types.Operator):
    bl_idname = "smile.snap_margin_snake"
    bl_label = "Snap to Margin (Snake)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        curve_obj = context.view_layer.objects.active
        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"ERROR"}, "Select the Rough Margin Curve.")
            return {"CANCELLED"}

        target_obj = None
        for o in context.selected_objects:
            if o.type == "MESH":
                target_obj = o
                break
        if not target_obj:
            self.report({"ERROR"}, "Select the Curve AND the Tooth Mesh.")
            return {"CANCELLED"}

        import numpy as np

        mesh = target_obj.data
        if not mesh.loop_triangles:
            mesh.calc_loop_triangles()

        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()

            ridge_points = []

            for v in bm.verts:
                neighbors = [e.other_vert(v) for e in v.link_edges]
                if not neighbors:
                    continue

                avg_n = Vector((0, 0, 0))
                for n in neighbors:
                    avg_n += n.normal
                if avg_n.length_squared > 1e-12:
                    avg_n.normalize()

                dot = v.normal.dot(avg_n)

                if dot < 0.95:
                    ridge_points.append(target_obj.matrix_world @ v.co)
        finally:
            bm.free()

        if not ridge_points:
            self.report({"WARNING"}, "No sharp edges found on mesh.")
            return {"CANCELLED"}

        kd = KDTree(len(ridge_points))
        for i, p in enumerate(ridge_points):
            kd.insert(p, i)
        kd.balance()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.curve.select_all(action="SELECT")
        bpy.ops.curve.subdivide(number_cuts=2)
        bpy.ops.object.mode_set(mode="OBJECT")

        pts = curve_world_points(curve_obj)
        new_pts = [p.copy() for p in pts]

        iterations = 20
        alpha = 0.5
        beta = 0.5

        mat_inv = curve_obj.matrix_world.inverted()

        for it in range(iterations):
            temp_pts = []
            n_pts = len(new_pts)

            for i in range(n_pts):
                p = new_pts[i]

                co, idx, dist = kd.find(p)
                attract_vec = Vector((0, 0, 0))
                if dist < 3.0:
                    attract_vec = (co - p) * alpha

                prev = new_pts[i - 1]
                next_p = new_pts[(i + 1) % n_pts]
                smooth_vec = ((prev + next_p) * 0.5 - p) * beta

                p_new = p + attract_vec + smooth_vec

                res, loc, norm, f_idx = target_obj.closest_point_on_mesh(
                    target_obj.matrix_world.inverted() @ p_new
                )
                if res:
                    p_new = target_obj.matrix_world @ loc

                temp_pts.append(p_new)

            new_pts = temp_pts

        spline = curve_obj.data.splines[0]
        if len(spline.points) == len(new_pts):
            for i, p in enumerate(new_pts):
                local_p = mat_inv @ p
                spline.points[i].co = (local_p.x, local_p.y, local_p.z, 1.0)
        else:
            curve_obj.data.splines.clear()
            spline = curve_obj.data.splines.new("POLY")
            spline.points.add(len(new_pts) - 1)
            for i, p in enumerate(new_pts):
                local_p = mat_inv @ p
                spline.points[i].co = (local_p.x, local_p.y, local_p.z, 1.0)
            spline.use_cyclic_u = True

        self.report({"INFO"}, "Snapped to Margin.")
        return {"FINISHED"}


# ============================================================
# Section 4: SMILE_OT_trace_magnetic_margin (lines ~19621-19786)
# ============================================================


class SMILE_OT_trace_magnetic_margin(bpy.types.Operator):
    bl_idname = "smile.trace_magnetic_margin"
    bl_label = "Magnetic Margin Tracer"
    bl_options = {"REGISTER", "UNDO"}

    _bm = None
    _bmesh_obj = None
    _pts = None
    _curve_obj = None
    _markers = None
    _kd = None

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the prep/tooth mesh.")
            return {"CANCELLED"}

        self._bmesh_obj = obj
        self._pts = []
        self._markers = []

        import bmesh

        self._bm = bmesh.new()
        self._bm.from_mesh(obj.data)
        self._bm.verts.ensure_lookup_table()

        self._kd = _build_vertex_kdtree_world(obj)

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Magnetic Trace: Click points. F=Close. Enter=Finish.")
        return {"RUNNING_MODAL"}

    def find_sharpest_in_radius(self, world_loc, radius=1.5):
        items = self._kd.find_range(world_loc, radius)
        if not items:
            return world_loc

        best_pos = world_loc
        max_score = -1.0

        scene = bpy.context.scene
        use_contrast = scene.smile_v2.margin_use_contrast
        contrast_weight = scene.smile_v2.margin_contrast_weight

        for co, index, dist in items:
            v = self._bm.verts[index]

            neighbors = [e.other_vert(v) for e in v.link_edges]
            if not neighbors:
                continue

            avg_n = Vector((0, 0, 0))
            for n in neighbors:
                avg_n += n.normal
            if avg_n.length_squared > 1e-12:
                avg_n.normalize()

            curv = 1.0 - v.normal.dot(avg_n)

            score = curv
            if use_contrast:
                contrast = compute_vertex_contrast(self._bmesh_obj, v, self._bm.verts)
                score = (1.0 - contrast_weight) * curv + contrast_weight * contrast

            if score > max_score:
                max_score = score
                best_pos = self._bmesh_obj.matrix_world @ v.co

        return best_pos

    def update_visuals(self):
        if not self._curve_obj:
            cdata = bpy.data.curves.new("Temp_Margin", "CURVE")
            cdata.dimensions = "3D"
            self._curve_obj = bpy.data.objects.new("Temp_Margin_Obj", cdata)
            ensure_collection(COL_MARGINS).objects.link(self._curve_obj)
            self._curve_obj.show_in_front = True

        cdata = self._curve_obj.data
        cdata.splines.clear()
        spline = cdata.splines.new("POLY")
        spline.points.add(len(self._pts) - 1)
        for i, p in enumerate(self._pts):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self._curve_obj:
                delete_object(self._curve_obj)
            for m in self._markers:
                delete_object(m)
            self._bm.free()
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._bmesh_obj)
            if hit:
                raw_loc, _, _ = hit
                snap_loc = self.find_sharpest_in_radius(raw_loc)
                self._pts.append(snap_loc)

                m = make_marker(
                    f"M_PT_{len(self._pts)}",
                    snap_loc,
                    0.003,
                    self._bmesh_obj,
                    (1, 0, 0, 1),
                    sticky=False,
                )
                m.show_in_front = True
                self._markers.append(m)

                self.update_visuals()
                context.area.tag_redraw()

        if event.type == "F" and event.value == "PRESS":
            if self._curve_obj and self._curve_obj.data.splines:
                self._curve_obj.data.splines[0].use_cyclic_u = True
                context.area.tag_redraw()

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._curve_obj:
                tid = _resolve_margin_tooth_id(context.scene, self._bmesh_obj)
                if tid > 0:
                    self._curve_obj.name = f"MARGIN_{self._bmesh_obj.name}_T{tid}"
                    self._curve_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)
                else:
                    self._curve_obj.name = f"MARGIN_{self._bmesh_obj.name}_T0"
                self._curve_obj.data.bevel_depth = 0.0003
                self._curve_obj.data.bevel_resolution = 2
                self._curve_obj.show_in_front = True

                mat_name = f"SMILE_Margin_Mat_{self._bmesh_obj.name}"
                mat = ensure_emission_material(
                    mat_name, MARGIN_NEON_RGBA, strength=12.0
                )
                self._curve_obj.data.materials.append(mat)

                if self._curve_obj.data.splines:
                    self._curve_obj.data.splines[0].use_cyclic_u = True

            for m in self._markers:
                delete_object(m)
            self._bm.free()

            self.report({"INFO"}, "Margin curve created.")
            return {"FINISHED"}

        return {"PASS_THROUGH"}


# ============================================================
# Section 5: SMILE_OT_finish_margin_draw (lines ~19788-20024)
# ============================================================


class SMILE_OT_finish_margin_draw(bpy.types.Operator):
    bl_idname = "smile.finish_margin_draw"
    bl_label = "Finish Margin & Create Curve"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if (
            "SMILE_LEGACY_MARGIN_POINTS" in context.scene
            and "SMILE_LEGACY_MARGIN_MESH" in context.scene
        ):
            mesh_name = context.scene["SMILE_LEGACY_MARGIN_MESH"]
            obj = bpy.data.objects.get(mesh_name)

            if not obj:
                self.report({"ERROR"}, "Original mesh not found.")
                return {"CANCELLED"}

            points_data = context.scene["SMILE_LEGACY_MARGIN_POINTS"]
            points = [Vector(p) for p in points_data]
            tid = _resolve_margin_tooth_id(context.scene, obj)

            if tid > 0:
                curve_name = f"MARGIN_{obj.name}_T{tid}"
                curve_names_to_delete = [
                    curve_name,
                    f"MARGIN_{obj.name}_T{tid}_Curve",
                    f"MARGIN_{obj.name}_Curve",
                ]
            else:
                curve_name = f"MARGIN_{obj.name}_T0"
                curve_names_to_delete = [curve_name, f"MARGIN_{obj.name}_Curve"]
            for cn in curve_names_to_delete:
                old_curve = bpy.data.objects.get(cn)
                if old_curve:
                    delete_object(old_curve)

            cdata = bpy.data.curves.new(curve_name, "CURVE")
            cdata.dimensions = "3D"
            spline = cdata.splines.new("POLY")
            spline.points.add(len(points) - 1)

            for i, pt in enumerate(points):
                spline.points[i].co = (pt.x, pt.y, pt.z, 1.0)

            spline.use_cyclic_u = True

            curve_obj = bpy.data.objects.new(curve_name, cdata)
            ensure_collection(COL_MARGINS).objects.link(curve_obj)
            curve_obj.show_in_front = True
            if tid > 0:
                curve_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)

            mat = ensure_emission_material(
                "SMILE_Margin_Final", MARGIN_NEON_RGBA, strength=12.0
            )
            curve_obj.data.materials.append(mat)
            curve_obj.data.bevel_depth = 0.005

            margin_data = {
                "control_points": [[p.x, p.y, p.z] for p in points],
                "refined_points": [[p.x, p.y, p.z] for p in points],
                "is_finalized": True,
                "is_closed": True,
                "mode": "MANUAL",
            }
            set_margin_data(
                context.scene, obj, margin_data, tooth_id=tid if tid > 0 else None
            )

            del context.scene["SMILE_LEGACY_MARGIN_POINTS"]
            del context.scene["SMILE_LEGACY_MARGIN_MESH"]

            self.report(
                {"INFO"}, f"Margin created with {len(points)} points (Pen Mode)."
            )
            return {"FINISHED"}

        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report(
                {"ERROR"},
                "Select a mesh object first, or use 'Start' to draw margin first.",
            )
            return {"CANCELLED"}
        tid = _resolve_margin_tooth_id(context.scene, obj)

        if obj.mode != "EDIT":
            self.report(
                {"ERROR"},
                "No pen-drawn margin found. Use 'Start' button first to draw margin.",
            )
            return {"CANCELLED"}

        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts = [v for v in bm.verts if v.select]

        if len(selected_verts) < 3:
            self.report(
                {"ERROR"},
                "No pen-drawn margin found. Use 'Start' button first to draw margin.",
            )
            return {"CANCELLED"}

        vg = obj.vertex_groups.get("SMILE_MARGIN")
        if not vg:
            vg = obj.vertex_groups.new(name="SMILE_MARGIN")

        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type="SELECTED")

        bpy.ops.object.mode_set(mode="OBJECT")

        margin_mesh = context.selected_objects[0]
        if margin_mesh == obj:
            margin_mesh = (
                context.selected_objects[1]
                if len(context.selected_objects) > 1
                else context.selected_objects[0]
            )

        if margin_mesh == obj:
            self.report({"ERROR"}, "Separation failed.")
            return {"CANCELLED"}

        margin_mesh.name = f"MARGIN_{obj.name}_Mesh"

        ensure_active(margin_mesh)
        bpy.ops.object.convert(target="CURVE")
        curve_obj = context.active_object
        if tid > 0:
            curve_obj.name = f"MARGIN_{obj.name}_T{tid}"
            curve_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)
        else:
            curve_obj.name = f"MARGIN_{obj.name}_T0"

        link_to_collection(curve_obj, ensure_collection(COL_MARGINS))

        ensure_active(obj)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.object.vertex_group_assign_new()
        obj.vertex_groups.active.name = "SMILE_MARGIN"

        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")

        margin_obj = context.selected_objects[0]
        if margin_obj == obj and len(context.selected_objects) > 1:
            margin_obj = context.selected_objects[1]

        if margin_obj == obj:
            pass
        else:
            ensure_active(margin_obj)
            bpy.ops.object.convert(target="CURVE")
            if tid > 0:
                margin_obj.name = f"MARGIN_{obj.name}_T{tid}"
                margin_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)
            else:
                margin_obj.name = f"MARGIN_{obj.name}_T0"
            link_to_collection(margin_obj, ensure_collection(COL_MARGINS))

            if margin_obj.data.splines:
                for spl in margin_obj.data.splines:
                    spl.use_cyclic_u = True

        ensure_active(obj)
        self.report({"INFO"}, "Margin defined and converted to Curve.")
        return {"FINISHED"}


# ============================================================
# Section 1: SMILE_OT_trace_geodesic_magnet (lines ~19091-19390)
# ============================================================


class SMILE_OT_trace_geodesic_magnet(bpy.types.Operator):
    bl_idname = "smile.trace_geodesic_magnet"
    bl_label = "Magnetic Geodesic Tracer"
    bl_options = {"REGISTER", "UNDO"}

    _bm = None
    _bmesh_obj = None
    _prev_idx = -1
    _curve_obj = None
    _markers = []
    _kd = None

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the mesh.")
            return {"CANCELLED"}

        self._bmesh_obj = obj
        self._markers = []
        self._prev_idx = -1

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")

        import bmesh

        self._bm = bmesh.from_edit_mesh(obj.data)
        self._bm.verts.ensure_lookup_table()

        self._kd = KDTree(len(self._bm.verts))
        mw = obj.matrix_world
        for i, v in enumerate(self._bm.verts):
            self._kd.insert(mw @ v.co, i)
        self._kd.balance()

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Click to trace margin. Auto-snaps to ridge & follows surface."
        )
        return {"RUNNING_MODAL"}

    def find_sharpest_idx(self, world_loc, radius=1.5):
        items = self._kd.find_range(world_loc, radius)
        if not items:
            return -1

        best_idx = -1
        max_score = -1.0

        for co, index, dist in items:
            v = self._bm.verts[index]
            neighbors = [e.other_vert(v) for e in v.link_edges]
            if not neighbors:
                continue
            avg_n = Vector((0, 0, 0))
            for n in neighbors:
                avg_n += n.normal
            if avg_n.length_squared > 1e-12:
                avg_n.normalize()
            curv = 1.0 - v.normal.dot(avg_n)

            if curv > max_score:
                max_score = curv
                best_idx = index

        return best_idx

    def update_curve_visual(self):
        pass

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.alt:
            return {"PASS_THROUGH"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            for m in self._markers:
                delete_object(m)
            bpy.ops.object.mode_set(mode="OBJECT")
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._bmesh_obj)
            if hit:
                raw_loc, _, _ = hit
                snap_idx = self.find_sharpest_idx(raw_loc)
                if snap_idx == -1:
                    return {"RUNNING_MODAL"}

                if self._prev_idx != -1:
                    bpy.ops.mesh.select_all(action="DESELECT")
                    self._bm.verts.ensure_lookup_table()
                    v_prev = self._bm.verts[self._prev_idx]
                    v_curr = self._bm.verts[snap_idx]
                    self._bm.select_history.add(v_prev)
                    v_prev.select = True
                    v_curr.select = True
                    try:
                        bpy.ops.mesh.shortest_path_select(use_fill=False)
                    except Exception:
                        traceback.print_exc()

                self._prev_idx = snap_idx

                v_co = self._bmesh_obj.matrix_world @ self._bm.verts[snap_idx].co
                m = make_marker(
                    f"M_NODE_{len(self._markers)}",
                    v_co,
                    0.003,
                    self._bmesh_obj,
                    (0, 1, 0, 1),
                    sticky=False,
                )
                m.show_in_front = True
                self._markers.append(m)

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            bpy.ops.mesh.select_all(action="DESELECT")

            indices = []
            mw_inv = self._bmesh_obj.matrix_world.inverted()
            for m in self._markers:
                loc_local = mw_inv @ m.location
                _, _, _, idx = self._bmesh_obj.closest_point_on_mesh(loc_local)
                poly = self._bmesh_obj.data.polygons[idx]
                bv = poly.vertices[0]
                bd = 1000.0
                for vi in poly.vertices:
                    d = (self._bmesh_obj.data.vertices[vi].co - loc_local).length
                    if d < bd:
                        bd = d
                        bv = vi
                indices.append(bv)

            bpy.ops.mesh.select_all(action="DESELECT")
            for i in range(len(indices)):
                idx = indices[i]
                if i == 0:
                    self._bm.verts[idx].select = True
                    self._bm.select_history.add(self._bm.verts[idx])
                else:
                    self._bm.verts[idx].select = True
                    bpy.ops.mesh.shortest_path_select(use_fill=False)
                    self._bm.select_history.add(self._bm.verts[idx])

            if len(indices) > 2:
                self._bm.verts[indices[0]].select = True
                bpy.ops.mesh.shortest_path_select(use_fill=False)

            bpy.ops.mesh.duplicate()
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")

            for m in self._markers:
                delete_object(m)

            sel = context.selected_objects
            margin_mesh = None
            for o in sel:
                if o != self._bmesh_obj:
                    margin_mesh = o
                    break

            if margin_mesh:
                ensure_active(margin_mesh)
                bpy.ops.object.convert(target="CURVE")
                tid = _resolve_margin_tooth_id(context.scene, self._bmesh_obj)
                if tid > 0:
                    margin_mesh.name = f"MARGIN_{self._bmesh_obj.name}_T{tid}"
                    margin_mesh["SMILE_MARGIN_TOOTH_ID"] = int(tid)
                else:
                    margin_mesh.name = f"MARGIN_{self._bmesh_obj.name}_T0"
                link_to_collection(margin_mesh, ensure_collection(COL_MARGINS))
                margin_mesh.data.bevel_depth = 0.002
                margin_mesh.data.bevel_resolution = 2
                margin_mesh.show_in_front = True
                mat_name = f"SMILE_Margin_Mat_{self._bmesh_obj.name}"
                mat = ensure_emission_material(
                    mat_name, MARGIN_NEON_RGBA, strength=12.0
                )
                margin_mesh.data.materials.append(mat)

            self.report({"INFO"}, "Margin Geodesic Trace Complete.")
            return {"FINISHED"}

        return {"RUNNING_MODAL"}


# ============================================================
# Section 2: SMILE_OT_draw_rough_margin (lines ~19393-19468)
# ============================================================


class SMILE_OT_draw_rough_margin(bpy.types.Operator):
    bl_idname = "smile.draw_rough_margin"
    bl_label = "Draw Rough Margin (Click Points)"
    bl_options = {"REGISTER", "UNDO"}

    _pts = None
    _curve_obj = None

    def invoke(self, context, event):
        self._pts = []

        cdata = bpy.data.curves.new("Rough_Margin", "CURVE")
        cdata.dimensions = "3D"
        self._curve_obj = bpy.data.objects.new("Rough_Margin_Obj", cdata)
        ensure_collection(COL_MARGINS).objects.link(self._curve_obj)
        self._curve_obj.show_in_front = True
        self._curve_obj.color = (0.20, 1.00, 0.10, 1.00)
        ensure_active(self._curve_obj)

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"}, "Click points AROUND the margin. Press ENTER to Close & Finish."
        )
        return {"RUNNING_MODAL"}

    def update_curve(self):
        cdata = self._curve_obj.data
        cdata.splines.clear()
        spline = cdata.splines.new("POLY")
        spline.points.add(len(self._pts) - 1)
        for i, p in enumerate(self._pts):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self._curve_obj:
                delete_object(self._curve_obj)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            v3d = _view3d_utils()

            deps = context.evaluated_depsgraph_get()
            ray_origin = v3d.region_2d_to_origin_3d(region, rv3d, coord)
            ray_dir = v3d.region_2d_to_vector_3d(region, rv3d, coord).normalized()

            hit, loc, norm, face_i, obj, _ = context.scene.ray_cast(
                deps, ray_origin, ray_dir
            )

            if hit:
                self._pts.append(loc)
                self.update_curve()

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(self._pts) > 2:
                self._curve_obj.data.splines[0].use_cyclic_u = True
                self.report(
                    {"INFO"}, "Rough Margin Created. Now click 'Snap to Margin'."
                )
                return {"FINISHED"}
            else:
                delete_object(self._curve_obj)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}


# ============================================================
# Section 3: SMILE_OT_snap_margin_snake (lines ~19470-19619)
# ============================================================


class SMILE_OT_snap_margin_snake(bpy.types.Operator):
    bl_idname = "smile.snap_margin_snake"
    bl_label = "Snap to Margin (Snake)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        curve_obj = context.view_layer.objects.active
        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"ERROR"}, "Select the Rough Margin Curve.")
            return {"CANCELLED"}

        target_obj = None
        for o in context.selected_objects:
            if o.type == "MESH":
                target_obj = o
                break
        if not target_obj:
            self.report({"ERROR"}, "Select the Curve AND the Tooth Mesh.")
            return {"CANCELLED"}

        import numpy as np

        mesh = target_obj.data
        if not mesh.loop_triangles:
            mesh.calc_loop_triangles()

        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()

            ridge_points = []

            for v in bm.verts:
                neighbors = [e.other_vert(v) for e in v.link_edges]
                if not neighbors:
                    continue

                avg_n = Vector((0, 0, 0))
                for n in neighbors:
                    avg_n += n.normal
                if avg_n.length_squared > 1e-12:
                    avg_n.normalize()

                dot = v.normal.dot(avg_n)

                if dot < 0.95:
                    ridge_points.append(target_obj.matrix_world @ v.co)
        finally:
            bm.free()

        if not ridge_points:
            self.report({"WARNING"}, "No sharp edges found on mesh.")
            return {"CANCELLED"}

        kd = KDTree(len(ridge_points))
        for i, p in enumerate(ridge_points):
            kd.insert(p, i)
        kd.balance()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.curve.select_all(action="SELECT")
        bpy.ops.curve.subdivide(number_cuts=2)
        bpy.ops.object.mode_set(mode="OBJECT")

        pts = curve_world_points(curve_obj)
        new_pts = [p.copy() for p in pts]

        iterations = 20
        alpha = 0.5
        beta = 0.5

        mat_inv = curve_obj.matrix_world.inverted()

        for it in range(iterations):
            temp_pts = []
            n_pts = len(new_pts)

            for i in range(n_pts):
                p = new_pts[i]

                co, idx, dist = kd.find(p)
                attract_vec = Vector((0, 0, 0))
                if dist < 3.0:
                    attract_vec = (co - p) * alpha

                prev = new_pts[i - 1]
                next_p = new_pts[(i + 1) % n_pts]
                smooth_vec = ((prev + next_p) * 0.5 - p) * beta

                p_new = p + attract_vec + smooth_vec

                res, loc, norm, f_idx = target_obj.closest_point_on_mesh(
                    target_obj.matrix_world.inverted() @ p_new
                )
                if res:
                    p_new = target_obj.matrix_world @ loc

                temp_pts.append(p_new)

            new_pts = temp_pts

        spline = curve_obj.data.splines[0]
        if len(spline.points) == len(new_pts):
            for i, p in enumerate(new_pts):
                local_p = mat_inv @ p
                spline.points[i].co = (local_p.x, local_p.y, local_p.z, 1.0)
        else:
            curve_obj.data.splines.clear()
            spline = curve_obj.data.splines.new("POLY")
            spline.points.add(len(new_pts) - 1)
            for i, p in enumerate(new_pts):
                local_p = mat_inv @ p
                spline.points[i].co = (local_p.x, local_p.y, local_p.z, 1.0)
            spline.use_cyclic_u = True

        self.report({"INFO"}, "Snapped to Margin.")
        return {"FINISHED"}


# ============================================================
# Section 4: SMILE_OT_trace_magnetic_margin (lines ~19621-19786)
# ============================================================


class SMILE_OT_trace_magnetic_margin(bpy.types.Operator):
    bl_idname = "smile.trace_magnetic_margin"
    bl_label = "Magnetic Margin Tracer"
    bl_options = {"REGISTER", "UNDO"}

    _bm = None
    _bmesh_obj = None
    _pts = None
    _curve_obj = None
    _markers = None
    _kd = None

    def invoke(self, context, event):
        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Select the prep/tooth mesh.")
            return {"CANCELLED"}

        self._bmesh_obj = obj
        self._pts = []
        self._markers = []

        import bmesh

        self._bm = bmesh.new()
        self._bm.from_mesh(obj.data)
        self._bm.verts.ensure_lookup_table()

        self._kd = _build_vertex_kdtree_world(obj)

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Magnetic Trace: Click points. F=Close. Enter=Finish.")
        return {"RUNNING_MODAL"}

    def find_sharpest_in_radius(self, world_loc, radius=1.5):
        items = self._kd.find_range(world_loc, radius)
        if not items:
            return world_loc

        best_pos = world_loc
        max_score = -1.0

        scene = bpy.context.scene
        use_contrast = scene.smile_v2.margin_use_contrast
        contrast_weight = scene.smile_v2.margin_contrast_weight

        for co, index, dist in items:
            v = self._bm.verts[index]

            neighbors = [e.other_vert(v) for e in v.link_edges]
            if not neighbors:
                continue

            avg_n = Vector((0, 0, 0))
            for n in neighbors:
                avg_n += n.normal
            if avg_n.length_squared > 1e-12:
                avg_n.normalize()

            curv = 1.0 - v.normal.dot(avg_n)

            score = curv
            if use_contrast:
                contrast = compute_vertex_contrast(self._bmesh_obj, v, self._bm.verts)
                score = (1.0 - contrast_weight) * curv + contrast_weight * contrast

            if score > max_score:
                max_score = score
                best_pos = self._bmesh_obj.matrix_world @ v.co

        return best_pos

    def update_visuals(self):
        if not self._curve_obj:
            cdata = bpy.data.curves.new("Temp_Margin", "CURVE")
            cdata.dimensions = "3D"
            self._curve_obj = bpy.data.objects.new("Temp_Margin_Obj", cdata)
            ensure_collection(COL_MARGINS).objects.link(self._curve_obj)
            self._curve_obj.show_in_front = True

        cdata = self._curve_obj.data
        cdata.splines.clear()
        spline = cdata.splines.new("POLY")
        spline.points.add(len(self._pts) - 1)
        for i, p in enumerate(self._pts):
            spline.points[i].co = (p.x, p.y, p.z, 1.0)

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            if self._curve_obj:
                delete_object(self._curve_obj)
            for m in self._markers:
                delete_object(m)
            self._bm.free()
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit = raycast_from_mouse_to_target(context, event, self._bmesh_obj)
            if hit:
                raw_loc, _, _ = hit
                snap_loc = self.find_sharpest_in_radius(raw_loc)
                self._pts.append(snap_loc)

                m = make_marker(
                    f"M_PT_{len(self._pts)}",
                    snap_loc,
                    0.003,
                    self._bmesh_obj,
                    (1, 0, 0, 1),
                    sticky=False,
                )
                m.show_in_front = True
                self._markers.append(m)

                self.update_visuals()
                context.area.tag_redraw()

        if event.type == "F" and event.value == "PRESS":
            if self._curve_obj and self._curve_obj.data.splines:
                self._curve_obj.data.splines[0].use_cyclic_u = True
                context.area.tag_redraw()

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._curve_obj:
                tid = _resolve_margin_tooth_id(context.scene, self._bmesh_obj)
                if tid > 0:
                    self._curve_obj.name = f"MARGIN_{self._bmesh_obj.name}_T{tid}"
                    self._curve_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)
                else:
                    self._curve_obj.name = f"MARGIN_{self._bmesh_obj.name}_T0"
                self._curve_obj.data.bevel_depth = 0.0003
                self._curve_obj.data.bevel_resolution = 2
                self._curve_obj.show_in_front = True

                mat_name = f"SMILE_Margin_Mat_{self._bmesh_obj.name}"
                mat = ensure_emission_material(
                    mat_name, MARGIN_NEON_RGBA, strength=12.0
                )
                self._curve_obj.data.materials.append(mat)

                if self._curve_obj.data.splines:
                    self._curve_obj.data.splines[0].use_cyclic_u = True

            for m in self._markers:
                delete_object(m)
            self._bm.free()

            self.report({"INFO"}, "Margin curve created.")
            return {"FINISHED"}

        return {"PASS_THROUGH"}


# ============================================================
# Section 5: SMILE_OT_finish_margin_draw (lines ~19788-20024)
# ============================================================


class SMILE_OT_finish_margin_draw(bpy.types.Operator):
    bl_idname = "smile.finish_margin_draw"
    bl_label = "Finish Margin & Create Curve"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if (
            "SMILE_LEGACY_MARGIN_POINTS" in context.scene
            and "SMILE_LEGACY_MARGIN_MESH" in context.scene
        ):
            mesh_name = context.scene["SMILE_LEGACY_MARGIN_MESH"]
            obj = bpy.data.objects.get(mesh_name)

            if not obj:
                self.report({"ERROR"}, "Original mesh not found.")
                return {"CANCELLED"}

            points_data = context.scene["SMILE_LEGACY_MARGIN_POINTS"]
            points = [Vector(p) for p in points_data]
            tid = _resolve_margin_tooth_id(context.scene, obj)

            if tid > 0:
                curve_name = f"MARGIN_{obj.name}_T{tid}"
                curve_names_to_delete = [
                    curve_name,
                    f"MARGIN_{obj.name}_T{tid}_Curve",
                    f"MARGIN_{obj.name}_Curve",
                ]
            else:
                curve_name = f"MARGIN_{obj.name}_T0"
                curve_names_to_delete = [curve_name, f"MARGIN_{obj.name}_Curve"]
            for cn in curve_names_to_delete:
                old_curve = bpy.data.objects.get(cn)
                if old_curve:
                    delete_object(old_curve)

            cdata = bpy.data.curves.new(curve_name, "CURVE")
            cdata.dimensions = "3D"
            spline = cdata.splines.new("POLY")
            spline.points.add(len(points) - 1)

            for i, pt in enumerate(points):
                spline.points[i].co = (pt.x, pt.y, pt.z, 1.0)

            spline.use_cyclic_u = True

            curve_obj = bpy.data.objects.new(curve_name, cdata)
            ensure_collection(COL_MARGINS).objects.link(curve_obj)
            curve_obj.show_in_front = True
            if tid > 0:
                curve_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)

            mat = ensure_emission_material(
                "SMILE_Margin_Final", MARGIN_NEON_RGBA, strength=12.0
            )
            curve_obj.data.materials.append(mat)
            curve_obj.data.bevel_depth = 0.005

            margin_data = {
                "control_points": [[p.x, p.y, p.z] for p in points],
                "refined_points": [[p.x, p.y, p.z] for p in points],
                "is_finalized": True,
                "is_closed": True,
                "mode": "MANUAL",
            }
            set_margin_data(
                context.scene, obj, margin_data, tooth_id=tid if tid > 0 else None
            )

            del context.scene["SMILE_LEGACY_MARGIN_POINTS"]
            del context.scene["SMILE_LEGACY_MARGIN_MESH"]

            self.report(
                {"INFO"}, f"Margin created with {len(points)} points (Pen Mode)."
            )
            return {"FINISHED"}

        obj = context.view_layer.objects.active
        if not obj or obj.type != "MESH":
            self.report(
                {"ERROR"},
                "Select a mesh object first, or use 'Start' to draw margin first.",
            )
            return {"CANCELLED"}
        tid = _resolve_margin_tooth_id(context.scene, obj)

        if obj.mode != "EDIT":
            self.report(
                {"ERROR"},
                "No pen-drawn margin found. Use 'Start' button first to draw margin.",
            )
            return {"CANCELLED"}

        bm = bmesh.from_edit_mesh(obj.data)
        selected_verts = [v for v in bm.verts if v.select]

        if len(selected_verts) < 3:
            self.report(
                {"ERROR"},
                "No pen-drawn margin found. Use 'Start' button first to draw margin.",
            )
            return {"CANCELLED"}

        vg = obj.vertex_groups.get("SMILE_MARGIN")
        if not vg:
            vg = obj.vertex_groups.new(name="SMILE_MARGIN")

        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type="SELECTED")

        bpy.ops.object.mode_set(mode="OBJECT")

        margin_mesh = context.selected_objects[0]
        if margin_mesh == obj:
            margin_mesh = (
                context.selected_objects[1]
                if len(context.selected_objects) > 1
                else context.selected_objects[0]
            )

        if margin_mesh == obj:
            self.report({"ERROR"}, "Separation failed.")
            return {"CANCELLED"}

        margin_mesh.name = f"MARGIN_{obj.name}_Mesh"

        ensure_active(margin_mesh)
        bpy.ops.object.convert(target="CURVE")
        curve_obj = context.active_object
        if tid > 0:
            curve_obj.name = f"MARGIN_{obj.name}_T{tid}"
            curve_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)
        else:
            curve_obj.name = f"MARGIN_{obj.name}_T0"

        link_to_collection(curve_obj, ensure_collection(COL_MARGINS))

        ensure_active(obj)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.object.vertex_group_assign_new()
        obj.vertex_groups.active.name = "SMILE_MARGIN"

        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")

        margin_obj = context.selected_objects[0]
        if margin_obj == obj and len(context.selected_objects) > 1:
            margin_obj = context.selected_objects[1]

        if margin_obj == obj:
            pass
        else:
            ensure_active(margin_obj)
            bpy.ops.object.convert(target="CURVE")
            if tid > 0:
                margin_obj.name = f"MARGIN_{obj.name}_T{tid}"
                margin_obj["SMILE_MARGIN_TOOTH_ID"] = int(tid)
            else:
                margin_obj.name = f"MARGIN_{obj.name}_T0"
            link_to_collection(margin_obj, ensure_collection(COL_MARGINS))

            if margin_obj.data.splines:
                for spl in margin_obj.data.splines:
                    spl.use_cyclic_u = True

        ensure_active(obj)
        self.report({"INFO"}, "Margin defined and converted to Curve.")
        return {"FINISHED"}
