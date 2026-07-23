from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.ai_cio_chat import ProjectDataCatalog  # noqa: E402


def build_catalog() -> Path:
    catalog = ProjectDataCatalog(
        root_dir=ROOT_DIR,
        max_index_chars=4_000,
        use_manifest=False,
    )
    catalog.refresh()
    output_path = catalog.write_manifest()
    stats = catalog.stats()
    print(
        f"AI-CIO data catalog: {output_path} | "
        f"files={stats['total_files']} readable={stats['readable_files']} "
        f"size_mb={stats['total_size_mb']}"
    )
    return output_path


if __name__ == "__main__":
    build_catalog()
