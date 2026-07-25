#!/bin/bash
source env.sh

psql -h ${PGSERVER} -d ${PGDB} ${PGUSER} \
     -c "\copy (select tr.repositorypath, ar.deploypath from artifact ar join targetrepository tr on ar.targetrepository_id = tr.id where ar.modificationtime >= '${FROM}' and ar.modificationtime < '${TO}' and tr.repositorypath like '%/hosted/%') to '/tmp/artifacts-${FROM}--${TO}.csv' WITH (format csv)"

python download.py --csv /tmp/artifacts-${FROM}--${TO}.csv --output-dir /tmp/artifacts-${FROM}--${TO}
python upload.py --metadata /tmp/artifacts-${FROM}--${TO}/metadata.json --dry-run
