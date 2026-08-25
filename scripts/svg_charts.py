#!/usr/bin/env python3
"""Minimal inline-SVG chart helpers for the HTML reports.

Self-contained on purpose: these reports are opened as local files and passed around, so a CDN
chart library would render a blank panel on a machine with no network. Everything here is plain
SVG in the document.

Design rules applied (see the dataviz method):
  - thin marks, 4px rounded data-ends anchored to the baseline, 2px lines, >=8px markers
  - a 2px surface gap between adjacent fills so bars never touch
  - recessive grid and axes; text in ink tokens, never in the series colour
  - a legend whenever there are >=2 series, plus selective direct labels
  - categorical hues assigned in fixed order per ENTITY, never cycled by rank

Palette is the project's per-model colours from runs_config, validated against this report
surface (#161b22): CVD dE 9.0, normal-vision 19.8, contrast >=3:1 on all pairs.
"""
import html as H

INK = '#e6edf3'
MUT = '#9aa7b4'
LINE = '#283041'
SURFACE = '#161b22'


def _esc(s):
    return H.escape(str(s))


def _nice(v):
    """Round an axis maximum up to a readable step, so ticks read 0/12/24/36/48 not 0/12/24/35/47."""
    if v <= 0:
        return 1
    for step in (0.25, 0.5, 1, 2, 5, 10, 20, 25, 50, 100):
        if v <= step * 4:
            return step * 4
    import math
    return math.ceil(v / 100) * 100


def _txt(x, y, s, fill=MUT, size=11, anchor='start', weight='400'):
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" '
            f'font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif">{_esc(s)}</text>')


def hbar(rows, *, width=620, bar=17, gap=11, pad_left=190, fmt=lambda v: f'{v:.0f}',
         maxval=None, title=None, sub=None):
    """Horizontal bars. rows = [(label, value, colour)].

    One row per entity, colour carried by the entity. Values are direct-labelled at the bar end,
    so no value axis is drawn — a grid would be redundant against a label on every mark.
    """
    if not rows:
        return ''
    top = 8 + (26 if title else 0) + (16 if sub else 0)
    h = top + len(rows) * (bar + gap) + 6
    mx = maxval or max(v for _, v, _ in rows) or 1
    plot_w = width - pad_left - 62
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" height="{h}" role="img">']
    if title:
        out.append(_txt(0, 15, title, INK, 12.5, weight='700'))
    if sub:
        out.append(_txt(0, 15 + (15 if title else 0), sub, MUT, 11))
    for i, (lab, v, col) in enumerate(rows):
        y = top + i * (bar + gap)
        w = max(2.0, v / mx * plot_w)
        out.append(_txt(pad_left - 10, y + bar * 0.74, lab, INK, 11.5, anchor='end'))
        out.append(f'<rect x="{pad_left}" y="{y}" width="{w:.1f}" height="{bar}" rx="4" '
                   f'fill="{col}"/>')
        out.append(_txt(pad_left + w + 8, y + bar * 0.74, fmt(v), MUT, 11))
    out.append('</svg>')
    return '\n'.join(out)


def grouped_bar(groups, series, *, width=620, height=210, pad_left=42, pad_bottom=46,
                fmt=lambda v: f'{v:.0f}', title=None, sub=None, ymax=None, ylabel=None):
    """Vertical grouped bars. groups = [label]; series = [(name, colour, [v per group])].

    A 2px gap separates adjacent bars so two fills never share an edge.
    """
    if not groups or not series:
        return ''
    top = 8 + (26 if title else 0) + (16 if sub else 0)
    legend_h = 22
    h = height + pad_bottom + top + legend_h
    plot_w = width - pad_left - 12
    plot_h = height
    mx = _nice(ymax or max(max(v for v in s[2]) for s in series) or 1)
    gw = plot_w / len(groups)
    bw = min(28.0, (gw - 16) / len(series) - 2)
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" height="{h}" role="img">']
    if title:
        out.append(_txt(0, 15, title, INK, 12.5, weight='700'))
    if sub:
        out.append(_txt(0, 15 + (15 if title else 0), sub, MUT, 11))
    # recessive gridlines + value axis
    for f in (0, .25, .5, .75, 1):
        y = top + plot_h - f * plot_h
        out.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width-12}" y2="{y:.1f}" '
                   f'stroke="{LINE}" stroke-width="1"/>')
        out.append(_txt(pad_left - 7, y + 3.5, fmt(mx * f), MUT, 10, anchor='end'))
    if ylabel:
        out.append(_txt(pad_left - 7, top - 6, ylabel, MUT, 10, anchor='end'))
    for gi, g in enumerate(groups):
        gx = pad_left + gi * gw
        for si, (name, col, vals) in enumerate(series):
            v = vals[gi]
            bh = max(2.0, (v / mx) * plot_h)
            x = gx + (gw - (bw + 2) * len(series)) / 2 + si * (bw + 2)
            y = top + plot_h - bh
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                       f'rx="4" fill="{col}"/>')
            out.append(_txt(x + bw / 2, y - 5, fmt(v), MUT, 10, anchor='middle'))
        for li, part in enumerate(str(g).split('\n')):
            out.append(_txt(gx + gw / 2, top + plot_h + 16 + li * 12, part, INK, 11,
                            anchor='middle'))
    ly = top + plot_h + pad_bottom - 4
    lx = pad_left
    for name, col, _ in series:
        out.append(f'<rect x="{lx}" y="{ly-8}" width="10" height="10" rx="3" fill="{col}"/>')
        out.append(_txt(lx + 15, ly + 1, name, MUT, 11))
        lx += 22 + len(name) * 6.4
    out.append('</svg>')
    return '\n'.join(out)


def line_chart(xlabels, series, *, width=620, height=180, pad_left=42, pad_bottom=52,
               fmt=lambda v: f'{v:g}', title=None, sub=None, ymax=None):
    """Line chart. series = [(name, colour, [v per x])]. 2px strokes, 9px markers."""
    if not xlabels or not series:
        return ''
    top = 8 + (26 if title else 0) + (16 if sub else 0)
    legend_h = 22
    h = height + pad_bottom + top + legend_h
    plot_w = width - pad_left - 20
    mx = _nice(ymax or max(max(s[2]) for s in series) or 1)
    step = plot_w / max(len(xlabels) - 1, 1)
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" height="{h}" role="img">']
    if title:
        out.append(_txt(0, 15, title, INK, 12.5, weight='700'))
    if sub:
        out.append(_txt(0, 15 + (15 if title else 0), sub, MUT, 11))
    for f in (0, .5, 1):
        y = top + height - f * height
        out.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width-14}" y2="{y:.1f}" '
                   f'stroke="{LINE}" stroke-width="1"/>')
        out.append(_txt(pad_left - 7, y + 3.5, fmt(mx * f), MUT, 10, anchor='end'))
    for name, col, vals in series:
        pts = [(pad_left + i * step, top + height - (v / mx) * height)
               for i, v in enumerate(vals)]
        out.append('<polyline fill="none" stroke="' + col + '" stroke-width="2" '
                   'stroke-linejoin="round" points="'
                   + ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts) + '"/>')
        for (x, y), v in zip(pts, vals):
            # 2px surface ring so overlapping markers stay separable
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{col}" '
                       f'stroke="{SURFACE}" stroke-width="2"/>')
        out.append(_txt(pts[-1][0] + 9, pts[-1][1] + 4, fmt(vals[-1]), MUT, 10.5))
    for i, lab in enumerate(xlabels):
        x = pad_left + i * step
        for li, part in enumerate(str(lab).split('\n')):
            out.append(_txt(x, top + height + 17 + li * 12, part, INK if li == 0 else MUT,
                            11 if li == 0 else 10, anchor='middle'))
    ly = top + height + pad_bottom - 2
    lx = pad_left
    for name, col, _ in series:
        out.append(f'<line x1="{lx}" y1="{ly-4}" x2="{lx+14}" y2="{ly-4}" stroke="{col}" '
                   f'stroke-width="2"/>')
        out.append(f'<circle cx="{lx+7}" cy="{ly-4}" r="4" fill="{col}"/>')
        out.append(_txt(lx + 20, ly, name, MUT, 11))
        lx += 30 + len(name) * 6.4
    out.append('</svg>')
    return '\n'.join(out)
