"""Offline recommendation package."""

import os

# implicit already parallelises ALS. Limiting BLAS avoids nested thread pools on laptops.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
