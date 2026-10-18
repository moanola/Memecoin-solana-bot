"""Load and flush the edge stores through persistence kv."""
from edge import flags


def restore() -> None:
    try:
        from persistence import load_kv
    except Exception:
        return
    if flags.rug_memory():
        from edge.rug_memory import load
        load(load_kv("rug_memory"))
    if flags.copycat():
        from edge.copycat import load_index
        blob = load_kv("copycat_index")
        load_index(blob if isinstance(blob, dict) else None)


def flush() -> None:
    try:
        from persistence import save_kv
    except Exception:
        return
    if flags.rug_memory():
        from edge.rug_memory import snapshot
        save_kv("rug_memory", snapshot())
    if flags.copycat():
        from edge.copycat import snapshot_index
        save_kv("copycat_index", snapshot_index())
