# Code Ontology Companion: 全体アーキテクチャとバージョンロードマップ

[English](../ARCHITECTURE_AND_ROADMAP.md) | [한국어](../ko/ARCHITECTURE_AND_ROADMAP.md) | [日本語](ARCHITECTURE_AND_ROADMAP.md) | [简体中文](../zh-CN/ARCHITECTURE_AND_ROADMAP.md)

## 1. 目的

Code Ontology Companion は、許可されたアプリケーションのソース、設定、ビルドメタデータ、
範囲を限定したランタイム evidence を、ポータブルでバージョン管理されたコードオントロジーへ
変換する、ローカルファーストの AI データパイプラインを目指して進化しています。
このパイプラインは、LLM に直接の書き込み、デプロイ、注文、認証情報、資金に関する権限を
与えることなく、低コストのコード理解、変更影響分析、evidence lineage、慎重に統制された
改善ワークフローを支援するものです。

バージョン 0.3.2 は、より限定された製品約束に対する最初の安定した機能基準を確立しました。
現在のバージョン 0.3.4 は、その機能基準を維持しながら、公開 Skills-only／OpenAI 提出プロファイルを
汎用コードオントロジー機能だけに分離しました。その範囲は、決定論的な Java/Spring および Python 静的解析、イミュータブルな
オントロジースナップショット、RDF 1.1 Turtle エクスポート、PROV-O 互換リネージ、
オフライン可視化、CLI 探索、同意に基づくオプションの Ollama エンリッチメント、読み取り専用の
ローカル MCP プロファイルです。以下に記す完全な常時稼働パイプラインには、まだ達していません。

## 2. エンジニアリング原則

- **ローカルファースト:** 既定ではローカルのストレージ、解析、可視化、モデルを使用します。
  外部リソースは、ユーザーが明示的に設定するオプションのフォールバックです。
- **KISS:** グラフデータベース、モデル、daemon、ネットワークサービスがなくても、
  依存関係ゼロのファイルスナップショット経路を実用的に保ちます。
- **YAGNI:** Graph DB、SPARQL、REST、CI 自動化、モデルのインストールは、検証済みの
  ユースケースで必要になったときに限り、オプションのアダプターとして追加します。
- **DRY:** 正規オントロジーと provenance model は 1 つだけ維持します。すべての
  ストレージ、照会、可視化、改善コンポーネントが、同じイミュータブルな identity と
  receipt を利用します。
- **決定論的コア:** 静的解析、fingerprint、candidate identity、validation、promotion gate は
  決定論的に保ちます。LLM の出力は助言にすぎません。
- **Fail closed:** 古いソース、曖昧な binding、不正な evidence、未対応の runtime state、
  署名失敗、部分的 mutation を approval と解釈してはなりません。
- **移植性を前提に設計:** RDF 1.1 Turtle と文書化された provenance を、ファイルストレージと
  オプションのオントロジーストア間の移行境界として維持します。

## 3. 目標アーキテクチャ

```text
使用を許可されたアプリケーション
  source + build + configuration + 範囲を限定した runtime evidence
                         |
                         v
  Host preflight と明示的な setup orchestrator
  - OS/CPU/RAM/disk/runtime の検出
  - 既存の Python、Java、Ollama、store の検出
  - installation または service 変更前の preview と同意
                         |
                         v
  入力 adapter
  - Java/Spring       - Python           - 将来の言語 adapter
  - build metadata    - configuration    - 認証済み read-only runtime facts
                         |
                         v
  決定論的な解析と正規化
  - symbol、call、import、inheritance、DI/AOP/proxy signal
  - pipeline role、policy leaf、runtime branch、evidence binding
                         |
                         v
  正規オントロジーと provenance model
  - RDF 1.1 / オプション OWL profile / SHACL validation profile
  - observed、declared、inferred、validated、approved evidence class
  - immutable snapshot、diff、lineage、release と policy identity
                         |
          +--------------+---------------+
          |                              |
          v                              v
  既定の file snapshot store      オプション store adapter
  JSON + Turtle + lineage         Jena/RDF4J/GraphDB/Stardog または互換 store
          |                              |
          +--------------+---------------+
                         |
                         v
  照会と表示の plane
  - Codex Skill/CLI       - read-only MCP
  - オプション SPARQL/REST - 対話型 graph と version comparison
                         |
                         v
  オプションの助言 intelligence
  - 既存 local LLM の検出と user-selected enrichment
  - 数値を含まない仮説と説明だけを許可
  - inferred sidecar は observed fact から分離
                         |
                         v
  分離された統制対象 improvement controller
  - 事前登録済み candidate と deterministic fingerprint
  - paired replay、purged OOS、cost calibration、natural shadow evidence
  - domain policy gate, signed admission, CAS, canary, rollback
  - 独立した authority gate を通じた issue/PR または policy activation
                         |
                         v
  新たに観測された outcome と source 変更を evidence pipeline へ戻す
```

アプリケーションサーバーは、このシステム内の 1 つの producer かつ consumer であり、
AI データパイプライン全体ではありません。Spring Boot/Tomcat アプリケーションは、認証済みの
読み取り専用 runtime facts を公開し、検証済み policy を利用できます。一方、ontology、experiment、
validation、governance の各段階は分離したままです。

## 4. アーキテクチャのプレーン

### 4.1 セットアップとホスト検出

将来の setup orchestrator は、新しいものを提案する前に既存コンポーネントを検出します。
OS がサポートするパッケージマネージャーと、ローカルで利用可能な runtime を優先します。
あらゆるインストール、モデルダウンロード、サービス起動、ポート binding、認証情報の使用、
外部 endpoint には、事前の明示的なプレビューとユーザー許可が必要です。
プラグインのインストールだけで、ホストを密かに変更してはなりません。

最小プロファイル:

1. **ゼロインストールプロファイル:** 同梱 Python スクリプト、イミュータブルファイル、CLI、
   オフラインワークベンチ。
2. **完全ローカルプロファイル:** ゼロインストールプロファイルに、同梱の読み取り専用 stdio MCP
   を加えたもの。
3. **拡張ローカルプロファイル:** オプションのグラフストア、SPARQL/REST 管理サービス、foreground
   または OS 管理の refresh trigger、既存ローカル LLM。
4. **外部フォールバックプロファイル:** ローカルリソースが不足し、データ境界を受け入れた場合に
   限り、ユーザーが設定した remote RDF または model service を使用。

次の値はユーザー向けの目安であり、厳密な互換性を保証するものではありません。

| Profile | macOS の目安 | Windows の目安 | 想定用途 |
| --- | --- | --- | --- |
| File-only 最小 | CPU 4コア、RAM 8 GiB、SSD 空き 5 GiB | x64、CPU 4コア、RAM 8 GiB、SSD 空き 5 GiB | Graph DB やローカル LLM を使わない小・中規模 repository |
| 推奨ローカル | Apple silicon、RAM 16 GiB、SSD 空き 20 GiB | CPU 6コア以上、RAM 16 GiB、SSD 空き 20 GiB | 現在の full-local workflow と軽量なオプション service 1つ |
| 拡張ローカル | Apple silicon、RAM 24-32 GiB、SSD 空き 50 GiB 以上 | CPU 8コア以上、RAM 32 GiB、SSD 空き 50 GiB 以上、8 GiB 以上の GPU はオプション | 大規模 repository、RDF store、量子化された 7-9B クラス model の同時利用 |

低スペックの PC では、graph storage と model enrichment を無効にした file-only profile を維持します。Preflight はこの表だけで installation を承認せず、実際の repository、選択した model、store の要件を測定しなければなりません。

### 4.2 入力と言語アダプター

各言語アダプターは、独自のオントロジーを定義するのではなく、正規の symbol／relationship model
を出力します。Java/Spring 解析は package、type、method、record、import、inheritance、
bean declaration、injection、annotation、aspect、transaction、asynchronous execution、cache、
authorization、retry、proxy signal を対象とします。Python 解析は module、class、function、
decorator、call、import、inheritance、data-pipeline role を対象とします。

将来のアダプターは、discovery、parsing、normalization、validation、capability reporting のための、
範囲を限定した interface を使用します。build／configuration adapter は、対象コードを実行せずに、
ソース構造を dependency version と effective configuration に結び付けます。runtime adapter は、
認証済み、読み取り専用、sanitized、期限付きでなければならず、static evidence から分離します。

### 4.3 正規オントロジー

RDF 1.1 Turtle を移植性の基準として維持します。完全な設計では、相互運用可能なセマンティクスの
ための文書化された OWL profile と、成果物検証用の SHACL shapes を追加できます。ただし、
reasoner の出力が observed fact になることはありません。すべての inference は、producer、
algorithm または model identity、source snapshot、timestamp、validation state を保持します。

provenance model は次を関連付けます。

```text
source revision
  -> ontology snapshot
  -> 仮説
  -> candidate と domain policy
  -> dataset、replay、OOS、cost、shadow evidence
  -> 判定と admission receipt
  -> canary または deployment
  -> 観測された outcome
  -> rollback または次の experiment
```

これは、「この日、order-policy の改善によって stop line が 2% から 3% に変わった」といった
記述の基盤になります。同時に、その記述が observed、inferred、validated、approved の
どれであるかを保持します。

### 4.4 ストレージと照会

ファイルストアは、ポータブルで、調査しやすく、バックアップに適し、サービスを必要としないため、
引き続き既定値です。オプションの store adapter は、同じ Turtle と provenance を RDF 互換の
グラフデータベースへインポートします。ストア固有の index、reasoning extension、認証、port、
license は正規モデルの外部にあり、明示的に設定しなければなりません。

照会機能は段階的に発展します。

- 決定論的な CLI search、impact、history、diff、lineage。
- 登録済みワークスペースに限定した読み取り専用 MCP。
- 標準ベースのグラフ照会のためのオプションの SPARQL。
- オプションの localhost REST 管理／health API。
- 範囲を限定した決定論的ツールを介する Codex の自然言語 orchestration。

自然言語の出力によって evidence strength が高まることはありません。

### 4.5 更新とデータパイプライン

refresh pipeline は、非公開の source fingerprint で変更のない作業を省略し、変更された解析を
staging で構築し、すべての成果物を検証し、イミュータブルな snapshot をアトミックに昇格し、
失敗時には直近の正常な snapshot を維持します。

完全な設計では次を追加します。

- 言語を考慮したファイル単位の増分解析。
- 明示的な Git hook、CI、foreground watcher trigger。
- debouncing と single-flight lease。
- build/config/runtime evidence adapter。
- provenance に結び付いた部分更新と dependency invalidation。
- snapshot または lineage を重複公開しない retry。

常駐 watcher や daemon が密かにインストールされることはありません。

### 4.6 ローカル LLM の境界

決定論的オントロジーに LLM は不要です。明示的に有効化された場合、システムは利用可能な既存の
ローカルモデルを検出し、ユーザーにモデル選択を求め、範囲を限定したポータブルメタデータだけを
送信し、正規化された提案を別の inferred evidence として保存します。

将来の installer は CPU、GPU、memory、disk、OS、license、provenance を確認した後、適切な
ローカルモデルを提案できます。そのモデルのダウンロードまたは起動には、なお明示的な同意が
必要です。remote/cloud model はオプションのフォールバックであり、黙って選択してはなりません。

LLM が行えること:

- 構造上の変更を要約する。
- 数値を含まない仮説を提案する。
- 決定論的な verdict を説明する。
- 調査対象を提案する。

LLM が行えないこと:

- observed evidence を捏造する。
- candidate value または candidate ordering を選択する。
- sign、approve、promote、deploy、order submit を行う。
- safety、reconciliation、idempotency、cost、OOS の gate を緩和する。

### 4.7 改善自動化の境界

Code Ontology Companion は、読み取り中心の knowledge／evidence component であり続けます。
別個の improvement controller が experiment とあらゆる write workflow を所有します。
ドメイン固有の experiment、policy、deployment、trading stack は、別プロジェクトに属する downstream extension です。この extension はバージョン付き evidence contract を利用し、独自の deterministic evaluation、admission、canary、rollback gate を定義します。Companion core または公開 roadmap には含まれません。

公開 Skills-only／OpenAI 提出プロファイルには、AETHER Lab の `runtime-binding` コマンド、
プロジェクト固有のポリシースキーマ、レシート生成機能、専用評価ケースは含まれません。
GitHub の完全版／ローカルプロファイルにだけ残る downstream extension は、policy leaf と
static production branch の間に限定的でイミュータブルな binding を生成できます。
この extension は OpenAI がホストする提出物には含まれず、その receipt は runtime execution、
safety、profitability、policy を変更する権限、注文を送信する権限、資金を移動する権限を証明しません。

## 5. 現在の公開基準: バージョン 0.3.4

| 領域 | バージョン 0.3.4 | 全体設計との関係 |
| --- | --- | --- |
| 製品 | 公開 Skills-only: Codex Skill、Python CLI、offline workbench。完全版／ローカル: read-only stdio MCP を追加 | 実用的なローカル ontology pipeline。常時稼働ではない |
| 入力 | 公開プロファイルは許可された `.java` と `.py` のみ | source core は実装済み。build/config/runtime adapter は未実装 |
| Java/Spring | 決定論的な構造抽出と保守的な DI/AOP/proxy signal 抽出 | 静的な可能性であり、active ApplicationContext の事実ではない |
| Python | 決定論的な module、symbol、call、import、inheritance、pipeline-role 抽出 | core は実装済み。adapter SPI は未実装 |
| オントロジー | JSON、RDF 1.1 Turtle、安定した `co:` vocabulary、PROV-O 互換 lineage | core は実装済み。オプションの OWL/SHACL は未実装 |
| ストレージ | イミュータブルな file snapshot、atomic current pointer、append-only lineage | default store は実装済み。graph DB はオプションの将来項目 |
| 検索 | 公開プロファイル: CLI query/impact/diff/history/lineage と workbench search。完全版／ローカル: 7 個の read-only MCP tools | MCP はローカル実装済み。SPARQL/REST は未実装 |
| 更新 | fingerprint skip、foreground watch、full staging reanalysis、atomic promotion | 安全な更新は実装済み。per-file incrementality と managed trigger は未実装 |
| ローカル LLM | 既存 Ollama の検出、同意済み user-selected enrichment、inferred sidecars | オプションの enrichment は実装済み。installation は意図的に未提供 |
| 可視化 | relationship lens と current/previous comparison を備える自己完結型 Cytoscape/ELK workbench | 大部分を実装済み |
| プロジェクト拡張 evidence | 公開 Skills-only から除外。完全版／ローカルだけに、1 つの downstream lab 統合向けの静的 `PolicyLeaf -> RuntimeBranch` と作成専用 mode-`0400` binding receipt | core 自動化ではなく、限定的な互換性 extension |
| 改善 | candidate、approval、policy-write、deployment、order、funds の権限なし | 別の controller が必要 |

公開 Skills-only パッケージには、汎用の CLI、analyzer、workbench、references、オプションの local-LLM
helper が含まれます。AETHER Lab の runtime-binding 実装、プロジェクト固有のポリシースキーマ、
レシート生成機能、専用評価ケース、関連する機能宣言は含まれません。公開 portal profile と
ローカル stdio transport は異なる配布モデルであるため、同梱 MCP server も意図的に除外されています。
完全版／ローカルパッケージには MCP と、別途管理される downstream extension が含まれますが、
OpenAI がホストする提出物ではありません。

## 6. バージョンロードマップ

このロードマップは方向性を示すものであり、日付を約束するものではありません。
各リリースは、次の段階を必要とせず、それ自体で有用かつ安全であり続けます。

### 0.3.3: 多言語ドキュメントとリリース継続性

- 全体アーキテクチャとバージョンロードマップを公開する。
- 英語、韓国語、日本語、簡体字中国語のドキュメント入口を提供する。
- 正規の法務およびポリシー原文として英語を維持する。
- ドキュメントの同等性検査を追加し、決定論的パッケージングを維持する。

### 0.3.4: 公開プロファイルの分離

- 公開 Skills-only／OpenAI 提出プロファイルを汎用コードオントロジーワークフローに限定する。
- AETHER Lab の runtime-binding 実装、プロジェクト固有のポリシースキーマ、レシート生成機能、
  専用評価ケース、関連する機能宣言を公開アーカイブから決定論的に除外する。
- downstream extension を GitHub の完全版／ローカルプロファイルにだけ残し、OpenAI がホストする
  提出物ではないこと、および runtime／policy／order／funds の権限がないことを明示する。
- プロファイル境界が破られた場合にフェイルクローズするリリース検証を維持する。

### 0.4.x: ユーザビリティと言語アナライザーアダプター

- 明示的で範囲を限定した language-adapter contract を抽出する。
- setup diagnostics、progress reporting、対処可能な failure を改善する。
- foreground watcher の制御、debouncing、single-flight behavior を改善する。
- static confidence と未対応 runtime を示す表示を明確にする。
- 依存関係ゼロの既定値を維持する。

### 0.5.x: オプションのストレージおよび照会拡張

- RDF 1.1 import/export を中心に graph-store adapter contract を定義する。
- いずれか 1 製品を必須にせず、ユーザーが選択した Jena、RDF4J、GraphDB、Stardog、
  または互換ストアをサポートする。
- オプションの SPARQL と localhost REST management profile を追加する。
- 大規模グラフの可視化と複数スナップショット比較を改善する。
- file snapshot store を引き続き完全にサポートする。

### 0.6.x: ローカル AI データパイプライン運用

- 明示的な Git、CI、managed-local refresh trigger adapter を追加する。
- 言語を考慮したファイル単位の増分 invalidation を実装する。
- build metadata、dependency、effective configuration、認証済み read-only runtime evidence
  の各 adapter を追加する。
- durable な pipeline health、recovery、lineage receipt を追加する。
- local-first の推奨を行う、同意ベースの host setup assistant を提供する。

### 0.7.x: 統制された改善との統合

- 外部 experiment controller 向けの安定した evidence contract を定義する。
- ontology identity を hypothesis、candidate、replay、OOS、cost、natural-shadow receipt に
  結び付ける。
- 別途許可された adapter による issue または draft-PR の準備をサポートする。
- code merge、deployment、policy mutation、runtime actuation は Companion の権限外に保つ。

### 0.8.x-0.9.x: 本番向け堅牢化

- クロスプラットフォームの lock、path safety、service lifecycle adapter を検証する。
- signed evidence と expiry contract を追加する。
- 外部 controller と連携した CAS、canary、rollback、mixed-state recovery を検証する。
- 大規模リポジトリと graph store をベンチマークする。
- migration と backward-compatibility tooling を完成させる。

### 1.0: 完成製品の基準

以下が独立して検証された場合に限り、バージョン 1.0 を宣言します。

1. language adapter、build/config input、認証済み runtime evidence が 1 つの正規の
   ontology identity を共有する。
2. file storage と少なくとも 1 つのオプションの標準 RDF store が、portable semantics または lineage を
   失わずに round-trip できる。
3. foreground、Git/CI、承認済み managed-local refresh path が、信頼でき、observable、
   idempotent、recoverable である。
4. MCP、SPARQL/REST profile、natural-language orchestration、visualization が、同じ read／evidence
   boundary を維持する。
5. 既存 local model を検出して安全に enrichment でき、オプションの installation は明示的で
   license-aware のままである。
6. external improvement controller が認証済み evidence を利用し、必要な validation、CAS、
   canary、rollback gate のすべてを証明できる。
7. installation と upgrade が user data、rollback lineage、privacy、portability、実用的な
   zero-dependency mode を維持する。
8. 製品ドキュメントと主要ワークフローが、英語、韓国語、日本語、簡体字中国語で維持される。

## 7. 互換性と移行

- 安定した `co:` namespace と RDF 1.1 export が migration contract です。
- 新しい storage adapter は、独自の source of truth を作るのではなく、既存 Turtle を
  インポートしなければなりません。
- snapshot と provenance identifier はイミュータブルです。adapter は index を作成できますが、
  それらを書き換えることはできません。
- analyzer、Companion、schema、canonicalizer、inference の各 version は receipt に
  明示され続けます。
- 新しい analyzer が refresh を必要とする場合でも、古い snapshot は読み取り可能なままです。
- store 固有機能には portable fallback が必要です。ない場合は non-portable extension と
  明確に表示しなければなりません。

## 8. 恒久的な安全性とプライバシーの境界

本プロジェクトは、コードへのアクセスを、対象コードの実行、秘密情報の読み取り、
リポジトリのアップロード、policy の変更、software の deploy、注文の送信、資金移動の
許可とは決してみなしません。決定論的解析は機密および生成済み path を除外し、portable artifact
は絶対パスと非公開 fingerprint を省略し、オプションの LLM data は範囲を限定して別に分類します。

自動改善は、ontology plugin 内部の capability switch ではなく、独立して検証される
component の組み合わせです。自動化を容易にするという理由だけで、この分離を弱める
roadmap milestone があってはなりません。

## 9. 公開戦略

バージョン 0.3.2 を最初の安定した機能基準として、0.3.3 を多言語ドキュメント基準として維持します。
現在のバージョン 0.3.4 は、公開 Skills-only／OpenAI 提出プロファイルと、GitHub の
完全版／ローカル downstream extension を明確に分離します。その後は互換性のある
patch／minor release を通じて発展させます。
実際のユーザーフィードバックを集める前に、目標アーキテクチャ全体の完成を待つ必要はありません。
現在の製品を graph database、live runtime tracer、autonomous refactoring system、deployment agent、
profitability engine として宣伝してはなりません。

想定する製品説明は次のとおりです。

> 許可された Java/Spring および Python リポジトリについて、プライバシーに配慮した
> ローカルコード知識グラフを構築・維持し、ポータブルな RDF リネージ、静的な影響探索、
> バージョン比較、オフライン可視化を提供します。
