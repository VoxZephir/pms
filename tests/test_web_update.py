"""The update button: `git pull --ff-only` from the page, on a throwaway
pair of repositories -- never this one, never the network."""

from __future__ import annotations

import subprocess

import pytest

from pms.web import updates


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd, name, text, message):
    (cwd / name).write_text(text, encoding="utf-8")
    _git(cwd, "add", name)
    _git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message)


@pytest.fixture
def copy(tmp_path, monkeypatch):
    """A clone one commit behind its origin."""
    origin, here = tmp_path / "origin", tmp_path / "here"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _commit(origin, "app.py", "v1\n", "First")
    _git(tmp_path, "clone", "-q", str(origin), str(here))
    _commit(origin, "app.py", "v2\n", "Better charts")
    monkeypatch.setattr(updates, "ROOT", here)
    monkeypatch.setitem(updates._cache, "result", None)
    return {"origin": origin, "here": here}


def test_the_check_says_what_is_waiting(copy):
    state = updates.check(force=True, now=5.0)
    assert state == {"available": True, "behind": 1, "changes": ["Better charts"],
                     "dependencies": False, "branch": "origin/main", "checked": 5.0}


def test_the_check_is_cached_for_an_hour(copy):
    first = updates.check(force=True, now=1000.0)
    _commit(copy["origin"], "b.py", "x\n", "More")
    assert updates.check(now=1000.0 + updates.FETCH_EVERY - 1) == first
    assert updates.check(now=1000.0 + updates.FETCH_EVERY)["behind"] == 2


def test_applying_pulls_and_names_a_change_of_dependencies(copy):
    _commit(copy["origin"], "uv.lock", "x\n", "Bump a dependency")
    assert updates.check(force=True)["dependencies"] is True
    done = updates.apply()
    assert done == {"pulled": 2, "dependencies": True}
    assert (copy["here"] / "app.py").read_text(encoding="utf-8") == "v2\n"
    assert updates.check(force=True, now=7.0) == {"available": False, "behind": 0,
                                                  "branch": "origin/main", "checked": 7.0}


def test_a_local_change_stops_the_pull_with_git_s_words(copy):
    (copy["here"] / "app.py").write_text("mine\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as failed:
        updates.apply()
    assert str(failed.value)
    assert (copy["here"] / "app.py").read_text(encoding="utf-8") == "mine\n"


def test_a_copy_without_git_is_said_so(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "ROOT", tmp_path)
    monkeypatch.setitem(updates._cache, "result", None)
    assert updates.check(force=True)["available"] is False


def test_the_routes_are_off_unless_the_serving_app_turns_them_on(client, copy):
    assert client.get("/api/update").get_json() == {"available": False, "reason": "off"}
    assert client.post("/api/update", headers={"Origin": "http://localhost"}).status_code == 409
    client.application.config["PMS_UPDATES"] = True
    try:
        assert client.get("/api/update?force=1").get_json()["behind"] == 1
        done = client.post("/api/update", headers={"Origin": "http://localhost"}).get_json()
        assert done["pulled"] == 1 and done["restarting"] is False  # no reloader here
    finally:
        client.application.config["PMS_UPDATES"] = False


def test_a_copy_pulled_from_another_branch_follows_that_branch(copy):
    """On a branch of its own, updated with `git pull origin <branch>`: its
    upstream never moves, the branch it was pulled from does. (A copy on
    main follows main and nothing else: the next test.)"""
    origin, here = copy["origin"], copy["here"]
    _git(here, "checkout", "-q", "-b", "mine")
    _git(origin, "checkout", "-q", "-b", "feature")
    _commit(origin, "c.py", "x\n", "On the branch")
    _git(here, "pull", "-q", "--no-rebase", "origin", "feature")
    _commit(origin, "d.py", "y\n", "Later on the branch")
    state = updates.check(force=True)
    assert (state["available"], state["branch"], state["changes"]) == (True, "origin/feature", ["Later on the branch"])
    assert updates.apply()["pulled"] == 1
    assert (here / "d.py").exists()
    upstream = subprocess.run(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=here,
                              capture_output=True, text=True).stdout.strip()
    assert upstream == "origin/feature"


def test_a_work_branch_merged_back_moves_the_copy_onto_main(copy):
    here, origin = copy["here"], copy["origin"]
    _git(here, "pull", "-q", "--ff-only")
    # The copy works on a branch of its own, pushed to origin...
    _git(here, "checkout", "-q", "-b", "work")
    _commit(here, "feature.py", "x\n", "Feature")
    _git(here, "push", "-q", "-u", "origin", "work")
    # ...which is merged back into main there.
    _git(origin, "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "-q", "--no-ff", "work",
         "-m", "Merge work")
    assert updates.check(force=True)["branch"] == "origin/main"
    updates.apply()
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=here,
                            capture_output=True, text=True).stdout.strip()
    assert branch == "main" and (here / "feature.py").exists()
    # From then on main is followed, and nothing else.
    _git(origin, "checkout", "-q", "work")
    _commit(origin, "other.py", "y\n", "On the old branch")
    _git(origin, "checkout", "-q", "main")
    assert updates.check(force=True, now=9.0)["branch"] == "origin/main"
    assert updates.check(force=True, now=9.0)["behind"] == 0
