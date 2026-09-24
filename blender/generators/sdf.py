"""Tiny numpy SDF sculpting kit: smooth-blended primitives -> surface-nets quad mesh.

Used by generators that need organic forms the skin modifier can't make (rex.py). No Blender imports,
so it runs anywhere numpy does.

    ops = [Op(ESeg(a, b, (wa, ha), (wb, hb)), k=0.2), Op(Ellipsoid(c, r), k=0.1, sub=True), ...]
    V, F = mesh(ops, h=0.02)            # vertices (N,3) float64, quads (M,4) int32, outward winding

Distances are approximate (ellipsoid bound, iq style), which is fine for a zero set; the extracted
vertices are Newton-projected back onto the surface. Each op only touches the grid inside its bbox
grown by 1.5 k, which is exact for the zero set (polynomial smin == min once |a - b| >= k).
"""
import numpy as np

Y = np.array((0.0, 1.0, 0.0))


def _v(x):
    return np.asarray(x, dtype=np.float64)


class Ellipsoid:
    def __init__(self, c, r, rot=None):
        self.c, self.r = _v(c), _v(r)
        self.R = None if rot is None else _v(rot)       # 3x3, columns = local axes in world
        ext = np.abs(self.R) @ self.r if self.R is not None else self.r
        self.lo, self.hi = self.c - ext, self.c + ext

    def __call__(self, P):
        q = P - self.c
        if self.R is not None:
            q = q @ self.R
        k0 = np.linalg.norm(q / self.r, axis=-1)
        k1 = np.linalg.norm(q / (self.r * self.r), axis=-1)
        return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


class ESeg:
    """Segment a->b swept by an ellipse: half-width w along the lateral axis (world Y made perpendicular),
    half-height h in the segment's plane. Radii lerp along the segment; the ends are ellipsoid caps."""

    def __init__(self, a, b, ra, rb, cap=None):
        self.a, self.b = _v(a), _v(b)
        self.ra, self.rb = _v(ra), _v(rb)
        ab = self.b - self.a
        self.L = np.linalg.norm(ab)
        self.u = ab / self.L
        side = Y - self.u * self.u.dot(Y)
        if np.linalg.norm(side) < 1e-6:
            side = np.array((1.0, 0, 0))
        self.s = side / np.linalg.norm(side)
        self.v = np.cross(self.u, self.s)
        self.cap = cap
        m = max(self.ra.max(), self.rb.max())
        self.lo = np.minimum(self.a, self.b) - m
        self.hi = np.maximum(self.a, self.b) + m

    def __call__(self, P):
        q = P - self.a
        t = q @ self.u
        tc = np.clip(t / self.L, 0.0, 1.0)
        w = self.ra[0] + (self.rb[0] - self.ra[0]) * tc
        h = self.ra[1] + (self.rb[1] - self.ra[1]) * tc
        du = t - tc * self.L
        ru = np.minimum(w, h) if self.cap is None else self.cap
        x = np.stack([q @ self.s, q @ self.v, du], -1)
        r = np.stack([w, h, np.broadcast_to(ru, w.shape)], -1)
        k0 = np.linalg.norm(x / r, axis=-1)
        k1 = np.linalg.norm(x / (r * r), axis=-1)
        return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


class Op:
    def __init__(self, prim, k=0.0, sub=False):
        self.p, self.k, self.sub = prim, k, sub
        m = 1.5 * k + 1e-3
        self.lo, self.hi = prim.lo - m, prim.hi + m


def sweep(pts, k=0.0, cap=None):
    """pts: [(xyz, (w, h)), ...] -> one Op per span (plain min between spans of one sweep)."""
    return [Op(ESeg(a, b, ra, rb, cap), k) for (a, ra), (b, rb) in zip(pts, pts[1:])]


def mirror_y(ops):
    out = []
    for o in ops:
        p = o.p
        if isinstance(p, ESeg):
            q = ESeg(p.a * (1, -1, 1), p.b * (1, -1, 1), p.ra, p.rb, p.cap)
        else:
            R = None if p.R is None else np.diag((1, -1, 1)) @ p.R
            q = Ellipsoid(p.c * (1, -1, 1), p.r, R)
        out.append(Op(q, o.k, o.sub))
    return out


def _combine(d, e, k, sub):
    if sub:
        e = -e
        if k <= 0:
            return np.maximum(d, e)
        hh = np.maximum(k - np.abs(d - e), 0.0) / k
        return np.maximum(d, e) + hh * hh * k * 0.25
    if k <= 0:
        return np.minimum(d, e)
    hh = np.maximum(k - np.abs(d - e), 0.0) / k
    return np.minimum(d, e) - hh * hh * k * 0.25


FAR = 10.0


def eval_points(ops, P):
    P = _v(P)
    d = np.full(P.shape[0], FAR)
    for o in ops:
        m = np.all((P >= o.lo) & (P <= o.hi), axis=1)
        if not m.any():
            continue
        d[m] = _combine(d[m], o.p(P[m]), o.k, o.sub)
    return d


def eval_grid(ops, lo, h, n):
    d = np.full(n, FAR, dtype=np.float32)
    axes = [lo[i] + h * np.arange(n[i]) for i in range(3)]
    for o in ops:
        i0 = np.clip(np.floor((o.lo - lo) / h).astype(int), 0, n)
        i1 = np.clip(np.ceil((o.hi - lo) / h).astype(int) + 1, 0, n)
        if np.any(i1 <= i0):
            continue
        X, Yg, Z = np.meshgrid(axes[0][i0[0]:i1[0]], axes[1][i0[1]:i1[1]], axes[2][i0[2]:i1[2]], indexing="ij")
        P = np.stack([X, Yg, Z], -1)
        sl = (slice(i0[0], i1[0]), slice(i0[1], i1[1]), slice(i0[2], i1[2]))
        d[sl] = _combine(d[sl].astype(np.float64), o.p(P), o.k, o.sub)
    return d


CORNERS = [(i, j, k) for k in (0, 1) for j in (0, 1) for i in (0, 1)]
EDGES = [(a, b) for a in range(8) for b in range(a + 1, 8)
         if sum(abs(CORNERS[a][t] - CORNERS[b][t]) for t in range(3)) == 1]


def surface_nets(d, lo, h):
    nx, ny, nz = d.shape
    s = d < 0
    code = np.zeros((nx - 1, ny - 1, nz - 1), np.uint8)
    for bit, (i, j, k) in enumerate(CORNERS):
        code |= s[i:nx - 1 + i, j:ny - 1 + j, k:nz - 1 + k].astype(np.uint8) << bit
    active = (code != 0) & (code != 255)
    ai, aj, ak = np.nonzero(active)
    count = len(ai)
    idx = np.full(active.shape, -1, np.int64)
    idx[ai, aj, ak] = np.arange(count)
    acc = np.zeros((count, 3))
    cnt = np.zeros(count)
    for a, b in EDGES:
        ca, cb = np.array(CORNERS[a]), np.array(CORNERS[b])
        d0 = d[ai + ca[0], aj + ca[1], ak + ca[2]].astype(np.float64)
        d1 = d[ai + cb[0], aj + cb[1], ak + cb[2]].astype(np.float64)
        m = (d0 < 0) != (d1 < 0)
        t = d0[m] / (d0[m] - d1[m])
        acc[m] += ca + t[:, None] * (cb - ca)
        cnt[m] += 1
    V = _v(lo) + (np.stack([ai, aj, ak], 1) + acc / np.maximum(cnt, 1)[:, None]) * h

    faces = []
    n = (nx, ny, nz)
    for ax in range(3):
        b, c = (ax + 1) % 3, (ax + 2) % 3
        s0 = [slice(None)] * 3
        s1 = [slice(None)] * 3
        s0[ax], s1[ax] = slice(0, n[ax] - 1), slice(1, n[ax])
        m = s[tuple(s0)] != s[tuple(s1)]
        for dim in (b, c):
            e = [slice(None)] * 3
            e[dim] = 0
            m[tuple(e)] = False
            e[dim] = n[dim] - 1
            m[tuple(e)] = False
        I = np.nonzero(m)
        inside = s[I]
        quad = []
        for db, dc in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            q = list(I)
            q[b] = I[b] + db
            q[c] = I[c] + dc
            quad.append(idx[q[0], q[1], q[2]])
        Q = np.stack(quad, 1)
        Q[~inside] = Q[~inside][:, ::-1]
        faces.append(Q)
    F = np.concatenate(faces).astype(np.int64)
    return V, F


def project(ops, V, h, iters=3):
    """Newton steps onto the zero set (central-difference gradient), capped at one voxel per step."""
    e = h * 0.25
    for _ in range(iters):
        d = eval_points(ops, V)
        g = np.stack([(eval_points(ops, V + off) - eval_points(ops, V - off)) / (2 * e)
                      for off in np.eye(3) * e], 1)
        g2 = np.maximum((g * g).sum(1), 1e-9)
        step = (d / g2)[:, None] * g
        ln = np.linalg.norm(step, axis=1)
        step *= (np.minimum(ln, h * 0.7) / np.maximum(ln, 1e-12))[:, None]
        V = V - step
    return V


def mesh(ops, h, pad=0.1, proj_iters=3):
    lo = np.min([o.p.lo for o in ops if not o.sub], axis=0) - pad
    hi = np.max([o.p.hi for o in ops if not o.sub], axis=0) + pad
    n = tuple(int(x) for x in np.ceil((hi - lo) / h).astype(int) + 1)
    d = eval_grid(ops, lo, h, n)
    V, F = surface_nets(d, lo, h)
    if proj_iters:
        V = project(ops, V, h, proj_iters)
    return V, F


def normals(ops, V, h):
    e = h * 0.25
    g = np.stack([(eval_points(ops, V + off) - eval_points(ops, V - off)) for off in np.eye(3) * e], 1)
    return g / np.maximum(np.linalg.norm(g, axis=1), 1e-12)[:, None]
