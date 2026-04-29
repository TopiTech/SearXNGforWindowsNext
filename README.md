# SearXNG for Windows Next

このリポジトリは、Windows 環境で SearXNG を動作させつつ、LLM APIや CLI ワークフローから使いやすい JSON 検索結果取得を実現することを目的としています。

## 目的

- Windows で SearXNG をネイティブに動かす
- ブラウザ UI に依存せず、`/search?q=...&format=json` で JSON レスポンスを取得できるようにする
- `searxng/searxng` の upstream 変更を反映し、Windows 互換パッチを維持する

## 構成

- `SearXNG for Windows.bat`: Windows 上で組み込み Python を使い、SearXNG を起動するバッチ
- `python/`: 埋め込み Python 環境と依存パッケージ
- `config/settings.yml`: Windows 向け設定と JSON 出力有効化
- `.github/workflows/upstream-sync.yml`: upstream 同期を自動化するワークフロー
- `tools/`: upstream 同期・パッチ適用・動作確認用スクリプト
- `UPSTREAM_VERSION.txt`: upstream 同期の metadata

## 使い方

1. リポジトリを展開する
2. `SearXNG for Windows.bat` を実行する
3. ブラウザから以下にアクセスする（起動確認）

```http
http://127.0.0.1:8888
```

### 初回セットアップ（必須）

リポジトリには最小限のファイルのみを同梱しています。起動前に埋め込み Python 環境へ必要なパッケージをインストールしてください。

PowerShell での実行例:

```powershell
.\tools\install-requirements.ps1
```

またはバッチ:

```bat
.\tools\install-requirements.bat
```

これにより `config/requirements.txt`（および存在する場合 `config/requirements-server.upstream.txt`）がインストールされます。

### CLI / JSON API の利用例

ブラウザではなくコマンドや生成AIから直接使う場合:

```powershell
curl "http://127.0.0.1:8888/search?q=example&format=json"
```

または PowerShell の場合:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8888/search?q=example&format=json" | Select-Object -ExpandProperty Content
```

このプロジェクトは、Web UI からの検索は想定していません。JSON API を第一に使うことを想定しています。

## Windows での起動

`SearXNG for Windows.bat` は次のように動作します:

- `python\python.exe` を使って起動
- `SEARXNG_SETTINGS_PATH` で `config/settings.yml` を指定
- Windows ネイティブで `python\Lib\site-packages\searx\webapp.py` を実行

## 設定

`config/settings.yml` はデフォルトで JSON 出力を許可し、Windows 向けに調整されています。

- `search.formats`: `html` と `json`
- `server.bind_address`: `127.0.0.1`
- `server.port`: `8888`
- `outgoing.request_timeout`: `3.0`
- `outgoing.pool_maxsize`: `20`

必要に応じて `config/settings.yml` を編集してください。

## upstream 同期

このリポジトリには、`searxng/searxng` からの同期を想定した次の仕組みがあります:

- `.github/workflows/upstream-sync.yml`: GitHub Actions で upstream を定期的／手動で同期
- `tools/sync-upstream.ps1`: upstream ソースの取得と Windows パッチ適用
- `UPSTREAM_VERSION.txt`: 同期済み upstream commit を記録

これにより、Windows 固有の改修を維持しつつ 最新のupstream 変更を取り込むことができます。

## 推奨環境

- Windows 10 / 11
- 32bit/64bit 共に動作可能な埋め込み Python 環境
- ローカルのみで動作させることを前提とした設定

## ライセンス

このプロジェクトはルートの `LICENSE` に従い、GNU Affero General Public License v3（AGPL-3.0）で配布されます。

`UPSTREAM_VERSION.txt` に記載された upstream 情報を併せて管理してください。
