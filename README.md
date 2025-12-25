# GREEN-Pro
**GREEN Pro** is a professional, offline desktop application for data quality assessment, cleaning, visualization, dataset comparison, and reporting — built for data scientists, analysts, and researchers.
GREEN Pro is a standalone Python desktop application designed to support the full lifecycle of exploratory data analysis (EDA) and data quality assurance for CSV datasets.

The tool focuses on:
- Data health diagnostics
- Robust data cleaning pipelines
- Flexible plotting and correlation analysis
- Dataset comparison and drift detection
- Professional HTML report generation

All processing is performed locally. No data is uploaded or sent to external services.
## Features

- 📊 **Data Health Scoring**
  - Missing values analysis
  - Duplicate detection
  - Outlier detection (robust MAD)
  - Skewness detection
  - Quality score (0–100)

- 🧹 **Cleaning Pipeline**
  - Duplicate removal
  - Missing value handling (drop, mean, median, mode)
  - Numeric coercion
  - Winsorization for outliers
  - Preview before activation
  - Export cleaned dataset

- 📈 **Visualization & Plots**
  - Scatter, Line, Histogram, Box, Bar, Violin plots
  - Scatter matrix
  - Advanced correlation matrix:
    - Pearson / Spearman / Kendall
    - Absolute correlations
    - Top-K filtering
    - Target-based sorting
    - Clustered correlation
    - Adaptive sizing and styling

- 🔍 **Dataset Comparison (A/B)**
  - Schema changes
  - Missingness drift
  - Numeric mean and variance drift

- 📝 **Professional Reporting**
  - Export clean HTML reports
  - Includes data health summary, issues, recommendations, correlations, cleaning log, and comparison results

- 🖥️ **Desktop & Offline**
  - Tkinter-based GUI
  - No internet required
  - Cross-platform (Windows / Linux / macOS)
 
  - ## Architecture

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

All long-running tasks are executed in background threads to keep the UI responsive.


## Technology Stack

- Python 3.9+
- Tkinter (GUI)
- Pandas (data processing)
- Matplotlib (visualization)
- NumPy (numeric operations)
- SciPy (optional, for clustering)

No external services or cloud dependencies.

## Installation

1. Clone the repository:
```bash
git clone https://github.com/your-username/green-pro.git
cd green-pro

pip install pandas matplotlib numpy scipy

<img width="1025" height="933" alt="logo" src="https://github.com/user-attachments/assets/0d627fec-6bde-4946-ab1c-5a5a4f9eebd1" />

python green_app_pro.py


---

## ▶️ Usage Workflow
```markdown
## Typical Workflow

1. Open CSV (A)
2. Review **Data Health** tab
3. Apply **Cleaning Pipeline**
4. Activate cleaned dataset (optional)
5. Explore data using **Plots**
6. Load CSV (B) for comparison (optional)
7. Export professional **HTML Report**

## Development Status

Current Version: **v0.1.0**

This is the initial stable release.
The application is actively evolving and new features will be added in future versions.

## Roadmap

- v0.2.0
  - Additional plot styles
  - Export plots as images
  - Enhanced cleaning presets

- v0.3.0
  - Statistical tests
  - Feature importance diagnostics
  - Large dataset optimizations

- v1.0.0
  - Production-ready release
  - Plugin system
  - Extended reporting templates

## Limitations

- Designed primarily for CSV files
- Extremely large datasets may require optimization
- Correlation clustering requires SciPy (optional)

## License

This project is released under the MIT License.

## Author

Developed by **GREEN Team**

For academic, research, and professional data analysis use.

v0.1.0 — Initial Stable Release

Initial public release of GREEN Pro.

Includes:
- Data health diagnostics
- Cleaning pipeline with preview
- Advanced plotting and correlation analysis
- Dataset comparison (A/B)
- Professional HTML report export

All processing is fully offline.

feat: initial stable release of GREEN Pro (v0.1.0)






