"""
meff_opciones.py  —  Pipeline MEFF completo
--------------------------------------------
Ejecución única que genera TODOS los outputs del proyecto:

    python3 meff_opciones.py

Outputs:
    data/meff_opciones_YYYYMMDD.csv          ← datos brutos scrapeados
    data/meff_top10_YYYYMMDD.txt             ← top 10 volumen (consola + archivo)
    data/meff_mini_ibex_YYYYMMDD.txt         ← top 5 MINI IBEX (consola + archivo)
    ✉  Email con ambos informes (Gmail SMTP)

    data/meff_gex_YYYYMMDD.json              ← GEX + DEX con fecha (respaldo)
    data/meff_gex_latest.json                ← Tab GEX + Tab DEX dashboard
    data/meff_opciones_latest.json           ← Tab OPCIONES dashboard
    data/meff_volumen_historico.json         ← Tab HISTÓRICO dashboard
    data/meff_informes_latest.json           ← Tab TOP POSICIONES dashboard

Dependencias:
    pip3 install requests beautifulsoup4 pandas numpy
    gex_calculator.py  (librería matemática — debe estar en el mismo directorio)
"""

import re
import json
import math
import requests
import glob
import os
import numpy as np
import pandas as pd
import smtplib
from bs4 import BeautifulSoup, Tag
from datetime import datetime, date
from email.message import EmailMessage
from gex_calculator import calcular_kpis as _calcular_kpis, calcular_kpis_dex as _calcular_kpis_dex


# ── Configuración ──────────────────────────────────────────────────────────────

EMAIL_ORIGEN  = os.getenv("EMAIL_ORIGEN")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
PASSWORD_APP  = os.getenv("PASSWORD_APP")

CARPETA = "data"
os.makedirs(CARPETA, exist_ok=True)

TASA_LIBRE_RIESGO = 0.025   # BCE — igual que gex_calculator.py

URLS = {
    "lunes":     "https://www.meff.es/docs/Ficheros/boletin/esp/boletinpmon.htm",
    "martes":    "https://www.meff.es/docs/Ficheros/boletin/esp/boletinptue.htm",
    "miercoles": "https://www.meff.es/docs/Ficheros/boletin/esp/boletinpwed.htm",
    "jueves":    "https://www.meff.es/docs/Ficheros/boletin/esp/boletinpthu.htm",
    "viernes":   "https://www.meff.es/docs/Ficheros/boletin/esp/boletinpfri.htm",
}

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Multiplicadores para GEX/DEX por vencimiento
MULTIPLICADORES_GEX = {"MINI IBEX": 1}
MULTIPLICADOR_GEX_DEFAULT = 100

# Meses para parseo de vencimientos
MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}

_PAT_SEMANAL = re.compile(r"\bw\d+\b", re.IGNORECASE)


# ── Columnas CSV ───────────────────────────────────────────────────────────────

COLS_CSV = [
    "fecha_boletin", "accion", "tipo", "fecha_vencimiento",
    "strike", "spot", "volatilidad_cierre", "delta_cierre",
    "volumen_contratos", "posicion_abierta",
]

COLS_INFORME = [
    "fecha_boletin", "accion", "tipo", "fecha_vencimiento",
    "strike", "volumen_contratos", "posicion_abierta",
]


# ── Helpers generales ─────────────────────────────────────────────────────────

def mantener_ultimos_20():
    archivos = sorted(glob.glob(f"{CARPETA}/meff_opciones_*.csv"))
    if len(archivos) > 20:
        for f in archivos[:-20]:
            os.remove(f)


def vcto_sort_key(v):
    """Clave de ordenación para vencimientos tipo 'May-26'."""
    m = re.match(r"([A-Za-z]+)-(\d+)", str(v))
    if not m:
        return (9999, 0)
    mes_raw = m.group(1)[:3].lower()
    yr = int(m.group(2))
    yr_full = yr + 2000 if yr < 100 else yr
    return (yr_full, MESES.get(mes_raw, 0))


def a_float(v) -> float:
    """Convierte string numérico español/mixto a float."""
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if v in ("", "-", "\u2013", "\u2014", "N/A", "nan"):
        return float("nan")
    try:
        if "," in v:
            return float(v.replace(".", "").replace(",", "."))
        elif "." in v:
            partes = v.split(".")
            if len(partes) == 2 and len(partes[1]) == 3:
                return float(v.replace(".", ""))
            return float(v)
        return float(v)
    except ValueError:
        return float("nan")


def _safe_float(v):
    """Convierte NaN a None para serialización JSON válida."""
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def vol_a_numero(serie: pd.Series) -> pd.Series:
    """Convierte columna volumen_contratos (string) a float para ordenar."""
    return (
        serie
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
    )


# ── Email ──────────────────────────────────────────────────────────────────────

def enviar_email(texto):
    if not EMAIL_ORIGEN:
        return
    msg = EmailMessage()
    msg["Subject"] = f"MEFF - Informe {datetime.today().strftime('%d/%m/%Y')}"
    msg["From"]    = f"MEFF Alert <{EMAIL_ORIGEN}>"
    msg["To"]      = EMAIL_DESTINO
    msg.set_content(f"""
Hola,

Este es el informe diario de MEFF:

{texto}

Generado: {datetime.today().strftime('%d/%m/%Y %H:%M')}

Un saludo
""")
    msg.add_alternative(f"""
    <html>
      <body>
        <h3>Informe diario MEFF</h3>
        <pre style="font-family: monospace;">{texto}</pre>
        <p>Generado: {datetime.today().strftime('%d/%m/%Y %H:%M')}</p>
      </body>
    </html>
    """, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_ORIGEN, PASSWORD_APP)
        smtp.send_message(msg)


# ── Scraping: helpers HTML ─────────────────────────────────────────────────────

def fetch_page(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "iso-8859-1"
    return BeautifulSoup(r.text, "html.parser")


def limpiar(t):
    return re.sub(r"\s+", " ", t.strip().replace("\xa0", " "))


def es_vacio(v):
    return v.strip() in ("", "-", "\u2013", "\u2014", "N/A")


def separar_fecha_strike(celda):
    m = re.match(r"^(\d{0,2}-?[A-Za-z]{3}-\d{2,4})\s*([\d.,]*)$", celda)
    if m:
        return m.group(1), m.group(2)
    return celda, ""


# ── Extracción de spots ────────────────────────────────────────────────────────

_PAT_CIERRE_LABEL = re.compile(r"^Cierre\s+(?!anterior\b)(.+)$", re.IGNORECASE)
_PAT_SOLO_NUMERO  = re.compile(r"^[\d.,]+$")


def _nombre_sin_precio(texto: str) -> str:
    return re.sub(r"\s+[\d.,]+\s*$", "", texto).strip()


def _parse_precio(val_str: str):
    val_limpio = val_str.replace(".", "").replace(",", "")
    if not _PAT_SOLO_NUMERO.match(val_limpio):
        return None
    try:
        return float(val_str.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def extraer_spots(soup) -> dict:
    """
    Extrae precios de cierre del boletín MEFF.
    Estrategia 1: CSS classes 'cierrefila2' / 'cantidadfila2'.
    Estrategia 2: Fallback genérico si la 1 no devuelve nada.
    MINI IBEX-35 hereda el spot del IBEX-35 si no tiene propio.
    """
    spots: dict = {}

    for td in soup.find_all("td", class_="cierrefila2"):
        label = limpiar(td.get_text(" "))
        m = _PAT_CIERRE_LABEL.match(label)
        if not m:
            continue
        nombre = _nombre_sin_precio(limpiar(m.group(1)))
        if not nombre:
            continue
        td_val = td.find_next_sibling("td", class_="cantidadfila2")
        if not td_val:
            continue
        val = _parse_precio(limpiar(td_val.get_text(" ")))
        if val is not None:
            spots[nombre.upper()] = val

    if not spots:
        for td in soup.find_all("td"):
            label = limpiar(td.get_text(" "))
            m = _PAT_CIERRE_LABEL.match(label)
            if not m:
                continue
            nombre = _nombre_sin_precio(limpiar(m.group(1)))
            if not nombre:
                continue
            next_td = td.find_next_sibling("td")
            if not next_td:
                continue
            val = _parse_precio(limpiar(next_td.get_text(" ")))
            if val is not None:
                spots[nombre.upper()] = val

    if "MINI IBEX-35" not in spots:
        ibex_key = next((k for k in spots if "IBEX" in k and "MINI" not in k), None)
        if ibex_key:
            spots["MINI IBEX-35"] = spots[ibex_key]

    return spots


# ── Extracción de tablas ───────────────────────────────────────────────────────

def indices_columnas(headers):
    norm = [limpiar(h).upper() for h in headers]
    idx_vol = idx_oi = idx_vola = idx_delta = None
    for i, h in enumerate(norm):
        if "VOLUMEN"     in h: idx_vol   = i
        if "POSICI"      in h: idx_oi    = i
        if "VOLATILIDAD" in h: idx_vola  = i
        if "DELTA"       in h: idx_delta = i
    return idx_vol, idx_oi, idx_vola, idx_delta


def extraer_tabla(tabla: Tag, accion: str, tipo: str = None, spot=None):
    """
    Extrae filas de opciones de una tabla HTML de MEFF.
    CALL/PUT se detecta desde la primera fila de la propia tabla.
    Opciones semanales (fecha con w\\d+) se descartan.
    """
    filas = []
    rows = tabla.find_all("tr")
    if len(rows) < 2:
        return filas

    primera_texto = limpiar(rows[0].get_text(" ")).upper()
    if "CALL" in primera_texto:
        tipo_real = "CALL"
    elif "PUT" in primera_texto:
        tipo_real = "PUT"
    else:
        return filas

    headers = [limpiar(c.get_text(" ")) for c in rows[0].find_all(["th", "td"])]
    idx_vol, idx_oi, idx_vola, idx_delta = indices_columnas(headers)
    if idx_vol is None or idx_oi is None:
        return filas

    def celda(vals, idx):
        if idx is not None and idx < len(vals):
            v = vals[idx]
            return "" if es_vacio(v) else v
        return ""

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        vals  = [limpiar(c.get_text(" ")) for c in cells]
        if not vals or es_vacio(vals[0]):
            continue
        fecha, strike = separar_fecha_strike(vals[0])
        if _PAT_SEMANAL.search(fecha):
            continue
        vol   = celda(vals, idx_vol)
        oi    = celda(vals, idx_oi)
        vola  = celda(vals, idx_vola)
        delta = celda(vals, idx_delta)
        if es_vacio(vol) and es_vacio(oi):
            continue
        filas.append({
            "accion":             accion,
            "tipo":               tipo_real,
            "fecha_vencimiento":  fecha,
            "strike":             strike,
            "spot":               spot if spot is not None else "",
            "volatilidad_cierre": vola,
            "delta_cierre":       delta,
            "volumen_contratos":  vol,
            "posicion_abierta":   oi,
        })
    return filas


def scrapear(url):
    soup = fetch_page(url)

    fecha_boletin = ""
    for t in soup.stripped_strings:
        if "BOLET" in t.upper():
            m = re.search(r"(\d{2}/\d{2}/\d{2,4})", t)
            if m:
                fecha_boletin = m.group(1)
                break

    spots = extraer_spots(soup)
    todos = []
    PAT_CIERRE = re.compile(r"^Cierre\s+(?!anterior\b)(.+)$", re.IGNORECASE)
    accion_actual = None

    for elem in soup.find_all(["b", "strong", "p", "td", "th", "table"]):
        if elem.name == "table":
            if accion_actual:
                spot = spots.get(accion_actual.upper())
                todos.extend(extraer_tabla(elem, accion_actual, spot=spot))
            continue
        texto = limpiar(elem.get_text(" "))
        if not texto:
            continue
        m = PAT_CIERRE.match(texto)
        if m:
            nombre_raw = limpiar(m.group(1))
            accion_actual = _nombre_sin_precio(nombre_raw)
            continue

    df = pd.DataFrame(todos)
    df["fecha_boletin"] = fecha_boletin
    return df


# ── Informes TXT ───────────────────────────────────────────────────────────────

def construir_informe(titulo: str, df_subset: pd.DataFrame, n: int) -> str:
    df_v = df_subset[df_subset["volumen_contratos"] != ""].copy()
    df_v["_vol_num"] = vol_a_numero(df_v["volumen_contratos"])
    top = df_v.sort_values("_vol_num", ascending=False).head(n)
    top = top[[c for c in COLS_INFORME if c in top.columns]]
    if top.empty:
        return f"{titulo}\n(sin datos)\n"
    anchos = {c: max(len(c), top[c].astype(str).str.len().max()) for c in top.columns}
    sep = "  ".join("-" * anchos[c] for c in top.columns)
    cab = "  ".join(c.upper().ljust(anchos[c]) for c in top.columns)
    lineas = ["=" * len(sep), f"  {titulo}", "=" * len(sep), "", cab, sep]
    for _, row in top.iterrows():
        lineas.append("  ".join(str(row[c]).ljust(anchos[c]) for c in top.columns))
    lineas += [sep, ""]
    return "\n".join(lineas)


# ── GEX/DEX: funciones auxiliares (para desglose por vencimiento) ─────────────

def _norm_pdf(x: float) -> float:
    return float(np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi))


def tercer_viernes(anio: int, mes: int) -> date:
    d = date(anio, mes, 1)
    dias = (4 - d.weekday()) % 7
    return date(anio, mes, 1 + dias + 14)


def parsear_vencimiento(texto: str):
    m = re.match(r"([A-Za-z]+)-(\d{2,4})", str(texto).strip())
    if not m:
        return None
    mes_str  = m.group(1).lower()[:3]
    anio_str = m.group(2)
    mes = MESES.get(mes_str)
    if not mes:
        return None
    anio = int(anio_str) if len(anio_str) == 4 else 2000 + int(anio_str)
    try:
        return tercer_viernes(anio, mes)
    except ValueError:
        return None


def get_mult_gex(accion: str) -> int:
    accion_up = str(accion).upper()
    for clave, mult in MULTIPLICADORES_GEX.items():
        if clave in accion_up:
            return mult
    return MULTIPLICADOR_GEX_DEFAULT


def bs_gamma_escalar(S, K, T, iv, r) -> float:
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (np.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
        return float(_norm_pdf(d1) / (S * iv * np.sqrt(T)))
    except Exception:
        return 0.0


def calcular_gex_vcto(df_raw: pd.DataFrame, r: float = TASA_LIBRE_RIESGO) -> pd.DataFrame:
    """
    Calcula GEX fila a fila para generar el desglose por vencimiento.
    Necesario para el selector de vencimiento del Tab GEX (dashboard).
    """
    hoy = date.today()
    filas = []
    for _, row in df_raw.iterrows():
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

        dias = (fv_date - hoy).days
        T    = max(dias, 1) / 365.0
        iv   = iv_pct / 100.0
        gamma = bs_gamma_escalar(S, K, T, iv, r)
        mult  = get_mult_gex(accion)

        gex_bruto = gamma * oi * mult * S ** 2
        gex = gex_bruto if tipo == "CALL" else -gex_bruto

        filas.append({
            "accion":            accion,
            "tipo":              tipo,
            "fecha_vencimiento": fv_str,
            "strike":            K,
            "spot":              S,
            "gex":               round(gex, 2),
        })
    return pd.DataFrame(filas)


def agregar_gex_df(df_gex: pd.DataFrame):
    """Agrega GEX por strike+vencimiento y por strike (todos los vencimientos sumados)."""
    if df_gex.empty:
        cols = ["accion", "fecha_vencimiento", "strike", "spot", "call_gex", "put_gex", "net_gex"]
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=cols)

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


def calcular_dex_vcto(df_raw: pd.DataFrame, r: float = TASA_LIBRE_RIESGO) -> pd.DataFrame:
    """
    Calcula DEX fila a fila para generar el desglose por vencimiento.
    Análogo a calcular_gex_vcto() pero usando delta en lugar de gamma.
    Necesario para el selector de vencimiento del Tab DEX (dashboard).
    """
    hoy = date.today()
    filas = []
    for _, row in df_raw.iterrows():
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

        dias = (fv_date - hoy).days
        T    = max(dias, 1) / 365.0
        iv   = iv_pct / 100.0

        # Delta Black-Scholes escalar usando math.erf (stdlib, sin dependencias externas)
        try:
            d1  = (math.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
            nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        except Exception:
            continue

        delta = nd1 if tipo == "CALL" else nd1 - 1.0
        mult  = get_mult_gex(accion)
        dex   = delta * oi * mult * S

        filas.append({
            "accion":            accion,
            "tipo":              tipo,
            "fecha_vencimiento": fv_str,
            "strike":            K,
            "spot":              S,
            "dex":               round(dex, 2),
        })
    return pd.DataFrame(filas)


def agregar_dex_df(df_dex: pd.DataFrame):
    """Agrega DEX por strike+vencimiento y por strike (todos los vencimientos sumados)."""
    if df_dex.empty:
        cols = ["accion", "fecha_vencimiento", "strike", "spot", "call_dex", "put_dex", "net_dex"]
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=cols)

    def agg_grupo(g):
        return pd.Series({
            "spot":     g["spot"].iloc[0],
            "call_dex": round(g.loc[g["tipo"] == "CALL", "dex"].sum(), 2),
            "put_dex":  round(g.loc[g["tipo"] == "PUT",  "dex"].sum(), 2),
            "net_dex":  round(g["dex"].sum(), 2),
        })

    dex_por_strike_vcto = (
        df_dex
        .groupby(["accion", "fecha_vencimiento", "strike"], sort=False)
        .apply(agg_grupo, include_groups=False)
        .reset_index()
        .sort_values(["accion", "strike"])
    )
    dex_por_strike = (
        df_dex
        .groupby(["accion", "strike"], sort=False)
        .apply(agg_grupo, include_groups=False)
        .reset_index()
        .sort_values(["accion", "strike"])
    )
    return dex_por_strike_vcto, dex_por_strike


# ── Generador JSON Tab GEX + Tab DEX ─────────────────────────────────────────

def generar_json_gex(df_raw: pd.DataFrame, csv_path: str, fecha_boletin: str, hoy: str):
    """
    Genera meff_gex_latest.json (Tab GEX + Tab DEX del dashboard unificado).

    Secciones GEX:
      kpis_por_accion, gex_por_strike, gex_por_strike_vcto
    Secciones DEX (añadidas):
      kpis_dex_por_accion, dex_por_strike, dex_por_strike_vcto
    """
    print("\n── Calculando GEX (Tab GEX) ──────────────────────────────────")

    todos_kpis = _calcular_kpis(csv_path)
    if not todos_kpis:
        print("  Sin datos suficientes para GEX (volatilidad vacía en el CSV).")
        return

    for ac, k in sorted(todos_kpis.items()):
        zg = f"{k['zero_gamma']:,.1f}" if k["zero_gamma"] is not None else "n/a"
        print(f"  {ac:<28}  spot={k['spot']:>10,.2f}  GEX={k['gex_total']:>+15,.0f}  "
              f"regime={k['regime']}")
        print(f"  {'':28}  call_wall={k['call_wall']:>8,.0f}  "
              f"put_wall={k['put_wall']:>8,.0f}  zero_gamma={zg}")
        print()

    # gex_por_strike: todos los vencimientos sumados
    gps_frames = []
    for ac, k in todos_kpis.items():
        gs = k["gex_por_strike"].copy()
        gs["accion"] = ac
        gs["spot"]   = k["spot"]
        gps_frames.append(gs)
    gex_por_strike = (
        pd.concat(gps_frames, ignore_index=True) if gps_frames else pd.DataFrame()
    )

    # gex_por_strike_vcto: desglose por vencimiento
    df_gex = calcular_gex_vcto(df_raw)
    if not df_gex.empty:
        gex_por_strike_vcto, _ = agregar_gex_df(df_gex)
    else:
        gex_por_strike_vcto = pd.DataFrame()

    # ── DEX ───────────────────────────────────────────────────────────────────
    print("\n── Calculando DEX (Tab DEX) ──────────────────────────────────")

    todos_kpis_dex = _calcular_kpis_dex(csv_path)

    if todos_kpis_dex:
        for ac, k in sorted(todos_kpis_dex.items()):
            zd = f"{k['zero_delta']:,.1f}" if k["zero_delta"] is not None else "n/a"
            print(f"  {ac:<28}  spot={k['spot']:>10,.2f}  DEX={k['dex_total']:>+15,.0f}  "
                  f"regime={k['regime']}")
            print(f"  {'':28}  call_wall={k['call_wall']:>8,.0f}  "
                  f"put_wall={k['put_wall']:>8,.0f}  zero_delta={zd}")
            print()

        # dex_por_strike: todos los vencimientos sumados
        dps_frames = []
        for ac, k in todos_kpis_dex.items():
            gs = k["dex_por_strike"].copy()
            gs["accion"] = ac
            gs["spot"]   = k["spot"]
            dps_frames.append(gs)
        dex_por_strike = (
            pd.concat(dps_frames, ignore_index=True) if dps_frames else pd.DataFrame()
        )

        # dex_por_strike_vcto: desglose por vencimiento
        df_dex = calcular_dex_vcto(df_raw)
        if not df_dex.empty:
            dex_por_strike_vcto, _ = agregar_dex_df(df_dex)
        else:
            dex_por_strike_vcto = pd.DataFrame()

        kpis_dex_json = {
            ac: {
                "spot":       k["spot"],
                "call_wall":  k["call_wall"],
                "put_wall":   k["put_wall"],
                "zero_delta": k["zero_delta"],
                "dex_total":  k["dex_total"],
                "regime":     k["regime"],
            }
            for ac, k in todos_kpis_dex.items()
        }
    else:
        dex_por_strike     = pd.DataFrame()
        dex_por_strike_vcto = pd.DataFrame()
        kpis_dex_json      = {}
        print("  Sin datos suficientes para DEX.")

    # ── Metadatos comunes ─────────────────────────────────────────────────────
    subyacentes = sorted(todos_kpis.keys())
    vencimientos = {
        ac: sorted(
            [v for v in df_raw[df_raw["accion"] == ac]["fecha_vencimiento"].unique()
             if not _PAT_SEMANAL.search(str(v))],
            key=vcto_sort_key
        )
        for ac in subyacentes
    }

    kpis_json = {
        ac: {
            "spot":          k["spot"],
            "call_wall":     k["call_wall"],
            "put_wall":      k["put_wall"],
            "zero_gamma":    k["zero_gamma"],
            "gex_total":     k["gex_total"],
            "regime":        k["regime"],
            "multiplicador": k["multiplicador"],
        }
        for ac, k in todos_kpis.items()
    }

    def to_records(df):
        return json.loads(df.to_json(orient="records", force_ascii=False))

    resultado = {
        "meta": {
            "fecha_boletin":     fecha_boletin,
            "generado":          datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tasa_libre_riesgo": TASA_LIBRE_RIESGO,
            "nota_tasa":         "Tipo BCE. Revisar periodicamente.",
            "fuente":            "MEFF",
        },
        "subyacentes":          subyacentes,
        "vencimientos":         vencimientos,
        # ── GEX ──────────────────────────────────────────────────────────────
        "kpis_por_accion":      kpis_json,
        "gex_por_strike_vcto":  to_records(gex_por_strike_vcto) if not gex_por_strike_vcto.empty else [],
        "gex_por_strike":       to_records(gex_por_strike)      if not gex_por_strike.empty      else [],
        # ── DEX ──────────────────────────────────────────────────────────────
        "kpis_dex_por_accion":  kpis_dex_json,
        "dex_por_strike_vcto":  to_records(dex_por_strike_vcto) if not dex_por_strike_vcto.empty else [],
        "dex_por_strike":       to_records(dex_por_strike)      if not dex_por_strike.empty      else [],
    }

    nombre = f"{CARPETA}/meff_gex_{hoy}.json"
    with open(nombre, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"  JSON guardado: {nombre}")

    latest = f"{CARPETA}/meff_gex_latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"  JSON latest:   {latest}")


# ── Generador JSON Tab OPCIONES ───────────────────────────────────────────────

def generar_json_opciones(df_raw: pd.DataFrame, fecha_boletin: str, hoy: str):
    """
    Genera meff_opciones_latest.json (Tab OPCIONES del dashboard unificado).
    Contiene volumen y OI por subyacente/vencimiento/strike, con valores numéricos.
    """
    print("\n── Generando JSON Opciones (Tab OPCIONES) ────────────────────")

    subyacentes = sorted(df_raw["accion"].dropna().unique().tolist())
    vencimientos = {
        ac: sorted(
            [v for v in df_raw[df_raw["accion"] == ac]["fecha_vencimiento"].unique()
             if not _PAT_SEMANAL.search(str(v))],
            key=vcto_sort_key
        )
        for ac in subyacentes
    }

    datos = []
    for _, row in df_raw.iterrows():
        if _PAT_SEMANAL.search(str(row.get("fecha_vencimiento", ""))):
            continue
        vol_num = a_float(row.get("volumen_contratos", ""))
        oi_num  = a_float(row.get("posicion_abierta",  ""))
        if np.isnan(vol_num) and np.isnan(oi_num):
            continue
        datos.append({
            "accion":             str(row.get("accion", "")),
            "tipo":               str(row.get("tipo",   "")),
            "fecha_vencimiento":  str(row.get("fecha_vencimiento", "")),
            "strike":             _safe_float(a_float(row.get("strike", ""))),
            "spot":               _safe_float(a_float(row.get("spot",   ""))),
            "volatilidad_cierre": _safe_float(a_float(row.get("volatilidad_cierre", ""))),
            "delta_cierre":       _safe_float(a_float(row.get("delta_cierre", ""))),
            "volumen_contratos":  0.0 if np.isnan(vol_num) else float(vol_num),
            "posicion_abierta":   0.0 if np.isnan(oi_num)  else float(oi_num),
        })

    resultado = {
        "meta": {
            "fecha_boletin": fecha_boletin,
            "generado":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            "fuente":        "MEFF",
        },
        "subyacentes": subyacentes,
        "vencimientos": vencimientos,
        "datos": datos,
    }

    nombre = f"{CARPETA}/meff_opciones_latest.json"
    with open(nombre, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"  Opciones JSON guardado: {nombre}  ({len(datos)} filas)")


# ── Generador JSON Tab HISTÓRICO ──────────────────────────────────────────────

def construir_historico():
    """
    Lee todos los CSVs disponibles en data/ (hasta 20 días) y genera
    meff_volumen_historico.json (Tab HISTÓRICO del dashboard unificado).

    Al leer siempre de la misma carpeta data/, el histórico es automáticamente
    común a todos los dashboards y se enriquece cada día con el CSV nuevo.
    """
    print("\n── Construyendo histórico de volumen (Tab HISTÓRICO) ─────────")

    archivos = sorted(glob.glob(f"{CARPETA}/meff_opciones_*.csv"))
    if not archivos:
        print("  Sin CSVs disponibles para el histórico.")
        return

    frames = []
    for f in archivos:
        try:
            df_f = pd.read_csv(f, sep=";", encoding="utf-8-sig", dtype=str)
            frames.append(df_f)
        except Exception as e:
            print(f"  Error leyendo {f}: {e}")

    if not frames:
        print("  Sin datos leídos.")
        return

    df_todo = pd.concat(frames, ignore_index=True)

    # Filtrar opciones semanales
    df_todo = df_todo[
        ~df_todo["fecha_vencimiento"].fillna("").str.contains(r"\bw\d+\b", regex=True)
    ]

    df_todo["_vol_num"] = vol_a_numero(df_todo["volumen_contratos"]).fillna(0)
    df_todo["_oi_num"]  = vol_a_numero(df_todo["posicion_abierta"]).fillna(0)
    # Conservar filas con volumen O con OI (un strike puede tener OI sin haber cruzado hoy)
    df_todo = df_todo[(df_todo["_vol_num"] > 0) | (df_todo["_oi_num"] > 0)]

    agrupado = (
        df_todo
        .groupby(["fecha_boletin", "accion", "tipo", "fecha_vencimiento"])
        .agg(
            volumen_contratos=("_vol_num", "sum"),
            posicion_abierta =("_oi_num",  "sum"),
        )
        .reset_index()
    )

    acciones = sorted(agrupado["accion"].unique().tolist())
    vencimientos = {
        ac: sorted(
            agrupado[agrupado["accion"] == ac]["fecha_vencimiento"].unique().tolist(),
            key=vcto_sort_key
        )
        for ac in acciones
    }

    datos = [
        {
            "fecha_boletin":     str(row["fecha_boletin"]),
            "accion":            str(row["accion"]),
            "tipo":              str(row["tipo"]),
            "fecha_vencimiento": str(row["fecha_vencimiento"]),
            "volumen_contratos": round(float(row["volumen_contratos"]), 0),
            "posicion_abierta":  round(float(row["posicion_abierta"]),  0),
        }
        for _, row in agrupado.iterrows()
    ]

    num_dias = agrupado["fecha_boletin"].nunique()

    salida = {
        "ultima_actualizacion": datetime.today().strftime("%d/%m/%Y %H:%M"),
        "num_dias":             num_dias,
        "acciones":             acciones,
        "vencimientos":         vencimientos,
        "datos":                datos,
    }

    nombre_json = f"{CARPETA}/meff_volumen_historico.json"
    with open(nombre_json, "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=2)

    print(
        f"  Histórico guardado: {nombre_json}  "
        f"({len(datos)} registros · {num_dias} días · {len(archivos)} CSVs)"
    )


# ── Generador JSON Tab TOP POSICIONES ─────────────────────────────────────────
# FIX: esta función faltaba en meff_opciones.py y causaba que la pestaña
# "TOP POSICIONES" del dashboard mostrara siempre datos del día anterior.

def generar_json_informes(df: pd.DataFrame, txt_top10: str, txt_mini: str,
                           fecha_boletin: str, hoy: str):
    """
    Genera meff_informes_latest.json (Tab ◈ TOP POSICIONES del dashboard).

    Incluye el texto preformateado que ya se envía por email, guardado en JSON
    para que el dashboard lo muestre directamente en el <pre> de la pestaña.
    También incluye los datos estructurados para uso futuro.

    Args:
        df:             DataFrame scrapeado (strings, antes del CSV re-read).
        txt_top10:      Texto preformateado del informe top 10 (ya construido).
        txt_mini:       Texto preformateado del informe MINI IBEX (ya construido).
        fecha_boletin:  Fecha del boletín en formato dd/mm/yy o dd/mm/yyyy.
        hoy:            Fecha de hoy en formato YYYYMMDD.
    """
    print("\n── Generando JSON Informes (Tab ◈ TOP POSICIONES) ────────────")

    cols_informe = ["fecha_boletin", "accion", "tipo", "fecha_vencimiento",
                    "strike", "volumen_contratos", "posicion_abierta"]

    def top_n_data(df_subset: pd.DataFrame, n: int) -> list:
        """Devuelve los n registros con mayor volumen como lista de dicts."""
        df_v = df_subset[df_subset["volumen_contratos"] != ""].copy()
        df_v["_vol_num"] = vol_a_numero(df_v["volumen_contratos"])
        top = df_v.sort_values("_vol_num", ascending=False).head(n)
        resultado = []
        for _, row in top.iterrows():
            resultado.append({c: str(row.get(c, "")) for c in cols_informe if c in top.columns})
        return resultado

    top10_data = top_n_data(df, 10)

    mask_mini = df["accion"].str.upper().str.contains("MINI IBEX", na=False)
    df_mini   = df[mask_mini].copy()
    mini_data = top_n_data(df_mini, 5) if not df_mini.empty else []

    resultado = {
        "meta": {
            "fecha_boletin": fecha_boletin,
            "generado":      datetime.now().strftime("%d/%m/%Y %H:%M"),
        },
        "top10_text":     txt_top10,
        "mini_ibex_text": txt_mini,
        "top10_data":     top10_data,
        "mini_ibex_data": mini_data,
    }

    nombre = f"{CARPETA}/meff_informes_latest.json"
    with open(nombre, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"  Informes JSON guardado: {nombre}  "
          f"({len(top10_data)} top10 · {len(mini_data)} mini ibex)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    dia_semana = datetime.today().weekday()
    MAPA = {0: "viernes", 1: "lunes",  2: "martes",   3: "miercoles",
            4: "jueves",  5: "viernes", 6: "viernes"}
    dia = MAPA[dia_semana]
    url = URLS[dia]

    print(f"Scrapeando: {url}")
    df = scrapear(url)

    if df.empty:
        print("Sin datos.")
        return

    # ── Diagnóstico rápido ─────────────────────────────────────────────────────
    spots_encontrados = df[df["spot"] != ""][["accion", "spot"]].drop_duplicates()
    if not spots_encontrados.empty:
        print("Spots encontrados:")
        for _, r in spots_encontrados.iterrows():
            print(f"  {r['accion']}: {r['spot']}")
    else:
        print("AVISO: no se encontró ningún spot → GEX/DEX no calculable.")

    vola_no_vacia = df["volatilidad_cierre"].replace("", pd.NA).dropna()
    if vola_no_vacia.empty:
        print("AVISO: no se encontró 'volatilidad_cierre' en las tablas.")
    else:
        print(f"Volatilidad cierre: {len(vola_no_vacia)} filas con dato.")

    # ── CSV ────────────────────────────────────────────────────────────────────
    hoy = datetime.today().strftime("%Y%m%d")
    nombre_csv = f"{CARPETA}/meff_opciones_{hoy}.csv"
    cols_presentes = [c for c in COLS_CSV if c in df.columns]
    df[cols_presentes].to_csv(nombre_csv, index=False, sep=";", encoding="utf-8-sig")
    mantener_ultimos_20()
    print(f"CSV guardado: {nombre_csv}")

    fecha_boletin_val = df["fecha_boletin"].iloc[0] if not df.empty else hoy

    # ── Informe 1: Top 10 general ──────────────────────────────────────────────
    titulo_top10 = f"MEFF - TOP 10 VOLUMEN CONTRATOS  |  Boletin: {fecha_boletin_val}"
    txt_top10 = construir_informe(titulo_top10, df, n=10)
    txt_top10 += f"Generado: {datetime.today().strftime('%d/%m/%Y %H:%M')}\n"
    nombre_top10 = f"{CARPETA}/meff_top10_{hoy}.txt"
    with open(nombre_top10, "w", encoding="utf-8") as f:
        f.write(txt_top10)
    print(f"TXT top10 guardado: {nombre_top10}")
    print(txt_top10)

    # ── Informe 2: Top 5 MINI IBEX-35 ─────────────────────────────────────────
    mask_mini = df["accion"].str.upper().str.contains("MINI IBEX", na=False)
    df_mini = df[mask_mini].copy()
    txt_mini = ""
    if df_mini.empty:
        print("No se encontraron datos de MINI IBEX-35.")
    else:
        nombre_mini_act = df_mini["accion"].iloc[0]
        titulo_mini = (
            f"MEFF - TOP 5 {nombre_mini_act.upper()} (CALL+PUT)  |  Boletin: {fecha_boletin_val}"
        )
        txt_mini = construir_informe(titulo_mini, df_mini, n=5)
        txt_mini += f"Generado: {datetime.today().strftime('%d/%m/%Y %H:%M')}\n"
        nombre_txt_mini = f"{CARPETA}/meff_mini_ibex_{hoy}.txt"
        with open(nombre_txt_mini, "w", encoding="utf-8") as f:
            f.write(txt_mini)
        print(f"TXT MINI IBEX guardado: {nombre_txt_mini}")
        print(txt_mini)

    # ── Email ──────────────────────────────────────────────────────────────────
    contenido_email = txt_top10
    if txt_mini:
        contenido_email += "\n\n" + txt_mini
    enviar_email(contenido_email)

    # ── JSON Tab TOP POSICIONES ────────────────────────────────────────────────
    # (llamada al generador que faltaba — FIX del bug de fecha atrasada)
    generar_json_informes(df, txt_top10, txt_mini, fecha_boletin_val, hoy)

    # ── Lee el CSV recién guardado para pasarlo a los generadores JSON ─────────
    df_raw = pd.read_csv(nombre_csv, sep=";", encoding="utf-8-sig", dtype=str)

    # ── JSON Tab GEX + Tab DEX ────────────────────────────────────────────────
    generar_json_gex(df_raw, nombre_csv, fecha_boletin_val, hoy)

    # ── JSON Tab OPCIONES ──────────────────────────────────────────────────────
    generar_json_opciones(df_raw, fecha_boletin_val, hoy)

    # ── JSON Tab HISTÓRICO (últimos 20 CSVs) ──────────────────────────────────
    construir_historico()

    print("\n✓ Pipeline completo — CSV + TXT + email + JSONs generados (GEX + DEX + Opciones + Histórico + Informes).")


if __name__ == "__main__":
    main()
