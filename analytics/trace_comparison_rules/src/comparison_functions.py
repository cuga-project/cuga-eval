###############################################################
# Comparison functions: in the pipeline, function will select between them

from collections.abc import Sequence
from typing import List, Union

from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer, util

FUZZY_THRESHOLD = 85.0
SEMANTIC_THRESHOLD = 0.75
NUMERIC_THRESHOLD = 0.05


def deep_equal(x, y):
    """
    Compare two objects using custom rules:
    - numeric: exact equality
    - boolean: exact equality
    - string: equality after stripping spaces
    - list: order-independent equality using previous version
    - tuple: same length, elementwise in order
    - set / frozenset: order-independent, deep comparison of elements
    - dict: recursive deep equality on all keys/values
    - objects with attributes: compare their __dict__ recursively
    - other types: fallback to ==
    """

    # --- Handle None ---
    if x is None or y is None:
        return x is y

    # --- Numeric (int, float, decimal, etc.) except bool ---
    if (
        isinstance(x, (int, float))
        and isinstance(y, (int, float))
        and not isinstance(x, bool)
        and not isinstance(y, bool)
    ):
        return x == y

    # --- Boolean ---
    if isinstance(x, bool) and isinstance(y, bool):
        return x == y

    # --- String ---
    if isinstance(x, str) and isinstance(y, str):
        return x.strip() == y.strip()

    # --- List (order does not matter, multiset semantics) ---
    if isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            return False
        used = [False] * len(y)
        for u in x:
            for i, v in enumerate(y):
                if not used[i] and deep_equal(u, v):
                    used[i] = True
                    break
            else:
                return False
        return True

    # --- Tuple: same length, compare in order ---
    if isinstance(x, tuple) and isinstance(y, tuple):
        if len(x) != len(y):
            return False
        return all(deep_equal(u, v) for u, v in zip(x, y))

    # --- Set / Frozenset: deep comparison without order ---
    if isinstance(x, (set, frozenset)) and isinstance(y, (set, frozenset)):
        if len(x) != len(y):
            return False

        y_list = list(y)
        used = [False] * len(y_list)

        for u in x:
            found = False
            for i, v in enumerate(y_list):
                if not used[i] and deep_equal(u, v):
                    used[i] = True
                    found = True
                    break
            if not found:
                return False

        return True

    # --- Dict / object with subobjects ---
    if isinstance(x, dict) and isinstance(y, dict):
        if x.keys() != y.keys():
            return False
        return all(deep_equal(x[k], y[k]) for k in x)

    # --- Objects with attributes ---
    if type(x) is type(y) and hasattr(x, "__dict__") and hasattr(y, "__dict__"):
        return deep_equal(vars(x), vars(y))

    # --- Fallback to simple equality ---
    return x == y


###############################################################################
def fuzzy_similar(x, y, threshold: float = FUZZY_THRESHOLD) -> bool:
    """
    Compare two fields that can be either:
      - a single string, or
      - a list of strings

    Rules:
    - For strings: use fuzzy similarity with given threshold.
    - For string lists:
        Concatenate strings on each side and compare with fuzzy similarity.
    - For mixed types (str vs list, or non-str items) -> return False.

    :param x: str or list[str]
    :param y: str or list[str]
    :param threshold: similarity threshold in [0, 100]
    :return: True if similarity >= threshold, False otherwise
    """

    # --- String vs String ---
    if isinstance(x, str) and isinstance(y, str):
        score = fuzz.token_set_ratio(x, y)
        # print(score)
        return score >= threshold

    # --- List[str] vs List[str] ---
    if isinstance(x, list) and isinstance(y, list):
        # Length must match
        # if len(x) != len(y):
        #     return False

        # Ensure all elements are strings (or at least stringifiable)
        left = " ".join(str(s) for s in x)
        right = " ".join(str(s) for s in y)

        score = fuzz.WRatio(left, right)
        # print(score)
        return score >= threshold

    # --- Other type combinations are not supported ---
    return False


# **************************************************************************
def semantic_similar(
    x: Union[str, List[str]],
    y: Union[str, List[str]],
    model: SentenceTransformer = SentenceTransformer("sentence-transformers/nli-distilroberta-base-v2"),
    threshold: float = SEMANTIC_THRESHOLD,
) -> bool:
    """
    Compare two fields using semantic similarity from sentence_transformers.

    Supported inputs:
      - x, y both str
      - x, y both list[str]

    Rules:
    - If both are strings:
        Compute semantic similarity and return True if it >= threshold.
    - If both are lists of strings:
        1) If lengths differ -> return False.
        2) Concatenate each list into a single string and compare them semantically.
    - Any other type combination -> return False.

    Similarity:
      - Cosine similarity between embeddings, in [-1, 1].
      - `threshold` should typically be in [0, 1] (e.g., 0.7–0.9).
    """

    # Helper to compute semantic similarity between two texts
    def _semantic_similarity(a: str, b: str) -> float:
        # Encode both texts in one batch for efficiency
        embeddings = model.encode([a, b], convert_to_tensor=True)
        sim = util.cos_sim(embeddings[0], embeddings[1]).item()
        return sim

    # --- String vs String ---
    if isinstance(x, str) and isinstance(y, str):
        sim = _semantic_similarity(x, y)
        # print(sim)
        return sim >= threshold

    # --- List[str] vs List[str] ---
    if isinstance(x, list) and isinstance(y, list):
        # length must match
        # if len(x) != len(y):
        #     return False

        # concatenate elements; you can change the separator if needed
        left = " ".join(str(s) for s in x)
        right = " ".join(str(s) for s in y)

        sim = _semantic_similarity(left, right)
        # print(sim)
        return sim >= threshold

    # --- Unsupported type combinations ---
    return False


#####################################################################
def numeric_similar(x, y, threshold: float = NUMERIC_THRESHOLD, mode: str = "absolute") -> bool:
    """
    Compare two numeric values or two numeric sequences using either absolute or relative tolerance.

    Scalars:
        mode = "absolute" -> |x - y| <= threshold
        mode = "relative" -> |x - y| / max(|x|, |y|) <= threshold

    Sequences (lists/tuples) of the same length:
        mode = "absolute" -> average(|xi - yi|) <= threshold
        mode = "relative" -> average( |xi - yi| / max(|xi|, |yi|) ) <= threshold

    Returns False if:
        - x and y are sequences of different lengths
        - mode is not 'absolute' or 'relative'
    """

    def _is_sequence(obj):
        return isinstance(obj, Sequence) and not isinstance(obj, (str, bytes))

    # --- Case 1: both are sequences (e.g., lists/tuples) ---
    if _is_sequence(x) and _is_sequence(y):
        if len(x) != len(y):
            return False

        n = len(x)
        if n == 0:
            # Two empty sequences: consider them similar
            return True

        if mode == "absolute":
            avg_diff = sum(abs(a - b) for a, b in zip(x, y)) / n
            return avg_diff <= threshold

        if mode == "relative":
            rel_diffs = []
            for a, b in zip(x, y):
                if a == 0 and b == 0:
                    rel_diffs.append(0.0)
                else:
                    denom = max(abs(a), abs(b))
                    rel_diffs.append(abs(a - b) / denom)
            avg_rel_diff = sum(rel_diffs) / n
            return avg_rel_diff <= threshold

        raise ValueError("mode must be 'absolute' or 'relative'")

    # --- Case 2: scalar comparison (original behavior) ---
    if mode == "absolute":
        return abs(x - y) <= threshold

    if mode == "relative":
        if x == 0 and y == 0:
            return True  # both zero
        denom = max(abs(x), abs(y))
        return abs(x - y) / denom <= threshold

    raise ValueError("mode must be 'absolute' or 'relative'")


##############################################################
def same_type_and_length(x, y):
    """
    Return True if:
    1) x and y have the same type
    2) x and y have the same length (if they are sized)

    Otherwise return False.
    """

    # 1) Same type
    if type(x) is not type(y):
        return False

    # 2) Same length — only for objects that support len()
    try:
        return len(x) == len(y)
    except TypeError:
        # If objects do not have length, fall back to: True only if both
        # do NOT support length (e.g., ints, floats) since type already matches
        try:
            len(x)
        except TypeError:
            try:
                len(y)
            except TypeError:
                return True  # both have no length

        return False  # one has len(), the other doesn't


#############################################################
def both_or_none(x, y):
    return (x is None) == (y is None)


###############################################################
# TESTING
if __name__ == "__main__":
    print("Check deep exact comparison")
    print(deep_equal(" a ", "a"))
    print(deep_equal([1, 2, 3], [3, 2, 1]))
    print(deep_equal([1, 2, 3], [4, 3, 2, 1]))
    print(deep_equal([1, 2, 2], [1, 2, 1]))  # maybe a problem
    print("")

    print("Check fuzzy comparison")
    print(fuzzy_similar("New York", "NewYork"))
    print(fuzzy_similar("New York", "York New"))
    print(fuzzy_similar("New York", "New Caledonia"))
    print(fuzzy_similar("New York", "Washington"))
    print(fuzzy_similar("I approve your proposal", "I endorse your proposal"))
    print("")

    print("Check semantic comparison")

    # model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    model = SentenceTransformer("sentence-transformers/nli-distilroberta-base-v2")

    print(semantic_similar("New York", "NewYork", model))
    print(semantic_similar("New York", "York New", model))
    print(semantic_similar("New York", "New Caledonia", model))
    print(semantic_similar("New York", "Washington", model))
    print(semantic_similar("I approve your proposal", "I endorse your proposal", model))
    print("")

    print("Check numeric similarity")
    print(numeric_similar(0.95, 0.92))
    print(numeric_similar(0.85, 0.95))
    print("")

    print("Check same type and length")
    print(same_type_and_length([1, 2, 3], [4, 5, 6]))
    print(same_type_and_length([1, 2], [1, 2, 3]))
    print("")

    print("check existence comparison")
    both_or_none(None, None)
    both_or_none(20, 10)
    both_or_none("x", None)
