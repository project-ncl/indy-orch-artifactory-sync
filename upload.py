import argparse
import hashlib
import json
import os
import sys

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry


def create_session(auth):
    session = requests.Session()
    session.auth = auth
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["PUT"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Upload artifacts to Artifactory")
    parser.add_argument("--metadata", required=True, help="Path to the metadata.json file")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without uploading")
    args = parser.parse_args()

    artifactory_url = os.environ.get("ARTIFACTORY_URL")
    artifactory_user = os.environ.get("ARTIFACTORY_USER")
    artifactory_password = os.environ.get("ARTIFACTORY_PASSWORD")

    if not args.dry_run:
        if not artifactory_url:
            sys.exit("Error: ARTIFACTORY_URL environment variable is required")
        if not artifactory_user or not artifactory_password:
            sys.exit("Error: ARTIFACTORY_USER and ARTIFACTORY_PASSWORD environment variables are required")

    auth = HTTPBasicAuth(artifactory_user or "", artifactory_password or "")
    session = create_session(auth)

    with open(args.metadata) as f:
        metadata = json.load(f)

    success_count = 0
    fail_count = 0

    for entry in metadata:
        local_path = entry["local_path"]
        repo_name = entry["repo_name"]
        artifact_path = entry["artifact_path"]
        target_url = artifactory_url.rstrip("/") + f"/{repo_name}/{artifact_path}" if artifactory_url else None

        if args.dry_run:
            print(f"[DRY-RUN] {repo_name}/{artifact_path}")
            print(f"  local:  {local_path}")
            print(f"  PUT     {target_url or '(ARTIFACTORY_URL not set)'}")
            continue

        if not os.path.exists(local_path):
            print(f"[FAIL] file not found: {local_path}")
            fail_count += 1
            continue

        try:
            checksum = sha256_file(local_path)
            with open(local_path, "rb") as f:
                upload = session.put(
                    target_url,
                    data=f,
                    headers={"X-Checksum-Sha256": checksum},
                    timeout=300,
                )
                upload.raise_for_status()
            print(f"[OK]   {repo_name}/{artifact_path}")
            success_count += 1
        except requests.RequestException as e:
            print(f"[FAIL] {repo_name}/{artifact_path} — {e}")
            fail_count += 1

    print(f"\nDone. uploaded={success_count} failed={fail_count}")


if __name__ == "__main__":
    main()
