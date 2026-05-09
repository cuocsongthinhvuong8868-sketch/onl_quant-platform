"""
Generate a visual PDF report by screenshotting Streamlit pages.
Output: reports/ddmmyy_quant_report.pdf
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import re

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


def _slug_from_page_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d+[_\- ]*", "", stem)
    return stem


def discover_page_paths(root_dir: Path) -> list[tuple[str, str]]:
    pages_dir = root_dir / "pages"
    items: list[tuple[str, str]] = [("Home", "/")]
    if not pages_dir.exists():
        return items

    for f in sorted(pages_dir.glob("*.py")):
        slug = _slug_from_page_filename(f.name)
        if not slug:
            continue
        items.append((slug, f"/{slug}"))
    return items


def _make_error_image(path: Path, title: str, message: str):
    img = Image.new("RGB", (1600, 900), color=(28, 28, 30))
    draw = ImageDraw.Draw(img)
    draw.text((60, 80), f"{title}", fill=(255, 120, 120))
    draw.text((60, 140), message[:1200], fill=(220, 220, 220))
    img.save(path)


def _assert_server_up(base_url: str):
    with urlopen(base_url, timeout=5) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"App trả về status {resp.status} tại {base_url}")


def generate_visual_report(base_url: str = "http://localhost:8501", output_dir: Path | None = None) -> Path:
    root = Path(__file__).resolve().parent.parent
    if output_dir is None:
        output_dir = Path.home() / "Desktop"

    _assert_server_up(base_url)

    pages = discover_page_paths(root)

    now = datetime.now()
    output_pdf = output_dir / f"{now.strftime('%d%m%y')}_quant_report.pdf"

    image_paths: list[Path] = []

    with TemporaryDirectory(prefix="quant_report_") as tmpdir:
        tmp = Path(tmpdir)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Dùng độ phân giải cao để hiển thị được nhiều nội dung, tỷ lệ 16:9 chuẩn
            context = browser.new_context(viewport={"width": 2560, "height": 1440})
            page = context.new_page()

            for idx, (name, rel) in enumerate(pages, start=1):
                shot = tmp / f"{idx:02d}_{name}.png"
                url = f"{base_url.rstrip('/')}{rel}"
                # Thêm ?embed=true để Streamlit tự động ẩn sidebar/header từ đầu, 
                # giúp biểu đồ tự render full width không bị cắt margin
                url_with_embed = url + ("&embed=true" if "?" in url else "?embed=true")
                try:
                    page.goto(url_with_embed, wait_until="networkidle", timeout=90000)
                    page.wait_for_timeout(3000)
                    
                    # Chỉnh lại padding để hiển thị rộng nhất có thể
                    page.add_style_tag(content='''
                        .block-container { padding: 1rem !important; max-width: 100% !important; }
                    ''')
                    page.wait_for_timeout(1000)
                    
                    page.screenshot(path=str(shot), full_page=False)
                except Exception as e:
                    _make_error_image(shot, f"{name} ({url})", f"Screenshot failed: {e}")
                image_paths.append(shot)

            context.close()
            browser.close()

        if not image_paths:
            raise RuntimeError("Không có ảnh screenshot nào được tạo.")

        imgs = [Image.open(p).convert("RGB") for p in image_paths]
        first, rest = imgs[0], imgs[1:]
        first.save(output_pdf, save_all=True, append_images=rest)

        for im in imgs:
            im.close()

    return output_pdf


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8501")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    
    out_dir = Path(args.output_dir) if args.output_dir else None
    path = generate_visual_report(base_url=args.base_url, output_dir=out_dir)
    print(path)
