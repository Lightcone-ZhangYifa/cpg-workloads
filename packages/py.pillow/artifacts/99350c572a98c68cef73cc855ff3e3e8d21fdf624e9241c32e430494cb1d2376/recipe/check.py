#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pil, work):
    """Check image pixels, lossless/lossy codecs, transforms and malformed inputs."""
    import io
    Image = installed_module('PIL.Image')
    pixels = [(x*40, y*70, (x+y)*20) for y in range(3) for x in range(4)]
    image = Image.new('RGB', (4, 3)); image.putdata(pixels)
    png = work / 'fixture.png'; image.save(png)
    with Image.open(png) as restored:
        restored.load(); require(restored.mode == 'RGB' and restored.size == (4, 3) and restored.tobytes() == image.tobytes(), 'PNG pixel round trip failed')
    flipped = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    require(flipped.getpixel((0, 1)) == image.getpixel((3, 1)), 'Horizontal flip wrong')
    resized = image.resize((8, 6), resample=Image.Resampling.NEAREST)
    require(resized.getpixel((4, 2)) == image.getpixel((2, 1)), 'Nearest resize wrong')
    grey = Image.new('L', (16,16), 80); jpeg = work / 'fixture.jpg'; grey.save(jpeg, quality=100)
    with Image.open(jpeg) as restored:
        require(restored.size == (16,16) and all(abs(value-80) <= 1 for value in restored.getdata()), 'JPEG flat-field tolerance failed')
    mask = Image.new('L', image.size, 255)
    require(Image.composite(image, Image.new('RGB', image.size), mask).tobytes() == image.tobytes(), 'Alpha-mask composite failed')
    raises(pil.UnidentifiedImageError, lambda: Image.open(io.BytesIO(b'not an image')), 'Invalid image accepted')
    raises(ValueError, lambda: image.crop((3,0,1,2)), 'Invalid crop accepted')
    raises(IndexError, lambda: image.getpixel((100,100)), 'Out-of-bounds pixel accepted')
    return {'checks': ['exact-png-pixels', 'horizontal-flip', 'nearest-resize', 'jpeg-flat-field', 'mask-composite', 'invalid-image', 'invalid-crop', 'pixel-bounds'], 'scope': 'selected PNG/JPEG and RGB/L operations; not every codec or color profile'}

if __name__ == "__main__":
    raise SystemExit(main('pillow', 'PIL', functional))
