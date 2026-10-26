# FreeCAD Web 日本語版 (3DCAD)

本リポジトリは [Virtastic/freecad-web](https://github.com/Virtastic/freecad-web) (FreeCAD 1.1.3 / WebAssembly) をもとにした、**日本語専用のカスタマイズ候補**です。

> **現状: GUIの日本語メニューと日本語フォント表示を外部ブラウザで確認済み。** 全ワークベンチとCAD操作の互換性・会社PCでの長時間利用は未検証です。Qt for WebAssemblyで日本語の字形が□になる問題に対し、日本語フォントの同梱、Qtへの動的登録、言語設定の固定化を実装しています。動作確認とログ診断が必要です。

## 日本語UIを標準化（2026-10-26）

[FreeCAD Web 日本語版](https://kana874.github.io/3DCAD/) の**通常URLで日本語フォント・日本語メニューを起動**するよう変更。先行する `?fontMode=static` のブラウザ検証では、「ファイル」「編集」「表示」などのメニューと初期設定画面が日本語で表示され、□文字化けは見られませんでした。GUIの起動と基本表示は確認済みですが、全ワークベンチ・STEP入出力・8GB環境の長時間安定性は未検証です。

- **通常URL（既定）**：固定ウェイトのNoto Sans JPを読み込み、FreeCADGui.setLocale('Japanese') と updateLocale() でUI言語を日本語に変更。
- **<https://kana874.github.io/3DCAD/?fontMode=off>**：Qtの日本語フォント登録を行わない回復モード。日本語は□表示になる可能性があります。
- **<https://kana874.github.io/3DCAD/?fontMode=static-register>**：フォント登録のみの診断モード。UIフォントの切替はしません。
- **<https://kana874.github.io/3DCAD/?experimentalFont=1>**：可変フォント診断。過去にWebAssemblyのfunction signature mismatchが報告されたため通常使用しないでください。

初期表示後にメニューの言語が変わる構成です。ブラウザの既存設計データがある場合は、リロード前にFCStd/STEPとしてダウンロードしてください。

## 日本語設定と翻訳UIは別（2026-10-26）

Edgeの実機画像では、`?fontMode=static` により日本語の文字（設定画面の言語名）は表示できる一方で、メニュー・設定項目の翻訳は英語のままでした。従来の実装は `App.ParamGet(...).SetString('Language','Japanese')` で設定だけ保存していましたが、起動済みGUIに言語切替を通知していませんでした。

**修正**：静的フォントを登録・適用した後、ワークベンチの準備が完了した時点で `FreeCADGui.setLocale('Japanese')` と `FreeCADGui.updateLocale()` を実行し、GUI内の既存コマンドを再翻訳します。公開済みQMファイルは `i18n/index.json` の日本語版のみが対象です。一部ワークベンチの表示は再起動が必要な場合があります。

試験用：[日本語フォント＋翻訳を有効化](https://kana874.github.io/3DCAD/?fontMode=static)。Qt/WASMの描画互換性はブラウザ依存なので、まず機密性のないサンプルのみで確認してください。通常URLでは静的日本語フォントとFreeCADの翻訳APIを自動適用します。復旧モードは`?fontMode=off`です。

## 静的日本語TrueTypeフォントの診断モード（2026-10-26）

最新のEdge 155実機ではFreeCADが起動するものの、Qtのメニューと初期設定画面で日本語が「□」になる。Qt WASM標準のDejaVu系フォントには日本語文字が不足しており、通常のCSSフォント指定ではQt Canvas内に適用されない。

可変Noto Sans JPを追加した従来の方式では、QFontEngineFT::initでWebAssembly function signature mismatchが発生した報告がある。原因はまだ確定していないため、**通常起動は安定優先で従来のまま**とし、固定ウェイト400の静的TTFを作って選択できるようにした。

**試験用（作業中の図面・機密情報を使わずに確認）**

- `https://kana874.github.io/3DCAD/?fontMode=static-register`：静的フォントを読み込んでQtに登録するだけ。UIフォントは変更しない。登録時のクラッシュ有無を調査。
- `https://kana874.github.io/3DCAD/?fontMode=static`：登録に加え、Qtのアプリケーションフォントとして設定する。日本語表示改善を試す。**起動失敗やクラッシュの可能性がある試験機能。**
- 通常の `https://kana874.github.io/3DCAD/` は現在、静的TTFによる日本語表示を標準採用しています。
- 以前の `?experimentalFont=1` は可変フォントの比較診断用として残している。

固定ウェイトフォントはGoogle FontsのNoto Sans JP（SIL OFL）をDockerビルド中にfontToolsで生成し、漢字のcmapと可変フォントテーブルが残らないことを検証する。公開Pagesに配布されるファイルはブラウザ内でのみ使われる。Qtのレンダラに依存するため、ビルドやFontDB登録成功だけで正常描画を保証しない。

## 2026-10-26: Qtフォント処理のfunction signature mismatch切り分け

Edge 155でFreeCAD起動中に `QFontEngineFT::init` → `QWasmFontDatabase::fontEngine` で `RuntimeError: function signature mismatch` が再現したため、WebAssembly/Qtのフォント登録を通常起動から切り離しました。これは**原因の断定ではなく、A/B診断用の暫定対処**です。

- **以前の通常URLの動作**：フォント登録を無効にしていました。現在は静的フォントによる日本語表示を標準化し、明示的な`?fontMode=off`で旧モードに戻せます。
- **フォント診断**：`?experimentalFont=1` — 日本語フォントプリロードとQFontDatabase追加を有効化。**クラッシュの可能性があるため作業ファイルを保存してから試すこと。**
- **WASM起動方式診断**：`?wasmMode=stream` — Qtのプリコンパイル済みWASMモジュール注入を使用せず、Service Worker経由でEmscripten標準のWASM fetch/instantiateStreamingを使用します。
- **組み合わせ**：`?experimentalFont=1&wasmMode=stream` — 問題がフォント追加とWASM起動方式のどちらに関係するか調査するためのモード。

正常に起動するかの確認には、FreeCADのメニューが表示されるまで操作せず、エラーが起きた場合はアプリの「Copy report」で診断内容を取得します。フォント変更の安全性、STEPモデル編集、8GB RAMでの長時間安定性はまだ未検証です。

## GitHub Pages（インストール不要のブラウザ版）

本リポジトリのPages用GitHub Actionsは、上流が提供するFreeCAD Web 1.0.8のDockerイメージから実行エンジンを抽出し、[https://kana874.github.io/3DCAD/](https://kana874.github.io/3DCAD/) に静的サイトとして配置する構成です。

**Pages設定**：リポジトリの Settings → Pages → Build and deployment → Source を **GitHub Actions** にします。初回の公開は、mainブランチへの変更後に Actions → FreeCAD Japanese GitHub Pages で成功したか確認してください。Pagesを有効にしただけでSourceが「Deploy from a branch」の場合、ワークフローは公開先を更新できません。

GitHub Pagesの仕様上、サーバーから任意のHTTPヘッダーを送れません。初回はService Workerを登録して自動リロードし、COOP/COEPを付与してからFreeCAD本体の起動に進みます。WASMとdataはPagesでContent-Encodingを指定できないため、gzipファイルのまま配信し、EdgeのDecompressionStreamで展開します。日本語の翻訳（QM）は日本語のみ配布します。

**制限と注意事項**：

- **実ブラウザでの3D CAD動作・日本語表示は未検証**です。CIのビルド成功は実操作成功の証拠ではありません。
- 先にService Workerが動く必要があるため、初回アクセスで自動リロードすることがあります。サードパーティーCookieやService Workerを禁止する社内ポリシーでは動作しない可能性があります。
- Pagesは静的サイトのため**共有セッション、Server Files、MCPサーバー、リバースプロキシを必要とするAddon Manager機能は提供されません**。メニュー項目が残っていても使用しないでください。
- ファイルはブラウザ内へ保存されるため、FCStdやSTEPは明示的にローカルへダウンロードしてバックアップしてください。GitHub Pages自体にはサーバー保存されません。
- 初回は大容量のWASM/データを取得し、展開後のメモリも使用します。8GB RAM環境で快適に動く保証はありません。
- Pagesのプロジェクトサブパス「/3DCAD/」用です。独自ドメインやリポジトリ名を変更する場合は scripts/build_pages.py の変換とテストを変更してください。

Pages用のビルドは .github/workflows/pages.yml で行い、Git履歴には数百MBの実行バイナリを入れません。公開用の圧縮ファイルはActions実行時に生成されます。

## Dockerでの実行方法

Windows 11 + Docker Desktop（会社の情報システム部門が許可した場合）:

~~~powershell
git clone https://github.com/kana874/3DCAD.git
cd 3DCAD
docker compose -f docker-compose.ja.yml up -d --build
~~~

Edge（137以上）で **http://localhost:8080/** を開きます。PCのIPアドレスを使ったHTTPアクセスはSecure Context要件を満たさないため利用できません。別PCからの利用にはHTTPSとCOOP/COEPヘッダーが必要です。

作成した設計データは原則ブラウザ内に置かれますが、共有セッションとServer Filesを有効にすると、サーバーにデータがコピーされます。業務データでは社内の許可を確認してください。

## 日本語化の方式

1. scripts/localize_freecad.py がFreeCAD WebのHTMLの言語属性・タイトル・翻訳起動スクリプト・Qtプリロード指定を適用します。上流HTMLの想定位置が変わったら明示的に失敗させます。
2. Dockerfile.ja が上流のDockerイメージ ghcr.io/virtastic/freecad-web:1.0.8 をベースに、Google FontsからSIL Open Font LicenseのNoto Sans JPを取得します。
3. play-gui/ja/fonts.json で字体をWebAssemblyの仮想ファイルシステムへプリロードします。
4. play-gui/ja/freecad-ja.js はFreeCADのPython APIが起動した後、QtのQFontDatabase.addApplicationFontでフォントを登録し、Qtアプリ全体に適用します。次回起動時の表示言語を日本語へ設定します。
5. 上流に含まれる日本語翻訳QMファイルを使います。**初回起動中に翻訳が適用されなかった場合、保存して再読み込みしてください。**

**制限:** フォント修正はQtの初期化後に適用されます。初期設定ダイアログが先に描画されるため、その場の即時修正、全ワークベンチの日本語訳、初回起動時の完全日本語表示は未検証です。Webページ側の英語メッセージは一部残ります。

## 上流ソースの取り込み

GitHubには空の既存リポジトリを他者リポジトリのフォークとして関連付ける通常の操作がありません。このリポジトリは独立した派生リポジトリで、GitHub上のforkメタデータや元のGitコミット履歴は保持しません。

.github/workflows/import-upstream-ja.yml は上流を取得し、ソース一式を作業ブランチへ複製して scripts/localize_freecad.py を適用します。成功後はその履歴と実行ログを確認してください。実行されない場合はActionsのImport upstream freecad-web (JA)から手動起動できます。実行にはGitHub Actionsのcontents: write許可が必要です。

## 動作検証

- Edgeで初回起動、日本語メニューが□にならないことを確認
- Networkで ja/NotoSansJP-VF.ttf と ja/fonts.json がHTTP 200となることを確認
- Consoleで Japanese font active を確認
- FreeCADの新規作成 → スケッチ → 押し出し → STEP保存を検証
- 8GB RAM環境ではメモリ不足が起きないことを別途確認

## 出典・ライセンス

- 上流: [Virtastic/freecad-web](https://github.com/Virtastic/freecad-web), main (取り込み時のコミットSHAを作業ログに保存)
- 上流 FreeCAD / web frontend: LGPL-2.1-or-later, LICENSE、NOTICE、LICENSES/ に元の著作権・第三者ライセンス
- 日本語フォント: [Google Fonts Noto Sans JP](https://github.com/google/fonts/tree/main/ofl/notosansjp), SIL Open Font License 1.1, アプリ内 /ja/OFL.txt
- 本リポジトリの変更点もLGPL-2.1-or-laterで提供

**注:** この派生版はFreeCAD本家・Virtastic・Googleによる公式サポート／承認製品ではありません。
