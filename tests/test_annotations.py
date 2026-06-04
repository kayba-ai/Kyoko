import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import annotations, storage
from kyoko.annotations import AnnotationError
from kyoko.cli import main
from tests.test_web import RunningServer

ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


def _seed(db_path: Path) -> str:
    """Seed a profile + run; returns the run id."""
    storage.ingest_source_fixture(db_path, HERMES)
    con = storage.connect(db_path)
    run_id = con.execute("SELECT id FROM runs LIMIT 1").fetchone()[0]
    con.close()
    return run_id


class AnnotationModuleTests(unittest.TestCase):
    def test_create_then_list_roundtrip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            created = annotations.create_annotation(
                db_path=db_path,
                kind="issue",
                run_id=run_id,
                note="needs a look",
                source="agent",
            )
            self.assertEqual(created["kind"], "issue")
            self.assertEqual(created["note"], "needs a look")
            self.assertEqual(created["source"], "agent")
            listed = annotations.list_annotations(db_path=db_path, run_id=run_id)
            self.assertEqual([a["id"] for a in listed], [created["id"]])
            self.assertEqual(listed[0]["note"], "needs a look")

    def test_create_bad_kind_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            with self.assertRaises(AnnotationError):
                annotations.create_annotation(
                    db_path=db_path, kind="bogus", run_id=run_id
                )

    def test_delete_removes_annotation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            created = annotations.create_annotation(
                db_path=db_path, kind="note", run_id=run_id, note="x"
            )
            annotations.delete_annotation(db_path=db_path, annotation_id=created["id"])
            self.assertEqual(annotations.list_annotations(db_path=db_path, run_id=run_id), [])

    def test_delete_unknown_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            with self.assertRaises(AnnotationError):
                annotations.delete_annotation(db_path=db_path, annotation_id="anno_missing")

    def test_note_is_not_redacted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            created = annotations.create_annotation(
                db_path=db_path, kind="note", run_id=run_id, note="my secret token"
            )
            self.assertEqual(created["note"], "my secret token")
            listed = annotations.list_annotations(db_path=db_path, run_id=run_id)
            self.assertEqual(listed[0]["note"], "my secret token")

    def test_annotation_kinds_constant(self) -> None:
        self.assertEqual(set(annotations.ANNOTATION_KINDS), {"issue", "good", "note"})


class AnnotationCliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_annotate_and_list_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            code, out = self._run(
                ["annotate", "issue", "--run-id", run_id, "--note", "x",
                 "--db", str(db_path), "--json"]
            )
            self.assertEqual(code, 0)
            created = json.loads(out)["annotation"]
            self.assertEqual(created["kind"], "issue")

            code, out = self._run(
                ["annotations", "--run-id", run_id, "--db", str(db_path), "--json"]
            )
            self.assertEqual(code, 0)
            listed = json.loads(out)["annotations"]
            self.assertEqual([a["id"] for a in listed], [created["id"]])

    def test_annotate_bad_kind_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            # argparse restricts kind choices, so a bad kind exits non-zero.
            with self.assertRaises(SystemExit):
                main(["annotate", "bogus", "--run-id", run_id, "--db", str(db_path)])


class AnnotationWebTests(unittest.TestCase):
    def test_post_list_and_delete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id = _seed(db_path)
            with RunningServer(db_path) as server:
                created = server.post_json(
                    "/api/annotations", {"kind": "note", "run_id": run_id, "note": "hi"}
                )["annotation"]
                self.assertEqual(created["kind"], "note")

                listed = server.get_json(f"/api/annotations?run_id={run_id}")["annotations"]
                self.assertEqual([a["id"] for a in listed], [created["id"]])

                server.post_json("/api/annotations/delete", {"id": created["id"]})
                remaining = server.get_json(f"/api/annotations?run_id={run_id}")["annotations"]
                self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()
