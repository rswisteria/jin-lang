# Jin（陣）

## 概要

Jinは、AIエージェントの構成と処理の流れを「魔法陣」で表すビジュアルプログラミング言語です。エージェントへの指示、使うツール、記憶する情報、ほかのエージェントとの連携を、ひとつの図で確認できます。

プログラムは `.jin` ファイル（JSON）に保存します。同じファイルから魔法陣を描画し、Google ADKのエージェントとして実行できます。複数の処理を順番に実行する、並列に進める、繰り返す構成にも対応しています。

ブラウザのエディタでは、魔法陣の要素をクリックして編集できます。記録済みの実行履歴を読み込み、処理の流れを図上で振り返ることもできます。

## 言語の例

<!-- ここにビジュアルプログラミングの画像を追加してください。 -->

サンプルを開いて、魔法陣の構成を試せます。

- [Researcher](examples/researcher/researcher.jin)：ツールや記憶を持ち、別のエージェントを呼び出す構成。
- [Pipeline](examples/pipeline/pipeline.jin)：順次・並列・繰り返しの処理を組み合わせた構成。
- [Showcase](examples/showcase/showcase.jin)：描かれる要素 9 種がすべて出る構成。エディタを一通り触るときに。

## エディタの実行方法

### 1. 必要なツールを用意する

- Python 3.14（このリポジトリの指定バージョン）
- [uv](https://docs.astral.sh/uv/getting-started/installation/)（Pythonの環境管理）
- Node.js 22以上
- [pnpm](https://pnpm.io/installation) 10.15.1（エディタのビルド）

エディタでサンプルを表示・編集するだけなら、AIモデルのAPIキーは不要です。

### 2. 初回のセットアップを行う

リポジトリを取得し、そのディレクトリで依存関係のインストールとエディタのビルドを行います。

```bash
git clone https://github.com/rswisteria/jin-lang.git
cd jin-lang
uv sync --locked
cd apps/editor
pnpm install --frozen-lockfile
pnpm build
cd ../..
```

### 3. サンプルを開く

リポジトリのルートで実行します。

```bash
uv run jin editor examples/pipeline/pipeline.jin
```

ブラウザに魔法陣が表示されます。要素をクリックし、プロパティパネルで値を編集して「保存」を押すと、開いた `.jin` ファイルに反映されます。別のファイルを開くには、コマンドのファイルパスを置き換えてください。

ブラウザが自動で開かない場合は、ターミナルに表示されたURLを開いてください。終了するときは、ターミナルで `Ctrl+C` を押します。次回からは起動コマンドだけで使えます。

CLIの各コマンドやデバッグの使い方、利用上の注意は[詳細ガイド](docs/usage.md)を参照してください。

`jin check --resolve` は任意コードを実行するため、中身を確認した `.jin` ファイルにだけ使ってください。
