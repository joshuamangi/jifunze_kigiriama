"""deploy/*.sh against a temporary directory tree, with fake systemctl, python and health checks."""

import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("sqlite3") is None,
    reason="bash and the sqlite3 command are needed",
)


@pytest.fixture
def box(tmp_path):
    """A fake /srv/jifunze plus stubs. systemctl 'restarts' by publishing a health answer that
    depends on which release `current` points at: any release whose tag contains 'bad' is down."""
    base = tmp_path / "srv"
    (base / "data").mkdir(parents=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    health = tmp_path / "health.json"
    health.write_text('{"status":"ok"}')

    def stub(name, body):
        path = stubs / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    systemctl = stub(
        "systemctl",
        f'echo "systemctl $*" >> "{log}"\n'
        # A release that crash-loops makes systemd give up ("start request repeated too quickly"):
        # until `reset-failed`, every later restart is refused, including the rollback's.
        f'limit="{tmp_path}/start-limit"\n'
        f'if [ "$1" = reset-failed ]; then rm -f "$limit"; fi\n'
        f'if [ "$1" = restart ]; then\n'
        f'  if [ -e "$limit" ]; then echo "Start request repeated too quickly." >&2; exit 1; fi\n'
        f'  case "$(readlink "{base}/current")" in\n'
        f'    *bad*) echo down > "{health}"; : > "$limit" ;;\n'
        f'    *) echo \'{{"status":"ok"}}\' > "{health}" ;;\n'
        f"  esac\nfi\n",
    )
    python = stub(
        "python3",
        f'if [ "$1" = -m ] && [ "$2" = venv ]; then\n'
        f'  mkdir -p "$3/bin"\n'
        f"  for t in python pip; do\n"
        f'    printf \'#!/bin/sh\\necho "{{}} $*" >> "{log}"\\n\' > "$3/bin/$t"\n'
        f'    sed -i.bak "s|{{}}|$t|" "$3/bin/$t"; rm -f "$3/bin/$t.bak"\n'
        f'    chmod +x "$3/bin/$t"\n'
        f"  done\nfi\n",
    )
    env = {
        **os.environ,
        "JIFUNZE_BASE": str(base),
        "JIFUNZE_ENV_FILE": str(tmp_path / "missing.env"),
        "JIFUNZE_SYSTEMCTL": str(systemctl),
        "JIFUNZE_PYTHON": str(python),
        "JIFUNZE_HEALTH_URL": f"file://{health}",
        "HEALTH_RETRIES": "2",
        "HEALTH_INTERVAL": "0",
        "DATABASE_PATH": str(base / "data" / "app.db"),
    }
    conn = sqlite3.connect(base / "data" / "app.db")
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, english TEXT)")
    conn.execute("INSERT INTO entries (english) VALUES ('one')")
    conn.commit()
    conn.close()
    return {"base": base, "env": env, "log": log, "tmp": tmp_path}


def tarball(box, tag):
    incoming = box["base"] / "incoming"
    incoming.mkdir(exist_ok=True)
    src = box["tmp"] / f"src-{tag}"
    (src / "app").mkdir(parents=True)
    (src / "app" / "__init__.py").write_text("")
    (src / "requirements.lock").write_text("")
    path = incoming / f"jifunze-{tag}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        tar.add(src, arcname=".")
    return path


def sh(box, script, *args, check=False):
    return subprocess.run(  # noqa: S603
        ["bash", str(DEPLOY / script), *args],  # noqa: S607
        env=box["env"],
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )


def current(box):
    link = box["base"] / "current"
    return os.readlink(link) if link.is_symlink() else None


def calls(box):
    return box["log"].read_text().splitlines() if box["log"].exists() else []


# ---- deploy.sh --------------------------------------------------------------------------------
def test_dry_run_prints_every_step_and_changes_nothing(box):
    result = sh(box, "deploy.sh", "--dry-run", "v1")
    assert result.returncode == 0, result.stderr
    for n in range(1, 10):
        assert f"{n}/9" in result.stdout
    assert "[dry-run]" in result.stdout
    assert not (box["base"] / "releases").exists()
    assert current(box) is None
    assert calls(box) == []


@pytest.mark.parametrize("tag", ["../evil", "a/b", ".hidden", "", "x y"])
def test_bad_release_tags_are_refused(box, tag):
    result = sh(box, "deploy.sh", tag)
    assert result.returncode != 0
    assert not (box["base"] / "releases").exists()


def test_first_deploy_goes_live_without_a_backup_of_nothing(box):
    (box["base"] / "data" / "app.db").unlink()
    tarball(box, "v1")
    result = sh(box, "deploy.sh", "v1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert current(box) == "releases/v1"
    assert "first deploy" in result.stdout
    assert any("python -m app.migrate" in c for c in calls(box))
    assert "systemctl restart jifunze.service" in calls(box)


def test_deploy_backs_up_migrates_switches_and_records_previous(box):
    tarball(box, "v1")
    tarball(box, "v2")
    assert sh(box, "deploy.sh", "v1").returncode == 0
    result = sh(box, "deploy.sh", "v2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert current(box) == "releases/v2"
    assert (box["base"] / "previous").read_text().strip() == "v1"
    backups = list((box["base"] / "backups").glob("app-*.db"))
    assert len(backups) == 2  # one before each deploy that found a database
    assert (box["base"] / "data" / "last_backup").exists()
    assert any("pip install" in c and "--require-hashes" in c for c in calls(box))


def test_every_restart_clears_a_start_limit_failure_first(box):
    """A crash-looping release leaves the unit in systemd's start-limit state. The restart after
    it (a rollback, or the next deploy) is refused unless `reset-failed` runs first."""
    tarball(box, "v1")
    assert sh(box, "deploy.sh", "v1").returncode == 0
    seen = calls(box)
    i = seen.index("systemctl restart jifunze.service")
    assert seen[i - 1] == "systemctl reset-failed jifunze.service"


def test_rollback_after_a_crash_looping_release_brings_the_old_one_back(box):
    tarball(box, "v1")
    tarball(box, "v2-bad")
    assert sh(box, "deploy.sh", "v1").returncode == 0
    result = sh(box, "deploy.sh", "v2-bad")
    assert result.returncode != 0
    assert "the previous release is back" in result.stdout + result.stderr
    assert current(box) == "releases/v1"
    health = (box["tmp"] / "health.json").read_text()
    assert '"ok"' in health  # the app is running again, not left refusing restarts


def test_failed_health_check_rolls_back_to_the_previous_release(box):
    tarball(box, "v1")
    tarball(box, "v2-bad")
    assert sh(box, "deploy.sh", "v1").returncode == 0
    result = sh(box, "deploy.sh", "v2-bad")
    assert result.returncode != 0
    assert current(box) == "releases/v1"
    assert "rolling back" in result.stdout
    restarts = [c for c in calls(box) if c == "systemctl restart jifunze.service"]
    assert len(restarts) == 3  # v1, v2-bad, then v1 again


def test_a_release_that_cannot_be_built_never_goes_live_and_can_be_retried(box):
    tarball(box, "v1")
    assert sh(box, "deploy.sh", "v1").returncode == 0
    broken = box["base"] / "incoming" / "jifunze-v2.tar.gz"
    broken.write_bytes(b"not a tarball")
    result = sh(box, "deploy.sh", "v2")
    assert result.returncode != 0
    assert current(box) == "releases/v1"
    assert not (box["base"] / "releases" / "v2").exists()


def test_existing_release_is_not_overwritten(box):
    tarball(box, "v1")
    assert sh(box, "deploy.sh", "v1").returncode == 0
    result = sh(box, "deploy.sh", "v1")
    assert result.returncode != 0
    assert "already exists" in result.stdout + result.stderr


# root ignores directory permissions, so these two cannot fail there.
needs_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")


@needs_non_root
def test_a_failed_switch_leaves_current_and_previous_untouched(box):
    """On the Pi the runner could not create files in /srv/jifunze (not group-writable) but could
    still write the existing `previous` file: deploy.sh used to record the wrong previous release
    before the symlink switch failed."""
    for tag in ("v1", "v2", "v3"):
        tarball(box, tag)
    assert sh(box, "deploy.sh", "v1").returncode == 0
    assert sh(box, "deploy.sh", "v2").returncode == 0
    base = box["base"]
    assert (base / "previous").read_text().strip() == "v1"
    base.chmod(0o555)  # no new files in the base directory; existing files stay writable
    try:
        result = sh(box, "deploy.sh", "v3")
    finally:
        base.chmod(0o755)
    assert result.returncode != 0
    assert current(box) == "releases/v2"
    assert (base / "previous").read_text().strip() == "v1"
    assert not list(base.glob("current.new.*")) and not list(base.glob("previous.new.*"))
    assert not (base / "releases" / "v3").exists()  # the unfinished release is cleaned up


@needs_non_root
def test_a_prune_that_cannot_remove_an_old_release_does_not_fail_a_live_deploy(box):
    """Old releases made by another user may not be removable by the deploying user. The new release
    is already live by then, so that must be a warning, not a failed deploy."""
    box["env"]["JIFUNZE_KEEP_RELEASES"] = "1"
    releases = box["base"] / "releases"
    old = releases / "r1"
    (old / "sub").mkdir(parents=True)
    (old / "sub" / "file").write_text("x")
    stamp = time.time() - 3600
    os.utime(old, (stamp, stamp))
    (old / "sub").chmod(0o500)  # rm -rf cannot unlink the file inside
    tarball(box, "r2")
    try:
        result = sh(box, "deploy.sh", "r2")
    finally:
        (old / "sub").chmod(0o700)
    assert result.returncode == 0, result.stdout + result.stderr
    assert current(box) == "releases/r2"
    assert "could not remove old release r1" in result.stdout + result.stderr
    assert old.exists()


def test_old_releases_are_pruned_but_current_and_previous_stay(box):
    box["env"]["JIFUNZE_KEEP_RELEASES"] = "2"
    releases = box["base"] / "releases"
    releases.mkdir()
    for age, name in enumerate(["r1", "r2", "r3", "r4"]):
        (releases / name).mkdir()
        stamp = time.time() - (100 - age) * 60
        os.utime(releases / name, (stamp, stamp))
    (box["base"] / "current").symlink_to("releases/r1")  # old but live: must survive
    tarball(box, "r5")
    assert sh(box, "deploy.sh", "r5").returncode == 0
    left = sorted(p.name for p in releases.iterdir())
    assert "r5" in left
    assert "r1" in left  # it is `previous` now
    assert "r2" not in left
    assert len(left) == 3


# ---- rollback.sh ------------------------------------------------------------------------------
def make_tree(box):
    releases = box["base"] / "releases"
    for name in ("a", "b"):
        (releases / name).mkdir(parents=True)
    (box["base"] / "current").symlink_to("releases/b")
    (box["base"] / "previous").write_text("a\n")


def test_rollback_points_current_back_restarts_and_records_where_it_left(box):
    make_tree(box)
    result = sh(box, "rollback.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert current(box) == "releases/a"
    assert (box["base"] / "previous").read_text().strip() == "b"
    # reset-failed first: a crash-looping release leaves the unit refusing starts until cleared
    assert calls(box) == [
        "systemctl reset-failed jifunze.service",
        "systemctl restart jifunze.service",
    ]
    assert sh(box, "rollback.sh").returncode == 0  # a second run rolls forward again
    assert current(box) == "releases/b"


def test_rollback_dry_run_changes_nothing(box):
    make_tree(box)
    result = sh(box, "rollback.sh", "--dry-run")
    assert result.returncode == 0
    assert "[dry-run]" in result.stdout
    assert current(box) == "releases/b"
    assert calls(box) == []


def test_rollback_refuses_without_a_usable_previous_release(box):
    make_tree(box)
    (box["base"] / "previous").unlink()
    assert sh(box, "rollback.sh").returncode != 0
    for bad in ("../outside", "missing", ".hidden"):
        (box["base"] / "previous").write_text(bad)
        assert sh(box, "rollback.sh").returncode != 0
    assert current(box) == "releases/b"


# ---- backup.sh --------------------------------------------------------------------------------
def test_backup_is_a_restorable_checked_copy_and_touches_the_stamp(box):
    result = sh(box, "backup.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    (backup,) = (box["base"] / "backups").glob("app-*.db")
    assert oct(backup.stat().st_mode & 0o777) == "0o600"
    rows = sqlite3.connect(backup).execute("SELECT english FROM entries").fetchall()
    assert rows == [("one",)]
    assert (box["base"] / "data" / "last_backup").exists()
    assert not list((box["base"] / "backups").glob(".*partial"))


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(box):
    # Regression: names have one-second resolution, so a second backup right after the first
    # (a deploy just after the nightly run) used to replace it. CI on a fast runner hit this.
    assert sh(box, "backup.sh").returncode == 0
    assert sh(box, "backup.sh").returncode == 0
    assert len(list((box["base"] / "backups").glob("app-*.db"))) == 2


def test_backup_prunes_to_the_newest_n(box):
    box["env"]["BACKUP_KEEP"] = "2"
    backups = box["base"] / "backups"
    backups.mkdir()
    for stamp in ("20200101T000000Z", "20200102T000000Z", "20200103T000000Z"):
        (backups / f"app-{stamp}.db").write_text("old")
    assert sh(box, "backup.sh").returncode == 0
    names = sorted(p.name for p in backups.glob("app-*.db"))
    assert len(names) == 2
    assert "app-20200101T000000Z.db" not in names
    assert "app-20200102T000000Z.db" not in names


def test_failed_off_device_copy_fails_the_job_but_keeps_the_local_backup(box):
    box["env"]["BACKUP_COPY_COMMAND"] = "exit 3"
    result = sh(box, "backup.sh")
    assert result.returncode != 0
    assert len(list((box["base"] / "backups").glob("app-*.db"))) == 1


def test_off_device_copy_receives_the_new_file(box):
    sink = box["tmp"] / "sink"
    sink.mkdir()
    box["env"]["BACKUP_COPY_COMMAND"] = f'cp "$1" "{sink}/"'
    assert sh(box, "backup.sh").returncode == 0
    assert len(list(sink.glob("app-*.db"))) == 1


def test_backup_refuses_a_missing_database_and_dry_run_writes_nothing(box):
    result = sh(box, "backup.sh", "--dry-run")
    assert result.returncode == 0
    assert not (box["base"] / "backups" / "x").exists()
    assert not list((box["base"] / "backups").glob("app-*.db"))
    (box["base"] / "data" / "app.db").unlink()
    assert sh(box, "backup.sh").returncode != 0


def fake_mountpoint(box, mounted):
    stubs = box["tmp"] / "stubs"
    path = stubs / "mountpoint"
    path.write_text(f"#!/bin/sh\nexit {0 if mounted else 1}\n")
    path.chmod(0o755)
    box["env"]["PATH"] = f"{stubs}:{os.environ['PATH']}"
    box["env"]["BACKUP_REQUIRE_MOUNT"] = "1"


def test_backup_refuses_when_the_backup_disk_is_not_mounted(box):
    fake_mountpoint(box, mounted=False)
    result = sh(box, "backup.sh")
    assert result.returncode != 0
    assert "not a mounted disk" in result.stdout + result.stderr
    assert not list((box["base"] / "backups").glob("app-*.db"))


def test_backup_runs_when_the_backup_disk_is_mounted(box):
    fake_mountpoint(box, mounted=True)
    assert sh(box, "backup.sh").returncode == 0
    assert len(list((box["base"] / "backups").glob("app-*.db"))) == 1


# ---- healthcheck.sh ---------------------------------------------------------------------------
def test_healthcheck_passes_and_fails_on_the_answer(box):
    health = Path(box["env"]["JIFUNZE_HEALTH_URL"].removeprefix("file://"))
    assert sh(box, "healthcheck.sh").returncode == 0
    health.write_text('{"status":"starting"}')
    assert sh(box, "healthcheck.sh").returncode != 0
    health.unlink()
    assert sh(box, "healthcheck.sh").returncode != 0


def test_healthcheck_ignores_a_vcgencmd_that_cannot_read_the_hardware(box):
    # Regression (first real deploy on the Pi): the deploy user cannot open /dev/vcio, so
    # vcgencmd prints an error line instead of a value. That used to crash the arithmetic and
    # fail a healthy deploy. The hardware lines are advice; they must never fail the check.
    fake = box["tmp"] / "fakebin"
    fake.mkdir()
    tool = fake / "vcgencmd"
    tool.write_text('#!/bin/sh\necho "Can\'t open device file: /dev/vcio_gencmd"\n')
    tool.chmod(0o755)
    box["env"]["PATH"] = f"{fake}:{box['env']['PATH']}"
    result = sh(box, "healthcheck.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "app: ok" in result.stdout
    assert "power: unknown" in result.stdout
