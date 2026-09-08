"""Cinema CI — Local FileSystem Artifact Store.

Implements the ArtifactStore interface using the local `./storage` directory,
allowing developers to directly inspect artifacts on disk (e.g. `ls storage/build_0023`).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil

from app.store.artifact_base import ArtifactStore

logger = logging.getLogger(__name__)


class LocalArtifactStore(ArtifactStore):
    """Local filesystem implementation of ArtifactStore."""

    def __init__(self, root_dir: str | None = None) -> None:
        self.root_dir = os.path.abspath(root_dir or os.getenv("CINEMA_STORAGE_ROOT", "./storage"))
        os.makedirs(self.root_dir, exist_ok=True)
        logger.info(f"LocalArtifactStore initialized at: {self.root_dir}")

    def _resolve(self, artifact_path: str) -> str:
        """Resolve a logical artifact path to a local absolute path in self.root_dir.
        
        Examples:
            'projects/blue-envelope/builds/build_0023/shot_01.mp4' -> '<root>/build_0023/shot_01.mp4'
            'build_0023/shot_01.mp4' -> '<root>/build_0023/shot_01.mp4'
            'storage/build_0023/shot_01.mp4' -> '<root>/build_0023/shot_01.mp4'
        """
        clean = artifact_path.replace("\\", "/")
        if "/builds/" in clean:
            rel = clean.split("/builds/", 1)[1]
        elif clean.startswith("storage/"):
            rel = clean[len("storage/"):]
        elif clean.startswith("./storage/"):
            rel = clean[len("./storage/"):]
        elif clean.startswith(self.root_dir):
            rel = os.path.relpath(clean, self.root_dir)
        else:
            rel = clean.lstrip("/")

        return os.path.abspath(os.path.join(self.root_dir, rel))

    def put_file(self, local_path: str, artifact_path: str) -> str:
        dest = self._resolve(artifact_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(local_path) != os.path.abspath(dest):
            shutil.copy2(local_path, dest)
        return self.uri(artifact_path)

    def get_file(self, artifact_path: str, local_path: str) -> str:
        src = self._resolve(artifact_path)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Artifact not found in local store: {artifact_path} ({src})")
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        if os.path.abspath(src) != os.path.abspath(local_path):
            shutil.copy2(src, local_path)
        return os.path.abspath(local_path)

    def copy(self, source_path: str, destination_path: str) -> str:
        src = self._resolve(source_path)
        dst = self._resolve(destination_path)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Source artifact not found for copy: {source_path} ({src})")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        return self.uri(destination_path)

    def exists(self, artifact_path: str) -> bool:
        dest = self._resolve(artifact_path)
        return os.path.exists(dest)

    def sha256(self, artifact_path: str) -> str:
        dest = self._resolve(artifact_path)
        if not os.path.exists(dest):
            return ""
        hasher = hashlib.sha256()
        with open(dest, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]

    def uri(self, artifact_path: str) -> str:
        dest = self._resolve(artifact_path)
        rel = os.path.relpath(dest, os.path.dirname(self.root_dir))
        return rel.replace("\\", "/")

    def get_read_url(self, artifact_path: str, expires_in_seconds: int = 3600) -> str | None:
        # In local development, no signed URLs; served directly via API
        return None

    def get_bytes(self, artifact_path: str) -> bytes:
        dest = self._resolve(artifact_path)
        with open(dest, "rb") as f:
            return f.read()

    def put_bytes(self, data: bytes, artifact_path: str) -> str:
        dest = self._resolve(artifact_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return self.uri(artifact_path)
