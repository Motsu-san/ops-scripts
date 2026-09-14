#!/usr/bin/env bash

set -euo pipefail

usage() {
    echo "Usage: $0 [OPTIONS] <ROOT_DIR> <PATTERN>"
    echo ""
    echo "ROOT_DIR 以下から PATTERN に一致するフォルダ／ファイルを削除する。"
    echo "既定では PATTERN の部分一致で探索し、一覧を表示して確認したうえで"
    echo "ゴミ箱へ移動する（rm ではないので復元できる）。"
    echo ""
    echo "Options:"
    echo "  -t, --type d|f|a   対象種別。d=フォルダ, f=ファイル, a=両方（既定: a）"
    echo "  -d, --max-depth N  ROOT_DIR からの探索深さ上限（既定: 無制限）"
    echo "  -e, --exact        部分一致ではなく完全一致で探索する"
    echo "  -n, --dry-run      削除せず、一覧だけを表示する"
    echo "  -y, --yes          確認プロンプトを省略する"
    echo "  -f, --force        ゴミ箱ではなく rm -rf で完全に削除する（復元不可）"
    echo "  -h, --help         ヘルプを表示する"
    echo ""
    echo "Note:"
    echo "  PATTERN には '*' '?' '[...]' などのグロブも使用できる。"
    echo "  シェルに展開されないよう、グロブを使う場合はクォートすること。"
    echo "  一致したフォルダの中は再探索しない（フォルダごと消えるため）。"
    echo ""
    echo "Example:"
    echo "  $0 --dry-run /path/to/root tmp_"
    echo "  $0 --type d /path/to/root __pycache__"
    echo "  $0 --exact --yes /path/to/root build"
    echo "  $0 --force --max-depth 2 /path/to/root .log"
}

TYPE=a
MAX_DEPTH=""
EXACT=0
DRY_RUN=0
ASSUME_YES=0
FORCE=0
POSITIONAL=()

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--type)
            if [ -z "${2-}" ]; then
                echo "Error: $1 requires a value" >&2
                exit 1
            fi
            TYPE="$2"
            shift 2
            ;;
        --type=*)
            TYPE="${1#*=}"
            shift
            ;;
        -d|--max-depth)
            if [ -z "${2-}" ]; then
                echo "Error: $1 requires a value" >&2
                exit 1
            fi
            MAX_DEPTH="$2"
            shift 2
            ;;
        --max-depth=*)
            MAX_DEPTH="${1#*=}"
            shift
            ;;
        -e|--exact)
            EXACT=1
            shift
            ;;
        -n|--dry-run)
            DRY_RUN=1
            shift
            ;;
        -y|--yes)
            ASSUME_YES=1
            shift
            ;;
        -f|--force)
            FORCE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            POSITIONAL+=("$@")
            break
            ;;
        -*)
            echo "Error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [ "${#POSITIONAL[@]}" -ne 2 ]; then
    echo "Error: ROOT_DIR and PATTERN are required" >&2
    usage >&2
    exit 1
fi

ROOT_DIR="${POSITIONAL[0]}"
PATTERN="${POSITIONAL[1]}"

case "$TYPE" in
    d|f|a) ;;
    *)
        echo "Error: --type must be one of d, f, a: $TYPE" >&2
        exit 1
        ;;
esac

if [ ! -d "$ROOT_DIR" ]; then
    echo "Error: ROOT_DIR does not exist or is not a directory: $ROOT_DIR" >&2
    exit 1
fi

ROOT_ABS="$(cd -- "$ROOT_DIR" && pwd -P)"
if [ "$ROOT_ABS" = "/" ]; then
    echo "Error: refusing to operate on the filesystem root" >&2
    exit 1
fi

if [ -n "$MAX_DEPTH" ] && ! [[ "$MAX_DEPTH" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: max-depth must be a positive integer: $MAX_DEPTH" >&2
    exit 1
fi

if [ -z "$PATTERN" ] || [ "$PATTERN" = "." ] || [ "$PATTERN" = ".." ]; then
    echo "Error: PATTERN must be a non-empty name" >&2
    exit 1
fi

if [[ "$PATTERN" == */* ]]; then
    echo "Error: PATTERN must not contain '/': $PATTERN" >&2
    exit 1
fi

if [ "$PATTERN" = "*" ]; then
    echo "Error: PATTERN '*' would delete everything under $ROOT_ABS" >&2
    exit 1
fi

if [ "$EXACT" -eq 1 ]; then
    FIND_NAME="$PATTERN"
else
    FIND_NAME="*${PATTERN}*"
fi

FIND_OPTS=(-mindepth 1)
if [ -n "$MAX_DEPTH" ]; then
    FIND_OPTS+=(-maxdepth "$MAX_DEPTH")
fi

# 一致したディレクトリは -prune で中を再探索しない。
# ディレクトリごと消えるので、その中の一致物を別途消す必要がないため。
FIND_EXPR=(-name "$FIND_NAME")
case "$TYPE" in
    d) FIND_EXPR+=(-type d -print0 -prune) ;;
    f) FIND_EXPR+=(-type f -print0) ;;
    a) FIND_EXPR+=(-print0 -prune) ;;
esac

mapfile -d '' TARGETS < <(find "$ROOT_ABS" "${FIND_OPTS[@]}" "${FIND_EXPR[@]}")

if [ "${#TARGETS[@]}" -eq 0 ]; then
    echo "No matching entries found. (pattern: $FIND_NAME, type: $TYPE, root: $ROOT_ABS)"
    exit 0
fi

if [ "$FORCE" -eq 1 ]; then
    METHOD="rm -rf (permanent)"
elif command -v gio >/dev/null 2>&1; then
    METHOD="trash"
else
    echo "Error: 'gio' not found, cannot move to trash. Re-run with --force to delete permanently." >&2
    exit 1
fi

echo "Matched ${#TARGETS[@]} entr$(if [ "${#TARGETS[@]}" -eq 1 ]; then echo y; else echo ies; fi) under $ROOT_ABS:"
for target in "${TARGETS[@]}"; do
    if [ -d "$target" ]; then
        printf '  [dir ] %s\n' "$target"
    else
        printf '  [file] %s\n' "$target"
    fi
done

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] Nothing was deleted. (method would be: $METHOD)"
    exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
    if [ ! -t 0 ]; then
        echo "Error: not a terminal; re-run with --yes to skip the confirmation" >&2
        exit 1
    fi
    printf 'Delete these via %s? [y/N] ' "$METHOD"
    read -r answer
    case "$answer" in
        y|Y|yes|YES) ;;
        *)
            echo "Aborted. Nothing was deleted."
            exit 1
            ;;
    esac
fi

DELETED=0
ERRORS=0

for target in "${TARGETS[@]}"; do
    if [ "$FORCE" -eq 1 ]; then
        if rm -rf -- "$target"; then
            echo "Deleted: $target"
            DELETED=$((DELETED + 1))
        else
            echo "Error: failed to delete: $target" >&2
            ERRORS=$((ERRORS + 1))
        fi
    else
        if gio trash -- "$target"; then
            echo "Trashed: $target"
            DELETED=$((DELETED + 1))
        else
            echo "Error: failed to trash: $target" >&2
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

echo "Done. $DELETED deleted, $ERRORS failed. (method: $METHOD)"

if [ "$ERRORS" -gt 0 ]; then
    exit 1
fi
