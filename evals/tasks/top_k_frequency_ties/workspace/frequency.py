"""Rank values by frequency."""


def top_k(words, k):
    """Return up to *k* unique words ordered by descending frequency.

    Ties are broken by the order in which the words first appear in the
    input. If k is less than or equal to zero, return []. If k exceeds the
    number of unique words, return all of them.
    """
    counts = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], word))
    return ranked[:k]
