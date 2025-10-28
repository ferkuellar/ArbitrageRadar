# Simple Arbitrage Radar **PLUS** (Spot)

**Binance · Bybit · OKX · BingX — Solo lectura, NO ejecuta órdenes**

Escáner visual de **arbitraje inter-exchange** en **spot** que compara en tiempo real (pull periódico) el **mejor ASK (más barato)** y el **mejor BID (más caro)** entre cuatro CEX y te muestra, por cada par, **dónde comprar** y **dónde vender**.
Incluye **filtros de calidad por profundidad**, **umbral visual por bps**, **alertas** y **exportación a CSV**.

> **Propósito**: monitoreo/sondeo operativo y educativo. **No** envía órdenes; no requiere API keys.

---

## Características

* **4 exchanges soportados** (spot, públicos): **Binance, Bybit, OKX, BingX**.
* **Detección por par** del *spread* efectivo:

  * **BUY** = exchange con **mejor ASK** (precio más bajo).
  * **SELL** = exchange con **mejor BID** (precio más alto).
* **Filtro BUY≠SELL** (evita “oportunidades” dentro del mismo exchange).
* **Semáforo por bps** del *net spread* (después de fees + slippage modelados):

  * **Verde**: `net_bps > 0`
  * **Amarillo**: `-2 ≤ net_bps ≤ +2`
  * **Rojo**: `net_bps ≤ -2`
* **Profundidad mínima** (USD) exigida en **top level** (bid/ask) para ambos lados.
* **Alerta audible/visual** si `net_bps ≥ umbral`.
* **Exportación CSV** opcional (solo las filas mostradas).
* **UI en Tkinter**: ajustes desde la app, sin editar código.

---

## ¿Cómo funciona?

1. Para cada **símbolo** seleccionado, consulta el **order book** (límite 5 niveles) en cada exchange.
2. Extrae **mejor ASK** y **mejor BID**, junto con su **cantidad** y **profundidad** (precio×cantidad).
3. Selecciona:

   * **BUY_EX** = exchange con **ASK más bajo**
   * **SELL_EX** = exchange con **BID más alto**
4. Aplica filtros:

   * **BUY≠SELL** (opcional)
   * **MinDepth** USD tanto en el **ASK** (BUY) como en el **BID** (SELL)
5. Calcula:

   * `gross = (bid - ask) / ask`
   * `net = gross - fee_frac - slip_frac`
   * `pnl_est = notional * net` (estimado, solo para referencia)
6. Ordena por **net** descendente, pinta con el semáforo de bps y muestra en la tabla.

> **Notas**
>
> * El **fee** y el **slippage** se modelan por **bps totales** (buy+sell) a criterio del usuario; no consulta tu nivel VIP.
> * Las consultas son **HTTP** (no websockets). Respeta *rate limits* de `ccxt`.

---

## Requisitos

* **Python 3.9+**
* Librerías:

  ```bash
  pip install -U ccxt
  ```
* **Tkinter** viene con Python en Win/macOS. En Linux, si no aparece:

  ```bash
  sudo apt-get install python3-tk
  ```

---

## Instalación & Ejecución

1. Guarda el archivo (por ejemplo) como `radar_plus.py`.
2. Instala dependencias (arriba).
3. Ejecuta:

   ```bash
   python radar_plus.py
   ```
4. Se abrirá la **UI**. Configura parámetros y pulsa **Start**.

---

## UI — Controles principales

| Campo / Opción         | Descripción                                                                      | Rango/Consejo                |
| ---------------------- | -------------------------------------------------------------------------------- | ---------------------------- |
| **Símbolos**           | Lista separada por coma o espacio. Ej: `BTC/USDT, ETH/USDT, SOL/USDT`            | De 5 a 30 pares para empezar |
| **Interval (s)**       | Segundos entre escaneos.                                                         | 0.8 – 3.0 (inicia con ~1.2)  |
| **Top-N**              | Máximo de filas mostradas (ordenadas por `net`).                                 | 10 – 50                      |
| **Notional ($)**       | Monto de referencia para estimar `pnl_est` (no opera).                           | 50 – 1000 (solo referencia)  |
| **Fee total (bps)**    | Modelo de **fees totales** (buy+sell).                                           | 6 – 16 bps típicos           |
| **Slip (bps)**         | Modelo de **slippage total** (buy+sell).                                         | 2 – 10 bps                   |
| **Min Depth ($)**      | Profundidad mínima exigida en top level para **BUY** y **SELL**.                 | 200 – 2000 (según par)       |
| **BUY≠SELL**           | Si está activo, descarta rutas donde el mejor ASK y BID sean del mismo exchange. | Recomendado: **ON**          |
| **Beep alerta**        | Tono audible cuando `net_bps` ≥ umbral.                                          | Opcional                     |
| **Alerta NET ≥ (bps)** | Umbral de alerta.                                                                | 6 – 12 bps                   |
| **Export CSV**         | Activa exportación y elige ruta.                                                 | Opcional                     |

**Columnas de la tabla:**

* `SYMBOL` · `BUY_EX` · `ASK` · `ASK_DEPTH$` · `SELL_EX` · `BID` · `BID_DEPTH$` · `GROSS_BPS` · `NET_BPS` · `PNL($ est.)` · `TIME`

**Código de color (NET_BPS):**

* 🟩 **Verde**: `> 0`
* 🟨 **Amarillo**: `-2 … +2`
* 🟥 **Rojo**: `≤ -2`

---

## Exportación CSV

Si activas **Export CSV**, cada *refresh* guardará las filas visibles:

**Encabezado CSV**

```
ts, symbol, buy_ex, ask, ask_depth_usd, sell_ex, bid, bid_depth_usd, gross_bps, net_bps, pnl_est_usd
```

---

## 📈 Sugerencias de uso

* **Exploración**:

  * `Fee total (bps)` realista a tu perfil; `Slip (bps)` en 3–8.
  * `Min Depth ($)` más alto en pares *mid/low cap* para evitar “falsos positivos” por libros finos.
  * Revisa **color** y **consistencia** de las rutas top por varios ciclos.
* **Rendimiento**:

  * Empieza con 10–20 pares.
  * Aumentar demasiados pares + intervalos cortos puede toparse con *rate limits*.
* **Cobertura**:

  * No todos los pares existen en todos los exchanges; el radar toma el mejor ASK/BID entre los que responden.

---

## Troubleshooting

* **`DDoSProtection` / `RateLimitExceeded`** (ccxt):
  Sube `Interval (s)` o baja cantidad de símbolos.
* **`ExchangeError` / Libro vacío**:
  El par puede no existir en ese exchange o estar temporalmente restringido.
* **UI no abre en Linux**:
  Instala `python3-tk` (ver sección Requisitos).
* **Beep no suena** (macOS/Linux):
  Se usa un *terminal bell* de fallback; algunos terminales lo silencian por defecto.

---

## Privacidad & Seguridad

* **No** requiere ni lee API keys.
* **No** envía órdenes ni toca balances.
* Solo consume **datos públicos** de order books.

---

## Glosario rápido

* **bps** (*basis points*): 1 bps = 0.01%.

  * Ej.: 10 bps = 0.10%.
* **Gross**: `(BID − ASK) / ASK`.
* **Net**: `Gross − Fee − Slippage` (ambos modelados en bps).
* **MinDepth**: `precio × cantidad` del nivel 1 del libro (bid/ask) en USD.

---

## Roadmap (ideas)

* Soporte **WebSockets** para menor latencia.
* Peso por **profundidad agregada** (no solo top level).
* Listas de **símbolos por liquidez** pre-curadas por exchange.
* Persistencia ligera en SQLite + gráficas históricas.

---

## Contribución

* **Issues**: bugs, mejoras, compatibilidad de símbolos.
* **PRs**: bienvenidos (limpios, con docstring/comentarios).
* Estándar sugerido: `black` / `ruff` / tipado opcional `mypy` ligero.

---

## Licencia

Recomendado **MIT**. Incluye un archivo `LICENSE` en tu repositorio.

---

## ⚠️ Descargo

Este software es **informativo/educativo**. No constituye asesoría financiera. El trading con criptoactivos implica **alto riesgo**. Úsalo bajo tu responsabilidad.
