from __future__ import annotations

import json
import sys

from ..domain import OpticalDesign
from .automatic_design import run_automatic_design


def main() -> int:
    raw = sys.stdin.readline()
    request: dict = {}
    try:
        request = json.loads(raw)
        generation = int(request["generation"])

        def progress(payload: dict) -> None:
            print(json.dumps({"type": "progress", "generation": generation, "progress": payload}, allow_nan=False), flush=True)

        result = run_automatic_design(
            OpticalDesign.from_dict(request["design"]),
            request.get("options"),
            progress,
        )
        response = {"type": "result", "generation": generation, "result": result}
    except Exception as exc:
        response = {
            "type": "result",
            "generation": int(request.get("generation", -1)) if isinstance(request, dict) else -1,
            "result": {"valid": False, "error": f"{type(exc).__name__}: {exc}"},
        }
    print(json.dumps(response, ensure_ascii=True, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

