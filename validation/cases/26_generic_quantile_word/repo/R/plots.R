ylim <- c(-1,1) * quantile(abs(py[is.finite(py)]), probs=0.99) * 1.1
