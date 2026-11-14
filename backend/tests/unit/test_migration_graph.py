import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]


def test_migration_revision_ids_are_unique_before_alembic_loads_them() -> None:
    revisions: dict[str, Path] = {}
    for path in (BACKEND / "app/db/migrations/versions").glob("*.py"):
        if path.name.startswith("_"):
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        declared = [
            node.value
            for node in module.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "revision"
        ]
        assert len(declared) == 1, path.name
        revision = ast.literal_eval(declared[0])
        assert isinstance(revision, str)
        assert revision not in revisions, (
            f"Duplicate {revision}: {revisions.get(revision)} and {path}"
        )
        revisions[revision] = path


def test_canonical_graph_keeps_planner_0006_and_places_task_change_after_it() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["0007"]
    planner = script.get_revision("0006")
    tasks = script.get_revision("0007")
    assert planner is not None and tasks is not None
    assert Path(planner.path).name == "0006_planner_integration.py"
    assert planner.down_revision == "0005" and tasks.down_revision == "0006"
    assert len(list(script.walk_revisions())) == 7
