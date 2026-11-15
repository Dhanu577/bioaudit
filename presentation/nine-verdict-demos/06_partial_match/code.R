dispPriorVar <- pmax(argminKL, 0.5)
dispPriorVar <- pmax((varLogDispEsts - expVarLogDisp), 0.25)
