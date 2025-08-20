
# PDF→JSONL 変換・**ポータブル配布**テンプレート（Windows）

受け取り側は **インストール不要**。ZIPを展開して `windows\run_ocr_portable.bat` を実行するだけで動かせます。

---

## 配布側が用意するもの（このテンプレートに追加）

```
bundle/
├─ pdf2jsonl-ocr.exe             ← PyInstaller で作成（one-folder/onedir を推奨）
├─ Tesseract-OCR/                ← フォルダまるごと同梱（tesseract.exe / tessdata/）
├─ pdf_to_jsonl_ocr_v4.py        ← EXEではなくスクリプトで配布する場合のみ（任意）
├─ README_portable.md            ← 本ファイル
└─ windows/
   ├─ run_ocr_portable.bat       ← 実行用（引数なしで対話も可）
   └─ _set_tesseract_portable.bat← 同梱Tesseractを自動で使うための設定
```

- **Tesseract-OCR** は「`C:\Program Files\Tesseract-OCR` を丸ごとコピー」または CI で取得（Chocolatey等）
- **pdf2jsonl-ocr.exe** は PyInstaller でビルド（下の GitHub Actions 例を利用可）

---

## 使い方（受け取り側・ユーザー）

1. ZIP を任意の場所に展開（フォルダ名は自由）
2. `windows\run_ocr_portable.bat` を **ダブルクリック**
   - 引数が無ければ **対話モード**（PDFパスと出力フォルダを入力）
   - 既にパスが分かっていれば、コマンドで：
     ```
     windows\run_ocr_portable.bat "C:\data\input.pdf" "C:\data\out"
     ```
3. 完了後、`<out>` に JSONL / 画像 / 表 / OCR / ZIP / 診断レポートが生成されます。

---

## よくある質問

- **Python のインストールは必要？** → 不要です。`pdf2jsonl-ocr.exe` に同梱済みです。
- **Tesseract のインストールは必要？** → 不要です。同梱の `Tesseract-OCR/` を自動で使います。
- **日本語OCRは？** → 同梱の `Tesseract-OCR\tessdata` に `jpn.traineddata` が入っていればOK。

---

## （任意）GitHub Actions でポータブルZIPを自動生成

`.github/workflows/build_portable.yml` を使うと、Windows上で EXE をビルドし、
`Tesseract-OCR` を同梱した **ポータブルZIP** をアーティファクトとして取得できます。
詳細はファイル内のコメントを参照してください。
