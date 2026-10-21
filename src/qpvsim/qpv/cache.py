"""A small least-recently-used cache for analyses that depend only on the project setup."""

from collections import OrderedDict
from typing import Any, Callable, Hashable


def memo(size: int = 8) -> Callable:
    def deco(fn):
        store: "OrderedDict[Hashable, Any]" = OrderedDict()

        def wrapper(key: Hashable, *args):
            if key in store:
                store.move_to_end(key)
                return store[key]
            store[key] = value = fn(*args)
            if len(store) > size:
                store.popitem(last=False)
            return value
        return wrapper
    return deco
