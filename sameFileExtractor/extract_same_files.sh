#!/bin/bash
# extract_same_files.sh
# 2つの比較対象フォルダ内で同じパス（フォルダ名＋ファイル名）のファイルを検索し，
# 最も新しいファイル以外を比較対象フォルダと同じ階層にフォルダ構造を保って移動する

set -euo pipefail

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
使い方: $(basename "$0") [オプション] <フォルダA> <フォルダB>

両フォルダ内で同じ相対パス（フォルダ名＋ファイル名）のファイルを検索し，
最も古いファイルを移動先フォルダに移動します。
移動先はデフォルトで両フォルダと同じ階層に作成されます。

オプション:
  -o <パス>    移動先フォルダを指定 (デフォルト: <フォルダAの親>/moved_YYYYMMDD_HHMMSS)
  -d           ドライラン: 実際には移動せず確認のみ
  -h           このヘルプを表示

例:
  $(basename "$0") ./backupA ./backupB
  $(basename "$0") -o ./old_files ./backupA ./backupB
  $(basename "$0") -d ./backupA ./backupB
EOF
    exit 1
}

# ---- オプション解析 ----
DRY_RUN=false
OUTPUT_DIR=""

while getopts "o:dh" opt; do
    case "$opt" in
        o) OUTPUT_DIR="$OPTARG" ;;
        d) DRY_RUN=true ;;
        h) usage ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

if [ $# -lt 2 ]; then
    echo -e "${RED}Error: フォルダA と フォルダB の両方を指定してください${NC}" >&2
    echo ""
    usage
fi

FOLDER_A="$1"
FOLDER_B="$2"

# ---- バリデーション ----
if [ ! -d "$FOLDER_A" ]; then
    echo -e "${RED}Error: '$FOLDER_A' はディレクトリではありません${NC}" >&2
    exit 1
fi
if [ ! -d "$FOLDER_B" ]; then
    echo -e "${RED}Error: '$FOLDER_B' はディレクトリではありません${NC}" >&2
    exit 1
fi

# ---- 絶対パスに変換 ----
FOLDER_A=$(cd "$FOLDER_A" && pwd)
FOLDER_B=$(cd "$FOLDER_B" && pwd)

# ---- 移動先フォルダを決定 ----
if [ -z "$OUTPUT_DIR" ]; then
    PARENT_DIR=$(dirname "$FOLDER_A")
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    OUTPUT_DIR="${PARENT_DIR}/moved_${TIMESTAMP}"
fi

FOLDER_A_NAME=$(basename "$FOLDER_A")
FOLDER_B_NAME=$(basename "$FOLDER_B")

# ---- ヘッダー表示 ----
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   同名ファイル抽出・移動スクリプト${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "比較フォルダ A : ${CYAN}${FOLDER_A}${NC}"
echo -e "比較フォルダ B : ${CYAN}${FOLDER_B}${NC}"
echo -e "移動先フォルダ : ${CYAN}${OUTPUT_DIR}${NC}"

if $DRY_RUN; then
    echo ""
    echo -e "${YELLOW}[ドライラン] 実際の移動は行いません${NC}"
fi
echo ""

# ---- カウンター ----
MATCH_COUNT=0
MOVE_COUNT=0

# ---- フォルダA 内の各ファイルについてフォルダB に同じ相対パスが存在するか確認 ----
while IFS= read -r -d '' file_a; do
    rel_path="${file_a#${FOLDER_A}/}"
    file_b="${FOLDER_B}/${rel_path}"

    if [ ! -f "$file_b" ]; then
        continue
    fi

    MATCH_COUNT=$((MATCH_COUNT + 1))

    # 更新日時（エポック秒）を取得（macOS 対応）
    mtime_a=$(stat -f "%m" "$file_a")
    mtime_b=$(stat -f "%m" "$file_b")

    mtime_a_str=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$file_a")
    mtime_b_str=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$file_b")

    echo -e "${YELLOW}[一致]${NC} ${rel_path}"
    echo "  A (${mtime_a_str}) : ${file_a}"
    echo "  B (${mtime_b_str}) : ${file_b}"

    if [ "$mtime_a" -ge "$mtime_b" ]; then
        # A が新しい（または同時刻）→ B を移動
        OLDER_FILE="$file_b"
        DEST_SUBFOLDER="$FOLDER_B_NAME"
        LABEL="B"
    else
        # B が新しい → A を移動
        OLDER_FILE="$file_a"
        DEST_SUBFOLDER="$FOLDER_A_NAME"
        LABEL="A"
    fi

    DEST="${OUTPUT_DIR}/${DEST_SUBFOLDER}/${rel_path}"
    echo -e "  -> ${RED}${LABEL} を移動${NC} (古い): ${DEST}"

    if ! $DRY_RUN; then
        mkdir -p "$(dirname "$DEST")"
        mv "$OLDER_FILE" "$DEST"
    fi

    MOVE_COUNT=$((MOVE_COUNT + 1))
    echo ""
done < <(find "$FOLDER_A" -type f -print0 | sort -z)

# ---- サマリー ----
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}処理完了${NC}"
echo "一致したファイル数 : ${MATCH_COUNT}"
echo "移動したファイル数 : ${MOVE_COUNT}"

if [ "$MOVE_COUNT" -gt 0 ] && ! $DRY_RUN; then
    echo ""
    echo -e "移動先: ${CYAN}${OUTPUT_DIR}${NC}"
fi

if $DRY_RUN; then
    echo ""
    echo -e "${YELLOW}[ドライラン] 実際の移動は行われていません${NC}"
fi
