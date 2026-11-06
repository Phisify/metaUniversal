"""HTML template -> 1080x1350 JPEG slides via headless Chromium."""
import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from .images import Photo

TEMPLATES = Path(__file__).resolve().parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def _title_size(text: str) -> int:
    n = len(text)
    return 104 if n <= 12 else 90 if n <= 18 else 76 if n <= 26 else 64


def _sub_size(text: str) -> int:
    return 40 if len(text) <= 55 else 36 if len(text) <= 75 else 32


def _body_size(text: str) -> int:
    words = len(text.split())
    return 46 if words <= 25 else 42 if words <= 34 else 38


def build_pages(draft: dict, photo: Photo | None, brand: dict, source_name: str, story: bool = False) -> list[str]:
    tpl = _env.get_template("carousel.html")
    common = {"brand": brand["name"], "handle": brand["handle"], "accent": brand["accent"]}
    slides = draft["slides"]
    total = len(slides) + 2
    photo_uri = (
        "data:image/jpeg;base64," + base64.b64encode(photo.data).decode() if photo else ""
    )

    pages = [
        tpl.render(
            kind="cover",
            title=draft["cover_title"],
            subtitle=draft["cover_subtitle"],
            title_size=_title_size(draft["cover_title"]),
            sub_size=_sub_size(draft["cover_subtitle"]),
            body_size=40,
            photo_uri=photo_uri,
            credit=photo.credit if photo else "",
            story=story,
            **common,
        )
    ]
    if story:
        return pages
    for i, s in enumerate(slides, start=2):
        pages.append(
            tpl.render(
                kind="text",
                heading=s["heading"],
                body=s["body"],
                body_size=_body_size(s["body"]),
                index=i,
                total=total,
                source_line=f"Source: {source_name}",
                title_size=0,
                sub_size=0,
                **common,
            )
        )
    pages.append(
        tpl.render(
            kind="final",
            body=draft["why_it_matters"],
            body_size=_body_size(draft["why_it_matters"]),
            theme=draft["theme"],
            index=total,
            total=total,
            title_size=0,
            sub_size=0,
            **common,
        )
    )
    return pages


def make_story(cover: Path, out_path: Path) -> Path:
    """1080x1920 Story: the 4:5 cover centred on a blurred, darkened copy of itself."""
    from PIL import Image, ImageEnhance, ImageFilter

    img = Image.open(cover).convert("RGB")
    bg = img.resize((1080, 1350)).resize((1536, 1920)).crop((228, 0, 1308, 1920))
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(40))).enhance(0.55)
    bg.paste(img.resize((1080, 1350)), (0, (1920 - 1350) // 2))
    bg.save(out_path, "JPEG", quality=92)
    return out_path


def render(pages: list[str], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for i, html in enumerate(pages, start=1):
            page.set_content(html, wait_until="networkidle", timeout=30000)
            page.evaluate("document.fonts.ready")
            path = out_dir / f"{i:02d}.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=92, full_page=False)
            paths.append(path)
        browser.close()
    return paths
