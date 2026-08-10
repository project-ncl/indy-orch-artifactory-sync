import argparse
import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def urlopen_with_retry(req, *, timeout=300, retries=3, backoff=1, retry_on=(500, 502, 503, 504)):
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx)
        except urllib.error.HTTPError as e:
            if e.code in retry_on and attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_repo(entry, repo_map):
    pkg_type = entry.get("pkg_type", "")
    repo_name = entry["repo_name"]
    key = f"{pkg_type}:{repo_name}"
    if key not in repo_map:
        raise KeyError(f"no artifactory repo configured for {key}")
    return repo_map[key]


def upload_one(entry, artifactory_url, auth_header, repo_map):
    local_path = entry["local_path"]
    target_repo = resolve_repo(entry, repo_map)
    artifact_path = entry["artifact_path"]
    target_url = artifactory_url.rstrip("/") + f"/{target_repo}/{artifact_path}"

    if not os.path.exists(local_path):
        raise FileNotFoundError(f"file not found: {local_path}")

    checksum = sha256_file(local_path)
    with open(local_path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(
        target_url,
        data=data,
        method="PUT",
        headers={
            "X-Checksum-Sha256": checksum,
            "Authorization": auth_header,
        },
    )
    urlopen_with_retry(req, timeout=300)


def main():
    parser = argparse.ArgumentParser(description="Upload artifacts to Artifactory")
    parser.add_argument("--metadata", required=True, help="Path to the metadata.json file")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without uploading")
    parser.add_argument("--repo-config", default=os.path.join(os.path.dirname(__file__), "repo_config.json"),
                        help="Path to repo mapping config (default: repo_config.json)")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel uploads (default: 4)")
    parser.add_argument("--repos", nargs="+", metavar="TYPE:NAME",
                        help="Only upload for these repos (e.g. maven:shared-imports maven:pnc-builds). "
                             "If omitted, all repos are uploaded.")
    args = parser.parse_args()

    with open(args.repo_config) as f:
        repo_map = json.load(f)

    artifactory_url = os.environ.get("ARTIFACTORY_URL")
    artifactory_token = os.environ.get("ARTIFACTORY_TOKEN")

    if not args.dry_run:
        if not artifactory_url:
            sys.exit("Error: ARTIFACTORY_URL environment variable is required")
        if not artifactory_token:
            sys.exit("Error: ARTIFACTORY_TOKEN environment variable is required")

    auth_header = f"Bearer {artifactory_token}"

    with open(args.metadata) as f:
        metadata = json.load(f)

    if args.repos:
        allowed = set(args.repos)
        metadata = [e for e in metadata if f"{e.get('pkg_type', '')}:{e['repo_name']}" in allowed]
        if not metadata:
            print(f"No entries match --repos filter: {args.repos}")
            return

    if args.dry_run:
        for entry in metadata:
            target_repo = resolve_repo(entry, repo_map)
            artifact_path = entry["artifact_path"]
            target_url = artifactory_url.rstrip("/") + f"/{target_repo}/{artifact_path}" if artifactory_url else None
            print(f"[DRY-RUN] {target_repo}/{artifact_path}")
            print(f"  local:  {entry['local_path']}")
            print(f"  PUT     {target_url or '(ARTIFACTORY_URL not set)'}")
        return

    success_count = 0
    fail_count = 0
    failures = []
    total = len(metadata)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(upload_one, entry, artifactory_url, auth_header, repo_map): entry
            for entry in metadata
        }
        for i, future in enumerate(as_completed(futures), 1):
            entry = futures[future]
            target_repo = resolve_repo(entry, repo_map)
            artifact_path = entry["artifact_path"]
            try:
                future.result()
                success_count += 1
                print(f"[{i}/{total} {100*i//total}%] [OK]   {target_repo}/{artifact_path}")
            except Exception as e:
                fail_count += 1
                failures.append({"repo": target_repo, "artifact_path": artifact_path, "local_path": entry["local_path"], "error": str(e)})
                print(f"[{i}/{total} {100*i//total}%] [FAIL] {target_repo}/{artifact_path} — {e}")

    if failures:
        failures_file = os.path.splitext(args.metadata)[0] + "_upload_failures.json"
        with open(failures_file, "w") as f:
            json.dump(failures, f, indent=2)
        print(f"\nFailures written to {failures_file}")

    print(f"\nDone. uploaded={success_count} failed={fail_count}")


if __name__ == "__main__":
    main()
