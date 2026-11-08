<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/wordmark-dark.svg">
  <img src="docs/assets/wordmark-light.svg" alt="Shizuku" width="320">
</picture>

**英語も日本語も、モードを切り替えずに打てる macOS の日本語入力。**

かな漢字変換はすべて Rust で書かれ、手元の Mac の中だけで動きます。打った文字は外に送りません。

<table>
  <tr>
    <td align="center" valign="top" width="33%">
      <img src="docs/assets/tile-convert.svg" width="200" alt="あしたははれです が Space で 明日は晴れです になり、Enter で確定する"><br>
      <b>変換</b><br>
      <sub>Space で変換、Enter で確定。</sub>
    </td>
    <td align="center" valign="top" width="33%">
      <img src="docs/assets/tile-english.svg" width="200" alt="ぎ が git になり、Space を挟んで git merge と打てる"><br>
      <b>英語はそのまま</b><br>
      <sub>英単語は英字で。Space は空白。</sub>
    </td>
    <td align="center" valign="top" width="33%">
      <img src="docs/assets/tile-mixed.svg" width="200" alt="artifact のあとの wo が を になり、artifactを使う に変換される"><br>
      <b>英語まじり</b><br>
      <sub>artifactを使う も、続けて打てる。</sub>
    </td>
  </tr>
</table>

- **変換** — Space で変換、Enter で確定。ローマ字の表は Mozc と同じ。
- **英語** — かなにならない英単語は英字のまま。一度英語で確定した語は、次から英字で出る。
- **候補** — カタカナ語の英単語 (デスクトップ → desktop) と絵文字 (ねこ → 🐈) も出る。
- **記憶** — 英語で確定した語を覚える。パスワード欄とパスワード管理アプリでは覚えない。
- **並べ替え** — 小さな日本語言語モデルを Mac の中で動かし、文全体の候補を自然な順にする。
- **ライブ変換 (任意)** — 打ちながら変換する。入力メニューで切り替える。

## インストール

macOS 26 以降、Apple Silicon のみ。

1. [Shizuku.pkg](https://github.com/n-seiji/shizuku-ime/releases/latest/download/Shizuku.pkg) を開く。
2. システム設定 > キーボード > 入力ソース で Shizuku を追加する。一覧に出ないときはログインし直す。

**更新:** 新しい `.pkg` を開くだけ。先に古いアプリを削除すると、入力ソースから外れて追加し直しになる。0.6.0 までの `.pkg` で更新して打てなくなったときも、追加し直す。

**アンインストール:**

1. 入力ソースから Shizuku を外す。
2. `~/Library/Input Methods/Shizuku.app` を削除する。
3. `pkgutil --forget dev.n-seiji.inputmethod.Shizuku.pkg --volume ~` を実行する。
4. 記憶と設定も消すなら、`~/Library/Application Support/Shizuku`、`~/Library/Logs/Shizuku`、`~/Library/Preferences/dev.n-seiji.inputmethod.Shizuku.plist` を削除する。

**ソースからビルド:** [mise](https://mise.jdx.dev/) と Rust が必要。`judge-model` は並べ替え用のモデル (約 41 MB) を取得する。省くと変換エンジン本来の順で動く。

```sh
mise run judge-model
mise run install
```

## キー

| キー | 動作 |
|---|---|
| Space | 変換 / 次の候補。英語の途中では空白 |
| Shift+Space | 前の候補。英語の途中では変換 |
| ↑ ↓ | 候補を移動 |
| 1〜9 | 候補を選んで確定 |
| Enter | 表示しているとおりに確定 |
| Esc / Backspace | 変換を取り消す |
| Ctrl+J / K / L / ; / : | ひらがな / カタカナ / 全角英数 / 半角英数 / 半角カナ |
| F6〜F10 | 同上 |

## プライバシー

実行時にネットワークを使わない。CI が `scripts/check-no-network.sh` で確かめている。記憶データは `~/Library/Application Support/Shizuku/rust-learning/` にだけ保存する。

## クレジット・ライセンス

GPL-3.0-or-later ([`LICENSE`](LICENSE))。

- 変換エンジン: [AzooKeyKanaKanjiConverter](https://github.com/azooKey/AzooKeyKanaKanjiConverter) の Rust 移植
- 辞書: [azooKey_dictionary_storage](https://github.com/ensan-hcl/azooKey_dictionary_storage)
- ローマ字の表: [Mozc](https://github.com/google/mozc)
- カタカナ語の英単語: [JMdict](https://www.edrdg.org/)
- 絵文字: Unicode / CLDR ([azooKey_emoji_dictionary_storage](https://github.com/ensan-hcl/azooKey_emoji_dictionary_storage) 経由)
- 並べ替えモデル: [rinna/japanese-gpt2-xsmall](https://huggingface.co/rinna/japanese-gpt2-xsmall) (リポジトリには含まない)
- ロゴの文字: [Quicksand](https://github.com/andrew-paglinawan/QuicksandFamily)

各ライセンスは [`NOTICE`](NOTICE)、[`dictionary/NOTICE`](dictionary/NOTICE)、[`THIRD_PARTY_LICENSES`](THIRD_PARTY_LICENSES) に記載。
