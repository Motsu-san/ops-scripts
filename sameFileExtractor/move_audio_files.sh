#!/bin/bash
# move_audio_files.sh
# 指定フォルダ内の .mp3 / .m4a ファイルを再帰的に検索し，
# ファイルの直上2階層のフォルダ構造を維持して移動先フォルダに移動する
#
# 例:
#   /source/any/depth/Artist/Album/song.mp3
#                            ↓
#   /dest/Artist/Album/song.mp3

set -uo pipefail

# ---- 色定義 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ---- ヘルプ ----
usage() {
    cat <<EOF
使い方: $(basename "$0") [オプション] <検索フォルダ> <移動先フォルダ>

.mp3 / .m4a ファイルを再帰的に検索し，ファイルの直上2階層を維持して移動先に移動する。

  検索フォルダ  : 対象ファイルを検索するフォルダ
  移動先フォルダ: ファイルの移動先ルートフォルダ

オプション:
  -d    ドライラン: 実際には移動せず確認のみ
  -h    このヘルプを表示

例:
  $(basename "$0") /NAS/music /backup/music
  $(basename "$0") -d /NAS/music /backup/music

階層の扱い:
  ファイルがある階層    移動後の構造
  depth1/file.mp3    ->  dest/[空]/depth1/file.mp3   ※1階層しかない場合
  d1/d2/file.mp3     ->  dest/d1/d2/file.mp3
  d1/d2/d3/file.mp3  ->  dest/d2/d3/file.mp3         ※直上2階層のみ保持
EOF
    exit 1
}

# ---- オプション解析 ----
DRY_RUN=false

while getopts "dh" opt; do
    case "$opt" in
        d) DRY_RUN=true ;;
        h) usage ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

if [ $# -lt 2 ]; then
    echo -e "${RED}Error: 検索フォルダと移動先フォルダを指定してください${NC}" >&2
    echo ""
    usage
fi

SOURCE_DIR="$1"
DEST_DIR="$2"

# ---- バリデーション ----
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: '${SOURCE_DIR}' はディレクトリではありません${NC}" >&2
    exit 1
fi

SOURCE_DIR=$(cd "$SOURCE_DIR" && pwd)
DEST_DIR=$(cd "$(dirname "$DEST_DIR")" && pwd)/$(basename "$DEST_DIR")

# ---- スキップリストのファイルパス ----
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SKIP_LOG="${DEST_DIR}/skipped_${TIMESTAMP}.txt"

# ---- ヘッダー表示 ----
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   音楽ファイル 2階層構造維持移動スクリプト${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "検索フォルダ  : ${CYAN}${SOURCE_DIR}${NC}"
echo -e "移動先フォルダ: ${CYAN}${DEST_DIR}${NC}"
echo -e "スキップログ  : ${CYAN}${SKIP_LOG}${NC}"

if $DRY_RUN; then
    echo ""
    echo -e "${YELLOW}[ドライラン] 実際の移動は行いません${NC}"
fi
echo ""

# ---- カウンター ----
TOTAL=0
MOVED=0
SKIPPED=0
ERRORS=0

# ---- エラーログのファイルパス ----
ERROR_LOG="${DEST_DIR}/errors_${TIMESTAMP}.txt"

# ---- ファイルを検索して移動 ----
while IFS= read -r -d '' filepath; do
    TOTAL=$((TOTAL + 1))

    filename=$(basename "$filepath")
    parent1=$(basename "$(dirname "$filepath")")
    parent2=$(basename "$(dirname "$(dirname "$filepath")")")

    # 直上2階層を組み立てる
    # ファイルが検索フォルダの直下にある場合 (parent1 == SOURCE_DIR の basename)
    abs_parent=$(dirname "$filepath")
    abs_grandparent=$(dirname "$abs_parent")

    if [ "$abs_parent" = "$SOURCE_DIR" ]; then
        # 1階層: /source/file.mp3 -> dest/file.mp3（フォルダなし）
        dest_path="${DEST_DIR}/${filename}"
    elif [ "$abs_grandparent" = "$SOURCE_DIR" ]; then
        # 1階層フォルダ: /source/folder/file.mp3 -> dest/folder/file.mp3
        dest_path="${DEST_DIR}/${parent1}/${filename}"
    else
        # 2階層以上: 直上2階層のみ保持
        dest_path="${DEST_DIR}/${parent2}/${parent1}/${filename}"
    fi

    echo -e "${YELLOW}[対象]${NC} ${filepath}"
    echo    "       -> ${dest_path}"

    # 移動先に同名ファイルが存在する場合はスキップ
    if [ -e "$dest_path" ]; then
        echo -e "       ${RED}[スキップ] 移動先に同名ファイルが存在します${NC}"
        if ! $DRY_RUN; then
            mkdir -p "$DEST_DIR"
            echo "$filepath" >> "$SKIP_LOG"
        fi
        SKIPPED=$((SKIPPED + 1))
        echo ""
        continue
    fi

    if ! $DRY_RUN; then
        mkdir -p "$(dirname "$dest_path")"
        if mv "$filepath" "$dest_path" 2>/tmp/_mv_err; then
            echo -e "       ${GREEN}[完了]${NC}"
            MOVED=$((MOVED + 1))
        else
            err_msg=$(cat /tmp/_mv_err)
            echo -e "       ${RED}[エラー] ${err_msg}${NC}"
            mkdir -p "$DEST_DIR"
            echo "$filepath -- $err_msg" >> "$ERROR_LOG"
            ERRORS=$((ERRORS + 1))
        fi
    else
        MOVED=$((MOVED + 1))
    fi
    echo ""

done < <(find "$SOURCE_DIR" -type f \( -iname "*.mp3" -o -iname "*.m4a" \) -print0 | sort -z)

# ---- サマリー ----
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}処理完了${NC}"
echo "検索ファイル数 : ${TOTAL}"
echo "移動ファイル数 : ${MOVED}"

if [ "$SKIPPED" -gt 0 ]; then
    echo -e "${YELLOW}スキップ数     : ${SKIPPED} (移動先に同名ファイルあり)${NC}"
    if ! $DRY_RUN; then
        echo -e "スキップログ   : ${CYAN}${SKIP_LOG}${NC}"
    fi
fi

if [ "$ERRORS" -gt 0 ]; then
    echo -e "${RED}エラー数       : ${ERRORS}${NC}"
    if ! $DRY_RUN; then
        echo -e "エラーログ     : ${CYAN}${ERROR_LOG}${NC}"
    fi
fi

if $DRY_RUN; then
    echo ""
    echo -e "${YELLOW}[ドライラン] 実際の移動は行われていません${NC}"
fi
