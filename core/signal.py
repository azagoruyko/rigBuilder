import weakref
import inspect

class Signal:
    """A pure-Python observer implementation using weak references to prevent 
    memory leaks in background environments like the networking client.
    """
    def __init__(self):
        # Stores either weakref objects (for python methods/functions) 
        # or direct callables (for built-ins like C++ Qt wrappers)
        self._callbacks = []

    def connect(self, callback):
        # Prevent duplicates
        for ref in self._callbacks:
            cb = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if cb == callback:
                return

        if inspect.ismethod(callback):
            ref = weakref.WeakMethod(callback)
            self._callbacks.append(ref)
        else:
            # Fallback for functions, lambdas, and C++ built-ins (like PyQt .emit)
            # which would otherwise be garbage collected immediately if weak-referenced.
            self._callbacks.append(callback)

    def disconnect(self, callback):
        new_callbacks = []
        for ref in self._callbacks:
            cb = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if cb is not None and cb != callback:
                new_callbacks.append(ref)
        self._callbacks = new_callbacks

    def emit(self, *args, **kwargs):
        active_callbacks = []
        for ref in self._callbacks:
            cb = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if cb is not None:
                active_callbacks.append(cb)
        
        # Clean up dead references automatically
        if len(active_callbacks) != len(self._callbacks):
            self._callbacks = [r for r in self._callbacks if (r() if isinstance(r, weakref.ReferenceType) else r) is not None]

        # Dispatch
        for cb in active_callbacks:
            cb(*args, **kwargs)
