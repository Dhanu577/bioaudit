"""Curated method concepts: paper phrase -> code calls/imports that implement it.

Rules are matched against *call and import names only* (never file paths or
comments), so a claim cannot be satisfied by a directory that merely carries the
tool's name. Extend this table; every entry should get a validation case.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    id: str
    claim_re: str
    calls: tuple[str, ...]
    imports: tuple[str, ...] = ()


def _c(id, claim_re, calls, imports=()):
    return Concept(id, claim_re, tuple(calls.split()), tuple(imports.split()))


CONCEPTS: tuple[Concept, ...] = (
    _c("deseq2", r"\bDESeq2?\b", "DESeq DESeqDataSetFromMatrix DESeqDataSet nbinomWaldTest nbinomLRT estimateSizeFactors estimateDispersions lfcShrink", "DESeq2"),
    _c("negative_binomial", r"negative[- ]binomial", "nbinomWaldTest nbinomLRT glm.nb DESeq glmFit glmQLFit NegativeBinomial NegativeBinomialP", "MASS"),
    _c("shrinkage", r"\bshrink(?:age|ing)?\b|\bshrunk(?:en)?\b", "lfcShrink estimateDispersions estimateDisp eBayes squeezeVar", ""),
    _c("limma_voom", r"\blimma\b|\bvoom\b", "voom lmFit eBayes topTable makeContrasts", "limma"),
    _c("edger", r"\bedgeR\b", "DGEList calcNormFactors estimateDisp glmQLFit glmQLFTest exactTest glmFit glmLRT", "edgeR"),
    # DESeq/topTable/glmQLFTest/glmLRT adjust p-values with BH internally.
    _c("multiple_testing", r"false discovery|\bFDR\b|Benjamini|Bonferroni|multiple (?:testing|comparison)|adjusted p|p-value adjust", "p.adjust multipletests fdrcorrection false_discovery_control qvalue DESeq topTable glmQLFTest glmLRT", "qvalue"),
    _c("pca", r"principal component|\bPCA\b", "prcomp princomp PCA pca RunPCA irlba TruncatedSVD", ""),
    _c("umap", r"\bUMAP\b", "umap UMAP RunUMAP", "umap"),
    _c("tsne", r"t-?SNE", "TSNE tsne Rtsne RunTSNE", "Rtsne"),
    _c("leiden", r"\bLeiden\b", "leiden find_partition RBConfigurationVertexPartition", "leidenalg"),
    _c("louvain", r"\bLouvain\b", "louvain community_louvain cluster_louvain best_partition FindClusters", "louvain"),
    _c("kmeans", r"k-?means", "KMeans kmeans MiniBatchKMeans", ""),
    _c("hierarchical_clustering", r"hierarchical clustering", "hclust linkage AgglomerativeClustering fcluster", ""),
    _c("random_forest", r"random forests?", "RandomForestClassifier RandomForestRegressor randomForest ranger", ""),
    _c("svm", r"support vector|\bSVMs?\b", "SVC LinearSVC SVR svm", ""),
    _c("logistic_regression", r"logistic regression", "LogisticRegression glm Logit", ""),
    _c("linear_model", r"(?<!generalized )(?<!generalised )linear (?:mixed[- ]effects? )?models?|(?<!generalized )linear regression", "lm lmer lme OLS ols LinearRegression mixedlm", ""),
    _c("cox", r"cox (?:proportional|regression)", "coxph CoxPHFitter", ""),
    _c("kaplan_meier", r"kaplan[- ]meier", "survfit KaplanMeierFitter", ""),
    _c("wilcoxon", r"wilcoxon|mann[- ]whitney", "wilcox.test mannwhitneyu wilcoxon ranksums", ""),
    _c("t_test", r"\bt-?tests?\b|student'?s t", "t.test ttest_ind ttest_rel ttest_1samp", ""),
    _c("fisher_exact", r"fisher'?s? exact", "fisher.test fisher_exact", ""),
    _c("chi_square", r"chi-?square", "chisq.test chi2_contingency", ""),
    _c("anova", r"\bANOVA\b", "aov anova f_oneway anova_lm", ""),
    _c("normalization", r"library[- ]size|log-?normali[sz]|counts per million|\bCPM\b|size factors?", "normalize_total NormalizeData log1p cpm calcNormFactors estimateSizeFactors sizeFactors", ""),
    _c("highly_variable_genes", r"highly variable", "highly_variable_genes FindVariableFeatures VariableFeatures modelGeneVar getTopHVGs", ""),
    _c("batch_correction", r"batch (?:correction|effect)|harmony|ComBat|\bMNN\b", "combat ComBat ComBat_seq RunHarmony run_harmony HarmonyMatrix fastMNN bbknn", "harmony"),
    _c("cross_validation", r"cross-?validation|k-?fold", "cross_val_score cross_validate KFold StratifiedKFold GridSearchCV createFolds vfold_cv trainControl", ""),
    _c("permutation_bootstrap", r"permutation|bootstrap", "permutation_test resample bootstrap boot", ""),
    _c("multithreading", r"multi-?thread|multi-?process|parallel(?:i[sz]ed|ly)?\b(?! sequenc)", "std::thread std::async omp pthread_create ThreadPool mclapply parLapply foreach multiprocessing Pool ProcessPoolExecutor ThreadPoolExecutor Parallel bplapply dask", ""),
)

# Phrases that mean the sentence is about *someone else's* tool, not this repo.
COMPARISON_RE = r"compar(?:e|es|ed|ing|ison)|versus|\bvs\.?\b|\bthan\b|baseline|unlike|outperform|in contrast|competing|other (?:tools|methods)|existing (?:tools|methods)"
# The sentence must read as "this work does X" (first person / this tool / passive 'implemented').
IMPLEMENTATION_CUE_RE = (
    r"\b(?:we|our|this (?:tool|package|software|method|pipeline|work|study)|"
    r"(?:is|are|was|were) (?:implemented|computed|calculated|performed|applied)|"
    r"implemented (?:in|as|using)|"
    r"(?:is|are|was|were) (?:\w+ ){0,2}\w+(?:ed|en)(?: \w+){0,4} (?:using|with|by|via))\b"
)
# Sentences describing experiments/datasets rather than code behaviour.
EXPERIMENT_RE = (
    r"simulat|benchmark|replicat|individuals|cohort|verification set|evaluation set|"
    r"\bdata ?sets?\b|\b(?:chose|selected|obtained|downloaded|sequenced)\b|"
    r"libraries were|were prepared|preamplification|cell lines?|uniquely mapped|million (?:tags|reads)|"
    r"\bGHz\b|\bprocessor\b|\bCPUs?\b|per (?:minute|second|hour)|"
    r"\bwe (?:ran|evaluated|tested|measured|benchmarked)\b|\bran (?:each|both)\b|taskset|"
    r"\bdots?\b|\bplotted\b|\bdepicted\b|experiments?\b|\bvaried\b|\bvarying\b|\bsweeps?\b"
)

# Tools whose mention (without the audited tool's own name) marks a sentence as being about someone else's software.
KNOWN_TOOLS = frozenset(
    "cutadapt trimmomatic fastqc afterqc soapnuke fastp kraken kraken2 bracken centrifuge kaiju blast diamond "
    "bowtie bowtie2 bwa star hisat hisat2 salmon kallisto deseq deseq2 edger limma voom dss samtools bedtools "
    "macs macs2 macs3 homer sicer scanpy seurat umis umitools multiqc jellyfish mason metaphlan clark cuffdiff "
    "cufflinks stringtie tophat picard gatk bcftools freebayes ebseq samseq cellranger".split()
)
