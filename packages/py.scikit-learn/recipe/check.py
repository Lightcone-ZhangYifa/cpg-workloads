#!/usr/bin/env python3
"""Installed functional check for scikit-learn; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(sklearn, work):
    """Fit known linear/classification fixtures and check estimator validation."""
    np = installed_module("numpy")
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.exceptions import NotFittedError
    x = np.arange(6, dtype=float).reshape(-1, 1)
    model = LinearRegression().fit(x, 2*x[:, 0]+3)
    require(np.allclose(model.predict([[7], [8]]), [17, 19], atol=1e-10, rtol=0), "Regression oracle mismatch")
    classifier = make_pipeline(StandardScaler(), LogisticRegression(random_state=0))
    classifier.fit([[-3], [-2], [-1], [1], [2], [3]], [0, 0, 0, 1, 1, 1])
    require(classifier.predict([[-4], [4]]).tolist() == [0, 1], "Pipeline classification mismatch")
    raises(NotFittedError, lambda: LinearRegression().predict([[1]]), "Unfitted estimator was accepted")
    raises(ValueError, lambda: model.predict([[1, 2]]), "Wrong feature count was accepted")
    return {"checks": ["linear-regression-oracle", "scaling-classification-pipeline", "unfitted-estimator", "wrong-feature-count"]}

if __name__ == "__main__":
    raise SystemExit(main('scikit-learn', 'sklearn', functional))
