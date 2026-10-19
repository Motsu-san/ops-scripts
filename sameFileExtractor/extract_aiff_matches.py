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
import re
import shutil
import subprocess
import sys
import unicodedata
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
    """ffprobe で title / album / artist / album_artist / track / disc タグを取得。
    失敗時は (None, None, None, None, None, None) を返す"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None, None, None, None, None, None
        data = json.loads(result.stdout)
        tags = data.get('format', {}).get('tags', {})
        title = ''
        album = ''
        artist = ''
        album_artist = ''
        track = ''
        disc = ''
        for k, v in tags.items():
            kl = k.lower()
            if kl == 'title':
                title = v.strip()
            elif kl == 'album':
                album = v.strip()
            elif kl == 'artist':
                artist = v.strip()
            elif kl == 'album_artist':
                album_artist = v.strip()
            elif kl == 'track':
                track = v.strip()
            elif kl == 'disc':
                disc = v.strip()
        return title, album, artist, album_artist, track, disc
    except Exception:
        return None, None, None, None, None, None


CACHE_FILENAME = '.tags_cache.json'


def load_tag_cache(folder):
    """指定フォルダ内のタグキャッシュ(.tags_cache.json)を読み込む。無ければ空dict"""
    try:
        with open(os.path.join(folder, CACHE_FILENAME), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_tag_cache(folder, cache):
    """指定フォルダ内にタグキャッシュを保存する。書き込みに失敗しても処理は継続する"""
    try:
        with open(os.path.join(folder, CACHE_FILENAME), 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def file_fingerprint(filepath):
    """mtime + サイズ からファイル変更検知用のフィンガープリントを作る。
    処理中にファイルが削除されるなどして stat に失敗した場合は None を返す
    （呼び出し側はキャッシュ不一致 → get_tags 失敗 のパスで通常のタグ読み取りエラーとして扱う）"""
    try:
        st = os.stat(filepath)
    except OSError:
        return None
    return f'{st.st_mtime_ns}:{st.st_size}'


def find_files(folder, extensions):
    """指定フォルダ以下の対象拡張子ファイルを再帰的に収集（AppleDouble の ._ ファイルは除外）"""
    files = []
    folder = os.path.abspath(folder)
    for root, dirs, filenames in os.walk(folder):
        dirs.sort()
        for filename in sorted(filenames):
            if filename.startswith('._'):
                continue
            if filename.lower().endswith(extensions):
                files.append(os.path.join(root, filename))
    return files


MIN_MATCH_LEN   = 3     # 部分一致に使う文字列の最小文字数
MIN_MATCH_RATIO = 0.4   # 部分一致とみなす最小の長さ比率（短い方 / 長い方）

BRACKETS_RE = re.compile(r'[()\[\]{}<>「」『』【】〔〕｛｝〈〉]')


def normalize(s):
    """比較用に正規化:
    - NFKC正規化で全角/半角の違いを吸収（例: "Ｅ．Ｐ．" -> "E.P."）
    - 大文字小文字を無視
    - 括弧の種類（()・[]・【】など）の違いを無視するため括弧文字自体を除去
    - 空白（全角含む）を除去
    例: "Love & DISCO E. P." と "Love&DISCO E.P." / "(Remastered)" と "[Remastered]" を同一視する"""
    s = unicodedata.normalize('NFKC', s).lower().strip()
    s = BRACKETS_RE.sub('', s)
    return re.sub(r'\s+', '', s)


def partial_match(a, b):
    """どちらかが他方に含まれれば一致（大文字小文字・空白・括弧種別の違いを無視）。
    どちらかが空、または正規化後 MIN_MATCH_LEN 未満の場合は完全一致のみ。
    部分一致の場合も、短い方が長い方の MIN_MATCH_RATIO 未満しか占めない場合は
    "you" のようなありふれた単語による誤マッチとみなし不一致とする"""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    if len(a) < MIN_MATCH_LEN or len(b) < MIN_MATCH_LEN:
        return a == b
    if a not in b and b not in a:
        return False
    shorter_len, longer_len = sorted((len(a), len(b)))
    return shorter_len / longer_len >= MIN_MATCH_RATIO


def artist_match(artist, album_artist, aiff_artist, aiff_album_artist):
    """artist または album_artist のどちらかが完全一致すれば一致（大文字小文字・空白の違いを無視）。
    AIFF 側に artist・album_artist が両方とも無い場合は判定不能として一致扱い"""
    aiff_artist = normalize(aiff_artist)
    aiff_album_artist = normalize(aiff_album_artist)
    if not aiff_artist and not aiff_album_artist:
        return True
    if aiff_artist and normalize(artist) == aiff_artist:
        return True
    if aiff_album_artist and normalize(album_artist) == aiff_album_artist:
        return True
    return False


def parse_num(s):
    """"8" や "1/19" のようなタグ値から先頭の数値部分だけを取り出す（先頭ゼロは無視）"""
    m = re.match(r'\s*0*(\d+)', s)
    return m.group(1) if m else ''


def num_match(value, aiff_value):
    """track / disc 用: AIFF側に値が無ければ判定不能として一致扱い。
    あれば数値部分を完全一致で比較する"""
    aiff_value = parse_num(aiff_value)
    if not aiff_value:
        return True
    return parse_num(value) == aiff_value


def parse_disc_total(s):
    """"1/1" のようなタグ値から総枚数部分（分母）だけを取り出す。無ければ None"""
    m = re.match(r'\s*\d+\s*/\s*0*(\d+)', s)
    return m.group(1) if m else None


def normalize_disc(s):
    """discタグを比較用に正規化する。
    値が空、総数1枚（"1/1"など。ほとんどのCDは1枚組のため）、
    または位置が0（disc番号は1始まりのため、0は古いツールが書き込む「未設定」の意味と考えられる）
    の場合は「意味のある情報なし」とみなして空文字列を返す。それ以外は先頭の数値（disc位置）を返す"""
    if not s or parse_disc_total(s) == '1':
        return ''
    pos = parse_num(s)
    return '' if pos == '0' else pos


def disc_match(value, aiff_value):
    """disc用: "1/1"（総数1枚）や値が空の場合はどちらも「意味のある情報なし」として
    同一視する。それ以外は disc位置が完全一致する場合のみ一致とする
    （どちらか一方だけが意味のある情報を持つ場合は不一致とする）"""
    return normalize_disc(value) == normalize_disc(aiff_value)


def find_aiff_match(title, album, artist, album_artist, track, disc, aiff_keys):
    """タイトル部分一致 かつ アルバム部分一致 かつ (artist または album_artist 一致)
    かつ track一致 かつ disc一致 の AIFF タグを返す。なければ None"""
    for aiff_title, aiff_album, aiff_artist, aiff_album_artist, aiff_track, aiff_disc in aiff_keys:
        if (partial_match(title, aiff_title) and partial_match(album, aiff_album)
                and artist_match(artist, album_artist, aiff_artist, aiff_album_artist)
                and num_match(track, aiff_track) and disc_match(disc, aiff_disc)):
            return (aiff_title, aiff_album, aiff_artist, aiff_album_artist, aiff_track, aiff_disc)
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

    tag_cache     = load_tag_cache(args.aiff_folder)
    new_tag_cache = {}
    cache_hits    = 0

    aiff_keys = []      # [(title_lower, album_lower, artist_lower, album_artist_lower, track, disc), ...]
    aiff_err  = []

    for i, filepath in enumerate(aiff_files):
        print(f'\r  {i + 1}/{len(aiff_files)} 処理中... ', end='', flush=True)
        fp = file_fingerprint(filepath)
        cached = tag_cache.get(filepath)
        if cached and cached.get('fp') == fp:
            title, album, artist, album_artist, track, disc = cached['tags']
            cache_hits += 1
        else:
            title, album, artist, album_artist, track, disc = get_tags(filepath)
        if title is None:
            aiff_err.append(filepath)
            continue
        new_tag_cache[filepath] = {'fp': fp, 'tags': [title, album, artist, album_artist, track, disc]}
        if args.skip_no_tags and (not title or not album):
            continue
        aiff_keys.append((title.lower(), album.lower(), artist.lower(), album_artist.lower(), track, disc))

    save_tag_cache(args.aiff_folder, new_tag_cache)
    print(f'\r  タグ読み取り完了 ({len(aiff_files)} ファイル、キャッシュ利用 {cache_hits} 件)      ')

    if aiff_err:
        print()
        cprint(YELLOW, f'  警告: タグ読み取り失敗 {len(aiff_err)} ファイル (AIFF)')
        for f in aiff_err:
            print(f'    {f}')
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

    search_tag_cache     = load_tag_cache(args.search_folder)
    new_search_tag_cache = {}
    search_cache_hits    = 0

    for i, filepath in enumerate(audio_files):
        print(f'\r  {i + 1}/{len(audio_files)} 処理中... ', end='', flush=True)
        fp = file_fingerprint(filepath)
        cached = search_tag_cache.get(filepath)
        if cached and cached.get('fp') == fp:
            title, album, artist, album_artist, track, disc = cached['tags']
            search_cache_hits += 1
        else:
            title, album, artist, album_artist, track, disc = get_tags(filepath)

        if title is None:
            err_files.append(filepath)
            continue
        new_search_tag_cache[filepath] = {'fp': fp, 'tags': [title, album, artist, album_artist, track, disc]}
        if args.skip_no_tags and (not title or not album):
            continue

        matched_key = find_aiff_match(title, album, artist, album_artist, track, disc, aiff_keys)
        if matched_key is None:
            continue

        grouped[matched_key].append((filepath, title, album))

    save_tag_cache(args.search_folder, new_search_tag_cache)
    print(f'\r  照合完了 ({len(audio_files)} ファイル、キャッシュ利用 {search_cache_hits} 件)      ')
    print()

    # ---- フェーズ2: 移動 or テキスト出力 ----
    match_log     = os.path.join(output_dir, f'matches_{timestamp}.txt')
    multi_log     = os.path.join(output_dir, f'multi_matches_{timestamp}.txt')
    move_count    = 0
    multi_count   = 0
    multi_files   = []   # (aiff_key, [filepaths]) のリスト
    match_list    = []   # (filepath, dest, title, album) の単一一致リスト

    for aiff_key, file_list in sorted(grouped.items(), key=lambda x: x[0]):
        aiff_title_disp, aiff_album_disp, _a_artist, _a_album_artist, _a_track, _a_disc = aiff_key

        if len(file_list) == 1:
            # 1件 → 移動（ドライラン時は移動せず記録のみ）
            filepath, title, album = file_list[0]
            dest = make_dest_path(filepath, args.search_folder, output_dir)
            match_list.append((filepath, dest, title, album))
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

    # 単一一致（移動対象）をテキストに出力（ドライランでも出力する）
    if match_list:
        os.makedirs(output_dir, exist_ok=True)
        with open(match_log, 'w', encoding='utf-8') as f:
            for filepath, dest, title, album in match_list:
                f.write(f'曲名: "{title}"\tアルバム: "{album}"\t{filepath}\t-> {dest}\n')

    # 複数一致をテキストに出力（ドライランでも出力する）
    if multi_files:
        os.makedirs(output_dir, exist_ok=True)
        with open(multi_log, 'w', encoding='utf-8') as f:
            for aiff_key, file_list in multi_files:
                aiff_title_disp, aiff_album_disp, _a_artist, _a_album_artist, _a_track, _a_disc = aiff_key
                f.write(f'# 曲名: "{aiff_title_disp}"  /  アルバム: "{aiff_album_disp}"\n')
                for filepath, title, album in file_list:
                    f.write(f'{filepath}\n')
                f.write('\n')

    if err_files:
        print()
        cprint(YELLOW, f'  警告: タグ読み取り／移動失敗 {len(err_files)} ファイル')
        for f in err_files:
            print(f'    {f}')
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

    if match_list:
        print(f'一致ファイルログ: {CYAN}{match_log}{NC}')

    if multi_files:
        print(f'複数一致ログ: {CYAN}{multi_log}{NC}')

    total_err = len(aiff_err) + len(err_files)
    if total_err > 0:
        print(f'タグエラーログ: {CYAN}{tag_err_log}{NC}')

    if args.dry_run:
        print()
        cprint(YELLOW, '[ドライラン] 実際の移動は行われていません')


if __name__ == '__main__':
    main()
