import scanpy as sc
from statsmodels.stats.multitest import multipletests

MIN_READ_LENGTH = 20


def run(adata, pvals, alpha=0.01):
    reject, padj, _, _ = multipletests(pvals, alpha=alpha, method="fdr_bh")
    sc.pp.neighbors(adata, n_neighbors=10)
    sc.tl.leiden(adata, resolution=1.0)
