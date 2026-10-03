GammaIbex · γ

Exposición gamma y delta del mercado de opciones español — en tiempo real.

🔗 gammaibex.noquedaotraopcion.com

Qué es esto

GammaIbex aplica al mercado español de opciones la metodología de Gamma Exposure (GEX) y Delta Exposure (DEX) popularizada en EEUU por referencias como SpotGamma.

Hasta ahora, este tipo de análisis no existía para el IBEX-35 y sus subyacentes. Los datos provienen del boletín diario público de MEFF (el mercado oficial de derivados financieros en España) y se actualizan automáticamente cada día hábil.

Qué muestra el dashboard

El dashboard tiene 6 pestañas:

γ · GEX — Gamma Exposure por strike

Posicionamiento gamma neto de los dealers por nivel de precio. Identifica los strikes donde el mercado actúa como imán o repulsor.

GEX positivo → dealers long gamma → venden en subidas, compran en caídas → volatilidad amortiguada
GEX negativo → dealers short gamma → amplifican el movimiento → volatilidad elevada
KPIs: Call Wall, Put Wall, Zero Gamma, régimen de mercado
Δ · DEX — Delta Exposure por strike

Posicionamiento delta acumulado de los dealers. Mide el sesgo direccional del mercado de opciones.

DEX positivo → dealers long delta → venden rallies (resistencia dinámica)
DEX negativo → dealers short delta → compran caídas (soporte dinámico)
KPIs: Zero Delta, Call Wall delta, Put Wall delta
◈ · Top Posiciones

Ranking de strikes por volumen de contratos y posición abierta — top 10 general y top 5 de MINI IBEX-35. Identifica dónde está concentrado el interés del mercado.

Incluye un selector de fecha: por defecto muestra el informe del día, pero se puede consultar cualquiera de los últimos ~20 días hábiles.

◎ · Flujo y Posicionamiento

Histórico de volumen y open interest por subyacente, vencimiento y tipo (CALL/PUT) — hasta 20 días de datos. Métrica conmutable entre Volumen y OI.

▥ · Tabla OI

Tabla de open interest: en filas los subyacentes, en columnas los últimos 20 boletines. Selectores de vencimiento y tipo de opción, y un toggle para ver el valor absoluto o la variación de OI respecto al boletín anterior.

≡ · Glosario

8 entradas explicando GEX, DEX, Call Wall, Put Wall, Zero Gamma y los conceptos clave del dashboard — pensado para quien llega sin experiencia previa en este tipo de análisis.

Subyacentes cubiertos

Todos los subyacentes incluidos en el boletín diario de MEFF: IBEX-35, MINI IBEX-35 y opciones sobre acciones individuales del índice.

Metodología
Modelo: Black-Scholes para cálculo de gamma y delta implícitas
Inputs: precio de cierre (spot), volatilidad implícita de cierre, strike, vencimiento, open interest
Multiplicador: 100 acciones/contrato para acciones; 1 €/punto para IBEX y MINI IBEX
Convención GEX: OI_call × Γ × S² × mult − OI_put × Γ × S² × mult (estándar SpotGamma)
Convención DEX: OI_call × Δ_call × S × mult + OI_put × Δ_put × S × mult
Filtro: opciones semanales excluidas del análisis (distorsionan el perfil de strikes mensuales)
Frecuencia: actualización automática diaria (martes–sábado, tras publicación del boletín MEFF)
Estructura del repositorio
├── meff_opciones.py          ← pipeline principal (scraping + cálculo + JSON)
├── gex_calculator.py         ← librería matemática GEX/DEX (Black-Scholes vectorizado)
├── meff_gex.py               ← wrapper de compatibilidad (recálculo manual)
├── run_meff_daily.py         ← entrypoint para GitHub Actions
├── index.html                ← dashboard (6 tabs; Chart.js y Google Fonts por CDN)
├── .github/workflows/
│   └── meff_daily.yml        ← automatización diaria (GitHub Actions)
└── data/
    ├── meff_opciones_YYYYMMDD.csv        ← datos brutos (se conservan los últimos 20 días)
    ├── meff_top10_YYYYMMDD.txt           ← informe top 10 diario (histórico completo, sin podar)
    ├── meff_mini_ibex_YYYYMMDD.txt       ← informe MINI IBEX-35 diario (idem)
    ├── meff_gex_latest.json              ← GEX + DEX del día (dashboard tabs γ y Δ)
    ├── meff_opciones_latest.json         ← posiciones del día (dashboard tab ◈)
    ├── meff_informes_latest.json         ← informes del día en JSON (dashboard tab ◈)
    └── meff_volumen_historico.json       ← histórico volumen/OI, 20 días (dashboard tabs ◎ y ▥)
Fuente de datos

Los datos provienen exclusivamente del boletín diario público de MEFF (meff.es), de acceso libre. Este proyecto no redistribuye datos de pago ni accede a ninguna fuente privada.

Aviso

Este dashboard es una herramienta de análisis de posicionamiento de mercado, no una recomendación de inversión. El GEX y el DEX son indicadores derivados de las posiciones públicas en opciones — no predicen movimientos de precio.

