#!/bin/bash
# The CSVs are mounted read-only at /csv. LOAD DATA INFILE may only read from the server's
# secure_file_priv folder, so copy them there first (this runs as the mysql user during first start).
cp /csv/*.csv /var/lib/mysql-files/
echo "[clinassist] copied $(ls /var/lib/mysql-files/*.csv | wc -l) CSV files for loading"
