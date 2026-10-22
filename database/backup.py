"""データベースのバックアップファイルを作る（!db_backup と自動バックアップで共用）"""
import datetime
import gzip
import os
import shutil
import sqlite3
import tempfile

import config

JST = datetime.timezone(datetime.timedelta(hours=9))
FILE_PREFIX = "tensoku_stats_backup_"


def create_backup_file(compress: bool = False) -> str:
    """稼働中でも一貫した状態のコピーを一時ファイルに作り、そのパスを返す（削除は呼び出し側で行う）"""
    stamp = f"{datetime.datetime.now(JST):%Y%m%d_%H%M%S}"
    # 自動バックアップと !db_backup が同時に動いても同じファイルを使わないよう、名前を一意にする
    fd, tmp_path = tempfile.mkstemp(prefix=f"{FILE_PREFIX}{stamp}_", suffix=".db")
    os.close(fd)
    # ファイルをそのままコピーすると書き込み途中の状態を写すことがあるため、SQLite のバックアップ機能を使う
    src = sqlite3.connect(config.DB_PATH)
    try:
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    if not compress:
        return tmp_path
    gz_path = tmp_path + ".gz"
    try:
        with open(tmp_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    finally:
        os.remove(tmp_path)
    return gz_path
