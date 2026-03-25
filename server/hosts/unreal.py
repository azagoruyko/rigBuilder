"""Unreal Engine host server.

Run inside Unreal (e.g. from Python Script Editor):

    from rigBuilder.server.hosts.unreal import UnrealServer
    UnrealServer(rep_port=7208, pub_port=7209).start()
"""

import queue
import traceback

import unreal

from rigBuilder.server.hosts import HostServer


class UnrealServer(HostServer):
    """Dispatches execution to Unreal's main thread via a persistent Slate post-tick callback and a task queue."""

    def __init__(self, rep_port: int, pub_port: int):
        super().__init__(rep_port, pub_port)
        self._queue = queue.Queue()
        self._tick_handle = None

    def start(self):
        """Bind sockets and start the command loop AND the persistent tick."""
        super().start()
        if unreal:
            try:
                # Register a persistent Slate tick that checks our internal queue
                self._tick_handle = unreal.register_slate_post_tick_callback(self._on_tick)
                print(f"[rigBuilder.server] Unreal persistent tick registered")
            except Exception as e:
                print(f"[rigBuilder.server] Failed to register Unreal tick: {e}")

    def stop(self):
        """Stop server and unregister tick."""
        super().stop()
        if self._tick_handle and unreal:
            try:
                unreal.unregister_slate_post_tick_callback(self._tick_handle)
                self._tick_handle = None
            except Exception:
                pass

    def _on_tick(self, delta_time: float):
        """Persistent callback that runs on Unreal's main thread."""
        try:
            callback = self._queue.get_nowait()
        except queue.Empty:
            return

        try:
            callback()
        except Exception as e:
            if unreal:
                try:
                    unreal.log_error(f"RigBuilder Error: {e}\n{traceback.format_exc()}")
                except Exception:
                    pass

    def executeOnMainThread(self, taskFunction):
        self._queue.put(taskFunction)


# API functions mostly used by the client's widgets

def select(names: list[str]) -> None:
    """Select actors by their label or name."""
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    all_actors = actor_subsystem.get_all_level_actors()

    to_select = []
    names_set = set(names)
    for actor in all_actors:
        if actor.get_actor_label() in names_set or actor.get_name() in names_set:
            to_select.append(actor)

    actor_subsystem.set_selected_level_actors(to_select)


def getSelected() -> list[str]:
    """Get selected actors labels."""
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    return [a.get_actor_label() for a in actor_subsystem.get_selected_level_actors()]
