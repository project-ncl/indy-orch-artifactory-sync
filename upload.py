import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def urlopen_with_retry(req, *, timeout=300, retries=3, backoff=1, retry_on=(500, 502, 503, 504)):
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
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


def upload_one(entry, artifactory_url, auth_header):
    local_path = entry["local_path"]
    repo_name = entry["repo_name"]
    artifact_path = entry["artifact_path"]
    target_url = artifactory_url.rstrip("/") + f"/{repo_name}/{artifact_path}"

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
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel uploads (default: 4)")
    args = parser.parse_args()

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

    if args.dry_run:
        for entry in metadata:
            repo_name = entry["repo_name"]
            artifact_path = entry["artifact_path"]
            target_url = artifactory_url.rstrip("/") + f"/{repo_name}/{artifact_path}" if artifactory_url else None
            print(f"[DRY-RUN] {repo_name}/{artifact_path}")
            print(f"  local:  {entry['local_path']}")
            print(f"  PUT     {target_url or '(ARTIFACTORY_URL not set)'}")
        return

    success_count = 0
    fail_count = 0
    total = len(metadata)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(upload_one, entry, artifactory_url, auth_header): entry
            for entry in metadata
        }
        for i, future in enumerate(as_completed(futures), 1):
            entry = futures[future]
            repo_name = entry["repo_name"]
            artifact_path = entry["artifact_path"]
            try:
                future.result()
                success_count += 1
                print(f"[{i}/{total} {100*i//total}%] [OK]   {repo_name}/{artifact_path}")
            except Exception as e:
                fail_count += 1
                print(f"[{i}/{total} {100*i//total}%] [FAIL] {repo_name}/{artifact_path} — {e}")

    print(f"\nDone. uploaded={success_count} failed={fail_count}")


if __name__ == "__main__":
    main()
