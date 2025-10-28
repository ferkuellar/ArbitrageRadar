#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Arbitrage Radar PLUS (solo lectura, NO ejecuta órdenes)
Exchanges: Binance / Bybit / OKX / BingX
Muestra por par: dónde comprar más barato (mejor ASK) y dónde vender más caro (mejor BID).
Mejoras:
- Filtro BUY_EX != SELL_EX
- Umbral visual (verde >0, amarillo entre -2 y +2 bps, rojo <= -2 bps)
- Profundidad mínima USD en top level
- Alerta por NET (bps) con beep opcional
- Export CSV opcional de las filas mostradas
"""

import time
import threading
import queue
import os
import csv
from typing import Dict, List, Tuple, Optional

# --- deps ---
# pip install ccxt
import ccxt

# ==================== Config ====================
EXCHANGES = ["binance", "bybit", "okx", "bingx"]
DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "BNB/USDT", "TON/USDT", "LINK/USDT", "AVAX/USDT"
]

# ==================== Utils ====================
def bps_to_frac(bps: float) -> float:
    try:
        return float(bps) / 10000.0
    except Exception:
        return 0.0

def now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def fmt_pct_bps(x_frac: float, digits: int = 1) -> str:
    # muestra en bps
    try:
        return f"{x_frac * 10000:.{digits}f}"
    except Exception:
        return "-"

def fmt_num(x: float, digits: int = 6) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "-"

def do_beep():
    try:
        # Windows
        import winsound
        winsound.Beep(880, 160)
    except Exception:
        # Fallback cross-platform (terminal bell)
        print("\a", end="")

# ==================== Core Radar ====================
class RadarCore:
    def __init__(self, ex_ids: List[str]):
        self.ex_ids = ex_ids
        self.clients: Dict[str, ccxt.Exchange] = {}
        self._init_clients()

    def _init_clients(self):
        for ex in self.ex_ids:
            klass = getattr(ccxt, ex)
            self.clients[ex] = klass({
                "enableRateLimit": True,
            })

    def fetch_best_prices(self, symbol: str) -> Optional[dict]:
        """
        Devuelve:
        {
          "symbol": str,
          "best_buy": {"ex": str, "ask": float, "ask_qty": float, "ask_depth_usd": float},
          "best_sell":{"ex": str, "bid": float, "bid_qty": float, "bid_depth_usd": float}
        }
        o None si nadie respondió con libro válido.
        """
        best_buy = None
        best_sell = None

        for ex in self.ex_ids:
            cli = self.clients[ex]
            try:
                ob = cli.fetch_order_book(symbol, limit=5)
            except Exception:
                continue

            bids = ob.get("bids") or []
            asks = ob.get("asks") or []
            if not bids or not asks:
                continue

            bid_price, bid_qty = bids[0][0], bids[0][1]
            ask_price, ask_qty = asks[0][0], asks[0][1]
            ask_depth_usd = ask_price * ask_qty
            bid_depth_usd = bid_price * bid_qty

            # best ask (más barato)
            if (best_buy is None) or (ask_price < best_buy["ask"]):
                best_buy = {
                    "ex": ex,
                    "ask": ask_price,
                    "ask_qty": ask_qty,
                    "ask_depth_usd": ask_depth_usd,
                }
            # best bid (más caro)
            if (best_sell is None) or (bid_price > best_sell["bid"]):
                best_sell = {
                    "ex": ex,
                    "bid": bid_price,
                    "bid_qty": bid_qty,
                    "bid_depth_usd": bid_depth_usd,
                }

        if not best_buy or not best_sell:
            return None
        return {"symbol": symbol, "best_buy": best_buy, "best_sell": best_sell}

# ==================== Worker (hilo) ====================
class RadarWorker:
    def __init__(self, params: dict, out_q: "queue.Queue"):
        self.params = params
        self.out_q = out_q
        self.running = False
        self.thread = None
        self.core = RadarCore(EXCHANGES)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        p = self.params
        symbols: List[str] = p["symbols"]
        interval = float(p["interval"])
        fee_bps = float(p["fee_bps"])
        slip_bps = float(p["slip_bps"])
        notional = float(p["notional"])
        top_n = int(p["top_n"])
        diff_ex_only = bool(p["diff_ex_only"])
        min_depth_usd = float(p["min_depth_usd"])
        alert_bps = p.get("alert_bps", None)
        alert_beep = bool(p.get("alert_beep", False))
        export_csv = bool(p.get("export_csv", False))
        export_path = p.get("export_path", "").strip()

        fee_frac = bps_to_frac(fee_bps)
        slip_frac = bps_to_frac(slip_bps)

        # CSV header
        if export_csv and export_path:
            try:
                new_file = not os.path.isfile(export_path)
                with open(export_path, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new_file:
                        w.writerow(["ts","symbol","buy_ex","ask","ask_depth_usd",
                                    "sell_ex","bid","bid_depth_usd",
                                    "gross_bps","net_bps","pnl_est_usd"])
            except Exception as e:
                self.out_q.put({"type":"status", "msg": f"CSV error: {e}"})

        while self.running:
            rows = []
            for sym in symbols:
                try:
                    snap = self.core.fetch_best_prices(sym)
                except Exception as e:
                    snap = None
                if not snap:
                    continue

                buy = snap["best_buy"]; sell = snap["best_sell"]
                if diff_ex_only and (buy["ex"] == sell["ex"]):
                    continue

                # Profundidad mínima en ambos lados (top level)
                if buy["ask_depth_usd"] < min_depth_usd or sell["bid_depth_usd"] < min_depth_usd:
                    continue

                ask = float(buy["ask"])
                bid = float(sell["bid"])
                gross = (bid - ask) / ask
                net = gross - fee_frac - slip_frac
                pnl_est = notional * net

                rows.append({
                    "ts": now_ts(),
                    "symbol": sym,
                    "buy_ex": buy["ex"], "ask": ask, "ask_depth_usd": buy["ask_depth_usd"],
                    "sell_ex": sell["ex"], "bid": bid, "bid_depth_usd": sell["bid_depth_usd"],
                    "gross": gross, "net": net, "pnl": pnl_est
                })

            # ordenar por net desc
            rows.sort(key=lambda r: r["net"], reverse=True)
            if top_n > 0:
                rows = rows[:top_n]

            # alerta simple
            if alert_bps is not None:
                thr = float(alert_bps)
                if any((r["net"] * 10000.0) >= thr for r in rows):
                    self.out_q.put({"type": "status", "msg": f"ALERTA: NET >= {thr} bps"})
                    if alert_beep:
                        do_beep()

            # export CSV
            if export_csv and export_path and rows:
                try:
                    with open(export_path, "a", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        for r in rows:
                            w.writerow([
                                r["ts"], r["symbol"], r["buy_ex"],
                                f"{r['ask']:.8f}", f"{r['ask_depth_usd']:.2f}",
                                r["sell_ex"], f"{r['bid']:.8f}", f"{r['bid_depth_usd']:.2f}",
                                f"{r['gross']*10000:.1f}", f"{r['net']*10000:.1f}",
                                f"{r['pnl']:.4f}"
                            ])
                except Exception as e:
                    self.out_q.put({"type":"status", "msg": f"CSV error: {e}"})

            header = (f"Radar activo | Fee≈{fee_bps}bps, Slip≈{slip_bps}bps | "
                      f"MinDepth=${min_depth_usd:.0f} | TopN={top_n} | "
                      f"{len(rows)} rutas")
            self.out_q.put({"type": "rows", "header": header, "rows": rows})

            time.sleep(max(0.5, interval))

# ==================== UI (Tkinter) ====================
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

class RadarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simple Arbitrage Radar — PLUS (Spot)")
        self.geometry("1260x740")
        self.configure(bg="#111")

        self.out_q = queue.Queue()
        self.worker: Optional[RadarWorker] = None

        self._build_controls()
        self._build_table()
        self._poll_q()

    def _build_controls(self):
        frm = ttk.Frame(self)
        frm.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        # Fila 0
        ttk.Label(frm, text="Símbolos").grid(row=0, column=0, sticky="e")
        self.e_symbols = ttk.Entry(frm, width=60)
        self.e_symbols.insert(0, ", ".join(DEFAULT_SYMBOLS))
        self.e_symbols.grid(row=0, column=1, columnspan=4, sticky="we", padx=6)

        ttk.Label(frm, text="Interval (s)").grid(row=0, column=5, sticky="e")
        self.e_interval = ttk.Entry(frm, width=8)
        self.e_interval.insert(0, "1.2")
        self.e_interval.grid(row=0, column=6, padx=6)

        ttk.Label(frm, text="Top-N").grid(row=0, column=7, sticky="e")
        self.e_topn = ttk.Entry(frm, width=6)
        self.e_topn.insert(0, "20")
        self.e_topn.grid(row=0, column=8, padx=6)

        # Fila 1
        ttk.Label(frm, text="Notional ($)").grid(row=1, column=0, sticky="e")
        self.e_notional = ttk.Entry(frm, width=8)
        self.e_notional.insert(0, "200")
        self.e_notional.grid(row=1, column=1, padx=6)

        ttk.Label(frm, text="Fee total (bps)").grid(row=1, column=2, sticky="e")
        self.e_fee = ttk.Entry(frm, width=8)
        self.e_fee.insert(0, "11.0")
        self.e_fee.grid(row=1, column=3, padx=6)

        ttk.Label(frm, text="Slip (bps)").grid(row=1, column=4, sticky="e")
        self.e_slip = ttk.Entry(frm, width=8)
        self.e_slip.insert(0, "5.0")
        self.e_slip.grid(row=1, column=5, padx=6)

        ttk.Label(frm, text="Min Depth ($)").grid(row=1, column=6, sticky="e")
        self.e_mindepth = ttk.Entry(frm, width=10)
        self.e_mindepth.insert(0, "400")
        self.e_mindepth.grid(row=1, column=7, padx=6)

        # Fila 2 opciones
        self.var_diffex = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="BUY≠SELL", variable=self.var_diffex).grid(row=2, column=0, sticky="w")

        self.var_alert_beep = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Beep alerta", variable=self.var_alert_beep).grid(row=2, column=1, sticky="w")

        ttk.Label(frm, text="Alerta NET ≥ (bps)").grid(row=2, column=2, sticky="e")
        self.e_alert = ttk.Entry(frm, width=8)
        self.e_alert.insert(0, "8.0")
        self.e_alert.grid(row=2, column=3, padx=6)

        self.var_export = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Export CSV", variable=self.var_export).grid(row=2, column=4, sticky="w")

        self.e_export = ttk.Entry(frm, width=32)
        self.e_export.insert(0, "")
        self.e_export.grid(row=2, column=5, columnspan=2, sticky="we", padx=6)

        ttk.Button(frm, text="…", width=3, command=self._pick_csv).grid(row=2, column=7, sticky="w")

        # Fila 3 botones
        self.btn_start = ttk.Button(frm, text="▶ Start", command=self.start)
        self.btn_start.grid(row=3, column=6, padx=6, sticky="we")

        self.btn_stop  = ttk.Button(frm, text="■ Stop", command=self.stop)
        self.btn_stop.grid(row=3, column=7, padx=6, sticky="we")

        self.lbl_header = ttk.Label(self, text="Listo.", anchor="w")
        self.lbl_header.pack(fill=tk.X, padx=8, pady=4)

    def _pick_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV","*.csv"), ("All files","*.*")]
        )
        if path:
            self.e_export.delete(0, tk.END)
            self.e_export.insert(0, path)

    def _build_table(self):
        cols = ["symbol","buy_ex","ask","ask_depth","sell_ex","bid","bid_depth","gross_bps","net_bps","pnl_usd","ts"]
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=26)
        heads = {
            "symbol":"SYMBOL","buy_ex":"BUY_EX","ask":"ASK","ask_depth":"ASK_DEPTH$",
            "sell_ex":"SELL_EX","bid":"BID","bid_depth":"BID_DEPTH$",
            "gross_bps":"GROSS_BPS","net_bps":"NET_BPS","pnl_usd":"PNL($ est.)","ts":"TIME"
        }
        widths = {
            "symbol":110,"buy_ex":90,"ask":110,"ask_depth":110,
            "sell_ex":90,"bid":110,"bid_depth":110,
            "gross_bps":90,"net_bps":90,"pnl_usd":110,"ts":130
        }
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # colores
        self.tree.tag_configure("pos", background="#0f3d0f", foreground="#e8ffe8")   # verde
        self.tree.tag_configure("mid", background="#3d3d0f", foreground="#fff3c2")   # amarillo
        self.tree.tag_configure("neg", background="#3d0f0f", foreground="#ffe8e8")   # rojo

    def _poll_q(self):
        try:
            while True:
                item = self.out_q.get_nowait()
                t = item.get("type")
                if t == "rows":
                    self.lbl_header.config(text=item.get("header",""))
                    self._update_rows(item.get("rows", []))
                elif t == "status":
                    self.lbl_header.config(text=item.get("msg",""))
        except queue.Empty:
            pass
        self.after(150, self._poll_q)

    def _parse_symbols(self, s: str) -> List[str]:
        s = (s or "").replace("\n"," ").replace(",", " ")
        parts = [p.strip().upper() for p in s.split() if p.strip()]
        return parts if parts else DEFAULT_SYMBOLS

    def _collect_params(self) -> dict:
        symbols = self._parse_symbols(self.e_symbols.get())
        return {
            "symbols": symbols,
            "interval": float(self.e_interval.get() or 1.2),
            "notional": float(self.e_notional.get() or 200.0),
            "fee_bps": float(self.e_fee.get() or 11.0),
            "slip_bps": float(self.e_slip.get() or 5.0),
            "top_n": int(self.e_topn.get() or 20),
            "diff_ex_only": bool(self.var_diffex.get()),
            "min_depth_usd": float(self.e_mindepth.get() or 400.0),
            "alert_bps": float(self.e_alert.get()) if self.e_alert.get().strip() != "" else None,
            "alert_beep": bool(self.var_alert_beep.get()),
            "export_csv": bool(self.var_export.get()),
            "export_path": self.e_export.get().strip(),
        }

    def start(self):
        if self.worker and self.worker.running:
            messagebox.showinfo("Info", "El radar ya está corriendo.")
            return
        try:
            p = self._collect_params()
        except Exception as e:
            messagebox.showerror("Error", f"Parámetros inválidos: {e}")
            return
        self.worker = RadarWorker(p, self.out_q)
        self.worker.start()
        self.lbl_header.config(text="Escaneando...")

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
            self.lbl_header.config(text="Detenido.")
        # limpiar tabla? opcional
        # for i in self.tree.get_children():
        #     self.tree.delete(i)

    def _update_rows(self, rows: List[Dict]):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            net_bps = r["net"] * 10000.0
            # color: verde >0, amarillo entre -2..+2, rojo <= -2
            if net_bps > 0.0:
                tag = "pos"
            elif -2.0 <= net_bps <= 2.0:
                tag = "mid"
            else:
                tag = "neg"

            vals = [
                r["symbol"],
                r["buy_ex"], fmt_num(r["ask"], 8), fmt_num(r["ask_depth_usd"], 2),
                r["sell_ex"], fmt_num(r["bid"], 8), fmt_num(r["bid_depth_usd"], 2),
                fmt_pct_bps(r["gross"], 1),
                fmt_pct_bps(r["net"], 1),
                fmt_num(r["pnl"], 4),
                r["ts"]
            ]
            self.tree.insert("", tk.END, values=vals, tags=(tag,))

if __name__ == "__main__":
    app = RadarApp()
    app.mainloop()
