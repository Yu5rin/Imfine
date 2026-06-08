from PIL import Image, ImageDraw


def _draw_available(size: int) -> Image.Image:
    S = 4
    w = size * S
    img = Image.new('RGBA', (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = max(2, int(w * 0.03))
    d.ellipse([pad, pad, w - pad - 1, w - pad - 1],
              fill='#6ABF69', outline='#43A047', width=max(2, int(w * 0.04)))

    lw = max(3, int(w * 0.09))
    p0 = (int(w * 0.24), int(w * 0.52))
    p1 = (int(w * 0.43), int(w * 0.69))
    p2 = (int(w * 0.74), int(w * 0.31))
    d.line([p0, p1], fill='white', width=lw)
    d.line([p1, p2], fill='white', width=lw)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 32, 48, 256]
    imgs = [_draw_available(s) for s in sizes]
    imgs[0].save(
        'icon.ico',
        format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=imgs[1:],
    )
    _draw_available(256).save('icon.png')
    print('Generated icon.ico and icon.png')


if __name__ == '__main__':
    main()
