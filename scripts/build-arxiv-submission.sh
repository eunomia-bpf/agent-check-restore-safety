#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
paper_dir="$repo_root/docs/paper"
config_file="$repo_root/docs/arxiv/arxiv-config.tex"

if [[ $# -gt 1 ]]; then
    echo "usage: $0 [output.tar.gz]" >&2
    exit 2
fi

if [[ $# -eq 1 ]]; then
    case "$1" in
        /*) output_archive="$1" ;;
        *) output_archive="$repo_root/$1" ;;
    esac
else
    output_archive="$repo_root/arxiv-submission.tar.gz"
fi

for command_name in latexmk pdflatex bibtex tar sha256sum pdfinfo; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "required command not found: $command_name" >&2
        exit 1
    fi
done

staging_dir="$(mktemp -d)"
verify_dir="$(mktemp -d)"
archive_tmp="$(mktemp "${output_archive}.tmp.XXXXXX")"
cleanup() {
    rm -rf -- "$staging_dir" "$verify_dir"
    rm -f -- "$archive_tmp"
}
trap cleanup EXIT

mkdir -p "$staging_dir/sections"
install -m 0644 "$paper_dir/main.tex" "$staging_dir/main.tex"
install -m 0644 "$paper_dir/references.bib" "$staging_dir/references.bib"
install -m 0644 "$config_file" "$staging_dir/arxiv-config.tex"
while IFS= read -r section_file; do
    install -m 0644 "$paper_dir/$section_file" "$staging_dir/$section_file"
done < <(cd "$paper_dir" && find sections -type f -name '*.tex' -print | LC_ALL=C sort)

(
    cd "$staging_dir"
    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
)
test -s "$staging_dir/main.pdf"
test -s "$staging_dir/main.bbl"

archive_members=(
    arxiv-config.tex
    main.bbl
    main.tex
    references.bib
)
while IFS= read -r section_file; do
    archive_members+=("$section_file")
done < <(cd "$staging_dir" && find sections -type f -name '*.tex' -print | LC_ALL=C sort)

tar \
    --sort=name \
    --mtime='UTC 1970-01-01' \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -czf "$archive_tmp" \
    -C "$staging_dir" \
    "${archive_members[@]}"

tar -xzf "$archive_tmp" -C "$verify_dir"
(
    cd "$verify_dir"
    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
)
test -s "$verify_dir/main.pdf"

mv -f -- "$archive_tmp" "$output_archive"
printf 'Created %s\n' "$output_archive"
printf 'SHA-256: '
sha256sum "$output_archive" | awk '{print $1}'
printf 'Verified PDF pages: %s\n' \
    "$(pdfinfo "$verify_dir/main.pdf" | awk '/^Pages:/ {print $2}')"
