import os

from spritesage import recent_projects
from spritesage.config import MAX_RECENT_PROJECTS, RECENT_PROJECTS_KEY


def test_add_recent_project_moves_latest_to_front_and_limits(tmp_path):
    entries = []
    for index in range(MAX_RECENT_PROJECTS + 2):
        project_dir = tmp_path / f"project_{index}"
        project_dir.mkdir()
        sage_file = project_dir / f"project_{index}.sage"
        sage_file.write_text("{}", encoding="utf-8")
        entries = recent_projects.add_recent_project(
            entries,
            str(project_dir),
            str(sage_file),
            f"Project {index}",
        )

    assert len(entries) == MAX_RECENT_PROJECTS
    assert entries[0]["name"] == f"Project {MAX_RECENT_PROJECTS + 1}"
    assert entries[-1]["name"] == "Project 2"


def test_add_recent_project_deduplicates_by_path(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    sage_file = project_dir / "project.sage"
    sage_file.write_text("{}", encoding="utf-8")

    entries = recent_projects.add_recent_project([], str(project_dir), str(sage_file), "Old")
    entries = recent_projects.add_recent_project(entries, str(project_dir), str(sage_file), "New")

    assert entries == [
        {
            "name": "New",
            "path": os.path.abspath(str(sage_file)),
            "project_dir": os.path.abspath(str(project_dir)),
        }
    ]


def test_normalize_recent_projects_accepts_legacy_string_entries(tmp_path):
    project_dir = tmp_path / "legacy"
    project_dir.mkdir()
    sage_file = project_dir / "legacy.sage"
    sage_file.write_text("{}", encoding="utf-8")

    entries = recent_projects.recent_projects_from_settings(
        {
            RECENT_PROJECTS_KEY: [
                str(sage_file),
                {"path": "not-a-project.txt"},
                123,
            ]
        }
    )

    assert entries == [
        {
            "name": "legacy",
            "path": os.path.abspath(str(sage_file)),
            "project_dir": os.path.abspath(str(project_dir)),
        }
    ]
