library(DESeq2)
dds <- DESeqDataSetFromMatrix(countData = counts, colData = meta, design = ~ condition)
dds <- DESeq(dds)
res <- results(dds, alpha = 0.05)
