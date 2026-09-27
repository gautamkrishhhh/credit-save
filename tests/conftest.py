import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def categorizer():
    from app.ml.categorizer import Categorizer
    c = Categorizer()
    c.train(evaluate=False)
    return c


@pytest.fixture(scope="session")
def intents():
    from app.ml.nlu import IntentClassifier
    c = IntentClassifier()
    c.train()
    return c


@pytest.fixture()
def db():
    from app.core.db import Database
    return Database(":memory:")
