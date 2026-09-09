"""Compose a before/after pair into one labelled image for a pull request.

    uv run --no-project --with pillow docs/pr-screenshots/compose.py \\
        before.png after.png pair-1.png [--box x,y,w,h] [--crop-left PX] [--gap PX]

Both frames are scaled to the same height, cropped on the left by the same amount (the
sidebar the reviewer has seen a thousand times), laid side by side with a label above
each, and an optional outline is drawn on the after frame around what the change adds,
in a hue the product's palette does not use. Read the result before uploading it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LABEL_HEIGHT = 44
ANNOTATION = (255, 122, 0)  # orange: not in the palette (Prussian blue, watermelon, gold)
PAPER = (247, 247, 245)
INK = (17, 34, 64)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _box(value: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in value.split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError("--box wants x,y,w,h in pixels of the after frame")
    return parts[0], parts[1], parts[2], parts[3]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument(
        "--box", type=_box, help="outline on the after frame: x,y,w,h in its source pixels"
    )
    parser.add_argument(
        "--crop-left", type=int, default=0, help="pixels to cut from the left of both frames"
    )
    parser.add_argument("--gap", type=int, default=24, help="pixels between the two frames")
    parser.add_argument("--labels", default="Before,After", help="the two labels, comma separated")
    args = parser.parse_args(argv)

    before = Image.open(args.before).convert("RGB")
    after = Image.open(args.after).convert("RGB")
    if args.crop_left:
        before = before.crop((args.crop_left, 0, before.width, before.height))
        after = after.crop((args.crop_left, 0, after.width, after.height))
    if args.box:
        x, y, w, h = args.box
        x -= args.crop_left
        draw = ImageDraw.Draw(after)
        for inset in range(4):
            draw.rectangle((x - inset, y - inset, x + w + inset, y + h + inset), outline=ANNOTATION)

    height = max(before.height, after.height)

    def fit(image: Image.Image) -> Image.Image:
        if image.height == height:
            return image
        return image.resize((round(image.width * height / image.height), height), Image.LANCZOS)

    before, after = fit(before), fit(after)
    width = before.width + args.gap + after.width
    canvas = Image.new("RGB", (width, height + LABEL_HEIGHT), PAPER)
    draw = ImageDraw.Draw(canvas)
    font = _font(20)
    labels = [s.strip() for s in args.labels.split(",")]
    if len(labels) != 2:
        parser.error("--labels wants exactly two labels")
    draw.text((8, 12), labels[0], fill=INK, font=font)
    draw.text((before.width + args.gap + 8, 12), labels[1], fill=INK, font=font)
    canvas.paste(before, (0, LABEL_HEIGHT))
    canvas.paste(after, (before.width + args.gap, LABEL_HEIGHT))
    canvas.save(args.out)
    print(f"{args.out}: {canvas.width}x{canvas.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
