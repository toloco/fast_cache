#!/usr/bin/env bash
# The only public benchmark entry point. Shell owns environments and orchestration;
# Python modules only measure workloads or transform their results.
set -euo pipefail

bench_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$bench_dir/.." && pwd)"
results_dir="${BENCH_RESULTS_DIR:-$bench_dir/results}"
mkdir -p "$results_dir"
results_dir="$(cd "$results_dir" && pwd)"
python_bin="${BENCH_PYTHON_BIN:-python3}"
cd "$project_root"

usage() {
  cat <<'EOF'
Usage: benchmarks/run.sh COMMAND [OPTIONS]

Commands:
  smoke        bounded warp_cache-only run (suitable for CI)
  compare      full native comparison; all competitor packages are required
  matrix       compare across BENCH_PYTHONS (default: "3.12 3.13 3.14")
  sieve        SIEVE eviction-quality workloads
  report       generate a report from explicit result JSON files
  action-json  convert one result file for github-action-benchmark
  docker       run a command in the reproducible Linux environment

Set BENCH_RESULTS_DIR to choose the output directory.
EOF
}

command="${1:-help}"
[[ $# -eq 0 ]] || shift

case "$command" in
  smoke)
    tag="${BENCH_TAG:-smoke}"
    "$python_bin" -m benchmarks.workloads.compare --tag "$tag" --output-dir "$results_dir" \
      --quick --warp-only --profile smoke "$@"
    ;;
  compare)
    tag="${BENCH_TAG:-default}"
    "$python_bin" -m benchmarks.workloads.compare --tag "$tag" --output-dir "$results_dir" \
      --require-comparison "$@"
    ;;
  matrix)
    versions="${BENCH_PYTHONS:-3.12 3.13 3.14}"
    temporary="$(mktemp -d "${TMPDIR:-/tmp}/warp-cache-bench.XXXXXX")"
    trap 'rm -rf "$temporary"' EXIT
    manifest="$results_dir/manifest.json"
    manifest_files=""
    matrix_outputs=()
    for version in $versions; do
      env_dir="$temporary/py$version"
      uv venv --python "$version" "$env_dir"
      env_python="$env_dir/bin/python"
      [[ -x "$env_python" ]] || env_python="$env_dir/Scripts/python.exe"
      uv pip install --python "$env_python" maturin==1.11.5 cachetools==7.0.1 cachebox==5.2.2 moka-py==0.3.0 zoocache==2026.2.11.post1
      wheel_dir="$temporary/wheels-$version"
      mkdir -p "$wheel_dir"
      "$env_python" -m maturin build --release -i "$env_python" -o "$wheel_dir" --manifest-path "$project_root/Cargo.toml"
      wheel="$(find "$wheel_dir" -name '*.whl' -type f)"
      [[ -n "$wheel" && "$(printf '%s\n' "$wheel" | wc -l | tr -d ' ')" = 1 ]] || { echo "expected exactly one wheel for $version" >&2; exit 1; }
      uv pip install --python "$env_python" --force-reinstall "$wheel"
      (cd "$project_root" && BENCH_TAG="py$version" BENCH_RESULTS_DIR="$results_dir" \
        "$env_python" -m benchmarks.workloads.compare --tag "py$version" \
        --output-dir "$results_dir" --require-comparison "$@")
      manifest_files="${manifest_files}${manifest_files:+,}\"bench_py$version.json\""
      matrix_outputs+=("$results_dir/bench_py$version.json")
    done
    printf '{"schema_version":1,"files":[%s]}\n' "$manifest_files" > "$manifest"
    "$python_bin" -m benchmarks._report_generator "${matrix_outputs[@]}" \
      --output "$results_dir/BENCHMARK_REPORT.md"
    echo "Manifest: $manifest"
    echo "Report: $results_dir/BENCHMARK_REPORT.md"
    ;;
  sieve)
    "$python_bin" -m benchmarks.workloads.sieve --output-dir "$results_dir" "$@"
    ;;
  report)
    "$python_bin" -m benchmarks._report_generator "$@"
    ;;
  action-json)
    "$python_bin" -m benchmarks._to_action_json "$@"
    ;;
  docker)
    docker build -f "$bench_dir/Dockerfile" -t warp-cache-bench "$project_root"
    [[ $# -gt 0 ]] || set -- smoke
    docker run --rm -v "$results_dir:/workspace/benchmarks/results" warp-cache-bench "$@"
    ;;
  help|-h|--help) usage ;;
  *) echo "unknown benchmark command: $command" >&2; usage >&2; exit 2 ;;
esac
