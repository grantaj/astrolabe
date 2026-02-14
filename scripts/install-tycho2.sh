#! /bin/bash
set -euo pipefail

base="https://cdsarc.u-strasbg.fr/ftp/cati/vizier/ftp/0/aliases/T/Tycho-2"
outdir="tycho2"
mkdir -p "$outdir"
for i in $(seq -w 00 19); do
  wget -c "$base/tyc2.dat.$i.gz" --no-check-certificate -P "$outdir"
done
wget -c "$base/ReadMe" --no-check-certificate -P "$outdir"
wget -c "$base/suppl_1.dat.gz" --no-check-certificate -P "$outdir"
wget -c "$base/suppl_2.dat.gz" --no-check-certificate -P "$outdir"
