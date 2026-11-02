"""Аппроксимация спектра суммой 1–3 логнормальных мод (без SciPy).

Модель для dN/dlogDp (log10):
    n(D) = Σ Nᵢ / (√(2π)·log10 σᵢ) · exp(−(log10 D − log10 CMDᵢ)² / (2·log10² σᵢ))
Параметры подбираются методом Левенберга–Марквардта по наименьшим квадратам, как в
py-smps (curve_fit) и в подходе Hussein et al., Boreal Env. Res. 10 (2005) 337–355.
Погрешности — из ковариационной матрицы (JᵀJ)⁻¹·s²."""
import numpy as np

SQRT2PI = np.sqrt(2 * np.pi)


def model(logd, p):
    """p = [ln N, ln CMD, ln(ln σ)] × моды; logd = log10 D."""
    y = np.zeros_like(logd)
    for k in range(len(p) // 3):
        N = np.exp(p[3 * k])
        mu = p[3 * k + 1] / np.log(10)                 # log10 CMD
        s = np.exp(p[3 * k + 2]) / np.log(10)          # log10 σ
        y += N / (SQRT2PI * s) * np.exp(-(logd - mu) ** 2 / (2 * s * s))
    return y


def _jacobian(logd, p, f0):
    J = np.empty((len(logd), len(p)))
    for j in range(len(p)):
        h = 1e-6 * max(1.0, abs(p[j]))
        q = p.copy()
        q[j] += h
        J[:, j] = (model(logd, q) - f0) / h
    return J


def _lm(logd, y, p0, max_iter=300):
    p = np.asarray(p0, float).copy()
    f = model(logd, p)
    r = y - f
    cost = float(r @ r)
    lam = 1e-3
    for _ in range(max_iter):
        J = _jacobian(logd, p, f)
        A = J.T @ J
        g = J.T @ r
        improved = False
        while lam < 1e12:
            try:
                dp = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            q = p + dp
            q[2::3] = np.clip(q[2::3], np.log(np.log(1.03)), np.log(np.log(5.0)))   # σ от 1,03 до 5
            fq = model(logd, q)
            rq = y - fq
            cq = float(rq @ rq)
            if np.isfinite(cq) and cq < cost:
                rel = (cost - cq) / max(cost, 1e-300)
                p, f, r, cost = q, fq, rq, cq
                lam = max(lam / 3, 1e-12)
                improved = True
                break
            lam *= 4
        if not improved or rel < 1e-10:
            break
    return p, cost


def _initial_guesses(logd, y, modes):
    """Несколько стартовых точек: по пикам сглаженной кривой и по квантилям распределения."""
    w = np.clip(y, 0, None)
    total_area = float(np.sum(w) * np.mean(np.diff(logd))) if len(logd) > 1 else float(w.sum())
    guesses = []
    ys = np.convolve(w, np.ones(5) / 5, mode='same')
    peaks = [i for i in range(1, len(ys) - 1) if ys[i] >= ys[i - 1] and ys[i] > ys[i + 1]]
    peaks.sort(key=lambda i: -ys[i])
    cum = np.cumsum(w) / max(w.sum(), 1e-300)
    quant = [logd[min(int(np.searchsorted(cum, (j + 0.5) / modes)), len(logd) - 1)] for j in range(modes)]
    centres = [sorted(logd[peaks[:modes]].tolist() + quant[:max(0, modes - len(peaks))]), sorted(quant)]
    for c in centres:
        for sig in (1.5, 1.8):
            p = []
            for mu in c[:modes]:
                p += [np.log(max(total_area / modes, 1e-30)), mu * np.log(10), np.log(np.log(sig))]
            guesses.append(np.array(p))
    return guesses


def fit(D, dndlogdp, modes=1, mask=None):
    """Подбор modes логнормальных мод. Возвращает dict или None, если данных недостаточно.
    Моды упорядочены по возрастанию CMD."""
    D = np.asarray(D, float)
    y = np.nan_to_num(np.asarray(dndlogdp, float))
    m = np.ones_like(D, bool) if mask is None else np.asarray(mask, bool)
    m &= np.isfinite(y) & (D > 0)
    if m.sum() < 3 * modes + 2 or np.max(y[m]) <= 0:
        return None
    logd, yy = np.log10(D[m]), y[m]
    best = None
    for p0 in _initial_guesses(logd, yy, modes):
        p, cost = _lm(logd, yy, p0)
        if best is None or cost < best[1]:
            best = (p, cost)
    p, cost = best
    n, k = len(yy), len(p)
    J = _jacobian(logd, p, model(logd, p))
    s2 = cost / max(n - k, 1)
    try:
        cov = np.linalg.inv(J.T @ J) * s2
        sd = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        sd = np.full(k, np.nan)
    res = []
    for j in range(modes):
        lnN, lnC, q = p[3 * j:3 * j + 3]
        sN, sC, sq = sd[3 * j:3 * j + 3]
        N, C, sig = np.exp(lnN), np.exp(lnC), np.exp(np.exp(q))
        res.append({'N': float(N), 'N_err': float(N * sN), 'CMD': float(C), 'CMD_err': float(C * sC),
                    'GSD': float(sig), 'GSD_err': float(sig * np.log(sig) * sq)})      # dσ/dq = σ·ln σ
    order = np.argsort([r['CMD'] for r in res])
    res = [res[i] for i in order]
    ss_tot = float(((yy - yy.mean()) ** 2).sum())
    return {'modes': res, 'r2': 1 - cost / ss_tot if ss_tot > 0 else np.nan,
            'params': [v for i in order for v in p[3 * i:3 * i + 3]]}


def curve(D, result, mode=None):
    """dN/dlogDp аппроксимации (всех мод или одной) в точках D."""
    p = np.asarray(result['params'], float)
    if mode is not None:
        p = p[3 * mode:3 * mode + 3]
    return model(np.log10(np.asarray(D, float)), p)
