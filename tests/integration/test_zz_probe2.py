import json
from pathlib import Path
from research.validation.validator import validate_run

def test_dump(complete_run):
    ws, rid, meta = complete_run
    res = validate_run(ws, rid)
    p = Path(res["validation_result_path"])
    art = json.loads(p.read_text(encoding="utf-8"))
    print("TOP-LEVEL KEYS:", sorted(art.keys()))
    print("CHECKS WITH artifact_ids:",
          [(c["check"], c.get("artifact_ids")) for c in art["checks"] if c.get("artifact_ids")])
    print("run manifest phase:", json.loads((meta["run_dir"]/"manifest.json").read_text(encoding="utf-8"))["phase"])
