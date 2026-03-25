"""Blender host server.

Run once inside Blender (e.g. from a startup script):

    from rigBuilder.server.hosts.blender import BlenderServer
    BlenderServer(rep_port=7204, pub_port=7205).start()
"""

import bpy

from rigBuilder.server.hosts import HostServer


class BlenderServer(HostServer):
    """Dispatches execution to Blender's main thread via bpy.app.timers."""

    def executeOnMainThread(self, taskFunction):
        bpy.app.timers.register(taskFunction, first_interval=0)

# API functions mostly used by the client's widgets

def select(names: list[str]) -> None:
    """Select objects, pose bones, or edit bones by the current mode."""
    obj = bpy.context.active_object
    
    if obj and obj.type == 'ARMATURE':
        mode = bpy.context.mode
        if mode == 'POSE':
            for bone in obj.pose.bones:
                bone.select = bone.name in names
            return
        elif mode == 'EDIT':
            for bone in obj.data.edit_bones:
                is_selected = bone.name in names
                bone.select = is_selected
                bone.select_head = is_selected
                bone.select_tail = is_selected
            return

    # Default to Object Mode selection
    bpy.ops.object.select_all(action='DESELECT')
    for name in names:
        if name in bpy.data.objects:
            bpy.data.objects[name].select_set(True)

def getSelected() -> list[str]:
    """Get selected objects, pose bones, or edit bones by the current mode."""
    obj = bpy.context.active_object
    
    if obj and obj.type == 'ARMATURE':
        mode = bpy.context.mode
        if mode == 'POSE':
            return [bone.name for bone in bpy.context.selected_pose_bones]
            
        if mode == 'EDIT':
            return [bone.name for bone in bpy.context.selected_editable_bones]
    
    return [o.name for o in bpy.context.selected_objects]