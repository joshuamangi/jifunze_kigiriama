"""The Pi's config files in git: systemd units, Nginx, the lock file and the failure alert.

None of this can run on the Mac, so these tests check that the files agree with each other and with
the app (socket path, CSP, Uvicorn limits, body cap) and that the safety settings are present."""

import configparser
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from app.config import Settings
from app.security import CSP
from scripts import notify_failure

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
SYSTEMD = DEPLOY / "systemd"
NGINX = DEPLOY / "nginx"
SOCKET = "/run/jifunze/app.sock"


def unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(path)
    return parser


SERVICES = sorted(p for p in SYSTEMD.glob("*.service"))
TIMERS = sorted(p for p in SYSTEMD.glob("*.timer"))


# ---- systemd ----------------------------------------------------------------------------------
@pytest.mark.parametrize("path", SERVICES, ids=lambda p: p.name)
def test_every_service_is_sandboxed_and_runs_as_the_service_user(path):
    service = unit(path)["Service"]
    assert service["User"] == "jifunze"
    assert service["NoNewPrivileges"] == "yes"
    assert service["ProtectSystem"] == "strict"
    assert service["PrivateTmp"] == "yes"
    assert "MemoryMax" in service
    assert service["CapabilityBoundingSet"] == ""


@pytest.mark.parametrize(
    "path", [p for p in SERVICES if "failure" not in p.name], ids=lambda p: p.name
)
def test_units_that_touch_data_wait_for_the_ssd_mount(path):
    assert "/srv/jifunze" in unit(path)["Unit"]["RequiresMountsFor"].split()


def test_backup_unit_also_waits_for_the_backup_disk_mount():
    wanted = unit(SYSTEMD / "jifunze-backup.service")["Unit"]["RequiresMountsFor"].split()
    assert "/srv/jifunze/backups" in wanted


def test_app_memory_ceiling_fits_a_2gb_pi():
    service = unit(SYSTEMD / "jifunze.service")["Service"]
    assert service["MemoryMax"] == "600M"
    assert service["MemoryHigh"] == "450M"


@pytest.mark.parametrize("path", SERVICES, ids=lambda p: p.name)
def test_failures_send_an_alert_except_the_alert_itself(path):
    on_failure = unit(path)["Unit"].get("OnFailure")
    if path.name.startswith("jifunze-failure@"):
        assert on_failure is None  # an alert that alerts about itself could loop
    else:
        assert on_failure == "jifunze-failure@%n.service"


@pytest.mark.parametrize("path", TIMERS, ids=lambda p: p.name)
def test_every_timer_has_a_service_and_is_enabled_by_timers_target(path):
    assert path.with_suffix(".service").exists()
    assert unit(path)["Install"]["WantedBy"] == "timers.target"
    assert "OnCalendar" in unit(path)["Timer"]


def test_app_unit_runs_one_worker_on_the_socket_with_a_memory_ceiling():
    service = unit(SYSTEMD / "jifunze.service")["Service"]
    start = " ".join(service["ExecStart"].split()).replace("\\ ", "")
    assert f"--uds {SOCKET}" in start
    assert "--workers 1" in start
    assert "--port" not in start  # never listens on TCP
    assert service["Restart"] == "on-failure"
    assert service["ReadWritePaths"] == "/srv/jifunze/data"
    assert service["EnvironmentFile"] == "/etc/jifunze/jifunze.env"
    assert service["UMask"] == "0007"  # socket is group-only; Nginx joins the group
    assert service["MemoryMax"].endswith("G") or service["MemoryMax"].endswith("M")


def test_unit_uses_the_same_uvicorn_limits_as_make_run():
    makefile = (ROOT / "Makefile").read_text()
    limits = re.search(r"^UVICORN_LIMITS := (.+)$", makefile, re.M).group(1).split()
    exec_start = unit(SYSTEMD / "jifunze.service")["Service"]["ExecStart"]
    assert " ".join(limits) in " ".join(exec_start.replace("\\", " ").split())


def test_socket_path_agrees_across_unit_nginx_and_scripts():
    assert SOCKET in (NGINX / "jifunze.conf").read_text()
    assert SOCKET in (DEPLOY / "lib.sh").read_text()


def test_optimize_runs_sqlite_pragma_on_the_configured_database():
    exec_start = unit(SYSTEMD / "jifunze-optimize.service")["Service"]["ExecStart"]
    assert "${DATABASE_PATH}" in exec_start
    assert "PRAGMA optimize" in exec_start


# ---- nginx ------------------------------------------------------------------------------------
def test_nginx_security_headers_match_the_apps_csp():
    text = (NGINX / "jifunze-security-headers.conf").read_text()
    assert f'Content-Security-Policy "{CSP}"' in text
    for header in ("Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy"):
        assert header in text


def test_nginx_listens_locally_trusts_cloudflare_header_only_from_localhost():
    conf = (NGINX / "jifunze.conf").read_text()
    assert "listen 127.0.0.1:8080;" in conf
    directives = [line for line in conf.splitlines() if line.strip().startswith("set_real_ip_from")]
    assert directives == ["    set_real_ip_from 127.0.0.1;"]
    assert "set_real_ip_from 127.0.0.1;" in conf
    assert "real_ip_header CF-Connecting-IP;" in conf


def test_nginx_overwrites_the_client_ip_header_sent_to_the_app():
    proxy = (NGINX / "jifunze-proxy.conf").read_text()
    assert "proxy_set_header CF-Connecting-IP $remote_addr;" in proxy
    assert "proxy_set_header Host $http_host;" in proxy


def test_nginx_body_cap_matches_the_apps_default():
    conf = (NGINX / "jifunze.conf").read_text()
    assert Settings.from_env({}).max_body_bytes == 64 * 1024
    assert "client_max_body_size 64k;" in conf


def test_nginx_login_is_rate_limited_and_api_prefix_beats_static_regex():
    conf = (NGINX / "jifunze.conf").read_text()
    login = re.search(r"location = /api/login \{(.*?)\n    \}", conf, re.S).group(1)
    assert "limit_req zone=jifunze_login" in login
    assert "location ^~ /api/ {" in conf
    assert re.search(r"client_(header|body)_timeout", conf)


def test_nginx_has_a_maintenance_page_that_exists():
    conf = (NGINX / "jifunze.conf").read_text()
    assert "error_page 502 503 504 /maintenance.html;" in conf
    page = (ROOT / "web" / "maintenance.html").read_text()
    assert "<script" not in page and "style=" not in page


def test_nginx_syntax_if_nginx_is_available(tmp_path):
    binary = shutil.which("nginx")
    if binary is None:
        pytest.skip("nginx is not installed here; run it on the Pi: sudo nginx -t")
    snippets = tmp_path / "snippets"
    snippets.mkdir()
    for name in ("jifunze-proxy.conf", "jifunze-security-headers.conf"):
        shutil.copy(NGINX / name, snippets / name)
    conf = (NGINX / "jifunze.conf").read_text().replace("/etc/nginx/snippets", str(snippets))
    main = tmp_path / "nginx.conf"
    # Everything nginx would write (pid, logs, temp dirs) goes under tmp_path, so this also runs
    # as an unprivileged user (CI). mime.types is not needed to check the syntax.
    temp_paths = " ".join(
        f"{kind}_temp_path {tmp_path}/{kind};"
        for kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")
    )
    main.write_text(
        f"pid {tmp_path}/n.pid; error_log {tmp_path}/e.log; events {{}} "
        f"http {{ access_log {tmp_path}/a.log; {temp_paths} {conf} }}"
    )
    result = subprocess.run(  # noqa: S603
        [binary, "-t", "-p", str(tmp_path), "-e", str(tmp_path / "e.log"), "-c", str(main)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---- shell scripts ----------------------------------------------------------------------------
def test_shellcheck_is_clean():
    binary = ROOT / ".venv" / "bin" / "shellcheck"
    if not binary.exists():
        pytest.skip("shellcheck is not installed (pip install shellcheck-py)")
    scripts = [str(p) for p in sorted(DEPLOY.glob("*.sh"))]
    result = subprocess.run(  # noqa: S603
        [str(binary), "-x", "-P", "SCRIPTDIR", *scripts], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout


def test_scripts_are_executable_and_mention_the_migration_rule():
    for name in ("deploy.sh", "rollback.sh", "backup.sh", "healthcheck.sh"):
        assert (DEPLOY / name).stat().st_mode & 0o111, name
    header = (DEPLOY / "deploy.sh").read_text().split("set -euo")[0]
    assert "BACKWARD COMPATIBLE" in header


# ---- requirements.lock ------------------------------------------------------------------------
def test_lock_file_is_hash_pinned_and_covers_every_runtime_dependency():
    lock = (ROOT / "requirements.lock").read_text()
    entries = re.findall(r"^([A-Za-z0-9_.-]+)==\S+.*?(?=^\S|\Z)", lock, re.M | re.S)
    blocks = re.split(r"^(?=[A-Za-z0-9_.-]+==)", lock, flags=re.M)[1:]
    assert entries and len(blocks) == len(entries)
    for block in blocks:
        assert "--hash=sha256:" in block, block.splitlines()[0]
    pinned = {b.split("==")[0].lower().replace("_", "-") for b in blocks}
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    for dep in deps:
        name = re.split(r"[<>=\[ ;]", dep.split("#")[0].strip().strip('",'))[0]
        assert name.lower().replace("_", "-") in pinned, name
    assert "pytest" not in pinned and "ruff" not in pinned  # dev tools stay off the Pi


# ---- failure alert ----------------------------------------------------------------------------
def test_failure_alert_names_the_unit_and_includes_the_log_tail():
    sent = []

    class Capture(notify_failure.Backend):
        def send(self, to, subject, body):
            sent.append((to, subject, body))

    notify_failure.notify("jifunze-backup.service", "me@example.com", Capture(), "pi", "boom")
    ((to, subject, body),) = sent
    assert to == "me@example.com"
    assert "jifunze-backup.service" in subject and "pi" in subject
    assert "boom" in body


@pytest.mark.parametrize("name", ["", "ssh.service", "jifunze;rm -rf /", "../x.service", "jifunze"])
def test_failure_alert_refuses_unit_names_that_are_not_ours(name, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["notify_failure.py", name][: 2 if name else 1])
    assert notify_failure.main() == 2


def test_failure_alert_needs_an_address(monkeypatch):
    monkeypatch.setattr("sys.argv", ["notify_failure.py", "jifunze.service"])
    monkeypatch.delenv("ALERT_EMAIL", raising=False)
    assert notify_failure.main() == 1


def test_failure_alert_console_run(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["notify_failure.py", "jifunze-backup.service"])
    monkeypatch.setenv("ALERT_EMAIL", "me@example.com")
    monkeypatch.setenv("ALERT_BACKEND", "console")
    monkeypatch.setattr(notify_failure, "journal_tail", lambda unit: "disk full")
    assert notify_failure.main() == 0
    out = capsys.readouterr().out
    assert "me@example.com" in out and "disk full" in out


# ---- the Pi's environment file template -------------------------------------------------------
def test_pi_env_template_is_plain_key_value_and_loads_as_prod_settings():
    pairs = {}
    for line in (DEPLOY / "jifunze.env.example").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.fullmatch(r"[A-Z0-9_]+=[^\s'\"]*", line), line  # systemd and sh agree
            key, value = line.split("=", 1)
            pairs[key] = value
    pairs["SESSION_SECRET"] = "x" * 48
    settings = Settings.from_env(pairs)
    assert settings.app_env == "prod" and settings.cookie_secure
    assert settings.database_path == "/srv/jifunze/data/app.db"
    assert settings.backup_stamp_path == "/srv/jifunze/data/last_backup"
    assert pairs["EMBEDDER"] == "fake"  # the onnx model is switched on only after benchmarking
    assert pairs["EMBED_MODEL"] == "qint8"  # the small model, for a 2 GB Pi
    assert pairs["BACKUP_REQUIRE_MOUNT"] == "1"
