# サードパーティ ライセンス表記

I'm fine は以下のオープンソースライブラリを使用しています。
配布される exe (PyInstaller によるビルド) には、これらのライブラリが
バイナリとして同梱されます。

## Pillow

- ライセンス: MIT-CMU (HPND)
- ソース: https://github.com/python-pillow/Pillow

## pystray

- ライセンス: **GNU Lesser General Public License v3.0 (LGPL-3.0)**
- ソース: https://github.com/moses-palmer/pystray

pystray は LGPL-3.0 で提供されています。本アプリは PyInstaller の
`--onefile` ビルドにより pystray を含む全依存ライブラリを単一の実行
ファイルへまとめて配布しています。LGPL は原則としてライブラリ部分を
利用者が差し替え・再リンクできる状態を求めており、単一exeへの静的な
まとめ方はこの要件との関係で解釈の余地があります。

pystray 自体のソースコードは上記リポジトリで公開されており、
ビルドに用いているバージョンは `requirements.txt` を参照してください。
LGPL 準拠についてより厳密な対応が必要な場合は、専門家への相談を推奨します。

## six (pystray の依存)

- ライセンス: MIT
- ソース: https://github.com/benjaminp/six

## PyInstaller (ビルドツール)

- ライセンス: GPL-2.0-or-later (ブートローダー部分にはリンク例外あり)
- ソース: https://github.com/pyinstaller/pyinstaller

PyInstaller のブートローダーには、生成される実行ファイル (本アプリの
配布物) を GPL の対象外とする例外条項があります。詳細は PyInstaller の
`COPYING.txt` を参照してください。
