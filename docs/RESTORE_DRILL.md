# Restore drill: prove a backup brings the dictionary back

A backup you have never restored is a hope. This drill takes the newest backup, restores it into a
clean temporary directory and checks it. It never touches the live database or the backup file. Do it
once before going live (`docs/GO_LIVE.md`) and again after any change to the schema or the backup job.

## What it checks

`scripts/restore_drill.py` (run through `make restore-drill`):

1. `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the restored copy.
2. The migrations recorded in the backup match the files in the code you are running. A backup older
   than the code is fine (it says which migrations the next deploy will apply); an edited one is not.
3. The full-text index agrees with the entries table.
4. Row counts of every table, backup file against restored copy, and optional `--expect NAME=COUNT`
   values that you copy from the live app.
5. At least one admin account exists, so someone can sign in after a restore.

It exits 0 only if everything passes, and prints `RESTORE DRILL FAILED` otherwise.

## On your Mac, with a sample backup (needs no Pi)

```
make migrate && make seed                 # a scratch database with the 12 verified entries
make create-user NAME=drill ROLE=admin   # restore needs an admin to be meaningful
mkdir -p data/backups
sqlite3 data/app.db ".backup 'data/backups/app-20261013T030000Z.db'"
make restore-drill ARGS="--backup-dir data/backups --expect entries=12"
```
Use a scratch `DATABASE_PATH` (in `.env`) if you do not want to touch your working database.
Expected: every line `ok` and `restore drill passed`.

## On the Pi, with a real backup

The backups are in `/srv/jifunze/backups` (the SSD). The drill reads them and writes only to a
temporary directory (`/tmp`, a few MB), so it is safe while the app is running.

```
cd /srv/jifunze/current && sudo -u jifunze bash -c \
  'set -a; . /etc/jifunze/jifunze.env; set +a; PYTHONPATH=. .venv/bin/python scripts/restore_drill.py --backup-dir /srv/jifunze/backups'
```
To make it meaningful, first read the live counts in the app (Add and Review screens, or
`sqlite3 /srv/jifunze/data/app.db 'select count(*) from entries'`) and pass them:
`--expect entries=<n> --expect users=<n>`. A nightly backup can legitimately be a day behind; the
comparison you care about is that the restored copy has what the backup file has.
Use `--backup FILE` for a specific file (for example the off-device copy) and `--keep` to leave
the restored database at the printed path for a look with `sqlite3`.

## The full restore (when the live database is gone)

The drill proves the file; this is the procedure it rehearses (also in `docs/PI_SETUP.md` section E):

1. `sudo systemctl stop jifunze`
2. Pick the newest file that passes the drill. Copy it over `/srv/jifunze/data/app.db`.
3. Delete `app.db-wal` and `app.db-shm` next to it (stale logs would be applied to the wrong file).
4. `sudo chown jifunze:jifunze /srv/jifunze/data/app.db`
5. `sudo systemctl start jifunze`, then `deploy/healthcheck.sh`, sign in, and look at the entries.

If the restored database is older than the running code, the app refuses to start and says which
migrations are pending. Apply them with the env file loaded: `python -m app.migrate` from
`/srv/jifunze/current` (a normal deploy does this for you at step 4 of 9).

## When it fails

- `integrity_check` or "cannot be read": that backup file is damaged. Try the next older one and
  check the SSD (`dmesg`, `sudo fsck.exfat`). Then look at the off-device copy.
- "differ from the files in this checkout": run the drill from the release that made the backup
  (`/srv/jifunze/releases/<tag>`), or find which migration file was edited.
- "no admin account": the backup is usable but you cannot sign in. Restore it, then create an admin with
  `scripts/create_user.py --role admin`.
