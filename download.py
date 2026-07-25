import argparse
import csv
import json
import os
import re
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def parse_indy_path(api_path):
    match = re.match(r"/api/content/([^/]+)/[^/]+/([^/]+)/(.*)", api_path)
    if not match:
        return None, None, None
    return match.group(1), match.group(2), match.group(3)


def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def main():
    parser = argparse.ArgumentParser(description="Download artifacts from Indy")
    parser.add_argument("--csv", required=True, help="Path to the CSV file")
    parser.add_argument("--output-dir", required=True, help="Directory to download artifacts into")
    args = parser.parse_args()

    indy_url = os.environ.get("INDY_URL")
    if not indy_url:
        sys.exit("Error: INDY_URL environment variable is required")

    os.makedirs(args.output_dir, exist_ok=True)
    session = create_session()

    metadata = []
    success_count = 0
    fail_count = 0
    skip_count = 0

    with open(args.csv, newline="") as f:
        reader = csv.reader(f)
        for line_num, row in enumerate(reader, 1):
            full_path = row[0] + row[1]
            full_path = re.sub(r"/{2,}", "/", full_path)

            pkg_type, repo_name, artifact_path = parse_indy_path(full_path)
            if not pkg_type:
                print(f"[SKIP] line {line_num}: cannot parse path: {full_path}")
                skip_count += 1
                continue

            source_url = indy_url.rstrip("/") + full_path
            local_path = os.path.join(args.output_dir, repo_name, artifact_path)
            tmp_path = local_path + ".tmp"
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            try:
                with session.get(source_url, stream=True, timeout=120) as dl:
                    dl.raise_for_status()
                    with open(tmp_path, "wb") as out:
                        for chunk in dl.iter_content(chunk_size=8192):
                            out.write(chunk)
                os.rename(tmp_path, local_path)
                print(f"[OK]   line {line_num}: {repo_name}/{artifact_path}")
                metadata.append({
                    "local_path": local_path,
                    "repo_name": repo_name,
                    "artifact_path": artifact_path,
                })
                success_count += 1
            except requests.RequestException as e:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                print(f"[FAIL] line {line_num}: {repo_name}/{artifact_path} — {e}")
                fail_count += 1

    metadata_file = os.path.join(args.output_dir, "metadata.json")
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nDone. downloaded={success_count} failed={fail_count} skipped={skip_count}")
    print(f"Metadata written to {metadata_file}")


if __name__ == "__main__":
    main()
