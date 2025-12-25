# GREEN Pro
<img width="400" height="400" alt="GREEN Pro Screenshot"
src="https://github.com/user-attachments/assets/5eb0d6c2-a790-47dc-b1e9-5a4444119701" />


**GREEN Pro** is a professional, offline desktop application for data quality assessment, cleaning, visualization, dataset comparison, and reporting.  
It is built for data scientists, analysts, and researchers who need a reliable and fully local tool for CSV-based data analysis.

GREEN Pro is a standalone Python desktop application designed to support the full lifecycle of exploratory data analysis (EDA) and data quality assurance for CSV datasets.

All processing is performed locally. **No data is uploaded or sent to external services.**

---

## Overview

The tool focuses on:

- Data health diagnostics
- Robust data cleaning pipelines
- Flexible plotting and correlation analysis
- Dataset comparison and drift detection
- Professional HTML report generation

---

## Features

### 📊 Data Health Scoring
- Missing values analysis
- Duplicate detection
- Outlier detection (robust MAD-based method)
- Skewness detection
- Interpretable quality score (0–100)

### 🧹 Cleaning Pipeline
- Duplicate row removal
- Missing value handling (drop, mean, median, mode)
- Numeric type coercion
- Winsorization for numeric outliers
- Preview before activation
- Export cleaned dataset as CSV

### 📈 Visualization & Plots
- Scatter, Line, Histogram, Box, Bar, and Violin plots
- Scatter matrix for multivariate inspection
- Advanced correlation matrix:
  - Pearson / Spearman / Kendall methods
  - Absolute correlation option
  - Top-K variable filtering
  - Target-based sorting
  - Clustered correlation (optional)
  - Adaptive sizing and styling

### 🔍 Dataset Comparison (A/B)
- Schema changes (added / removed columns)
- Missingness drift analysis
- Numeric mean and variance drift

### 📝 Professional Reporting
- Export clean and self-contained HTML reports
- Includes:
  - Data health summary
  - Detected issues
  - Recommendations
  - Top correlations
  - Cleaning log
  - Dataset comparison results

### 🖥️ Desktop & Offline
- Tkinter-based graphical user interface
- No internet connection required
- Cross-platform support (Windows / Linux / macOS)

---

## Architecture

GREEN Pro follows a modular and extensible architecture:

- UI Layer (Tkinter)
- State Management Layer
- Data Controller
- Analysis Engines:
  - Profile Engine
  - Cleaning Engine
  - Compare Engine
  - Report Engine
- Visualization Layer (Matplotlib)

All long-running operations are executed in background threads to keep the UI responsive.

---

## Technology Stack

- Python 3.9+
- Tkinter (GUI)
- Pandas (data processing)
- Matplotlib (visualization)
- NumPy (numerical operations)
- SciPy (optional, for correlation clustering)

No external services or cloud dependencies are used.

---

## Installation

### Application Preview



<img width="900" height="600" alt="image" src="https://github.com/user-attachments/assets/ea3cfaa9-0051-4909-9e8e-89e7ff6260ee" />

<img width="900" height="600" alt="image" src="https://github.com/user-attachments/assets/dbe75c6d-32f3-4754-b2b2-9bf408b38fc4" />

<img width="400" height="600" alt="image" src="https://github.com/user-attachments/assets/102c45ef-baa5-4e74-bdc4-26b2a45981e3" />

<img width="900" height="600" alt="image" src="https://github.com/user-attachments/assets/5a6fce97-9084-4354-a788-1eee43042e13" />

<img width="900" height="600" alt="image" src="https://github.com/user-attachments/assets/f09eefcd-0c72-4868-b88a-e15ff58370e9" />

<img width="700" height="800" alt="image" src="https://github.com/user-attachments/assets/98432575-9629-4da5-97a7-c58f55efdbe9" />



### 1. Clone the repository
```bash
git clone https://github.com/AliRezaKhatibi/GREEN-Pro
cd green-pro
```
### 2. Install dependencies
```bash
pip install pandas matplotlib numpy scipy
```
### 3. Run the application
```bash
python green_app_pro.py
```

