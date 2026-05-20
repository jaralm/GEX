# MEFF GEX Dashboard

> **No Queda Otra Opción** — Gamma Exposure sobre derivados españoles

Pipeline diario que descarga el boletín de opciones de [MEFF](https://www.meff.es), calcula el Gamma Exposure (GEX) de todos los subyacentes y sirve un dashboard interactivo con el perfil de gamma por strike.

---

## ¿Qué es el GEX y para qué sirve?

El **Gamma Exposure** mide la exposición agregada de los *market makers* (dealers) a la gamma de las opciones que tienen en su libro. Saber el signo y la distribución del GEX por strike permite anticipar comportamientos de precio:

| Régimen | Qué ocurre |
|---|---|
| **GEX positivo** (dealers *long gamma*) | Los dealers venden al subir y compran al bajar → el precio revierte, la volatilidad se amortigua |
| **GEX negativo** (dealers *short gamma*) | Los dealers compran al subir y venden al bajar → el precio se amplifica, la volatilidad aumenta |

Los niveles clave calculados son:

- **Call Wall** — strike con mayor GEX call (resistencia dinámica)
- **Put Wall** — strike con mayor GEX put en valor absoluto (soporte dinámico)
- **Zero Gamma** — nivel donde el GEX neto cruza cero (cambia el régimen)
- **Net GEX por strike** — perfil completo call GEX − |put GEX|

---

## Arquitectura

```
meff_opciones.py    →  scraping boletín MEFF → CSV diario + email
gex_calculator.py   →  librería GEX (Black-Scholes vectorizado)
meff_gex.py         →  orquestador → JSON para el dashboard
dashboard.html      →  frontend interactivo (Chart.js, sin servidor)
```

```
data/
├── meff_opciones_YYYYMMDD.csv      # opciones CALL/PUT del día
├── meff_top10_YYYYMMDD.txt         # top 10 por volumen
├── meff_mini_ibex_YYYYMMDD.txt     # top 5 MINI IBEX-35
├── meff_gex_YYYYMMDD.json          # GEX del día
└── meff_gex_latest.json            # siempre el más reciente (lee el dashboard)
```

---

## Instalación

**Requisitos:** Python 3, pip3, Mac o Linux.

```bash
# 1. Clonar el repositorio
git clone https://github.com/jaralm/gex.git
cd meff-gex

# 2. Instalar dependencias
pip3 install requests beautifulsoup4 pandas numpy
```

Para el envío de email (opcional), configurar estas variables de entorno:

```bash
export EMAIL_ORIGEN="tucuenta@gmail.com"
export EMAIL_DESTINO="destino@gmail.com"
export PASSWORD_APP="xxxx xxxx xxxx xxxx"   # contraseña de app Gmail
```

---

## Uso diario

```bash
# Paso 1 — Scraping del boletín MEFF + CSV + email
python3 meff_opciones.py

# Paso 2 — Cálculo GEX → JSON
python3 meff_gex.py

# Paso 3 — Abrir el dashboard en el navegador
python3 -m http.server 8080
# → http://localhost:8080/dashboard.html
```

`meff_gex.py` acepta fecha opcional si quieres reprocesar un día concreto:

```bash
python3 meff_gex.py 20260515
```

---

## Dashboard

El dashboard se sirve en local con el servidor HTTP de Python y no requiere ningún framework ni conexión a internet (salvo los CDN de Chart.js y Google Fonts).

**Pantalla 1 — GEX por strike (barras)**

Muestra el GEX call (verde) y put (rojo) por strike para el subyacente y vencimiento seleccionados, con líneas verticales de Spot, Call Wall, Put Wall y Zero Gamma.

**Pantalla 2 — Net GEX (línea)**

Muestra el GEX neto (`call GEX − |put GEX|`) para todos los vencimientos con sombreado verde cuando el régimen es positivo y rojo cuando es negativo. Marca los cruces de cero (Gamma Flip) y anota outliers que superan ±40 M.

---

## Modelo GEX

**Fórmula** (convenio SpotGamma):

```
GEX(K) = OI_call × Γ(K) × S² × mult  −  OI_put × Γ(K) × S² × mult
```

**Gamma Black-Scholes:**

```
d1 = [ ln(S/K) + (r + 0.5·σ²)·T ] / (σ·√T)
Γ  = exp(−0.5·d1²) / (√(2π) · S · σ · √T)
```

**Parámetros:**

| Parámetro | Valor | Descripción |
|---|---|---|
| `r` | 0.025 | Tasa libre de riesgo BCE |
| Multiplicador MINI IBEX-35 | 1 €/punto | |
| Multiplicador resto | 100 acciones/contrato | |
| Sweep Zero Gamma | ±15% del spot, 600 puntos | |

El cálculo de gamma está vectorizado con NumPy — el barrido completo tarda < 1 segundo.

---

## Subyacentes disponibles

Todos los publicados en el boletín diario de MEFF: MINI IBEX-35, IBEX-35, y opciones sobre acciones (Acciona, ACS, Aena, Amadeus, BBVA, CaixaBank, Cellnex, Enagás, Endesa, Ferrovial, Grifols, IAG, Iberdrola, Inditex, Mapfre, Naturgy, PharmaMar, Repsol, Sabadell, Santander, Solaria, Telefónica, y otros según el boletín del día).

---

## Integración con Google Sheets

Para leer los CSVs directamente desde GitHub en una hoja de cálculo:

```
=IFERROR(
  IMPORTDATA("https://raw.githubusercontent.com/jaralm/gex/main/data/"&A1&".csv";";");
  "Archivo no encontrado"
)
```

Donde `A1` contiene la fecha en formato `meff_opciones_YYYYMMDD`.

> **Nota:** requiere que el repositorio sea **público**. La caché de `IMPORTDATA` es de aproximadamente 1 hora.

---

## Estado del proyecto

- ✅ Scraping funcional y validado en producción
- ✅ GEX calculado para todos los subyacentes del boletín
- ✅ Dashboard operativo en local
- ✅ Email diario (Gmail SMTP)
- ✅ Zero Gamma implementado (puede ser `null` — resultado correcto si el GEX no cruza cero en ±15%)
- ✅ Pantalla Net GEX con perfil de línea y sombreado por régimen
- 🔲 GitHub Pages: pendiente
- 🔲 Automatización diaria (cron / GitHub Actions): pendiente

---

## Licencia

Uso personal. Los datos son propiedad de [MEFF — BME Derivatives](https://www.meff.es).

---

*joseantonio@noquedaotraopcion.com*
