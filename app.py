from __future__ import annotations

import os

from shared_notes import install_cloud_annotations, install_local_annotations

ONLINE_MODE = os.getenv("ONLINE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

if ONLINE_MODE:
    import cloud_app as _cloud

    app = _cloud.app
    install_cloud_annotations(app, _cloud)
else:
    import local_app as _local

    app = _local.app
    install_local_annotations(app)
    _run_check_worker = _local._run_check_worker
    _snapshot = _local._snapshot
    _lock = _local._lock
    _state = _local._state
    _now = _local._now


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
