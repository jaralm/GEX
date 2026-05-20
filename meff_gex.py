"""
meff_gex.py
-----------
Lee el CSV generado por meff_opciones.py y calcula el Gamma Exposure (GEX)
por strike y vencimiento.

Uso:
    python3 meff_gex.py            # usa el CSV mas reciente en data/
    python3 meff_gex.py 20260515   # usa un CSV especifico por fecha

Salida:
    data/meff_gex_YYYYMMDD.json   datos estructurados para el dashboard
"""

import re
import json
import glob
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, date
from gex_calculator import calcular_kpis as _calcular_kpis_accion

def _norm_pdf(x: float) -> float:
    """PDF de la normal estandar."""
    return float(np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi))


# ─────────────────────────────────────────────────────────────────────────────
# Parametros
# ─────────────────────────────────────────────────────────────────────────────
TASA_LIBRE_RIESGO = 0.024

CARPETA = "data"

MULTIPLICADORES = {
    "MINI IBEX": 1,
}
MULTIPLICADOR_DEFAULT = 100


# ─────────────────────────────────────────────────────────────────────────────
# Parseo de campos
# ─────────────────────────────────────────────────────────────────────────────

def a_float(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if v in ("", "-", "–", "—", "N/A", "nan"):
        return float("nan")
    try:
        if "," in v:
            return float(v.replace(".", "").replace(",", "."))
        elif "." in v:
            partes = v.split(".")
            if len(partes) == 2 and len(partes[1]) == 3:
                return float(v.replace(".", ""))
            else:
                return float(v)
        else:
            return float(v)
    except ValueError:
        return float("nan")


MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3,
    "abr": 4, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}


def tercer_viernes(anio: int, mes: int) -> date:
    d = date(anio, mes, 1)
    dias_hasta_primer_viernes = (4 - d.weekday()) % 7
    return date(anio, mes, 1 + dias_hasta_primer_viernes + 14)


def parsear_vencimiento(texto: str) -> date | None:
    m = re.match(r"([A-Za-zaeiouAEIOU]+)-(\d{2,4})", str(texto).strip())
    if not m:
        return None
    mes_str = m.group(1).lower()[:3]
    anio_str = m.group(2)
    mes = MESES.get(mes_str)
    if not mes:
        return None
    anio = int(anio_str) if len(anio_str) == 4 else 2000 + int(anio_str)
    try:
        return tercer_viernes(anio, mes)
    except ValueError:
        return None


def tiempo_a_vencimiento(fv_date: date, hoy: date) -> float:
    dias = (fv_date - hoy).days
    return max(dias, 1) / 365.0


def get_multiplicador(accion: str) -> int:
    accion_up = str(accion).upper()
    for clave, mult in MULTIPLICADORES.items():
        if clave in accion_up:
            return mult
    return MULTIPLICADOR_DEFAULT


# ─────────────────────────────────────────────────────────────────────────────
# Black-Scholes Gamma
# ─────────────────────────────────────────────────────────────────────────────

def bs_gamma(S: float, K: float, T: float, iv: float, r: float) -> float:
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (np.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * np.sqrt(T))
        return float(_norm_pdf(d1) / (S * iv * np.sqrt(T)))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Calculo GEX
# ─────────────────────────────────────────────────────────────────────────────

def calcular_gex(df: pd.DataFrame, r: float = TASA_LIBRE_RIESGO) -> pd.DataFrame:
    hoy = date.today()
    filas = []

    for _, row in df.iterrows():
        S      = a_float(row.get("spot", ""))
        K      = a_float(row.get("strike", ""))
        oi     = a_float(row.get("posicion_abierta", ""))
        iv_pct = a_float(row.get("volatilidad_cierre", ""))
        tipo   = str(row.get("tipo", "")).upper().strip()
        accion = str(row.get("accion", "")).strip()
        fv_str = str(row.get("fecha_vencimiento", "")).strip()

        if any(np.isnan(x) for x in [S, K, oi, iv_pct]):
            continue
        if oi <= 0 or S <= 0 or K <= 0 or iv_pct <= 0:
            continue
        if tipo not in ("CALL", "PUT"):
            continue

        fv_date = parsear_vencimiento(fv_str)
        if fv_date is None:
            continue

        T     = tiempo_a_vencimiento(fv_date, hoy)
        iv    = iv_pct / 100.0
        gamma = bs_gamma(S, K, T, iv, r)
        mult  = get_multiplicador(accion)

        gex_bruto = gamma * oi * mult * S ** 2
        gex = gex_bruto if tipo == "CALL" else -gex_bruto

        filas.append({
            "accion":            accion,
            "tipo":              tipo,
            "fecha_vencimiento": fv_str,
            "strike":            K,
            "spot":              S,
            "iv_pct":            round(iv_pct, 4),
            "T_anios":           round(T, 4),
            "gamma":             round(gamma, 8),
            "oi":                oi,
            "multiplicador":     mult,
            "gex":               round(gex, 2),
        })

    return pd.DataFrame(filas)


# ─────────────────────────────────────────────────────────────────────────────
# Agregacion
# ─────────────────────────────────────────────────────────────────────────────

def agregar_gex(df_gex: pd.DataFrame):
    if df_gex.empty:
        cols = ["accion", "fecha_vencimiento", "strike", "spot",
                "call_gex", "put_gex", "net_gex"]
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=cols[:-1] + ["net_gex"])

    def agg_grupo(g):
        return pd.Series({
            "spot":     g["spot"].iloc[0],
            "call_gex": round(g.loc[g["tipo"] == "CALL", "gex"].sum(), 2),
            "put_gex":  round(g.loc[g["tipo"] == "PUT",  "gex"].sum(), 2),
            "net_gex":  round(g["gex"].sum(), 2),
        })

    gex_por_strike_vcto = (
        df_gex
        .groupby(["accion", "fecha_vencimiento", "strike"], sort=False)
        .apply(agg_grupo, include_groups=False)
        .reset_index()
        .sort_values(["accion", "strike"])
    )

    gex_por_strike = (
        df_gex
        .groupby(["accion", "strike"], sort=False)
        .apply(agg_grupo, include_groups=False)
        .reset_index()
        .sort_values(["accion", "strike"])
    )

    return gex_por_strike_vcto, gex_por_strike


# ─────────────────────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────────────────────

def cargar_csv(fecha_str: str = None, return_path: bool = False):
    if fecha_str:
        path = f"{CARPETA}/meff_opciones_{fecha_str}.csv"
    else:
        archivos = sorted(glob.glob(f"{CARPETA}/meff_opciones_*.csv"))
        if not archivos:
            raise FileNotFoundError("No se encontro ningun CSV en data/")
        path = archivos[-1]
    print(f"Leyendo: {path}")
    if return_path:
        return path
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)


def guardar_json(todos_kpis, gex_por_strike_vcto, gex_por_strike,
                 fecha_boletin: str, hoy: str) -> str:
    def to_records(df):
        return json.loads(df.to_json(orient="records", force_ascii=False))

    subyacentes = sorted(todos_kpis.keys())
    MESES_ORD = {
        "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
        "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
    }

    def vcto_key(v):
        m = re.match(r"([A-Za-z]+)-(\d{2,4})", str(v))
        if not m:
            return (9999, 99)
        mes  = MESES_ORD.get(m.group(1).lower()[:3], 99)
        anio = int(m.group(2))
        anio = anio if anio > 100 else 2000 + anio
        return (anio, mes)

    df_raw_vcto = pd.read_csv(
        glob.glob(f"{CARPETA}/meff_opciones_*.csv")[-1],
        sep=";", encoding="utf-8-sig", dtype=str
    )
    # Excluir vencimientos semanales (contienen "wN") de la lista del selector
    _pat_semanal = re.compile(r"\bw\d+\b", re.IGNORECASE)
    vencimientos = {
        accion: sorted(
            [
                v for v in df_raw_vcto[df_raw_vcto["accion"] == accion]["fecha_vencimiento"].unique()
                if not _pat_semanal.search(str(v))
            ],
            key=vcto_key
        )
        for accion in subyacentes
    }

    kpis_json = {}
    for ac, k in todos_kpis.items():
        kpis_json[ac] = {
            "spot":          k["spot"],
            "call_wall":     k["call_wall"],
            "put_wall":      k["put_wall"],
            "zero_gamma":    k["zero_gamma"],
            "gex_total":     k["gex_total"],
            "regime":        k["regime"],
            "multiplicador": k["multiplicador"],
        }

    resultado = {
        "meta": {
            "fecha_boletin":     fecha_boletin,
            "generado":          datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tasa_libre_riesgo": TASA_LIBRE_RIESGO,
            "nota_tasa":         "Tipo BCE. Revisar periodicamente.",
            "fuente":            "MEFF",
        },
        "subyacentes":         subyacentes,
        "vencimientos":        vencimientos,
        "kpis_por_accion":     kpis_json,
        "gex_por_strike_vcto": to_records(gex_por_strike_vcto),
        "gex_por_strike":      to_records(gex_por_strike),
    }

    os.makedirs(CARPETA, exist_ok=True)
    nombre = f"{CARPETA}/meff_gex_{hoy}.json"
    with open(nombre, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"JSON guardado: {nombre}")

    latest = f"{CARPETA}/meff_gex_latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"JSON latest:   {latest}")
    return nombre


def imprimir_resumen(df_gex: pd.DataFrame, gex_por_strike: pd.DataFrame, n: int = 5):
    print()
    print("=" * 65)
    print("  GEX TOTAL POR SUBYACENTE")
    print("=" * 65)
    resumen = (df_gex.groupby("accion")["gex"]
               .sum()
               .sort_values(key=abs, ascending=False))
    for accion, gex_total in resumen.items():
        spot_val = df_gex[df_gex["accion"] == accion]["spot"].iloc[0]
        print(f"  {accion:<28}  spot={spot_val:>10,.2f}  GEX={gex_total:>15,.2f}")

    print()
    print(f"  TOP {n} STRIKES POR |GEX NETO| (agregado)")
    print("=" * 65)
    top = (gex_por_strike
           .assign(abs_net=lambda d: d["net_gex"].abs())
           .sort_values("abs_net", ascending=False)
           .head(n))
    for _, r in top.iterrows():
        print(f"  {r['accion']:<22} strike={r['strike']:>10,.2f}  "
              f"net_gex={r['net_gex']:>12,.2f}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostico de calidad de datos
# ─────────────────────────────────────────────────────────────────────────────

def diagnostico(df_raw: pd.DataFrame):
    print("=" * 65)
    print("  DIAGNOSTICO DE DATOS")
    print("=" * 65)
    print(f"  {'ACTIVO':<28}  {'FILAS':>5}  {'CON_VOLA':>8}  {'CON_SPOT':>8}")
    print("  " + "-" * 57)
    for ac in sorted(df_raw["accion"].dropna().unique()):
        sub = df_raw[df_raw["accion"] == ac]
        total = len(sub)
        con_vola = sub["volatilidad_cierre"].replace("", pd.NA).dropna().shape[0]
        con_spot = sub["spot"].replace("", pd.NA).dropna().shape[0]
        aviso = ""
        if con_vola == 0:
            aviso = " <- SIN VOLATILIDAD: zero_gamma no calculable"
        elif con_vola < total * 0.5:
            aviso = f" <- ATENCION: solo {con_vola}/{total} filas tienen volatilidad"
        print(f"  {ac:<28}  {total:>5}  {con_vola:>8}  {con_spot:>8}{aviso}")
    print("=" * 65)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main(fecha_str: str = None):
    csv_path = cargar_csv(fecha_str, return_path=True)
    df_raw   = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", dtype=str)

    fecha_boletin = (df_raw["fecha_boletin"].iloc[0]
                     if "fecha_boletin" in df_raw.columns else "")
    hoy = datetime.today().strftime("%Y%m%d")

    print(f"Filas en CSV : {len(df_raw)}")
    print(f"Subyacentes  : {sorted(df_raw['accion'].unique().tolist())}")
    print()

    # Diagnostico: cuantas filas tienen volatilidad y spot
    diagnostico(df_raw)

    # Calcular GEX
    todos_kpis = _calcular_kpis_accion(csv_path)

    if not todos_kpis:
        print("Sin datos suficientes para calcular GEX.")
        print("Causa probable: volatilidad_cierre vacia en el CSV.")
        print("Verifica que meff_opciones.py extrae la columna volatilidad del boletin.")
        return

    # Resumen en consola
    print("=" * 65)
    print("  GEX POR SUBYACENTE")
    print("=" * 65)
    for ac, k in sorted(todos_kpis.items()):
        if k["zero_gamma"] is not None:
            zg = f"{k['zero_gamma']:,.1f}"
        else:
            zg = "n/a"
        print(f"  {ac:<28}  spot={k['spot']:>10,.2f}  "
              f"GEX={k['gex_total']:>+15,.0f}  regimen={k['regime']}")
        print(f"  {'':28}  call_wall={k['call_wall']:>8,.0f}  "
              f"put_wall={k['put_wall']:>8,.0f}  zero_gamma={zg}")
        print()

    # Construir gex_por_strike
    gps_frames = []
    for ac, k in todos_kpis.items():
        gs = k["gex_por_strike"].copy()
        gs["accion"] = ac
        gs["spot"]   = k["spot"]
        gps_frames.append(gs)
    gex_por_strike = pd.concat(gps_frames, ignore_index=True) if gps_frames else pd.DataFrame()

    # gex_por_strike_vcto: desglose por vencimiento
    df_gex = calcular_gex(df_raw)
    if not df_gex.empty:
        gex_por_strike_vcto, _ = agregar_gex(df_gex)
    else:
        gex_por_strike_vcto = pd.DataFrame()

    guardar_json(todos_kpis, gex_por_strike_vcto, gex_por_strike,
                 fecha_boletin, hoy)
    print("Listo. JSON preparado para el dashboard.")


if __name__ == "__main__":
    fecha = sys.argv[1] if len(sys.argv) > 1 else None
    main(fecha)
