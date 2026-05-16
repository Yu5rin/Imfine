from PIL import Image, ImageDraw


def _draw_mouse(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    outline = max(2, int(s * 0.04))
    ml, mr = int(s * 0.22), int(s * 0.78)
    mt, mb = int(s * 0.10), int(s * 0.88)
    radius = int(s * 0.20)

    # Mouse body
    d.rounded_rectangle([ml, mt, mr, mb], radius=radius, fill='white',
                         outline='#1A1A2E', width=outline)

    # Horizontal split line (top button area / bottom grip)
    split_y = int(s * 0.42)
    d.line([(ml + outline, split_y), (mr - outline, split_y)],
           fill='#1A1A2E', width=outline)

    # Vertical split line between left/right button (top area only)
    cx = s // 2
    d.line([(cx, mt + outline), (cx, split_y)], fill='#1A1A2E', width=outline)

    # Scroll wheel (red, centered in top area)
    ww = max(3, int(s * 0.07))
    wh = max(5, int(s * 0.12))
    wy = int(s * 0.22)
    d.rounded_rectangle(
        [cx - ww, wy, cx + ww, wy + wh * 2],
        radius=max(2, int(s * 0.03)),
        fill='#E94560',
    )

    # Cable nub at bottom
    nub_w = max(3, int(s * 0.07))
    nub_h = max(4, int(s * 0.05))
    d.rectangle([cx - nub_w, mb - outline, cx + nub_w, mb + nub_h], fill='#1A1A2E')

    return img


def main() -> None:
    sizes = [16, 32, 48, 256]
    base = _draw_mouse(256)
    icons = [base.resize((s, s), Image.LANCZOS) for s in sizes]
    icons[0].save(
        'icon.ico',
        format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=icons[1:],
    )
    base.save('icon.png')
    print('Generated icon.ico and icon.png')


if __name__ == '__main__':
    main()
