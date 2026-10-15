dispPriorVar <- pmax(argminKL, 0.25)
dispPriorVar <- pmax((varLogDispEsts - expVarLogDisp), 0.25)
