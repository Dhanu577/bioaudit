import scanpy as sc
from statsmodels.stats.multitest import multipletests

MIN_READ_LENGTH = 50


def run(adata, pvals, alpha=0.05):
    reject, padj, _, _ = multipletests(pvals, alpha=alpha, method="fdr_bh")
    sc.pp.neighbors(adata, n_neighbors=15)
    sc.tl.leiden(adata, resolution=0.8)
