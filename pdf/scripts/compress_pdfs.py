#!/usr/bin/env python3

from __future__ import annotations

import argparse
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from PIL import Image
from pikepdf import Name, ObjectStreamMode, Pdf, PdfImage


@dataclass(frozen=True)
class Profile:
    jpeg_quality: int
    max_dimension: int | None
    min_image_bytes: int
    recompress_jpeg: bool


PROFILES = {
    "conservative": Profile(
        jpeg_quality=85,
        max_dimension=None,
        min_image_bytes=350_000,
        recompress_jpeg=False,
    ),
    "balanced": Profile(
        jpeg_quality=72,
        max_dimension=2200,
        min_image_bytes=175_000,
        recompress_jpeg=False,
    ),
    "aggressive": Profile(
        jpeg_quality=55,
        max_dimension=1600,
        min_image_bytes=100_000,
        recompress_jpeg=True,
    ),
}

MIN_ABSOLUTE_SAVINGS = 32 * 1024
MIN_RELATIVE_SAVINGS = 0.002


class CompressionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compress PDFs recursively with safe temp-file replacement."
    )
    parser.add_argument("target", help="Directory or PDF file to process")
    parser.add_argument(
        "--profile",
        default="balanced",
        choices=sorted(PROFILES),
        help="Compression profile to use",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate impact without writing files",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="Write output beside the source using the given suffix instead of overwriting",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Mirror output under a separate root instead of overwriting",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only process PDFs directly under the target directory",
    )
    return parser.parse_args()


def gather_pdfs(target: Path, recursive: bool) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() != ".pdf":
            raise CompressionError(f"Target file is not a PDF: {target}")
        return [target]

    if not target.exists():
        raise CompressionError(f"Target does not exist: {target}")
    if not target.is_dir():
        raise CompressionError(f"Target is neither a file nor a directory: {target}")

    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(
        path for path in target.glob(pattern) if path.is_file() and path.suffix.lower() == ".pdf"
    )


def destination_for(source: Path, target_root: Path, suffix: str, output_root: Path | None) -> Path:
    if output_root is not None:
        return output_root / source.relative_to(target_root)
    if suffix:
        return source.with_name(f"{source.stem}{suffix}{source.suffix}")
    return source


def image_should_be_recompressed(filters: list[str], profile: Profile) -> bool:
    if filters == ["/FlateDecode"]:
        return True
    if profile.recompress_jpeg and filters == ["/DCTDecode"]:
        return True
    return False


def resize_if_needed(image: Image.Image, max_dimension: int | None) -> Image.Image:
    if max_dimension is None:
        return image
    width, height = image.size
    if max(width, height) <= max_dimension:
        return image

    scale = max_dimension / max(width, height)
    resized = image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.LANCZOS,
    )
    return resized


def maybe_recompress_images(pdf: Pdf, profile: Profile) -> int:
    rewritten = 0
    seen: set[tuple[int, int]] = set()

    for page in pdf.pages:
        for _, image_obj in page.images.items():
            key = tuple(image_obj.objgen)
            if key in seen:
                continue
            seen.add(key)

            pdf_image = PdfImage(image_obj)
            filters = [str(item) for item in pdf_image.filters]
            raw_bytes = image_obj.read_raw_bytes()

            if len(raw_bytes) < profile.min_image_bytes:
                continue
            if pdf_image.image_mask or pdf_image.indexed or pdf_image.bits_per_component != 8:
                continue
            if pdf_image.mode not in {"L", "RGB"}:
                continue
            if not image_should_be_recompressed(filters, profile):
                continue

            try:
                pil_image = pdf_image.as_pil_image()
            except Exception:
                continue

            if pil_image.mode not in {"L", "RGB"}:
                pil_image = pil_image.convert("RGB")

            pil_image = resize_if_needed(pil_image, profile.max_dimension)
            output = io.BytesIO()
            pil_image.save(
                output,
                format="JPEG",
                quality=profile.jpeg_quality,
                optimize=True,
            )
            jpeg_bytes = output.getvalue()
            if len(jpeg_bytes) >= len(raw_bytes):
                continue

            image_obj.write(jpeg_bytes, filter=Name("/DCTDecode"), decode_parms=None)
            rewritten += 1

    return rewritten


def save_candidate(source: Path, temp_path: Path, profile: Profile) -> tuple[int, int, int]:
    pdf = Pdf.open(source)
    rewritten_images = maybe_recompress_images(pdf, profile)
    pdf.save(
        temp_path,
        compress_streams=True,
        object_stream_mode=ObjectStreamMode.generate,
        recompress_flate=True,
        linearize=False,
    )
    Pdf.open(temp_path).close()
    return source.stat().st_size, temp_path.stat().st_size, rewritten_images


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def has_meaningful_savings(original_size: int, candidate_size: int) -> bool:
    savings = original_size - candidate_size
    if savings <= 0:
        return False
    return savings >= MIN_ABSOLUTE_SAVINGS or (savings / original_size) >= MIN_RELATIVE_SAVINGS


def compress_one(
    source: Path,
    target_root: Path,
    profile: Profile,
    dry_run: bool,
    suffix: str,
    output_root: Path | None,
) -> tuple[str, int, int]:
    destination = destination_for(source, target_root, suffix, output_root)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix=f"{source.stem[:20]}-",
        suffix=".tmp.pdf",
        dir=destination.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    try:
        original_size, candidate_size, rewritten_images = save_candidate(source, temp_path, profile)
        savings = original_size - candidate_size

        if not has_meaningful_savings(original_size, candidate_size):
            return (
                f"SKIP  {source} -> below threshold "
                f"({format_bytes(original_size)} -> {format_bytes(candidate_size)})",
                0,
                0,
            )

        if dry_run:
            return (
                f"DRY   {source} -> would save {format_bytes(savings)} "
                f"({format_bytes(original_size)} -> {format_bytes(candidate_size)}, images={rewritten_images})",
                original_size,
                candidate_size,
            )

        if destination == source:
            os.replace(temp_path, source)
        else:
            os.replace(temp_path, destination)

        return (
            f"OK    {source} -> saved {format_bytes(savings)} "
            f"({format_bytes(original_size)} -> {format_bytes(candidate_size)}, images={rewritten_images})",
            original_size,
            candidate_size,
        )
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    args = parse_args()
    target = Path(args.target).resolve()
    output_root = args.output_root.resolve() if args.output_root else None
    profile = PROFILES[args.profile]

    try:
        pdfs = gather_pdfs(target, recursive=not args.no_recursive)
    except CompressionError as exc:
        print(f"ERROR {exc}")
        return 1

    if not pdfs:
        print(f"No PDFs found under {target}")
        return 0

    processed = 0
    replaced = 0
    skipped = 0
    failed = 0
    total_before = 0
    total_after = 0

    for pdf_path in pdfs:
        processed += 1
        try:
            message, before, after = compress_one(
                pdf_path,
                target if target.is_dir() else target.parent,
                profile,
                args.dry_run,
                args.suffix,
                output_root,
            )
            print(message)
            if before and after:
                total_before += before
                total_after += after
                replaced += 1
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            print(f"FAIL  {pdf_path} -> {exc}")

    total_saved = total_before - total_after
    action = "would replace" if args.dry_run else "replaced"
    print(
        "SUMMARY "
        f"processed={processed} {action}={replaced} skipped={skipped} failed={failed} "
        f"saved={format_bytes(total_saved)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
