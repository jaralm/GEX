"""
gex_calculator.py
-----------------
Calcula Gamma Exposure (GEX) y Delta Exposure (DEX) y KPIs derivados
desde el CSV de meff_opciones.py.

Parámetros del modelo:
  R            = 0.0244 (€STR, tasa libre de riesgo; dato BCE del 30/09/2026: 2,437 %)
  SWEEP_MARGIN = 0.15   (±15% del spot para buscar Zero Gamma / Zero Delta)
  N_SWEEP      = 600    (resolución del barrido)

Arrastre implícito (tipo − dividendos) por subyacente y vencimiento:
  El modelo trabaja con el forward F = S · e^x, donde x = ln(F/S) recoge el
  tipo de interés y los dividendos esperados hasta el vencimiento. x no se
  estima a partir de dividendos supuestos: se ajusta, para cada subyacente y
  vencimiento, minimizando el error entre la delta del modelo y la delta de
  cierre que publica MEFF en el boletín (columna delta_cierre). Así gamma y
  delta quedan coherentes con el modelo con el que MEFF calcula su volatilidad
  y su delta, dividendos incluidos.

  Con forward F y descuento e^(−rT) (Black-76 expresado sobre el spot):
    d1     = (ln(S/K) + x + σ²T/2) / (σ√T)
    Δ_call = e^(x−rT) · N(d1)        Δ_put = e^(x−rT) · (N(d1) − 1)
    Γ      = e^(x−rT) · n(d1) / (S σ √T)
  En el barrido de Zero Gamma / Zero Delta, x se mantiene fijo (el forward se
  mueve proporcionalmente al spot).

  Si un vencimiento no tiene deltas MEFF suficientes, se usa el arrastre anual
  mediano de los demás vencimientos del mismo subyacente; si tampoco hay, x = r·T
  (sin dividendos).

Multiplicadores por contrato:
  MINI IBEX-35 → 1 €/punto
  Resto        → 100 acciones/contrato

Convenio GEX (SpotGamma):
  GEX(K) = OI_call × Γ × S² × mult  −  OI_put × Γ × S² × mult
  Dealers asumidos short en ambos lados.
  GEX positivo → dealers long gamma → volatilidad amortiguada.
  GEX negativo → dealers short gamma → volatilidad amplificada.

Convenio DEX:
  DEX(K) = OI_call × Δ_call × S × mult  +  OI_put × Δ_put × S × mult
  Δ al spot actual: la delta de cierre de MEFF cuando existe; si falta, la del
  modelo con el arrastre implícito. En el barrido de Zero Delta se usa siempre
  la delta del modelo.
  DEX positivo (LONG)  → dealers son long delta → venden rallies (techo).
  DEX negativo (SHORT) → dealers son short delta → compran caídas (suelo).
"""

import re
import math
import numpy as np
import pandas as pd
from datetime import date, datetime

# ── Parámetros ────────────────────────────────────────────────────────────────
R            = 0.0244
SWEEP_MARGIN = 0.15
N_SWEEP      = 600

# Ajuste del arrastre implícito
X_MIN, X_MAX     = -0.40, 0.15   # límites de ln(F/S)
DELTA_MIN_AJUSTE = 0.03          # se usan opciones con 0,03 < |Δ MEFF| < 0,97
MIN_PUNTOS       = 3             # mínimo de opciones para ajustar un vencimiento

MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}

# ── Parseo de números ─────────────────────────────────────────────────────────

def parse_es(s) -> float:
    """
    Convierte string numérico en formato español/CSV mixto a float.

    '17.500'   → 17500.0   (miles: punto seguido de EXACTAMENTE 3 dígitos)
    '17622.7'  → 17622.7   (decimal anglosajón: otro número de decimales)
    '37,47'    → 37.47     (decimal español con coma)
    '2.116,60' → 2116.60   (mixto)
    '-'        → NaN
    """
    if pd.isna(s):
        return float("nan")
    s = str(s).strip()
    if s in ("", "-", "–", "—", "nan", "N/A"):
        return float("nan")
    try:
        if "," in s:
            return float(s.replace(".", "").replace(",", "."))
        elif "." in s:
            partes = s.split(".")
            if len(partes) == 2 and len(partes[1]) == 3:
                return float(s.replace(".", ""))
            return float(s)
        return float(s)
    except ValueError:
        return float("nan")


# ── Fechas ───────────────────────────────────────────────────────────────────

_fv_cache: dict = {}

def _tercer_viernes(anio: int, mes: int) -> date:
    key = (anio, mes)
    if key not in _fv_cache:
        d = date(anio, mes, 1)
        dias = (4 - d.weekday()) % 7
        _fv_cache[key] = date(anio, mes, 1 + dias + 14)
    return _fv_cache[key]


def _parsear_vencimiento(texto: str) -> date | None:
    """'May-26' → tercer viernes de mayo 2026."""
    m = re.match(r"([A-Za-z]+)-(\d{2,4})", str(texto).strip())
    if not m:
        return None
    mes = MESES.get(m.group(1).lower()[:3])
    if not mes:
        return None
    anio = int(m.group(2))
    anio = anio if anio > 100 else 2000 + anio
    try:
        return _tercer_viernes(anio, mes)
    except ValueError:
        return None


# ── Normal CDF ───────────────────────────────────────────────────────────────

def _ncdf(x) -> np.ndarray:
    """
    CDF de la normal estándar. Compatible con escalares float y arrays numpy.
    Usa math.erf (stdlib) a través de np.vectorize.
    """
    return np.vectorize(lambda v: 0.5 * (1.0 + math.erf(v / math.sqrt(2.0))))(
        np.asarray(x, dtype=float)
    )


# ── Modelo: gamma y delta con forward implícito ───────────────────────────────

def bs_gamma(S: float, K: float, T: float, sigma: float,
             r: float = R, x: float | None = None) -> float:
    """Gamma escalar (idéntica para CALL y PUT). x = ln(F/S); si es None, x = r·T."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    if x is None:
        x = r * T
    try:
        d1 = (np.log(S / K) + x + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
        return float(np.exp(x - r * T) * np.exp(-0.5 * d1**2)
                     / (np.sqrt(2 * np.pi) * S * sigma * np.sqrt(T)))
    except Exception:
        return 0.0


def bs_delta(S: float, K: float, T: float, sigma: float,
             tipo: str = "CALL", r: float = R, x: float | None = None) -> float:
    """Delta escalar. x = ln(F/S); si es None, x = r·T."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    if x is None:
        x = r * T
    try:
        d1  = (np.log(S / K) + x + 0.5 * sigma**2 * T) / (sigma * np.sqrt(T))
        nd1 = float(_ncdf(d1))
        df  = math.exp(x - r * T)
        return df * nd1 if tipo.upper() == "CALL" else df * (nd1 - 1.0)
    except Exception:
        return 0.0


def _bs_gamma_vec(S: float, K: np.ndarray, T: np.ndarray, sigma: np.ndarray,
                  x: np.ndarray, r: float = R) -> np.ndarray:
    """Gamma vectorizada con forward implícito por fila (x = ln(F/S))."""
    gamma = np.zeros(len(K))
    valid = (T > 0) & (sigma > 0) & (S > 0) & (K > 0)
    if not valid.any():
        return gamma
    Kv, Tv, sv, xv = K[valid], T[valid], sigma[valid], x[valid]
    d1 = (np.log(S / Kv) + xv + 0.5 * sv ** 2 * Tv) / (sv * np.sqrt(Tv))
    gamma[valid] = (np.exp(xv - r * Tv) * np.exp(-0.5 * d1 ** 2)
                    / (np.sqrt(2 * np.pi) * S * sv * np.sqrt(Tv)))
    return gamma


def _bs_delta_vec(S: float, K: np.ndarray, T: np.ndarray, sigma: np.ndarray,
                  tipos: np.ndarray, x: np.ndarray, r: float = R) -> np.ndarray:
    """Delta vectorizada con forward implícito por fila. tipos: 'CALL'/'PUT'."""
    delta = np.zeros(len(K))
    valid = (T > 0) & (sigma > 0) & (S > 0) & (K > 0)
    if not valid.any():
        return delta
    Kv, Tv, sv, xv = K[valid], T[valid], sigma[valid], x[valid]
    d1  = (np.log(S / Kv) + xv + 0.5 * sv**2 * Tv) / (sv * np.sqrt(Tv))
    nd1 = _ncdf(d1)
    dfac = np.exp(xv - r * Tv)
    is_call = tipos[valid] == "CALL"
    delta[valid] = dfac * np.where(is_call, nd1, nd1 - 1.0)
    return delta


# ── Multiplicador ─────────────────────────────────────────────────────────────

def get_multiplicador(accion: str) -> int:
    return 1 if "IBEX" in accion.upper() else 100


# ── Preparación del DataFrame ─────────────────────────────────────────────────

def _preparar(df_raw: pd.DataFrame, accion: str, hoy: date) -> pd.DataFrame:
    """Filtra y parsea el DataFrame para un subyacente dado."""
    df = df_raw[df_raw["accion"].str.upper() == accion.upper()].copy()
    if df.empty:
        return df

    df["tipo"]       = df["tipo"].str.upper().str.strip()
    df["strike_pts"] = df["strike"].apply(parse_es)
    df["oi"]         = df["posicion_abierta"].apply(parse_es)
    df["sigma"]      = df["volatilidad_cierre"].apply(parse_es) / 100
    df["spot_val"]   = df["spot"].apply(parse_es)
    df["delta_meff"] = (df["delta_cierre"].apply(parse_es)
                        if "delta_cierre" in df.columns else float("nan"))
    df["fv_date"]    = df["fecha_vencimiento"].apply(_parsear_vencimiento)
    df["T"]          = df["fv_date"].apply(
        lambda d: max((d - hoy).days, 0) / 365.0 if d is not None else float("nan")
    )

    mask = (
        (df["oi"] > 0)           &
        df["oi"].notna()          &
        df["strike_pts"].notna()  &
        df["sigma"].notna()       &
        (df["sigma"] > 0)         &
        (df["T"] > 0)             &
        df["tipo"].isin(["CALL", "PUT"])
    )
    return df[mask].copy()


# ── Arrastre implícito (ln F/S) por vencimiento ───────────────────────────────

def _ajustar_x(K, T, sigma, tipos, delta_meff, S0, r=R):
    """Ajusta x = ln(F/S) minimizando Σ (Δ_modelo − Δ_MEFF)². Devuelve (x, rmse)."""
    def err(x):
        d = _bs_delta_vec(S0, K, T, sigma, tipos, np.full(len(K), x), r)
        return float(np.mean((d - delta_meff) ** 2))

    # Rejilla gruesa (evita mínimos locales) + sección áurea alrededor del mejor punto
    rejilla = np.linspace(X_MIN, X_MAX, 111)
    errores = [err(v) for v in rejilla]
    i = int(np.argmin(errores))
    a = rejilla[max(i - 1, 0)]
    b = rejilla[min(i + 1, len(rejilla) - 1)]
    gr = (math.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc, fd = err(c), err(d)
    while b - a > 1e-6:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = err(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = err(d)
    x = (a + b) / 2
    return float(x), math.sqrt(err(x))


def _calcular_carry(df_raw: pd.DataFrame, accion: str, hoy: date, S0: float,
                    r: float = R) -> dict:
    """
    Arrastre implícito por vencimiento de un subyacente.

    Para el ajuste se usan TODAS las filas con delta MEFF y volatilidad (no solo
    las que tienen posición abierta), para tener más puntos.

    Devuelve {vencimiento: {"x", "T", "carry_anual", "fwd_spot", "n", "rmse", "fuente"}}
    con fuente = "ajuste" | "mediana subyacente" | "sin dividendos".
    """
    df = df_raw[df_raw["accion"].str.upper() == accion.upper()].copy()
    if df.empty:
        return {}
    df["tipo"]   = df["tipo"].str.upper().str.strip()
    df["K"]      = df["strike"].apply(parse_es)
    df["sigma"]  = df["volatilidad_cierre"].apply(parse_es) / 100
    df["dm"]     = (df["delta_cierre"].apply(parse_es)
                    if "delta_cierre" in df.columns else float("nan"))
    df["fv"]     = df["fecha_vencimiento"].apply(_parsear_vencimiento)
    df["T"]      = df["fv"].apply(
        lambda d: max((d - hoy).days, 0) / 365.0 if d is not None else float("nan")
    )

    carry = {}
    for vcto, g in df.groupby("fecha_vencimiento"):
        T_v = g["T"].dropna()
        if T_v.empty or T_v.iloc[0] <= 0:
            continue
        T0 = float(T_v.iloc[0])
        ok = (
            g["K"].notna() & g["sigma"].notna() & (g["sigma"] > 0) &
            g["dm"].notna() & g["tipo"].isin(["CALL", "PUT"]) &
            (g["dm"].abs() > DELTA_MIN_AJUSTE) & (g["dm"].abs() < 1 - DELTA_MIN_AJUSTE)
        )
        gg = g[ok]
        if len(gg) >= MIN_PUNTOS:
            x, rmse = _ajustar_x(gg["K"].values.astype(float), gg["T"].values.astype(float),
                                 gg["sigma"].values.astype(float), gg["tipo"].values,
                                 gg["dm"].values.astype(float), S0, r)
            # Si el ajuste queda pegado a un límite, no se fía de él
            if X_MIN + 1e-3 < x < X_MAX - 1e-3:
                carry[vcto] = {"x": x, "T": T0, "n": int(len(gg)),
                               "rmse": rmse, "fuente": "ajuste"}
                continue
        carry[vcto] = {"x": None, "T": T0, "n": int(len(gg)),
                       "rmse": None, "fuente": None}

    # Relleno de vencimientos sin ajuste válido
    anuales = [c["x"] / c["T"] for c in carry.values()
               if c["fuente"] == "ajuste" and c["T"] >= 0.1]
    mediana = float(np.median(anuales)) if anuales else None
    for c in carry.values():
        if c["fuente"] is None:
            if mediana is not None:
                c["x"], c["fuente"] = mediana * c["T"], "mediana subyacente"
            else:
                c["x"], c["fuente"] = r * c["T"], "sin dividendos"

    for c in carry.values():
        c["carry_anual"] = c["x"] / c["T"]
        c["fwd_spot"]    = math.exp(c["x"])
    return carry


def _asignar_x(df: pd.DataFrame, carry: dict, r: float = R) -> pd.DataFrame:
    """Añade la columna x (ln F/S) a cada fila según su vencimiento."""
    df = df.copy()
    df["x"] = [
        carry[v]["x"] if v in carry else r * t
        for v, t in zip(df["fecha_vencimiento"], df["T"])
    ]
    return df


def _preparar_con_carry(df_raw: pd.DataFrame, accion: str, hoy: date):
    """_preparar + spot + multiplicador + arrastre implícito. (df, S0, mult, carry)"""
    df = _preparar(df_raw, accion, hoy)
    if df.empty:
        return df, None, None, {}
    S0    = float(df["spot_val"].dropna().iloc[0])
    mult  = get_multiplicador(accion)
    carry = _calcular_carry(df_raw, accion, hoy, S0)
    df    = _asignar_x(df, carry)
    return df, S0, mult, carry


# ── GEX por fila y por strike ─────────────────────────────────────────────────

def _calcular_gex_filas(df: pd.DataFrame, S0: float, mult: int) -> pd.DataFrame:
    """Calcula gamma y GEX para cada fila (con el forward implícito de su vencimiento)."""
    df = df.copy()
    K     = df["strike_pts"].values.astype(float)
    T     = df["T"].values.astype(float)
    sigma = df["sigma"].values.astype(float)
    x     = df["x"].values.astype(float)
    signs = np.where(df["tipo"] == "CALL", 1.0, -1.0)

    df["gamma_bs"] = _bs_gamma_vec(S0, K, T, sigma, x)
    df["gex"]      = signs * df["oi"].values * df["gamma_bs"].values * S0 ** 2 * mult
    return df


def _agregar_por_strike(df: pd.DataFrame) -> pd.DataFrame:
    gs = (
        df.groupby(["strike_pts", "tipo"])["gex"]
        .sum()
        .unstack(fill_value=0)
        .rename(columns={"CALL": "gex_call", "PUT": "gex_put"})
    )
    for col in ("gex_call", "gex_put"):
        if col not in gs.columns:
            gs[col] = 0.0
    gs["gex_neto"] = gs["gex_call"] + gs["gex_put"]
    return gs.reset_index().sort_values("strike_pts").rename(
        columns={"strike_pts": "strike", "gex_call": "call_gex",
                 "gex_put": "put_gex", "gex_neto": "net_gex"}
    )


# ── Zero Gamma (barrido vectorizado) ─────────────────────────────────────────

def _calcular_zero_gamma(S0: float, df: pd.DataFrame, mult: int):
    """
    Busca el nivel de spot donde el GEX neto cruza cero mediante un barrido
    de N_SWEEP puntos en el rango S0 × (1 ± SWEEP_MARGIN). El forward de cada
    vencimiento se mueve proporcionalmente al spot (x fijo).

    Devuelve el precio interpolado en el cruce más cercano al spot actual,
    o None si no hay cruce en el rango.
    """
    K     = df["strike_pts"].values.astype(float)
    T     = df["T"].values.astype(float)
    sigma = df["sigma"].values.astype(float)
    oi    = df["oi"].values.astype(float)
    x     = df["x"].values.astype(float)
    signs = np.where(df["tipo"] == "CALL", 1.0, -1.0)

    spots = np.linspace(S0 * (1 - SWEEP_MARGIN), S0 * (1 + SWEEP_MARGIN), N_SWEEP)

    gex_s = np.array([
        float((signs * oi * _bs_gamma_vec(s, K, T, sigma, x) * s ** 2 * mult).sum())
        for s in spots
    ])

    cruces = np.where(np.diff(np.sign(gex_s)))[0]
    if not len(cruces):
        return None

    i = cruces[np.argmin(np.abs(spots[cruces] - S0))]
    x0, x1, y0, y1 = spots[i], spots[i + 1], gex_s[i], gex_s[i + 1]
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))


# ── DEX por fila y por strike ─────────────────────────────────────────────────

def _calcular_dex_filas(df: pd.DataFrame, S0: float, mult: int) -> pd.DataFrame:
    """
    Calcula la delta y el DEX de cada fila.
    Delta: la de cierre de MEFF si existe; si no, la del modelo con forward implícito.
    El signo de la delta ya incluye la dirección: Δ_call > 0, Δ_put < 0.
    """
    df    = df.copy()
    K     = df["strike_pts"].values.astype(float)
    T     = df["T"].values.astype(float)
    sigma = df["sigma"].values.astype(float)
    x     = df["x"].values.astype(float)
    tipos = df["tipo"].values

    d_modelo = _bs_delta_vec(S0, K, T, sigma, tipos, x)
    d_meff   = df["delta_meff"].values.astype(float)
    usa_meff = ~np.isnan(d_meff)
    df["delta_bs"]     = np.where(usa_meff, d_meff, d_modelo)
    df["delta_fuente"] = np.where(usa_meff, "MEFF", "modelo")
    df["dex"] = df["oi"].values * df["delta_bs"].values * S0 * mult
    return df


def _agregar_por_strike_dex(df: pd.DataFrame) -> pd.DataFrame:
    gs = (
        df.groupby(["strike_pts", "tipo"])["dex"]
        .sum()
        .unstack(fill_value=0)
        .rename(columns={"CALL": "dex_call", "PUT": "dex_put"})
    )
    for col in ("dex_call", "dex_put"):
        if col not in gs.columns:
            gs[col] = 0.0
    gs["dex_neto"] = gs["dex_call"] + gs["dex_put"]
    return gs.reset_index().sort_values("strike_pts").rename(
        columns={"strike_pts": "strike", "dex_call": "call_dex",
                 "dex_put": "put_dex", "dex_neto": "net_dex"}
    )


# ── Zero Delta (barrido vectorizado) ─────────────────────────────────────────

def _calcular_zero_delta(S0: float, df: pd.DataFrame, mult: int):
    """
    Busca el nivel de spot donde el DEX neto cruza cero mediante un barrido
    de N_SWEEP puntos en el rango S0 × (1 ± SWEEP_MARGIN), con la delta del
    modelo (forward implícito, x fijo). Devuelve None si no hay cruce.
    """
    K     = df["strike_pts"].values.astype(float)
    T     = df["T"].values.astype(float)
    sigma = df["sigma"].values.astype(float)
    oi    = df["oi"].values.astype(float)
    x     = df["x"].values.astype(float)
    tipos = df["tipo"].values

    spots = np.linspace(S0 * (1 - SWEEP_MARGIN), S0 * (1 + SWEEP_MARGIN), N_SWEEP)

    dex_s = np.array([
        float((oi * _bs_delta_vec(s, K, T, sigma, tipos, x) * s * mult).sum())
        for s in spots
    ])

    cruces = np.where(np.diff(np.sign(dex_s)))[0]
    if not len(cruces):
        return None

    i = cruces[np.argmin(np.abs(spots[cruces] - S0))]
    x0, x1, y0, y1 = spots[i], spots[i + 1], dex_s[i], dex_s[i + 1]
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))


# ── Lectura del CSV ───────────────────────────────────────────────────────────

def _leer_csv(csv_path: str) -> pd.DataFrame:
    df_raw = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", dtype=str)
    requeridas = {"accion", "tipo", "strike", "posicion_abierta",
                  "volatilidad_cierre", "spot", "fecha_vencimiento"}
    faltantes = requeridas - set(df_raw.columns)
    if faltantes:
        raise ValueError(
            f"El CSV no tiene las columnas necesarias: {sorted(faltantes)}\n"
            f"Asegúrate de correr meff_opciones.py antes de calcular GEX/DEX."
        )
    return df_raw


# ── Función pública: GEX ──────────────────────────────────────────────────────

def calcular_kpis(csv_path: str, accion: str = None,
                  hoy: date = None) -> dict:
    """
    Calcula KPIs de GEX desde el CSV de meff_opciones.py.

    Returns (si accion especificado):
        {
            "accion", "spot", "call_wall", "put_wall",
            "zero_gamma":     float | None,   # None si GEX no cruza cero en ±15%
            "gex_total", "regime" ("POSITIVO" | "NEGATIVO"), "multiplicador", "fecha",
            "gex_por_strike": pd.DataFrame,   # strike|call_gex|put_gex|net_gex
            "carry":          dict,           # arrastre implícito por vencimiento
        }

    Returns (si accion=None):
        { accion: kpis_dict, ... }  para todos los subyacentes del CSV
    """
    if hoy is None:
        hoy = date.today()
    df_raw = _leer_csv(csv_path)

    if accion is not None:
        return _kpis_accion(df_raw, accion, hoy)

    resultado = {}
    for ac in df_raw["accion"].dropna().unique():
        k = _kpis_accion(df_raw, ac, hoy)
        if k is not None:
            resultado[ac] = k
    return resultado


def _kpis_accion(df_raw: pd.DataFrame, accion: str, hoy: date) -> dict | None:
    df, S0, mult, carry = _preparar_con_carry(df_raw, accion, hoy)
    if df.empty:
        return None

    df  = _calcular_gex_filas(df, S0, mult)
    gs  = _agregar_por_strike(df)

    call_wall = float(gs.loc[gs["call_gex"].idxmax(), "strike"]) if not gs.empty else None
    put_wall  = float(gs.loc[gs["put_gex"].idxmin(),  "strike"]) if not gs.empty else None
    gex_total = float(df["gex"].sum())
    zero_gm   = _calcular_zero_gamma(S0, df, mult)
    regime    = "POSITIVO" if gex_total >= 0 else "NEGATIVO"

    fecha = hoy
    if "fecha_boletin" in df.columns:
        try:
            fb = df["fecha_boletin"].iloc[0]
            fecha = (datetime.strptime(fb, "%d/%m/%y").date()
                     if len(fb) <= 8 else datetime.strptime(fb, "%d/%m/%Y").date())
        except Exception:
            pass

    return {
        "accion":         accion,
        "spot":           S0,
        "call_wall":      call_wall,
        "put_wall":       put_wall,
        "zero_gamma":     zero_gm,
        "gex_total":      gex_total,
        "regime":         regime,
        "multiplicador":  mult,
        "fecha":          fecha,
        "gex_por_strike": gs,
        "carry":          carry,
    }


# ── Función pública: DEX ──────────────────────────────────────────────────────

def calcular_kpis_dex(csv_path: str, accion: str = None,
                      hoy: date = None) -> dict:
    """
    Calcula KPIs de DEX desde el CSV de meff_opciones.py.
    Misma interfaz que calcular_kpis() pero con delta en lugar de gamma.

    Returns (si accion especificado):
        {
            "accion", "spot", "call_wall", "put_wall",
            "zero_delta":     float | None,   # None si DEX no cruza cero en ±15%
            "dex_total", "regime" ("LONG" | "SHORT"), "multiplicador",
            "dex_por_strike": pd.DataFrame,   # strike|call_dex|put_dex|net_dex
            "pct_delta_meff": float,          # % de filas con delta MEFF
        }
    """
    if hoy is None:
        hoy = date.today()
    df_raw = _leer_csv(csv_path)

    if accion is not None:
        return _kpis_dex_accion(df_raw, accion, hoy)

    resultado = {}
    for ac in df_raw["accion"].dropna().unique():
        k = _kpis_dex_accion(df_raw, ac, hoy)
        if k is not None:
            resultado[ac] = k
    return resultado


def _kpis_dex_accion(df_raw: pd.DataFrame, accion: str, hoy: date) -> dict | None:
    df, S0, mult, carry = _preparar_con_carry(df_raw, accion, hoy)
    if df.empty:
        return None

    df  = _calcular_dex_filas(df, S0, mult)
    gs  = _agregar_por_strike_dex(df)

    call_wall = float(gs.loc[gs["call_dex"].idxmax(), "strike"]) if not gs.empty else None
    put_wall  = float(gs.loc[gs["put_dex"].idxmin(),  "strike"]) if not gs.empty else None
    dex_total = float(df["dex"].sum())
    zero_dt   = _calcular_zero_delta(S0, df, mult)
    regime    = "LONG" if dex_total >= 0 else "SHORT"

    return {
        "accion":         accion,
        "spot":           S0,
        "call_wall":      call_wall,
        "put_wall":       put_wall,
        "zero_delta":     zero_dt,
        "dex_total":      dex_total,
        "regime":         regime,
        "multiplicador":  mult,
        "dex_por_strike": gs,
        "pct_delta_meff": float((df["delta_fuente"] == "MEFF").mean()),
    }


# ── Función pública: GEX y DEX fila a fila (desglose por vencimiento) ─────────

def calcular_filas(df_raw: pd.DataFrame, hoy: date = None) -> pd.DataFrame:
    """
    GEX y DEX de cada fila (opción) de todos los subyacentes, con el mismo modelo
    que calcular_kpis / calcular_kpis_dex. Lo usa meff_opciones.py para el
    desglose por vencimiento del dashboard.

    Columnas: accion, tipo, fecha_vencimiento, strike, spot, gex, dex
    """
    if hoy is None:
        hoy = date.today()
    cols = ["accion", "tipo", "fecha_vencimiento", "strike", "spot", "gex", "dex"]
    frames = []
    for ac in df_raw["accion"].dropna().unique():
        df, S0, mult, _ = _preparar_con_carry(df_raw, ac, hoy)
        if df.empty:
            continue
        df = _calcular_gex_filas(df, S0, mult)
        df = _calcular_dex_filas(df, S0, mult)
        frames.append(pd.DataFrame({
            "accion":            df["accion"].str.strip().values,
            "tipo":              df["tipo"].values,
            "fecha_vencimiento": df["fecha_vencimiento"].str.strip().values,
            "strike":            df["strike_pts"].values,
            "spot":              S0,
            "gex":               np.round(df["gex"].values, 2),
            "dex":               np.round(df["dex"].values, 2),
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
