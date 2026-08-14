# Code Ontology Companion: 現在のアーキテクチャと対応ワークフロー

[English](../ARCHITECTURE_AND_ROADMAP.md) | [한국어](../ko/ARCHITECTURE_AND_ROADMAP.md) | [日本語](ARCHITECTURE_AND_ROADMAP.md) | [简体中文](../zh-CN/ARCHITECTURE_AND_ROADMAP.md)

## 1. 目的

Code Ontology Companion は、許可された Java/Spring および Python リポジトリを決定論的に解析し、プライバシーに配慮したローカルコード知識グラフとして維持します。バージョン 0.5.2 は、イミュータブルスナップショット、根拠付きの関係、adapter coverage、RDF 1.1 Turtle、PROV-O 互換リネージ、アクセシブルな 2D とオプションの 3D を備えたオフラインワークベンチ、読み取り専用ローカル MCP、オプションの Ollama エンリッチメントをサポートします。

## 2. 現在の実装原則

- **ローカルファースト:** ソース解析、スナップショット、検索、可視化、リネージをローカルで処理します。
- **決定論的コア:** 同じ入力とバージョンから同じ正規化結果を生成します。
- **イミュータブルな履歴:** 新しい解析を新しいスナップショットとして公開し、以前のスナップショットとリネージを保持します。
- **読み取り専用検索:** MCP は登録済み workspace ID のみを受け取り、照会ツールだけを提供します。
- **明示的な同意:** 初期化とオプションの Ollama 接続には、データ範囲の開示と許可が必要です。
- **静的証拠:** 関係、影響、比較結果を静的構造証拠として分類します。

## 3. 現在の実装アーキテクチャ

```text
許可された Java/Spring または Python リポジトリ
  -> read-only doctor / preflight
  -> 安全な source manifest と制限付き静的解析
  -> staging artifact 検証
  -> immutable snapshot の atomic promotion
  -> ontology.json / ontology.ttl / report.md / graph.html
  -> append-only lineage.jsonl / portable lineage.ttl
  -> CLI と read-only local MCP query
  -> optional fixed-loopback Ollama inferred sidecar
```

### アナライザー

アナライザーは Python standard library だけを使用します。`.java` と `.py` の通常ファイルを制限されたサイズと件数で読み取り、対象リポジトリを import、compile、build、test、run しません。Java package/import/type/method/inheritance、Spring stereotype/bean/injection/AOP/proxy signals、Python module/import/type/function/decorator/call/inheritance と heuristic pipeline role を抽出します。Java の unqualified call または `this.method(...)` は、同じ owner で method name と argument count が一致する candidate が 1 つだけの場合に解決します。認識済み imported `Type.method(...)` は `ExternalCallable` とし、同一 arity overload と dynamic receiver は保守的に省略します。

### 関係 evidence と adapter coverage

バージョン 0.5.2 は従来の `source`/`target`/`type` relation triple と安定した identity を維持します。各 relation の追加 `evidence` array には、安定した `rule_id`、定性的な `basis`（`direct_syntax`、`resolved_static`、`framework_semantic`、`name_heuristic`）、`runtime_status`（`not_applicable`、`runtime_unknown`）、任意のリポジトリ相対 `path`/`line_start`/`line_end`、制限付き `limitations` が入ります。

`document.quality` contract version `1.0` は、`relationship_evidence` の `total_edges`、`documented_edges`、`missing_evidence`、`coverage_percent`、`basis_counts`、`runtime_status_counts` と、Java/Python adapter の `status`、`detected`、`capabilities`、`unsupported_runtime` を報告します。両 adapter は常に表示され、`detected` がその言語の実在を区別します。定性的 basis は数値確率ではなく、parse warning 0 件は完全な静的または runtime coverage の証明ではありません。RDF は従来の direct triple を維持し、追加の `RelationshipEvidence` resource でこの metadata を表します。

### スナップショットとリネージ

各スナップショットには、運用検索用 JSON、ポータブルな RDF 1.1 Turtle、要約 report、自己完結型 HTML workbench、非公開 source manifest が含まれます。workspace lineage は observed、declared、inferred、validated、approved の evidence を区別し、append-only JSONL と Turtle で維持します。

### オフラインワークベンチ

ワークベンチは完全な portable index を検索し、選択した制限付き関係 neighborhood だけを materialize します。既定の `2D 構造`ビューとオプションの `3D 空間`コンステレーションは、同じ node、relation、evidence、filter、詳細パネルを使用します。3D は標準 Canvas2D perspective と決定論的な静的位置を使い、CDN、WebGL、package、worker、telemetry、network を追加しません。

Pointer orbit/zoom には、keyboard orbit、zoom、camera reset、node 移動・選択、root への復帰があります。検索、DOM 関係一覧、詳細パネル、2D graph は screen reader を含む同等の探索経路です。Reduced-motion と forced-colors/high-contrast を尊重し、mode と selection 状態を assistive technology に公開し、非表示タブでは描画を停止して canvas 失敗時は 2D に戻ります。これは WCAG 2.2 AA を目標とする設計契約であり、別途の手動 AT/browser 検証なしに包括的な準拠を主張するものではありません。

### 読み取り専用ローカル MCP

stdio MCP サーバーは、workspace 一覧、status、symbol search、bounded neighbors、history、snapshot changes、lineage を照会する 7 個のツールを提供します。待受ポートを開かず、任意の filesystem path ではなく登録済み `workspace_id` を受け取ります。Python 3.9 以降を使用する Windows、macOS、Linux で直接 Python stdio 設定を利用できます。

### オプションのローカル LLM

ユーザーが明示的に同意すると、別個の helper が既存 Ollama の固定 IPv4 loopback `127.0.0.1:11434` だけへ接続します。helper は制限された portable ontology metadata を決定的に分割して送信し、正規化された提案を別個の `inferred` sidecar として atomic に保存します。observed ontology と RDF は変更しません。

## 4. 対応機能

| 領域 | バージョン 0.5.2 の対応機能 |
| --- | --- |
| 入力 | 許可された通常の `.java`、`.py` ファイル |
| Java/Spring | 構造、generic/record/nested type、inheritance、annotation、bean、injection、AOP/proxy signal |
| Python | module、symbol、import、call、inheritance、decorator、nested scope、pipeline role |
| Ontology | JSON index、追加 relation evidence、adapter coverage、legacy-compatible RDF 1.1 Turtle、安定した `co:` vocabulary |
| Provenance | PROV-O 互換 append-only lineage と区別された evidence type |
| Refresh | private fingerprint、stable manifest、staging validation、full reanalysis、atomic promotion |
| Search | CLI、offline workbench、7 個の read-only local MCP tool |
| Visualization | full-index search、既定 2D、オプション Canvas2D 3D、bounded relation lens、keyboard/pointer control、reduced motion/high contrast、current/previous comparison |
| Local LLM | 既存 Ollama の検出、同意に基づく model 選択、bounded batching、atomic inferred sidecar |
| Platform | Python 3.9+ を使用する Windows、macOS、Linux |

## 5. データと実行の境界

アナライザーは、シークレットに似た名前、link/reparse point、special file、VCS、dependency、generated output、cache path をスキップします。Portable RDF、HTML、MCP response には、リポジトリの絶対パスと完全な source fingerprint を含めません。ローカル LLM payload には、source body、comment、credential、absolute path、private manifest、raw file hash を含めません。

アナライザー、workspace CLI、workbench、launcher、MCP は直接の network request を行いません。オプションの Ollama helper だけが同意後に固定 loopback endpoint を使用します。プラグインは Python、Java、model、graph database、package manager、daemon、watcher を自動インストールしません。

## 6. 解釈上の制限

静的 graph は runtime trace、active dependency-injection container、vulnerability verdict、causal proof ではありません。Reflection、generated code、runtime condition、dynamic proxy、external configuration、dependency version、Python metaprogramming により、一部の関係が完全でない場合があります。表示される parse warning と evidence type を併せて確認し、runtime fact は別の runtime evidence で検証してください。

RDF/Turtle は RDF 1.1-compatible store へ移植できます。Store 固有の index、reasoning rule、authentication、extension は、各 store の設定に合わせて mapping します。

## 7. 現在のロードマップ

この roadmap は方向性を示すもので、日付を約束しません。0.5.x は v0.3.4 architecture roadmap の大規模 visualization 方向を制限付きオフライン探索として進め、オプション storage/query は future work として分離します。

0.5.0 以降には bounded Java/Python adapter coverage、定性的 static evidence basis、unsupported-runtime indicator、source-attributed relation evidence、保守的な Java call、ontology quality gate、同じ制限付き近傍を共有する既定 2D／オプション Canvas2D 3D、visualization quality gate が含まれます。

今後の方向には、setup diagnostics/progress/actionable failures、foreground watcher debouncing/single-flight、quality fixture で正当化された bounded parser/language adapter、オプションの RDF store/SPARQL/large-graph profile、別途範囲を限定した build/config/authenticated read-only runtime evidence adapter があります。新言語、graph database、SPARQL/REST profile、whole-repository 3D、target execution、live runtime tracing、autonomous code change/deployment、security verdict、local-LLM inference の observed evidence への昇格はバージョン 0.5.2 の機能ではありません。
