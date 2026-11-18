import argparse
from pathlib import Path

from app.modules.schedule.read_models import ScheduleReadResult
from scripts.generate_biorhythm_vectors import render

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts/fixtures/schedule_read.schema.json"


def content() -> bytes:
    return render(ScheduleReadResult.model_json_schema(mode="serialization"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = content()
    if args.check:
        if not SCHEMA_PATH.exists() or SCHEMA_PATH.read_bytes() != schema:
            print("Outdated schedule_read.schema.json; regenerate without --check")
            return 1
        print("Schedule read schema is current")
    else:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_bytes(schema)
        print(f"Wrote {SCHEMA_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
