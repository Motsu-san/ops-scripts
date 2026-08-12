#!/usr/bin/env python3
"""
extract_aiff_matches.py
AIFFフォルダ内のファイルのアルバム・タイトルタグと一致する
mp3 / m4a ファイルを検索フォルダから探して移動先フォルダに移動する

依存: ffprobe (ffmpeg に同梱)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

# ANSI カラー
RED    = '\033[0;31m'
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE   = '\033[0;34m'
CYAN   = '\033[0;36m'
NC     = '\033[0m'


def cprint(color, msg):
    print(f"{color}{msg}{NC}")


def check_ffprobe():
    result = subprocess.run(['which', 'ffprobe'], capture_output=True)
    if result.returncode != 0:
        cprint(RED, "Error: ffprobe が見つかりません。ffmpeg をインストールしてください。")
        cprint(RED, "  brew install ffmpeg")
        sys.exit(1)


def get_tags(filepath):
    """ffprobe で title / album タグを取得。失敗時は (None, None) を返す"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        tags = data.get('format', {}).get('tags', {})
        title = ''
        album = ''
        for k, v in tags.items():
            if k.lower() == 'title':
                title = v.strip()
            elif k.lower() == 'album':
                album = v.strip()
        return title, album
    except Exception:
        return None, None


def find_files(folder, extensions):
    """指定フォルダ以下の対象拡張子ファイルを再帰的に収集"""
    files = []
    folder = os.path.abspath(folder)
    for root, dirs, filenames in os.walk(folder):
        dirs.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(extensions):
                files.append(os.path.join(root, filename))
    return files


MIN_MATCH_LEN = 3  # 部分一致に使う文字列の最小文字数


def partial_match(a, b):
    """どちらかが他方に含まれれば一致（大文字小文字を区別しない）
    どちらかが空、または MIN_MATCH_LEN 未満の場合は完全一致のみ"""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return False
    if len(a) < MIN_MATCH_LEN or len(b) < MIN_MATCH_LEN:
        return a == b
    return a in b or b in a


def find_aiff_match(title, album, aiff_keys):
    """タイトル部分一致 かつ アルバム部分一致 の AIFF タグを返す。なければ None"""
    for aiff_title, aiff_album in aiff_keys:
        if partial_match(title, aiff_title) and partial_match(album, aiff_album):
            return (aiff_title, aiff_album)
    return None


def make_dest_path(filepath, search_folder, output_dir):
    """移動先パスを生成（直上2階層のフォルダ構造を維持）"""
    abs_path   = os.path.abspath(filepath)
    folder_abs = os.path.abspath(search_folder)
    filename   = os.path.basename(abs_path)
    parent     = os.path.dirname(abs_path)
    grandparent = os.path.dirname(parent)

    if parent == folder_abs:
        # 検索フォルダ直下: dest/file
        return os.path.join(output_dir, filename)
    elif grandparent == folder_abs:
        # 1階層: dest/folder1/file
        return os.path.join(output_dir, os.path.basename(parent), filename)
    else:
        # 2階層以上: 直上2階層のみ保持
        return os.path.join(output_dir, os.path.basename(grandparent),
                            os.path.basename(parent), filename)


def main():
    parser = argparse.ArgumentParser(
        description='AIFFのアルバム・タイトルと一致する mp3/m4a を検索して移動する',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  %(prog)s ./aiff_folder ./music_folder ./output
  %(prog)s -d ./aiff_folder ./music_folder ./output
  %(prog)s --skip-no-tags ./aiff_folder ./music_folder ./output
        """
    )
    parser.add_argument('aiff_folder',   help='AIFF ファイルが入ったフォルダ（参照元）')
    parser.add_argument('search_folder', help='mp3 / m4a を検索するフォルダ')
    parser.add_argument('output_dir',    help='一致した mp3 / m4a の移動先フォルダ')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='ドライラン: 実際には移動しない')
    parser.add_argument('--skip-no-tags', action='store_true',
                        help='title または album タグが空のファイルを無視')

    args = parser.parse_args()

    check_ffprobe()

    for folder in [args.aiff_folder, args.search_folder]:
        if not os.path.isdir(folder):
            cprint(RED, f"Error: '{folder}' はディレクトリではありません")
            sys.exit(1)

    output_dir = os.path.abspath(args.output_dir)
    timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')
    tag_err_log = os.path.join(output_dir, f'tag_errors_{timestamp}.txt')

    # ---- ヘッダー ----
    print()
    cprint(BLUE, '=' * 56)
    cprint(BLUE, '   AIFF一致 mp3/m4a 抽出・移動スクリプト')
    cprint(BLUE, '=' * 56)
    print()
    print(f'AIFF フォルダ  : {CYAN}{os.path.abspath(args.aiff_folder)}{NC}')
    print(f'検索フォルダ   : {CYAN}{os.path.abspath(args.search_folder)}{NC}')
    print(f'移動先フォルダ : {CYAN}{output_dir}{NC}')
    if args.dry_run:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行いません')
    print()

    # ---- AIFF タグを収集 ----
    print('AIFF ファイルのタグを読み取り中...')
    aiff_files = find_files(args.aiff_folder, ('.aiff', '.aif'))
    print(f'  {len(aiff_files)} ファイルが見つかりました')

    aiff_keys = []      # [(title_lower, album_lower), ...]
    aiff_err  = []

    for i, filepath in enumerate(aiff_files):
        print(f'\r  {i + 1}/{len(aiff_files)} 処理中... ', end='', flush=True)
        title, album = get_tags(filepath)
        if title is None:
            aiff_err.append(filepath)
            continue
        if args.skip_no_tags and (not title or not album):
            continue
        aiff_keys.append((title.lower(), album.lower()))

    print(f'\r  タグ読み取り完了 ({len(aiff_files)} ファイル)      ')

    if aiff_err:
        print()
        cprint(YELLOW, f'  警告: タグ読み取り失敗 {len(aiff_err)} ファイル (AIFF)')
        for f in aiff_err:
            print(f'    {f}')
        if not args.dry_run:
            os.makedirs(output_dir, exist_ok=True)
            with open(tag_err_log, 'a', encoding='utf-8') as log:
                log.write('# AIFF タグ読み取り失敗\n')
                for f in aiff_err:
                    log.write(f + '\n')

    print(f'  有効なタグセット: {len(aiff_keys)} 件')
    print()

    if not aiff_keys:
        cprint(YELLOW, 'AIFF からタグが取得できませんでした。終了します。')
        return

    # ---- mp3/m4a を検索して照合（フェーズ1: 収集） ----
    print('mp3 / m4a ファイルを検索中...')
    audio_files = find_files(args.search_folder, ('.mp3', '.m4a'))
    print(f'  {len(audio_files)} ファイルが見つかりました')
    print()
    print('タグを照合中...')

    # aiff_key -> [(filepath, title, album), ...]
    from collections import defaultdict
    grouped   = defaultdict(list)
    err_files = []

    for i, filepath in enumerate(audio_files):
        print(f'\r  {i + 1}/{len(audio_files)} 処理中... ', end='', flush=True)
        title, album = get_tags(filepath)

        if title is None:
            err_files.append(filepath)
            continue
        if args.skip_no_tags and (not title or not album):
            continue

        matched_key = find_aiff_match(title, album, aiff_keys)
        if matched_key is None:
            continue

        grouped[matched_key].append((filepath, title, album))

    print(f'\r  照合完了 ({len(audio_files)} ファイル)      ')
    print()

    # ---- フェーズ2: 移動 or テキスト出力 ----
    multi_log     = os.path.join(output_dir, f'multi_matches_{timestamp}.txt')
    move_count    = 0
    multi_count   = 0
    multi_files   = []   # (aiff_key, [filepaths]) のリスト

    for aiff_key, file_list in sorted(grouped.items(), key=lambda x: x[0]):
        aiff_title_disp, aiff_album_disp = aiff_key

        if len(file_list) == 1:
            # 1件 → 移動
            filepath, title, album = file_list[0]
            dest = make_dest_path(filepath, args.search_folder, output_dir)
            cprint(YELLOW, f'[一致]  曲名: "{title}"  /  アルバム: "{album}"')
            print(f'  {RED}[移動]{NC} {filepath}')
            print(f'         -> {dest}')

            if not args.dry_run:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    shutil.move(filepath, dest)
                    move_count += 1
                except Exception as e:
                    cprint(RED, f'  [エラー] {e}')
                    err_files.append(filepath)
            else:
                move_count += 1
        else:
            # 2件以上 → 移動せずログ
            multi_count += 1
            multi_files.append((aiff_key, file_list))
            cprint(YELLOW, f'[複数一致] 曲名: "{aiff_title_disp}"  /  アルバム: "{aiff_album_disp}"  ({len(file_list)} 件 → スキップ)')
            for filepath, title, album in file_list:
                print(f'  {YELLOW}[保留]{NC} {filepath}')
        print()

    # 複数一致をテキストに出力
    if multi_files and not args.dry_run:
        os.makedirs(output_dir, exist_ok=True)
        with open(multi_log, 'w', encoding='utf-8') as f:
            for aiff_key, file_list in multi_files:
                aiff_title_disp, aiff_album_disp = aiff_key
                f.write(f'# 曲名: "{aiff_title_disp}"  /  アルバム: "{aiff_album_disp}"\n')
                for filepath, title, album in file_list:
                    f.write(f'{filepath}\n')
                f.write('\n')

    if err_files:
        print()
        cprint(YELLOW, f'  警告: タグ読み取り／移動失敗 {len(err_files)} ファイル')
        for f in err_files:
            print(f'    {f}')
        if not args.dry_run:
            os.makedirs(output_dir, exist_ok=True)
            with open(tag_err_log, 'a', encoding='utf-8') as log:
                log.write('# mp3/m4a タグ読み取り／移動失敗\n')
                for f in err_files:
                    log.write(f + '\n')

    # ---- サマリー ----
    print()
    cprint(BLUE, '=' * 56)
    cprint(GREEN, '処理完了')
    print(f'AIFF タグセット数     : {len(aiff_keys)}')
    print(f'mp3/m4a 検索数        : {len(audio_files)}')
    print(f'移動ファイル数        : {move_count}')
    if multi_count > 0:
        print(f'複数一致（保留）      : {multi_count} グループ')

    if move_count > 0 and not args.dry_run:
        print()
        print(f'移動先: {CYAN}{output_dir}{NC}')

    if multi_files and not args.dry_run:
        print(f'複数一致ログ: {CYAN}{multi_log}{NC}')

    total_err = len(aiff_err) + len(err_files)
    if total_err > 0 and not args.dry_run:
        print(f'タグエラーログ: {CYAN}{tag_err_log}{NC}')

    if args.dry_run:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行われていません')


if __name__ == '__main__':
    main()
