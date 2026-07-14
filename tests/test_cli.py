from pathlib import Path

from nowhere.cli import init_day


def test_init_day_creates_reference_files(tmp_path: Path) -> None:
    day = init_day(tmp_path, "2026-07-14", "test")
    assert (day / "README.md").exists()
    assert (day / "links.md").exists()
