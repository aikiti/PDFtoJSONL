#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF→JSONL 変換（v4：Windows配布向け）
- プリフライト診断（非空白文字数／画像被覆率）
- OCR 自動切替（auto/force/off）＋ OSD回転（--ocr-rotate auto）
- Tesseract 検出を強化（環境変数/Windows/mac の既定パス）
- 画像・表の抽出、JSONL＋ZIP 化

依存: pymupdf, pdfplumber, pytesseract, Pillow
"""

from __future__ import annotations
import argparse
import os
import io
import json
import zipfile
import csv
import re
from typing import Dict, List, Tuple, Optional, Any

import fitz  # PyMuPDF
import pdfplumber

# OCR 依存
try:
    import pytesseract
    from PIL import Image
except Exception:
    pytesseract = None
    Image = None

# 既定値
IMAGE_ZOOM = 4.0
DEFAULT_OCR_MODE = "auto"   # auto|force|off
DEFAULT_OCR_LANG = "jpn+eng"
DEFAULT_OCR_DPI = 300
DEFAULT_CSV_ENCODING = "utf-8-sig"
DEFAULT_OCR_ROTATE = "auto"  # auto|none
DEFAULT_OCR_PSM = 6
DEFAULT_OCR_OEM = 1
DEFAULT_TH_NONWS = 20
DEFAULT_TH_COVERAGE = 0.7


class PDFToJSONLConverterOCRv4:
    def __init__(self, output_dir: str, *,
                 ocr_mode: str = DEFAULT_OCR_MODE,
                 ocr_lang: str = DEFAULT_OCR_LANG,
                 ocr_dpi: int = DEFAULT_OCR_DPI,
                 ocr_rotate: str = DEFAULT_OCR_ROTATE,
                 ocr_psm: int = DEFAULT_OCR_PSM,
                 ocr_oem: int = DEFAULT_OCR_OEM,
                 th_nonws: int = DEFAULT_TH_NONWS,
                 th_coverage: float = DEFAULT_TH_COVERAGE,
                 csv_encoding: str = DEFAULT_CSV_ENCODING,
                 tesseract_cmd: Optional[str] = None,
                 preflight_report: Optional[str] = None,
                 password: Optional[str] = None):
        self.output_dir = output_dir
        self.image_dir = os.path.join(output_dir, 'images')
        self.table_dir = os.path.join(output_dir, 'tables')
        self.ocr_dir = os.path.join(output_dir, 'ocr')
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.image_dir, exist_ok=True)
        os.makedirs(self.table_dir, exist_ok=True)
        os.makedirs(self.ocr_dir, exist_ok=True)

        self.ocr_mode = ocr_mode
        self.ocr_lang = ocr_lang
        self.ocr_dpi = max(72, int(ocr_dpi))
        self.ocr_rotate = ocr_rotate
        self.ocr_psm = int(ocr_psm)
        self.ocr_oem = int(ocr_oem)
        self.th_nonws = int(th_nonws)
        self.th_coverage = float(th_coverage)
        self.csv_encoding = csv_encoding
        self.preflight_report = preflight_report
        self.password = password

        self._configure_tesseract(tesseract_cmd)

    # -------------------- Tesseract path detection --------------------
    def _configure_tesseract(self, tesseract_cmd: Optional[str]):
        if pytesseract is None:
            return

        # 1) env var highest priority
        env_cmd = os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_EXE")
        candidates: List[str] = []
        if env_cmd:
            candidates.append(env_cmd)
        if tesseract_cmd:
            candidates.append(tesseract_cmd)

        # 2) Windows common paths
        candidates += [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        # 3) mac / Linux common paths
        candidates += [
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/usr/bin/tesseract",
        ]

        for c in candidates:
            if c and os.path.exists(c):
                pytesseract.pytesseract.tesseract_cmd = c
                # If tessdata is alongside the executable, set TESSDATA_PREFIX
                tdir = os.path.dirname(c)
                tessdata = os.path.join(tdir, "tessdata")
                if os.path.isdir(tessdata) and not os.environ.get("TESSDATA_PREFIX"):
                    os.environ["TESSDATA_PREFIX"] = tdir
                break
        # else: rely on PATH. If not found, ocr_page() will report error.

    # -------------------- Open (with password) --------------------
    def open_document(self, pdf_path: str) -> fitz.Document:
        doc = fitz.open(pdf_path)
        needs_pass_attr = getattr(doc, "needs_pass", 0)
        try:
            locked = bool(needs_pass_attr()) if callable(needs_pass_attr) else bool(needs_pass_attr)
        except TypeError:
            locked = bool(needs_pass_attr)
        if locked:
            if not self.password or not doc.authenticate(self.password):
                raise RuntimeError("PDF が暗号化されています。--password で正しいパスワードを指定してください。")
        return doc

    # -------------------- Preflight diagnostics --------------------
    def preflight(self, doc: fitz.Document) -> Dict[str, Any]:
        needs_pass_attr = getattr(doc, "needs_pass", 0)
        try:
            locked = bool(needs_pass_attr()) if callable(needs_pass_attr) else bool(needs_pass_attr)
        except TypeError:
            locked = bool(needs_pass_attr)
        info: Dict[str, Any] = {
            "encrypted": bool(getattr(doc, "is_encrypted", False)),
            "needs_pass": locked,
            "permissions": int(getattr(doc, "permissions", 0)),
            "pages": []
        }
        for i, page in enumerate(doc, start=1):
            raw = page.get_text("rawdict")
            blocks = raw.get("blocks", []) if isinstance(raw, dict) else []
            has_text = any(b.get("type") == 0 for b in blocks)
            text_plain = page.get_text().strip()
            non_ws = sum(1 for ch in text_plain if not ch.isspace())
            # image coverage
            img_area = 0.0
            for b in blocks:
                if b.get("type") == 1:
                    x0, y0, x1, y1 = b.get("bbox", (0, 0, 0, 0))
                    img_area += max(0, (x1 - x0)) * max(0, (y1 - y0))
            page_area = float(page.rect.width * page.rect.height) or 1.0
            coverage = img_area / page_area
            info["pages"].append({
                "page": i,
                "has_text_block": bool(has_text),
                "non_ws_chars": int(non_ws),
                "image_block_coverage": float(round(coverage, 4)),
            })
        return info

    # -------------------- OCR helpers --------------------
    def _page_to_image(self, page: fitz.Page, dpi: int) -> "Optional[Image.Image]":
        if Image is None:
            return None
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        return Image.open(io.BytesIO(png_bytes)).convert("RGB")

    def _auto_rotate(self, img: "Image.Image") -> "Image.Image":
        if pytesseract is None:
            return img
        try:
            osd = pytesseract.image_to_osd(img)
            m = re.search(r"Rotate: (\d+)", osd)
            angle = int(m.group(1)) if m else 0
            return img.rotate(-angle, expand=True) if angle else img
        except Exception:
            return img

    def ocr_page(self, page: fitz.Page, page_num: int) -> Tuple[str, Dict[str, Optional[str]]]:
        meta = {"used": False, "lang": None, "dpi": None, "txt": None, "tsv": None, "hocr": None, "error": None}
        if pytesseract is None or Image is None:
            meta["error"] = "pytesseract_or_pillow_not_available"
            return "", meta
        # Tesseract binary sanity
        cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
        if not shutil_which(cmd) and not os.path.exists(cmd):
            meta["error"] = "tesseract_not_found"
            return "", meta
        try:
            img = self._page_to_image(page, self.ocr_dpi)
            if img is None:
                meta["error"] = "failed_to_render_page_image"
                return "", meta
            if self.ocr_rotate == "auto":
                img = self._auto_rotate(img)
            config = f"--oem {self.ocr_oem} --psm {self.ocr_psm}"
            text = pytesseract.image_to_string(img, lang=self.ocr_lang, config=config)
            tsv_str = pytesseract.image_to_data(img, lang=self.ocr_lang, config=config, output_type=pytesseract.Output.STRING)
            hocr_bytes = pytesseract.image_to_pdf_or_hocr(img, lang=self.ocr_lang, config=config, extension='hocr')

            txt_path = os.path.join(self.ocr_dir, f"page{page_num}.txt")
            tsv_path = os.path.join(self.ocr_dir, f"page{page_num}.tsv")
            hocr_path = os.path.join(self.ocr_dir, f"page{page_num}.hocr")
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(text)
            with open(tsv_path, 'w', encoding='utf-8') as f:
                f.write(tsv_str)
            with open(hocr_path, 'wb') as f:
                f.write(hocr_bytes)

            meta.update({"used": True, "lang": self.ocr_lang, "dpi": self.ocr_dpi,
                         "txt": txt_path, "tsv": tsv_path, "hocr": hocr_path})
            return text.strip(), meta
        except Exception as e:
            meta["error"] = str(e)
            return "", meta

    # -------------------- TEXT --------------------
    def extract_text_by_page(self, doc: fitz.Document) -> List[Dict[str, str]]:
        pages = []
        for i, page in enumerate(doc, start=1):
            pages.append({"page": i, "text": page.get_text().strip()})
        return pages

    # -------------------- IMAGES --------------------
    def extract_images_by_page(self, doc: fitz.Document) -> Dict[int, List[str]]:
        images: Dict[int, List[str]] = {}
        for i, page in enumerate(doc, start=1):
            saved: List[str] = []
            seen_xrefs = set()
            # XObject images
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                data = doc.extract_image(xref)
                ext = data.get("ext", "png")
                name = f"page{i}_img{len(saved)+1}.{ext}"
                path = os.path.join(self.image_dir, name)
                with open(path, "wb") as f:
                    f.write(data["image"])
                saved.append(path)
            # image blocks (clipped, high DPI)
            raw = page.get_text("rawdict")
            fig_count = 0
            if isinstance(raw, dict):
                for block in raw.get("blocks", []):
                    if block.get("type") == 1:
                        fig_count += 1
                        rect = fitz.Rect(block["bbox"])
                        mat = fitz.Matrix(IMAGE_ZOOM, IMAGE_ZOOM)
                        pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
                        name = f"page{i}_fig{fig_count}.png"
                        path = os.path.join(self.image_dir, name)
                        pix.save(path)
                        saved.append(path)
            # vector drawings (bounding box render)
            drawings = page.get_drawings()
            if drawings:
                bbox = None
                for d in drawings:
                    r = fitz.Rect(d["rect"])
                    bbox = r if bbox is None else bbox.include_rect(r)
                if bbox is not None and bbox.get_area() > 0:
                    mat = fitz.Matrix(IMAGE_ZOOM, IMAGE_ZOOM)
                    pix = page.get_pixmap(matrix=mat, clip=bbox, alpha=False)
                    name = f"page{i}_vector.png"
                    path = os.path.join(self.image_dir, name)
                    pix.save(path)
                    saved.append(path)
            images[i] = saved
        return images

    # -------------------- TABLES --------------------
    def extract_and_save_tables(self, pdf_path: str) -> Dict[int, List[str]]:
        tables: Dict[int, List[str]] = {}
        lattice_settings = {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "edge_min_length": 3,
            "intersection_x_tolerance": 5,
            "intersection_y_tolerance": 5,
        }
        stream_settings = {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "text_tolerance": 1,
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_x_tolerance": 5,
            "intersection_y_tolerance": 5,
        }
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                saved_paths: List[str] = []
                for settings in (lattice_settings, stream_settings):
                    try:
                        page_tables = page.extract_tables(table_settings=settings)
                    except Exception:
                        page_tables = []
                    for table in page_tables:
                        cleaned_rows: List[List[str]] = []
                        for row in table:
                            cleaned = [(cell if cell is not None else "") for cell in row]
                            if any((c.strip() if isinstance(c, str) else str(c)) for c in cleaned):
                                cleaned_rows.append(cleaned)
                        if not cleaned_rows:
                            continue
                        table_file = os.path.join(self.table_dir, f"page{i}_table{len(saved_paths)+1}.csv")
                        with open(table_file, 'w', newline='', encoding=self.csv_encoding) as csvfile:
                            writer = csv.writer(csvfile)
                            writer.writerows(cleaned_rows)
                        saved_paths.append(table_file)
                tables[i] = saved_paths
        return tables

    # -------------------- PACKAGE --------------------
    def package_and_save(self, records: List[Dict], base_name: str):
        jsonl_file = os.path.join(self.output_dir, f"{base_name}.jsonl")
        with open(jsonl_file, 'w', encoding='utf-8') as jf:
            for rec in records:
                jf.write(json.dumps(rec, ensure_ascii=False) + '\n')

        zip_file = os.path.join(self.output_dir, f"{base_name}_export.zip")
        with zipfile.ZipFile(zip_file, 'w') as zf:
            zf.write(jsonl_file, os.path.basename(jsonl_file))
            for root, _, files in os.walk(self.image_dir):
                for f in files:
                    file_path = os.path.join(root, f)
                    zf.write(file_path, os.path.join('images', f))
            for root, _, files in os.walk(self.table_dir):
                for f in files:
                    file_path = os.path.join(root, f)
                    zf.write(file_path, os.path.join('tables', f))
            if os.path.isdir(self.ocr_dir):
                for root, _, files in os.walk(self.ocr_dir):
                    for f in files:
                        file_path = os.path.join(root, f)
                        zf.write(file_path, os.path.join('ocr', f))
        return jsonl_file, zip_file

    # -------------------- MAIN --------------------
    def convert_pdf(self, pdf_path: str):
        doc = self.open_document(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]

        diag = self.preflight(doc)
        if self.preflight_report:
            report_path = self.preflight_report if os.path.isabs(self.preflight_report) else os.path.join(self.output_dir, self.preflight_report)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(diag, f, ensure_ascii=False, indent=2)

        images = self.extract_images_by_page(doc)
        tables = self.extract_and_save_tables(pdf_path)

        records: List[Dict] = []
        for i, page in enumerate(doc, start=1):
            text_pymupdf = page.get_text().strip()
            non_ws = sum(1 for ch in text_pymupdf if not ch.isspace())
            page_diag = diag["pages"][i-1] if diag and "pages" in diag and len(diag["pages"]) >= i else {}
            # OCR trigger
            need_ocr = False
            if self.ocr_mode == 'force':
                need_ocr = True
            elif self.ocr_mode == 'auto':
                has_text_block = bool(page_diag.get("has_text_block", False))
                coverage = float(page_diag.get("image_block_coverage", 0.0))
                if (not has_text_block) or (non_ws < self.th_nonws) or (coverage >= self.th_coverage):
                    need_ocr = True

            ocr_used = False
            ocr_meta: Dict[str, Optional[str]] = {"used": False}
            text_final = text_pymupdf

            if need_ocr:
                ocr_text, meta = self.ocr_page(page, i)
                if meta.get('used') and ocr_text:
                    text_final = ocr_text
                    ocr_used = True
                ocr_meta = meta

            record = {
                'page': i,
                'text': text_final,
                'images': images.get(i, []),
                'tables': tables.get(i, []),
                'diagnostics': page_diag,
                'ocr': {
                    'used': bool(ocr_used),
                    'mode': self.ocr_mode,
                    'lang': self.ocr_lang if ocr_used else None,
                    'dpi': self.ocr_dpi if ocr_used else None,
                    'psm': self.ocr_psm if ocr_used else None,
                    'oem': self.ocr_oem if ocr_used else None,
                    'rotate': self.ocr_rotate if ocr_used else None,
                    'artifacts': {
                        'txt': ocr_meta.get('txt'),
                        'tsv': ocr_meta.get('tsv'),
                        'hocr': ocr_meta.get('hocr'),
                        'error': ocr_meta.get('error')
                    }
                }
            }
            records.append(record)

        doc.close()
        return self.package_and_save(records, base_name)


def shutil_which(cmd: str) -> Optional[str]:
    """shutil.which の簡易版（Windows パス含む存在チェック用）"""
    import shutil
    return shutil.which(cmd)


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to JSONL with Preflight + OCR (auto/force) + OSD rotation.")
    parser.add_argument('--input', '-i', required=True, help='Path to input PDF')
    parser.add_argument('--output-dir', '-o', required=True, help='Directory to save outputs')
    parser.add_argument('--password', default=None, help='Password for encrypted PDFs')
    # OCR settings
    parser.add_argument('--ocr', choices=['auto', 'force', 'off'], default=DEFAULT_OCR_MODE, help='OCR mode')
    parser.add_argument('--ocr-lang', default=DEFAULT_OCR_LANG, help='Tesseract languages (e.g., "eng", "jpn", "jpn+eng")')
    parser.add_argument('--ocr-dpi', type=int, default=DEFAULT_OCR_DPI, help='DPI for OCR page rendering (>=72)')
    parser.add_argument('--ocr-rotate', choices=['auto', 'none'], default=DEFAULT_OCR_ROTATE, help='Auto rotate page image by OSD before OCR')
    parser.add_argument('--ocr-psm', type=int, default=DEFAULT_OCR_PSM, help='Tesseract PSM (e.g., 4/6/11/12)')
    parser.add_argument('--ocr-oem', type=int, default=DEFAULT_OCR_OEM, help='Tesseract OEM (0..3, 1=LSTM)')
    # thresholds
    parser.add_argument('--ocr-th-nonws', type=int, default=DEFAULT_TH_NONWS, help='Non-whitespace char threshold to trigger OCR in auto mode')
    parser.add_argument('--ocr-th-coverage', type=float, default=DEFAULT_TH_COVERAGE, help='Image coverage threshold (0..1) to trigger OCR in auto mode')
    # misc
    parser.add_argument('--csv-encoding', default=DEFAULT_CSV_ENCODING, help='Encoding for CSV tables (e.g., utf-8-sig)')
    parser.add_argument('--tesseract-cmd', default=None, help='Path to tesseract binary (if not on PATH)')
    parser.add_argument('--preflight-report', default='preflight_report.json', help='Filename for preflight JSON report (saved under output-dir)')

    args = parser.parse_args()

    # Input checks
    if not os.path.isfile(args.input):
        raise SystemExit(f"[ERROR] Input PDF not found: {args.input}")
    os.makedirs(args.output_dir, exist_ok=True)

    converter = PDFToJSONLConverterOCRv4(
        args.output_dir,
        ocr_mode=args.ocr,
        ocr_lang=args.ocr_lang,
        ocr_dpi=args.ocr_dpi,
        ocr_rotate=args.ocr_rotate,
        ocr_psm=args.ocr_psm,
        ocr_oem=args.ocr_oem,
        th_nonws=args.ocr_th_nonws,
        th_coverage=args.ocr_th_coverage,
        csv_encoding=args.csv_encoding,
        tesseract_cmd=args.tesseract_cmd,
        preflight_report=args.preflight_report,
        password=args.password,
    )

    jsonl_path, zip_path = converter.convert_pdf(args.input)
    print("Done.")
    print(f"JSONL file: {jsonl_path}")
    print(f"ZIP file: {zip_path}")


if __name__ == '__main__':
    main()
