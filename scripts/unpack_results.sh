#!/bin/bash
# Decompress the per-mission result files shipped with the repository (needed by the table scripts).
cd "$(dirname "$0")/../study_results" && gunzip -k -f *.csv.gz && echo "unpacked into study_results/"
