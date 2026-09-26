"""
Shared drawing layer for the SIH deck generator.

One geometry spec, two renderers:
  - to_pptx()    -> the real PowerPoint file (the deliverable)
    - to_preview() -> a PNG per slide, so the layout can actually be looked at
                    before it is shipped (no LibreOffice on this machine)

All coordinates are INCHES from the top-left of a 13.333 x 7.5in slide.
All text is pre-broken with explicit newlines: nothing is left to reflow
differently between the two renderers or between PowerPoint versions.

Palette is white / black / graphite only. There is no accent colour.
"""
from __future__ import annotations
import os

W, H = 13.333, 7.5

# ---- palette ---------------------------------------------------------------
INK = "111111"       # near-black, primary type and emphasis fills
GRAPHITE = "5A5F66"  # secondary type
MID = "8A8F96"       # tertiary type, de-emphasised labels
HAIR = "C9CDD2"      # hairlines and box outlines
WASH = "F2F3F5"      # very light panel fill
PALE = "E4E6E9"      # slightly stronger fill, table header bands
WHITE = "FFFFFF"
BLUE = "2F5D8C"      # restrained engineering accent

FONT = "Arial"
MONO = "Courier New"


class Canvas:
    """Accumulates drawing primitives for one slide."""

    def __init__(self):
        self.items = []

    # -- primitives ---------------------------------------------------------
    def rect(self, x, y, w, h, fill=None, edge=None, lw=0.75, dash=False,
             rounded=False):
        self.items.append(dict(k="rect", x=x, y=y, w=w, h=h,
                               fill=fill, edge=edge, lw=lw, dash=dash,
                               rounded=rounded))

    def line(self, x1, y1, x2, y2, c=HAIR, lw=0.75, dash=False):
        self.items.append(dict(k="line", x1=x1, y1=y1, x2=x2, y2=y2,
                               c=c, lw=lw, dash=dash))

    def poly(self, pts, fill=None, edge=None, lw=0.75, dash=False, close=True):
        self.items.append(dict(k="poly", pts=list(pts), fill=fill, edge=edge,
                               lw=lw, dash=dash, close=close))

    def dot(self, cx, cy, r, fill=INK, edge=None, lw=0.75):
        self.items.append(dict(k="dot", cx=cx, cy=cy, r=r,
                               fill=fill, edge=edge, lw=lw))

    def text(self, x, y, w, s, size=9.0, c=INK, bold=False, align="l",
             lead=1.22, font=FONT):
        self.items.append(dict(k="text", x=x, y=y, w=w, s=s, size=size, c=c,
                               bold=bold, align=align, lead=lead, font=font))

    def img(self, path, x, y, w, h):
        self.items.append(dict(k="img", p=path, x=x, y=y, w=w, h=h))

    # -- composites ---------------------------------------------------------
    def chevron(self, cx, cy, size=0.09, c=MID):
        """Small right-pointing triangle used between pipeline stages."""
        self.poly([(cx - size * 0.55, cy - size),
                   (cx + size * 0.75, cy),
                   (cx - size * 0.55, cy + size)], fill=c, edge=None)

    def arrow_h(self, x1, x2, y, c=INK, lw=1.1, head=0.10):
        self.line(x1, y, x2 - head * 0.9, y, c=c, lw=lw)
        self.poly([(x2 - head, y - head * 0.72),
                   (x2, y),
                   (x2 - head, y + head * 0.72)], fill=c, edge=None)


def text_height(s, size, lead):
    """Inches occupied by a pre-broken string."""
    return len(s.split("\n")) * size * lead / 72.0


# ===========================================================================
# PPTX renderer
# ===========================================================================
def to_pptx(slides, out_path):
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
    from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
    from pptx.enum.dml import MSO_LINE_DASH_STYLE

    ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}

    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    blank = prs.slide_layouts[6]

    def rgb(hexs):
        return RGBColor.from_string(hexs)

    def style_shape(shp, fill, edge, lw, dash):
        shp.shadow.inherit = False
        if fill:
            shp.fill.solid()
            shp.fill.fore_color.rgb = rgb(fill)
        else:
            shp.fill.background()
        if edge:
            shp.line.color.rgb = rgb(edge)
            shp.line.width = Pt(lw)
            if dash:
                shp.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        else:
            shp.line.fill.background()

    for spec in slides:
        s = prs.slides.add_slide(blank)
        for it in spec.items:
            k = it["k"]

            if k == "rect":
                shp = s.shapes.add_shape(
                    MSO_SHAPE.ROUNDED_RECTANGLE if it.get("rounded") else MSO_SHAPE.RECTANGLE,
                    Inches(it["x"]), Inches(it["y"]),
                    Inches(it["w"]), Inches(it["h"]))
                style_shape(shp, it["fill"], it["edge"], it["lw"], it["dash"])

            elif k == "line":
                cn = s.shapes.add_connector(
                    MSO_CONNECTOR.STRAIGHT, Inches(it["x1"]), Inches(it["y1"]),
                    Inches(it["x2"]), Inches(it["y2"]))
                cn.line.color.rgb = rgb(it["c"])
                cn.line.width = Pt(it["lw"])
                if it["dash"]:
                    cn.line.dash_style = MSO_LINE_DASH_STYLE.DASH

            elif k == "poly":
                pts = it["pts"]
                b = s.shapes.build_freeform(Inches(pts[0][0]), Inches(pts[0][1]))
                b.add_line_segments([(Inches(px), Inches(py))
                                     for px, py in pts[1:]], close=it["close"])
                shp = b.convert_to_shape()
                style_shape(shp, it["fill"], it["edge"], it["lw"], it["dash"])

            elif k == "dot":
                r = it["r"]
                shp = s.shapes.add_shape(
                    MSO_SHAPE.OVAL, Inches(it["cx"] - r), Inches(it["cy"] - r),
                    Inches(2 * r), Inches(2 * r))
                style_shape(shp, it["fill"], it["edge"], it["lw"], False)

            elif k == "img":
                s.shapes.add_picture(it["p"], Inches(it["x"]), Inches(it["y"]),
                                     Inches(it["w"]), Inches(it["h"]))

            elif k == "text":
                h = text_height(it["s"], it["size"], it["lead"]) + 0.06
                tb = s.shapes.add_textbox(Inches(it["x"]), Inches(it["y"] - 0.035),
                                          Inches(it["w"]), Inches(h))
                tf = tb.text_frame
                tf.word_wrap = True
                tf.auto_size = MSO_AUTO_SIZE.NONE
                tf.vertical_anchor = MSO_ANCHOR.TOP
                tf.margin_left = tf.margin_right = 0
                tf.margin_top = tf.margin_bottom = 0
                lines = it["s"].split("\n")
                for i, ln in enumerate(lines):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.alignment = ALIGN[it["align"]]
                    p.line_spacing = it["lead"]
                    p.space_before = Pt(0)
                    p.space_after = Pt(0)
                    run = p.add_run()
                    run.text = ln
                    f = run.font
                    f.size = Pt(it["size"])
                    f.bold = it["bold"]
                    f.name = it["font"]
                    f.color.rgb = rgb(it["c"])

    prs.save(out_path)
    return out_path


# ===========================================================================
# Preview renderer (matplotlib) -- for visual QA only, never shipped
# ===========================================================================
def to_preview(slides, out_dir, prefix="preview"):
    os.environ.setdefault("MPLCONFIGDIR",
                          os.environ.get("TMPDIR", "/tmp") + "/mplcache")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Polygon, Circle, FancyBboxPatch
    import matplotlib.image as mpimg

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    })
    HA = {"l": "left", "c": "center", "r": "right"}
    paths = []
    os.makedirs(out_dir, exist_ok=True)

    for n, spec in enumerate(slides, start=1):
        fig = plt.figure(figsize=(W, H), dpi=105)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, W)
        ax.set_ylim(H, 0)
        ax.axis("off")
        ax.add_patch(Rectangle((0, 0), W, H, facecolor="white", edgecolor="none"))

        for it in spec.items:
            k = it["k"]
            ds = (3, 2) if it.get("dash") else None

            if k == "rect":
                patch = FancyBboxPatch if it.get("rounded") else Rectangle
                kwargs = dict(
                    facecolor=("#" + it["fill"]) if it["fill"] else "none",
                    edgecolor=("#" + it["edge"]) if it["edge"] else "none",
                    linewidth=it["lw"], linestyle=(0, ds) if ds else "-",
                )
                if it.get("rounded"):
                    kwargs["boxstyle"] = "round,pad=0.02,rounding_size=0.08"
                ax.add_patch(patch((it["x"], it["y"]), it["w"], it["h"], **kwargs))

            elif k == "line":
                ax.plot([it["x1"], it["x2"]], [it["y1"], it["y2"]],
                        color="#" + it["c"], linewidth=it["lw"],
                        linestyle=(0, ds) if ds else "-",
                        solid_capstyle="butt")

            elif k == "poly":
                ax.add_patch(Polygon(
                    it["pts"], closed=it["close"],
                    facecolor=("#" + it["fill"]) if it["fill"] else "none",
                    edgecolor=("#" + it["edge"]) if it["edge"] else "none",
                    linewidth=it["lw"], linestyle=(0, ds) if ds else "-"))

            elif k == "dot":
                ax.add_patch(Circle(
                    (it["cx"], it["cy"]), it["r"],
                    facecolor=("#" + it["fill"]) if it["fill"] else "none",
                    edgecolor=("#" + it["edge"]) if it["edge"] else "none",
                    linewidth=it["lw"]))

            elif k == "img":
                im = mpimg.imread(it["p"])
                ax.imshow(im, extent=(it["x"], it["x"] + it["w"],
                                      it["y"] + it["h"], it["y"]),
                          aspect="auto", zorder=5)

            elif k == "text":
                tx = {"l": it["x"], "c": it["x"] + it["w"] / 2,
                      "r": it["x"] + it["w"]}[it["align"]]
                ax.text(tx, it["y"], it["s"], ha=HA[it["align"]], va="top",
                        fontsize=it["size"], color="#" + it["c"],
                        fontweight="bold" if it["bold"] else "normal",
                        linespacing=it["lead"] * 1.02, zorder=6)

        p = os.path.join(out_dir, f"{prefix}_{n:02d}.png")
        fig.savefig(p, dpi=105)
        plt.close(fig)
        paths.append(p)
    return paths
