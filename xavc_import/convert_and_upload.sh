#!/bin/bash
set -uo pipefail

cd "$(dirname "$0")"
current_dir=$(pwd)
log_file="$current_dir/xavc_import.log"

# ログ出力を有効にする場合は、以下の行のコメントアウトを外してください
# exec > >(tee -a "$log_file") 2>&1

# ロックファイルのパス
lock_file="$current_dir/$(basename "$0").lock"
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

upload_dir="/Volumes/photo"
# フォルダが存在しない場合はスクリプトを終了
if [ ! -d "$upload_dir" ]; then
  upload_dir="$HOME/Photo"
  if [ ! -d "$upload_dir" ]; then
    echo "Error: Directory $upload_dir does not exist."
    exit 1
  fi
fi

# マッチしないglobを空に展開する
shopt -s nullglob

# 取り込み履歴。SDカードの元ファイルは消さないため、取り込み済みのファイルを記録して再取り込みを防ぐ
# 形式: <元ファイル名(拡張子なし)>_<撮影日時>\t<記録日 YYYYMMDD>
history_file="$script_dir/import_history.tsv"
touch "$history_file"
# 1年より古い記録は削除する
history_cutoff=$(date -v-365d +"%Y%m%d")
awk -F'\t' -v cutoff="$history_cutoff" '$2 >= cutoff' "$history_file" > "$history_file.tmp" \
  && mv "$history_file.tmp" "$history_file"

# 履歴のキーを返す。撮影日時が取得できない場合は空を返す（常に取り込み対象になる）
history_key() {
  local file=$1 tag=$2 shot_time
  shot_time=$(exiftool -s3 -d "%Y%m%d_%H%M%S" -"$tag" "$file" 2>/dev/null)
  [ -n "$shot_time" ] && echo "$(basename "${file%.*}")_${shot_time}"
}

in_history() {
  [ -n "$1" ] && grep -qF -- "$1"$'\t' "$history_file"
}

add_history() {
  # 撮影日時が取れず末尾が "_" になったキーは記録しない
  case "$1" in ""|*_) return 0 ;; esac
  printf '%s\t%s\n' "$1" "$(date +"%Y%m%d")" >> "$history_file"
}

# 失敗したファイル数（失敗したファイルは作業フォルダに残し、次回の実行で再処理する）
failed=0

create_time=$(date +"%Y%m%d_%H%M%S")
# 元ファイル(C*.MP4)の作業フォルダ。変換に成功したファイルは削除する
xavc_work="${script_dir}/${create_time}_xavc"
# 変換後ファイル(*.mp4)の作業フォルダ。アップロードに成功したファイルは削除する
h264_work="${script_dir}/${create_time}_h264"
mkdir -p "$xavc_work" "$h264_work"

# 動画ファイルを作業フォルダに集める（無ければ動画変換はスキップし、RAWのみの取り込みも可能にする）
if [ ! -d "$xavc_dir" ]; then
  echo "Directory $xavc_dir does not exist."
  # コピー元がマウントされていない場合は過去の実行で処理が終わらなかったファイルを回収する
  for dir in "$script_dir"/*_xavc "$script_dir"/*_h264; do
    [ -d "$dir" ] || continue
    case "$dir" in
      "$xavc_work"|"$h264_work") continue ;;
      *_xavc) leftovers=("$dir"/C*.MP4); dest="$xavc_work" ;;
      *_h264) leftovers=("$dir"/*.mp4); dest="$h264_work" ;;
    esac
    if [ ${#leftovers[@]} -gt 0 ]; then
      echo "Leftover files found in $dir. Collecting..."
      mv -nv "${leftovers[@]}" "$dest/"
    fi
    rmdir "$dir" 2>/dev/null
  done
elif ls "$xavc_dir"/C*.MP4 1> /dev/null 2>&1; then
  # コピー元にファイルが存在する場合は、取り込み済みのものを除いてローカルにコピーする
  echo "Files found. Continuing..."
  for src in "$xavc_dir"/C*.MP4; do
    if in_history "$(history_key "$src" LastUpdate)"; then
      echo "Already imported: $src. Skipping."
      continue
    fi
    cp -nv "$src" "$xavc_work/"
  done
else
  echo "No files matching C*.MP4 found. Skipping video conversion."
fi

xavc_files=("$xavc_work"/C*.MP4)
mp4_files=("$h264_work"/*.mp4)
has_video=false
if [ ${#xavc_files[@]} -gt 0 ] || [ ${#mp4_files[@]} -gt 0 ]; then
  has_video=true
fi

# 取り込み済みでないRAW画像を集める
raw_files=()
raw_keys=()
if [ -d "$raw_image_dir" ]; then
  for src in "$raw_image_dir"/*.ARW; do
    key=$(history_key "$src" DateTimeOriginal)
    if in_history "$key"; then
      echo "Already imported: $src. Skipping."
      continue
    fi
    raw_files+=("$src")
    raw_keys+=("$key")
  done
fi
has_raw=false
if [ ${#raw_files[@]} -gt 0 ]; then
  has_raw=true
fi

if [ "$has_video" = false ] && [ "$has_raw" = false ]; then
  echo "No video or RAW files found. Nothing to do. Exiting."
  rmdir "$xavc_work" "$h264_work" 2>/dev/null
  exit 0
fi

target_dir="${upload_dir}/${create_time}_alpha6000"
mkdir -p "$target_dir"

# RAW画像を1件ずつコピーし、成功したものを履歴に記録する
for ((i=0; i<${#raw_files[@]}; i++)); do
  if cp -v "${raw_files[$i]}" "$target_dir/"; then
    add_history "${raw_keys[$i]}"
  else
    echo "Error: failed to copy ${raw_files[$i]}."
    failed=$((failed + 1))
  fi
done

# 動画が無い場合はRAWのみの取り込みとしてここで終了する
if [ "$has_video" = false ]; then
  rmdir "$xavc_work" "$h264_work" 2>/dev/null
  if [ "$failed" -gt 0 ]; then
    echo "$failed file(s) failed. They will be retried on the next run."
    exit 1
  fi
  echo "No video files to convert. RAW-only import completed successfully."
  exit 0
fi

# 入力ファイルのパターンと出力ファイルのパターンを指定してください
input_pattern="C%04d.MP4"  # 入力ファイル名のパターン
output_pattern="%s_h264_%s.mp4" # 出力ファイル名のパターン

if [ ${#xavc_files[@]} -gt 0 ]; then
  cd "$xavc_work"
  sequence_numbers=$(find "$xavc_work" -name "C[0-9][0-9][0-9][0-9].MP4" | sed 's/.*C\([0-9][0-9][0-9][0-9]\).MP4/\1/' | sort -n)

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
          if ffmpeg -y -r 59.94 -i "$input_file" -c:v libx264 -r 59.94 -c:a copy -map_metadata 0 "$h264_work/$output_file"; then
              # 変換が完走した元ファイルは削除する
              rm -v "$input_file"
          else
              echo "Error: failed to convert $input_file. Keeping it in $xavc_work."
              rm -f "$h264_work/$output_file"
              failed=$((failed + 1))
          fi
      else
          echo "File $input_file does not exist. Skipping."
      fi
  done

  cd "$script_dir"
fi
# 全て変換できていれば空になるので削除する
rmdir "$xavc_work" 2>/dev/null

# DO NOT REMOVE ORIGIN DIR IN ALPHA6000 SD CARD
# THAT MAKES ERRORS IN ALPHA6000
# rm -v $xavc_dir/*

# 変換後ファイルを1件ずつアップロードし、成功したものは履歴に記録して削除する
for mp4_file in "$h264_work"/*.mp4; do
  if cp -v "$mp4_file" "$target_dir/" && [ -f "$target_dir/$(basename "$mp4_file")" ]; then
    # C0007_h264_20261017_095533.mp4 -> C0007_20261017_095533
    mp4_name=$(basename "$mp4_file" .mp4)
    add_history "${mp4_name/_h264_/_}"
    rm -v "$mp4_file"
  else
    echo "Error: failed to upload $mp4_file. Keeping it in $h264_work."
    failed=$((failed + 1))
  fi
done
# 全てアップロードできていれば空になるので削除する
rmdir "$h264_work" 2>/dev/null
rmdir "$target_dir" 2>/dev/null

if [ "$failed" -gt 0 ]; then
  echo "$failed file(s) failed. They will be retried on the next run."
  exit 1
fi

echo "Successfully converted and uploaded"
