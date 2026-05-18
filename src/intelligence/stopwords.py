"""English stopword list.

Bundled inline to avoid runtime downloads (Railway / Pi may not have
network access at boot). The list is conservative — common
function/grammar words plus a handful of OCR-frequent junk tokens.
"""
from __future__ import annotations

ENGLISH_STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all am an and any are aren as at
    be because been before being below between both but by
    can cannot could couldn
    did didn do does doesn doing don down during
    each
    few for from further
    had hadn has hasn have haven having he her here hers herself him himself his how
    i if in into is isn it its itself
    just
    let
    me more most mustn my myself
    needn no nor not now
    of off on once only or other our ours ourselves out over own
    same shan she should shouldn so some such
    than that the their theirs them themselves then there these they this those through to too
    under until up
    very
    was wasn we were weren what when where which while who whom why will with won would wouldn
    you your yours yourself yourselves

    also however therefore thus hence indeed somewhat moreover whereas
    onto upon within without across along around behind beyond near
    one two three four five six seven eight nine ten

    eg ie etc et al cf vs viz
    page pages section chapter figure table note notes
    """.split()
)
