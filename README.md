# FreeCAD Web 日本語版 (3DCAD)

本リポジトリは [Virtastic/freecad-web](https://github.com/Virtastic/freecad-web) (FreeCAD 1.1.3 / WebAssembly) をもとにした、**日本語専用のカスタマイズ候補**です。

> **現状: Dockerビルド・静的配信テスト成功、ブラウザの日本語描画は未検証。** 日本語表示を保証する完成ビルドではありません。Qt for WebAssemblyで日本語の字形が□になる問題に対し、日本語フォントの同梱、Qtへの動的登録、言語設定の固定化を実装しています。動作確認とログ診断が必要です。

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
