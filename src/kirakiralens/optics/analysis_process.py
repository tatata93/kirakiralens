from __future__ import annotations

import json
import sys
from dataclasses import asdict

from ..domain import OpticalDesign
from .optiland_adapter import OptilandAdapter


def main() -> int:
    adapter = OptilandAdapter()
    for raw_line in sys.stdin:
        request: dict = {}
        try:
            request = json.loads(raw_line)
            if request.get("command") == "quit":
                return 0
            generation = int(request["generation"])
            design = OpticalDesign.from_dict(request["design"])
            result = adapter.analyze_first_order(design)
            response = {"generation": generation, "result": asdict(result)}
        except Exception as exc:
            response = {
                "generation": int(request.get("generation", -1)) if isinstance(request, dict) else -1,
                "result": {
                    "valid": False,
                    "engine": "Optiland process",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            }
        print(json.dumps(response, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
