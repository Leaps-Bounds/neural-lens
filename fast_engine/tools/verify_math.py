"""Checks the engine's two shaders against their arithmetic done again on the CPU.

    python verify_math.py OUTDIR [--original PNG]

OUTDIR is a folder the self test wrote: composite.png, nr_in.png and nr_out.png. The original
is the picture the test ran on, docs\\images\\blender-before.png unless --original names
another.

1. The area downscale of the original to the size of nr_in.png, done here in float32 tap by
   tap as the ingest shader does it, against nr_in.png.
2. The residual composite of the original with nr_in.png and nr_out.png, done here the same
   way as the composite shader, against composite.png.

Both are computed for each axis by itself, so the check holds for a work size that is
squeezed in one direction, as 2560x896 for a 6144x2526 picture, as well as for one with the
picture's own proportions. The network is not part of the check. Its input and its output
are taken as they are.

The arithmetic is the shaders', operation for operation, in float32. The downscale's weights
are computed in double and rounded to float, as the engine computes them on the CPU. The
composite's sample positions are whole numbers, and the weight between two work texels is a
remainder times the float nearest to the reciprocal of its divisor, not a quotient.
src\\shaders\\composite_ps.hlsl says why.

Exit code 0 when both are equal byte for byte, 1 when a byte differs.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None   # the pictures are large on purpose
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ORIGINAL = os.path.join(REPO, "docs", "images", "blender-before.png")
f32 = np.float32


def rgb(path):
    return np.asarray(Image.open(path).convert("RGB"), np.uint8)


def area_taps(src, dst):
    """For every work texel along one axis: its first source texel and the float weights of
    its footprint, the part of each source texel under the work texel over the scale."""
    scale = src / dst
    first, weights = [], []
    for i in range(dst):
        a, b = i * scale, (i + 1) * scale
        j0, j1 = int(np.floor(a)), min(src, int(np.ceil(b)))
        ws = []
        for j in range(j0, j1):
            w = min(b, j + 1.0) - max(a, float(j))
            if w <= 0:
                continue
            ws.append(f32(w / scale))
        first.append(j0)
        weights.append(ws)
    return first, weights


def area_downscale(img, dw, dh):
    """Across each source row first, then down the rows, all in float32, tap by tap."""
    H, W = img.shape[:2]
    fx, wx = area_taps(W, dw)
    fy, wy = area_taps(H, dh)
    src = img.astype(f32)
    n = max(len(w) for w in wx)
    tmp = np.zeros((H, dw, 3), f32)
    for k in range(n):
        idx = np.array([fx[x] + k if k < len(wx[x]) else 0 for x in range(dw)])
        wgt = np.array([wx[x][k] if k < len(wx[x]) else 0 for x in range(dw)], f32)
        has = np.array([k < len(wx[x]) for x in range(dw)])
        add = src[:, idx, :] * wgt[None, :, None]
        tmp[:, has, :] = tmp[:, has, :] + add[:, has, :]
    dst = np.zeros((dh, dw, 3), f32)
    for y in range(dh):
        for k, wgt in enumerate(wy[y]):
            dst[y] = dst[y] + wgt * tmp[fy[y] + k]
    return dst


def round_half_up(v):
    """To the nearest whole number, a half going up, for what is never negative."""
    lo = np.floor(v)
    return lo + ((v - lo) >= 0.5)


def axis(full, work):
    """The two work texels under each of `full` pixels along one axis, and the weight of the
    second, as composite_ps.hlsl computes them: the sample position s = (x + 0.5) * work /
    full - 0.5 in whole numbers, s = n / d with n = (2x + 1) * work - full held inside 0 to
    (work - 1) * d and d = 2 * full. i0 is n / d rounded down, and f is the remainder as a
    float times the float nearest to 1 / d."""
    x = np.arange(full, dtype=np.int64)
    d = 2 * full
    n = np.clip((2 * x + 1) * work - full, 0, (work - 1) * d)
    i0 = n // d
    f = (n - i0 * d).astype(f32) * (f32(1.0) / f32(d))
    return i0, np.minimum(i0 + 1, work - 1), f.astype(f32)


def residual_composite(native, nr_in, nr_out):
    """native + bilinear(nr_out - nr_in), the sample positions of each axis by themselves."""
    H, W = native.shape[:2]
    wh, ww = nr_in.shape[:2]
    diff = nr_out.astype(f32) - nr_in.astype(f32)
    x0, x1, fx = axis(W, ww)
    y0, y1, fy = axis(H, wh)
    out = np.empty((H, W, 3), np.uint8)
    step = 128
    for top in range(0, H, step):
        ys = slice(top, min(H, top + step))
        r0, r1 = diff[y0[ys]], diff[y1[ys]]
        a = r0[:, x0] + (r0[:, x1] - r0[:, x0]) * fx[None, :, None]
        b = r1[:, x0] + (r1[:, x1] - r1[:, x0]) * fx[None, :, None]
        d = a + (b - a) * fy[ys][:, None, None]
        v = native[ys].astype(f32) + d
        out[ys] = np.clip(round_half_up(v), 0, 255).astype(np.uint8)
    return out


def report(label, a, b):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    differing = int((d > 0).sum())
    print("%-58s mean_abs %.6f max %d differing %d of %d" % (label, d.mean(), d.max(), differing, d.size))
    return differing


def main():
    ap = argparse.ArgumentParser(description="Checks the engine's downscale and composite against the CPU.")
    ap.add_argument("outdir")
    ap.add_argument("--original", default=ORIGINAL)
    args = ap.parse_args()

    native = rgb(args.original)
    mine_in = rgb(os.path.join(args.outdir, "nr_in.png"))
    mine_out = rgb(os.path.join(args.outdir, "nr_out.png"))
    wh, ww = mine_in.shape[:2]
    H, W = native.shape[:2]
    print("picture %dx%d, work size %dx%d, scale %.4f across and %.4f down" % (W, H, ww, wh, W / ww, H / wh))

    replay = np.clip(round_half_up(area_downscale(native, ww, wh)), 0, 255).astype(np.uint8)
    bad = report("the engine's nr_in against the downscale done here", mine_in, replay)
    comp = residual_composite(native, mine_in, mine_out)
    bad += report("the engine's composite against the composite done here",
                  rgb(os.path.join(args.outdir, "composite.png")), comp)
    print("verify_math: %s" % ("both equal byte for byte" if bad == 0 else "A BYTE DIFFERS"))
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
