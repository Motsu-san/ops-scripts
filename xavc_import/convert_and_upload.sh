#!/bin/bash
set -uo pipefail

cd "$(dirname "$0")"
current_dir=$(pwd)
log_file="$current_dir/xavc_import.log"

# ログ出力を有効にする場合は、以下の行のコメントアウトを外してください
# exec > >(tee -a "$log_file") 2>&1

# ロックファイルのパス
lock_file="$(basename "$0").lock"
# ロックファイルが存在すれば終了
if [ -e "$lock_file" ]; then
    echo "Another instance is running. Exiting."
    exit 1
fi
# ロックファイルを作成
touch "$lock_file"

# スクリプト終了時にロックファイルを削除
trap 'rm -f "$lock_file"' EXIT

# xavcファイル・RAW画像のコピー元フォルダ
xavc_dir="/Volumes/Untitled/private/M4ROOT/CLIP"
raw_image_dir="/Volumes/Untitled/DCIM/100MSDCF"
script_dir=$(cd "$(dirname "$0")"; pwd)
tmp_dir="$script_dir/tmp"
mkdir -p "$tmp_dir"

# 動画ファイルをtmpに集める（無ければ動画変換はスキップし、RAWのみの取り込みも可能にする）
has_video=false
if [ ! -d "$xavc_dir" ]; then
  echo "Directory $xavc_dir does not exist."
  # コピー元がマウントされていない場合は直近でローカルにコピー済みのファイルを移動させる
  newest_xavc_dir=$(find "$script_dir" -maxdepth 1 -type d -name '*_xavc' -print0 | xargs -0 ls -td | head -n 1)
  if [ -d "$newest_xavc_dir" ] && ls "$newest_xavc_dir"/C*.MP4 1> /dev/null 2>&1; then
    echo "Files found in $newest_xavc_dir. Continuing..."
    mv -v "$newest_xavc_dir"/C*.MP4 "$tmp_dir/"
    has_video=true
  else
    echo "No local backup files matching C*.MP4 found. Skipping video conversion."
  fi
elif ls "$xavc_dir"/C*.MP4 1> /dev/null 2>&1; then
  # コピー元にファイルが存在する場合はローカルにコピーする
  echo "Files found. Continuing..."
  cp -nv "$xavc_dir"/C*.MP4 "$tmp_dir"
  has_video=true
else
  echo "No files matching C*.MP4 found. Skipping video conversion."
fi

# RAW画像の有無を確認
has_raw=false
if [ -d "$raw_image_dir" ] && ls "$raw_image_dir"/*.ARW 1> /dev/null 2>&1; then
  has_raw=true
fi

if [ "$has_video" = false ] && [ "$has_raw" = false ]; then
  echo "No video or RAW files found. Nothing to do. Exiting."
  rmdir "$tmp_dir" 2>/dev/null
  exit 0
fi

upload_dir="/Volumes/Multimedia/Photo"
# フォルダが存在しない場合はスクリプトを終了
if [ ! -d "$upload_dir" ]; then
  upload_dir="$HOME/Photo"
  if [ ! -d "$upload_dir" ]; then
    echo "Error: Directory $upload_dir does not exist."
    exit 1
  fi
fi

create_time=$(date +"%Y%m%d_%H%M%S")
target_dir="${upload_dir}/${create_time}_alpha6000"
mkdir -p "$target_dir"

# RAW画像をコピー
if [ "$has_raw" = true ]; then
  cp -v "$raw_image_dir"/*.ARW "$target_dir/"
fi

# 動画が無い場合はRAWのみの取り込みとしてここで終了する
if [ "$has_video" = false ]; then
  echo "No video files to convert. RAW-only import completed successfully."
  rmdir "$tmp_dir" 2>/dev/null
  exit 0
fi

backup_dir="${script_dir}/${create_time}_xavc"
mkdir -p "$backup_dir"

# 入力ファイルのパターンと出力ファイルのパターンを指定してください
input_pattern="C%04d.MP4"  # 入力ファイル名のパターン
output_pattern="%s_h264_%s.mp4" # 出力ファイル名のパターン

cd "$tmp_dir"
sequence_numbers=$(find "$tmp_dir" -name "C[0-9][0-9][0-9][0-9].MP4" | sed 's/.*C\([0-9][0-9][0-9][0-9]\).MP4/\1/' | sort -n)

# 最初と最後の連番を取得
first_number=$(echo "$sequence_numbers" | head -n 1)
last_number=$(echo "$sequence_numbers" | tail -n 1)

# 0 paddingを削除してループの開始終了番号を指定
start_number=$((10#$first_number)) # 10進数として解釈
end_number=$((10#$last_number)) # 10進数として解釈

# 連番の範囲でループを回します
for ((i=start_number; i<=end_number; i++)); do
    # printfでゼロパディングされた番号を作成
    input_file=$(printf "$input_pattern" "$i")

    # ファイルが存在するかチェック
    if [ -f "$input_file" ]; then
        # 動画の撮影日時を取得し、YYYYMMDD_HHMMSS形式に変換
        # creation_time=$(stat -f "%Sm" -t "%Y%m%d_%H%M%S" "$input_file")
        # CreateDateはUTCだが，LastUpdateがJSTになっているのでこちらを参照する
        creation_time=$(exiftool -s3 -d "%Y%m%d_%H%M%S" -LastUpdate "$input_file" 2>/dev/null)

        # 出力ファイル名の作成（元のパターンに作成日時を追加）
        org_name=$(basename "$input_file" .MP4)
        output_file=$(printf "$output_pattern" "$org_name" "$creation_time")

        echo "Processing $input_file -> $output_file"
        # FFmpegコマンドで連番ファイルを変換します
        # 撮影日時を保持するためメタデータをコピー
        # 確認方法は ffprobe -v quiet -print_format json -show_format C0017.mp4 で
        # "creation_time": "2024-10-13T00:02:03.000000Z" とUTCで時刻が打たれている
        ffmpeg -y -r 59.94 -i "$input_file" -c:v libx264 -r 59.94 -c:a copy -map_metadata 0 "$output_file"
    else
        echo "File $input_file does not exist. Skipping."
    fi
done

echo "successfully converted"

# DO NOT REMOVE ORIGIN DIR IN ALPHA6000 SD CARD
# THAT MAKES ERRORS IN ALPHA6000
# rm -v $xavc_dir/*

mv -v "$tmp_dir"/C*.MP4 "$backup_dir/"
cp -v "$tmp_dir"/*.mp4 "$target_dir/"

if ls "$target_dir"/C"${last_number}"_h264_*.mp4 1> /dev/null 2>&1; then
  echo "Files found. successfully uploaded"
  rm -rv "$tmp_dir"
  echo "Delete tmp directory for conversion"
else
  echo "No file or directory of target found. Error in copying. Exiting."
  exit 1
fi
