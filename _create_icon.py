"""
صنع أيقونة احترافية لنظام المحاسبة
تصميم عصري: خلفية متدرجة داكنة + رمز ميزانية + حروف ج
"""
import math
from PIL import Image, ImageDraw, ImageFont

SIZE = 512

def make_gradient_bg(draw, size):
    """خلفية دائرية بتدرج من أزرق داكن إلى أزرق ملكي"""
    cx = cy = size // 2
    r  = size // 2
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            if dx*dx + dy*dy <= r*r:
                # تدرج من المركز للحافة
                dist = math.sqrt(dx*dx + dy*dy) / r
                # ألوان: مركز #1a3a6e (أزرق ملكي) → حافة #0a1f3d (كحلي)
                r_c = int(26  + (10  - 26)  * dist)
                g_c = int(58  + (31  - 58)  * dist)
                b_c = int(110 + (61  - 110) * dist)
                draw.point((x, y), fill=(r_c, g_c, b_c, 255))

def draw_coin_stack(draw, cx, cy, size):
    """رسم كومة عملات ذهبية"""
    coin_w = int(size * 0.18)
    coin_h = int(size * 0.055)
    coin_x = cx - coin_w // 2

    colors = [
        ((212, 175, 55), (255, 215, 0)),   # ذهبي
        ((200, 160, 40), (240, 200, 0)),
        ((190, 150, 30), (230, 185, 0)),
    ]
    for i, (dark, light) in enumerate(colors):
        y_pos = cy + i * int(coin_h * 1.3)
        # ظل
        draw.ellipse([coin_x+3, y_pos+3, coin_x+coin_w+3, y_pos+coin_h+3],
                     fill=(0, 0, 0, 80))
        # العملة
        draw.ellipse([coin_x, y_pos, coin_x+coin_w, y_pos+coin_h],
                     fill=dark)
        # لمعة
        draw.ellipse([coin_x+3, y_pos+2, coin_x+coin_w-3, y_pos+coin_h//2],
                     fill=light)

def draw_bar_chart(draw, bx, by, bw, bh):
    """رسم مخطط أعمدة صاعدة"""
    bars = [
        (0.35, (46, 204, 113)),   # أخضر
        (0.55, (52, 152, 219)),   # أزرق
        (0.75, (26, 188, 156)),   # فيروزي
        (1.00, (52, 152, 219)),   # أزرق
    ]
    n     = len(bars)
    gap   = int(bw * 0.08)
    bar_w = (bw - gap * (n + 1)) // n

    for i, (ratio, color) in enumerate(bars):
        x  = bx + gap + i * (bar_w + gap)
        h  = int(bh * ratio)
        y1 = by + bh - h
        y2 = by + bh
        r  = 4  # تقريب الزوايا
        draw.rounded_rectangle([x, y1, x + bar_w, y2], radius=r, fill=color)
        # لمعة علوية
        hl_h = max(4, h // 5)
        draw.rounded_rectangle([x+2, y1+2, x+bar_w-2, y1+hl_h],
                                radius=r, fill=(*[min(255, c+60) for c in color], 180))

def draw_trend_line(draw, bx, by, bw, bh):
    """رسم خط اتجاه تصاعدي فوق الأعمدة"""
    bars = [0.35, 0.55, 0.75, 1.00]
    n     = len(bars)
    gap   = int(bw * 0.08)
    bar_w = (bw - gap * (n + 1)) // n

    points = []
    for i, ratio in enumerate(bars):
        x = bx + gap + i * (bar_w + gap) + bar_w // 2
        y = by + bh - int(bh * ratio) - int(bh * 0.05)
        points.append((x, y))

    # الخط
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i+1]
        for t in range(3):
            draw.line([(x1-t, y1-t), (x2-t, y2-t)], fill=(255, 220, 80, 220), width=3)

    # نقاط
    for x, y in points:
        draw.ellipse([x-5, y-5, x+5, y+5], fill=(255, 220, 80), outline=(255,255,255), width=2)

def draw_card(draw, size):
    """رسم بطاقة بيضاء شفافة (خلفية للمخطط)"""
    pad   = int(size * 0.12)
    card_l = pad
    card_t = int(size * 0.18)
    card_r = size - pad
    card_b = size - int(size * 0.22)
    # ظل
    for s in range(8, 0, -1):
        alpha = int(80 * (1 - s/8))
        draw.rounded_rectangle([card_l+s, card_t+s, card_r+s, card_b+s],
                                radius=20, fill=(0, 0, 0, alpha))
    # البطاقة
    draw.rounded_rectangle([card_l, card_t, card_r, card_b],
                            radius=20, fill=(255, 255, 255, 30))

def draw_bottom_accent(draw, size):
    """شريط تزييني سفلي بدلاً من النص العربي"""
    cx  = size // 2
    cy  = int(size * 0.835)
    # 3 نقاط متصلة كشريط
    stripe_w = int(size * 0.38)
    stripe_h = int(size * 0.022)
    colors = [
        (52,  152, 219, 200),   # أزرق
        (46,  204, 113, 200),   # أخضر
        (255, 215, 0,   200),   # ذهبي
    ]
    total_w  = stripe_w
    seg_w    = total_w // len(colors)
    x_start  = cx - total_w // 2
    for i, col in enumerate(colors):
        x1 = x_start + i * seg_w
        x2 = x1 + seg_w - 3
        r  = stripe_h // 2
        draw.rounded_rectangle([x1, cy, x2, cy + stripe_h], radius=r, fill=col)

def draw_small_coins(draw, size):
    """عملات صغيرة في الزاوية العلوية اليسرى"""
    cx = int(size * 0.22)
    cy = int(size * 0.28)
    coin_r = int(size * 0.065)

    # ظل
    draw.ellipse([cx-coin_r+3, cy-coin_r+3, cx+coin_r+3, cy+coin_r+3],
                 fill=(0, 0, 0, 60))
    # العملة الخارجية
    draw.ellipse([cx-coin_r, cy-coin_r, cx+coin_r, cy+coin_r],
                 fill=(184, 142, 30))
    draw.ellipse([cx-coin_r+3, cy-coin_r+3, cx+coin_r-3, cy+coin_r-3],
                 fill=(212, 175, 55))
    # لمعة
    draw.ellipse([cx-coin_r+6, cy-coin_r+5, cx+coin_r-6, cy-2],
                 fill=(255, 215, 0, 180))
    # رمز $ أو ﷼
    try:
        font_s = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", int(size * 0.09))
        bbox   = draw.textbbox((0,0), "﷼", font=font_s)
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        draw.text((cx - tw//2, cy - th//2 - 2), "﷼", font=font_s,
                  fill=(120, 80, 10, 220))
    except:
        pass

def draw_checkmark_badge(draw, size):
    """شارة صح خضراء في الزاوية السفلية اليمنى"""
    bx = int(size * 0.76)
    by = int(size * 0.68)
    br = int(size * 0.065)
    # دائرة خضراء
    draw.ellipse([bx-br, by-br, bx+br, by+br], fill=(39, 174, 96))
    draw.ellipse([bx-br+2, by-br+2, bx+br-2, by+br-2], fill=(46, 204, 113))
    # ارسم علامة صح يدوياً بالخطوط
    sw = int(br * 0.4)  # عرض الخط
    # نقاط علامة الصح
    p1 = (bx - int(br*0.45), by)
    p2 = (bx - int(br*0.1),  by + int(br*0.38))
    p3 = (bx + int(br*0.5),  by - int(br*0.38))
    draw.line([p1, p2], fill=(255,255,255), width=sw)
    draw.line([p2, p3], fill=(255,255,255), width=sw)

def draw_outer_ring(draw, size):
    """حلقة خارجية ناعمة"""
    pad = 4
    for i in range(4):
        alpha = 60 - i*15
        draw.ellipse([pad+i, pad+i, size-pad-i, size-pad-i],
                     outline=(100, 160, 255, alpha), width=2)

# ──────────────── main ────────────────
img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 1. خلفية دائرية متدرجة
make_gradient_bg(draw, SIZE)

# 2. حلقة خارجية
draw_outer_ring(draw, SIZE)

# 3. بطاقة شفافة
draw_card(draw, SIZE)

# 4. مخطط الأعمدة
pad   = int(SIZE * 0.12)
card_t = int(SIZE * 0.21)
bx = pad + int(SIZE * 0.04)
by = card_t + int(SIZE * 0.04)
bw = SIZE - 2*pad - int(SIZE * 0.08)
bh = int(SIZE * 0.40)
draw_bar_chart(draw, bx, by, bw, bh)
draw_trend_line(draw, bx, by, bw, bh)

# 5. عملة ذهبية
draw_small_coins(draw, SIZE)

# 6. شارة صح
draw_checkmark_badge(draw, SIZE)

# 7. شريط تزييني أسفل
draw_bottom_accent(draw, SIZE)

# ──────── حفظ بكل الأحجام ────────
sizes = [16, 24, 32, 48, 64, 128, 256]
icon_imgs = []
for s in sizes:
    resized = img.resize((s, s), Image.LANCZOS)
    icon_imgs.append(resized)

# حفظ ICO
icon_imgs[-1].save(
    "app_icon.ico",
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=icon_imgs[:-1]
)

# حفظ PNG للمعاينة (512×512)
img.save("app_icon_preview.png", "PNG")

print("✅ تم إنشاء الأيقونة الاحترافية:")
print("   app_icon.ico     — للبرنامج")
print("   app_icon_preview.png — للمعاينة")
