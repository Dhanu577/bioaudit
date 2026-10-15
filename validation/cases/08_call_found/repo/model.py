from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

def fit(X, y):
    clf = RandomForestClassifier(n_estimators=100)
    return cross_val_score(clf, X, y, cv=5)
