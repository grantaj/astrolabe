#! /bin/bash
set -euo pipefail

base="https://cdsarc.u-strasbg.fr/ftp/cati/vizier/ftp/0/aliases/T/Tycho-2" # expired tls cert
outdir="tycho2"
mkdir -p "$outdir"
for i in $(seq -w 00 19); do
  curl -kfSL -C - -o "$outdir/tyc2.dat.$i.gz" "$base/tyc2.dat.$i.gz"
done
curl -kfSL -C - -o "$outdir/ReadMe" "$base/ReadMe"
curl -kfSL -C - -o "$outdir/suppl_1.dat.gz" "$base/suppl_1.dat.gz"
curl -kfSL -C - -o "$outdir/suppl_2.dat.gz" "$base/suppl_2.dat.gz"
