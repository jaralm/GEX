# GammaIbex · γ

**Exposición gamma y delta del mercado de opciones español — en tiempo real.**

🔗 **[gammaibex.noquedaotraopcion.com](https://gammaibex.noquedaotraopcion.com)**

---

## Qué es esto

GammaIbex aplica al mercado español de opciones la metodología de **Gamma Exposure (GEX)** y **Delta Exposure (DEX)** popularizada en EEUU por referencias como SpotGamma.

Hasta ahora, este tipo de análisis no existía para el IBEX-35 y sus subyacentes. Los datos provienen del boletín diario público de [MEFF](https://www.meff.es) (el mercado oficial de derivados financieros en España) y se actualizan automáticamente cada día hábil.

---

## Qué muestra el dashboard

### γ · GEX — Gamma Exposure por strike
Posicionamiento gamma neto de los dealers por nivel de precio. Identifica los strikes donde el mercado actúa como imán o repulsor.

- **GEX positivo** → dealers *long gamma* → venden en subidas, compran en caídas → volatilidad amortiguada
- **GEX negativo** → dealers *short gamma* → amplifican el movimiento → volatilidad elevada
- KPIs: Call Wall, Put Wall, Zero Gamma, régimen de mercado

### Δ · DEX — Delta Exposure por strike
Posicionamiento delta acumulado de los dealers. Mide el sesgo direccional del mercado de opciones.

- **DEX positivo** → dealers *long delta* → venden rallies (resistencia dinámica)
- **DEX negativo** → dealers *short delta* → compran caídas (soporte dinámico)
- KPIs: Zero Delta, Call Wall delta, Put Wall delta

### ◈ · Top Posiciones
Ranking de strikes por volumen de contratos y posición abierta. Identifica dónde está concentrado el interés del mercado.

### ◎ · Flujo y Posicionamiento
Histórico de volumen y open interest por subyacente, vencimiento y tipo (CALL/PUT) — hasta 20 días de datos.

---

## Subyacentes cubiertos

Todos los subyacentes incluidos en el boletín diario de MEFF: **IBEX-35**, **MINI IBEX-35** y opciones sobre acciones individuales del índice.

---

## Metodología

- **Modelo:** Black-Scholes para cálculo de gamma y delta implícitas
- **Inputs:** precio de cierre (spot), volatilidad implícita de cierre, strike, vencimiento, open interest
- **Multiplicador:** 100 acciones/contrato para acciones; 1 €/punto para IBEX y MINI IBEX
- **Convención GEX:** `OI_call × Γ × S² × mult − OI_put × Γ × S² × mult` (estándar SpotGamma)
- **Convención DEX:** `OI_call × Δ_call × S × mult + OI_put × Δ_put × S × mult`
- **Filtro:** opciones semanales excluidas del análisis (distorsionan el perfil de strikes mensuales)
- **Frecuencia:** actualización automática diaria (martes–sábado, tras publicación del boletín MEFF)

---

## Estructura del repositorio

```
├── meff_opciones.py          ← pipeline principal (scraping + cálculo + JSON)
├── gex_calculator.py         ← librería matemática GEX/DEX (Black-Scholes vectorizado)
├── meff_gex.py               ← script standalone para recálculo manual por fecha
├── index.html                ← dashboard (4 tabs, sin dependencias externas)
├── .github/workflows/
│   └── meff_daily.yml        ← automatización diaria (GitHub Actions)
└── data/
    ├── meff_opciones_YYYYMMDD.csv        ← datos brutos
    ├── meff_gex_latest.json              ← GEX + DEX (dashboard tabs γ y Δ)
    ├── meff_opciones_latest.json         ← top posiciones (dashboard tab ◈)
    └── meff_volumen_historico.json       ← histórico (dashboard tab ◎)
```

---

## Fuente de datos

Los datos provienen exclusivamente del **boletín diario público de MEFF** ([meff.es](https://www.meff.es)), de acceso libre. Este proyecto no redistribuye datos de pago ni accede a ninguna fuente privada.

---

## Aviso

Este dashboard es una herramienta de análisis de posicionamiento de mercado, no una recomendación de inversión. El GEX y el DEX son indicadores derivados de las posiciones públicas en opciones — no predicen movimientos de precio.

