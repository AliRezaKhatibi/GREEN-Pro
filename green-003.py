# green_app_pro.py
# -*- coding: utf-8 -*-
"""
GREEN (Pro) — Data Health + Cleaning + Compare + Report
Single-file, runnable Tkinter desktop app.

What changed vs your current version (implemented here):
- Product focus: Data Health / Cleaning / Compare / Reporting
- Audio tab removed; optional notification beep only (no pygame dependency)
- Non-blocking UI: heavy tasks run in background thread + progress overlay
- Column picker plots: X/Y selection + histogram/boxplot/scatter/line
- Cleaning pipeline with preview + save cleaned.csv
- Compare two CSVs (schema + stats drift + missingness drift)
- Export professional HTML report (no external web calls)
- Robust CSV loading (encoding fallbacks, delimiter sniffing)

Brand requirements:
- Uses your name: GREEN
- Uses your logo: logo.png (place next to this script)

Dependencies:
- Python 3.9+
- pip install pandas matplotlib

Run:
- Put logo.png beside this file
- python green_app_pro.py
"""

from __future__ import annotations

import os
import io
import csv
import json
import time
import base64
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

import tkinter as tk
from tkinter import filedialog as fd
from tkinter import messagebox

import pandas as pd
from pandas.plotting import scatter_matrix


import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# -----------------------------
# Config / Theme (pure Tk)
# -----------------------------

@dataclass(frozen=True)
class AppConfig:
    title: str = "GREEN"
    version: str = "v0.1.0 (Initial Release)"
    author: str = "GREEN Team"

    width: int = 1600
    height: int = 980
    resizable: bool = True

    logo_path: str = "logo.png"  # must be next to this script
    splash_w: int = 920
    splash_h: int = 600

    # Theme
    bg_app: str = "#0B1220"
    bg_panel: str = "#0F172A"
    bg_card: str = "#0A1326"
    fg_text: str = "#E5E7EB"
    fg_muted: str = "#9CA3AF"
    border: str = "#1F2A44"
    accent: str = "#22C55E"
    accent2: str = "#38BDF8"
    danger: str = "#EF4444"
    warn: str = "#F59E0B"

    font: str = "Segoe UI"
    font_mono: str = "Consolas"


# -----------------------------
# Utilities
# -----------------------------

def _center_window(win: tk.Toplevel | tk.Tk, w: int, h: int):
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = int((sw - w) / 2)
    y = int((sh - h) / 2)
    win.geometry(f"{w}x{h}+{x}+{y}")

def _try_load_logo(path: str) -> Optional[tk.PhotoImage]:
    if not os.path.exists(path):
        return None
    try:
        img = tk.PhotoImage(file=path)
        # keep reasonable size
        if img.width() > 220 or img.height() > 220:
            fx = max(1, int(img.width() / 160))
            fy = max(1, int(img.height() / 160))
            img = img.subsample(fx, fy)
        return img
    except Exception:
        return None

def _beep():
    # Cross-platform-ish: Tk bell (no extra deps)
    try:
        root = tk._default_root
        if root is not None:
            root.bell()
    except Exception:
        pass

def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        return dialect.delimiter
    except Exception:
        return ","

def _read_csv_robust(path: str) -> pd.DataFrame:
    # Robust read with encoding fallback + delimiter sniff
    raw = None
    for enc in ("utf-8", "utf-8-sig", "cp1256", "cp1252", "latin1"):
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                raw = f.read(20000)

            delimiter = _sniff_delimiter(raw)

            # NOTE:
            # low_memory is NOT supported when engine="python"
            return pd.read_csv(
                path,
                encoding=enc,
                sep=delimiter,
                engine="python",
            )
        except Exception:
            continue

    # last resort (still avoid low_memory with engine="python")
    try:
        return pd.read_csv(path, sep=",", engine="python", encoding_errors="ignore")
    except Exception:
        # ultimate fallback: let pandas decide
        return pd.read_csv(path)


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

def _mad_based_zscore(x: pd.Series) -> pd.Series:
    x = x.astype("float64")
    med = x.median()
    mad = (x - med).abs().median()
    if mad == 0 or pd.isna(mad):
        return pd.Series([0.0] * len(x), index=x.index)
    return 0.6745 * (x - med) / mad

def _winsorize_series(s: pd.Series, p: float = 0.01) -> pd.Series:
    # winsorize by quantiles (no scipy dependency)
    x = s.copy()
    lo = x.quantile(p)
    hi = x.quantile(1 - p)
    return x.clip(lower=lo, upper=hi)

def _format_pct(x: float) -> str:
    return f"{x*100:.2f}%"

def _escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# -----------------------------
# Data State + Controllers
# -----------------------------

@dataclass
class DataState:
    file_a: Optional[str] = None
    file_b: Optional[str] = None

    df_a: Optional[pd.DataFrame] = None
    df_b: Optional[pd.DataFrame] = None

    df_view: Optional[pd.DataFrame] = None  # current active dataset
    df_clean: Optional[pd.DataFrame] = None

    report_last: Optional[Dict[str, Any]] = None

    @property
    def has_data(self) -> bool:
        return self.df_view is not None and not self.df_view.empty


class DataController:
    def __init__(self, state: DataState):
        self.state = state

    def load_a(self, path: str) -> pd.DataFrame:
        df = _read_csv_robust(path)
        self.state.file_a = path
        self.state.df_a = df
        self.state.df_view = df
        self.state.df_clean = None
        return df

    def load_b(self, path: str) -> pd.DataFrame:
        df = _read_csv_robust(path)
        self.state.file_b = path
        self.state.df_b = df
        return df

    def set_active_a(self):
        if self.state.df_a is None:
            raise RuntimeError("Dataset A not loaded.")
        self.state.df_view = self.state.df_a
        self.state.df_clean = None

    def set_active_clean(self):
        if self.state.df_clean is None:
            raise RuntimeError("No cleaned dataset available yet.")
        self.state.df_view = self.state.df_clean

    def numeric_cols(self) -> List[str]:
        if self.state.df_view is None:
            return []
        num = self.state.df_view.select_dtypes(include="number")
        return list(num.columns)

    def cols(self) -> List[str]:
        if self.state.df_view is None:
            return []
        return list(self.state.df_view.columns)


# -----------------------------
# Engines: Profile / Clean / Compare / Report
# -----------------------------

class ProfileEngine:
    @staticmethod
    def profile(df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {
                "rows": 0, "cols": 0, "quality_score": 0,
                "summary": ["No data loaded."],
                "issues": ["Load a CSV file."],
                "recommendations": ["Open a CSV and re-run profiling."],
                "top_correlations": [],
                "missing_per_col": {},
                "outlier_counts": {},
            }

        rows, cols = df.shape
        mem_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)

        missing_per_col = df.isna().mean().sort_values(ascending=False)
        missing_total_ratio = float(df.isna().sum().sum() / max(1, rows * cols))

        dup_rows = int(df.duplicated().sum())
        dup_ratio = float(dup_rows / max(1, rows))

        num = df.select_dtypes(include="number").copy()
        numeric_cols = list(num.columns)

        outlier_counts: Dict[str, int] = {}
        skew_flags: List[Tuple[str, float]] = []
        constant_numeric: List[str] = []
        top_corrs: List[Tuple[str, str, float]] = []

        if not num.empty:
            # outliers by MAD zscore
            for c in numeric_cols:
                s = num[c].dropna()
                if len(s) < 10:
                    outlier_counts[c] = 0
                    continue
                z = _mad_based_zscore(s)
                outlier_counts[c] = int((z.abs() > 3.5).sum())
                if s.nunique(dropna=True) <= 1:
                    constant_numeric.append(c)

            # skewness
            try:
                sk = num.skew(numeric_only=True)
                for c, v in sk.items():
                    if pd.notna(v) and abs(float(v)) >= 1.0:
                        skew_flags.append((c, float(v)))
            except Exception:
                pass

            # correlations
            try:
                corr = num.corr(numeric_only=True)
                pairs = []
                cols_ = corr.columns
                for i in range(len(cols_)):
                    for j in range(i + 1, len(cols_)):
                        v = corr.iloc[i, j]
                        if pd.notna(v):
                            pairs.append((cols_[i], cols_[j], float(v), abs(float(v))))
                pairs.sort(key=lambda x: x[3], reverse=True)
                top_corrs = [(a, b, v) for a, b, v, _ in pairs[:10]]
            except Exception:
                top_corrs = []

        issues: List[str] = []
        recs: List[str] = []
        summary: List[str] = []

        summary.append(f"Rows: {rows:,} | Columns: {cols:,} | Memory: {mem_mb:.2f} MB")
        summary.append(f"Missing cells: {_format_pct(missing_total_ratio)} | Duplicate rows: {dup_rows:,} ({_format_pct(dup_ratio)})")
        summary.append(f"Numeric columns: {len(numeric_cols)}")

        if missing_total_ratio > 0.10:
            issues.append("High missingness detected (>10% of cells).")
            recs.append("Impute missing values or drop high-missing columns after review.")

        if dup_ratio > 0.02:
            issues.append("Noticeable duplicated rows detected (>2%).")
            recs.append("Consider dropping duplicates in the cleaning step.")

        # per-column missing
        for c, r in missing_per_col.head(5).items():
            if r >= 0.20:
                issues.append(f"Column '{c}' has high missing rate: {_format_pct(float(r))}")
                recs.append(f"Fix upstream source for '{c}', or impute/drop column depending on importance.")

        # outliers
        if outlier_counts:
            total_out = sum(outlier_counts.values())
            if total_out > 0:
                issues.append(f"Outliers detected (robust MAD z-score): total={total_out}")
                top_out = sorted(outlier_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                for c, n in top_out:
                    if n > 0:
                        recs.append(f"Inspect '{c}' outliers (count={n}); consider winsorization or robust scaling.")

        # skew
        if skew_flags:
            issues.append("Skewed numeric distributions detected (|skew|>=1).")
            top_sk = sorted(skew_flags, key=lambda x: abs(x[1]), reverse=True)[:5]
            for c, v in top_sk:
                recs.append(f"'{c}' skew={v:.2f}; consider log/Box-Cox transform if meaningful.")

        # constant
        if constant_numeric:
            issues.append("Constant/near-constant numeric columns detected.")
            recs.append("Remove constant columns; they add no analytic value.")

        if top_corrs:
            summary.append("Top correlations: " + ", ".join([f"{a}~{b}({v:.2f})" for a, b, v in top_corrs[:3]]))
            recs.append("Check multicollinearity if building predictive models.")

        # quality score (interpretable)
        score = 100.0
        score -= min(50.0, missing_total_ratio * 100 * 0.8)
        score -= min(15.0, dup_ratio * 100 * 0.7)
        if outlier_counts and rows > 0 and len(numeric_cols) > 0:
            out_ratio = (sum(outlier_counts.values()) / max(1, rows * len(numeric_cols)))
            score -= min(20.0, out_ratio * 100 * 0.5)
        score -= min(10.0, len(skew_flags) * 1.0)
        score -= min(5.0, len(constant_numeric) * 1.0)
        score = max(0.0, min(100.0, score))

        if not issues:
            issues.append("No major issues detected with current heuristics.")
        if not recs:
            recs.append("Proceed to analysis; consider exporting a report.")

        return {
            "rows": rows,
            "cols": cols,
            "quality_score": int(round(score)),
            "summary": summary,
            "issues": issues[:15],
            "recommendations": recs[:15],
            "top_correlations": top_corrs,
            "missing_per_col": missing_per_col.to_dict(),
            "outlier_counts": outlier_counts,
            "dtypes": df.dtypes.astype(str).to_dict(),
        }


class CleaningEngine:
    @staticmethod
    def clean(
        df: pd.DataFrame,
        *,
        drop_duplicates: bool,
        trim_strings: bool,
        coerce_numeric: bool,
        missing_strategy: str,   # "none" | "drop_rows" | "median" | "mean" | "mode"
        winsorize: bool,
        winsor_p: float,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        if df is None or df.empty:
            raise ValueError("No data to clean.")

        out = df.copy()
        log: Dict[str, Any] = {"steps": [], "before": {}, "after": {}}

        log["before"] = {
            "rows": int(out.shape[0]),
            "cols": int(out.shape[1]),
            "missing_cells": int(out.isna().sum().sum()),
            "dup_rows": int(out.duplicated().sum()),
        }

        if trim_strings:
            for c in out.select_dtypes(include=["object", "string"]).columns:
                out[c] = out[c].astype("string").str.strip()
            log["steps"].append("Trimmed string columns.")

        if coerce_numeric:
            # try convert object columns that look numeric
            for c in out.columns:
                if out[c].dtype == "object":
                    converted = pd.to_numeric(out[c], errors="coerce")
                    # convert if it improves numeric fill rate
                    non_na_before = out[c].notna().sum()
                    non_na_after = converted.notna().sum()
                    if non_na_after >= int(0.7 * max(1, non_na_before)):
                        out[c] = converted
            log["steps"].append("Coerced numeric-like columns to numeric where reasonable.")

        if drop_duplicates:
            before = out.shape[0]
            out = out.drop_duplicates()
            after = out.shape[0]
            log["steps"].append(f"Dropped duplicates: {before-after} rows removed.")

        if winsorize:
            num_cols = out.select_dtypes(include="number").columns
            for c in num_cols:
                s = out[c]
                if s.dropna().shape[0] >= 20 and s.nunique(dropna=True) > 5:
                    out[c] = _winsorize_series(s, p=winsor_p)
            log["steps"].append(f"Winsorized numeric columns with p={winsor_p:.3f}.")

        # missing handling
        ms = missing_strategy
        if ms == "drop_rows":
            before = out.shape[0]
            out = out.dropna()
            after = out.shape[0]
            log["steps"].append(f"Dropped rows with any missing: {before-after} rows removed.")
        elif ms in ("median", "mean"):
            num_cols = out.select_dtypes(include="number").columns
            for c in num_cols:
                if out[c].isna().any():
                    val = out[c].median() if ms == "median" else out[c].mean()
                    out[c] = out[c].fillna(val)
            log["steps"].append(f"Imputed numeric missing values using {ms}.")
            # categorical: mode
            cat_cols = out.select_dtypes(exclude="number").columns
            for c in cat_cols:
                if out[c].isna().any():
                    mode = out[c].mode(dropna=True)
                    if not mode.empty:
                        out[c] = out[c].fillna(mode.iloc[0])
            log["steps"].append("Imputed non-numeric missing values using mode (if possible).")
        elif ms == "mode":
            for c in out.columns:
                if out[c].isna().any():
                    mode = out[c].mode(dropna=True)
                    if not mode.empty:
                        out[c] = out[c].fillna(mode.iloc[0])
            log["steps"].append("Imputed missing values using mode (per column).")
        elif ms == "none":
            pass
        else:
            raise ValueError("Invalid missing strategy.")

        log["after"] = {
            "rows": int(out.shape[0]),
            "cols": int(out.shape[1]),
            "missing_cells": int(out.isna().sum().sum()),
            "dup_rows": int(out.duplicated().sum()),
        }
        return out, log


class CompareEngine:
    @staticmethod
    def compare(df_a: pd.DataFrame, df_b: pd.DataFrame) -> Dict[str, Any]:
        if df_a is None or df_a.empty:
            raise ValueError("Dataset A is missing/empty.")
        if df_b is None or df_b.empty:
            raise ValueError("Dataset B is missing/empty.")

        cols_a = set(df_a.columns)
        cols_b = set(df_b.columns)
        added = sorted(list(cols_b - cols_a))
        removed = sorted(list(cols_a - cols_b))
        common = sorted(list(cols_a & cols_b))

        schema = {
            "added_columns_in_B": added,
            "removed_columns_in_B": removed,
            "common_columns": common,
        }

        # missingness drift
        miss_a = df_a.isna().mean()
        miss_b = df_b.isna().mean()
        miss_drift = []
        for c in common:
            da = float(miss_a.get(c, 0.0))
            db = float(miss_b.get(c, 0.0))
            miss_drift.append((c, da, db, db - da))
        miss_drift.sort(key=lambda x: abs(x[3]), reverse=True)

        # numeric drift
        num_common = [c for c in common if pd.api.types.is_numeric_dtype(df_a[c]) and pd.api.types.is_numeric_dtype(df_b[c])]
        drift_stats = []
        for c in num_common:
            a = pd.to_numeric(df_a[c], errors="coerce")
            b = pd.to_numeric(df_b[c], errors="coerce")
            if a.dropna().empty or b.dropna().empty:
                continue
            ma, mb = float(a.mean()), float(b.mean())
            sa, sb = float(a.std(ddof=1)), float(b.std(ddof=1))
            drift_stats.append((c, ma, mb, mb - ma, sa, sb, sb - sa))
        drift_stats.sort(key=lambda x: abs(x[3]), reverse=True)

        return {
            "schema": schema,
            "missing_drift_top": miss_drift[:20],
            "numeric_drift_top": drift_stats[:20],
            "rows_a": int(df_a.shape[0]),
            "rows_b": int(df_b.shape[0]),
            "cols_a": int(df_a.shape[1]),
            "cols_b": int(df_b.shape[1]),
        }


class ReportEngine:
    @staticmethod
    def _inline_logo_b64(logo_path: str) -> Optional[str]:
        if not os.path.exists(logo_path):
            return None
        try:
            with open(logo_path, "rb") as f:
                b = f.read()
            return base64.b64encode(b).decode("ascii")
        except Exception:
            return None

    @staticmethod
    def export_html(
        cfg: AppConfig,
        *,
        path: str,
        file_name: str,
        profile: Dict[str, Any],
        clean_log: Optional[Dict[str, Any]] = None,
        compare: Optional[Dict[str, Any]] = None,
    ) -> None:
        logo_b64 = ReportEngine._inline_logo_b64(os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg.logo_path))
        logo_html = ""
        if logo_b64:
            logo_html = f'<img class="logo" src="data:image/png;base64,{logo_b64}" alt="logo"/>'

        def li(items: List[str]) -> str:
            return "\n".join([f"<li>{_escape_html(x)}</li>" for x in items])

        top_corrs = profile.get("top_correlations", [])[:10]
        corr_rows = ""
        for a, b, v in top_corrs:
            corr_rows += f"<tr><td>{_escape_html(a)}</td><td>{_escape_html(b)}</td><td>{v:.4f}</td></tr>\n"

        # missing top
        miss = profile.get("missing_per_col", {})
        miss_top = sorted([(k, float(v)) for k, v in miss.items()], key=lambda x: x[1], reverse=True)[:12]
        miss_rows = ""
        for c, r in miss_top:
            miss_rows += f"<tr><td>{_escape_html(c)}</td><td>{r*100:.2f}%</td></tr>\n"

        # clean summary
        clean_html = ""
        if clean_log:
            steps = clean_log.get("steps", [])
            b = clean_log.get("before", {})
            a = clean_log.get("after", {})
            clean_html = f"""
            <section class="card">
              <h2>Cleaning Log</h2>
              <div class="grid2">
                <div>
                  <h3>Before</h3>
                  <ul>
                    <li>Rows: {b.get('rows','')}</li>
                    <li>Columns: {b.get('cols','')}</li>
                    <li>Missing cells: {b.get('missing_cells','')}</li>
                    <li>Duplicate rows: {b.get('dup_rows','')}</li>
                  </ul>
                </div>
                <div>
                  <h3>After</h3>
                  <ul>
                    <li>Rows: {a.get('rows','')}</li>
                    <li>Columns: {a.get('cols','')}</li>
                    <li>Missing cells: {a.get('missing_cells','')}</li>
                    <li>Duplicate rows: {a.get('dup_rows','')}</li>
                  </ul>
                </div>
              </div>
              <h3>Steps Applied</h3>
              <ol>
                {''.join([f'<li>{_escape_html(s)}</li>' for s in steps])}
              </ol>
            </section>
            """

        # compare summary
        compare_html = ""
        if compare:
            sch = compare.get("schema", {})
            added = sch.get("added_columns_in_B", [])
            removed = sch.get("removed_columns_in_B", [])
            md = compare.get("missing_drift_top", [])
            nd = compare.get("numeric_drift_top", [])

            md_rows = ""
            for c, da, db, dd in md[:12]:
                md_rows += f"<tr><td>{_escape_html(c)}</td><td>{da*100:.2f}%</td><td>{db*100:.2f}%</td><td>{dd*100:+.2f}%</td></tr>\n"

            nd_rows = ""
            for c, ma, mb, dm, sa, sb, ds in nd[:12]:
                nd_rows += f"<tr><td>{_escape_html(c)}</td><td>{ma:.4g}</td><td>{mb:.4g}</td><td>{dm:+.4g}</td><td>{sa:.4g}</td><td>{sb:.4g}</td></tr>\n"

            compare_html = f"""
            <section class="card">
              <h2>Compare A vs B</h2>
              <p class="muted">A: {compare.get('rows_a',0)} rows, {compare.get('cols_a',0)} cols — B: {compare.get('rows_b',0)} rows, {compare.get('cols_b',0)} cols</p>

              <div class="grid2">
                <div>
                  <h3>Schema Changes</h3>
                  <p><b>Added in B</b>: {', '.join(map(_escape_html, added)) if added else '—'}</p>
                  <p><b>Removed in B</b>: {', '.join(map(_escape_html, removed)) if removed else '—'}</p>
                </div>
                <div>
                  <h3>Notes</h3>
                  <p class="muted">This drift check is heuristic and intended for quick QA/monitoring.</p>
                </div>
              </div>

              <h3>Missingness Drift (Top)</h3>
              <table>
                <thead><tr><th>Column</th><th>Missing A</th><th>Missing B</th><th>Δ</th></tr></thead>
                <tbody>
                  {md_rows or '<tr><td colspan="4">No comparable columns.</td></tr>'}
                </tbody>
              </table>

              <h3>Numeric Drift (Top)</h3>
              <table>
                <thead><tr><th>Column</th><th>Mean A</th><th>Mean B</th><th>ΔMean</th><th>Std A</th><th>Std B</th></tr></thead>
                <tbody>
                  {nd_rows or '<tr><td colspan="6">No numeric comparable columns.</td></tr>'}
                </tbody>
              </table>
            </section>
            """

        html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{cfg.title} Report</title>
<style>
:root {{
  --bg: {cfg.bg_app};
  --panel: {cfg.bg_panel};
  --card: {cfg.bg_card};
  --text: {cfg.fg_text};
  --muted: {cfg.fg_muted};
  --border: {cfg.border};
  --accent: {cfg.accent};
  --accent2: {cfg.accent2};
  --danger: {cfg.danger};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0;
  font-family: {cfg.font}, Arial, sans-serif;
  background: var(--bg); color: var(--text);
}}
.header {{
  padding: 24px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(34,197,94,0.10), rgba(56,189,248,0.05));
}}
.brand {{
  display: flex; align-items: center; gap: 14px;
}}
.logo {{
  width: 56px; height: 56px; border-radius: 14px;
  border: 1px solid var(--border);
  background: #0b1220;
}}
.h1 {{
  font-size: 22px; font-weight: 800; margin: 0;
}}
.sub {{
  margin: 4px 0 0; color: var(--muted);
}}
.container {{
  max-width: 1100px;
  margin: 0 auto;
  padding: 18px 18px 40px;
}}
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px 18px;
  margin-top: 14px;
}}
.card h2 {{
  margin: 0 0 10px;
  font-size: 16px;
}}
.grid2 {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}}
.muted {{ color: var(--muted); }}
.badge {{
  display: inline-block;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(34,197,94,0.15);
  border: 1px solid rgba(34,197,94,0.35);
  color: var(--text);
  font-weight: 700;
}}
.badge.bad {{
  background: rgba(239,68,68,0.12);
  border-color: rgba(239,68,68,0.35);
}}
table {{
  width: 100%;
  border-collapse: collapse;
  margin-top: 8px;
}}
th, td {{
  border-bottom: 1px solid var(--border);
  text-align: left;
  padding: 10px 8px;
  font-size: 13px;
}}
th {{ color: var(--muted); font-weight: 700; }}
ul, ol {{ margin: 8px 0 0 18px; }}
.footer {{
  margin-top: 18px;
  color: var(--muted);
  font-size: 12px;
}}
@media (max-width: 900px) {{
  .grid2 {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
  <div class="header">
    <div class="container">
      <div class="brand">
        {logo_html}
        <div>
          <p class="h1">{cfg.title} — Data Health Report</p>
          <p class="sub">Version {cfg.version} • Generated locally • File: {_escape_html(file_name)}</p>
        </div>
      </div>
    </div>
  </div>

  <div class="container">

    <section class="card">
      <h2>Quality Score</h2>
      <p>
        <span class="badge {'bad' if int(profile.get('quality_score',0)) < 60 else ''}">
          {int(profile.get('quality_score',0))}/100
        </span>
      </p>
      <p class="muted">This score is a heuristic signal (missingness, duplicates, outliers, skewness). Review detected issues and recommendations.</p>
    </section>

    <section class="card">
      <h2>Quick Summary</h2>
      <ul>
        {li([str(x) for x in profile.get("summary", [])])}
      </ul>
    </section>

    <section class="card">
      <h2>Detected Issues</h2>
      <ul>
        {li([str(x) for x in profile.get("issues", [])])}
      </ul>
    </section>

    <section class="card">
      <h2>Recommendations</h2>
      <ul>
        {li([str(x) for x in profile.get("recommendations", [])])}
      </ul>
    </section>

    <section class="card">
      <h2>Missingness (Top Columns)</h2>
      <table>
        <thead><tr><th>Column</th><th>Missing %</th></tr></thead>
        <tbody>
          {miss_rows or '<tr><td colspan="2">—</td></tr>'}
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>Top Correlations (Numeric)</h2>
      <table>
        <thead><tr><th>Column A</th><th>Column B</th><th>Correlation</th></tr></thead>
        <tbody>
          {corr_rows or '<tr><td colspan="3">No numeric correlations available.</td></tr>'}
        </tbody>
      </table>
    </section>

    {clean_html}
    {compare_html}

    <div class="footer">
      <p>Generated by {cfg.title}. No data is uploaded or sent to the internet.</p>
    </div>

  </div>
</body>
</html>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)


# -----------------------------
# UI Components (pure Tk)
# -----------------------------

class Card(tk.Frame):
    def __init__(self, master, cfg: AppConfig, title: str):
        super().__init__(master, bg=cfg.bg_card, highlightthickness=1, highlightbackground=cfg.border)
        hdr = tk.Frame(self, bg=cfg.bg_card)
        hdr.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(hdr, text=title, bg=cfg.bg_card, fg=cfg.fg_text,
                 font=(cfg.font, 12, "bold")).pack(anchor="w")


class AppButton(tk.Frame):
    def __init__(self, master, cfg: AppConfig, text: str, command, variant: str = "primary", width: int = 210, height: int = 44):
        bg = cfg.accent if variant == "primary" else cfg.bg_card
        fg = "#04110A" if variant == "primary" else cfg.fg_text
        hover = "#16A34A" if variant == "primary" else "#101a33"

        super().__init__(master, bg=bg, highlightthickness=1, highlightbackground=cfg.border)
        self.cfg = cfg
        self.command = command
        self._bg = bg
        self._hover = hover
        self._fg = fg

        self.configure(width=width, height=height)
        self.pack_propagate(False)

        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="both", expand=True)

        lbl = tk.Label(inner, text=text, bg=bg, fg=fg, font=(cfg.font, 10, "bold"))
        lbl.pack(side="left", padx=12)

        for w in (self, inner, lbl):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            w.configure(cursor="hand2")

    def _click(self, _=None):
        try:
            if callable(self.command):
                self.command()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _enter(self, _=None):
        self._set_bg(self._hover)

    def _leave(self, _=None):
        self._set_bg(self._bg)

    def _set_bg(self, c: str):
        self.configure(bg=c)
        for w in self.winfo_children():
            w.configure(bg=c)
            for ww in w.winfo_children():
                ww.configure(bg=c, fg=self._fg)


class ProgressOverlay(tk.Toplevel):
    def __init__(self, master: tk.Tk, cfg: AppConfig, title: str = "Working..."):
        super().__init__(master)
        self.cfg = cfg
        self.title(title)
        self.configure(bg=cfg.bg_panel)
        self.resizable(False, False)
        self.transient(master)
        try:
            self.grab_set()
        except Exception:
            pass


        
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        w, h = 420, 160
        _center_window(self, w, h)

        tk.Label(self, text=title, bg=cfg.bg_panel, fg=cfg.fg_text,
                 font=(cfg.font, 12, "bold")).pack(anchor="w", padx=14, pady=(14, 8))

        self.msg = tk.StringVar(value="Please wait...")
        tk.Label(self, textvariable=self.msg, bg=cfg.bg_panel, fg=cfg.fg_muted,
                 font=(cfg.font, 10)).pack(anchor="w", padx=14)

        # fake progress (indeterminate)
        bar = tk.Canvas(self, height=18, bg=cfg.bg_card, highlightthickness=1, highlightbackground=cfg.border)
        bar.pack(fill="x", padx=14, pady=(16, 8))
        self._bar = bar
        self._pos = 0
        self._running = True
        self.after(60, self._tick)

        tk.Label(self, text="Do not close the application during processing.", bg=cfg.bg_panel,
                 fg=cfg.fg_muted, font=(cfg.font, 9)).pack(anchor="w", padx=14)

    def set(self, text: str):
        self.msg.set(text)

    def _tick(self):
        if not self._running:
            return
        w = self._bar.winfo_width()
        self._bar.delete("all")
        span = max(40, int(w * 0.25))
        x0 = self._pos
        x1 = min(w, x0 + span)
        self._bar.create_rectangle(x0, 1, x1, 17, fill=self.cfg.accent, outline="")
        self._pos += 14
        if self._pos > w:
            self._pos = -span
        self.after(60, self._tick)

    def close(self):
        self._running = False
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


# -----------------------------
# Splash Screen
# -----------------------------

class SplashScreen(tk.Toplevel):
    def __init__(self, master: tk.Tk, cfg: AppConfig, on_start):
        super().__init__(master)
        self.cfg = cfg
        self.on_start = on_start

        self.title(f"{cfg.title} — Welcome")
        self.configure(bg=cfg.bg_app)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        _center_window(self, cfg.splash_w, cfg.splash_h)
        self.protocol("WM_DELETE_WINDOW", self._exit)

        wrap = tk.Frame(self, bg=cfg.bg_app)
        wrap.pack(fill="both", expand=True, padx=18, pady=18)

        card = tk.Frame(wrap, bg=cfg.bg_card, highlightthickness=1, highlightbackground=cfg.border)
        card.pack(fill="both", expand=True)

        top = tk.Frame(card, bg=cfg.bg_card)
        top.pack(fill="both", expand=True, padx=28, pady=24)
        top.grid_columnconfigure(1, weight=1)

        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg.logo_path)
        self._logo_ref = _try_load_logo(logo_path)
        if self._logo_ref:
            tk.Label(top, image=self._logo_ref, bg=cfg.bg_card).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 16))

        tk.Label(top, text=f"Welcome to {cfg.title}", bg=cfg.bg_card, fg=cfg.fg_text,
                 font=(cfg.font, 28, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text="Professional Data Health, Cleaning, Compare, and Reporting for CSV files.",
                 bg=cfg.bg_card, fg=cfg.fg_muted, font=(cfg.font, 11)).grid(row=1, column=1, sticky="w", pady=(6, 0))

        info = tk.Frame(top, bg=cfg.bg_panel, highlightthickness=1, highlightbackground=cfg.border)
        info.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(22, 0))
        text = (
            "Quick workflow:\n"
            "1) Open CSV (A)\n"
            "2) Review Data Health (Quality Score, Issues, Recommendations)\n"
            "3) Apply Cleaning Pipeline and save cleaned.csv\n"
            "4) (Optional) Load CSV (B) and Compare A vs B (schema + drift)\n"
            "5) Export a professional HTML report\n\n"
            "All processing is local and offline."
        )
        tk.Label(info, text=text, bg=cfg.bg_panel, fg=cfg.fg_text, justify="left",
                 font=(cfg.font, 10)).pack(anchor="w", padx=14, pady=14)

        btns = tk.Frame(top, bg=cfg.bg_card)
        btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        btns.grid_columnconfigure(0, weight=1)

        left = tk.Frame(btns, bg=cfg.bg_card)
        left.grid(row=0, column=0, sticky="w")

        right = tk.Frame(btns, bg=cfg.bg_card)
        right.grid(row=0, column=1, sticky="e")

        AppButton(left, cfg, "About", self._about, variant="secondary", width=130).pack(side="left", padx=(0, 10))
        AppButton(left, cfg, "Version", self._version, variant="secondary", width=130).pack(side="left", padx=(0, 10))
        AppButton(left, cfg, "Help", self._help, variant="secondary", width=130).pack(side="left")

        AppButton(right, cfg, "Exit", self._exit, variant="secondary", width=120).pack(side="right", padx=(10, 0))
        AppButton(right, cfg, "Start", self._start, variant="primary", width=140).pack(side="right")

    def _start(self):
        try:
            self.destroy()
        except Exception:
            pass
        self.on_start()

    def _exit(self):
        try:
            self.master.destroy()
        except Exception:
            pass

    def _about(self):
        messagebox.showinfo(
            "About",
            f"{self.cfg.title}\n\n"
            "A local, offline CSV decision-support tool focused on:\n"
            "• Data Health (quality score, missingness, duplicates, outliers)\n"
            "• Cleaning pipeline with preview and export\n"
            "• A/B compare and drift checks\n"
            "• Professional HTML reports\n"
        )

    def _version(self):
        messagebox.showinfo("Version", f"{self.cfg.title} Version: {self.cfg.version}\nPython: {os.sys.version.split()[0]}")

    def _help(self):
        messagebox.showinfo(
            "Help",
            "Tips:\n"
            "• For large CSVs, profiling/compare may take time; UI stays responsive.\n"
            "• Use Cleaning tab to create a cleaned dataset and save it.\n"
            "• Use Compare tab after loading both A and B.\n"
            "• Export Reports as HTML for easy sharing.\n"
        )




class ScrollableFrame(tk.Frame):
    """
    A lightweight scrollable frame for Tkinter using Canvas.
    Usage:
        sf = ScrollableFrame(parent, bg=...)
        sf.pack(fill="both", expand=True)
        # put widgets inside sf.inner
    """
    def __init__(self, master, *, bg, border=None):
        super().__init__(master, bg=bg)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vscroll = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        def _on_inner_config(_evt=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def _on_canvas_config(_evt=None):
            # make inner frame match canvas width
            w = self.canvas.winfo_width()
            self.canvas.itemconfig(self._win, width=w)

        self.inner.bind("<Configure>", _on_inner_config)
        self.canvas.bind("<Configure>", _on_canvas_config)

        # Mouse wheel support (Windows/macOS/Linux best-effort)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)          # Windows/macOS
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)      # Linux up
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)      # Linux down

    def _on_mousewheel(self, event):
        # On Windows event.delta is multiples of 120
        if event.delta:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")




class CollapsibleSection(tk.Frame):
    """
    Simple collapsible panel: header row + content frame.
    """
    def __init__(self, master, cfg: AppConfig, title: str, start_open: bool = True):
        super().__init__(master, bg=cfg.bg_card)
        self.cfg = cfg
        self._open = start_open

        self.header = tk.Frame(self, bg=cfg.bg_panel, highlightthickness=1, highlightbackground=cfg.border)
        self.header.pack(fill="x", pady=(6, 0))

        self.btn = tk.Button(
            self.header,
            text=("▾ " + title) if self._open else ("▸ " + title),
            command=self.toggle,
            relief="flat",
            bg=cfg.bg_panel, fg=cfg.fg_text,
            activebackground=cfg.bg_panel, activeforeground=cfg.fg_text,
            bd=0,
            font=(cfg.font, 10, "bold"),
            anchor="w",
            padx=10, pady=8
        )
        self.btn.pack(fill="x")

        self.body = tk.Frame(self, bg=cfg.bg_card)
        if self._open:
            self.body.pack(fill="x", padx=6, pady=(6, 0))

    def toggle(self):
        self._open = not self._open
        if self._open:
            self.body.pack(fill="x", padx=6, pady=(6, 0))
            self.btn.configure(text=self.btn.cget("text").replace("▸", "▾", 1))
        else:
            self.body.pack_forget()
            self.btn.configure(text=self.btn.cget("text").replace("▾", "▸", 1))

# -----------------------------
# Main App
# -----------------------------

class GreenProApp(tk.Tk):
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        self.state = DataState()
        self.data = DataController(self.state)
        self.profile_engine = ProfileEngine()
        self.clean_engine = CleaningEngine()
        self.compare_engine = CompareEngine()
        self.report_engine = ReportEngine()

        self._status = tk.StringVar(value="Ready")
        self._active_dataset_label = tk.StringVar(value="Active: —")

        self._icon_ref = None
        self._configure_window()
        self._build_layout()

    def _configure_window(self):
        self.title(self.cfg.title)
        self.geometry(f"{self.cfg.width}x{self.cfg.height}")
        self.configure(bg=self.cfg.bg_app)
        self.resizable(self.cfg.resizable, self.cfg.resizable)

        icon_path = os.path.join(self.base_dir, self.cfg.logo_path)
        if os.path.exists(icon_path):
            try:
                icon = tk.PhotoImage(file=icon_path)
                self.iconphoto(False, icon)
                self._icon_ref = icon
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- layout ----

    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)

        self.sidebar = tk.Frame(self, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        self.sidebar.grid(row=0, column=0, sticky="nsw")

        self.main = tk.Frame(self, bg=self.cfg.bg_app)
        self.main.grid(row=0, column=1, sticky="nsew")

        self.statusbar = tk.Frame(self, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        self.statusbar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.statusbar.grid_columnconfigure(1, weight=1)

        tk.Label(self.statusbar, textvariable=self._active_dataset_label, bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 9, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=6)

        tk.Label(self.statusbar, textvariable=self._status, bg=self.cfg.bg_panel, fg=self.cfg.fg_muted,
                 font=(self.cfg.font, 9)).grid(row=0, column=1, sticky="w", padx=12, pady=6)

        self._build_sidebar()
        self._build_main()

        self._select_tab("Dashboard")

        self.sidebar.configure(width=250)
        self.sidebar.pack_propagate(False)

    def _build_sidebar(self):
        head = tk.Frame(self.sidebar, bg=self.cfg.bg_panel)
        head.pack(fill="x", padx=14, pady=(14, 10))

        logo_path = os.path.join(self.base_dir, self.cfg.logo_path)
        self._logo_small = _try_load_logo(logo_path)
        if self._logo_small:
            tk.Label(head, image=self._logo_small, bg=self.cfg.bg_panel).pack(anchor="w")

        tk.Label(head, text=self.cfg.title, bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 16, "bold")).pack(anchor="w", pady=(10, 0))
        tk.Label(head, text="Data Health • Clean • Compare • Report", bg=self.cfg.bg_panel, fg=self.cfg.fg_muted,
                 font=(self.cfg.font, 9)).pack(anchor="w", pady=(3, 0))

        btns = tk.Frame(self.sidebar, bg=self.cfg.bg_panel)
        btns.pack(fill="x", padx=12, pady=10)

        AppButton(btns, self.cfg, "Open CSV (A)", self.open_csv_a, width=220).pack(fill="x", pady=6)
        AppButton(btns, self.cfg, "Open CSV (B)", self.open_csv_b, width=220, variant="secondary").pack(fill="x", pady=6)

        tk.Frame(btns, bg=self.cfg.bg_panel, height=12).pack(fill="x")

        AppButton(btns, self.cfg, "Dashboard", lambda: self._select_tab("Dashboard"), width=220, variant="secondary").pack(fill="x", pady=6)
        AppButton(btns, self.cfg, "Data Health", lambda: self._select_tab("Health"), width=220, variant="secondary").pack(fill="x", pady=6)
        AppButton(btns, self.cfg, "Cleaning", lambda: self._select_tab("Clean"), width=220, variant="secondary").pack(fill="x", pady=6)
        AppButton(btns, self.cfg, "Plots", lambda: self._select_tab("Plots"), width=220, variant="secondary").pack(fill="x", pady=6)
        AppButton(btns, self.cfg, "Compare A/B", lambda: self._select_tab("Compare"), width=220, variant="secondary").pack(fill="x", pady=6)
        AppButton(btns, self.cfg, "Export Report", self.export_report, width=220).pack(fill="x", pady=6)

        tk.Frame(btns, bg=self.cfg.bg_panel, height=12).pack(fill="x")
        AppButton(btns, self.cfg, "Exit", self._on_close, width=220, variant="secondary").pack(fill="x", pady=6)

    def _build_main(self):
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.content = tk.Frame(self.main, bg=self.cfg.bg_app)
        self.content.grid(row=0, column=0, sticky="nsew")
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # tabs bar
        self.tabs_bar = tk.Frame(self.content, bg=self.cfg.bg_app)
        self.tabs_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))

        self.tab_container = tk.Frame(self.content, bg=self.cfg.bg_app)
        self.tab_container.grid(row=1, column=0, sticky="nsew", padx=14, pady=14)
        self.tab_container.grid_rowconfigure(0, weight=1)
        self.tab_container.grid_columnconfigure(0, weight=1)

        self._tabs: Dict[str, tk.Frame] = {}
        self._tab_buttons: Dict[str, tk.Button] = {}

        for name in ("Dashboard", "Health", "Clean", "Plots", "Compare"):
            self._create_tab(name)

        self._build_dashboard()
        self._build_health()
        self._build_clean()
        self._build_plots()
        self._build_compare()

    def _create_tab(self, name: str):
        btn = tk.Button(
            self.tabs_bar,
            text=name,
            relief="flat",
            bg=self.cfg.bg_card,
            fg=self.cfg.fg_text,
            activebackground=self.cfg.bg_card,
            activeforeground=self.cfg.fg_text,
            bd=0,
            padx=12,
            pady=8,
            command=lambda n=name: self._select_tab(n),
            font=(self.cfg.font, 10, "bold"),
        )
        btn.pack(side="left", padx=(0, 8))
        self._tab_buttons[name] = btn

        frame = tk.Frame(self.tab_container, bg=self.cfg.bg_app)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_remove()
        self._tabs[name] = frame

    def _select_tab(self, name: str):
        for f in self._tabs.values():
            f.grid_remove()
        self._tabs[name].grid()

        for n, b in self._tab_buttons.items():
            if n == name:
                b.configure(bg=self.cfg.accent, fg="#04110A")
            else:
                b.configure(bg=self.cfg.bg_card, fg=self.cfg.fg_text)

        self._set_status(f"Tab: {name}")

    # -------------------------
    # Dashboard
    # -------------------------

    def _build_dashboard(self):
        root = self._tabs["Dashboard"]
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        card = Card(root, self.cfg, "Overview")
        card.pack(fill="both", expand=True)

        body = tk.Frame(card, bg=self.cfg.bg_card)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.dashboard_text = tk.Label(
            body,
            text=(
                "Open CSV (A) to start.\n\n"
                "Recommended workflow:\n"
                "1) Data Health: quality score + issues + recommendations\n"
                "2) Cleaning: apply pipeline and save cleaned dataset\n"
                "3) Plots: choose columns and visualize quickly\n"
                "4) Compare: load CSV (B) and detect schema/drift changes\n"
                "5) Export Report: professional HTML\n"
            ),
            bg=self.cfg.bg_card,
            fg=self.cfg.fg_muted,
            justify="left",
            font=(self.cfg.font, 11),
        )
        self.dashboard_text.pack(anchor="w", pady=10)

        row = tk.Frame(body, bg=self.cfg.bg_card)
        row.pack(fill="x", pady=10)

        tk.Button(
            row, text="Open CSV (A)", command=self.open_csv_a, relief="flat",
            bg=self.cfg.accent, fg="#04110A", bd=0, padx=14, pady=10,
            font=(self.cfg.font, 10, "bold"),
        ).pack(side="left")

        tk.Button(
            row, text="Run Data Health", command=self.refresh_health, relief="flat",
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text, bd=0, padx=14, pady=10,
            font=(self.cfg.font, 10, "bold"),
        ).pack(side="left", padx=10)

        tk.Button(
            row, text="Export Report", command=self.export_report, relief="flat",
            bg=self.cfg.accent2, fg="#001018", bd=0, padx=14, pady=10,
            font=(self.cfg.font, 10, "bold"),
        ).pack(side="left")

    # -------------------------
    # Health tab
    # -------------------------

    def _build_health(self):
        root = self._tabs["Health"]
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        card = Card(root, self.cfg, "Data Health (Quality Score, Issues, Recommendations)")
        card.pack(fill="both", expand=True)

        body = tk.Frame(card, bg=self.cfg.bg_card)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        body.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        top = tk.Frame(body, bg=self.cfg.bg_card)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        top.grid_columnconfigure(2, weight=1)

        self.quality_var = tk.StringVar(value="Quality Score: —")

        qbox = tk.Frame(top, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        qbox.grid(row=0, column=0, sticky="w")
        tk.Label(qbox, textvariable=self.quality_var, bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 11, "bold")).pack(anchor="w", padx=12, pady=10)

        tk.Button(
            top, text="Generate / Refresh", command=self.refresh_health,
            relief="flat", bg=self.cfg.accent, fg="#04110A", bd=0, padx=14, pady=10,
            font=(self.cfg.font, 10, "bold"),
        ).grid(row=0, column=1, padx=10, sticky="w")

        tk.Button(
            top, text="Notify (Beep)", command=_beep,
            relief="flat", bg=self.cfg.bg_panel, fg=self.cfg.fg_text, bd=0, padx=14, pady=10,
            font=(self.cfg.font, 10, "bold"),
        ).grid(row=0, column=2, sticky="e")

        summary_card = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        summary_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        summary_card.grid_columnconfigure(0, weight=1)

        tk.Label(summary_card, text="Quick Summary", bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))

        self.summary_text = tk.Text(
            summary_card, height=4, wrap="word",
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text, insertbackground=self.cfg.fg_text,
            relief="flat", bd=0, font=(self.cfg.font, 10)
        )
        self.summary_text.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.summary_text.config(state="disabled")

        issues_card = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        issues_card.grid(row=2, column=0, sticky="nsew", padx=(0, 6))
        issues_card.grid_rowconfigure(1, weight=1)
        issues_card.grid_columnconfigure(0, weight=1)

        tk.Label(issues_card, text="Detected Issues", bg=self.cfg.bg_panel, fg=self.cfg.danger,
                 font=(self.cfg.font, 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        self.issues_list = tk.Listbox(
            issues_card, bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
            selectbackground=self.cfg.accent2, selectforeground="#001018",
            relief="flat", highlightthickness=0
        )
        self.issues_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        rec_card = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        rec_card.grid(row=2, column=1, sticky="nsew", padx=(6, 0))
        rec_card.grid_rowconfigure(1, weight=1)
        rec_card.grid_columnconfigure(0, weight=1)

        tk.Label(rec_card, text="Recommendations", bg=self.cfg.bg_panel, fg=self.cfg.accent,
                 font=(self.cfg.font, 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        self.recs_list = tk.Listbox(
            rec_card, bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
            selectbackground=self.cfg.accent2, selectforeground="#001018",
            relief="flat", highlightthickness=0
        )
        self.recs_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self._set_summary_lines(["Open CSV (A), then click Generate / Refresh."])

    def _set_summary_lines(self, lines: List[str]):
        self.summary_text.config(state="normal")
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.config(state="disabled")

    def refresh_health(self):
        if not self.state.has_data:
            messagebox.showwarning("Data Health", "First open CSV (A) or activate a dataset.")
            return

        df = self.state.df_view

        overlay = ProgressOverlay(self, self.cfg, "Profiling data...")
        overlay.set("Computing missingness, duplicates, outliers, correlations...")

        def worker():
            try:
                prof = self.profile_engine.profile(df)
                self.state.report_last = {"profile": prof}
                def done():
                    overlay.close()
                    score = int(prof.get("quality_score", 0))
                    self.quality_var.set(f"Quality Score: {score}/100")
                    self._set_summary_lines([str(x) for x in prof.get("summary", [])])

                    self.issues_list.delete(0, tk.END)
                    for it in prof.get("issues", []):
                        self.issues_list.insert(tk.END, it)

                    self.recs_list.delete(0, tk.END)
                    for it in prof.get("recommendations", []):
                        self.recs_list.insert(tk.END, it)

                    self._set_status("Data Health refreshed.")
                    if score < 60:
                        _beep()
                self.after(0, done)
            except Exception as e:
                def err():
                    overlay.close()
                    messagebox.showerror("Profile Error", str(e))
                self.after(0, err)

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------
    # Cleaning tab
    # -------------------------

    def _build_clean(self):
        root = self._tabs["Clean"]
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        card = Card(root, self.cfg, "Cleaning Pipeline (Preview + Save)")
        card.pack(fill="both", expand=True)

        body = tk.Frame(card, bg=self.cfg.bg_card)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        # ---- scrollable left panel (Options) ----
        left_container = tk.Frame(body, bg=self.cfg.bg_card)
        left_container.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 12))
        left_container.configure(width=360)
        left_container.pack_propagate(False)
        
        canvas = tk.Canvas(
            left_container,
            bg=self.cfg.bg_card,
            highlightthickness=0,
            width=360
        )
        canvas.pack(side="left", fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        left = tk.Frame(canvas, bg=self.cfg.bg_card)
        canvas.create_window((0, 0), window=left, anchor="nw")
        
        def _on_left_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        left.bind("<Configure>", _on_left_configure)


        tk.Label(left, text="Options", bg=self.cfg.bg_card, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 11, "bold")).pack(anchor="w", pady=(8, 8))

        self.opt_drop_dup = tk.BooleanVar(value=True)
        self.opt_trim = tk.BooleanVar(value=True)
        self.opt_coerce_num = tk.BooleanVar(value=True)
        self.opt_winsor = tk.BooleanVar(value=False)

        def chk(text, var):
            f = tk.Frame(left, bg=self.cfg.bg_card)
            f.pack(fill="x", pady=4)
            cb = tk.Checkbutton(
                f, text=text, variable=var,
                bg=self.cfg.bg_card, fg=self.cfg.fg_text,
                activebackground=self.cfg.bg_card, activeforeground=self.cfg.fg_text,
                selectcolor=self.cfg.bg_panel,
                font=(self.cfg.font, 10),
            )
            cb.pack(anchor="w")
        chk("Drop duplicate rows", self.opt_drop_dup)
        chk("Trim string columns (strip)", self.opt_trim)
        chk("Coerce numeric-like strings to numeric", self.opt_coerce_num)
        chk("Winsorize numeric outliers", self.opt_winsor)

        tk.Label(left, text="Winsorize p (e.g., 0.01)", bg=self.cfg.bg_card, fg=self.cfg.fg_muted,
                 font=(self.cfg.font, 9)).pack(anchor="w", pady=(10, 2))
        self.winsor_p_var = tk.StringVar(value="0.01")
        tk.Entry(left, textvariable=self.winsor_p_var, bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 insertbackground=self.cfg.fg_text, relief="flat").pack(fill="x", ipady=8)

        tk.Label(left, text="Missing values strategy", bg=self.cfg.bg_card, fg=self.cfg.fg_muted,
                 font=(self.cfg.font, 9)).pack(anchor="w", pady=(12, 2))
        self.missing_var = tk.StringVar(value="median")
        ms_frame = tk.Frame(left, bg=self.cfg.bg_card)
        ms_frame.pack(fill="x")
        for v in ("none", "drop_rows", "median", "mean", "mode"):
            rb = tk.Radiobutton(
                ms_frame, text=v, value=v, variable=self.missing_var,
                bg=self.cfg.bg_card, fg=self.cfg.fg_text,
                activebackground=self.cfg.bg_card, activeforeground=self.cfg.fg_text,
                selectcolor=self.cfg.bg_panel, font=(self.cfg.font, 9)
            )
            rb.pack(anchor="w")

        btn_row = tk.Frame(left, bg=self.cfg.bg_card)
        btn_row.pack(fill="x", pady=(14, 0))

        tk.Button(
            btn_row, text="Apply & Preview", command=self.apply_cleaning,
            relief="flat", bg=self.cfg.accent, fg="#04110A", bd=0, padx=12, pady=10,
            font=(self.cfg.font, 10, "bold")
        ).pack(fill="x", pady=6)

        tk.Button(
            btn_row, text="Activate Cleaned Dataset", command=self.activate_cleaned,
            relief="flat", bg=self.cfg.bg_panel, fg=self.cfg.fg_text, bd=0, padx=12, pady=10,
            font=(self.cfg.font, 10, "bold")
        ).pack(fill="x", pady=6)

        tk.Button(
            btn_row, text="Save Cleaned CSV", command=self.save_cleaned_csv,
            relief="flat", bg=self.cfg.accent2, fg="#001018", bd=0, padx=12, pady=10,
            font=(self.cfg.font, 10, "bold")
        ).pack(fill="x", pady=6)

        # right preview
        right = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        tk.Label(right, text="Preview (Top 50 rows)", bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=10)

        self.clean_preview = tk.Text(
            right, wrap="none",
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
            insertbackground=self.cfg.fg_text,
            relief="flat", bd=0, font=(self.cfg.font_mono, 9)
        )
        self.clean_preview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.clean_preview.insert("1.0", "No cleaned dataset yet.")
        self.clean_preview.config(state="disabled")

        # bottom log
        log_card = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        log_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        log_card.grid_columnconfigure(0, weight=1)

        tk.Label(log_card, text="Cleaning Log", bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))

        self.clean_log_text = tk.Text(
            log_card, height=6, wrap="word",
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
            insertbackground=self.cfg.fg_text,
            relief="flat", bd=0, font=(self.cfg.font, 10)
        )
        self.clean_log_text.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.clean_log_text.insert("1.0", "Apply cleaning to generate a log.")
        self.clean_log_text.config(state="disabled")

    def apply_cleaning(self):
        if not self.state.has_data:
            messagebox.showwarning("Cleaning", "First open CSV (A) or activate a dataset.")
            return

        df = self.state.df_view

        try:
            winsor_p = float(self.winsor_p_var.get().strip())
            if not (0.0 < winsor_p < 0.5):
                raise ValueError
        except Exception:
            messagebox.showwarning("Cleaning", "Winsorize p must be a number in (0, 0.5).")
            return

        overlay = ProgressOverlay(self, self.cfg, "Cleaning data...")
        overlay.set("Applying pipeline (duplicates / missing / outliers / type fixes)...")

        opts = dict(
            drop_duplicates=bool(self.opt_drop_dup.get()),
            trim_strings=bool(self.opt_trim.get()),
            coerce_numeric=bool(self.opt_coerce_num.get()),
            missing_strategy=str(self.missing_var.get()),
            winsorize=bool(self.opt_winsor.get()),
            winsor_p=winsor_p,
        )

        def worker():
            try:
                cleaned, log = self.clean_engine.clean(df, **opts)
                self.state.df_clean = cleaned
                # also attach to report state
                if self.state.report_last is None:
                    self.state.report_last = {}
                self.state.report_last["clean_log"] = log

                def done():
                    overlay.close()
                    self._render_clean_preview(cleaned)
                    self._render_clean_log(log)
                    self._set_status("Cleaning completed (preview ready).")
                    _beep()
                self.after(0, done)
            except Exception as e:
                def err():
                    overlay.close()
                    messagebox.showerror("Cleaning Error", str(e))
                self.after(0, err)

        threading.Thread(target=worker, daemon=True).start()

    def _render_clean_preview(self, df: pd.DataFrame):
        self.clean_preview.config(state="normal")
        self.clean_preview.delete("1.0", tk.END)
        preview = df.head(50).to_string(index=False)
        self.clean_preview.insert("1.0", preview)
        self.clean_preview.config(state="disabled")

    def _render_clean_log(self, log: Dict[str, Any]):
        self.clean_log_text.config(state="normal")
        self.clean_log_text.delete("1.0", tk.END)
        lines = []
        b = log.get("before", {})
        a = log.get("after", {})
        lines.append(f"Before: rows={b.get('rows')} cols={b.get('cols')} missing_cells={b.get('missing_cells')} dup_rows={b.get('dup_rows')}")
        lines.append(f"After : rows={a.get('rows')} cols={a.get('cols')} missing_cells={a.get('missing_cells')} dup_rows={a.get('dup_rows')}")
        lines.append("")
        lines.append("Steps:")
        for s in log.get("steps", []):
            lines.append(f" - {s}")
        self.clean_log_text.insert("1.0", "\n".join(lines))
        self.clean_log_text.config(state="disabled")

    def activate_cleaned(self):
        try:
            self.data.set_active_clean()
            self._active_dataset_label.set("Active: Cleaned")
            self._set_status("Activated cleaned dataset.")
            self._select_tab("Health")
            self.refresh_health()
        except Exception as e:
            messagebox.showwarning("Activate", str(e))

    def save_cleaned_csv(self):
        if self.state.df_clean is None or self.state.df_clean.empty:
            messagebox.showwarning("Save", "No cleaned dataset available. Apply cleaning first.")
            return
        path = fd.asksaveasfilename(defaultextension=".csv", initialfile="cleaned.csv",
                                   filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.state.df_clean.to_csv(path, index=False)
            self._set_status(f"Saved cleaned CSV: {os.path.basename(path)}")
            messagebox.showinfo("Save", "Cleaned CSV saved successfully.")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    # -------------------------
    # Plots tab
    # -------------------------

    def _build_plots(self):
        root = self._tabs["Plots"]
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)
    
        card = Card(root, self.cfg, "Plots (Column Picker)")
        card.pack(fill="both", expand=True)
    
        body = tk.Frame(card, bg=self.cfg.bg_card)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
    
        # -------------------------
        # LEFT: Scrollable controls
        # -------------------------
        left_wrap = tk.Frame(body, bg=self.cfg.bg_card)
        left_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left_wrap.configure(width=360)
        left_wrap.pack_propagate(False)
    
        sf = ScrollableFrame(left_wrap, bg=self.cfg.bg_card)
        sf.pack(fill="both", expand=True)
    
        left = sf.inner  # put all left-side widgets in this
    
        # --- Section: Select columns (collapsible)
        sec_cols = CollapsibleSection(left, self.cfg, "Select columns", start_open=True)
        sec_cols.pack(fill="x", padx=4, pady=(6, 0))
    
        tk.Label(
            sec_cols.body, text="X column",
            bg=self.cfg.bg_card, fg=self.cfg.fg_muted, font=(self.cfg.font, 9)
        ).pack(anchor="w")
        self.x_var = tk.StringVar(value="")
        self.x_menu = tk.OptionMenu(sec_cols.body, self.x_var, "")
        self._style_optionmenu(self.x_menu)
        self.x_menu.pack(fill="x", pady=(2, 10))
    
        tk.Label(
            sec_cols.body, text="Y column (numeric for most plots)",
            bg=self.cfg.bg_card, fg=self.cfg.fg_muted, font=(self.cfg.font, 9)
        ).pack(anchor="w")
        self.y_var = tk.StringVar(value="")
        self.y_menu = tk.OptionMenu(sec_cols.body, self.y_var, "")
        self._style_optionmenu(self.y_menu)
        self.y_menu.pack(fill="x", pady=(2, 6))
    
        # --- Section: Plot type (collapsible)
        sec_type = CollapsibleSection(left, self.cfg, "Plot type", start_open=True)
        sec_type.pack(fill="x", padx=4, pady=(10, 0))
    
        self.plot_type = tk.StringVar(value="scatter")
        for v in ("scatter", "line", "hist", "box", "bar", "violin", "corr", "scatter_matrix"):
            tk.Radiobutton(
                sec_type.body, text=v, value=v, variable=self.plot_type,
                bg=self.cfg.bg_card, fg=self.cfg.fg_text,
                activebackground=self.cfg.bg_card, activeforeground=self.cfg.fg_text,
                selectcolor=self.cfg.bg_panel, font=(self.cfg.font, 9)
            ).pack(anchor="w")
    
        # --- Section: Corr options (collapsible)
        sec_corr = CollapsibleSection(left, self.cfg, "Corr options", start_open=False)
        sec_corr.pack(fill="x", padx=4, pady=(10, 0))
    
        # Corr option variables
        self.corr_method = tk.StringVar(value="pearson")
        self.corr_style = tk.StringVar(value="heatmap_full")
        self.corr_annot = tk.BooleanVar(value=True)
        self.corr_abs = tk.BooleanVar(value=False)     # show abs(corr)
        self.corr_topk = tk.StringVar(value="0")       # 0 means all
        self.corr_target = tk.StringVar(value="")      # optional target col for sorting
    
        # Method
        tk.Label(
            sec_corr.body, text="Method",
            bg=self.cfg.bg_card, fg=self.cfg.fg_text, font=(self.cfg.font, 9, "bold")
        ).pack(anchor="w", pady=(2, 2))
    
        for v in ("pearson", "spearman", "kendall"):
            tk.Radiobutton(
                sec_corr.body, text=v, value=v, variable=self.corr_method,
                bg=self.cfg.bg_card, fg=self.cfg.fg_text,
                activebackground=self.cfg.bg_card, activeforeground=self.cfg.fg_text,
                selectcolor=self.cfg.bg_panel, font=(self.cfg.font, 9)
            ).pack(anchor="w")
    
        # Style
        tk.Label(
            sec_corr.body, text="Style",
            bg=self.cfg.bg_card, fg=self.cfg.fg_text, font=(self.cfg.font, 9, "bold")
        ).pack(anchor="w", pady=(8, 2))
    
        style_menu = tk.OptionMenu(
            sec_corr.body, self.corr_style,
            "heatmap_full", "heatmap_lower", "sorted_by_target", "cluster"
        )
        self._style_optionmenu(style_menu)
        style_menu.pack(fill="x", pady=(2, 0))
    
        # Toggles
        tk.Checkbutton(
            sec_corr.body, text="Annotate values", variable=self.corr_annot,
            bg=self.cfg.bg_card, fg=self.cfg.fg_text,
            activebackground=self.cfg.bg_card, activeforeground=self.cfg.fg_text,
            selectcolor=self.cfg.bg_panel, font=(self.cfg.font, 9)
        ).pack(anchor="w", pady=(8, 0))
    
        tk.Checkbutton(
            sec_corr.body, text="Use absolute correlations", variable=self.corr_abs,
            bg=self.cfg.bg_card, fg=self.cfg.fg_text,
            activebackground=self.cfg.bg_card, activeforeground=self.cfg.fg_text,
            selectcolor=self.cfg.bg_panel, font=(self.cfg.font, 9)
        ).pack(anchor="w", pady=(2, 0))
    
        # Top-K
        tk.Label(
            sec_corr.body, text="Top-K (0 = all)",
            bg=self.cfg.bg_card, fg=self.cfg.fg_muted, font=(self.cfg.font, 9)
        ).pack(anchor="w", pady=(8, 2))
    
        tk.Entry(
            sec_corr.body, textvariable=self.corr_topk,
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
            insertbackground=self.cfg.fg_text, relief="flat"
        ).pack(fill="x", ipady=6)
    
        # Target column (optional)
        tk.Label(
            sec_corr.body, text="Target col for sorting (optional)",
            bg=self.cfg.bg_card, fg=self.cfg.fg_muted, font=(self.cfg.font, 9)
        ).pack(anchor="w", pady=(8, 2))
    
        self._corr_target_menu = tk.OptionMenu(sec_corr.body, self.corr_target, "")
        self._style_optionmenu(self._corr_target_menu)
        self._corr_target_menu.pack(fill="x", pady=(2, 0))
    
        # Auto-open Corr options when "corr" selected
        def _on_plot_type_change(*_):
            if self.plot_type.get() == "corr":
                if not sec_corr._open:
                    sec_corr.toggle()
        self.plot_type.trace_add("write", _on_plot_type_change)
    
        # --- Section: Actions (collapsible)
        sec_actions = CollapsibleSection(left, self.cfg, "Actions", start_open=True)
        sec_actions.pack(fill="x", padx=4, pady=(12, 10))
    
        tk.Button(
            sec_actions.body, text="Refresh Columns", command=self.refresh_plot_columns,
            relief="flat", bg=self.cfg.bg_panel, fg=self.cfg.fg_text, bd=0, padx=12, pady=10,
            font=(self.cfg.font, 10, "bold")
        ).pack(fill="x", pady=6)
    
        tk.Button(
            sec_actions.body, text="Plot", command=self.do_plot,
            relief="flat", bg=self.cfg.accent, fg="#04110A", bd=0, padx=12, pady=10,
            font=(self.cfg.font, 10, "bold")
        ).pack(fill="x", pady=6)
    
        # -------------------------
        # RIGHT: Plot canvas
        # -------------------------
        right = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        
        self._plot_right = right   # ✅ ADD
        
        tk.Label(right, text="Canvas", bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
                 font=(self.cfg.font, 10, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=8)
        
        self.fig = Figure(figsize=(6, 4), dpi=110)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Load data and plot")
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        
        tb = tk.Frame(right, bg=self.cfg.bg_panel)
        tb.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        
        self._plot_toolbar_frame = tb  # ✅ ADD
        
        self.toolbar = NavigationToolbar2Tk(self.canvas, tb)
        self.toolbar.update()


    def _reset_plot_canvas(self):
        """Hard reset canvas+toolbar to avoid ghost axes / leftover drawings."""
        try:
            if hasattr(self, "toolbar") and self.toolbar:
                try:
                    self.toolbar.destroy()
                except Exception:
                    pass
        except Exception:
            pass
    
        try:
            if hasattr(self, "canvas") and self.canvas:
                try:
                    self.canvas.get_tk_widget().destroy()
                except Exception:
                    pass
        except Exception:
            pass
    
        # recreate canvas + toolbar on the same figure
        self.canvas = FigureCanvasTkAgg(self.fig, master=self._plot_right)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
    
        self.toolbar = NavigationToolbar2Tk(self.canvas, self._plot_toolbar_frame)
        self.toolbar.update()



    def _style_optionmenu(self, om: tk.OptionMenu):
        om.configure(
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text, activebackground=self.cfg.bg_panel,
            activeforeground=self.cfg.fg_text, relief="flat", bd=0, highlightthickness=1,
            highlightbackground=self.cfg.border
        )
        om["menu"].configure(
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text, activebackground=self.cfg.accent2,
            activeforeground="#001018"
        )

    def refresh_plot_columns(self):
        if not self.state.has_data:
            messagebox.showwarning("Plots", "Load a dataset first.")
            return
        cols = self.data.cols()
        nums = self.data.numeric_cols()

        # X defaults to first column, Y defaults to first numeric column
        x_default = cols[0] if cols else ""
        y_default = nums[0] if nums else (cols[0] if cols else "")

        self._reset_optionmenu(self.x_menu, self.x_var, cols, x_default)
        self._reset_optionmenu(self.y_menu, self.y_var, nums if nums else cols, y_default)
        self._set_status("Plot columns refreshed.")
        # update corr target options too (numeric columns)
        try:
            self._reset_optionmenu(self._corr_target_menu, self.corr_target, [""] + nums, "")
        except Exception:
            pass


    def _reset_optionmenu(self, menu: tk.OptionMenu, var: tk.StringVar, values: List[str], default: str):
        m = menu["menu"]
        m.delete(0, "end")
        if not values:
            values = [""]
        for v in values:
            m.add_command(label=v, command=lambda vv=v: var.set(vv))
        var.set(default if default in values else values[0])

    def do_plot(self):
        if not self.state.has_data:
            messagebox.showwarning("Plots", "Load a dataset first.")
            return
    
        df = self.state.df_view
    
        x = (self.x_var.get() or "").strip()
        y = (self.y_var.get() or "").strip()
        p = (self.plot_type.get() or "").strip()
    
        # -------------------------
        # HARD RESET FIGURE (prevents ghost axes)
        # -------------------------
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
    
        # very important: reset canvas/toolbar so old drawings don't remain
        self._reset_plot_canvas()
    
        # -------------------------
        # Scatter / Line
        # -------------------------
        if p in ("scatter", "line"):
            if not x or not y:
                messagebox.showwarning("Plot", "Select X and Y columns.")
                return
            try:
                xdata = df[x]
                ydata = _to_numeric_safe(df[y])
                if p == "scatter":
                    self.ax.scatter(xdata, ydata, s=18)
                else:
                    self.ax.plot(xdata, ydata)
    
                self.ax.set_title(f"{p.title()} — {y} vs {x}")
                self.ax.set_xlabel(x)
                self.ax.set_ylabel(y)
                self.fig.tight_layout()
                self.canvas.draw_idle()
                self._set_status("Plot rendered.")
            except Exception as e:
                messagebox.showerror("Plot Error", str(e))
            return
    
        # -------------------------
        # Histogram
        # -------------------------
        if p == "hist":
            if not y:
                messagebox.showwarning("Plot", "Select a numeric Y column for histogram.")
                return
            try:
                ydata = _to_numeric_safe(df[y]).dropna()
                self.ax.hist(ydata, bins=30)
                self.ax.set_title(f"Histogram — {y}")
                self.ax.set_xlabel(y)
                self.ax.set_ylabel("Count")
                self.fig.tight_layout()
                self.canvas.draw_idle()
                self._set_status("Histogram rendered.")
            except Exception as e:
                messagebox.showerror("Plot Error", str(e))
            return
    
        # -------------------------
        # Boxplot
        # -------------------------
        if p == "box":
            if not y:
                messagebox.showwarning("Plot", "Select a numeric Y column for boxplot.")
                return
            try:
                ydata = _to_numeric_safe(df[y]).dropna()
                self.ax.boxplot(ydata, vert=True)
                self.ax.set_title(f"Boxplot — {y}")
                self.ax.set_ylabel(y)
                self.fig.tight_layout()
                self.canvas.draw_idle()
                self._set_status("Boxplot rendered.")
            except Exception as e:
                messagebox.showerror("Plot Error", str(e))
            return
    
        # -------------------------
        # Bar
        # -------------------------
        if p == "bar":
            if not x:
                messagebox.showwarning("Plot", "Select X column for bar chart.")
                return
            try:
                if y:
                    ydata = _to_numeric_safe(df[y])
                    tmp = pd.DataFrame({"x": df[x], "y": ydata}).dropna()
                    g = tmp.groupby("x")["y"].mean().sort_values(ascending=False).head(30)
                    self.ax.bar(g.index.astype(str), g.values)
                    self.ax.set_title(f"Bar — mean({y}) by {x} (top 30)")
                    self.ax.set_xlabel(x)
                    self.ax.set_ylabel(f"mean({y})")
                    self.ax.tick_params(axis="x", labelrotation=45)
                else:
                    vc = df[x].astype(str).value_counts().head(30)
                    self.ax.bar(vc.index, vc.values)
                    self.ax.set_title(f"Bar — {x} value counts (top 30)")
                    self.ax.set_xlabel(x)
                    self.ax.set_ylabel("Count")
                    self.ax.tick_params(axis="x", labelrotation=45)
    
                self.fig.tight_layout()
                self.canvas.draw_idle()
                self._set_status("Bar chart rendered.")
            except Exception as e:
                messagebox.showerror("Plot Error", str(e))
            return
    
        # -------------------------
        # Violin
        # -------------------------
        if p == "violin":
            if not y:
                messagebox.showwarning("Plot", "Select a numeric Y column for violin plot.")
                return
            try:
                ynum = _to_numeric_safe(df[y])
    
                if x:
                    tmp = pd.DataFrame({"x": df[x].astype(str), "y": ynum}).dropna()
                    top_groups = tmp["x"].value_counts().head(12).index.tolist()
                    tmp = tmp[tmp["x"].isin(top_groups)]
                    groups = [tmp.loc[tmp["x"] == g, "y"].values for g in top_groups]
    
                    self.ax.violinplot(groups, showmeans=True, showmedians=True)
                    self.ax.set_xticks(range(1, len(top_groups) + 1))
                    self.ax.set_xticklabels(top_groups, rotation=45, ha="right")
                    self.ax.set_title(f"Violin — {y} grouped by {x} (top 12 groups)")
                    self.ax.set_ylabel(y)
                else:
                    data = ynum.dropna().values
                    self.ax.violinplot([data], showmeans=True, showmedians=True)
                    self.ax.set_xticks([1])
                    self.ax.set_xticklabels([y])
                    self.ax.set_title(f"Violin — {y}")
                    self.ax.set_ylabel(y)
    
                self.fig.tight_layout()
                self.canvas.draw_idle()
                self._set_status("Violin plot rendered.")
            except Exception as e:
                messagebox.showerror("Plot Error", str(e))
            return
    
        # -------------------------
        # Scatter Matrix (FIXED: draw on self.fig, not pyplot/new figure)
        # -------------------------
        if p == "scatter_matrix":
            try:
                num = df.select_dtypes(include="number").copy()
                if num.shape[1] < 2:
                    messagebox.showwarning("Plot", "Need at least 2 numeric columns for scatter matrix.")
                    return
    
                cols = list(num.columns)[:6]
                num = num[cols].dropna()
                k = len(cols)
    
                # rebuild figure grid on self.fig
                self.fig.clear()
                axes = self.fig.subplots(nrows=k, ncols=k, squeeze=False)
    
                scatter_matrix(
                    num,
                    ax=axes,
                    figsize=(min(12, 2.2 * k), min(12, 2.2 * k)),
                    diagonal="hist"
                )
    
                self.fig.tight_layout()
                self.canvas.draw_idle()
                self._set_status("Scatter matrix rendered.")
            except Exception as e:
                messagebox.showerror("Plot Error", str(e))
            return
    
        # -------------------------
        # Correlation Matrix (no overflow + no ghosts)
        # -------------------------
        if p == "corr":
            try:
                num = df.select_dtypes(include="number")
                if num.shape[1] < 2:
                    messagebox.showwarning("Corr", "Need at least 2 numeric columns.")
                    return
    
                method = (self.corr_method.get() or "pearson").strip()
                style = (self.corr_style.get() or "heatmap_full").strip()
                use_abs = bool(self.corr_abs.get())
                annotate = bool(self.corr_annot.get())
    
                try:
                    topk = int(str(self.corr_topk.get()).strip() or "0")
                    if topk < 0:
                        topk = 0
                except Exception:
                    topk = 0
    
                corr = num.corr(method=method, numeric_only=True)
                if use_abs:
                    corr = corr.abs()
    
                if topk and topk < corr.shape[0]:
                    strength = corr.abs().sum(axis=1).sort_values(ascending=False)
                    keep = list(strength.index[:topk])
                    corr = corr.loc[keep, keep]
    
                target = (self.corr_target.get() or "").strip()
                if style == "sorted_by_target":
                    t = target if target in corr.columns else ""
                    if not t:
                        yy = (self.y_var.get() or "").strip()
                        if yy in corr.columns:
                            t = yy
                    if t:
                        order = corr[t].abs().sort_values(ascending=False).index.tolist()
                        corr = corr.loc[order, order]
    
                if style == "cluster":
                    try:
                        import numpy as np
                        from scipy.cluster.hierarchy import linkage, leaves_list
                        dist = 1 - corr.values
                        iu = np.triu_indices(dist.shape[0], 1)
                        condensed = dist[iu]
                        Z = linkage(condensed, method="average")
                        order = leaves_list(Z).tolist()
                        labels = corr.index.tolist()
                        new_labels = [labels[i] for i in order]
                        corr = corr.loc[new_labels, new_labels]
                    except Exception:
                        strength = corr.abs().sum(axis=1).sort_values(ascending=False)
                        keep = list(strength.index)
                        corr = corr.loc[keep, keep]
    
                mask_upper = (style == "heatmap_lower")
    
                import numpy as np
                M = corr.values.copy()
                if mask_upper:
                    mu = np.triu(np.ones_like(M, dtype=bool), k=1)
                    M = np.where(mu, np.nan, M)
    
                n = corr.shape[0]
                if n <= 8:
                    tick_fs, ann_fs = 11, 10
                elif n <= 14:
                    tick_fs, ann_fs = 9, 8
                else:
                    tick_fs, ann_fs = 7, 6
                if n >= 22:
                    annotate = False
    
                self.fig.clear()
                ax = self.fig.add_subplot(111)
    
                im = ax.imshow(M, vmin=-1 if not use_abs else 0, vmax=1)
                ax.set_title(f"Correlation Matrix ({method})", fontsize=max(11, tick_fs + 2))
    
                ax.set_xticks(range(n))
                ax.set_yticks(range(n))
                ax.set_xticklabels(list(corr.columns), rotation=45, ha="right", fontsize=tick_fs)
                ax.set_yticklabels(list(corr.index), fontsize=tick_fs)
    
                if annotate:
                    for i in range(n):
                        for j in range(n):
                            v = M[i, j]
                            if np.isnan(v):
                                continue
                            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=ann_fs)
    
                # colorbar controlled
                cbar = self.fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
                cbar.ax.tick_params(labelsize=tick_fs)
    
                # prevent overflow
                self.fig.subplots_adjust(left=0.12, right=0.88, top=0.88, bottom=0.18)
    
                self.canvas.draw_idle()
                self._set_status("Correlation matrix rendered.")
            except Exception as e:
                import traceback
                traceback.print_exc()
                messagebox.showerror("Plot Error", str(e))
            return
    
        messagebox.showwarning("Plot", f"Unknown plot type: {p}")




    # -------------------------
    # Compare tab
    # -------------------------

    def _build_compare(self):
        root = self._tabs["Compare"]
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        card = Card(root, self.cfg, "Compare CSV A vs CSV B (Schema + Drift)")
        card.pack(fill="both", expand=True)

        body = tk.Frame(card, bg=self.cfg.bg_card)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=1)

        top = tk.Frame(body, bg=self.cfg.bg_card)
        top.grid(row=0, column=0, sticky="ew", pady=(8, 10))
        top.grid_columnconfigure(1, weight=1)
        
        tk.Button(
            top, text="Run Compare", command=self.run_compare,
            relief="flat", bg=self.cfg.accent, fg="#04110A", bd=0, padx=14, pady=10,
            font=(self.cfg.font, 10, "bold")
        ).grid(row=0, column=0, sticky="w")

        self.compare_hint = tk.Label(
            top,
            text="Load CSV (A) and CSV (B), then click Run Compare.",
            bg=self.cfg.bg_card,
            fg=self.cfg.fg_muted,
            font=(self.cfg.font, 10),
        )
        self.compare_hint.grid(row=0, column=1, sticky="w", padx=10)

        # result area
        host = tk.Frame(body, bg=self.cfg.bg_panel, highlightthickness=1, highlightbackground=self.cfg.border)
        host.grid(row=1, column=0, sticky="nsew")
        host.grid_rowconfigure(0, weight=1)
        host.grid_columnconfigure(0, weight=1)

        self.compare_text = tk.Text(
            host, wrap="word",
            bg=self.cfg.bg_panel, fg=self.cfg.fg_text,
            insertbackground=self.cfg.fg_text,
            relief="flat", bd=0, font=(self.cfg.font, 10)
        )
        self.compare_text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.compare_text.insert("1.0", "No compare results yet.")
        self.compare_text.config(state="disabled")

    def run_compare(self):
        if self.state.df_a is None or self.state.df_a.empty:
            messagebox.showwarning("Compare", "Dataset A is not loaded. Use 'Open CSV (A)'.")
            return
        if self.state.df_b is None or self.state.df_b.empty:
            messagebox.showwarning("Compare", "Dataset B is not loaded. Use 'Open CSV (B)'.")
            return
    
        overlay = ProgressOverlay(self, self.cfg, "Comparing datasets...")
        overlay.set("Checking schema changes and drift (missingness + numeric stats)...")
    
        df_a = self.state.df_a
        df_b = self.state.df_b
    
        def worker():
            try:
                cmp = self.compare_engine.compare(df_a, df_b)
                if self.state.report_last is None:
                    self.state.report_last = {}
                self.state.report_last["compare"] = cmp
    
                def done(cmp_result=cmp):
                    overlay.close()
                    self._render_compare(cmp_result)
                    self._set_status("Compare completed.")
                    _beep()
    
                self.after(0, done)
    
            except Exception as e:
                def err(ex=e):  # ✅ fix: bind exception into default arg
                    overlay.close()
                    messagebox.showerror("Compare Error", str(ex))
    
                self.after(0, err)
    
        threading.Thread(target=worker, daemon=True).start()


    def _render_compare(self, cmp: Dict[str, Any]):
        sch = cmp.get("schema", {})
        added = sch.get("added_columns_in_B", [])
        removed = sch.get("removed_columns_in_B", [])
        md = cmp.get("missing_drift_top", [])
        nd = cmp.get("numeric_drift_top", [])
    
        lines: List[str] = []
        lines.append("COMPARE SUMMARY")
        lines.append("-" * 60)
        lines.append(f"A: rows={cmp.get('rows_a')} cols={cmp.get('cols_a')}")
        lines.append(f"B: rows={cmp.get('rows_b')} cols={cmp.get('cols_b')}")
        lines.append("")
        lines.append("SCHEMA CHANGES (B vs A)")
        lines.append(f"  Added columns in B   : {', '.join(added) if added else '—'}")
        lines.append(f"  Removed columns in B : {', '.join(removed) if removed else '—'}")
        lines.append("")
    
        lines.append("TOP MISSINGNESS DRIFT (common columns)")
        if md:
            for c, da, db, dd in md[:12]:
                lines.append(f"  {c}: A={da*100:.2f}%  B={db*100:.2f}%  Δ={dd*100:+.2f}%")
        else:
            lines.append("  —")
        lines.append("")
    
        lines.append("TOP NUMERIC DRIFT (common numeric columns)")
        if nd:
            for c, ma, mb, dm, sa, sb, ds in nd[:12]:
                lines.append(
                    f"  {c}: mean A={ma:.4g}  mean B={mb:.4g}  Δmean={dm:+.4g} | std A={sa:.4g} std B={sb:.4g}"
                )
        else:
            lines.append("  —")
    
        self.compare_text.config(state="normal")
        self.compare_text.delete("1.0", tk.END)
        self.compare_text.insert("1.0", "\n".join(lines))
        self.compare_text.config(state="disabled")


    # -------------------------
    # CSV Load / Active dataset
    # -------------------------
    
    def open_csv_a(self):
        path = fd.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return

        overlay = ProgressOverlay(self, self.cfg, "Loading CSV (A)...")
        overlay.set("Reading file with robust encoding/delimiter detection...")
    
        def worker():
            try:
                df = self.data.load_a(path)
    
                def done(df=df, path=path):
                    overlay.close()
                    self._active_dataset_label.set("Active: A")
                    self._set_status(
                        f"Loaded A: {os.path.basename(path)} | rows={len(df):,} cols={len(df.columns):,}"
                    )
                    # Refresh plot columns for convenience
                    try:
                        self.refresh_plot_columns()
                    except Exception:
                        pass
                    # Move user to health tab and profile automatically
                    self._select_tab("Health")
                    self.refresh_health()
    
                self.after(0, done)
    
            except Exception as e:
                # IMPORTANT: bind the exception into the callback default arg
                def err(err_msg=str(e)):
                    overlay.close()
                    messagebox.showerror("Open CSV (A)", err_msg)
    
                self.after(0, err)
    
        threading.Thread(target=worker, daemon=True).start()


    def open_csv_b(self):
        path = fd.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
    
        overlay = ProgressOverlay(self, self.cfg, "Loading CSV (B)...")
        overlay.set("Reading file with robust encoding/delimiter detection...")
    
        def worker():
            try:
                df = self.data.load_b(path)
    
                def done(df=df, path=path):
                    overlay.close()
                    self._set_status(
                        f"Loaded B: {os.path.basename(path)} | rows={len(df):,} cols={len(df.columns):,}"
                    )
                    self._select_tab("Compare")
    
                self.after(0, done)
    
            except Exception as e:
                # IMPORTANT: bind the exception into the callback default arg
                def err(err_msg=str(e)):
                    overlay.close()
                    messagebox.showerror("Open CSV (B)", err_msg)
    
                self.after(0, err)
    
        threading.Thread(target=worker, daemon=True).start()
    
    
    def export_report(self):
        if self.state.df_a is None or self.state.df_a.empty:
            messagebox.showwarning("Report", "Load CSV (A) first.")
            return
    
        # Ensure we have at least a profile
        if self.state.report_last is None or "profile" not in self.state.report_last:
            overlay = ProgressOverlay(self, self.cfg, "Preparing report...")
            overlay.set("Generating profile for report...")
    
            def worker_profile():
                try:
                    df_for_profile = self.state.df_view if self.state.df_view is not None else self.state.df_a
                    prof = self.profile_engine.profile(df_for_profile)
    
                    if self.state.report_last is None:
                        self.state.report_last = {}
                    self.state.report_last["profile"] = prof
    
                    def done():
                        overlay.close()
                        self._export_report_dialog()
    
                    self.after(0, done)
    
                except Exception as e:
                    # IMPORTANT: bind the exception into the callback default arg
                    def err(err_msg=str(e)):
                        overlay.close()
                        messagebox.showerror("Report Error", err_msg)
    
                    self.after(0, err)
    
            threading.Thread(target=worker_profile, daemon=True).start()
        else:
            self._export_report_dialog()


    

    def _export_report_dialog(self):
        path = fd.asksaveasfilename(
            defaultextension=".html",
            initialfile="green_report.html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")]
        )
        if not path:
            return

        overlay = ProgressOverlay(self, self.cfg, "Exporting report...")
        overlay.set("Building professional HTML report...")

        def worker():
            try:
                prof = (self.state.report_last or {}).get("profile", {})
                clean_log = (self.state.report_last or {}).get("clean_log", None)
                cmp = (self.state.report_last or {}).get("compare", None)

                file_name = os.path.basename(self.state.file_a or "dataset.csv")
                self.report_engine.export_html(
                    self.cfg,
                    path=path,
                    file_name=file_name,
                    profile=prof,
                    clean_log=clean_log,
                    compare=cmp,
                )

                def done():
                    overlay.close()
                    self._set_status(f"Report exported: {os.path.basename(path)}")
                    messagebox.showinfo("Report", "HTML report exported successfully.")
                    _beep()
                self.after(0, done)
            except Exception as e:
                def err(err_msg=str(e)):
                    overlay.close()
                    messagebox.showerror("Open CSV (B)", err_msg)
                self.after(0, err)


        threading.Thread(target=worker, daemon=True).start()

    # -------------------------
    # Status / Close
    # -------------------------

    def _set_status(self, text: str):
        self._status.set(text)

    def _on_close(self):
        if messagebox.askokcancel("Close", "Do you really want to quit?"):
            try:
                self.destroy()
            except Exception:
                pass


def main():
    cfg = AppConfig()

    app = GreenProApp(cfg)
    app.withdraw()

    def start_main():
        app.deiconify()
        app.lift()
        app.focus_force()
        app._set_status("Ready")

    splash = SplashScreen(app, cfg, on_start=start_main)
    app.mainloop()


if __name__ == "__main__":
    main()