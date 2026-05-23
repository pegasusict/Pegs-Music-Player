import unittest
from pathlib import Path
from unittest.mock import patch

from app_queue.queue_manager import QueueManager
from domain.track import Track
from infrastructure.database import Database
from infrastructure.queries import track_queries
from repository.music_repository import MusicRepository
from runtime.bootstrap import Application


class MigrationTests(unittest.TestCase):
    def test_fresh_database_has_current_schema_and_revisions(self):
        db = Database(":memory:")
        try:
            connection = db.connect()
            revisions = [
                row["revision"]
                for row in connection.execute(
                    "SELECT revision FROM schema_migrations ORDER BY revision"
                ).fetchall()
            ]
            columns = [
                row["name"]
                for row in connection.execute("PRAGMA table_info(tracks)").fetchall()
            ]

            self.assertEqual(
                revisions,
                ["0001_initial_schema", "0002_track_replaygain"],
            )
            self.assertIn("replaygain_track_gain_db", columns)
            self.assertIn("replaygain_track_peak", columns)
        finally:
            db.close()


class ReplayGainCoverageTests(unittest.TestCase):
    def test_replaygain_coverage_counts_only_complete_track_gain_data(self):
        db = Database(":memory:")
        try:
            track_queries.add_track(
                db,
                "/music/a.flac",
                "Artist",
                "A",
                "shared",
                180,
                -6.0,
                0.95,
            )
            track_queries.add_track(
                db,
                "/music/b.flac",
                "Artist",
                "B",
                "shared",
                180,
                -3.0,
                None,
            )

            self.assertEqual(MusicRepository(db).get_replaygain_coverage(), (2, 1))
        finally:
            db.close()

    def test_refresh_track_metadata_updates_existing_track_row(self):
        db = Database(":memory:")
        try:
            track_id = track_queries.add_track(
                db,
                "/music/a.flac",
                "Old Artist",
                "Old Title",
                "shared",
                100,
                None,
                None,
            )[0]
            repo = MusicRepository(db)

            with (
                patch.object(Path, "exists", return_value=True),
                patch.object(
                    repo,
                    "_read_metadata",
                    return_value=("New Artist", "New Title", 200, -6.0, 0.95),
                ),
            ):
                result = repo.refresh_track_metadata()

            track = repo.get_by_id(track_id)
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(track.artist, "New Artist")
            self.assertEqual(track.title, "New Title")
            self.assertEqual(track.duration_seconds, 200)
            self.assertEqual(track.replaygain_track_gain_db, -6.0)
            self.assertEqual(track.replaygain_track_peak, 0.95)
            self.assertEqual(repo.get_replaygain_coverage(), (1, 1))
        finally:
            db.close()

    def test_replaygain_float_parser_accepts_tag_values(self):
        db = Database(":memory:")
        try:
            repo = MusicRepository(db)
            self.assertEqual(repo._parse_replaygain_float(["-6.04 dB"]), -6.04)
            self.assertEqual(repo._parse_replaygain_float("0.955597"), 0.955597)
            self.assertIsNone(repo._parse_replaygain_float("not-a-number"))
        finally:
            db.close()


class QueuePersistenceTests(unittest.TestCase):
    def test_queue_persist_and_restore_preserves_manual_and_auto_order(self):
        db = Database(":memory:")
        try:
            tracks = [
                Track(
                    id=track_queries.add_track(
                        db,
                        f"/music/{name}.flac",
                        "Artist",
                        name,
                        "shared",
                        180,
                        -1.0,
                        0.9,
                    )[0],
                    path=Path(f"/music/{name}.flac"),
                    artist="Artist",
                    title=name,
                    folder="shared",
                    duration_seconds=180,
                    replaygain_track_gain_db=-1.0,
                    replaygain_track_peak=0.9,
                )
                for name in ("a", "b", "c")
            ]

            queue = QueueManager()
            queue.enqueue_manual(tracks[0])
            queue.enqueue_auto(tracks[1])
            queue.enqueue_auto(tracks[2])
            queue.persist(db)

            restored = QueueManager()
            restored.restore(db, MusicRepository(db))
            snapshot = restored.snapshot()

            self.assertEqual([track.title for track in snapshot["manual"]], ["a"])
            self.assertEqual([track.title for track in snapshot["auto"]], ["b", "c"])
        finally:
            db.close()


class ConfigApplyTests(unittest.TestCase):
    def test_apply_config_rewires_scheduler_dependents(self):
        db = Database(":memory:")
        app = Application(db)
        try:
            raw_config = app.get_raw_config()
            original_scheduler = app.scheduler

            app._rebuild_scheduler_and_notify_slot_runtime(raw_config)

            self.assertIsNot(app.scheduler, original_scheduler)
            self.assertIs(app.selection_engine.scheduler, app.scheduler)
            self.assertIs(app.slot_runtime.scheduler, app.scheduler)
        finally:
            app.playback_engine.shutdown()
            db.close()

    def test_apply_config_ignores_live_db_path_change(self):
        db = Database(":memory:")
        app = Application(db)
        try:
            raw_config = app.get_raw_config()
            changed_config = dict(raw_config)
            changed_config["db_path"] = "/tmp/other-music-player.db"

            with (
                patch("runtime.bootstrap.config.load_config", return_value=raw_config),
                patch("runtime.bootstrap.config.save_config") as save_config,
            ):
                app.apply_config(changed_config)

            saved_config = save_config.call_args.args[0]
            self.assertEqual(saved_config["db_path"], raw_config["db_path"])
        finally:
            app.playback_engine.shutdown()
            db.close()


if __name__ == "__main__":
    unittest.main()
