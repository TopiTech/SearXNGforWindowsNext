<p align="center">
</p>

# SearXNG for Windows Next 🚀

**GenAIフレンドリーな検索体験を、Windowsネイティブ環境で。**

このプロジェクトは、Windows環境でSearXNGを最適に動作させつつ、LLM（大規模言語モデル）やAPIワークフローから利用しやすい**軽量・高速な検索結果取得**を実現することを目的としたフォークリポジトリです。

---

##  主な特徴

-  Windows Native: 組み込みPython環境により、DockerなしでWindows上で直接動作。
-  GenAI Optimized: LLMのトークン消費を抑える専用の `json_lite` フォーマットを搭載。
- High-Quality Engines: Bing, DuckDuckGo, Mojeekなどの信頼性の高いエンジンを標準で最適化。
- Auto-Sync Architecture: `searxng/searxng` 本家の最新コードを追従しつつ、Windows固有のパッチを自動適用。常に最新の状態に。
- Secure & Local: ローカルホストでの動作に特化したセキュアなデフォルト設定。

---

##  クイックスタート

### 1. セットアップ
リポジトリをダウンロード(クローン)後、まずは依存パッケージをインストールします。

```powershell
# PowerShellで実行
.\tools\install-requirements.ps1
```

### 2. 起動
`SearXNG for Windows.bat` を実行します。起動後、ブラウザで [http://127.0.0.1:8888](http://127.0.0.1:8888) にアクセスできれば成功です。

### 3. 動作確認 (Testing)
以下のコマンドを実行して、特に `json_lite` 形式のレスポンスが正しく返ってくるか確認できます。

**PowerShell:**
```powershell
Invoke-RestMethod "http://127.0.0.1:8888/search?q=SearXNG&format=json_lite" | ConvertTo-Json -Depth 5
```

**curl:**
```bash
curl -G "http://127.0.0.1:8888/search" --data-urlencode "q=SearXNG" --data-urlencode "format=json_lite"
```

---

##  GenAI / LLM での活用

このプロジェクトの最大の特徴は、AIエージェント向けの**超軽量JSONレスポンス**です。

### `json_lite` フォーマット
通常のJSONレスポンスに含まれる膨大なメタデータを削ぎ落とし、AIが必要とする情報（タイトル・URL・内容）のみを返します。

**リクエスト例:**
```http
GET http://127.0.0.1:8888/search?q=SearXNG&format=json_lite
```

**レスポンス例:**
```json
{
  "query": "SearXNG",
  "results": [
    {
      "title": "SearXNG Documentation",
      "url": "https://docs.searxng.org/",
      "content": "SearXNG is a free internet metasearch engine..."
    }
  ]
}
```

---

##  構成ファイル

- **`SearXNG for Windows.bat`**: メインの起動スクリプト。
- **`config/settings.yml`**: ユーザー設定（エンジン、ポート、フォーマットなど）。
- **`tools/sync-upstream.ps1`**: 本家リポジトリとの同期およびパッチ適用。
- **`python/`**: ポータブルな組み込みPython環境。

---

##  メンテナンスと同期

GitHub Actions（`.github/workflows/upstream-sync.yml`）により、本家のアップデートが週次で自動チェックされます。同期プロセスでは以下の処理が行われます：

1. `searxng/searxng` の最新ソースを取得。
2. Windows互換性およびGenAI向け機能のパッチを再適用。
3. `requirements.txt` の変更を検知し、ユーザーに通知。
4. **ユーザーの `settings.yml` は上書きされません。**

---

## 📜 ライセンス

このプロジェクトはフォーク元に乗っ取り **GNU Affero General Public License v3 (AGPL-3.0)** の下で公開されています。
詳細は [LICENSE](LICENSE) ファイルを参照してください。
