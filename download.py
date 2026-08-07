import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def parse_indy_path(api_path):
    match = re.match(r"/api/content/([^/]+)/[^/]+/([^/]+)/(.*)", api_path)
    if not match:
        return None, None, None
    return match.group(1), match.group(2), match.group(3)


def urlopen_with_retry(req, *, timeout=120, retries=3, backoff=1, retry_on=(500, 502, 503, 504)):
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


def download_one(source_url, local_path, line_num, pkg_type, repo_name, artifact_path, buildrecord_id):
    tmp_path = local_path + ".tmp"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        with urlopen_with_retry(source_url, timeout=120) as resp:
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    out.write(chunk)
        os.rename(tmp_path, local_path)
        return {
            "local_path": local_path,
            "pkg_type": pkg_type,
            "repo_name": repo_name,
            "artifact_path": artifact_path,
            "buildrecord_id": buildrecord_id,
        }
    except (urllib.error.URLError, TimeoutError) as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def main():
    parser = argparse.ArgumentParser(description="Download artifacts from Indy")
    parser.add_argument("--csv", required=True, help="Path to the CSV file")
    parser.add_argument("--output-dir", required=True, help="Directory to download artifacts into")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel downloads (default: 4)")
    args = parser.parse_args()

    indy_url = os.environ.get("INDY_URL")
    if not indy_url:
        sys.exit("Error: INDY_URL environment variable is required")

    os.makedirs(args.output_dir, exist_ok=True)

    work_items = []
    skip_count = 0

    with open(args.csv, newline="") as f:
        reader = csv.reader(f)
        for line_num, row in enumerate(reader, 1):
            full_path = row[0] + row[1]
            full_path = re.sub(r"/{2,}", "/", full_path)

            buildrecord_id = row[2].strip() if len(row) > 2 else ""

            pkg_type, repo_name, artifact_path = parse_indy_path(full_path)
            if not pkg_type:
                print(f"[SKIP] line {line_num}: cannot parse path: {full_path}")
                skip_count += 1
                continue

            source_url = indy_url.rstrip("/") + full_path
            local_path = os.path.join(args.output_dir, repo_name, artifact_path)
            work_items.append((source_url, local_path, line_num, pkg_type, repo_name, artifact_path, buildrecord_id))

    metadata = []
    fail_count = 0
    total = len(work_items)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(download_one, *item): item
            for item in work_items
        }
        for i, future in enumerate(as_completed(futures), 1):
            item = futures[future]
            _, _, line_num, _, repo_name, artifact_path, _ = item
            try:
                result = future.result()
                metadata.append(result)
                print(f"[{i}/{total} {100*i//total}%] [OK]   line {line_num}: {repo_name}/{artifact_path}")
            except (urllib.error.URLError, TimeoutError) as e:
                fail_count += 1
                print(f"[{i}/{total} {100*i//total}%] [FAIL] line {line_num}: {repo_name}/{artifact_path} — {e}")

    metadata_file = os.path.join(args.output_dir, "metadata.json")
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nDone. downloaded={len(metadata)} failed={fail_count} skipped={skip_count}")
    print(f"Metadata written to {metadata_file}")


if __name__ == "__main__":
    main()
