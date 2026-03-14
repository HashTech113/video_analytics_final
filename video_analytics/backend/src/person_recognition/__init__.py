from importlib import import_module

__all__ = [
    "RecognitionService",
    "match_embedding",
    "ArcFaceRecognizer",
    "FaceMatcher",
    "FaceTracker",
    "ByteTrackFaceTracker",
]


_SYMBOL_TO_MODULE = {
    "RecognitionService": ".recognition_service",
    "match_embedding": ".recognition_service",
    "ArcFaceRecognizer": ".face_embedding",
    "FaceMatcher": ".face_matcher",
    "FaceTracker": ".face_tracker",
    "ByteTrackFaceTracker": ".bytetrack_tracker",
}


def __getattr__(name):
    module_path = _SYMBOL_TO_MODULE.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        module = import_module(module_path, __name__)
    except Exception as e:
        raise ImportError(f"Failed to load module {module_path}: {e}") from e

    value = getattr(module, name)
    globals()[name] = value
    return value
