"""
Full-database encrypted backup, restore and restore drill (inspection finding F-26;
controls 54-56; AGENTS.md section 7).

Why: scripts/backup_database.py exports only 10 identity tables through the ORM (no
orders, quotes, invoices, inventory, conversations, voice data ...) and derives its key
from the JWT secret. It is not a disaster-recovery backup.

This tool:
  * dumps the WHOLE database with pg_dump (custom format: schema, RLS policies, functions,
    grants and data), streamed - the plaintext dump never touches disk;
  * encrypts it with AES-256-GCM in 1 MiB chunks. Each chunk's nonce is a random 8-byte
    prefix plus a counter, and its AAD binds the chunk index and a final-chunk flag, so
    reordering, truncation or appended data is detected;
  * uses a dedicated 256-bit key from BACKUP_ENCRYPTION_KEY (base64url or hex), never an
    application secret;
  * writes a manifest (SHA-256 of the ciphertext, per-table row counts, PG version) and can
    copy both files to an off-site location (--copy-to), re-verifying the checksum there;
  * restore: verifies checksum, decrypts in a stream into pg_restore, into a NEW database;
  * drill: backup -> restore into a scratch database -> compare every table's row count
    and the RLS/policy catalogue with the source -> report measured duration (RTO for
    this dataset) -> drop the scratch database.

PostgreSQL client tools are used inside the database container by default
(--container sales-ai-postgres); use --container "" to run local pg_dump/pg_restore.
"""
import argparse
import base64
import binascii
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"SAIBK2\n"
CHUNK = 1 << 20


class BackupError(RuntimeError):
    pass


def load_key(raw: str | None = None) -> bytes:
    raw = raw or os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    if not raw:
        raise BackupError("BACKUP_ENCRYPTION_KEY is required (32 random bytes, base64url or hex)")
    for decode in (lambda s: binascii.unhexlify(s), lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))):
        try:
            key = decode(raw.strip())
            if len(key) == 32:
                return key
        except (binascii.Error, ValueError):
            continue
    raise BackupError("BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes")


def _aad(index: int, final: bool) -> bytes:
    return MAGIC + struct.pack(">I?", index, final)


def encrypt_stream(src, dst, key: bytes) -> None:
    aes, prefix = AESGCM(key), os.urandom(8)
    dst.write(MAGIC + prefix)
    index, block = 0, src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK) if block else b""
        final = not nxt
        ct = aes.encrypt(prefix + struct.pack(">I", index), block, _aad(index, final))
        dst.write(struct.pack(">I", len(ct)) + ct)
        if final:
            return
        index, block = index + 1, nxt


def decrypt_stream(src, dst, key: bytes) -> None:
    if src.read(len(MAGIC)) != MAGIC:
        raise BackupError("not a Sales AI backup file (bad magic)")
    aes, prefix, index = AESGCM(key), src.read(8), 0
    while True:
        header = src.read(4)
        if len(header) < 4:
            raise BackupError("backup truncated (no final chunk)")
        ct = src.read(struct.unpack(">I", header)[0])
        try:  # the final flag is authenticated: try "not final" first, then "final"
            dst.write(aes.decrypt(prefix + struct.pack(">I", index), ct, _aad(index, False)))
        except Exception:
            try:
                dst.write(aes.decrypt(prefix + struct.pack(">I", index), ct, _aad(index, True)))
            except Exception as exc:
                raise BackupError("authentication failed: wrong key or tampered backup") from exc
            if src.read(1):
                raise BackupError("data after the final chunk")
            return
        index += 1


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def _tool(container: str, *args: str, stdin=None):
    cmd = (["docker", "exec", "-i", container] if container else []) + list(args)
    return subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def table_counts(url: str) -> dict:
    with psycopg.connect(url) as c:
        tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")]
        return {t: c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def security_catalog(url: str) -> dict:
    with psycopg.connect(url) as c:
        return {
            "rls_forced_tables": c.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                           "WHERE n.nspname='public' AND c.relkind='r' AND c.relforcerowsecurity").fetchone()[0],
            "policies": c.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public'").fetchone()[0],
            "functions": c.execute("SELECT count(*) FROM pg_proc WHERE pronamespace='public'::regnamespace").fetchone()[0],
        }


def backup(url: str, db: str, user: str, out_dir: Path, key: bytes, container: str, copy_to: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    enc_path = out_dir / f"{db}_{stamp}.dump.enc"
    started = time.perf_counter()
    counts = table_counts(url)  # snapshot just before the dump (informational)
    proc = _tool(container, "pg_dump", "-U", user, "-d", db, "-Fc", "--no-owner")
    with open(enc_path, "wb") as dst:
        encrypt_stream(proc.stdout, dst, key)
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        enc_path.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed: {err.strip()[:300]}")
    with psycopg.connect(url) as c:
        pg_version = c.execute("SHOW server_version").fetchone()[0]
    manifest = {
        "format": "SAIBK2 (pg_dump custom format, AES-256-GCM 1 MiB chunks)",
        "database": db, "created_at": stamp, "postgres_version": pg_version,
        "file": enc_path.name, "size_bytes": enc_path.stat().st_size,
        "sha256": sha256_file(enc_path), "tables": len(counts), "row_counts": counts,
        "duration_s": round(time.perf_counter() - started, 3),
    }
    man_path = enc_path.with_suffix(".manifest.json")
    man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if copy_to:
        copy_to.mkdir(parents=True, exist_ok=True)
        for p in (enc_path, man_path):
            shutil.copy2(p, copy_to / p.name)
        if sha256_file(copy_to / enc_path.name) != manifest["sha256"]:
            raise BackupError("off-site copy checksum mismatch")
        manifest["offsite_copy"] = str(copy_to / enc_path.name)
    manifest["path"] = str(enc_path)
    return manifest


def restore(enc_path: Path, admin_url: str, target_db: str, user: str, key: bytes, container: str) -> float:
    manifest = json.loads(enc_path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if sha256_file(enc_path) != manifest["sha256"]:
        raise BackupError("checksum mismatch: backup file altered or corrupted")
    with psycopg.connect(admin_url, autocommit=True) as c:
        if c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target_db,)).fetchone():
            raise BackupError(f"target database {target_db} already exists (restore never overwrites)")
        c.execute(f'CREATE DATABASE "{target_db}"')
    started = time.perf_counter()
    proc = _tool(container, "pg_restore", "-U", user, "-d", target_db, "--no-owner", "--exit-on-error", stdin=subprocess.PIPE)
    try:
        with open(enc_path, "rb") as src:
            decrypt_stream(src, proc.stdin, key)
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise BackupError(f"pg_restore failed: {err.strip()[:300]}")
    return time.perf_counter() - started


def drill(args, key: bytes) -> dict:
    base = args.admin_url.rsplit("/", 1)[0]
    source = f"{base}/{args.db}"
    scratch = f"{args.db}_restore_drill"
    with psycopg.connect(args.admin_url, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
    report = {"started_at": datetime.now(timezone.utc).isoformat()}
    try:
        m = backup(source, args.db, args.user, Path(args.out), key, args.container, Path(args.copy_to) if args.copy_to else None)
        # Counts at restore time are compared with counts taken *after* the dump, from the
        # same source; a busy production database needs a quiesced window for exact equality.
        after = table_counts(source)
        restore_s = restore(Path(m["path"]), args.admin_url, scratch, args.user, key, args.container)
        restored = table_counts(f"{base}/{scratch}")
        mismatched = {t: (after.get(t), restored.get(t)) for t in set(after) | set(restored) if after.get(t) != restored.get(t)}
        src_sec, dst_sec = security_catalog(source), security_catalog(f"{base}/{scratch}")
        report.update({
            "backup": {k: v for k, v in m.items() if k not in ("row_counts", "path")},
            "restore_duration_s": round(restore_s, 3),
            "tables_compared": len(after), "rows_compared": sum(after.values()),
            "row_count_mismatches": mismatched,
            "security_catalog_source": src_sec, "security_catalog_restored": dst_sec,
            "result": "PASS" if not mismatched and src_sec == dst_sec else "FAIL",
        })
        # Negative checks: a wrong key and a tampered file must both be refused.
        wrong = os.urandom(32)
        try:
            with open(m["path"], "rb") as f:
                decrypt_stream(f, open(os.devnull, "wb"), wrong)
            report["wrong_key_rejected"] = False
        except BackupError:
            report["wrong_key_rejected"] = True
        tampered = Path(m["path"] + ".tampered")
        data = bytearray(Path(m["path"]).read_bytes()); data[len(data) // 2] ^= 0x01
        tampered.write_bytes(bytes(data))
        try:
            with open(tampered, "rb") as f:
                decrypt_stream(f, open(os.devnull, "wb"), key)
            report["tamper_rejected"] = False
        except BackupError:
            report["tamper_rejected"] = True
        finally:
            tampered.unlink(missing_ok=True)
        truncated = Path(m["path"] + ".truncated")
        truncated.write_bytes(Path(m["path"]).read_bytes()[:-100])
        try:
            with open(truncated, "rb") as f:
                decrypt_stream(f, open(os.devnull, "wb"), key)
            report["truncation_rejected"] = False
        except BackupError:
            report["truncation_rejected"] = True
        finally:
            truncated.unlink(missing_ok=True)
    finally:
        with psycopg.connect(args.admin_url, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=["backup", "restore", "drill"])
    p.add_argument("--admin-url", default=os.environ.get("BACKUP_ADMIN_URL", ""),
                   help="owner connection to the 'postgres' maintenance DB, e.g. postgresql://postgres:...@host:5432/postgres")
    p.add_argument("--db", default="sales_ai_db")
    p.add_argument("--user", default="postgres", help="role used by pg_dump/pg_restore inside the container")
    p.add_argument("--container", default="sales-ai-postgres")
    p.add_argument("--out", default="backups")
    p.add_argument("--copy-to", help="off-site directory (mounted remote storage) for a verified second copy")
    p.add_argument("--file", help="restore: encrypted backup file")
    p.add_argument("--target-db", help="restore: new database name (never overwrites)")
    p.add_argument("--report", help="drill: write the JSON report here")
    a = p.parse_args(argv)
    if not a.admin_url:
        print("--admin-url or BACKUP_ADMIN_URL is required", file=sys.stderr)
        return 2
    try:
        key = load_key()
        if a.command == "backup":
            m = backup(a.admin_url.rsplit("/", 1)[0] + "/" + a.db, a.db, a.user, Path(a.out), key, a.container,
                       Path(a.copy_to) if a.copy_to else None)
            print(json.dumps({k: v for k, v in m.items() if k != "row_counts"}, indent=1))
        elif a.command == "restore":
            if not (a.file and a.target_db):
                raise BackupError("restore needs --file and --target-db")
            print(f"restored into {a.target_db} in {restore(Path(a.file), a.admin_url, a.target_db, a.user, key, a.container):.2f}s")
        else:
            r = drill(a, key)
            text = json.dumps(r, indent=1)
            if a.report:
                Path(a.report).write_text(text, encoding="utf-8")
            print(text)
            return 0 if r["result"] == "PASS" and r["wrong_key_rejected"] and r["tamper_rejected"] and r["truncation_rejected"] else 1
    except BackupError as exc:
        print(f"BACKUP ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
