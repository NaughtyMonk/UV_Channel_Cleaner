bl_info = {
    "name": "UV Channel Cleaner",
    "author": "NaughtyMonk",
    "version": (1, 3),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > UV Tools",
    "description": "Clean up UV channels by material or loose parts. Keeps the best one, deletes the rest (with exceptions).",
    "category": "UV"
}

import bpy
import bmesh
import mathutils

# === PROPERTIES ===
class UVToolProps(bpy.types.PropertyGroup):
    target_uv_name: bpy.props.StringProperty(name="Final UV Name", default="UVMap")
    keep_uv_list: bpy.props.StringProperty(name="Keep UV Channels (comma-separated)", default="")
    log: bpy.props.StringProperty(name="Log", default="")
    merge_threshold: bpy.props.FloatProperty(name="Merge Distance", default=0.0001, min=0.0, precision=6)

# === PANELS ===
class UV_PT_ToolsPanel(bpy.types.Panel):
    bl_label = "UV Tools"
    bl_idname = "UV_PT_ToolsPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'UV Tools'

    def draw(self, context):
        layout = self.layout
        layout.label(text="UV Cleanup Toolkit")

class UV_PT_ByMaterialsPanel(bpy.types.Panel):
    bl_label = "UV Merge"
    bl_idname = "UV_PT_ByMaterialsPanel"
    bl_parent_id = "UV_PT_ToolsPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'UV Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.uv_tools_props

        layout.prop(props, "target_uv_name")
        layout.prop(props, "keep_uv_list")
        layout.operator("uvtools.clean_uv_by_materials", icon="UV")
        layout.operator("uvtools.clean_uv_by_loose_parts", icon="GROUP_VERTEX")

        # layout.prop(props, "merge_threshold")
        # layout.operator("uvtools.merge_objects", icon="AUTOMERGE_ON")
        # layout.operator("uvtools.export_log", icon="FILE_TICK")

        # if props.log:
        #     layout.label(text="Log:")
        #     for line in props.log.split("\n"):
        #         layout.label(text=line[:80])

# === OPERATOR: CLEAN BY MATERIALS ===
class UV_OT_CleanByMaterials(bpy.types.Operator):
    bl_idname = "uvtools.clean_uv_by_materials"
    bl_label = "Clean UV Channels by Materials"

    def execute(self, context):
        props = context.scene.uv_tools_props
        final_name = props.target_uv_name
        keep_uv_names = [n.strip() for n in props.keep_uv_list.split(",") if n.strip()]
        selected_objects = context.selected_objects.copy()

        for obj in selected_objects:
            if obj.type != 'MESH':
                continue

            for i, slot in enumerate(obj.material_slots):
                if not slot.material:
                    continue

                bpy.ops.object.select_all(action='DESELECT')
                context.view_layer.objects.active = obj
                obj.select_set(True)

                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.object.mode_set(mode='OBJECT')

                for poly in obj.data.polygons:
                    if poly.material_index == i:
                        poly.select = True

                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.separate(type='SELECTED')
                bpy.ops.object.mode_set(mode='OBJECT')

                new_objs = [o for o in context.selected_objects if o != obj]
                for new_obj in new_objs:
                    clean_uv_channels(new_obj, final_name, keep_uv_names)

            if obj.data and len(obj.data.polygons) == 0:
                bpy.data.objects.remove(obj)

        return {'FINISHED'}

# === OPERATOR: CLEAN BY LOOSE PARTS ===
class UV_OT_CleanByLooseParts(bpy.types.Operator):
    bl_idname = "uvtools.clean_uv_by_loose_parts"
    bl_label = "Split & Clean by Loose Parts"

    def execute(self, context):
        props = context.scene.uv_tools_props
        final_name = props.target_uv_name
        keep_uv_names = [n.strip() for n in props.keep_uv_list.split(",") if n.strip()]

        collection = bpy.data.collections.get("UV_Merge")
        if not collection:
            collection = bpy.data.collections.new("UV_Merge")
            context.scene.collection.children.link(collection)

        original_objs = [o for o in context.selected_objects if o.type == 'MESH']
        bpy.ops.object.select_all(action='DESELECT')

        for obj in original_objs:
            obj.select_set(True)
            context.view_layer.objects.active = obj

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='LOOSE')
            bpy.ops.object.mode_set(mode='OBJECT')

            separated_objs = [o for o in context.selected_objects if o != obj]

            for part in separated_objs:
                if part.name not in collection.objects:
                    collection.objects.link(part)
                clean_uv_channels(part, final_name, keep_uv_names)

            if obj.data and len(obj.data.polygons) > 0:
                if obj.name not in collection.objects:
                    collection.objects.link(obj)
                clean_uv_channels(obj, final_name, keep_uv_names)
            else:
                bpy.data.objects.remove(obj)

        return {'FINISHED'}

# === CLEAN UV CHANNELS ===

from mathutils import geometry

# === Реальное пересечение UV треугольников ===
def get_uv_triangles(bm, uv_layer):
    tris = []
    for face in bm.faces:
        uvs = [loop[uv_layer].uv.copy() for loop in face.loops]
        if len(uvs) < 3:
            continue
        # Триангуляция N-угольников (на случай не-треугольных)
        for i in range(1, len(uvs) - 1):
            tris.append((uvs[0], uvs[i], uvs[i + 1]))
    return tris

def count_uv_triangle_overlaps(tris):
    overlaps = 0
    for i in range(len(tris)):
        for j in range(i + 1, len(tris)):
            a1, a2, a3 = tris[i]
            b1, b2, b3 = tris[j]
            try:
                if geometry.intersect_tri_tri_2d(a1, a2, a3, b1, b2, b3):
                    overlaps += 1
            except:
                continue
    return overlaps


def clean_uv_channels(obj, final_uv_name, keep_uvs):
    mesh = obj.data
    uv_layers = mesh.uv_layers
    if not uv_layers:
        return "No UV layers found."

    best_score = float('inf')
    best_uv_name = None

    for uv in uv_layers:
        if uv.name in keep_uvs:
            continue
        score = calc_uv_score(obj, uv.name)
        if score < best_score and score != float('inf'):
            best_score = score
            best_uv_name = uv.name

    if best_uv_name and best_uv_name != final_uv_name:
        uv_layers[best_uv_name].name = final_uv_name

    keep_names = [final_uv_name] + keep_uvs
    to_remove = [uv.name for uv in uv_layers if uv.name not in keep_names]
    for name in to_remove:
        uv_layers.remove(uv_layers[name])

    return f"Kept: {final_uv_name}, removed: {', '.join(to_remove)}"

# === SCORING ===
def calc_uv_score(obj, uv_name):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.get(uv_name)

    if not uv_layer:
        bm.free()
        return float('inf')

    total_area_3d = 0.0
    total_area_uv = 0.0
    total_stretch = 0.0
    total_angle_diff = 0.0
    uv_coords = []
    edge_count = 0
    angle_count = 0

    for face in bm.faces:
        loops = face.loops
        if len(loops) < 3:
            continue

        verts = [loop.vert.co for loop in loops]
        uvs = [loop[uv_layer].uv for loop in loops]
        area_3d = face.calc_area()
        total_area_3d += area_3d

        try:
            tri_uv = [mathutils.Vector((uv[0], uv[1])) for uv in uvs]
            area_uv = mathutils.geometry.area_tri(tri_uv[0], tri_uv[1], tri_uv[2])
            total_area_uv += abs(area_uv)
            uv_coords.extend(tri_uv)
        except:
            continue

        for i in range(len(loops)):
            v1 = verts[i]
            v2 = verts[(i + 1) % len(loops)]
            d3d = (v2 - v1).length
            uv1 = uvs[i]
            uv2 = uvs[(i + 1) % len(loops)]
            duv = (uv2 - uv1).length
            if d3d > 0:
                stretch = abs((duv / d3d) - 1)
                total_stretch += stretch
                edge_count += 1

        if len(verts) == 3:
            try:
                a = (verts[1] - verts[0]).normalized()
                b = (verts[2] - verts[0]).normalized()
                angle3d = a.angle(b)
                auv = (uvs[1] - uvs[0]).normalized()
                buv = (uvs[2] - uvs[0]).normalized()
                angle_uv = auv.angle(buv)
                total_angle_diff += abs(angle3d - angle_uv)
                angle_count += 1
            except:
                continue

    # Подсчёт островов
    island_count = count_uv_islands(obj, uv_name)

    # Подсчёт пересечений UV треугольников
    tris = get_uv_triangles(bm, uv_layer)
    real_overlap_count = count_uv_triangle_overlaps(tris)
    real_overlap_penalty = real_overlap_count * 0.2  # коэффициент можно подправить

    bm.free()



    if total_area_3d == 0 or total_area_uv == 0:
        return float('inf')

    area_ratio = total_area_uv / total_area_3d
    coverage = compute_uv_coverage(uv_coords)

    uv_grid = {}
    overlap_count = 0
    precision = 1000
    for uv in uv_coords:
        key = (int(uv[0] * precision), int(uv[1] * precision))
        if key in uv_grid:
            overlap_count += 1
        else:
            uv_grid[key] = 1

    uv_aspect_penalty = 0
    if uv_coords:
        min_u = min(v[0] for v in uv_coords)
        max_u = max(v[0] for v in uv_coords)
        min_v = min(v[1] for v in uv_coords)
        max_v = max(v[1] for v in uv_coords)
        width = max_u - min_u
        height = max_v - min_v
        if width > 0 and height > 0:
            aspect = max(width / height, height / width)
            if aspect > 3:
                uv_aspect_penalty = (aspect - 3) * 5

    stretch_score = (total_stretch / edge_count) if edge_count else 1
    angle_score = (total_angle_diff / angle_count) if angle_count else 1
    island_penalty = island_count * 1.5
    overlap_penalty = overlap_count * 0.15  # 👉 увеличено с 0.03

    final_score = (
        (1 - coverage) * 8 +
        abs(1 - area_ratio) * 10 +
        stretch_score * 10 +           # 👉 усилили влияние
        angle_score * 15 +
        island_penalty +
        overlap_penalty +
        uv_aspect_penalty + 
        real_overlap_penalty
    )

    print(f"[{obj.name}] UV '{uv_name}'")
    print(f"  Coverage:         {coverage:.4f}")
    print(f"  Area Ratio:       {area_ratio:.4f}")
    print(f"  Stretch Score:    {stretch_score:.4f}")
    print(f"  Angle Score:      {angle_score:.4f}")
    print(f"  Overlaps:         {overlap_count}, Penalty: {overlap_penalty:.2f}")
    print(f"  Islands:          {island_count}, Penalty: {island_penalty:.2f}")
    print(f"  Aspect Penalty:   {uv_aspect_penalty:.2f}")
    print(f"  Final Score:      {final_score:.2f}")
    print("-" * 40)

    return final_score

def compute_uv_coverage(uv_coords):
    if not uv_coords:
        return 0
    min_u = min(v[0] for v in uv_coords)
    max_u = max(v[0] for v in uv_coords)
    min_v = min(v[1] for v in uv_coords)
    max_v = max(v[1] for v in uv_coords)
    bbox_area = (max_u - min_u) * (max_v - min_v)
    if bbox_area == 0:
        return 0
    total_uv_area = 0
    for i in range(0, len(uv_coords) - 2, 3):
        try:
            total_uv_area += abs(mathutils.geometry.area_tri(uv_coords[i], uv_coords[i+1], uv_coords[i+2]))
        except:
            continue
    return min(total_uv_area / bbox_area, 1.0)

def count_uv_islands(obj, uv_name):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.get(uv_name)
    if not uv_layer:
        bm.free()
        return 1

    visited_faces = set()
    islands = 0

    def walk_island(face, island_faces):
        stack = [face]
        while stack:
            f = stack.pop()
            if f.index in island_faces:
                continue
            island_faces.add(f.index)
            for e in f.edges:
                linked = [f2 for f2 in e.link_faces if f2 != f]
                for f2 in linked:
                    shared = 0
                    for l1 in f.loops:
                        for l2 in f2.loops:
                            if l1.vert == l2.vert and l1[uv_layer].uv == l2[uv_layer].uv:
                                shared += 1
                    if shared >= 2:
                        stack.append(f2)

    for face in bm.faces:
        if face.index in visited_faces:
            continue
        island_faces = set()
        walk_island(face, island_faces)
        visited_faces.update(island_faces)
        islands += 1

    bm.free()
    return islands

class UV_PT_UVOrderPanel(bpy.types.Panel):
    bl_label = "UV Map Position"
    bl_idname = "UV_PT_UVOrderPanel"
    bl_parent_id = "UV_PT_ToolsPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'UV Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        obj = context.object

        if not obj or obj.type != 'MESH' or not obj.data.uv_layers:
            layout.label(text="Select a mesh with UV maps", icon="INFO")
            return

        uv_layers = obj.data.uv_layers
        active_index = uv_layers.active_index

        layout.label(text=f"UVs for {obj.name}")
        for i, uv in enumerate(uv_layers):
            row = layout.row()
            row.label(text=uv.name + ("  (Active)" if i == active_index else ""))

            col = row.row(align=True)
            op_up = col.operator("uvtools.reorder_uv", text="", icon="TRIA_UP")
            op_up.move_index = i
            op_up.direction = 'UP'

            op_down = col.operator("uvtools.reorder_uv", text="", icon="TRIA_DOWN")
            op_down.move_index = i
            op_down.direction = 'DOWN'


class UV_OT_ReorderUV(bpy.types.Operator):
    bl_idname = "uvtools.reorder_uv"
    bl_label = "Reorder UV Map"
    bl_description = "Change the order of UV maps by rebuilding them"

    move_index: bpy.props.IntProperty()
    direction: bpy.props.EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")]
    )

    def execute(self, context):
        obj = context.object
        mesh = obj.data
        uv_layers = mesh.uv_layers

        index = self.move_index
        if self.direction == 'UP' and index <= 0:
            return {'CANCELLED'}
        if self.direction == 'DOWN' and index >= len(uv_layers) - 1:
            return {'CANCELLED'}

        new_index = index - 1 if self.direction == 'UP' else index + 1

        # 1. Сохраняем все UV слои и их данные
        uv_data_all = []
        for i, layer in enumerate(uv_layers):
            uv_data_all.append({
                "name": layer.name,
                "data": [loop.uv.copy() for loop in layer.data],
                "is_active": (i == uv_layers.active_index),
            })

        # 2. Меняем местами два слоя
        uv_data_all[index], uv_data_all[new_index] = uv_data_all[new_index], uv_data_all[index]

        # 3. Удаляем все UV слои
        while len(uv_layers) > 0:
            uv_layers.remove(uv_layers[0])

        # 4. Пересоздаём в новом порядке
        for i, layer_data in enumerate(uv_data_all):
            new_layer = uv_layers.new(name=layer_data["name"])
            for loop, uv in zip(new_layer.data, layer_data["data"]):
                loop.uv = uv
            if layer_data["is_active"]:
                uv_layers.active_index = i

        return {'FINISHED'}


# === REGISTER ===
classes = (
    UVToolProps,
    UV_PT_ToolsPanel,
    UV_PT_ByMaterialsPanel,
    UV_OT_CleanByMaterials,
    UV_OT_CleanByLooseParts,
    UV_PT_UVOrderPanel,
    UV_OT_ReorderUV,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.uv_tools_props = bpy.props.PointerProperty(type=UVToolProps)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.uv_tools_props

if __name__ == "__main__":
    register()
