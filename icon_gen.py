from PIL import Image, ImageDraw


def _draw_mouse(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    cx = s // 2

    outline = max(2, int(s * 0.045))
    dark = '#333333'

    # Body: 縦長の角丸長方形
    ml, mr = int(s * 0.25), int(s * 0.75)
    mt, mb = int(s * 0.08), int(s * 0.85)
    radius = int(s * 0.22)
    d.rounded_rectangle([ml, mt, mr, mb], radius=radius,
                         fill='white', outline=dark, width=outline)

    # 上下分割線（ボタン部 / グリップ部）
    split_y = int(s * 0.40)
    d.line([(ml + outline, split_y), (mr - outline, split_y)],
           fill=dark, width=outline)

    # 左右分割線（左ボタン / 右ボタン）
    d.line([(cx, mt + outline), (cx, split_y)],
           fill=dark, width=outline)

    # スクロールホイール（赤）
    ww = max(2, int(s * 0.06))
    wh = max(4, int(s * 0.11))
    wy = int(s * 0.20)
    d.rounded_rectangle(
        [cx - ww, wy, cx + ww, wy + wh * 2],
        radius=max(1, int(s * 0.025)),
        fill='#E94560',
    )

    # ケーブル（上部中央から出る）
    cable_w = max(2, int(s * 0.05))
    cable_top = max(0, mt - int(s * 0.10))
    d.rectangle([cx - cable_w, cable_top, cx + cable_w, mt + outline],
                fill=dark)

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
