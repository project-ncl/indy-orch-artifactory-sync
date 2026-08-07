# indy-orch-artifactory-sync

Sync artifacts added in a certain time range from Indy to an Artifactory instance, using the Orch database.

## Prerequisites

- Python 3 (no external dependencies)
- A CSV file listing the artifacts to sync (columns: base path, relative path)

```
export PGPASSWORD=''
psql -h <server> -d <orch> <orch> -c "\copy (select tr.repositorypath, ar.deploypath, ar.buildrecord_id from artifact ar join targetrepository tr on ar.targetrepository_id = tr.id where ar.modificationtime >= '2026-07-16' and ar.modificationtime < '2026-08-07' and tr.repositorypath like '%/hosted/%') to '/tmp/test.csv' WITH (format csv)"
```

## Setup

```bash
cp env-template.sh env.sh
# Edit env.sh and populate the values
source env.sh
```

## Usage

### 1. Download artifacts from Indy

```bash

python download.py --csv artifacts.csv --output-dir ./downloads
```

| Argument | Required | Description |
|---|---|---|
| `--csv` | Yes | Path to the CSV file listing artifacts to download |
| `--output-dir` | Yes | Directory to download artifacts into |

| Environment Variable | Required | Description |
|---|---|---|
| `INDY_URL` | Yes | Base URL of the Indy instance |

Downloaded artifacts are saved under `<output-dir>/<repo_name>/<artifact_path>`. A `metadata.json` file is written to the output directory for use by the upload step.

### 2. Upload artifacts to Artifactory

```bash
export ARTIFACTORY_URL="https://your-artifactory-instance"
export ARTIFACTORY_USER="username"
export ARTIFACTORY_PASSWORD="password"

python upload.py --metadata ./downloads/metadata.json
```

| Argument | Required | Description |
|---|---|---|
| `--metadata` | Yes | Path to the `metadata.json` produced by `download.py` |
| `--dry-run` | No | Print what would be uploaded without actually uploading |

| Environment Variable | Required | Description |
|---|---|---|
| `ARTIFACTORY_URL` | Yes | Base URL of the Artifactory instance |
| `ARTIFACTORY_USER` | Yes | Artifactory username |
| `ARTIFACTORY_PASSWORD` | Yes | Artifactory password |

The `--dry-run` flag skips authentication checks, so you can preview the upload plan without setting credentials.
