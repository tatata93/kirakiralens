from __future__ import annotations

import json
import sys

from ..domain import OpticalDesign
from .performance import evaluate_performance


def main() -> int:
    for raw_line in sys.stdin:
        request: dict = {}
        try:
            request = json.loads(raw_line)
            if request.get("command") == "quit":
                return 0
            generation = int(request["generation"])
            design = OpticalDesign.from_dict(request["design"])
            result = evaluate_performance(design, request.get("options"))
            response = {"generation": generation, "result": result}
        except Exception as exc:
            response = {
                "generation": int(request.get("generation", -1)) if isinstance(request, dict) else -1,
                "result": {
                    "valid": False,
                    "engine": "Optiland performance process",
                    "warnings": [f"{type(exc).__name__}: {exc}"],
                },
            }
        print(json.dumps(response, ensure_ascii=True, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
