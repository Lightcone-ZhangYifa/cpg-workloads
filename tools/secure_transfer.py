"""Move authorized Library bytes to one ephemeral Actions runner without URL logs.

Public request: {schema_version: 1, source_commit: SHA40, inputs: [
  {id, library_file_id, file_id?, file_name?, bytes, sha256}]}
Envelope: {schema_version: 1, binding: challenge.binding,
           transfers: [{id, spec: <unchanged official transfer object>}]}
Only the public certificate and binding are committed by this module. Workload
admission/publication and deleting the transport branch belong to its caller.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "Lightcone-ZhangYifa/cpg-workloads"
CHALLENGE = ".transfer/challenge.json"
CERTIFICATE = ".transfer/certificate.pem"
ENVELOPE = ".transfer/envelope.cms.b64"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")


class TransferError(RuntimeError):
    """A diagnostic deliberately containing no URL, header, token or plaintext."""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode()


def _command(argv, *, data=None, env=None, check=True):
    result = subprocess.run(argv, input=data, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise TransferError("Transfer subprocess failed: " + Path(argv[0]).name) from None
    return result


def _git(*args, **kwargs):
    return _command(["git", *args], **kwargs)


def _validate_request(request, branch):
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF_NAME") != branch
            or not re.fullmatch(r"transport/secure-[a-zA-Z0-9._-]+", branch)):
        raise TransferError("Transfer must run on its canonical dedicated branch")
    if (request.get("schema_version") != 1
            or not _SHA40.fullmatch(str(request.get("source_commit", "")))):
        raise TransferError("Invalid public transfer request")
    inputs = request.get("inputs")
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 20:
        raise TransferError("A transfer request needs 1 to 20 identified inputs")
    identifiers = set()
    for row in inputs:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"] or row["id"] in identifiers
                or not isinstance(row.get("library_file_id"), str)
                or not row["library_file_id"] or type(row.get("bytes")) is not int
                or row["bytes"] <= 0 or not _SHA256.fullmatch(str(row.get("sha256", "")))):
            raise TransferError("Invalid or duplicate input identity/byte lock")
        identifiers.add(row["id"])
    # A caller must not accidentally put a private transfer object in its public plan.
    def check_public(value):
        if isinstance(value, dict):
            if any(str(k).lower() in {"download_url", "headers", "completion_token",
                                     "authorization", "private_key"} for k in value):
                raise TransferError("Public request contains a private transfer field")
            for child in value.values():
                check_public(child)
        elif isinstance(value, list):
            for child in value:
                check_public(child)
    check_public(request)
    return inputs


def _publish_challenge(branch, challenge, certificate, private):
    ref = "refs/heads/" + branch
    _git("fetch", "--no-tags", "origin", ref)
    base = _git("rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if base != os.environ["GITHUB_SHA"]:
        raise TransferError("Transport branch advanced before this job created its challenge")
    index_env = dict(os.environ, GIT_INDEX_FILE=str(private / "public-index"),
                     GIT_AUTHOR_NAME="github-actions[bot]",
                     GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
                     GIT_COMMITTER_NAME="github-actions[bot]",
                     GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    _git("read-tree", base, env=index_env)
    for name, raw in ((CHALLENGE, canonical(challenge) + b"\n"), (CERTIFICATE, certificate)):
        blob = _git("hash-object", "-w", "--stdin", data=raw).stdout.decode().strip()
        _git("update-index", "--add", "--cacheinfo", "100644", blob, name, env=index_env)
    _git("update-index", "--force-remove", "--", ENVELOPE, env=index_env)
    tree = _git("write-tree", env=index_env).stdout.decode().strip()
    commit = _git("commit-tree", tree, "-p", base, env=index_env,
                  data=b"Open ephemeral workload transfer challenge\n").stdout.decode().strip()
    _git("push", "origin", commit + ":" + ref)
    print(json.dumps({"transfer": "challenge_ready", "branch": branch,
                      "challenge_commit": commit, "request_digest": challenge["binding"]["request_digest"]}),
          flush=True)


def _read_envelope(branch, challenge, certificate, timeout):
    deadline = time.monotonic() + timeout
    expected_challenge = canonical(challenge) + b"\n"
    while time.monotonic() < deadline:
        _git("fetch", "--quiet", "--no-tags", "origin", "refs/heads/" + branch)
        if (_git("show", "FETCH_HEAD:" + CHALLENGE).stdout != expected_challenge
                or _git("show", "FETCH_HEAD:" + CERTIFICATE).stdout != certificate):
            raise TransferError("Public challenge changed while this job was waiting")
        value = _git("show", "FETCH_HEAD:" + ENVELOPE, check=False)
        if value.returncode == 0:
            if len(value.stdout) > 1024 * 1024:
                raise TransferError("Encrypted response exceeds the bounded transfer envelope")
            try:
                return base64.b64decode(value.stdout.strip(), validate=True)
            except ValueError:
                raise TransferError("Encrypted response is not valid base64") from None
        time.sleep(5)
    raise TransferError("Timed out waiting for the encrypted transfer response")


def _decrypt(encrypted, certificate, key, binding):
    description = _command(["openssl", "cms", "-cmsout", "-print", "-inform", "DER"],
                           data=encrypted).stdout
    if b"aes-256-gcm" not in description or b"rsaesOaep" not in description:
        raise TransferError("Transfer envelope must use authenticated CMS encryption and RSA OAEP")
    result = _command(["openssl", "cms", "-decrypt", "-binary", "-inform", "DER",
                       "-recip", str(certificate), "-inkey", str(key)], data=encrypted, check=False)
    if result.returncode:
        raise TransferError("Encrypted response failed authentication/decryption")
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise TransferError("Authenticated transfer response is not JSON") from None
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("binding") != binding:
        raise TransferError("Transfer response does not match this job's exact public binding")
    return value


class _CheckedRedirect(HTTPRedirectHandler):
    def __init__(self, has_official_headers=False):
        super().__init__()
        self.has_official_headers = has_official_headers

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlparse(req.full_url), urlparse(newurl)
        if new.scheme != "https" or not new.hostname or new.username or new.password:
            raise TransferError("Transfer redirect is not credential-free HTTPS")
        if old.hostname != new.hostname and self.has_official_headers:
            raise TransferError("Transfer redirect would forward credentials to a different host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(row, spec, destination):
    if (not isinstance(spec, dict) or spec.get("workspace_path") is not None
            or spec.get("library_file_id") != row["library_file_id"]
            or type(spec.get("size_bytes")) is not int or spec["size_bytes"] != row["bytes"]):
        raise TransferError("Official transfer identity/size differs from the authorized request")
    for name in ("file_id", "file_name"):
        if row.get(name) and spec.get(name) != row[name]:
            raise TransferError("Official transfer file/version differs from the requested input")
    url, method, headers = spec.get("download_url"), spec.get("method"), spec.get("headers")
    if not isinstance(url, str) or not isinstance(method, str) or not isinstance(headers, dict):
        raise TransferError("Official signed transfer specification is incomplete")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise TransferError("Official signed transfer requires credential-free HTTPS")
    if method != "GET":
        raise TransferError("This receive-only transport supports the official GET method")
    if any(not isinstance(k, str) or not isinstance(v, str) or "\n" in k + v or "\r" in k + v
           for k, v in headers.items()):
        raise TransferError("Official transfer headers are invalid")
    if shutil.disk_usage(destination.parent).free < row["bytes"] + 512 * 1024 * 1024:
        raise TransferError("Runner has insufficient free space for this locked input")
    temporary = destination.with_suffix(".part")
    digest, observed = hashlib.sha256(), 0
    try:
        request = Request(url, method=method, headers=headers)
        with build_opener(_CheckedRedirect(bool(headers))).open(request, timeout=90) as response:
            if response.status != 200:
                raise TransferError("Whole-file transfer returned an unexpected HTTP status")
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdecimal() or int(declared) != row["bytes"]):
                raise TransferError("Transfer response size differs from the public byte lock")
            with temporary.open("xb") as target:
                while block := response.read(1024 * 1024):
                    observed += len(block)
                    if observed > row["bytes"]:
                        raise TransferError("Transfer exceeded its public byte lock")
                    digest.update(block)
                    target.write(block)
        if observed != row["bytes"] or digest.hexdigest() != row["sha256"]:
            raise TransferError("Downloaded bytes differ from the public SHA-256/size lock")
        os.link(temporary, destination)
    except TransferError:
        raise
    except HTTPError as error:
        raise TransferError("Signed transfer failed with HTTP status " + str(error.code)) from None
    except (URLError, TimeoutError, OSError):
        raise TransferError("Signed transfer failed due to a network or local-file error") from None
    except Exception:
        # urllib/SSL/parser exceptions can embed a complete signed request URL.
        raise TransferError("Signed transfer failed while processing the official response") from None
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"transfer": "download_verified", "id": row["id"],
                      "bytes": observed, "sha256": row["sha256"]}), flush=True)
    return destination


def _materialize_reader(descriptor, encrypted_value, destination):
    """Materialize only an independently pinned Python reader from the CMS body."""
    if (not isinstance(descriptor, dict) or not _SHA40.fullmatch(str(descriptor.get("source_commit", "")))
            or not _SHA256.fullmatch(str(descriptor.get("sha256", "")))
            or type(descriptor.get("bytes")) is not int or not 0 < descriptor["bytes"] <= 768 * 1024
            or not isinstance(encrypted_value, dict) or set(encrypted_value) != {"archive_base64"}
            or not isinstance(encrypted_value["archive_base64"], str)):
        raise TransferError("Encrypted format reader lacks its pinned identity")
    try:
        packed = base64.b64decode(encrypted_value["archive_base64"], validate=True)
    except ValueError:
        raise TransferError("Encrypted format reader is not valid base64") from None
    if len(packed) != descriptor["bytes"] or hashlib.sha256(packed).hexdigest() != descriptor["sha256"]:
        raise TransferError("Encrypted format reader differs from its full byte lock")
    rows = descriptor.get("files")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise TransferError("Format reader lacks a bounded complete file inventory")
    expected, total = {}, 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise TransferError("Invalid pinned reader path")
        name = row["path"]
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or path.as_posix() != name
                or not name.startswith("src/compiler_playground/") or not name.endswith(".py")
                or name in expected or type(row.get("bytes")) is not int or row["bytes"] < 0
                or not _SHA256.fullmatch(str(row.get("sha256", "")))):
            raise TransferError("Invalid pinned reader file identity")
        expected[name] = row
        total += row["bytes"]
    if total > 8 * 1024 * 1024:
        raise TransferError("Pinned reader exceeds its expanded size bound")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise TransferError("Refusing to overwrite an existing format reader")
    destination.mkdir(mode=0o700)
    found = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
            for member in archive:
                row = expected.get(member.name)
                if (row is None or member.name in found or not member.isreg() or member.issparse()
                        or member.size != row["bytes"] or member.mode != 0o644):
                    raise TransferError("Format reader contains an unplanned archive member")
                raw = archive.extractfile(member).read(member.size + 1)
                if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                    raise TransferError("Format reader member differs from its pinned identity")
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(raw)
                target.chmod(0o600)
                found.add(member.name)
        if found != set(expected):
            raise TransferError("Format reader is missing pinned source files")
    except BaseException:
        shutil.rmtree(destination)
        raise


def receive(request: dict, branch: str, scratch: Path, *, wait_seconds: int = 1800,
            reader_destination: Path | None = None) -> list[Path]:
    """Receive locked files; retain downloads for the caller and remove private state."""
    inputs = _validate_request(request, branch)
    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    outputs = []
    with tempfile.TemporaryDirectory(prefix="secure-transfer-", dir=scratch) as directory:
        private = Path(directory)
        private.chmod(0o700)
        key, cert = private / "key.pem", private / "certificate.pem"
        _command(["openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "1",
                  "-subj", "/CN=cpg-ephemeral-workload-transfer", "-keyout", str(key), "-out", str(cert)])
        key.chmod(0o600)
        certificate = cert.read_bytes()
        binding = {"repository": REPOSITORY, "branch": branch,
                   "request_digest": hashlib.sha256(canonical(request)).hexdigest(),
                   "source_commit": request["source_commit"], "workflow_commit": os.environ["GITHUB_SHA"],
                   "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                   "nonce": secrets.token_hex(32), "certificate_sha256": hashlib.sha256(certificate).hexdigest()}
        challenge = {"schema_version": 1, "kind": "cpg_ephemeral_transfer_challenge", "binding": binding,
                     "created_at": datetime.now(timezone.utc).isoformat(),
                     "cipher": "CMS-AES-256-GCM-RSA-OAEP-SHA256"}
        _publish_challenge(branch, challenge, certificate, private)
        encrypted = _read_envelope(branch, challenge, certificate, wait_seconds)
        envelope = _decrypt(encrypted, cert, key, binding)
        if reader_destination is not None:
            descriptor = request.get("format_reader")
            if not isinstance(descriptor, dict) or descriptor.get("source_commit") != request.get("framework_commit"):
                raise TransferError("Format reader differs from the requested framework source")
            _materialize_reader(descriptor, envelope.get("format_reader"), reader_destination)
        elif "format_reader" in envelope:
            raise TransferError("This transfer did not request a private format reader")
        transfers = envelope.get("transfers")
        if (not isinstance(transfers, list) or len(transfers) != len(inputs)
                or any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
                       for item in transfers)):
            raise TransferError("Encrypted response has an invalid transfer list")
        by_id = {item["id"]: item.get("spec") for item in transfers}
        if len(by_id) != len(transfers) or set(by_id) != {row["id"] for row in inputs}:
            raise TransferError("Encrypted transfer list differs from the authorized input set")
        try:
            for index, row in enumerate(inputs):
                destination = scratch / ("input-" + str(index).zfill(3) + "-" + row["sha256"] + ".archive")
                if destination.exists() or destination.is_symlink():
                    raise TransferError("Refusing to overwrite an existing transfer destination")
                outputs.append(_download(row, by_id[row["id"]], destination))
        except BaseException:
            for path in outputs:
                path.unlink(missing_ok=True)
            raise
    return outputs


def seal_response(challenge: dict, certificate: bytes, transfers: list[dict], *,
                  format_reader_archive: bytes | None = None) -> str:
    """Encrypt a local official transfer specification; return only public ciphertext."""
    binding = challenge.get("binding", {})
    if (challenge.get("schema_version") != 1 or binding.get("repository") != REPOSITORY
            or binding.get("certificate_sha256") != hashlib.sha256(certificate).hexdigest()):
        raise TransferError("Public certificate differs from the selected challenge")
    envelope = {"schema_version": 1, "binding": binding, "transfers": transfers}
    if format_reader_archive is not None:
        envelope["format_reader"] = {"archive_base64": base64.b64encode(format_reader_archive).decode("ascii")}
    plaintext = canonical(envelope)
    with tempfile.TemporaryDirectory(prefix="cpg-public-cert-") as directory:
        cert = Path(directory) / "certificate.pem"
        cert.write_bytes(certificate)
        result = _command(["openssl", "cms", "-encrypt", "-binary", "-aes-256-gcm", "-outform", "DER",
                           "-recip", str(cert), "-keyopt", "rsa_padding_mode:oaep",
                           "-keyopt", "rsa_oaep_md:sha256"], data=plaintext)
    encoded = base64.b64encode(result.stdout).decode("ascii") + "\n"
    if len(encoded) > 1024 * 1024:
        raise TransferError("Encrypted response exceeds the bounded transfer envelope")
    return encoded
