#! /bin/bash
set -euo pipefail

base="https://cdsarc.u-strasbg.fr/ftp/cati/vizier/ftp/0/aliases/T/Tycho-2" # expired tls cert
outdir="tycho2"
mkdir -p "$outdir"
curl_flags=( -kfSL -C - --retry 5 --retry-all-errors --retry-delay 3 )
for i in $(seq -w 00 19); do
  curl "${curl_flags[@]}" -o "$outdir/tyc2.dat.$i.gz" "$base/tyc2.dat.$i.gz"
done
curl "${curl_flags[@]}" -o "$outdir/ReadMe" "$base/ReadMe"
curl "${curl_flags[@]}" -o "$outdir/suppl_1.dat.gz" "$base/suppl_1.dat.gz"
curl "${curl_flags[@]}" -o "$outdir/suppl_2.dat.gz" "$base/suppl_2.dat.gz"
