import importlib

import pytest


@pytest.fixture
def locking(tmp_path, monkeypatch):
    import kairo.paths as paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    import kairo.locking as locking_mod
    importlib.reload(locking_mod)
    yield locking_mod
    importlib.reload(locking_mod)


def test_acquire_and_release(locking):
    with locking.data_lock():
        pass
    # A second acquisition after release must succeed immediately.
    with locking.data_lock(timeout=1):
        pass


def test_reentrant_within_one_process(locking):
    with locking.data_lock():
        with locking.data_lock(timeout=1):
            with locking.data_lock(timeout=1):
                pass


def test_yields_control_and_runs_body(locking):
    ran = []
    with locking.data_lock():
        ran.append(1)
    assert ran == [1]
